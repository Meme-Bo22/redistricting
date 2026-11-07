"""End-to-end plan generation for one state."""
from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import shapely

from .data import State, Units, load_state_outline, load_units, seats, state_by_abbr
from .mesh import LAEA, PopulationMesh, build_population_mesh, outline_polygon, unit_cells
from .metrics import DistrictStats, PlanStats, district_stats, plan_stats
from .solver import PartitionResult, partition

__all__ = ["Plan", "generate_plan", "plan_from_units"]


@dataclass
class Plan:
    state: State
    k: int
    units: Units
    proj: LAEA
    mesh: PopulationMesh
    result: PartitionResult
    districts: list  # projected shapely geometries, index = district - 1
    district_stats: list[DistrictStats]
    stats: PlanStats
    seconds: float
    seed: int
    init: str = "rcb"

    @property
    def labels(self) -> np.ndarray:
        return self.result.labels

    # ------------------------------------------------------------------ output
    def write(self, out_dir: str | Path) -> Path:
        """Write assignment.csv, districts.geojson, stats.json (and population mesh fort.14)."""
        out = Path(out_dir) / self.state.abbr
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "assignment.csv", "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["GEOID", "district", "population"])
            for g, d, p in zip(self.units.geoid, self.labels + 1, self.units.pop):
                wr.writerow([g, int(d), int(p)])
        feats = []
        for g, s in zip(self.districts, self.district_stats):
            geo = self.proj.unproject_geom(g)
            feats.append({"type": "Feature", "properties": asdict(s), "geometry": shapely.geometry.mapping(geo)})
        meta = {
            "state": self.state.abbr,
            "districts": self.k,
            "population_vintage": self.units.vintage,
            "seed": self.seed,
            "init": self.init,
            "method": "balanced centroidal power diagram + mesh-graph contiguity + FM boundary refinement",
        }
        with open(out / "districts.geojson", "w") as f:
            json.dump({"type": "FeatureCollection", "metadata": meta, "features": feats}, f)
        with open(out / "stats.json", "w") as f:
            json.dump({**meta, "plan": self.stats.as_dict(), "seconds": round(self.seconds, 2),
                       "lloyd_iterations": self.result.lloyd_iterations, "refine_moves": self.result.moves,
                       "units": len(self.units),
                       "districts_detail": [asdict(s) for s in self.district_stats]}, f, indent=1)
        return out

    def write_fort14(self, path: str | Path) -> None:
        """Population mesh as an ADCIRC fort.14 (lon/lat nodes, depth = population).

        Loadable by CHILmesh / SegmentAnyMesh / Valence tooling. Only Delaunay
        triangles whose three edges survived pruning are written.
        """
        lon, lat = self.proj.inverse(self.mesh.xy[:, 0], self.mesh.xy[:, 1])
        tri = self.mesh.triangles
        with open(path, "w") as f:
            f.write(f"{self.state.abbr} population mesh ({self.units.vintage}); depth=population\n")
            f.write(f"{len(tri)} {len(lon)}\n")
            for i, (x, y, p) in enumerate(zip(lon, lat, self.units.pop), 1):
                f.write(f"{i} {x:.6f} {y:.6f} {float(p):.1f}\n")
            for j, (a, b, c) in enumerate(tri, 1):
                f.write(f"{j} 3 {a + 1} {b + 1} {c + 1}\n")
            f.write("0\n0\n0\n0\n")


def _number_districts(labels, centers):
    """Deterministic numbering: north-to-south bands, west-to-east within a band."""
    k = len(centers)
    span = np.ptp(centers[:, 1]) or 1.0
    band = np.floor((centers[:, 1].max() - centers[:, 1]) / (span / max(1, round(np.sqrt(k))) + 1e-9))
    order = np.lexsort((centers[:, 0], band))
    remap = np.empty(k, np.int64)
    remap[order] = np.arange(k)
    return remap[labels], centers[order]


def plan_from_units(state: State, units: Units, k: int, outline_lonlat=None, seed: int | None = None,
                    n_init: int = 1, tol: float = 0.001, county_weight: float = 0.5, init: str = "rcb") -> Plan:
    t0 = time.perf_counter()
    lon = units.lon
    proj = LAEA.for_lonlat(lon, units.lat)
    x, y = proj.forward(lon, units.lat)
    xy = np.column_stack([x, y])
    if outline_lonlat is not None:
        domain = proj.project_geom(outline_polygon(outline_lonlat))
    else:  # no outline: the convex hull of the units (tests / custom regions)
        domain = shapely.buffer(shapely.convex_hull(shapely.multipoints(xy)), 1.0)
    mesh = build_population_mesh(xy, units.pop, domain)
    adj = mesh.adjacency()
    seed = int(state.fips) if seed is None else seed
    res = partition(mesh.xy, units.pop.astype(float), k, adj, county=units.county, seed=seed,
                    n_init=n_init, tol=tol, county_weight=county_weight, init=init)
    res.labels, res.centers = _number_districts(res.labels, res.centers)
    cells = unit_cells(mesh.xy, domain)
    districts = []
    for d in range(k):
        g = shapely.union_all(cells[res.labels == d])
        districts.append(shapely.make_valid(g))
    ds = district_stats(res.labels, units.pop, units.county, adj, districts)
    ps = plan_stats(res.labels, units.pop, units.county, adj, ds)
    return Plan(state, k, units, proj, mesh, res, districts, ds, ps, time.perf_counter() - t0, seed, init)


def generate_plan(state: str | State, k: int | None = None, cenpop_path=None, seats_year: int = 2020,
                  seed: int | None = None, n_init: int = 1, tol: float = 0.001,
                  county_weight: float = 0.5, pop_year: int = 2020, init: str = "rcb") -> Plan:
    """Generate a fair congressional plan for ``state``.

    ``k`` defaults to the state's House seats after the ``seats_year`` Census;
    population comes from the ``pop_year`` block groups (2020 by default).
    """
    st = state if isinstance(state, State) else state_by_abbr(state)
    units = load_units(st, cenpop_path, year=pop_year)
    k = seats(st, seats_year) if k is None else int(k)
    return plan_from_units(st, units, k, load_state_outline(st), seed=seed, n_init=n_init, tol=tol,
                           county_weight=county_weight, init=init)
