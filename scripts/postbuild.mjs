import fs from 'node:fs';

// WordPress robots.txt points at /sitemap_index.xml; Astro emits
// /sitemap-index.xml. Keep both names available without a runtime.
const dist = new URL('../dist/', import.meta.url);
const source = new URL('sitemap-index.xml', dist);
const target = new URL('sitemap_index.xml', dist);
if (fs.existsSync(source)) fs.copyFileSync(source, target);
