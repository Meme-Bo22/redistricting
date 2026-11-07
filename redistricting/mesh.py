"""The population mesh: a constrained Delaunay graph of block-group centroids.

Each block group is a node carrying its population. Delaunay edges are the
natural-neighbour (Voronoi-adjacency) relation, so the triangulation is the
dual of the Voronoi tessellation that gives every unit its territory. Edges
that leave the state (crossing a bay, a lake or a neighbouring state) are
removed; the components this splits off -- islands, peninsulas across water --
are rejoined with the shortest removed edges (a Kruskal spanning forest over
components), the computational form of "contiguous by water".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.spatial import Delaunay

__all__ = ["LAEA", "PopulationMesh", "build_population_mesh", "outline_polygon"]

R_EARTH_KM = 6371.0088


class LAEA:
    """Spherical Lambert azimuthal equal-area projection (km) about a centre."""

    def __init__(self, lon0: float, lat0: float):
        self.lon0, self.lat0 = float(lon0), float(lat0)
        self._l0, self._p0 = np.radians(lon0), np.radians(lat0)

    @classmethod
    def for_lonlat(cls, lon: np.ndarray, lat: np.ndarray) -> "LAEA":
        lon = np.asarray(lon, float)
        if lon.max() - lon.min() > 180:  # straddles the antimeridian (Alaska)
            lon = np.where(lon > 0, lon - 360, lon)
        return cls(0.5 * (lon.min() + lon.max()), 0.5 * (np.min(lat) + np.max(lat)))

    def forward(self, lon, lat):
        lam, phi = np.radians(lon) - self._l0, np.radians(lat)
        sp0, cp0 = np.sin(self._p0), np.cos(self._p0)
        den = 1 + sp0 * np.sin(phi) + cp0 * np.cos(phi) * np.cos(lam)
        k = np.sqrt(2 / np.maximum(den, 1e-12))
        x = R_EARTH_KM * k * np.cos(phi) * np.sin(lam)
        y = R_EARTH_KM * k * (cp0 * np.sin(phi) - sp0 * np.cos(phi) * np.cos(lam))
        return x, y

    def inverse(self, x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        rho = np.hypot(x, y)
        c = 2 * np.arcsin(np.clip(rho / (2 * R_EARTH_KM), -1, 1))
        sp0, cp0 = np.sin(self._p0), np.cos(self._p0)
        sc, cc = np.sin(c), np.cos(c)
        with np.errstate(invalid="ignore", divide="ignore"):
            phi = np.arcsin(np.clip(cc * sp0 + np.where(rho > 0, y * sc * cp0 / rho, 0), -1, 1))
        lam = np.arctan2(x * sc, rho * cp0 * cc - y * sp0 * sc)
        return np.degrees(lam + self._l0), np.degrees(phi)

    def project_geom(self, geom):
        return shapely.transform(geom, lambda xy: np.column_stack(self.forward(xy[:, 0], xy[:, 1])))

    def unproject_geom(self, geom):
        return shapely.transform(geom, lambda xy: np.column_stack(self.inverse(xy[:, 0], xy[:, 1])))


def outline_polygon(polys) -> shapely.MultiPolygon:
    """Shapely (Multi)Polygon from ``[[exterior, *holes], ...]`` lon/lat rings."""
    parts = [shapely.Polygon(p[0], p[1:]) for p in polys]
    return shapely.make_valid(shapely.MultiPolygon(parts))


@dataclass
class PopulationMesh:
    """Units as nodes of a pruned, re-bridged Delaunay graph (all coordinates km)."""

    xy: np.ndarray  # (n, 2)
    pop: np.ndarray  # (n,)
    edges: np.ndarray  # (m, 2) unique undirected graph edges, i < j
    bridges: np.ndarray  # (b, 2) subset of edges added back across water
    triangles: np.ndarray  # (t, 3) Delaunay triangles whose 3 edges all survived
    domain: shapely.Geometry  # projected state polygon

    @property
    def n(self) -> int:
        return self.pop.size

    def adjacency(self) -> sparse.csr_matrix:
        n = self.n
        a = sparse.coo_matrix(
            (np.ones(2 * len(self.edges)), (np.r_[self.edges[:, 0], self.edges[:, 1]], np.r_[self.edges[:, 1], self.edges[:, 0]])),
            shape=(n, n),
        ).tocsr()
        a.data[:] = 1
        return a


def _dedupe(xy: np.ndarray, eps: float = 1e-3) -> np.ndarray:
    """Nudge coincident centroids apart by ``eps`` km so Delaunay sees them all."""
    xy = xy.copy()
    _, inv, cnt = np.unique(np.round(xy / eps).astype(np.int64), axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    for g in np.flatnonzero(cnt > 1):
        idx = np.flatnonzero(inv == g)
        ang = 2 * np.pi * np.arange(len(idx)) / len(idx)
        xy[idx] += eps * np.column_stack([np.cos(ang), np.sin(ang)])
    return xy


def build_population_mesh(xy: np.ndarray, pop: np.ndarray, domain, snap_km: float = 1.5) -> PopulationMesh:
    """Delaunay-triangulate units, drop edges leaving ``domain``, re-bridge components.

    ``snap_km`` buffers the (generalised 1:10M) outline so coastal centroids
    and edges hugging the shoreline are not cut spuriously.
    """
    xy = _dedupe(np.asarray(xy, float))
    n = len(xy)
    if n < 3:
        e = np.array([[0, 1]]) if n == 2 else np.zeros((0, 2), int)
        return PopulationMesh(xy, np.asarray(pop), e, np.zeros((0, 2), int), np.zeros((0, 3), int), domain)
    tri = Delaunay(xy).simplices
    e = np.sort(np.vstack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [0, 2]]]), axis=1)
    e, inv = np.unique(e, axis=0, return_inverse=True)
    inv = inv.ravel()

    zone = shapely.buffer(domain, snap_km)
    shapely.prepare(zone)
    segs = shapely.linestrings(np.stack([xy[e[:, 0]], xy[e[:, 1]]], axis=1))
    keep = shapely.within(segs, zone)

    # Kruskal over components: re-add shortest removed edges that join components.
    parent = np.arange(n)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in e[keep]:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    removed = np.flatnonzero(~keep)
    length = np.linalg.norm(xy[e[removed, 0]] - xy[e[removed, 1]], axis=1)
    bridges = []
    for idx in removed[np.argsort(length, kind="stable")]:
        a, b = e[idx]
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            keep[idx] = True
            bridges.append(idx)

    tri_ok = keep[inv.reshape(3, -1)].all(axis=0)
    return PopulationMesh(
        xy=xy,
        pop=np.asarray(pop),
        edges=e[keep],
        bridges=e[np.array(bridges, dtype=int)] if bridges else np.zeros((0, 2), int),
        triangles=tri[tri_ok],
        domain=domain,
    )


def is_connected(adj: sparse.csr_matrix) -> bool:
    return connected_components(adj, directed=False)[0] == 1


def unit_cells(xy: np.ndarray, domain) -> np.ndarray:
    """Voronoi cell of every unit, clipped to ``domain`` (array of geometries)."""
    hull = shapely.envelope(shapely.buffer(domain, 50.0))
    vor = shapely.voronoi_polygons(shapely.multipoints(xy), extend_to=hull, ordered=True)
    cells = np.array(shapely.get_parts(vor))
    if len(cells) != len(xy):  # GEOS dropped duplicates despite dedupe: fall back to point lookup
        tree = shapely.STRtree(cells)
        idx = tree.query(shapely.points(xy), predicate="intersects")
        full = np.empty(len(xy), dtype=object)
        full[idx[0]] = cells[idx[1]]
        cells = full
    shapely.prepare(domain)
    return shapely.intersection(cells, domain)
