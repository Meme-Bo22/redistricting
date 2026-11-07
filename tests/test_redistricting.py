"""Offline tests for the redistricting generator (synthetic data, no network)."""
import numpy as np
import pytest

shapely = pytest.importorskip("shapely")

from redistricting import STATES, seats, state_by_abbr  # noqa: E402
from redistricting.data import Units, _read_cenpop, decode_topojson  # noqa: E402
from redistricting.mesh import LAEA, build_population_mesh  # noqa: E402
from redistricting.metrics import _pieces  # noqa: E402
from redistricting.plan import plan_from_units  # noqa: E402
from redistricting.solver import balanced_assign, enforce_contiguity, partition, rcb  # noqa: E402


def test_apportionment_totals():
    assert len(STATES) == 50
    assert sum(s.seats_2020 for s in STATES) == 435
    assert sum(s.seats_2010 for s in STATES) == 435
    assert seats("CA") == 52 and seats("CA", 2010) == 53
    assert state_by_abbr("42").abbr == "PA" and state_by_abbr("new york").abbr == "NY"


def test_read_cenpop_filters_state():
    txt = ("STATEFP,COUNTYFP,TRACTCE,BLKGRPCE,POPULATION,LATITUDE,LONGITUDE\n"
           "01,001,020100,1,698,+32.464812,-086.486527\n"
           "02,013,000100,1,10,+55.0,-160.0\n")
    u = _read_cenpop(txt, "01", "CenPop2010")
    assert len(u) == 1 and u.geoid[0] == "010010201001" and u.county[0] == "01001" and u.pop[0] == 698


def test_decode_topojson_quantized_and_reversed_arcs():
    topo = {
        "type": "Topology",
        "transform": {"scale": [1, 1], "translate": [0, 0]},
        "arcs": [[[0, 0], [1, 0], [0, 1]], [[1, 1], [-1, 0], [0, -1]]],
        "objects": {"s": {"type": "GeometryCollection", "geometries": [
            {"type": "Polygon", "arcs": [[0, 1]], "id": "A"},
            {"type": "Polygon", "arcs": [[~1, ~0]], "id": "B"},
        ]}},
    }
    out = decode_topojson(topo, "s")
    ring_a = out["A"][0][0]
    assert ring_a[0] == ring_a[-1] and len(ring_a) == 5
    assert shapely.Polygon(ring_a).area == pytest.approx(1.0)
    assert shapely.Polygon(out["B"][0][0]).area == pytest.approx(1.0)


def test_laea_roundtrip_and_equal_area():
    p = LAEA(-77.0, 40.0)
    lon = np.array([-80.0, -75.0, -77.0])
    lat = np.array([39.0, 41.5, 40.0])
    x, y = p.forward(lon, lat)
    lo, la = p.inverse(x, y)
    np.testing.assert_allclose(lo, lon, atol=1e-9)
    np.testing.assert_allclose(la, lat, atol=1e-9)
    # a 1x1 degree cell at 40N has area ~ 111.2 * 85.2 km^2
    cell = shapely.box(-78, 40, -77, 41)
    area = p.project_geom(shapely.segmentize(cell, 0.01)).area
    assert area == pytest.approx(9360, rel=0.02)


def test_laea_antimeridian_centre():
    p = LAEA.for_lonlat(np.array([-170.0, 175.0, -140.0]), np.array([52.0, 52.0, 60.0]))
    assert -180 < p.lon0 < -150


def _grid(nx=30, ny=20, seed=0):
    rng = np.random.default_rng(seed)
    xs, ys = np.meshgrid(np.arange(nx), np.arange(ny))
    xy = np.column_stack([xs.ravel(), ys.ravel()]).astype(float) + rng.uniform(-0.2, 0.2, (nx * ny, 2))
    w = rng.integers(500, 2000, nx * ny).astype(float)
    w[(xy[:, 0] < 8) & (xy[:, 1] < 6)] *= 6  # a "city"
    return xy, w


def test_rcb_balanced():
    xy, w = _grid()
    lab = rcb(xy, w, 7)
    pops = np.bincount(lab, weights=w)
    assert len(pops) == 7
    # each of the <= 3 cuts on a root-to-leaf path is off by at most one unit
    assert np.max(np.abs(pops - pops.mean())) <= 3 * w.max()


def test_balanced_assign_reaches_tolerance():
    xy, w = _grid()
    centers = xy[np.random.default_rng(1).choice(len(xy), 6, replace=False)]
    d2 = np.sum((xy[:, None] - centers[None]) ** 2, axis=2)
    lab, v = balanced_assign(d2, w, tol=0.01)
    pops = np.bincount(lab, weights=w, minlength=6)
    assert np.max(np.abs(pops / pops.mean() - 1)) < 0.03
    # it is a power diagram: every unit is at its weighted-nearest centre
    assert np.array_equal(lab, np.argmin(d2 - v, axis=1))


def test_contiguity_repair_merges_detached_piece():
    xy, w = _grid(8, 6)
    dom = shapely.buffer(shapely.box(0, 0, 7, 5), 0.5)
    adj = build_population_mesh(xy, w, dom).adjacency()
    lab = (xy[:, 0] > 3.5).astype(np.int64)
    island = int(np.argmin(np.sum((xy - [6, 2.5]) ** 2, axis=1)))
    lab[island] = 0  # detached piece of district 0 inside district 1
    assert _pieces(lab, adj, 2)[0] == 2
    fixed = enforce_contiguity(lab, adj, w, 2)
    assert fixed[island] == 1 and np.all(_pieces(fixed, adj, 2) == 1)


def test_mesh_prunes_water_and_bridges_islands():
    # two land masses separated by a channel: units on both, domain excludes water
    left = np.column_stack([np.repeat(np.arange(5.0), 5), np.tile(np.arange(5.0), 5)])
    right = left + [10.0, 0.0]
    xy = np.vstack([left, right])
    w = np.ones(len(xy))
    dom = shapely.union(shapely.box(-0.5, -0.5, 4.5, 4.5), shapely.box(9.5, -0.5, 14.5, 4.5))
    m = build_population_mesh(xy, w, dom, snap_km=0.1)
    crossing = (xy[m.edges[:, 0], 0] < 7) != (xy[m.edges[:, 1], 0] < 7)
    assert crossing.sum() == 1 and len(m.bridges) == 1  # exactly one shortest water link


@pytest.mark.parametrize("k", [2, 5, 9])
def test_partition_balanced_contiguous_deterministic(k):
    xy, w = _grid()
    dom = shapely.buffer(shapely.box(0, 0, 29, 19), 1.0)
    adj = build_population_mesh(xy, w, dom).adjacency()
    county = np.array([f"{int(x // 6):02d}{int(y // 5):02d}" for x, y in xy])
    r1 = partition(xy, w, k, adj, county=county, tol=0.005)
    r2 = partition(xy, w, k, adj, county=county, tol=0.005)
    assert np.array_equal(r1.labels, r2.labels)
    pops = np.bincount(r1.labels, weights=w, minlength=k)
    # balanced to within about one (large, "city") unit
    assert np.max(np.abs(pops - pops.mean())) <= 1.5 * w.max()
    assert np.all(_pieces(r1.labels, adj, k) == 1)


def test_plan_from_units_end_to_end(tmp_path):
    xy, w = _grid(24, 18, seed=3)
    lon, lat = -100 + xy[:, 0] * 0.05, 40 + xy[:, 1] * 0.04
    st = state_by_abbr("KS")
    u = Units(
        geoid=np.array([f"20{i:010d}" for i in range(len(w))]),
        county=np.array([f"20{int(x // 6):03d}" for x in xy[:, 0]]),
        pop=w.astype(np.int64), lon=lon, lat=lat, vintage="synthetic",
    )
    ring = [(-100.1, 39.9), (-98.7, 39.9), (-98.7, 40.75), (-100.1, 40.75), (-100.1, 39.9)]
    plan = plan_from_units(st, u, 4, [[ring]])
    s = plan.stats
    assert s.k == 4 and s.all_contiguous and s.total_population == int(w.sum())
    assert s.max_abs_deviation_pct < 1.0
    assert 0 < s.mean_polsby_popper <= 1 and 0 < s.mean_reock <= 1
    # district polygons tile the domain
    total = sum(g.area for g in plan.districts)
    assert total == pytest.approx(plan.mesh.domain.area, rel=1e-6)
    out = plan.write(tmp_path)
    assert (out / "assignment.csv").exists() and (out / "districts.geojson").exists()
    plan.write_fort14(out / "mesh.14")
    head = (out / "mesh.14").read_text().splitlines()[1].split()
    assert int(head[1]) == len(w)


def test_default_population_is_2020():
    from redistricting.data import load_units

    u = load_units("DE")
    assert u.vintage == "CenPop2020" and int(u.pop.sum()) == 989_948  # 2020 Census, Delaware
