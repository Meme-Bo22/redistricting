"""Tests for redistricting_addons.geo_layers and the keep rules it adds to ensembles.

In short (for people): checks the pieces that turn maps into numbers: reading road and river line files, finding
the ridge between two points on a made-up mountain, and the new ensemble rules that keep towns or watersheds whole.

For AI agents (detailed): ``read_lines`` on a hand-built two-record polyline shapefile (one record with two
parts); ``ridges`` on a synthetic DEM (a north-south ridge of 500 m); ``_wmax`` with ``keep_groups`` (weight only
inside a group, never for -1) and ``keep_edges``; ``plan_stats`` with ``split_groups`` / ``edge_flags``.
"""
import struct
from pathlib import Path

import numpy as np

from redistricting_addons import geo_layers as G
from redistricting_addons.ensemble import Graph, _wmax, grid_graph, plan_stats


def _polyline_shp(path: Path, records):
    body = b""
    for n, parts in enumerate(records, 1):
        pts = [p for part in parts for p in part]
        starts, c = [], 0
        for part in parts:
            starts.append(c)
            c += len(part)
        rec = struct.pack("<i", 3) + struct.pack("<4d", 0, 0, 0, 0) + struct.pack("<ii", len(parts), len(pts))
        rec += struct.pack(f"<{len(parts)}i", *starts) + b"".join(struct.pack("<2d", *p) for p in pts)
        body += struct.pack(">ii", n, len(rec) // 2) + rec
    head = struct.pack(">i", 9994) + b"\0" * 20 + struct.pack(">i", (100 + len(body)) // 2) + struct.pack("<ii", 1000, 3)
    head += b"\0" * (100 - len(head))
    path.write_bytes(head + body)


def test_read_lines(tmp_path):
    p = tmp_path / "x.shp"
    _polyline_shp(p, [[[(0, 0), (1, 0)]], [[(2, 2), (3, 3), (4, 4)], [(5, 5), (6, 6)]]])
    pts, pid, prec, nrec = G.read_lines(p)
    assert nrec == 2 and len(pts) == 7
    assert pid.tolist() == [0, 0, 1, 1, 1, 2, 2]
    assert prec.tolist() == [0, 1, 1]


class _FlatState:
    def __init__(self):
        self.lon = np.array([-80.05, -79.95, -80.05])
        self.lat = np.array([40.0, 40.0, 40.05])

    def segs(self, pairs):
        return self.lon[pairs[:, 0]], self.lat[pairs[:, 0]], self.lon[pairs[:, 1]], self.lat[pairs[:, 1]]


class _RidgeDEM:
    def at(self, lon, lat):
        return 100.0 + 500.0 * np.exp(-((np.asarray(lon) + 80.0) / 0.01) ** 2)  # a ridge along lon = -80


def test_ridges():
    r = G.ridges(_FlatState(), _RidgeDEM(), np.array([[0, 1], [0, 2]]))
    assert 450 < r[0] <= 500  # across the ridge
    assert r[1] < 1  # along the same side


def test_keep_rules_and_split_stats():
    g = grid_graph(4, 1)  # path 0-1-2-3
    g.keep_groups = np.array([0, 0, -1, -1])
    em = np.ones(len(g.edges), bool)
    w = _wmax(g, em, 20.0)
    pairs = [tuple(e) for e in g.edges.tolist()]
    assert w[pairs.index((0, 1))] == 20 and w[pairs.index((2, 3))] == 1 and w[pairs.index((1, 2))] == 1
    g.keep_groups = None
    g.keep_edges = np.array([p == (1, 2) for p in pairs])
    w = _wmax(g, em, 20.0)
    assert w[pairs.index((1, 2))] == 20 and w[pairs.index((0, 1))] == 1
    assert np.all(_wmax(g, em, 1.0) == 1)
    g.split_groups = {"town": np.array([0, 0, 1, -1])}
    g.edge_flags = {"natural": np.array([p == (0, 1) for p in pairs])}
    s = plan_stats(g, np.array([0, 1, 1, 1]), 2)
    assert s["town_splits"] == 1 and s["natural_cut_edges"] == 1
    assert isinstance(g, Graph)
