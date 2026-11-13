# redistricting_addons

## In short (for people)

These tools build a **neutral baseline** for every state: 10,000 district maps drawn by computer with no party data, following the method of Moon Duchin and Daryl DeFord's group (ReCom). The toys then show where any map (yours, the solver's, the official one) falls among them, for seats, compactness and county splits. Run `python -m redistricting_addons.batch` to rebuild everything; the results are already in `site/data/ensembles/`. See `docs/PLAN.md` for the bigger picture.

## For AI agents (detailed)

Add-on tools for the redistricting toys. They are additive: they read the same data as the site and change nothing in `redistricting/`, `site/` pages or existing data. They live outside `redistricting/` because `scripts/sync_from_research.py` mirrors that folder from SegmentAnyMesh and deletes files it does not know. `site/data/ensembles/` and `tests/test_ensemble.py` are also outside the sync's reach.

Needs numpy and scipy only.

### ensemble.py: a neutral baseline (ReCom)

Samples thousands of valid plans for a state with ReCom (DeFord, Duchin & Solomon 2019, [arXiv:1911.05725](https://arxiv.org/abs/1911.05725)). Each move merges two neighbouring districts, draws a random spanning tree over their block groups and cuts it at an edge where both sides are within the population tolerance. Every plan is contiguous and balanced, and compact plans are favoured without tuning.

```
python -m redistricting_addons.ensemble --state PA
python -m redistricting_addons.ensemble --state PA --county-weight 20 --out site/data/ensembles/PA.county20.json
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--steps` | 20000 | ReCom moves per chain after burn-in |
| `--burn` | 1000 | moves discarded at the start of each chain |
| `--every` | 10 | keep every n-th plan |
| `--tol` | 0.01 | population tolerance (1% of the ideal; block groups cannot reach legal precision) |
| `--county-weight` | 1 | 1 = plain ReCom; above 1 keeps counties whole more (Clelland et al. 2021, [arXiv:2011.06049](https://arxiv.org/abs/2011.06049)) |
| `--chains` | 2 | chain 1 starts from the solver's plan, chain 2 from a random spanning-tree plan |

Input: `site/data/<ST>.json`. Output: `site/data/ensembles/<ST>.json` (about 5 kB), summaries only:

- `elections.<name>.seats_d_histogram`: how many sampled plans give Democrats each seat count (two-party; a seat = more D than R votes);
- `elections.<name>.sorted_d_share_quantiles`: for each district rank (least to most Democratic), the 5/25/50/75/95% Democratic share;
- `cut_edges`, `county_splits`, `max_dev_pct`: quantiles over the sample;
- `log_spanning_trees`: quantiles of the spanning-tree score, the natural log of each district's number of spanning trees (Kirchhoff's matrix-tree theorem) summed over districts. Compact districts have far more spanning trees, so higher = more compact (Procaccia & Tucker-Foltz 2021). A district in pieces is counted piece by piece. `--no-trees` skips it;
- `chain_agreement`: how far the two chains' seat histograms (total variation) and median district shares differ. Small numbers mean the sample is reliable;
- `reference.solver`, `reference.official`: each existing plan's numbers and the share of sampled plans at or below it.

Cut edges are counted on the site's block-group graph (a Delaunay triangulation of centre points), not on true shared borders. The official plan is assigned to block groups by centre point, so its population deviation here is larger than the real one.

Tests: `python tests/test_ensemble.py` (or `pytest tests/test_ensemble.py`).

### batch.py: every state

`python -m redistricting_addons.batch` builds both variants for every state in parallel (`--workers 12`), re-running a state with twice the moves when its two chains disagree, and records the outcome in `site/data/ensembles/index.json`. `--from-index` re-runs each state at the move count and seed that passed before, so the chains (and every existing number) are reproduced exactly; use it after adding a statistic.

### regions_votes.py: votes for Re-draw the states

`python -m redistricting_addons.regions_votes` writes `site/data/ensembles/regions_votes.json`: presidential votes for each of the 435 districts the regions page draws. Each block group in `site/data/national.json` is placed on the page's own district raster (nearest district for points on water), because the page's districts differ slightly from the borderless plan in `national.json`.

### Pages

`site/addons/ensemble-panel.js` (Draw, Fair Lines) and `site/addons/regions-sampler.js` (Re-draw the states) read these files. Each page loads its add-on with one `<script>` line; Fair Lines also publishes its state with one line (`window.__RD_PAGE`). The panel computes the spanning-tree score for the maps on the page in the browser (reverse Cuthill-McKee order and envelope Cholesky, about 50-90 ms a map); it matches the Python values to 0.01.
