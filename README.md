# Redistricting

(better name TBD)

Fair-lines redistricting toys: equal-population, contiguous, compact districts built from Census block groups with meshing and optimal-transport methods.

## Run locally

No build step, just Python 3:

```
git clone https://github.com/domattioli/redistricting && cd redistricting && python -m http.server -d site 8000
```

Then open http://localhost:8000. The tools are the static pages in `site/` ([site/index.html](site/index.html) is the landing page).

## Embed in your site (see embed/README.md)

`site/` is self-contained and copies as a unit into any static site, under any subpath. Copy it, then link or iframe `fair-lines/`, `draw/` and `regions/`; or skip the 39 MB of data and point the toys at jsDelivr with `?data-base=`. Copy-paste iframe snippets, the CSP notes and the three recipes are in [embed/README.md](embed/README.md); a machine-readable description is in [embed/manifest.json](embed/manifest.json).

## Toys

**1. State solver** ([`site/fair-lines/index.html`](site/fair-lines/index.html)). Pick any state and get equal-population, contiguous, compact districts from Census block groups, computed with a balanced centroidal power diagram. A "how far from fair?" least-change slider morphs the fair plan toward the official map and shows how many people must move.

**2. Borderless US** ([`site/fair-lines/index.html`](site/fair-lines/index.html), national view). The same solver run across the whole country: 435 equal-population districts that ignore state lines.

**3. Draw your own** ([`site/draw/index.html`](site/draw/index.html)). Segment-Anything-style drawing: click a block group and a district grows from it. Then hand off with Finish my map, Improve my map or Solve from my seeds, and compare your plan to the official map on a scorecard.

**4. Re-draw the states** ([`site/regions/index.html`](site/regions/index.html)). Regroup the borderless districts into 50 new contiguous states. In progress.

## How it works

Block-group adjacency graph, then a recursive coordinate bisection (RCB) seed, then Lloyd relaxation with optimal-transport balancing (damped Newton on the power-diagram weights), then contiguity repair, then boundary refinement (Fiduccia-Mattheyses style moves) with a penalty for splitting counties.

## What "fair" means here

Equal population, contiguous, compact and county-respecting. No party, race or incumbent data enters the solver. Voting Rights Act compliance and communities of interest are out of scope.

## Data

2020 Census block groups (population and population-weighted centroids). Election data used today: 2016 and 2020 presidential returns from precinct results disaggregated to blocks, plus 2024 presidential county totals spread over block groups by the 2020 pattern. Planned: 2024 precinct-level, and 2026 when certified. Full provenance is in the toy's `SOURCES.md` (see `toys/README.md`).

## Site layout and sync

`site/` is a static, framework-free prototype site (landing page plus the toys). Layout: `site/fair-lines/`, `site/draw/`, `site/regions/` (one `index.html` each), `site/data/` (all shared JSON, about 39 MB: the 51 state files, `national.json` at 9.3 MB, `us.json`, `us_sizefn.json`, `layers/`, `regions/`) and `site/img/`. Pages read data from `window.REDISTRICTING_DATA_BASE`, else `?data-base=`, else `../data/`. No file is near GitHub's 50 MB warning size, so no Git LFS is used; if a future data file passes it, keep it out of git and fetch it at build time.

Refreshing from research: `python scripts/sync_from_research.py /path/to/SegmentAnyMesh` copies the built pages, data, solver package (`redistricting/`, `tests/`) and `docs/METHOD.md`, rewrites the pages' data fetches to the data-base config (it aborts if the upstream strings changed), and records the source commit in `site/SYNC.json`. It is idempotent and read-only on the source. The synced files are generated copies: edit them in SegmentAnyMesh, not here, until migration is complete.

Check the site: `python scripts/verify_site.py` (needs Playwright with Chromium; set `PW_CHROMIUM` to a browser binary if needed). It serves `site/` under the subpath `/projects/redistricting/`, loads every page, runs a PA solve and a draw Finish, checks the `REDISTRICTING_DATA_BASE` / `?data-base=` override against a second server, checks the iframe snippets, and fails on any console error or 404. Python tests: `pytest tests` (needs numpy, scipy, shapely).

## Links

- Write-up: [TBD]
- Origin: research in the SegmentAnyMesh repo (`research/redistricting_*`, `redistricting/`)
