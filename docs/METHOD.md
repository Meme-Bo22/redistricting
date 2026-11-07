# `redistricting`: fair congressional districts by meshing science

<p align="center"><img src="assets/redistricting_all_states.png" width="900" alt="Generated congressional districts for all 50 states"/></p>

A congressional plan is a **domain decomposition**: split a domain into *k*
subdomains with equal load (population), small interfaces (compact districts)
and no disconnected pieces (contiguity). That is the same problem as
partitioning an unstructured mesh across MPI ranks, for example ADCIRC's
`adcprep` split of a coastal mesh. `redistricting` applies the standard meshing
tools to Census population:

| Step | Meshing technique | Redistricting role |
|---|---|---|
| 1. Population mesh | Delaunay triangulation of block-group centroids, edges pruned to the state outline, components re-bridged by a Kruskal spanning forest | Adjacency graph that follows land; islands are joined by their shortest water crossing ("contiguous by water") |
| 2. Seed | Recursive coordinate bisection (RCB) along principal axes | Deterministic, balanced start (no random draw that someone could cherry-pick) |
| 3. Balanced geodesic CVT | Lloyd relaxation: power-diagram assignment, then centroid update. Distances run along the mesh (Dijkstra) | Compact, equal-population districts that go around bays and lakes, not across them |
| 4. Capacity constraint | Damped Newton on the semi-discrete transport dual. The Jacobian is a district-graph Laplacian (diffusion load balancing) | Every district gets about P/k people |
| 5. Contiguity | Connected components over the mesh graph | Detached pieces join the neighbour they share the most edges with |
| 6. Refinement | Batched Fiduccia–Mattheyses boundary moves (as in METIS) | Exact balance to block-group granularity; cheapest moves by moment of inertia, with a penalty for each new county split; a move that would disconnect a district is never taken |

**Novelty: none claimed.** Every step above is an established method (see
References). Balanced centroidal power diagrams for districting go back to
Hess et al. (1965) and Cohen-Addad, Klein & Young (2018), and capacitated
p-median models on network distances come from location science. This
package is a neutral baseline for comparison, not a new algorithm.

**What "fair" means here.** The plan is a function of population counts,
their locations and the state outline. **No** election results, party
registration, incumbent addresses, race or ethnicity data enter the process,
so the plan cannot be tuned for a partisan or racial outcome. The seed is
fixed per state (its FIPS code) and the default start is deterministic (RCB), so anyone can rerun the generator and get the
same plan. The audit reports the neutral criteria that courts and commissions
use: population deviation, contiguity, Polsby-Popper, Reock and county splits.

## Usage

```bash
pip install -e ".[districts]"                  # numpy, scipy, shapely>=2.1, matplotlib
python -m redistricting --state PA             # one state
python -m redistricting --all --out plans/     # all 50 states (about a minute)
python -m redistricting --state TX --pop-year 2010                    # 2010 population instead of 2020
python -m redistricting --state PA --init random --seed 7            # random start (seed ensembles)
python -m redistricting --state OH --districts 33                    # e.g. a state senate
```

```python
from redistricting import generate_plan
plan = generate_plan("MI")                 # 13 seats (2020 apportionment)
plan.stats.max_abs_deviation_pct, plan.stats.mean_polsby_popper
plan.write("plans/")                       # assignment.csv, districts.geojson, stats.json
plan.write_fort14("MI_population.14")      # the population mesh, loadable by CHILmesh
```

Each `out/<ST>/` directory holds:

- `assignment.csv`: block-group GEOID, district, population. This is the plan as a block-equivalency file.
- `districts.geojson`: district polygons (union of the block groups' Voronoi cells clipped to the state) with per-district stats.
- `stats.json`: plan and per-district metrics, the seed, the data vintage, and the run time.
- `map.png`: the map. The palette deliberately avoids a red/blue pair.

`summary.csv` and `all_states.png` cover the whole run.

## Data

| Input | Source | Pinned |
|---|---|---|
| Population | Census *Centers of Population* by block group (`CenPop<year>_Mean_BG.txt`). Default: **2020**, `research/redistricting_2020/CenPop2020_Mean_BG.txt` (50 states + DC, 331,449,281 people; built from the CC0 CRAN mirror `USpopcenters` by `build_cenpop2020.py`, because census.gov is unreachable from the build host). `--pop-year 2010`: the official 2010 file from a public GitHub mirror (national total 312,471,327 incl. PR, exactly the 2010 Census figure) | sha256 |
| Outlines | `us-atlas@3.0.1` `states-10m.json` (Census cartographic boundaries 1:10M), from the npm registry | npm sha512 integrity |
| Seats | 2010 and 2020 House apportionment (435 each) | in code |

Downloads are cached in `~/.cache/redistricting` (or `$REDISTRICTING_CACHE`);
the 2020 file is copied there from the repository and hash-checked. Any other
Centers-of-Population block-group file can be passed with `--cenpop` (same
format). The default run combines 2020 population with 2020 seat counts. The
2020 file comes from a mirror, not census.gov directly; verify it against the
Bureau's `CenPop2020_Mean_BG.txt` before using a plan for anything official.

## Results (2020 block groups, 2020 seats)

All 50 states (435 districts, 239,209 block groups) in 56 s in this environment. Every district is contiguous. The worst population deviation in any state is 0.20% (California; block-group granularity). Mean Polsby-Popper across multi-district states is 0.42; 866 counties are split in total. The previous 2010-population table is in git history (worst deviation 0.20%, mean Polsby-Popper 0.42); PA before/after numbers are in `research/redistricting_2020/PA_2010_vs_2020.md`.

| State | Seats | Block groups | Max \|dev\| % | Mean Polsby-Popper | Mean Reock | Counties split | Contiguous | Time (s) |
|---|--:|--:|--:|--:|--:|--:|:-:|--:|
| AL | 7 | 3,925 | 0.060 | 0.504 | 0.545 | 23 | yes | 0.37 |
| AK | 1 | 504 | 0.000 | 0.023 | 0.147 | 0 | yes | 0.51 |
| AZ | 9 | 4,773 | 0.095 | 0.418 | 0.406 | 8 | yes | 0.57 |
| AR | 4 | 2,294 | 0.063 | 0.446 | 0.485 | 13 | yes | 0.27 |
| CA | 52 | 25,607 | 0.202 | 0.333 | 0.417 | 40 | yes | 16.0 |
| CO | 8 | 4,058 | 0.072 | 0.470 | 0.410 | 15 | yes | 0.36 |
| CT | 5 | 2,716 | 0.079 | 0.482 | 0.467 | 6 | yes | 0.22 |
| DE | 1 | 706 | 0.000 | 0.376 | 0.259 | 0 | yes | 0.05 |
| FL | 28 | 13,388 | 0.114 | 0.436 | 0.464 | 29 | yes | 3.07 |
| GA | 14 | 7,446 | 0.088 | 0.479 | 0.546 | 43 | yes | 1.14 |
| HI | 2 | 1,083 | 0.017 | 0.212 | 0.090 | 1 | yes | 0.09 |
| ID | 2 | 1,284 | 0.056 | 0.379 | 0.382 | 5 | yes | 0.14 |
| IL | 17 | 9,898 | 0.092 | 0.461 | 0.537 | 31 | yes | 2.14 |
| IN | 9 | 5,290 | 0.072 | 0.473 | 0.507 | 31 | yes | 0.53 |
| IA | 4 | 2,703 | 0.054 | 0.489 | 0.532 | 15 | yes | 0.26 |
| KS | 4 | 2,461 | 0.068 | 0.497 | 0.440 | 13 | yes | 0.27 |
| KY | 6 | 3,581 | 0.068 | 0.412 | 0.430 | 25 | yes | 0.41 |
| LA | 6 | 4,294 | 0.090 | 0.296 | 0.390 | 15 | yes | 0.75 |
| ME | 2 | 1,184 | 0.046 | 0.343 | 0.483 | 4 | yes | 0.18 |
| MD | 8 | 4,079 | 0.086 | 0.367 | 0.438 | 7 | yes | 0.65 |
| MA | 9 | 5,116 | 0.057 | 0.384 | 0.444 | 10 | yes | 0.6 |
| MI | 13 | 8,386 | 0.100 | 0.406 | 0.465 | 32 | yes | 1.55 |
| MN | 8 | 4,706 | 0.064 | 0.439 | 0.477 | 21 | yes | 0.76 |
| MS | 4 | 2,445 | 0.083 | 0.357 | 0.495 | 15 | yes | 0.29 |
| MO | 8 | 5,031 | 0.073 | 0.474 | 0.494 | 26 | yes | 0.68 |
| MT | 2 | 900 | 0.006 | 0.522 | 0.499 | 3 | yes | 0.09 |
| NE | 3 | 1,648 | 0.063 | 0.463 | 0.400 | 7 | yes | 0.17 |
| NV | 4 | 1,963 | 0.060 | 0.382 | 0.333 | 4 | yes | 0.16 |
| NH | 2 | 997 | 0.041 | 0.400 | 0.285 | 3 | yes | 0.07 |
| NJ | 12 | 6,599 | 0.098 | 0.447 | 0.492 | 17 | yes | 0.62 |
| NM | 3 | 1,614 | 0.096 | 0.356 | 0.305 | 8 | yes | 0.14 |
| NY | 26 | 16,070 | 0.195 | 0.385 | 0.452 | 35 | yes | 4.61 |
| NC | 14 | 7,111 | 0.092 | 0.445 | 0.478 | 37 | yes | 1.13 |
| ND | 1 | 632 | 0.000 | 0.727 | 0.541 | 0 | yes | 0.04 |
| OH | 15 | 9,472 | 0.085 | 0.448 | 0.489 | 41 | yes | 1.66 |
| OK | 5 | 3,374 | 0.075 | 0.454 | 0.456 | 19 | yes | 0.36 |
| OR | 6 | 2,970 | 0.087 | 0.515 | 0.487 | 9 | yes | 0.4 |
| PA | 17 | 10,173 | 0.090 | 0.459 | 0.473 | 37 | yes | 1.83 |
| RI | 2 | 792 | 0.086 | 0.376 | 0.489 | 1 | yes | 0.06 |
| SC | 7 | 3,408 | 0.096 | 0.457 | 0.502 | 22 | yes | 0.35 |
| SD | 1 | 694 | 0.000 | 0.611 | 0.497 | 0 | yes | 0.06 |
| TN | 9 | 4,562 | 0.053 | 0.461 | 0.438 | 24 | yes | 0.59 |
| TX | 38 | 18,638 | 0.151 | 0.322 | 0.462 | 80 | yes | 8.5 |
| UT | 4 | 2,020 | 0.097 | 0.558 | 0.470 | 5 | yes | 0.17 |
| VT | 1 | 552 | 0.000 | 0.476 | 0.381 | 0 | yes | 0.05 |
| VA | 11 | 5,963 | 0.057 | 0.386 | 0.421 | 37 | yes | 1.56 |
| WA | 10 | 5,311 | 0.093 | 0.332 | 0.385 | 16 | yes | 0.85 |
| WV | 2 | 1,639 | 0.080 | 0.333 | 0.517 | 6 | yes | 0.18 |
| WI | 8 | 4,692 | 0.095 | 0.452 | 0.538 | 27 | yes | 0.85 |
| WY | 1 | 457 | 0.000 | 0.773 | 0.621 | 0 | yes | 0.04 |

## Research experiments

- `research/redistricting_seeds/`: 30 random starts per state (`--init random`) and 5 for the borderless national solve; seat projections, efficiency gap and compactness spread (`SUMMARY.md`).
- `research/redistricting_leastchange/`: share of people moved from the 2026 maps against compactness gained, all 44 multi-seat states (`README.md`, figure, ranking).
- `research/redistricting_county/`: county-aware solves (county-level transport LP, county cost in the metric) against production on 10 states. Halves county splits at a ~25 % Polsby-Popper cost.
- `docs/REDISTRICTING_LITERATURE.md`: literature survey and what is and is not new here.

## Limitations (read before citing a plan)

- **Granularity.** Block groups average about 1,400 people, so plans are
  balanced to roughly 0.1–0.3%. Congressional plans are held to "as nearly
  equal as practicable" (*Karcher v. Daggett*), which in practice means
  near-zero deviation at **block** level. Refining these plans to blocks
  (PL 94-171 data) is the next step and is not implemented.
- **Voting Rights Act.** Race-blind generation does not check Section 2
  compliance. A neutral plan can still dilute minority voting strength where
  the VRA requires an opportunity district. Treat these plans as a neutral
  baseline, not as a legally sufficient plan.
- **Neutral process does not guarantee proportional outcomes.** Because
  partisans are not spread evenly across a state, compact neutral maps can
  still favour one party (Chen & Rodden 2013). The generator guarantees
  process neutrality; it does not measure outcomes.
- **Other criteria.** Counties are a soft preference during refinement only
  (a much stronger county-aware variant is in `research/redistricting_county/`).
  Municipalities, communities of interest and VTDs are not modelled.
  Outlines are 1:10M generalisations, so district polygons are for display;
  the block-group assignment is the plan.
- **Optimality.** Lloyd iteration finds a local optimum of population-weighted
  moment of inertia. `--n-init` keeps the best of several seeds, chosen by the
  objective and never by inspecting outcomes.

## References

Hess, Weaver, Siegfeldt, Whelan & Zitlau (1965), *Nonpartisan political
redistricting by computer*, Operations Research 13. · Du, Faber & Gunzburger
(1999), *Centroidal Voronoi tessellations*, SIAM Review 41. · Aurenhammer,
Hoffmann & Aronov (1998), *Minkowski-type theorems and least-squares
clustering*, Algorithmica 20. · Cohen-Addad, Klein & Young (2018), *Balanced
centroidal power diagrams for redistricting*, SIGSPATIAL. · Kitagawa, Mérigot
& Thibert (2019), *Convergence of a Newton algorithm for semi-discrete optimal
transport*, JEMS. · Hu & Blake (1999), *An improved diffusion algorithm for
dynamic load balancing*, Parallel Computing. · Karypis & Kumar (1998), *A fast
and high quality multilevel scheme for partitioning irregular graphs* (METIS).
· Chen & Rodden (2013), *Unintentional gerrymandering*, QJPS.
