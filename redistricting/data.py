"""Input data: state table, apportionment, population units and state outlines.

Two inputs feed every plan, both fetched once and cached with a pinned hash:

* **Population units** -- the Census Bureau's *Centers of Population* file at
  block-group level (``CenPop<year>_Mean_BG.txt``): one row per block group with
  its population and population-weighted centroid. The default is **2020**:
  ``research/redistricting_2020/CenPop2020_Mean_BG.txt`` (50 states + DC,
  331,449,281 people; built from the CC0 CRAN mirror ``USpopcenters`` because
  census.gov is unreachable from the build host -- see
  ``research/redistricting_2020/build_cenpop2020.py``), copied into the cache
  and sha256-checked. ``year=2010`` selects the official 2010 file, fetched
  from a public GitHub mirror (its national total, 312,471,327 incl. Puerto
  Rico, matches the 2010 Census exactly). ``cenpop_path=`` overrides both.
* **State outlines** -- ``states-10m.json`` from the ``us-atlas`` npm package
  (Census cartographic boundaries, 1:10M, TopoJSON, ISC licence).

Nothing here uses election results, party registration, incumbent addresses or
race/ethnicity: the generator is blind to them by construction.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "STATES",
    "State",
    "seats",
    "state_by_abbr",
    "load_units",
    "load_state_outline",
    "decode_topojson",
    "Units",
]


@dataclass(frozen=True)
class State:
    fips: str
    abbr: str
    name: str
    seats_2010: int
    seats_2020: int


# U.S. House apportionment after the 2010 and 2020 Censuses (435 seats each).
_TABLE = """\
01 AL Alabama 7 7
02 AK Alaska 1 1
04 AZ Arizona 9 9
05 AR Arkansas 4 4
06 CA California 53 52
08 CO Colorado 7 8
09 CT Connecticut 5 5
10 DE Delaware 1 1
12 FL Florida 27 28
13 GA Georgia 14 14
15 HI Hawaii 2 2
16 ID Idaho 2 2
17 IL Illinois 18 17
18 IN Indiana 9 9
19 IA Iowa 4 4
20 KS Kansas 4 4
21 KY Kentucky 6 6
22 LA Louisiana 6 6
23 ME Maine 2 2
24 MD Maryland 8 8
25 MA Massachusetts 9 9
26 MI Michigan 14 13
27 MN Minnesota 8 8
28 MS Mississippi 4 4
29 MO Missouri 8 8
30 MT Montana 1 2
31 NE Nebraska 3 3
32 NV Nevada 4 4
33 NH New_Hampshire 2 2
34 NJ New_Jersey 12 12
35 NM New_Mexico 3 3
36 NY New_York 27 26
37 NC North_Carolina 13 14
38 ND North_Dakota 1 1
39 OH Ohio 16 15
40 OK Oklahoma 5 5
41 OR Oregon 5 6
42 PA Pennsylvania 18 17
44 RI Rhode_Island 2 2
45 SC South_Carolina 7 7
46 SD South_Dakota 1 1
47 TN Tennessee 9 9
48 TX Texas 36 38
49 UT Utah 4 4
50 VT Vermont 1 1
51 VA Virginia 11 11
53 WA Washington 10 10
54 WV West_Virginia 3 2
55 WI Wisconsin 8 8
56 WY Wyoming 1 1
"""

STATES: tuple[State, ...] = tuple(
    State(f, a, n.replace("_", " "), int(s10), int(s20))
    for f, a, n, s10, s20 in (line.split() for line in _TABLE.splitlines())
)
_BY_ABBR = {s.abbr: s for s in STATES}
_BY_FIPS = {s.fips: s for s in STATES}


def state_by_abbr(key: str) -> State:
    """Look a state up by postal abbreviation, FIPS code or full name."""
    k = key.strip()
    if k.upper() in _BY_ABBR:
        return _BY_ABBR[k.upper()]
    if k.zfill(2) in _BY_FIPS:
        return _BY_FIPS[k.zfill(2)]
    for s in STATES:
        if s.name.lower() == k.lower():
            return s
    raise KeyError(f"unknown state {key!r}")


def seats(state: State | str, year: int = 2020) -> int:
    """U.S. House seats apportioned to ``state`` after the ``year`` Census."""
    st = state if isinstance(state, State) else state_by_abbr(state)
    if year == 2020:
        return st.seats_2020
    if year == 2010:
        return st.seats_2010
    raise ValueError("apportionment is tabulated for 2010 and 2020 only")


# --------------------------------------------------------------------------- cache

CENPOP2010_URL = "https://raw.githubusercontent.com/cindyrzheng/CenPop/master/CenPop2010.txt"
CENPOP2010_SHA256 = "c6931fcc60d26d53144e8282aa05db475b9bf965fea48f7785c2d9b5ec6d4d96"
CENPOP2020_SHA256 = "9897a3bf9a2cf622f22af088f619fe5fa22c8fb2d404b175fff77cb19a77797a"
CENPOP2020_REPO_PATH = Path(__file__).resolve().parents[1] / "research" / "redistricting_2020" / "CenPop2020_Mean_BG.txt"
DEFAULT_YEAR = 2020
US_ATLAS_URL = "https://registry.npmjs.org/us-atlas/-/us-atlas-3.0.1.tgz"
US_ATLAS_SHA512 = (
    "c042190aad0898fbc66e54ddf2064ca8d3423e442c86e80c506ffc9e44965dbd"
    "36f97a8d151120f5ab4738a3fdc3aa6b2d94e9a9c2e14af7415bcd4c915dffd1"
)  # npm "integrity" sha512-wEIZCq0Im... in hex


def cache_dir() -> Path:
    root = os.environ.get("REDISTRICTING_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cache", "redistricting"
    )
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _fetch(url: str, dest: Path, algo: str, digest: str) -> Path:
    if dest.exists() and hashlib.new(algo, dest.read_bytes()).hexdigest() == digest:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "redistricting/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    got = hashlib.new(algo, blob).hexdigest()
    if got != digest:
        raise RuntimeError(f"{url}: {algo} mismatch (got {got[:16]}..., want {digest[:16]}...)")
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(blob)
    tmp.replace(dest)
    return dest


# --------------------------------------------------------------------------- units


@dataclass
class Units:
    """Population units (block groups) of one state."""

    geoid: np.ndarray  # str, 12-digit block-group GEOID
    county: np.ndarray  # str, 5-digit county FIPS
    pop: np.ndarray  # int64
    lon: np.ndarray
    lat: np.ndarray
    vintage: str  # e.g. "CenPop2010"

    def __len__(self) -> int:
        return self.pop.size


def _read_cenpop(text: str, fips: str, vintage: str) -> Units:
    rd = csv.reader(io.StringIO(text))
    header = [h.strip().upper() for h in next(rd)]
    col = {h: i for i, h in enumerate(header)}
    need = ["STATEFP", "COUNTYFP", "TRACTCE", "BLKGRPCE", "POPULATION", "LATITUDE", "LONGITUDE"]
    missing = [h for h in need if h not in col]
    if missing:
        raise ValueError(f"CenPop file lacks columns {missing}")
    rows = [r for r in rd if r and r[col["STATEFP"]].zfill(2) == fips]
    if not rows:
        raise ValueError(f"no block groups for state FIPS {fips}")
    g = lambda h: [r[col[h]].strip() for r in rows]  # noqa: E731
    st, co, tr, bg = g("STATEFP"), g("COUNTYFP"), g("TRACTCE"), g("BLKGRPCE")
    geoid = np.array([a.zfill(2) + b.zfill(3) + c.zfill(6) + d for a, b, c, d in zip(st, co, tr, bg)])
    county = np.array([a.zfill(2) + b.zfill(3) for a, b in zip(st, co)])
    return Units(
        geoid=geoid,
        county=county,
        pop=np.array(g("POPULATION"), dtype=np.int64),
        lon=np.array(g("LONGITUDE"), dtype=float),
        lat=np.array(g("LATITUDE"), dtype=float),
        vintage=vintage,
    )


_TEXT_CACHE: dict[str, str] = {}


def _cenpop2020() -> Path:
    """The pinned 2020 block-group file: from the cache, else copied from the repository."""
    dest = cache_dir() / "CenPop2020_Mean_BG.txt"
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == CENPOP2020_SHA256:
        return dest
    src = CENPOP2020_REPO_PATH
    if not src.exists():
        raise FileNotFoundError(
            f"2020 population file not found ({src}); run research/redistricting_2020/build_cenpop2020.py "
            "or pass cenpop_path= / --cenpop, or use year=2010")
    blob = src.read_bytes()
    got = hashlib.sha256(blob).hexdigest()
    if got != CENPOP2020_SHA256:
        raise RuntimeError(f"{src}: sha256 mismatch (got {got[:16]}..., want {CENPOP2020_SHA256[:16]}...)")
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(blob)
    tmp.replace(dest)
    return dest


def load_units(state: State | str, cenpop_path: str | os.PathLike | None = None, year: int = DEFAULT_YEAR) -> Units:
    """Block-group population units of ``state``.

    ``cenpop_path`` is a local Census *Centers of Population* block-group file
    (national, or one state's file). Without it, ``year`` picks the pinned
    2020 file (default) or the official 2010 file (downloaded, hash-pinned).
    """
    st = state if isinstance(state, State) else state_by_abbr(state)
    if cenpop_path is None and year == 2020:
        path, vintage = _cenpop2020(), "CenPop2020"
    elif cenpop_path is None and year == 2010:
        path = _fetch(CENPOP2010_URL, cache_dir() / "CenPop2010_Mean_BG.txt", "sha256", CENPOP2010_SHA256)
        vintage = "CenPop2010"
    elif cenpop_path is None:
        raise ValueError("population is available for 2010 and 2020 only")
    else:
        path = Path(cenpop_path)
        stem = path.stem
        vintage = stem.split("_")[0] if stem.lower().startswith("cenpop") else stem
    key = str(path)
    if key not in _TEXT_CACHE:
        _TEXT_CACHE.clear()
        _TEXT_CACHE[key] = path.read_bytes().decode("utf-8-sig", errors="replace")
    return _read_cenpop(_TEXT_CACHE[key], st.fips, vintage)


# --------------------------------------------------------------------------- outlines


def decode_topojson(topo: dict, obj: str) -> dict[str, list[list[list[tuple[float, float]]]]]:
    """Decode a TopoJSON object into ``{id: [polygon, ...]}``.

    Each polygon is a list of rings (exterior first), each ring a list of
    ``(lon, lat)``. Handles quantized (delta-encoded) and plain arcs.
    """
    tr = topo.get("transform")
    arcs: list[np.ndarray] = []
    for arc in topo["arcs"]:
        a = np.asarray(arc, dtype=float)[:, :2]
        if tr:
            a = np.cumsum(a, axis=0) * np.asarray(tr["scale"]) + np.asarray(tr["translate"])
        arcs.append(a)

    def ring(idx: list[int]) -> list[tuple[float, float]]:
        pts: list[np.ndarray] = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.append(a if not pts else a[1:])
        r = np.vstack(pts)
        return [tuple(p) for p in r]

    out: dict[str, list] = {}
    for geom in topo["objects"][obj]["geometries"]:
        t = geom.get("type")
        if t == "Polygon":
            polys = [geom["arcs"]]
        elif t == "MultiPolygon":
            polys = geom["arcs"]
        else:
            continue
        out[str(geom.get("id"))] = [[ring(r) for r in poly] for poly in polys]
    return out


_OUTLINES: dict | None = None


def _atlas_states() -> dict:
    global _OUTLINES
    if _OUTLINES is None:
        tgz = _fetch(US_ATLAS_URL, cache_dir() / "us-atlas-3.0.1.tgz", "sha512", US_ATLAS_SHA512)
        with tarfile.open(tgz, "r:gz") as tf:
            member = tf.getmember("package/states-10m.json")
            topo = json.load(tf.extractfile(member))
        _OUTLINES = decode_topojson(topo, "states")
    return _OUTLINES


def load_state_outline(state: State | str) -> list[list[list[tuple[float, float]]]]:
    """Polygons (lon/lat rings) of the state's 1:10M cartographic boundary."""
    st = state if isinstance(state, State) else state_by_abbr(state)
    return _atlas_states()[st.fips]
