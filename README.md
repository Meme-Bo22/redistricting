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

## Links

- Live demo: [TBD]
- Write-up: [TBD]
- Origin: research in the SegmentAnyMesh repo (`research/redistricting_*`, `redistricting/`)
