# Embedding the toys in your own site

The three toys are static pages under `site/`. They need no build step, no server code and no GitHub Pages. Machine-readable details are in [`manifest.json`](manifest.json).

```
site/
  index.html            optional landing page
  fair-lines/index.html state solver + borderless US   (uses a Blob Web Worker)
  draw/index.html       draw your own districts
  regions/index.html    re-draw the states             (self-contained, no data fetch)
  data/                 shared JSON, 39.3 MB: <ST>.json x51, national.json, us.json, us_sizefn.json,
                        layers/<ST>.json (draw), regions/<ST>.json (draw)
  img/                  screenshots
```

Every URL inside `site/` is relative (no leading slash), so the folder works under any mount path such as `/projects/redistricting/`. `scripts/verify_site.py` tests exactly that.

## The one data setting

All fetches go through one base URL, resolved in this order:

1. `?data-base=<url>` query parameter on the toy's URL (the only form that works from outside an iframe)
2. `window.REDISTRICTING_DATA_BASE`, set by a script that runs before the toy's own script
3. default `../data/`, relative to the toy page, i.e. `site/data/`

A trailing slash is added if missing. An absolute base must send CORS headers (`Access-Control-Allow-Origin: *`); jsDelivr and most object stores do.

## Recipe (a): copy `site/` into your static dir

Copy the whole folder, keeping `data/` next to the toy folders.

```
cp -r site  <your-site>/public/projects/redistricting      # Astro/Next public/, Hugo static/, Eleventy passthrough, ...
```

Then link or iframe each toy:

```html
<a href="/projects/redistricting/fair-lines/">Fair Lines</a>
<a href="/projects/redistricting/draw/">Draw your own</a>
<a href="/projects/redistricting/regions/">Re-draw the states</a>
```

```html
<iframe src="/projects/redistricting/fair-lines/#PA" title="Fair Lines: equal-population districts"
        width="100%" style="aspect-ratio:4/3; min-height:640px; border:0" loading="lazy"
        sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer"></iframe>

<iframe src="/projects/redistricting/draw/" title="Draw your own districts"
        width="100%" style="aspect-ratio:4/3; min-height:720px; border:0" loading="lazy"
        sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer"></iframe>

<iframe src="/projects/redistricting/regions/" title="Re-draw the states"
        width="100%" style="aspect-ratio:4/3; min-height:640px; border:0" loading="lazy"
        sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer"></iframe>
```

If your generator rewrites or hashes static files, exclude this folder from processing; the pages are single-file and contain inline script and style that must stay intact.

## Recipe (b): iframe the pages, data from jsDelivr

Host the pages yourself but leave out the 39 MB of data: `rsync -a --exclude data site/ <dest>/`. (The pages cannot be iframed from jsDelivr itself, which serves HTML as plain text.) Point the toys at jsDelivr with the query parameter:

```html
<iframe src="/projects/redistricting/fair-lines/?data-base=https://cdn.jsdelivr.net/gh/domattioli/redistricting@COMMIT_OR_TAG/site/data/#PA"
        title="Fair Lines" width="100%" style="aspect-ratio:4/3; min-height:640px; border:0" loading="lazy"
        sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer"></iframe>

<iframe src="/projects/redistricting/draw/?data-base=https://cdn.jsdelivr.net/gh/domattioli/redistricting@COMMIT_OR_TAG/site/data/&state=OH"
        title="Draw your own districts" width="100%" style="aspect-ratio:4/3; min-height:720px; border:0" loading="lazy"
        sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer"></iframe>
```

`regions/` needs no data. To set it once for a toy page you serve yourself, put this before the toy's script instead: `<script>window.REDISTRICTING_DATA_BASE = "https://cdn.jsdelivr.net/gh/domattioli/redistricting@COMMIT_OR_TAG/site/data/";</script>`.

Replace `COMMIT_OR_TAG` with a full commit hash or a tag. Do not use a branch name in production: jsDelivr caches branch URLs for up to 12 hours. Check a pin with `curl -I https://cdn.jsdelivr.net/gh/domattioli/redistricting@COMMIT_OR_TAG/site/data/us.json` (expect 200 and `access-control-allow-origin: *`). The largest file, `national.json`, is 9.3 MB; jsDelivr's documented per-file limit for GitHub is 20 MB.

Status: the jsDelivr URL was not reachable from the environment this repo was prepared in (outbound proxy returned 403), so the CDN path was only exercised against a CORS-enabled local server standing in for the CDN. The repository is public, which jsDelivr requires.

## Recipe (c): link out

If you serve nothing, link to the repository and let visitors run it locally (`python -m http.server -d site 8000`):

```html
<a href="https://github.com/domattioli/redistricting#run-locally">Redistricting toys (source and run instructions)</a>
```

## Iframe attributes: why these

- `sandbox="allow-scripts allow-same-origin"`: scripts are required; same-origin is required so the page can fetch its data from your origin and so the Blob Web Worker (national solve) starts. The toys open no popups, downloads, forms, storage or top-level navigation, so none of those sandbox tokens are needed. Note that scripts plus same-origin on a same-origin page lets the framed page remove its own sandbox, so the sandbox only protects when the toys are hosted on a different origin than your site (recipe b with the pages on a separate subdomain).
- `allow`: no Permissions-Policy features (camera, geolocation, fullscreen, ...) are used, so omit it.
- `referrerpolicy="no-referrer"`: nothing needs the referrer.
- Height: use `min-height` as above; the pages are fixed-layout dashboards, not auto-sizing, so there is no `postMessage` resize protocol.
- Both recipes above are exercised by `scripts/verify_site.py` (same-origin host, and a cross-origin host with `?data-base=`).

## Content-Security-Policy

If your site sets a CSP, the framed pages need:

- `script-src 'unsafe-inline'` and `style-src 'unsafe-inline'` (single-file pages with inline script/style)
- `worker-src blob:` (fair-lines only; the draw and regions toys use no workers)
- `img-src data:` (fair-lines national size overlay is a data URI)
- `connect-src 'self'` plus `https://cdn.jsdelivr.net` if you use the CDN base
- optional: `style-src https://fonts.googleapis.com` and `font-src https://fonts.gstatic.com` for the web fonts; without them the pages fall back to system fonts. These are the only other external requests; there is no analytics or tracking.
- `frame-src` / `child-src` on the host page allowing the origin that serves the toys; the toys set no `X-Frame-Options` or `frame-ancestors`, so do not add one on the server that hosts them.

## Notes

- Sizes: `site/` is 42.4 MB, of which `site/data/` is 39.3 MB. Toy pages are 0.2 MB (fair-lines), 0.9 MB (draw, includes Pennsylvania) and 0.6 MB (regions).
- Deep links: `fair-lines/#PA` opens a state (any two-letter code); `draw/?state=OH` and `draw/?region=PA` load from the data base. Pennsylvania in `draw/` is embedded and needs no fetch.
- Refresh after an upstream change: `python scripts/sync_from_research.py /path/to/SegmentAnyMesh`, then `python scripts/verify_site.py`.
