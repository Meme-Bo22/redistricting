"""Third take (2026-11-25): every plan read from the stored, audited maps; seat histograms of each neutral set.
Second reel, take two: greyscale terrain per state (USGS 3DEP hillshade, rivers in pale grey) plus one transparent
overlay per district plan (filled by 2020 lean in strong red/blue, white borders), pixel-aligned so the page can
stack them. Usage: python scripts/reel/posters.py OUTDIR ST [ST ...]  (PYTHONPATH = the redistricting repo)."""
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

DATA = None
PLANS = [  # (key, label, source) -- every map read from the stored, audited files (docs/MAP_AUDIT.md)
    ("official", "Official map", "plans/{st}.official.census.json"),
    ("solver", "Fair Lines solver", "plans/{st}.solver.census.json"),
    ("recom1", "ReCom, plain", "ensembles/maps/{st}.census.json"),
    ("recom20", "ReCom, counties whole", "ensembles/maps/{st}.county20.census.json"),
    ("zip20", "ReCom, ZIP areas whole", "ensembles/maps/{st}.zip20.census.json"),
    ("sci.adjusted.compact", "Social ties (counties)", "sci/districts/{st}.adjusted.compact.census.json"),
    ("sci.zcta", "Social ties (ZIP)", "sci/districts/{st}.zcta.census.json"),
    ("geo:nature", "Rivers & ridges", "ensembles/maps/{st}.nature20.census.json"),
    ("geo:huc", "Watersheds whole", "ensembles/maps/{st}.huc20.census.json"),
    ("geo:town", "Towns whole", "ensembles/maps/{st}.town20.census.json"),
    ("geo:school", "School districts whole", "ensembles/maps/{st}.school20.census.json"),
]
ENS = {"recom1": "{st}.census.json", "recom20": "{st}.county20.census.json", "zip20": "{st}.zip20.census.json",
       "geo:nature": "{st}.nature20.census.json", "geo:huc": "{st}.huc20.census.json",
       "geo:town": "{st}.town20.census.json", "geo:school": "{st}.school20.census.json"}
IDX = {"recom1": "plain-census", "recom20": "county20-census", "zip20": "zip20-census", "geo:nature": "nature20-census",
       "geo:huc": "huc20-census", "geo:town": "town20-census", "geo:school": "school20-census"}


def plan_labels(st, key, src):
    from redistricting_addons.ensemble import ROOT
    p = ROOT / "site" / "data" / src.format(st=st)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return np.asarray(d["typical"] if "typical" in d else d["labels"])


def one(args):
    out_dir, st = args
    import ctypes
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    from scipy.ndimage import median_filter
    from shapely import unary_union
    from redistricting_addons import geo_layers as G
    from redistricting_addons.ensemble import ROOT

    out = Path(out_dir) / st
    out.mkdir(parents=True, exist_ok=True)
    S = G.State(st)
    d = S.d
    k = int(d["seats"])
    x0, y0, x1, y1 = S.xy_box
    size = 1500
    sc = max(x1 - x0, y1 - y0) / size
    w, h = int(math.ceil((x1 - x0) / sc)), int(math.ceil((y1 - y0) / sc))
    gx = x0 + (np.arange(w) + 0.5) * sc
    gy = y1 - (np.arange(h) + 0.5) * sc
    X, Y = np.meshgrid(gx, gy)
    lon, lat = S.to_ll(X.ravel(), Y.ravel())
    Z = G.DEM(S.bbox).at(lon, lat).reshape(h, w) / 1000.0
    med = median_filter(Z, size=5)
    Z = np.where(np.abs(Z - med) > 0.25, med, Z)
    inside = np.zeros(X.size, bool)
    for ring in S.outline:
        inside ^= MPath(ring).contains_points(np.c_[X.ravel(), Y.ravel()])
    inside = inside.reshape(h, w)
    zin = Z[inside]
    lo, hi = np.percentile(zin, 1), np.percentile(zin, 99.7)
    t = np.clip((Z - lo) / max(hi - lo, 0.05), 0, 1)
    dzdx, dzdy = np.gradient(Z, sc, axis=1), -np.gradient(Z, sc, axis=0)
    zf = 2.2 if hi - lo > 1.0 else 6.0
    nx, ny = -zf * dzdx, -zf * dzdy
    hs = (nx * -0.5 + ny * 0.5 + 0.7071) / np.sqrt(nx * nx + ny * ny + 1)
    grey = np.clip(0.50 + 0.18 * t + 0.42 * (np.clip(hs, 0, 1) - 0.7), 0.08, 0.97)
    rgba = np.dstack([grey, grey, grey, inside.astype(float)])

    pad = 0.02 * max(x1 - x0, y1 - y0)
    W, H = w + int(2 * pad / sc), h + int(2 * pad / sc)

    def canvas(transparent):
        fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(x0 - pad, x0 - pad + W * sc)
        ax.set_ylim(y1 + pad - H * sc, y1 + pad)
        ax.set_aspect("equal")
        ax.axis("off")
        if transparent:
            fig.patch.set_alpha(0)
            ax.patch.set_alpha(0)
        else:
            fig.patch.set_facecolor("#111316")
        return fig, ax

    verts, codes = [], []
    for ring in S.outline:
        verts += ring.tolist() + [ring[0].tolist()]
        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(ring) - 1) + [MPath.CLOSEPOLY]
    outline_path = MPath(verts, codes)

    def clip_all(ax):
        clip = PathPatch(outline_path, transform=ax.transData, facecolor="none", edgecolor="none")
        ax.add_patch(clip)
        for art in ax.lines + ax.patches + ax.collections + ax.images:
            if art is not clip:
                art.set_clip_path(clip)

    xy = lambda f: (np.asarray(f[0::2]), np.asarray(f[1::2]))
    sh = json.loads((G.OUT / f"{st}.shapes.json").read_text(encoding="utf-8"))
    fig, ax = canvas(False)
    ax.imshow(rgba, extent=(x0, x0 + w * sc, y1 - h * sc, y1), interpolation="bilinear")
    for f in sh["lakes"]:
        ax.fill(*xy(f), color="#2a2e33", lw=0)
    for f in sh["rivers"]:
        ax.plot(*xy(f["p"]), color="#e9edf0", alpha=0.55, lw={4: 0.4, 5: 0.7, 6: 1.1}.get(f["o"], 1.6))
    clip_all(ax)
    for ring in S.outline:
        ax.plot(ring[:, 0], ring[:, 1], color="#d8d8d8", lw=1.2)
    fig.savefig(out / "terrain.png", dpi=100, facecolor="#111316")
    plt.close(fig)

    polys = G.bg_polygons(S)
    e = d["elections"]["pres2020"]
    vd, vr = np.asarray(e["d"], float), np.asarray(e["r"], float)
    info = {"st": st, "name": d["name"], "k": k, "w": W, "h": H, "plans": {}}
    for key, label, src in PLANS:
        try:
            lab = plan_labels(st, key, src)
        except Exception as ex:  # noqa: BLE001
            print(st, key, "skipped:", ex, flush=True)
            lab = None
        if lab is None or len(lab) != len(polys):
            continue
        lab = lab.astype(int)
        D = np.bincount(lab, weights=vd, minlength=k)
        R = np.bincount(lab, weights=vr, minlength=k)
        share = D / np.maximum(D + R, 1)
        fig, ax = canvas(True)
        rings_all = []
        for g in range(k):
            geoms = [polys[i] for i in np.flatnonzero(lab == g) if polys[i] is not None]
            if not geoms:
                continue
            u = unary_union(geoms).simplify(0.002)
            s = share[g]
            col = "#2563eb" if s > 0.5 else "#dc2626"
            a = min(0.82, 0.38 + abs(s - 0.5) * 1.6)
            for part in getattr(u, "geoms", [u]):
                if part.geom_type != "Polygon" or part.is_empty:
                    continue
                ex_ = np.asarray(part.exterior.coords)
                px, py = S.to_xy(ex_[:, 0], ex_[:, 1])
                vs, cs = [np.c_[px, py]], [[MPath.MOVETO] + [MPath.LINETO] * (len(px) - 2) + [MPath.CLOSEPOLY]]
                for hole in part.interiors:
                    hc = np.asarray(hole.coords)
                    hx, hy = S.to_xy(hc[:, 0], hc[:, 1])
                    vs.append(np.c_[hx, hy])
                    cs.append([MPath.MOVETO] + [MPath.LINETO] * (len(hx) - 2) + [MPath.CLOSEPOLY])
                ax.add_patch(PathPatch(MPath(np.vstack(vs), np.concatenate(cs)), facecolor=col, alpha=a, lw=0))
                rings_all += [v for v in vs]
        for r in rings_all:
            ax.plot(r[:, 0], r[:, 1], color="#ffffff", lw=1.0)
        clip_all(ax)
        fig.savefig(out / f"{key.replace(':', '-')}.png", dpi=100, transparent=True)
        plt.close(fig)
        info["plans"][key] = {"label": label, "file": f"{key.replace(':', '-')}.png", "seats_d": int(np.sum(share > 0.5))}
    index = json.loads((ROOT / "site" / "data" / "ensembles" / "index.json").read_text(encoding="utf-8")).get(st, {})
    info["hist"] = {}
    for key, fn in ENS.items():
        p = ROOT / "site" / "data" / "ensembles" / fn.format(st=st)
        if not p.exists():
            continue
        ens = json.loads(p.read_text(encoding="utf-8"))
        hist = {int(a): b for a, b in ens["elections"]["pres2020"]["seats_d_histogram"].items()}
        info["hist"][key] = {"h": hist, "settled": bool(index.get(IDX[key], {}).get("passed", True)),
                             "n": int(sum(hist.values()))}
    hist = info["hist"].get("recom20", {}).get("h") or {}
    ks = sorted(hist)
    c = np.cumsum([hist[a] for a in ks]) / max(1, sum(hist.values()))
    info["neutral_median_d"] = ks[int(np.searchsorted(c, 0.5))] if ks else None
    tot_d, tot_r = vd.sum(), vr.sum()
    info["vote_d"] = round(float(tot_d / (tot_d + tot_r)) * 100, 1)
    (out / "info.json").write_text(json.dumps(info), encoding="utf-8")
    return st


if __name__ == "__main__":
    out_dir, sts = sys.argv[1], sys.argv[2:]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    todo = [s for s in sts if not (Path(out_dir) / s / "info.json").exists()]
    with ProcessPoolExecutor(int(__import__('os').environ.get('WORKERS', '2'))) as ex:
        for st in ex.map(one, [(out_dir, s) for s in todo]):
            print("done", st, flush=True)
