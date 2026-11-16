"""Social-ties maps on real borders (redistricting_addons.sci_census): every district one piece, populations within 1%."""
import json

import numpy as np
import pytest

from redistricting_addons.ensemble import ROOT, grid_graph, load_state
from redistricting_addons.sci_census import DIST, pieces


def test_pieces_counts_split_districts():
    g = grid_graph(4, 4)
    lab = np.repeat([0, 1], 8)  # two halves: one piece each
    assert pieces(g, lab) == 2
    lab2 = lab.copy()
    lab2[0] = 1  # a corner cell of district 1 cut off inside district 0
    assert pieces(g, lab2) == 3


FILES = sorted(DIST.glob("[A-Z][A-Z].*.census.json"))


@pytest.mark.skipif(not FILES, reason="no real-border social-ties maps built yet")
@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_census_maps_contiguous_and_balanced(path):
    st = path.name[:2]
    g = load_state(ROOT / "site" / "data" / f"{st}.json", graph="census", sci=False)
    lab = np.asarray(json.loads(path.read_text(encoding="utf-8"))["labels"], np.int64)
    assert pieces(g, lab) == g.k
    pops = np.bincount(lab, weights=g.pop, minlength=g.k)
    assert np.max(np.abs(pops / (g.pop.sum() / g.k) - 1)) <= 0.0101
