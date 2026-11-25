# Map audit: every stored map on real borders

## In short (for people)

1272 stored maps checked across 44 states. Every one has each district in one piece on real Census borders and within 1% of equal population.

---

## For AI agents (detailed)

`python -m redistricting_addons.audit_maps` (module docstring). Scheme = file name after the state code.

| Source | Scheme | Maps | Pass | States | States failing |
| --- | --- | --: | --: | --: | --- |
| ensembles | `census` | 132 | 132 | 44 |  |
| ensembles | `county20.census` | 132 | 132 | 44 |  |
| ensembles | `huc20.census` | 132 | 132 | 44 |  |
| ensembles | `nature20.census` | 132 | 132 | 44 |  |
| ensembles | `school20.census` | 132 | 132 | 44 |  |
| ensembles | `town20.census` | 132 | 132 | 44 |  |
| ensembles | `zip20.census` | 132 | 132 | 44 |  |
| plans | `official.census` | 44 | 44 | 44 |  |
| plans | `solver.census` | 44 | 44 | 44 |  |
| sci | `adjusted.census` | 43 | 43 | 43 |  |
| sci | `adjusted.compact.census` | 43 | 43 | 43 |  |
| sci | `raw.census` | 43 | 43 | 43 |  |
| sci | `raw.compact.census` | 43 | 43 | 43 |  |
| sci | `zcta.census` | 44 | 44 | 44 |  |
| sci | `zcta.free.census` | 44 | 44 | 44 |  |
