"""Matplotlib maps of a plan (lazy import; ``pip install matplotlib``)."""
from __future__ import annotations

import numpy as np
import shapely

__all__ = ["PALETTE", "district_colors", "render_plan", "render_grid"]

# Deliberately non-partisan: no red/blue pair, muted, distinguishable in both themes.
PALETTE = ["#8dd3c7", "#fdd49e", "#bebada", "#b3de69", "#fccde5", "#d9d9d9", "#ccebc5", "#ffed6f"]


def district_colors(districts) -> np.ndarray:
    """Greedy (largest-degree-first) colouring so touching districts differ."""
    k = len(districts)
    tree = shapely.STRtree(districts)
    a, b = tree.query(districts, predicate="intersects")
    nbr = [set() for _ in range(k)]
    for i, j in zip(a, b):
        if i != j:
            nbr[i].add(j)
            nbr[j].add(i)
    col = np.full(k, -1)
    for d in sorted(range(k), key=lambda i: -len(nbr[i])):
        used = {col[j] for j in nbr[d]}
        col[d] = next(c for c in range(len(PALETTE) * 4) if c not in used) % len(PALETTE)
    return col


def _patches(geom, **kw):
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    out = []
    for poly in shapely.get_parts(geom):
        if poly.geom_type != "Polygon" or poly.is_empty:
            continue
        verts, codes = [], []
        for ring in [poly.exterior, *poly.interiors]:
            xy = np.asarray(ring.coords)
            verts.append(xy)
            codes += [Path.MOVETO] + [Path.LINETO] * (len(xy) - 2) + [Path.CLOSEPOLY]
        out.append(PathPatch(Path(np.vstack(verts), codes), **kw))
    return out


def _draw(ax, plan, labels_on=True, lw=0.6):
    from matplotlib.collections import PatchCollection

    cols = district_colors(plan.districts)
    patches, faces = [], []
    for d, g in enumerate(plan.districts):
        ps = _patches(g)
        patches += ps
        faces += [PALETTE[cols[d]]] * len(ps)
    pc = PatchCollection(patches, facecolor=faces, edgecolor="#333333", linewidth=lw)
    ax.add_collection(pc)
    for p in _patches(plan.mesh.domain, fill=False, edgecolor="#111111", linewidth=lw * 1.4):
        ax.add_patch(p)
    if labels_on:
        fs = max(4, 9 - plan.k // 10)
        for d, g in enumerate(plan.districts):
            pt = shapely.point_on_surface(g) if not g.is_empty else None
            if pt is not None:
                ax.text(pt.x, pt.y, str(d + 1), ha="center", va="center", fontsize=fs, color="#111111")
    minx, miny, maxx, maxy = shapely.bounds(plan.mesh.domain)
    pad = 0.02 * max(maxx - minx, maxy - miny)
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.axis("off")


def render_plan(plan, path, dpi: int = 150):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = plan.stats
    fig, ax = plt.subplots(figsize=(8, 8))
    _draw(ax, plan)
    ax.set_title(
        f"{plan.state.name}: {plan.k} districts ({plan.units.vintage} block groups)\n"
        f"max |dev| {s.max_abs_deviation_pct:.2f}%  ·  Polsby-Popper {s.mean_polsby_popper:.2f}  ·  "
        f"Reock {s.mean_reock:.2f}  ·  counties split {s.counties_split}",
        fontsize=10,
    )
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_grid(plans, path, cols: int = 10, dpi: int = 110):
    """Small multiples of many plans (e.g. all 50 states)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = int(np.ceil(len(plans) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.0, rows * 2.2))
    for ax in np.ravel(axes):
        ax.axis("off")
    for ax, p in zip(np.ravel(axes), plans):
        _draw(ax, p, labels_on=False, lw=0.25)
        ax.set_title(f"{p.state.abbr} ({p.k})", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
