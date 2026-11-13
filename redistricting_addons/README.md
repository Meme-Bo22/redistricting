# redistricting_addons

Add-on tools for the redistricting toys. They are additive: they read the same data as the site and change nothing in `redistricting/`, `site/` pages or existing data. They live outside `redistricting/` because `scripts/sync_from_research.py` mirrors that folder from SegmentAnyMesh and deletes files it does not know. `site/data/ensembles/` and `tests/test_ensemble.py` are also outside the sync's reach.

Needs numpy and scipy only.

## ensemble.py: a neutral baseline (ReCom)

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
- `chain_agreement`: how far the two chains' seat histograms (total variation) and median district shares differ. Small numbers mean the sample is reliable;
- `reference.solver`, `reference.official`: each existing plan's numbers and the share of sampled plans at or below it.

Cut edges are counted on the site's block-group graph (a Delaunay triangulation of centre points), not on true shared borders. The official plan is assigned to block groups by centre point, so its population deviation here is larger than the real one.

Tests: `python tests/test_ensemble.py` (or `pytest tests/test_ensemble.py`).
