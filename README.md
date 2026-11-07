# Redistricting

(better name TBD)

Fair-lines redistricting toys: equal-population, contiguous, compact districts built from Census block groups with meshing and optimal-transport methods.

## Toys

**1. State solver.** Pick any state and get equal-population, contiguous, compact districts from Census block groups, computed with a balanced centroidal power diagram. A "how far from fair?" least-change slider morphs the fair plan toward the official map and shows how many people must move.

**2. Borderless US.** The same solver run across the whole country: 435 equal-population districts that ignore state lines.

**3. Draw your own.** Segment-Anything-style drawing: click a block group and a district grows from it. Then hand off with Finish my map, Improve my map or Solve from my seeds, and compare your plan to the official map on a scorecard.

**4. Re-draw the states.** Regroup the borderless districts into 50 new contiguous states. In progress.

## How it works

Block-group adjacency graph, then a recursive coordinate bisection (RCB) seed, then Lloyd relaxation with optimal-transport balancing (damped Newton on the power-diagram weights), then contiguity repair, then boundary refinement (Fiduccia-Mattheyses style moves) with a penalty for splitting counties.

## What "fair" means here

Equal population, contiguous, compact and county-respecting. No party, race or incumbent data enters the solver. Voting Rights Act compliance and communities of interest are out of scope.

## Data

2020 Census block groups (population and population-weighted centroids). Election data used today: 2016 and 2020 presidential returns from precinct results disaggregated to blocks, plus 2024 presidential county totals spread over block groups by the 2020 pattern. Planned: 2024 precinct-level, and 2026 when certified. Full provenance is in the toy's `SOURCES.md` (see `toys/README.md`).

## Site and deployment

`site/` is a static, framework-free prototype site (landing page plus the toys), deployed by `.github/workflows/pages.yml` on every push to `main` and on manual dispatch.

To turn it on once: repository Settings, Pages, Build and deployment, Source = GitHub Actions. Then run the "Deploy site to GitHub Pages" workflow (or push to `main`). The URL will be https://domattioli.github.io/redistricting/.

Preview locally: `python -m http.server -d site` and open http://localhost:8000/.

Layout: `site/fair-lines/` (state solver and borderless US, with `data/` for the 51 states plus `national.json`, about 9 MB, the largest file), `site/draw/` (draw tool, loads `../fair-lines/data/XX.json` for `?state=XX`), `site/regions/`. The largest file is well under GitHub's 50 MB warning size, so no Git LFS is used. If a future data file passes 50 MB, keep it out of git (`.gitignore`) and fetch it at deploy time instead.

Refreshing from research: `python scripts/sync_from_research.py /path/to/SegmentAnyMesh` copies the built pages, data, solver package (`redistricting/`, `tests/`) and `docs/METHOD.md`, and records the source commit in `site/SYNC.json`. It is idempotent and read-only on the source. The synced files are generated copies: edit them in SegmentAnyMesh, not here, until migration is complete.

Check the site: `python scripts/verify_site.py` (needs Playwright with Chromium; set `PW_CHROMIUM` to a browser binary if needed). It loads every page, runs a PA solve and a draw Finish, and fails on any console error. Python tests: `pytest tests` (needs numpy, scipy, shapely).

## Links

- Live demo: https://domattioli.github.io/redistricting/ (pending enable, see "Site and deployment")
- Write-up: [TBD]
- Origin: research in the SegmentAnyMesh repo (`research/redistricting_*`, `redistricting/`)
