"""Usable maps on real borders (added 2026-11-24): plans_census fix steps, and every stored map passes audit_maps.

In short (for people): checks the steps that make the official and Fair Lines maps usable on small grids, and that
every stored map (official, Fair Lines, social ties, neutral typical and final maps) has each district in one piece
and within 1% of equal population.

For AI agents (detailed): grid tests for ``make_contiguous``, ``balance`` and ``resplit_pairs``; then
``audit_maps.audit()`` over the stored files (skipped when none are built).
"""
import numpy as np
import pytest

from redistricting_addons.ensemble import grid_graph
from redistricting_addons.plans_census import _adj, balance, extra_pieces, make_contiguous, resplit_pairs
from redistricting_addons import audit_maps


def test_make_contiguous_joins_stray_piece():
    g = grid_graph(4, 4)
    lab = np.repeat([0, 1], 8)
    lab[15] = 0  # a corner of district 1's half given to district 0: a stray piece
    adj = _adj(g)
    assert extra_pieces(adj, lab, 2) == 1
    out, moved, _ = make_contiguous(adj, lab, g.pop, 2)
    assert extra_pieces(adj, out, 2) == 0 and moved == 1


def test_balance_and_resplit_reach_tolerance():
    g = grid_graph(10, 10)
    lab = (np.arange(100) % 10 >= 3).astype(np.int64)  # 30 / 70 split
    adj = _adj(g)
    out, _, _ = balance(adj, lab, g.pop, 2, tol=0.0)
    pops = np.bincount(out, weights=g.pop, minlength=2)
    assert abs(pops[0] - pops[1]) <= 1 and extra_pieces(adj, out, 2) == 0
    out2, n = resplit_pairs(g, lab, 2, tol=0.0)
    pops2 = np.bincount(out2, weights=g.pop, minlength=2)
    assert n >= 1 and pops2[0] == pops2[1] and extra_pieces(adj, out2, 2) == 0


HAVE = any(True for _ in audit_maps.files())


@pytest.mark.skipif(not HAVE, reason="no stored maps built yet")
def test_every_stored_map_usable():
    bad = [r for r in audit_maps.audit() if not r["ok"]]
    assert not bad, bad[:5]
