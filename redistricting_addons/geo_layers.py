"""Geography layers for fair maps: mountains and ridges, watersheds, USGS rivers, drive time, towns, school districts.

In short (for people): district lines can be asked to follow nature and real communities. This builds, for every
state, what each link between two neighbouring block groups crosses: how high a ridge lies between them, whether
they drain into different rivers (USGS watersheds), how big a river runs between them (USGS hydrography), how
long the drive is compared with the straight line (Census road map), and whether they sit in different towns or
school districts (Census). The Draw toy gets a slider for each, and the neutral-map ensembles get versions that
keep watersheds, towns or school districts whole, or avoid crossing rivers and ridges.
``python -m redistricting_addons.geo_layers`` fetches and builds every state with more than one district.

For AI agents (detailed):
- Units and edges: the site's block groups (``site/data/<ST>.json``, centres from ``cenpop.rows``, same order);
  every value below is per site edge (``data.edges`` order) or per water bridge (``data.bridges`` order), so the
  Draw page and ``ensemble.load_state(graph="site")`` can use them directly. Each edge is the straight segment
  between the two units' population centres.
- Elevation (``ridge``, metres): USGS 3DEP via the AWS Terrain Tiles (terrarium PNG, zoom 9, about 240 m per pixel
  at 38 degrees; elevation = R*256 + G + B/256 - 32768, sea clipped to 0). Each edge is sampled every 150 m
  (at most 400 samples); ``ridge`` = highest sample minus the higher endpoint: the climb over the highest ground
  between two neighbourhoods (0 on flat land or straight up a valley side). A shaded-relief picture per state
  (``<ST>.relief.png``) is drawn in the site's x, y (km) frame, inverse-mapped through a cubic fit of the
  site's projection (fit error reported in the file).
- Watersheds (``huc8``, ``huc10``: per unit, index into ``names``): USGS Watershed Boundary Dataset, the
  hydro.nationalmap.gov ``wbd`` MapServer layers 4 (8-digit subbasins) and 5 (10-digit watersheds), queried by the
  state's bounding box and simplified 0.002 / 0.001 degrees by the server. Units take the polygon containing their
  centre (nearest polygon when none does).
- Rivers (``river``, Strahler order): USGS small-scale hydrography, 1:1,000,000 streams of the United States
  (``streaml010g``, selected and generalised from the NHD, one 240 MB download; features Stream, Stream
  Intermittent, Artificial Path of Strahler order 4 or more); per edge, the highest order of a river the segment
  crosses (0 when none). ``lake`` (km2): the largest lake or reservoir of at least 4 km2 (``wtrbdyp010g``) the
  segment crosses. Water bridges get ``river`` = 9 (open water). (The NHDPlus High Resolution map service was
  tried first and is far too slow for 44 states: 20-45 s per one-degree tile.)
- Drive time (``travel``, tenths of a minute): Census TIGER/Line 2020 roads, every county's ``tl_2020_<ccccc>_roads``,
  as a graph on road end points (TIGER splits roads at intersections) with speeds by MTFCC (``SPEED``). Each unit
  centre joins its nearest road node by a straight leg at 20 km/h times 1.3. ``travel`` = shortest drive time
  between the two centres (scipy Dijkstra from each unit, limited to a radius); unreachable pairs (islands, no road)
  get 6000 (600 minutes). A county whose 2020 file the Census server rejects uses its 2021 file. ``dist`` (hundredths of km) is the straight distance; the Draw page compares the two.
- Towns (``town``) and school districts (``school``): Census 2020 Block Assignment Files (block -> incorporated or
  census-designated place, county subdivision, unified / secondary / elementary school district) and the 2020
  code lists (place TYPE, county-subdivision FUNCSTAT). A town is an incorporated place, else a county subdivision
  with an active government (FUNCSTAT A: New England towns, townships in the Midwest, PA, NJ, NY ...). A school
  district is the unified district, else the secondary, else the elementary one. Each block group takes the town /
  district holding the most of its blocks (blocks are not weighted by population: the Census API needs a key for
  block counts, and the block shapefiles are 7 GB); -1 when the plurality is "none" (unincorporated land).
- Outlines for display (``<ST>.shapes.json``): rivers (x, y polylines with drainage area), lakes, HUC8 / HUC10
  rings, and town / school-district outlines dissolved from the 2020 block-group boundary file
  (``graphs.boundary_files``), all in site x, y, simplified, rounded to 0.1 km.
- Outputs: ``site/data/layers/geo/<ST>.json`` (per-edge arrays ``ridge``, ``river``, ``lake``, ``travel``, ``dist``
  and the same with a ``bridge_`` prefix; per-unit ``huc8``, ``huc10``, ``town``, ``school``; ``names``; counts;
  sources), ``<ST>.shapes.json``, ``<ST>.relief.png``. Nothing existing is changed (the page's own
  ``layers/<ST>.json`` stays as it is). Downloads are cached under ``cenpop.cache_dir()/geo``.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from . import cenpop

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "layers" / "geo"
UA = {"User-Agent": "redistricting-addons/0.1 (geo layers)"}
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ZOOM = 9
WBD = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/{layer}/query"
NHD = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/{layer}/query"
ROADS = "https://www2.census.gov/geo/tiger/TIGER2020/ROADS/tl_2020_{fips}_roads.zip"
BAF = "https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST{fips}_{st}.zip"
PLACES = "https://www2.census.gov/geo/docs/reference/codes2020/place/st{fips}_{st}_place2020.txt"
COUSUBS = "https://www2.census.gov/geo/docs/reference/codes2020/cousub/st{fips}_{st}_cousub2020.txt"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_{kind}_national.zip"
USGS1M = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Small-scale/data/Hydrography/{file}"
USGS1M_FILES = {"streaml010g": "streaml010g.shp_nt00885.tar.gz", "wtrbdyp010g": "wtrbdyp010g.shp_nt00886.tar.gz"}
RIVER_MIN_ORDER = 4  # Strahler order on the 1:1M map (1 to 7); 4+ are rivers, 6-7 the largest
LAKE_MIN_KM2 = 4
# km/h by TIGER MTFCC; classes not listed (walkways, stairs, bike paths, census-only lines) are left out
SPEED = {"S1100": 100, "S1200": 70, "S1400": 40, "S1630": 50, "S1640": 25, "S1500": 15, "S1730": 15,
         "S1740": 20, "S1780": 10}
ACCESS_KMH, ACCESS_DETOUR = 20.0, 1.3
UNREACHED = 6000  # tenths of a minute


# --------------------------------------------------------------------------- downloads

def cache(*parts) -> Path:
    p = cenpop.cache_dir().joinpath("geo", *parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get(url: str, dest: Path, timeout: int = 300, tries: int = 5) -> Path | None:
    """Download once (atomically); None on 404."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    for t in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                blob = r.read()
            if dest.suffix == ".zip" and blob[:2] != b"PK":  # the Census server sometimes answers "Request Rejected"
                raise RuntimeError(f"{url}: not a zip ({blob[:60]!r})")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(blob)
            tmp.replace(dest)
            return dest
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if t == tries - 1:
                raise
        except Exception:
            if t == tries - 1:
                raise
        time.sleep(3 * (t + 1))
    return None


def arcgis(url: str, where: str, bbox, fields: str, offset: float, dest: Path, page: int = 1000) -> list[dict]:
    """All features of an ArcGIS MapServer layer intersecting ``bbox`` (GeoJSON, paged), cached at ``dest``."""
    if dest.exists():
        return json.loads(dest.read_text(encoding="utf-8"))["features"]
    feats, off = [], 0
    while True:
        q = {"where": where, "geometry": ",".join(f"{v:.4f}" for v in bbox), "geometryType": "esriGeometryEnvelope",
             "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": fields, "returnGeometry": "true",
             "outSR": 4326, "maxAllowableOffset": offset, "geometryPrecision": 5, "resultOffset": off,
             "resultRecordCount": page, "orderByFields": "OBJECTID", "f": "geojson"}
        body = urllib.parse.urlencode(q).encode()
        for t in range(6):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=UA), timeout=300) as r:
                    d = json.loads(r.read())
                if "error" in d:
                    raise RuntimeError(str(d["error"])[:300])
                break
            except Exception:
                if t == 5:
                    raise
                time.sleep(5 * (t + 1))
        fs = d.get("features", [])
        feats += fs
        if len(fs) < page:
            break
        off += len(fs)
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return feats


# --------------------------------------------------------------------------- state basics

class State:
    def __init__(self, st: str):
        self.st = st
        self.d = json.loads((ROOT / "site" / "data" / f"{st}.json").read_text(encoding="utf-8"))
        self.fips = self.d["fips"]
        rows = cenpop.rows(self.fips)
        if len(rows) != self.d["n"]:
            raise ValueError(f"{st}: {len(rows)} CenPop rows, site has {self.d['n']}")
        self.geoid = [r[0] + r[1] + r[2] + r[3] for r in rows]
        self.lat = np.array([float(r[5]) for r in rows])
        self.lon = np.array([float(r[6]) for r in rows])
        self.x = np.asarray(self.d["x"], float)
        self.y = np.asarray(self.d["y"], float)
        self.edges = np.asarray(self.d["edges"], np.int64).reshape(-1, 2)
        self.bridges = np.asarray(self.d.get("bridges", []), np.int64).reshape(-1, 2)
        pad = 0.15
        self.bbox = (self.lon.min() - pad, self.lat.min() - pad, self.lon.max() + pad, self.lat.max() + pad)
        ol = [np.asarray(r, float) for poly in self.d["outline"] for r in poly]
        allp = np.vstack(ol)
        self.xy_box = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
        self.outline = ol
        self._fit()

    # cubic fit of the site's projection (lon, lat -> x, y) and its inverse
    def _feat(self, a, b, c):
        a = (np.asarray(a, float) - c[0]) / c[1]
        b = (np.asarray(b, float) - c[2]) / c[3]
        return np.stack([np.ones_like(a), a, b, a * a, a * b, b * b, a ** 3, a * a * b, a * b * b, b ** 3], -1)

    def _fit(self):
        self.cf = (self.lon.mean(), max(np.ptp(self.lon), 1e-6), self.lat.mean(), max(np.ptp(self.lat), 1e-6))
        self.ci = (self.x.mean(), max(np.ptp(self.x), 1e-6), self.y.mean(), max(np.ptp(self.y), 1e-6))
        A = self._feat(self.lon, self.lat, self.cf)
        self.px = np.linalg.lstsq(A, self.x, rcond=None)[0]
        self.py = np.linalg.lstsq(A, self.y, rcond=None)[0]
        B = self._feat(self.x, self.y, self.ci)
        self.plon = np.linalg.lstsq(B, self.lon, rcond=None)[0]
        self.plat = np.linalg.lstsq(B, self.lat, rcond=None)[0]
        ex, ey = self.to_xy(self.lon, self.lat)
        self.fit_err_km = float(np.max(np.hypot(ex - self.x, ey - self.y)))

    def to_xy(self, lon, lat):
        A = self._feat(lon, lat, self.cf)
        return A @ self.px, A @ self.py

    def to_ll(self, x, y):
        B = self._feat(x, y, self.ci)
        return B @ self.plon, B @ self.plat

    def segs(self, pairs):
        return self.lon[pairs[:, 0]], self.lat[pairs[:, 0]], self.lon[pairs[:, 1]], self.lat[pairs[:, 1]]


def km(lon1, lat1, lon2, lat2):
    p = np.radians((np.asarray(lat1) + np.asarray(lat2)) / 2)
    return 111.195 * np.hypot((np.asarray(lon2) - lon1) * np.cos(p), np.asarray(lat2) - lat1)


# --------------------------------------------------------------------------- elevation

def _tile_xy(lon, lat, z=ZOOM):
    n = 2 ** z
    lat = np.clip(lat, -85, 85)
    x = (np.asarray(lon) + 180) / 360 * n
    y = (1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / math.pi) / 2 * n
    return x, y


class DEM:
    """Elevation mosaic (metres) over a bounding box from terrarium tiles; ``at(lon, lat)`` samples bilinearly."""

    def __init__(self, bbox, z=ZOOM, workers=16):
        from PIL import Image
        x0, y1 = _tile_xy(bbox[0], bbox[1], z)
        x1, y0 = _tile_xy(bbox[2], bbox[3], z)
        tx0, tx1, ty0, ty1 = int(x0), int(x1), int(y0), int(y1)
        self.z, self.tx0, self.ty0 = z, tx0, ty0
        jobs = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]

        def one(xy):
            x, y = xy
            return xy, get(TILE_URL.format(z=z, x=x, y=y), cache("dem", str(z), str(x), f"{y}.png"), timeout=60)

        with ThreadPoolExecutor(workers) as ex:
            paths = dict(ex.map(one, jobs))
        self.a = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), np.float32)
        for (x, y), p in paths.items():
            if p is None:
                continue
            rgb = np.asarray(Image.open(p).convert("RGB"), np.float32)
            el = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
            self.a[(y - ty0) * 256:(y - ty0 + 1) * 256, (x - tx0) * 256:(x - tx0 + 1) * 256] = el
        np.maximum(self.a, 0, out=self.a)
        self.tiles = len(jobs)

    def at(self, lon, lat):
        x, y = _tile_xy(lon, lat, self.z)
        x = x * 1.0 - self.tx0 * 1.0
        y = y * 1.0 - self.ty0 * 1.0
        px = np.clip(x * 256 - 0.5, 0, self.a.shape[1] - 1.001)
        py = np.clip(y * 256 - 0.5, 0, self.a.shape[0] - 1.001)
        i, j = py.astype(np.int64), px.astype(np.int64)
        fy, fx = py - i, px - j
        a = self.a
        return ((a[i, j] * (1 - fx) + a[i, j + 1] * fx) * (1 - fy) + (a[i + 1, j] * (1 - fx) + a[i + 1, j + 1] * fx) * fy)


def ridges(S: State, dem: DEM, pairs: np.ndarray, step_km=0.15, max_samples=400) -> np.ndarray:
    """Per pair: highest ground on the segment minus the higher endpoint (metres, >= 0)."""
    lo1, la1, lo2, la2 = S.segs(pairs)
    d = km(lo1, la1, lo2, la2)
    ns = np.clip(np.ceil(d / step_km).astype(np.int64) + 1, 2, max_samples)
    out = np.zeros(len(pairs), np.float32)
    for s in range(0, len(pairs), 20000):
        sl = slice(s, s + 20000)
        n = ns[sl]
        idx = np.repeat(np.arange(n.size), n)
        start = np.repeat(np.cumsum(n) - n, n)
        t = (np.arange(n.sum()) - start) / np.repeat(n - 1, n)
        lo = np.repeat(lo1[sl], n) + t * np.repeat(lo2[sl] - lo1[sl], n)
        la = np.repeat(la1[sl], n) + t * np.repeat(la2[sl] - la1[sl], n)
        z = dem.at(lo, la)
        top = np.full(n.size, -1e9)
        np.maximum.at(top, idx, z)
        ends = np.maximum(dem.at(lo1[sl], la1[sl]), dem.at(lo2[sl], la2[sl]))
        out[sl] = np.maximum(top - ends, 0)
    return out


def relief_png(S: State, dem: DEM, path: Path, size=1000) -> dict:
    """Shaded relief in the site's x, y frame (north-west light), black shadows and white highlights on alpha."""
    from PIL import Image
    from matplotlib.path import Path as MPath
    x0, y0, x1, y1 = S.xy_box
    sc = max(x1 - x0, y1 - y0) / size
    w, h = int(math.ceil((x1 - x0) / sc)), int(math.ceil((y1 - y0) / sc))
    gx = x0 + (np.arange(w) + 0.5) * sc
    gy = y1 - (np.arange(h) + 0.5) * sc  # row 0 = north (largest y)
    X, Y = np.meshgrid(gx, gy)
    lon, lat = S.to_ll(X.ravel(), Y.ravel())
    Z = dem.at(lon, lat).reshape(h, w) / 1000.0  # km
    dzdx = np.gradient(Z, sc, axis=1)
    dzdy = -np.gradient(Z, sc, axis=0)  # rows run south
    zf = 3.0
    nx, ny, nz = -zf * dzdx, -zf * dzdy, np.ones_like(Z)
    nn = np.sqrt(nx * nx + ny * ny + nz * nz)
    L = np.array([-1, 1, 1.4142]) / 2.0  # from the north-west, 45 degrees up
    hs = (nx * L[0] + ny * L[1] + nz * L[2]) / nn
    shade = 0.7071 - hs
    inside = np.zeros(X.size, bool)
    for ring in S.outline:
        inside ^= MPath(ring).contains_points(np.c_[X.ravel(), Y.ravel()])
    inside = inside.reshape(h, w)
    rgba = np.zeros((h, w, 4), np.uint8)
    dark = shade > 0
    rgba[..., :3] = np.where(dark[..., None], 0, 255)
    alpha = np.where(dark, np.clip(shade * 2.2, 0, 1) * 200, np.clip(-shade * 2.2, 0, 1) * 110)
    rgba[..., 3] = np.where(inside, alpha, 0).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)
    return {"file": path.name, "x0": round(x0, 3), "y0": round(y0, 3), "x1": round(x0 + w * sc, 3),
            "y1": round(y1, 3), "y_bottom": round(y1 - h * sc, 3), "w": w, "h": h}


# --------------------------------------------------------------------------- watersheds, rivers, lakes

def _geoms(feats):
    from shapely.geometry import shape
    out = []
    for f in feats:
        try:
            g = shape(f["geometry"]) if f.get("geometry") else None
        except Exception:
            g = None
        out.append(g)
    return out


def watersheds(S: State):
    from shapely import STRtree, points
    res = {}
    for key, layer, off in (("huc8", 4, 0.002), ("huc10", 5, 0.001)):
        feats = arcgis(WBD.format(layer=layer), "1=1", S.bbox, f"{key},name", off, cache("wbd", f"{S.st}.{key}.json"))
        geoms = _geoms(feats)
        keep = [i for i, g in enumerate(geoms) if g is not None and not g.is_empty]
        geoms = [geoms[i] for i in keep]
        feats = [feats[i] for i in keep]
        tree = STRtree(geoms)
        pts = points(S.lon, S.lat)
        a, b = tree.query(pts, predicate="within")
        lab = np.full(S.d["n"], -1, np.int64)
        lab[a] = b
        miss = np.flatnonzero(lab < 0)
        if miss.size:
            lab[miss] = tree.query_nearest(pts[miss], return_distance=False, all_matches=False)[1]
        used = np.unique(lab)
        remap = np.full(len(geoms), -1, np.int64)
        remap[used] = np.arange(used.size)
        res[key] = {"lab": remap[lab], "names": [f"{feats[i]['properties'].get(key)} {feats[i]['properties'].get('name')}"
                                                for i in used],
                    "geoms": [geoms[i] for i in used]}
    return res


_NATIONAL = {}


def _usgs1m():
    """USGS small-scale (1:1,000,000) streams and waterbodies of the United States, read once per process."""
    if _NATIONAL:
        return _NATIONAL
    from .graphs import read_dbf, read_polygons
    import pickle
    d = cenpop.cache_dir() / "geo" / "usgs1m"
    pk = d / f"selected_order{RIVER_MIN_ORDER}_lake{LAKE_MIN_KM2}.pkl"  # the selection, so workers skip the 400 MB read
    if pk.exists():
        _NATIONAL.update(pickle.loads(pk.read_bytes()))
        return _NATIONAL
    for name in ("streaml010g", "wtrbdyp010g"):
        if not (d / f"{name}.shp").exists():
            import tarfile
            z = get(USGS1M.format(file=USGS1M_FILES[name]), cache("usgs1m", USGS1M_FILES[name]), timeout=1800)
            with tarfile.open(z) as tf:
                tf.extractall(d, filter="data")
    pts, pid, prec, nrec = read_lines(d / "streaml010g.shp")
    att = read_dbf(d / "streaml010g.dbf", ["Strahler", "Feature", "Name"])
    order = np.array([int(v) if v.lstrip("-").isdigit() else 0 for v in att["Strahler"]], np.int64)
    ok = np.isin(att["Feature"], ["Stream", "Stream Intermittent", "Artificial Path"]) & (order >= RIVER_MIN_ORDER)
    starts = np.r_[0, np.flatnonzero(np.diff(pid)) + 1]
    ends = np.r_[starts[1:], len(pid)]
    lines = [(int(order[prec[p]]), att["Name"][prec[p]], pts[a:b]) for p, (a, b) in enumerate(zip(starts, ends))
             if ok[prec[p]] and b - a >= 2]
    w = read_dbf(d / "wtrbdyp010g.dbf", ["Feature", "Name", "Area_sq_mi"])
    area = np.array([float(v or 0) for v in w["Area_sq_mi"]]) * 2.58999
    keep = np.flatnonzero(np.isin(w["Feature"], ["Lake", "Reservoir"]) & (area >= LAKE_MIN_KM2))
    rings = read_polygons(d / "wtrbdyp010g.shp", d / "wtrbdyp010g.shx", keep.tolist())
    lakes = [(float(area[i]), w["Name"][i], rings[i]) for i in keep if rings.get(i)]

    def box(arrs):
        a = np.vstack(arrs)
        return [a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()]

    _NATIONAL.update(lines=lines, lakes=lakes, line_box=np.array([box([l[2]]) for l in lines]),
                     lake_box=np.array([box(r) for _, _, r in lakes]))
    tmp = pk.with_suffix(".part")
    tmp.write_bytes(pickle.dumps(dict(_NATIONAL)))
    tmp.replace(pk)
    return _NATIONAL


def rivers(S: State):
    """Features (rivers: Strahler ``order``; lakes: ``areasqkm``) near the state, from the USGS 1:1M layers."""
    from shapely.geometry import LineString, Polygon, mapping
    from shapely import unary_union
    N = _usgs1m()
    x0, y0, x1, y1 = S.bbox

    def near(bx):
        return np.flatnonzero((bx[:, 2] >= x0) & (bx[:, 0] <= x1) & (bx[:, 3] >= y0) & (bx[:, 1] <= y1))

    fl = [{"properties": {"order": o, "name": nm}, "geometry": mapping(LineString(p))}
          for o, nm, p in (N["lines"][i] for i in near(N["line_box"]))]
    wb = []
    for i in near(N["lake_box"]):
        a, nm, rings = N["lakes"][i]
        shells, holes = [], []
        for r in rings:
            if len(r) < 4:
                continue
            sa = 0.5 * np.sum(r[:-1, 0] * r[1:, 1] - r[1:, 0] * r[:-1, 1])
            (shells if sa < 0 else holes).append(Polygon(r).buffer(0))
        if not shells:
            continue
        g = unary_union(shells)
        if holes:
            g = g.difference(unary_union(holes))
        wb.append({"properties": {"areasqkm": a, "name": nm}, "geometry": mapping(g)})
    return fl, wb


def crossings(S: State, pairs: np.ndarray, feats, value_key: str) -> np.ndarray:
    """Per pair: the largest ``value_key`` of the features its segment crosses (0 when none)."""
    from shapely import STRtree, linestrings
    geoms = _geoms(feats)
    ok = [i for i, g in enumerate(geoms) if g is not None and not g.is_empty]
    out = np.zeros(len(pairs), np.float64)
    if not ok or not len(pairs):
        return out
    vals = np.array([float(feats[i]["properties"].get(value_key) or 0) for i in ok])
    tree = STRtree([geoms[i] for i in ok])
    lo1, la1, lo2, la2 = S.segs(pairs)
    segs = linestrings(np.stack([np.c_[lo1, la1], np.c_[lo2, la2]], 1))
    a, b = tree.query(segs, predicate="intersects")
    np.maximum.at(out, a, vals[b])
    return out


# --------------------------------------------------------------------------- roads and drive time

def read_lines(shp: Path):
    """(points (N, 2), part id per point, record per part, record count) of a polyline shapefile."""
    data = shp.read_bytes()
    pos, recs, chunks, pid, prec, npart = 100, 0, [], [], [], 0
    while pos + 8 <= len(data):
        clen = struct.unpack(">i", data[pos + 4:pos + 8])[0]
        off = pos + 8
        stype = struct.unpack("<i", data[off:off + 4])[0]
        if stype in (3, 13, 23):
            nparts, npts = struct.unpack("<ii", data[off + 36:off + 44])
            parts = np.frombuffer(data, "<i4", nparts, off + 44)
            pts = np.frombuffer(data, "<f8", 2 * npts, off + 44 + 4 * nparts).reshape(npts, 2)
            chunks.append(pts)
            lens = np.diff(np.r_[parts, npts])
            pid.append(np.repeat(np.arange(npart, npart + nparts), lens))
            prec += [recs] * nparts
            npart += nparts
        recs += 1
        pos = off + clen * 2
    if not chunks:
        return np.zeros((0, 2)), np.zeros(0, np.int64), np.zeros(0, np.int64), recs
    return np.vstack(chunks), np.concatenate(pid), np.asarray(prec, np.int64), recs


def road_graph(S: State, counties: list[str]):
    """Drive-time graph (tenths of a minute) on road vertices shared by two roads or ending a road.

    TIGER ``roads`` records are whole named roads, not split at crossings, so a crossing is a vertex that appears
    in more than one record (or twice in one); other vertices are only shape points and are contracted away."""
    from .graphs import read_dbf
    P, R, SP = [], [], []
    base = 0
    for c in counties:
        year = 2020
        try:
            z = get(ROADS.format(fips=c), cache("roads", f"tl_2020_{c}_roads.zip"), timeout=600)
        except Exception:  # added fallback: the Census firewall rejects a few 2020 files (e.g. 51036); use 2021
            year = 2021
            z = get(ROADS.format(fips=c).replace("TIGER2020", "TIGER2021").replace("tl_2020_", "tl_2021_"),
                    cache("roads", f"tl_2021_{c}_roads.zip"), timeout=600)
        if z is None:
            continue
        d = cache("roads", c)
        stem = d / f"tl_{year}_{c}_roads"
        if not stem.with_suffix(".shp").exists():
            d.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(d)
        pts, pid, prec, nrec = read_lines(stem.with_suffix(".shp"))
        mt = read_dbf(stem.with_suffix(".dbf"), ["MTFCC"])["MTFCC"]
        sp = np.array([SPEED.get(m, 0) for m in mt], float)[prec]  # per part
        keep = sp[pid] > 0
        P.append(pts[keep])
        R.append(pid[keep] + base)
        SP.append(sp)
        base += len(prec)
    pts, rid, speed = np.vstack(P), np.concatenate(R), np.concatenate(SP)
    q = np.round(pts * 1e6).astype(np.int64)
    key = q[:, 0] * 1_000_000_000 + q[:, 1]  # lon * 1e6 (negative) and lat * 1e6 (< 1e9) packed in one int64
    uk, firsti, inv, cnt = np.unique(key, return_index=True, return_inverse=True, return_counts=True)
    start = np.r_[True, rid[1:] != rid[:-1]]
    end = np.r_[rid[1:] != rid[:-1], True]
    kept = start | end | (cnt[inv] > 1)
    seg = km(pts[:-1, 0], pts[:-1, 1], pts[1:, 0], pts[1:, 1])
    seg[rid[:-1] != rid[1:]] = 0
    cum = np.r_[0.0, np.cumsum(seg)]
    K = np.flatnonzero(kept)
    same = rid[K[:-1]] == rid[K[1:]]
    i0, i1 = K[:-1][same], K[1:][same]
    w = (cum[i1] - cum[i0]) / speed[rid[i0]] * 600.0  # tenths of a minute
    u, v = inv[i0], inv[i1]
    used = np.unique(np.r_[u, v])
    remap = np.full(uk.size, -1, np.int64)
    remap[used] = np.arange(used.size)
    u, v = remap[u], remap[v]
    nodes = pts[firsti[used]]
    a, b = np.minimum(u, v), np.maximum(u, v)
    ok = a != b
    a, b, w = a[ok], b[ok], np.maximum(w[ok], 1e-3)
    order = np.lexsort((w, b, a))
    a, b, w = a[order], b[order], w[order]
    first = np.r_[True, (a[1:] != a[:-1]) | (b[1:] != b[:-1])]
    G = sparse.csr_matrix((w[first], (a[first], b[first])), shape=(len(nodes), len(nodes)))
    return G, nodes


def drive_times(S: State, pairs: np.ndarray, G, nodes, log=None) -> np.ndarray:
    lat0 = np.radians(S.lat.mean())
    tree = cKDTree(np.c_[nodes[:, 0] * math.cos(lat0), nodes[:, 1]])
    dd, nn = tree.query(np.c_[S.lon * math.cos(lat0), S.lat])
    acc = dd * 111.195 * ACCESS_DETOUR / ACCESS_KMH * 600.0  # tenths of a minute
    lo1, la1, lo2, la2 = S.segs(pairs)
    dkm = km(lo1, la1, lo2, la2)
    out = np.full(len(pairs), float(UNREACHED))
    by = {}
    for t, (i, j) in enumerate(pairs.tolist()):
        by.setdefault(i, []).append((t, j))
    t0 = time.perf_counter()
    for c, (i, lst) in enumerate(by.items()):
        far = max(dkm[t] for t, _ in lst)
        limit = min(2400.0, acc[i] + 4.0 * far / 30.0 * 600.0 + 100.0) + max(acc[j] for _, j in lst)
        dist = dijkstra(G, directed=False, indices=int(nn[i]), limit=limit)
        for t, j in lst:
            v = acc[i] + dist[nn[j]] + acc[j]
            if np.isfinite(v):
                out[t] = min(v, UNREACHED)
        if log and c and c % 2000 == 0:
            log(f"  {S.st} drive times: {c}/{len(by)} units, {time.perf_counter() - t0:.0f}s")
    return out


# --------------------------------------------------------------------------- towns and school districts

def _codes(url, dest):
    p = get(url, dest)
    if p is None:
        return []
    lines = p.read_text(encoding="latin-1").splitlines()
    head = lines[0].split("|")
    return [dict(zip(head, ln.split("|"))) for ln in lines[1:] if ln.strip()]


def towns_schools(S: State):
    st = S.st
    z = get(BAF.format(fips=S.fips, st=st), cache("baf", f"BlockAssign_ST{S.fips}_{st}.zip"))
    places = {r["PLACEFP"]: r for r in _codes(PLACES.format(fips=S.fips, st=st.lower()), cache("codes", f"{st}.place.txt"))}
    cousub = {r["COUNTYFP"] + r["COUSUBFP"]: r for r in _codes(COUSUBS.format(fips=S.fips, st=st.lower()),
                                                                 cache("codes", f"{st}.cousub.txt"))}
    school_names = {}
    for k in ("unsd", "scsd", "elsd"):
        g = get(GAZ.format(kind=k), cache("codes", f"gaz_{k}.zip"))
        if g is not None:
            with zipfile.ZipFile(g) as zf:
                for ln in zf.read(zf.namelist()[0]).decode("latin-1").splitlines()[1:]:
                    f = ln.split("	")
                    if len(f) > 2 and f[1][:2] == S.fips:
                        school_names.setdefault(f[1], f[2].strip())
    files = {}
    with zipfile.ZipFile(z) as zf:
        for name in zf.namelist():
            for k in ("INCPLACE_CDP", "MCD", "SDUNI", "SDSEC", "SDELM", "CD"):
                if name.endswith(f"_{k}.txt"):
                    rows = zf.read(name).decode("latin-1").splitlines()[1:]
                    files[k] = [r.split("|") for r in rows if r]
    blocks = {}

    def put(kind, rows, fn):
        for r in rows:
            v = fn(r)
            if v:
                blocks.setdefault(r[0], {})[kind] = v

    put("place", files.get("INCPLACE_CDP", []),
        lambda r: ("P" + r[1]) if len(r) > 1 and r[1] and places.get(r[1], {}).get("TYPE", "").startswith("INCORPORATED") else None)
    put("mcd", files.get("MCD", []),
        lambda r: ("M" + r[1] + r[2]) if len(r) > 2 and r[2] and cousub.get(r[1] + r[2], {}).get("FUNCSTAT") == "A" else None)
    for k in ("SDUNI", "SDSEC", "SDELM"):
        put(k, files.get(k, []), lambda r, k=k: (k[2] + r[1]) if len(r) > 1 and r[1] and r[1] not in ("99999", "") else None)
    idx = {g: i for i, g in enumerate(S.geoid)}
    out = {}
    for kind, pick in (("town", lambda b: b.get("place") or b.get("mcd")),
                       ("school", lambda b: b.get("SDUNI") or b.get("SDSEC") or b.get("SDELM"))):
        votes = [dict() for _ in range(S.d["n"])]
        for r in files["CD"]:  # every block of the state is listed in the congressional-district file
            i = idx.get(r[0][:12])
            if i is None:
                continue
            v = pick(blocks.get(r[0], {}))
            votes[i][v] = votes[i].get(v, 0) + 1
        names, lab = {}, np.full(S.d["n"], -1, np.int64)
        for i, vs in enumerate(votes):
            none = vs.pop(None, 0)
            best = max(vs.items(), key=lambda kv: kv[1]) if vs else (None, 0)
            if best[0] is not None and best[1] >= none:
                lab[i] = names.setdefault(best[0], len(names))
        label = {}
        for code in names:
            if code[0] == "P":
                label[code] = places.get(code[1:], {}).get("PLACENAME", code)
            elif code[0] == "M":
                label[code] = cousub.get(code[1:], {}).get("COUSUBNAME", code)
            else:
                label[code] = school_names.get(S.fips + code[1:], code)
        out[kind] = {"lab": lab, "names": [label[c] for c in names], "codes": list(names)}
    return out


def outlines(S: State, lab: np.ndarray, polys_ll) -> list:
    """Outlines (site x, y rings) of each group of units, dissolved from the block-group boundary polygons."""
    from shapely import unary_union
    rings = []
    for g in range(int(lab.max()) + 1 if lab.size and lab.max() >= 0 else 0):
        geoms = [polys_ll[i] for i in np.flatnonzero(lab == g) if polys_ll[i] is not None]
        if not geoms:
            continue
        u = unary_union(geoms).simplify(0.002)
        rings += _rings_xy(S, u)
    return rings


def _rings_xy(S: State, geom) -> list:
    out = []
    parts = getattr(geom, "geoms", [geom])
    for p in parts:
        if p.is_empty:
            continue
        if p.geom_type == "Polygon":
            lines = [p.exterior] + list(p.interiors)
        elif p.geom_type in ("LineString", "LinearRing"):
            lines = [p]
        elif p.geom_type == "MultiLineString":
            lines = list(p.geoms)
        else:
            continue
        for ln in lines:
            c = np.asarray(ln.coords)
            if len(c) < 2:
                continue
            x, y = S.to_xy(c[:, 0], c[:, 1])
            out.append([round(float(v), 1) for v in np.c_[x, y].ravel()])
    return out


def bg_polygons(S: State):
    """Shapely polygon (lon, lat) per site unit from the 2020 block-group boundary file (None when missing)."""
    from shapely.geometry import Polygon
    from shapely import unary_union
    from .graphs import boundary_files, read_dbf, read_polygons
    shp, shx, dbf = boundary_files()
    ids = read_dbf(dbf, ["GEOID"])["GEOID"]
    rec = {g: i for i, g in enumerate(ids) if g[:2] == S.fips}
    want = [rec.get(g) for g in S.geoid]
    rings = read_polygons(shp, shx, [r for r in want if r is not None])
    out = []
    for r in want:
        if r is None or not rings.get(r):
            out.append(None)
            continue
        shells, holes = [], []
        for ring in rings[r]:
            a = 0.5 * np.sum(ring[:-1, 0] * ring[1:, 1] - ring[1:, 0] * ring[:-1, 1])
            (shells if a < 0 else holes).append(Polygon(ring))  # shapefile shells are clockwise
        g = unary_union([s.buffer(0) for s in shells])
        if holes:
            g = g.difference(unary_union([h.buffer(0) for h in holes]))
        out.append(g)
    return out


# --------------------------------------------------------------------------- build

def build_state(st: str, log=print) -> dict:
    t0 = time.perf_counter()
    S = State(st)
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = np.r_[S.edges, S.bridges]
    m = len(S.edges)
    timing = {}

    t = time.perf_counter()
    dem = DEM(S.bbox)
    ridge = ridges(S, dem, pairs)
    relief = relief_png(S, dem, OUT / f"{st}.relief.png")
    timing["elevation"] = round(time.perf_counter() - t, 1)
    log(f"{st}: elevation {dem.tiles} tiles, {timing['elevation']}s")

    t = time.perf_counter()
    ws = watersheds(S)
    fl, wb = rivers(S)
    river = crossings(S, pairs, fl, "order")
    lake = crossings(S, pairs, wb, "areasqkm")
    river[m:] = 9  # water bridges cross open water
    timing["water"] = round(time.perf_counter() - t, 1)
    log(f"{st}: {len(fl)} flowlines, {len(wb)} waterbodies, {len(ws['huc8']['names'])} HUC8, "
        f"{len(ws['huc10']['names'])} HUC10, {timing['water']}s")

    t = time.perf_counter()
    counties = sorted({g[:5] for g in S.geoid})
    G, nodes = road_graph(S, counties)
    travel = drive_times(S, pairs, G, nodes, log)
    lo1, la1, lo2, la2 = S.segs(pairs)
    dist = km(lo1, la1, lo2, la2)
    timing["roads"] = round(time.perf_counter() - t, 1)
    log(f"{st}: road graph {G.shape[0]} nodes {G.nnz} links, {timing['roads']}s")

    t = time.perf_counter()
    ts = towns_schools(S)
    polys = bg_polygons(S)
    timing["towns"] = round(time.perf_counter() - t, 1)

    def ints(a, lo=None):
        return [int(v) for v in np.rint(a)]

    out = {
        "v": 1, "abbr": st, "n": S.d["n"], "edges": m, "bridges": len(S.bridges),
        "ridge": ints(ridge[:m]), "bridge_ridge": ints(ridge[m:]),
        "river": ints(river[:m]), "bridge_river": ints(river[m:]),
        "lake": ints(lake[:m]), "bridge_lake": ints(lake[m:]),
        "travel": ints(travel[:m]), "bridge_travel": ints(travel[m:]),
        "dist": ints(dist[:m] * 100), "bridge_dist": ints(dist[m:] * 100),
        "huc8": ws["huc8"]["lab"].tolist(), "huc10": ws["huc10"]["lab"].tolist(),
        "town": ts["town"]["lab"].tolist(), "school": ts["school"]["lab"].tolist(),
        "names": {"huc8": ws["huc8"]["names"], "huc10": ws["huc10"]["names"],
                  "town": ts["town"]["names"], "school": ts["school"]["names"]},
        "relief": relief,
        "counts": {
            "ridge_100m": int(np.sum(ridge[:m] >= 100)), "ridge_300m": int(np.sum(ridge[:m] >= 300)),
            "river_order4": int(np.sum(river[:m] >= 4)), "river_order5": int(np.sum(river[:m] >= 5)),
            "river_order6": int(np.sum(river[:m] >= 6)),
            "lake": int(np.sum(lake[:m] > 0)),
            "huc8": len(ws["huc8"]["names"]), "huc10": len(ws["huc10"]["names"]),
            "towns": len(ts["town"]["names"]), "units_in_towns": int(np.sum(ts["town"]["lab"] >= 0)),
            "school_districts": len(ts["school"]["names"]), "units_in_school_districts": int(np.sum(ts["school"]["lab"] >= 0)),
            "flowlines": len(fl), "waterbodies": len(wb), "dem_tiles": dem.tiles,
            "road_nodes": int(G.shape[0]), "road_links": int(G.nnz),
            "unreached_pairs": int(np.sum(travel >= UNREACHED)),
            "median_minutes_per_km": round(float(np.median(travel[:m] / 10 / np.maximum(dist[:m], 0.05))), 3),
        },
        "fit_err_km": round(S.fit_err_km, 3),
        "seconds": timing,
        "sources": {
            "elevation": "USGS 3DEP (via AWS Terrain Tiles, terrarium zoom 9; Mapzen/Linux Foundation, public domain in the US)",
            "watersheds": "USGS Watershed Boundary Dataset (hydro.nationalmap.gov wbd MapServer, HUC8 / HUC10), public domain",
            "rivers": f"USGS small-scale hydrography (1:1,000,000): streams of Strahler order >= {RIVER_MIN_ORDER} "
                      f"(streaml010g, from NHD) and lakes / reservoirs >= {LAKE_MIN_KM2} km2 (wtrbdyp010g), public domain",
            "roads": "U.S. Census Bureau TIGER/Line 2020 roads (every county), speeds by MTFCC: " + json.dumps(SPEED),
            "towns_schools": "U.S. Census Bureau 2020 Block Assignment Files and 2020 place / county-subdivision code lists",
            "outlines": "U.S. Census Bureau cartographic boundary file cb_2020_us_bg_500k (dissolved)",
        },
    }
    (OUT / f"{st}.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")

    t = time.perf_counter()
    from shapely import clip_by_rect
    box = S.bbox
    shapes = {"v": 1, "abbr": st, "rivers": [], "lakes": [], "huc8": [], "huc10": [], "town": [], "school": []}
    for f, g in zip(fl, _geoms(fl)):
        if g is None or g.is_empty:
            continue
        o = int(f["properties"].get("order") or 0)
        for r in _rings_xy(S, clip_by_rect(g.simplify(0.001), *box)):
            shapes["rivers"].append({"o": o, "p": r})
    for f, g in zip(wb, _geoms(wb)):
        if g is None or g.is_empty:
            continue
        shapes["lakes"] += _rings_xy(S, clip_by_rect(g.simplify(0.001), *box))
    for key in ("huc8", "huc10"):
        for g in ws[key]["geoms"]:
            shapes[key] += _rings_xy(S, clip_by_rect(g, *box))
    shapes["town"] = outlines(S, ts["town"]["lab"], polys)
    shapes["school"] = outlines(S, ts["school"]["lab"], polys)
    (OUT / f"{st}.shapes.json").write_text(json.dumps(shapes, separators=(",", ":")), encoding="utf-8")
    timing["shapes"] = round(time.perf_counter() - t, 1)
    log(f"{st}: done in {time.perf_counter() - t0:.0f}s ({timing})")
    return out["counts"]


# --------------------------------------------------------------------------- ensembles

NATURE_RIVER_ORDER = 4  # a river of at least this Strahler order on the USGS 1:1M map counts as a natural line
NATURE_RIDGE_M = 150  # a climb of at least this much between two neighbourhoods counts as a ridge
KEEP = {"nature": "links that cross no river (Strahler order 4+ on the USGS 1:1M map), lake, ridge (>= 150 m) or 8-digit watershed line",
        "huc8": "8-digit USGS watersheds (subbasins) kept whole", "town": "towns (municipalities) kept whole",
        "school": "school districts kept whole"}


def natural_lines(L: dict, pairs: np.ndarray, S_edges: np.ndarray, S_bridges: np.ndarray) -> np.ndarray:
    """Per row of ``pairs`` (unit pairs, any order): True when the link crosses a natural line."""
    m = len(S_edges)
    ridge = np.r_[L["ridge"], L["bridge_ridge"]]
    river = np.r_[L["river"], L["bridge_river"]]
    lake = np.r_[L["lake"], L["bridge_lake"]]
    huc = np.asarray(L["huc8"])
    allp = np.r_[S_edges, S_bridges]
    flag = (river >= NATURE_RIVER_ORDER) | (lake > 0) | (ridge >= NATURE_RIDGE_M) | (huc[allp[:, 0]] != huc[allp[:, 1]])
    look = {}
    for t, (i, j) in enumerate(allp.tolist()):
        look[(min(i, j), max(i, j))] = look.get((min(i, j), max(i, j)), False) or bool(flag[t])
    return np.array([look.get((min(i, j), max(i, j)), bool(huc[i] != huc[j])) for i, j in pairs.tolist()])


def attach(g, st: str, keep: str | None = None):
    """Add geo_layers statistics (and optionally a keep rule) to an ``ensemble.Graph`` loaded with graph="site"."""
    L = json.loads((OUT / f"{st}.json").read_text(encoding="utf-8"))
    d = json.loads((ROOT / "site" / "data" / f"{st}.json").read_text(encoding="utf-8"))
    nat = natural_lines(L, g.edges, np.asarray(d["edges"], np.int64).reshape(-1, 2),
                        np.asarray(d.get("bridges", []), np.int64).reshape(-1, 2))
    g.split_groups = {"huc8": np.asarray(L["huc8"], np.int64), "town": np.asarray(L["town"], np.int64),
                      "school": np.asarray(L["school"], np.int64)}
    g.edge_flags = {"natural": nat}
    if keep == "nature":
        g.keep_edges = ~nat
    elif keep in ("huc8", "town", "school"):
        g.keep_groups = g.split_groups[keep]
    elif keep is not None:
        raise ValueError(f"unknown keep rule {keep!r}")
    return g


def report() -> Path:
    """docs/GEO_LAYERS.md: what the layers hold, and the neutral maps that follow them (added 2026-11-14)."""
    ens = ROOT / "site" / "data" / "ensembles"

    def load(st, suf):
        f = ens / f"{st}{suf}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def med(d, el="pres2020"):
        if not d:
            return None
        h = {int(k_): v for k_, v in d["elections"][el]["seats_d_histogram"].items()}
        ks = sorted(h)
        c = np.cumsum([h[k_] for k_ in ks]) / sum(h.values())
        return ks[int(np.searchsorted(c, 0.5))]

    def q(d, key):
        return d[key]["quantiles"][2] if d and key in d else None

    VARS = [("", "plain"), (".county20", "counties"), (".nature20", "rivers & ridges"), (".huc20", "river basins"),
            (".town20", "towns"), (".school20", "school districts")]
    rows, layers = [], []
    for p in sorted(OUT.glob("[A-Z][A-Z].json")):
        L = json.loads(p.read_text(encoding="utf-8"))
        st = L["abbr"]
        c = L["counts"]
        layers.append((st, c))
        res = {suf: load(st, suf) for suf, _ in VARS}
        if not res[".nature20"] or res[".nature20"].get("districts", 1) < 2:
            continue
        ref = res[".nature20"]["reference"].get("official", {})
        rows.append({"st": st, "k": res[".nature20"]["districts"], "off": ref.get("pres2020", {}).get("seats_d"),
                     **{suf: med(res[suf]) for suf, _ in VARS},
                     "town_off": ref.get("town_splits"), "town_t": q(res[".town20"], "town_splits"),
                     "town_c": q(res[".nature20"], "town_splits"),
                     "school_off": ref.get("school_splits"), "school_s": q(res[".school20"], "school_splits"),
                     "nat_off": ref.get("natural_cut_edges"), "nat_n": q(res[".nature20"], "natural_cut_edges"),
                     "huc_off": ref.get("huc8_splits"), "huc_h": q(res[".huc20"], "huc8_splits")})
    idx_p = ens / "index.json"
    idx = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else {}
    bad = sorted({f"{r['st']} ({v})" for r in rows for v in ("nature20", "huc20", "town20", "school20")
                  if idx.get(r["st"], {}).get(v, {}).get("passed") is False})
    tot = lambda key: sum(r[key] for r in rows if r[key] is not None)
    f = lambda v, nd=0: "" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))
    lines = ["# Following the land and its communities", "", "## In short (for people)", "",
             "District lines can now be asked to follow nature and real communities, in two places:", "",
             "- **Draw toy:** six new sliders under \"Geography & communities\": mountains and ridges (USGS elevation), "
             "watersheds (USGS river basins), USGS rivers and lakes, drive time (Census road map), towns and school "
             "districts (Census). Each has a box that draws the layer on the map (shaded relief, rivers, basin lines, "
             "town and school-district outlines, slow-to-drive links).",
             "- **Neutral maps:** four new ensembles beside \"counties kept whole\": rivers & ridges followed, river "
             "basins kept whole, towns kept whole, school districts kept whole (ReCom, links inside weighted 20x, two "
             "agreeing chains per state).", "",
             f"Across {len(rows)} states (2020 votes, sum of median Democratic seats): plain {tot('')}, counties kept whole "
             f"{tot('.county20')}, rivers & ridges {tot('.nature20')}, river basins {tot('.huc20')}, towns {tot('.town20')}, "
             f"school districts {tot('.school20')}; official maps {tot('off')}. Following nature or communities moves the "
             "neutral result by a few seats nationally; the official maps sit well below every neutral version.",
             *([f"- Not passing the two-chain agreement check: {', '.join(bad)} (marked in the index)."] if bad else []),
             "- Pictures: `docs/samples/<ST>.techniques.geo.png` (the land, the communities, and seven ways to draw).", "",
             "| State | Seats | Official | Plain | Counties | Rivers & ridges | River basins | Towns | School districts | "
             "Towns split (official / towns kept) | School districts split (official / kept) | District-line links on natural lines (official / rivers & ridges) |",
             "| --- | --: | --: | --: | --: | --: | --: | --: | --: | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['st']} | {r['k']} | {f(r['off'])} | " + " | ".join(f(r[suf]) for suf, _ in VARS) +
                     f" | {f(r['town_off'])} / {f(r['town_t'])} | {f(r['school_off'])} / {f(r['school_s'])} | "
                     f"{f(r['nat_off'])} / {f(r['nat_n'])} |")
    lines += ["", "Democratic seats with 2020 presidential votes; neutral columns are ensemble medians; splits and links are "
              "medians for the ensembles.", "", "### What each layer holds", "",
              "| State | Ridge links 100 m+ | River links (order 4+) | Lake links | River basins | Watersheds | Towns | "
              "Block groups in a town | School districts | Road nodes | Median minutes per km |",
              "| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |"]
    for st, c in layers:
        lines.append(f"| {st} | {c['ridge_100m']} | {c.get('river_order4', '')} | {c['lake']} | {c['huc8']} | {c['huc10']} | "
                     f"{c['towns']} | {c['units_in_towns']} | {c['school_districts']} | {c['road_nodes']:,} | "
                     f"{c['median_minutes_per_km']} |")
    lines += ["", "---", "", "## For AI agents (detailed)", "",
              "- Build: `python -m redistricting_addons.geo_layers` (every state with 2+ districts; `--states`, "
              "`--workers`) -> `site/data/layers/geo/<ST>.json`, `<ST>.shapes.json`, `<ST>.relief.png`. Sources, "
              "formats and thresholds are in the module docstring. Downloads are cached under the redistricting cache "
              "(`geo/`): terrain tiles, WBD queries, the USGS 1:1M streams and waterbodies, every county's TIGER roads, "
              "Block Assignment Files, code lists, gazetteers. The road step dominates (one Dijkstra per block group "
              "on the county road graphs; North Carolina 3.6 million road nodes, about 9 minutes).",
              "- Draw: `site/addons/geo-sliders.js`, loaded by `ensemble-panel.js` on the Draw page. Wraps "
              "`DrawEngine.penalize` like `sci-slider.js` (multiplies link lengths by 1 + sum of lambda x factor and "
              "adds the same to `edgePen`). Factors: ridge min(1, m / 300); watershed / town / school 1 across a line; "
              "river 1 across a river of the chosen Strahler order or a lake; drive time min(3, max(0, r - 1)) with "
              "r = link minutes per km / the state's median.",
              "- Ensembles: `python -m redistricting_addons.batch --variants nature20 huc20 town20 school20` -> "
              "`site/data/ensembles/<ST>.<variant>.json`. `geo_layers.attach(graph, st, keep)` sets the new "
              "`Graph.keep_edges` (nature: links crossing no order-4+ river, lake, 150 m+ ridge or HUC8 line) or "
              "`Graph.keep_groups` (huc8 / town / school; -1 never kept), plus `split_groups` and `edge_flags`, so every "
              "plan records `huc8_splits`, `town_splits`, `school_splits` and `natural_cut_edges`. The panel offers the "
              "four as baselines (site neighbour graph only).",
              "- Report: `python -m redistricting_addons.geo_layers --report`. Pictures: "
              "`python -m redistricting_addons.samples --states --fifty \"\" --techniques-geo NC PA ...`.",
              "- Limits: towns and school districts go to a block group by most of its blocks, not by population (block "
              "counts need a Census API key; block shapefiles are 7 GB). The 1:1M river map keeps rivers of map-scale "
              "Strahler order 4 or more (smaller creeks are not lines). Ridges are measured along the straight link between "
              "population centres (about 240 m elevation pixels), so a long rural link that crosses several ridges "
              "records the highest. Edges are the site's Delaunay links, not shared borders.", ""]
    out = ROOT / "docs" / "GEO_LAYERS.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def all_states():
    return sorted(p.stem for p in (ROOT / "site" / "data").glob("[A-Z][A-Z].json") if p.stem.isupper())


def _job(st):
    try:
        return st, build_state(st, log=lambda s: print(s, flush=True)), None
    except Exception as e:  # keep going; report at the end
        import traceback
        return st, None, traceback.format_exc()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m redistricting_addons.geo_layers", description=__doc__.split("\n\n")[0])
    ap.add_argument("--states", nargs="*", help="two-letter codes (default: every state with more than one district)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--report", action="store_true", help="only write docs/GEO_LAYERS.md from the built files and ensembles")
    a = ap.parse_args(argv)
    if a.report:
        print("wrote", report())
        return 0
    states = [s.upper() for s in a.states] if a.states else [
        s for s in all_states() if json.loads((ROOT / "site" / "data" / f"{s}.json").read_text(encoding="utf-8"))["seats"] > 1]
    bad = []
    if a.workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(a.workers) as ex:
            for st, counts, err in ex.map(_job, states):
                print(st, "OK" if err is None else "FAILED", flush=True)
                if err:
                    print(err, flush=True)
                    bad.append(st)
    else:
        for st in states:
            st, counts, err = _job(st)
            if err:
                print(err, flush=True)
                bad.append(st)
    print(f"built {len(states) - len(bad)} of {len(states)}" + (f"; failed: {' '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
