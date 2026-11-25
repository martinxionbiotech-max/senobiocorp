#!/usr/bin/env python3
"""Export the public senobiocorp.com WordPress pages into a static Astro source tree.

The site is crawled from its public sitemap.  Each source page is kept as a
complete HTML document (so the Astra/Elementor layout is preserved), while
same-origin assets are mirrored under public/ and URLs are rewritten to
root-relative paths.  This is deliberately a *content/asset* export, not a
WordPress runtime: forms and WP-only endpoints are left as source markup but
are not required for navigation.

Run: python3 scripts/extract.py
"""
from __future__ import annotations

import html
import json
import mimetypes
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://senobiocorp.com"
ROOT = Path(__file__).resolve().parents[1]
RAW_URLS = ROOT / "raw" / "urls.txt"
RAW_HTML = ROOT / "raw" / "html"
OUT_HTML = ROOT / "src" / "html"
PUBLIC = ROOT / "public"
MANIFEST = ROOT / "src" / "data" / "pages.json"
ASSET_LOG = ROOT / "raw" / "assets.tsv"
UA = "Mozilla/5.0 (compatible; SENO-static-export/1.0)"
MAX_ASSET_BYTES = 60 * 1024 * 1024

ASSET_PREFIXES = ("/wp-content/", "/wp-includes/")
# WP-only head resources that would point at a non-existent REST/feed endpoint
# in the static output.  Visible page links are left alone.
WP_HEAD_TAG_RE = re.compile(
    r"<link\b[^>]*(?:wp-json|xmlrpc|wlwmanifest|EditURI|api\.w\.org|"
    r"application/rss\+xml|application/atom\+xml|oembed)[^>]*>",
    re.I,
)
GENERATOR_RE = re.compile(r"<meta\b[^>]*name=[\"']generator[\"'][^>]*>", re.I)


def page_key(url: str) -> str:
    p = urllib.parse.urlsplit(url).path.strip("/")
    return "home" if not p else p.replace("/", "__")


def route_path(url: str) -> str:
    p = urllib.parse.urlsplit(url).path or "/"
    return p


def is_asset_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ASSET_PREFIXES)


def local_path(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path)


def same_origin(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host in {"senobiocorp.com", "www.senobiocorp.com"}


class Assets:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.rows: list[tuple[str, int, str]] = []
        self.failed: list[tuple[str, str]] = []

    def local(self, url: str, referer: str) -> str | None:
        """Download an asset and return its local root-relative path."""
        if not url or url.startswith(("data:", "blob:", "mailto:", "tel:", "javascript:", "#")):
            return None
        url = html.unescape(url).strip()
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            url = urllib.parse.urljoin(BASE, url)
        if not same_origin(url):
            return None
        parsed = urllib.parse.urlsplit(url)
        path = local_path(url)
        if not is_asset_path(path):
            return None
        # Keep the on-disk filename free of query strings; query variants of
        # the same path are treated as one asset.
        key = path
        if key in self.seen:
            return path
        self.seen.add(key)
        dest = PUBLIC / path.lstrip("/")
        if dest.exists() and dest.stat().st_size > 0:
            self.rows.append((path, dest.stat().st_size, "cached"))
            return path
        try:
            # Source HTML contains unescaped CJK filenames; encode the path
            # before handing it to urllib, while keeping the local filename as
            # the decoded path.
            parsed = urllib.parse.urlsplit(url)
            request_url = urllib.parse.urlunsplit((
                parsed.scheme,
                parsed.netloc,
                urllib.parse.quote(parsed.path, safe="/%:@"),
                parsed.query,
                parsed.fragment,
            ))
            req = urllib.request.Request(request_url, headers={"User-Agent": UA, "Referer": referer})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read(MAX_ASSET_BYTES + 1)
                ctype = r.headers.get("content-type", "")
            if len(data) > MAX_ASSET_BYTES:
                self.failed.append((url, "too large"))
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            if "text/css" in ctype or path.endswith(".css"):
                text = data.decode("utf-8", "replace")
                text = rewrite_css(text, url, self)
                dest.write_text(text, encoding="utf-8")
            else:
                dest.write_bytes(data)
            self.rows.append((path, len(data), ctype))
            return path
        except Exception as exc:
            self.failed.append((url, str(exc)))
            return None


def rewrite_css(text: str, css_url: str, assets: Assets) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(2).strip().strip("\"'")
        if raw.startswith(("data:", "#")):
            return match.group(0)
        absolute = urllib.parse.urljoin(css_url, raw)
        local = assets.local(absolute, css_url)
        return f"url({local or absolute})"

    # url(...) covers fonts, background images and CSS imports.
    return re.sub(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", repl, text, flags=re.I)


def rewrite_srcset(value: str, page_url: str, assets: Assets) -> str:
    out: list[str] = []
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        absolute = urllib.parse.urljoin(page_url, html.unescape(bits[0]))
        if same_origin(absolute):
            local = assets.local(absolute, page_url)
            url = local or urllib.parse.urlsplit(absolute).path
        else:
            url = bits[0]
        out.append(" ".join([url] + bits[1:]))
    return ", ".join(out)


def rewrite_style(value: str, page_url: str, assets: Assets) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(2).strip().strip("\"'")
        if raw.startswith(("data:", "#")):
            return match.group(0)
        absolute = urllib.parse.urljoin(page_url, raw)
        local = assets.local(absolute, page_url)
        return f"url({local or absolute})"

    return re.sub(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", repl, value, flags=re.I)


def decode_cfemail(hex_value: str) -> str | None:
    try:
        raw = bytes.fromhex(hex_value)
        key = raw[0]
        return "".join(chr(b ^ key) for b in raw[1:])
    except Exception:
        return None


def replace_cfemail(html_text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        full = match.group(0)
        raw_hex = re.search(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', full)
        email = decode_cfemail(raw_hex.group(1)) if raw_hex else None
        if not email:
            return full
        safe = html.escape(email, quote=True)
        # The Cloudflare email decoder removes the wrapper anchor and leaves
        # plain text in the parent paragraph.  Matching that DOM is important
        # for line-height/pixel parity in the cloned footer.
        return safe

    html_text = re.sub(
        r'<a\b[^>]*data-cfemail=["\']([0-9a-fA-F]+)["\'][^>]*>.*?</a>',
        repl,
        html_text,
        flags=re.I | re.S,
    )
    html_text = re.sub(
        r'<script\b[^>]*src=["\'][^"\']*email-decode[^"\']*["\'][^>]*>\s*</script>',
        "",
        html_text,
        flags=re.I,
    )
    return html_text


def absolutize_head_links(text: str) -> str:
    """Keep canonical/hreflang absolute even though navigation is root-relative."""
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if not re.search(r'rel=["\'][^"\']*(?:canonical|alternate)[^"\']*["\']', tag, re.I):
            return tag
        return re.sub(
            r'(href=["\'])(/[^"\']*)',
            lambda m: m.group(1) + BASE + m.group(2),
            tag,
        )
    return re.sub(r'<link\b[^>]*>', repl, text, flags=re.I)

def rewrite_html_document(text: str, page_url: str, assets: Assets) -> str:
    text = replace_cfemail(text)
    text = WP_HEAD_TAG_RE.sub("", text)
    text = GENERATOR_RE.sub("", text)

    # srcset / style attributes first, before generic src/href replacement.
    text = re.sub(
        r'(\bsrcset=["\'])([^"\']+)(["\'])',
        lambda m: m.group(1) + rewrite_srcset(m.group(2), page_url, assets) + m.group(3),
        text,
        flags=re.I,
    )
    text = re.sub(
        r'(\bstyle=["\'])([^"\']*)(["\'])',
        lambda m: m.group(1) + rewrite_style(m.group(2), page_url, assets) + m.group(3),
        text,
        flags=re.I,
    )

    # Rewrite URL-bearing HTML attributes.  Query strings are kept for page
    # links but dropped for mirrored assets.
    attr_re = re.compile(
        r'(\b(?:href|src|data-src|data-lazy-src|data-bg|poster)=["\'])([^"\']+)(["\'])',
        re.I,
    )

    def attr_repl(match: re.Match[str]) -> str:
        raw = html.unescape(match.group(2)).strip()
        if raw.startswith(("data:", "blob:", "mailto:", "tel:", "javascript:", "#")):
            return match.group(0)
        absolute = urllib.parse.urljoin(page_url, raw)
        if not same_origin(absolute):
            return match.group(0)
        parsed = urllib.parse.urlsplit(absolute)
        if is_asset_path(parsed.path):
            local = assets.local(absolute, page_url)
            return match.group(1) + (local or parsed.path) + match.group(3)
        # Internal page link / canonical / hreflang: root-relative, preserving
        # the query string for search or tracked links.
        path = parsed.path or "/"
        query = ("?" + parsed.query) if parsed.query else ""
        return match.group(1) + path + query + match.group(3)

    text = attr_re.sub(attr_repl, text)

    # Inline <style> blocks can contain absolute background/font URLs.
    def style_repl(match: re.Match[str]) -> str:
        return "<style" + match.group(1) + ">" + rewrite_css(match.group(2), page_url, assets) + "</style>"

    text = re.sub(r"<style([^>]*)>([\s\S]*?)</style>", style_repl, text, flags=re.I)
    return absolutize_head_links(text)


def main() -> int:
    urls = [line.strip() for line in RAW_URLS.read_text().splitlines() if line.strip()]
    OUT_HTML.mkdir(parents=True, exist_ok=True)
    (ROOT / "src" / "data").mkdir(parents=True, exist_ok=True)
    assets = Assets()
    manifest = []
    missing = []
    for i, url in enumerate(urls, 1):
        key = page_key(url)
        source = RAW_HTML / f"{key}.html"
        if not source.exists():
            missing.append((url, str(source)))
            continue
        text = source.read_text(errors="ignore")
        text = rewrite_html_document(text, url, assets)
        (OUT_HTML / f"{key}.html").write_text(text, encoding="utf-8")
        lang = re.search(r'<html[^>]*\blang=["\']([^"\']+)', text, re.I)
        title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        manifest.append(
            {
                "path": route_path(url),
                "file": f"{key}.html",
                "url": url,
                "lang": lang.group(1) if lang else "",
                "title": html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else "",
            }
        )
        if i % 25 == 0:
            print(f"pages {i}/{len(urls)} assets {len(assets.seen)}", flush=True)

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ASSET_LOG.write_text(
        "\n".join(f"{p}\t{n}\t{t}" for p, n, t in sorted(assets.rows)) + "\n",
        encoding="utf-8",
    )
    print(f"pages={len(manifest)} assets={len(assets.rows)} failed={len(assets.failed)} missing={len(missing)}")
    if assets.failed:
        print("failed sample:", assets.failed[:8])
    if missing:
        print("missing sample:", missing[:8])
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
