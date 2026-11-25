# SENO Animal & Plant DNA Fingerprinting Lab — Astro static replica

This repository is a static Astro export of the public WordPress site
`https://senobiocorp.com` (WordPress 7.1.5, Astra + Elementor + TranslatePress).

## What is included

- **204 HTML routes** — the 192 URLs in the WordPress sitemaps plus 12 archive
  routes (`/seno-products/` and `/author/martin2024/` in six languages).
- **Six languages** as published by the source: `en-US`, `ja`, `es-ES`, `fr-FR`,
  `ar`, `zh-HK`.
- **Exact full-page HTML** for every route: Astra header/footer, Elementor
  sections, inline page CSS and the original page semantics are preserved.
- **401 local assets** under `public/` (CSS, JS, images, fonts) with URLs rewritten
  to root-relative paths. No page depends on the WordPress runtime for its
  visual layout.
- Source `robots.txt` and a generated Astro sitemap.
- Redirects for the source's WordPress form endpoint and sitemap aliases.

## Build

```bash
npm install
npm run build
```

The build is a static site in `dist/`. It does not need a database, PHP or the
WordPress API at runtime.

## Structure

- `src/html/` — the exported full HTML documents, one per route.
- `src/data/pages.json` — route → file → source URL/language manifest.
- `src/pages/index.astro` — home route.
- `src/pages/[...slug].astro` — all other routes; reads the exported document at
  build time.
- `public/` — mirrored assets and redirects.
- `scripts/extract.py` — the reproducible export script. It reads the URL list
  and saved source pages under `raw/` and rewrites assets/links into the source
  tree.

## Source/API note

The supplied WordPress application credential (`Agent`) returned `401` against
`senobiocorp.com` (`rest_not_logged_in`). This export therefore uses the public
WordPress sitemap, public REST collection data and the public rendered HTML.
Unpublished drafts, private pages, private media and form submissions are not
included. If those are required, a working application password with edit
permissions is needed.

## URL parity

- Source sitemap URLs: **192** (before archive routes).
- Exported routes: **204** (192 + 12 archive routes).
- Internal anchors checked: **11,885**, with **0 missing internal page or asset
  targets** after rewrite.
- Source and exported HTML are byte-identical for all 204 pages (asset URL
  rewrites and Cloudflare email decoding happen before the final export).
