# Toys

Built, runnable toys. Serve `site/` locally (`python -m http.server -d site 8000`, then http://localhost:8000).

- **State solver and Borderless US (Fair Lines)**: equal-population, contiguous, compact districts for any state, or all 435 across the country. Here: `site/fair-lines/index.html`. Upstream source: SegmentAnyMesh `research/redistricting_toy/`.
- **Draw your own**: click a block group and a district grows from it; compare to the official map. Here: `site/draw/index.html`. Upstream source: SegmentAnyMesh `research/redistricting_draw/`.
- **Re-draw the states**: regroup the borderless districts into 50 new contiguous states (in progress). Here: `site/regions/index.html`. Upstream source: SegmentAnyMesh `research/redistricting_regions/`.
- **Solver package (Python)**: `redistricting/` here. Upstream source: SegmentAnyMesh `redistricting/`.

The files here are synced copies (see README, "Site layout and sync"); edit upstream in SegmentAnyMesh.

To put the toys on your own website see [`embed/README.md`](../embed/README.md).
