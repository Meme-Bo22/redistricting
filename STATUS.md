# Status

## Works
- State solver for all 50 states plus DC, 2020 block groups, contiguous plans, runs in about a minute for the whole country.
- Least-change slider against the official 2026 maps.
- Borderless 435-district US plan.
- Draw-your-own prototype: click-to-grow, county-aware selection, Finish / Improve / Solve-from-seeds, scorecard.
- Optional edge penalties in the draw tool: state lines, rivers and lakes, commuting zones.

## Site
- `site/` is a self-contained static prototype (copy the folder; no hosting service assumed) (landing, Fair Lines, Draw, Re-draw the states), synced from SegmentAnyMesh commit recorded in `site/SYNC.json`. Smoke-tested with Playwright (`scripts/verify_site.py`): zero console errors, PA solve and draw Finish both run.
- Embedding: `site/` copies as a unit under any subpath; all toys read shared data from `site/data/` by default and from `window.REDISTRICTING_DATA_BASE` or `?data-base=` when set (for example a jsDelivr URL). See `embed/README.md` and `embed/manifest.json`. The jsDelivr URL could not be fetched from the build sandbox (proxy 403), so only a stand-in CORS server was tested.
- Draw page only ships constraint layers (`site/data/layers/`) for states present in SegmentAnyMesh `layers/`; the "region" datasets (`?region=XX`) ship only for CA, TX and PA (`site/data/regions/`) because the rest are gitignored upstream.

## In progress
- Re-draw the states: grouping borderless districts into 50 contiguous new states.
- Multi-seed runs for the headline results.
- Election data moving to 2024 precinct-level, then 2026 when certified.
- Migration of code out of SegmentAnyMesh: pages, data and solver package are currently synced copies (`scripts/sync_from_research.py`); builders (`build_*.py`), the benchmark and research scripts are not copied yet.

## Known limits
- Block-group resolution gives about 0.2% worst population deviation; the legal standard for congressional maps is 0 to 1 person (needs block-level data).
- Compactness in the draw tool is a raster estimate (640 px); compare columns within the tool, not against the Python audit.
- Results are single-seed; multi-seed runs are pending.
- Election data vintage: 2016 and 2020 are sub-county estimates on 2010 geography carried to 2020 block groups; 2024 is a county-level swing applied to the 2020 pattern, not precinct data.
- Official districts are assigned to block groups by centre point, so the official map is only within about 2% of equal on these units.

## Negative result
Density-adapted meshing (a population-size-function triangle mesh partitioned with METIS) did not help: plans were less compact than partitioning the block-group graph directly, in every state tested. Boundary-length edge weighting did help (about +0.07 Polsby-Popper), and it works on the block-group graph without any mesh.

## Decisions needed
- Licence: this repo is Apache-2.0, but the origin research in SegmentAnyMesh is PolyForm Noncommercial 1.0.0. Confirm licence intent: the synced `redistricting/` package and pages are already copied here from the PolyForm-licensed repo. Some data inputs also carry their own terms (election arrays CC BY-SA 4.0, no resale; the enacted-district source states no licence).
- Final project name.
