# Handoff — 2026-11-07

## State
- This repo (`development` @ a89ac65): toys packaged under `site/` (fair-lines, draw, regions), shared `site/data/` (39 MB), embed contract in `embed/manifest.json` + `embed/README.md`. No GitHub Pages; the owner's portfolio-site bot builds the toys from `site/`.
- Research upstream: SegmentAnyMesh `development` @ 9014f52 (`redistricting/`, `research/redistricting_*`). Compact objective is default (50-state mean Polsby-Popper 0.421→0.472, county splits 866→782).
- Sync: `scripts/sync_from_research.py`; verify: `scripts/verify_site.py` (PW_CHROMIUM env).

## Unverified
- jsDelivr CDN data path (`?data-base=https://cdn.jsdelivr.net/gh/domattioli/redistricting@<commit>/site/data/`) — tested only locally; `curl -I` once.

## Known gaps
- Fast engine, `national.json`, regions data not compact-aware / lack `blen`.
- AK/HI zero-population bridge trap in FM refinement.
- Seed ensembles + least-change stats predate compact plans.
- 2024 precinct + 2026 House overlays downloaded (SegmentAnyMesh `research/redistricting_elections/`) but not wired into toys.
- `docs/assets/redistricting_all_states.png` in SegmentAnyMesh is stale.
- `draw` test zoom step flaky.

## Next
1. Integration pass: compaction in fast engine → toy (jittered-RCB start), recompute national plan, election overlays, `blen` in `build_layers.py --regions`, resync here, rerun ensembles.
2. One-at-a-time brainstorm: least-change optimiser; compactness measure choice; what the toy shows.
Open: smoothing fills vs lines; strict vs max(0.1%, start) balance; additive vs multiplicative penalty; "∞" state-line setting; licence (Apache vs PolyForm; data CC BY-SA); fun project name.
