"""Equal-population, compact, contiguous partition of a population mesh.

Three stages, each a standard tool of meshing / domain decomposition:

1. **Balanced geodesic centroidal power diagram** (capacity-constrained Lloyd
   relaxation). Seeded by recursive coordinate bisection, alternate (a) the
   *transportation problem* "assign units to the k centres minimising
   population-weighted squared distance, P/k people each" -- solved in its
   dual, whose optimum is a power diagram (additively weighted Voronoi), by
   damped Newton with a district-graph-Laplacian Jacobian -- and (b) moving
   every centre to its district's population centroid. Distances are
   geodesic along the population mesh. The fixed point is a capacity-
   constrained centroidal Voronoi tessellation: the relaxation that smooths
   meshes, with population as the density (Hess et al. 1965; Du, Faber &
   Gunzburger 1999; Cohen-Addad, Klein & Young 2018).
2. **Contiguity on the mesh graph.** Convex cells in the plane can still be cut
   by water or a state's concavities; every district keeps its most populous
   connected piece over the population mesh and detached pieces join the
   neighbour they share most edges with.
3. **Boundary refinement** (Fiduccia-Mattheyses style, as in METIS): single
   boundary units move between neighbouring districts whenever the move lowers
   the sum of squared population deviations, the cheapest move in moment of
   inertia (and county splits) first, never disconnecting a district.

Inputs are positions and head-counts only, so the result cannot encode a
partisan or racial target; everything is deterministic, so plans are reproducible.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

__all__ = ["PartitionResult", "partition", "balanced_assign", "kmeans_pp", "random_centers"]


@dataclass
class PartitionResult:
    labels: np.ndarray
    centers: np.ndarray
    lloyd_iterations: int
    moves: int
    history: list = field(default_factory=list)  # per-iteration inertia


def kmeans_pp(xy: np.ndarray, w: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """Population-weighted k-means++ seeding."""
    p = w / w.sum()
    centers = [xy[rng.choice(len(xy), p=p)]]
    d2 = np.sum((xy - centers[0]) ** 2, axis=1)
    for _ in range(1, k):
        q = w * d2
        if q.sum() <= 0:
            q = w.astype(float).copy()
        c = xy[rng.choice(len(xy), p=q / q.sum())]
        centers.append(c)
        d2 = np.minimum(d2, np.sum((xy - c) ** 2, axis=1))
    return np.array(centers)


def random_centers(xy: np.ndarray, w: np.ndarray, k: int, rng: np.random.Generator, min_sep: float = 0.5) -> np.ndarray:
    """``k`` distinct units drawn with probability proportional to population, at least ``min_sep`` apart.

    The same draw as the Fair Lines toy's "random starting centres" (page.html ``randomCenters``).
    """
    n = len(xy)
    p = np.maximum(w, 0).astype(float)
    p = p / p.sum() if p.sum() > 0 else np.full(n, 1.0 / n)
    chosen: list[int] = []
    cand = rng.choice(n, size=min(n, 64 * k + 400), p=p)
    for c in cand:
        if len(chosen) == k:
            break
        if chosen and np.min(np.sum((xy[chosen] - xy[c]) ** 2, axis=1)) < min_sep ** 2:
            continue
        if c not in chosen:
            chosen.append(int(c))
    for c in rng.permutation(n):  # fallback for tiny or degenerate inputs
        if len(chosen) == k:
            break
        if c not in chosen:
            chosen.append(int(c))
    return xy[np.array(chosen)].astype(float)


def rcb(xy, w, k: int) -> np.ndarray:
    """Recursive coordinate bisection by population along the principal axis.

    The classic mesh-partitioning seed: split the units at the weighted
    quantile ``floor(k/2)/k`` along their principal axis, recurse on both sides.
    Deterministic, balanced to within one unit per cut, and roughly compact.
    """
    labels = np.zeros(len(xy), np.int64)

    def rec(ids, kk, base):
        if kk == 1 or ids.size == 0:
            labels[ids] = base
            return
        p, q = xy[ids], w[ids]
        ww = q + 1e-9
        mu = np.average(p, axis=0, weights=ww)
        cov = np.cov((p - mu).T, aweights=ww) if ids.size > 2 else np.eye(2)
        axis = np.linalg.eigh(cov)[1][:, -1]
        t = (p - mu) @ axis
        o = np.argsort(t, kind="stable")
        k1 = kk // 2
        cum = np.cumsum(q[o])
        cut = int(np.searchsorted(cum, cum[-1] * k1 / kk)) + 1
        cut = min(max(cut, 1), ids.size - 1)
        rec(ids[o[:cut]], k1, base)
        rec(ids[o[cut:]], kk - k1, base + k1)

    rec(np.arange(len(xy)), k, 0)
    return labels


def balanced_assign(dist2, w, v=None, tol: float = 0.002, m: int = 12, max_steps: int | None = None):
    """Equal-population power-diagram assignment by exact dual coordinate ascent.

    Units go to ``argmin_j |x - c_j|^2 - v_j`` (a power diagram with weights
    ``v``). This is the dual of the transportation problem "assign units to
    centres minimising population-weighted squared distance with P/k people
    each" (``dist2`` is the n-by-k squared distance, Euclidean or geodesic).
    Each step takes the worst-balanced district and shifts its weight by
    exactly the margin that sheds (or gains) the population it is off by --
    the units nearest to the moving power boundary transfer first. Only units
    that have that district among their ``m`` nearest centres are touched.
    Returns ``(labels, v)``; ``v`` warm-starts the next Lloyd iteration.
    """
    n, k = dist2.shape
    v = np.zeros(k) if v is None else np.asarray(v, float).copy()
    m = min(max(m, 2), k)
    while True:
        (labels, v), starved = _ascent(dist2, w, v, tol, m, max_steps)
        if not starved or m >= k:
            return labels, v
        m = min(2 * m, k)


def _newton(d2, idx, w, v, target, tol, iters: int = 150, band_q: float = 0.2, lm: float = 0.05):
    """Damped, regularised Newton on the transport dual (Kitagawa, Merigot & Thibert 2019).

    The Jacobian of district populations w.r.t. the power weights is a graph
    Laplacian over adjacent districts, weighted by the population in a thin
    band on each shared power boundary. Solving it moves every weight at once,
    so imbalance diffuses across the district graph (cf. Hu & Blake diffusion
    load balancing) instead of hopping one district per step. Levenberg-
    Marquardt damping, a per-weight trust region and a backtracking line search
    keep it stable on discrete units; it stops when no step helps.
    """
    n, m = idx.shape
    k = len(v)
    rows = np.arange(n)

    def state(vv):
        s = d2 - vv[idx]
        o = np.argpartition(s, 1, axis=1)[:, :2]
        s0, s1 = s[rows, o[:, 0]], s[rows, o[:, 1]]
        swap = s1 < s0
        b = np.where(swap, o[:, 1], o[:, 0])
        c = np.where(swap, o[:, 0], o[:, 1])
        lab = idx[rows, b]
        return lab, idx[rows, c], np.abs(s1 - s0), np.bincount(lab, weights=w, minlength=k)

    live = w > 0
    lab, sec, gap, pops = state(v)
    err = np.max(np.abs(pops / target - 1))
    for _ in range(iters):
        if err <= tol or not live.any():
            break
        eps = max(float(np.quantile(gap[live], band_q)), 1e-12)
        band = (gap < eps) & live
        cw = w[band] / eps
        K = np.zeros((k, k))
        np.add.at(K, (lab[band], sec[band]), -cw)
        np.add.at(K, (sec[band], lab[band]), -cw)
        dg = -K.sum(axis=1)
        K[np.diag_indices(k)] = dg
        K += lm * np.diag(dg + dg.mean() + 1e-12)
        dv = np.linalg.solve(K, target - pops)
        dv = np.clip(dv - dv.mean(), -4 * eps, 4 * eps)
        ss0 = np.sum((pops / target - 1) ** 2)
        for step in (1.0, 0.5, 0.25, 0.125, 0.0625):
            r = state(v + step * dv)
            e = np.max(np.abs(r[3] / target - 1))
            if np.sum((r[3] / target - 1) ** 2) < ss0 or e < err:
                v = v + step * dv
                lab, sec, gap, pops = r
                err = e
                break
        else:
            break
    return v


def _best(labels, v, pops, target, best_err, best_lab, best_v):
    if np.max(np.abs(pops / target - 1)) <= best_err:
        return labels.astype(np.int64), v
    return best_lab.astype(np.int64), best_v


def _ascent(dist2, w, v, tol, m, max_steps):
    n, k = dist2.shape
    target = w.sum() / k
    idx = np.argpartition(dist2, m - 1, axis=1)[:, :m] if m < k else np.tile(np.arange(k), (n, 1))
    d2 = np.take_along_axis(dist2, idx, axis=1)
    v = _newton(d2, idx, w, v, target, tol)
    # rows (and slot) in which each district is a candidate
    flat = idx.ravel()
    order = np.argsort(flat, kind="stable")
    bounds = np.searchsorted(flat[order], np.arange(k + 1))
    cand_rows = [order[bounds[j]:bounds[j + 1]] // m for j in range(k)]
    cand_slot = [order[bounds[j]:bounds[j + 1]] % m for j in range(k)]
    s = d2 - v[idx]
    best = np.argmin(s, axis=1)
    labels = idx[np.arange(n), best]
    pops = np.bincount(labels, weights=w, minlength=k)
    best_err, best_lab, best_v = np.inf, labels.copy(), v.copy()
    max_steps = max_steps if max_steps is not None else 10 * k
    for _ in range(max_steps):
        dev = pops / target - 1
        j = int(np.argmax(np.abs(dev)))
        if abs(dev[j]) < best_err:
            best_err, best_lab, best_v = abs(dev[j]), labels.copy(), v.copy()
        if abs(dev[j]) <= tol:
            break
        need = abs(pops[j] - target)
        r, sl = cand_rows[j], cand_slot[j]
        if r.size == 0:
            return _best(labels, v, pops, target, best_err, best_lab, best_v), True
        sr = s[r]
        sj = sr[np.arange(r.size), sl]
        lr = labels[r]
        if dev[j] > 0:  # shed: lowering v_j by delta releases members with margin < delta
            sel = lr == j
            other = sr[sel].copy()
            other[np.arange(sel.sum()), sl[sel]] = np.inf
            margin = other.min(axis=1) - sj[sel]
        else:  # gain: raising v_j by delta captures non-members with margin < delta
            sel = lr != j
            margin = sj[sel] - sr[sel].min(axis=1)
        if margin.size == 0:
            return _best(labels, v, pops, target, best_err, best_lab, best_v), True
        wi = w[r[sel]]
        o = np.argsort(margin, kind="stable")
        cum = np.cumsum(wi[o])
        if cum[-1] < need:  # candidate pool cannot cover the deficit/excess: widen it
            return _best(labels, v, pops, target, best_err, best_lab, best_v), True
        t = int(np.argmin(np.abs(cum - need)))
        lo = margin[o[t]]
        hi = margin[o[t + 1]] if t + 1 < o.size else lo + 1.0
        delta = 0.5 * (lo + hi) if hi > lo else lo + 1e-9 * (1 + abs(lo))
        v[j] += -delta if dev[j] > 0 else delta
        # incremental update of the touched rows
        s[r, sl] = d2[r, sl] - v[j]
        nb = np.argmin(s[r], axis=1)
        newlab = idx[r, nb]
        ch = newlab != lr
        if ch.any():
            np.subtract.at(pops, lr[ch], w[r[ch]])
            np.add.at(pops, newlab[ch], w[r[ch]])
            labels[r[ch]] = newlab[ch]
        best[r] = nb
    return _best(labels, v, pops, target, best_err, best_lab, best_v), False


def _inertia(xy, w, labels, centers) -> float:
    return float(np.sum(w * np.sum((xy - centers[labels]) ** 2, axis=1)))


def _centroids(xy, w, labels, k, fallback):
    tot = np.bincount(labels, weights=w, minlength=k)
    cx = np.bincount(labels, weights=w * xy[:, 0], minlength=k)
    cy = np.bincount(labels, weights=w * xy[:, 1], minlength=k)
    c = fallback.copy()
    ok = tot > 0
    c[ok, 0], c[ok, 1] = cx[ok] / tot[ok], cy[ok] / tot[ok]
    return c


def _dist2(xy, centers, graph):
    """Squared distance from every unit to every centre: Euclidean, or geodesic over ``graph``."""
    if graph is None:
        return np.sum((xy[:, None, :] - centers[None, :, :]) ** 2, axis=2)
    _, src = cKDTree(xy).query(centers)
    d = dijkstra(graph, directed=False, indices=src).T
    big = np.nanmax(np.where(np.isfinite(d), d, np.nan)) * 10 if np.isfinite(d).any() else 1.0
    return np.where(np.isfinite(d), d, big) ** 2


def lloyd_power(xy, w, k, rng, graph=None, max_iter: int = 40, tol_km: float = 0.05, tol: float = 0.002,
                init: str = "rcb"):
    """Capacity-constrained Lloyd iteration; returns (labels, centers, iters, history).

    With ``graph`` (edge weights = lengths) distances are geodesic along the
    population mesh, so districts flow around bays and lakes instead of across
    them -- a geodesic centroidal Voronoi tessellation of the mesh.

    ``init="rcb"`` (default) starts from the centroids of a recursive
    coordinate bisection, plus a 1 m jitter drawn from ``rng`` -- so different
    seeds give (nearly) the same plan. ``init="random"`` starts from ``k``
    population-weighted random units drawn from ``rng``: different seeds give
    genuinely different local optima (for ensembles / seed-sensitivity runs).
    """
    if init == "random":
        if rng is None:
            raise ValueError("init='random' needs an rng")
        centers = random_centers(xy, w, k, rng)
    elif init == "rcb":
        centers = _centroids(xy, w, rcb(xy, w, k), k, xy[:k].astype(float))
        if rng is not None:  # optional tiny deterministic jitter, for n_init restarts
            centers = centers + rng.normal(scale=1e-3, size=centers.shape)
    else:
        raise ValueError(f"unknown init {init!r} (use 'rcb' or 'random')")
    labels, v = None, None
    hist = []
    it = 0
    for it in range(1, max_iter + 1):
        # warm start: weights are relative to centres, so keep them as centres drift
        new, v = balanced_assign(_dist2(xy, centers, graph), w, v=v, tol=max(tol, 0.01))
        c = _centroids(xy, w, new, k, centers)
        shift = float(np.max(np.linalg.norm(c - centers, axis=1)))
        stable = labels is not None and np.array_equal(new, labels)
        labels, centers = new, c
        hist.append(_inertia(xy, w, labels, centers))
        if shift < tol_km or stable or (it >= 8 and abs(hist[-2] - hist[-1]) < 1e-4 * hist[-1]):
            break
    labels, v = balanced_assign(_dist2(xy, centers, graph), w, v=v, tol=tol)
    hist.append(_inertia(xy, w, labels, centers))
    return labels, centers, it, hist


def enforce_contiguity(labels, adj: sparse.csr_matrix, w, k, max_rounds: int = 200):
    """Give every district a single connected piece over ``adj``."""
    labels = labels.copy()
    coo = adj.tocoo()
    r, c = coo.row, coo.col
    for _ in range(max_rounds):
        same = labels[r] == labels[c]
        g = sparse.csr_matrix((np.ones(same.sum()), (r[same], c[same])), shape=adj.shape)
        ncomp, comp = connected_components(g, directed=False)
        cpop = np.bincount(comp, weights=w + 1e-9, minlength=ncomp)  # tiny term: break ties by size
        cdist = np.zeros(ncomp, dtype=np.int64)
        cdist[comp] = labels
        main = np.full(k, -1)
        best = np.full(k, -1.0)
        for ci in range(ncomp):
            d = cdist[ci]
            if cpop[ci] > best[d]:
                best[d], main[d] = cpop[ci], ci
        orphans = np.setdiff1d(np.arange(ncomp), main[main >= 0])
        if orphans.size == 0:
            return labels
        # Re-home the smallest orphan piece first, to its most-shared neighbour.
        oi = orphans[np.argmin(cpop[orphans])]
        members = np.flatnonzero(comp == oi)
        mask = np.zeros(len(labels), bool)
        mask[members] = True
        cross = mask[r] & ~mask[c]
        nb = labels[c[cross]]
        nb = nb[nb != labels[members[0]]]
        if nb.size == 0:  # isolated in graph; leave (cannot happen on a connected mesh)
            continue
        labels[members] = np.bincount(nb).argmax()
    return labels


def _connected_without(u, district, labels, indptr, indices) -> bool:
    """Would ``district`` stay connected if unit ``u`` left it?"""
    nbrs = [v for v in indices[indptr[u] : indptr[u + 1]] if labels[v] == district]
    if len(nbrs) <= 1:
        return True
    goal = set(nbrs[1:])
    seen = {u, nbrs[0]}
    dq = deque([nbrs[0]])
    while dq and goal:
        a = dq.popleft()
        for v in indices[indptr[a] : indptr[a + 1]]:
            if v not in seen and labels[v] == district:
                seen.add(v)
                goal.discard(v)
                dq.append(v)
    return not goal


def refine(labels, xy, w, k, adj: sparse.csr_matrix, county=None, tol: float = 0.001,
           county_weight: float = 0.5, max_passes: int = 2000, movable=None):
    """Batched FM-style boundary refinement; returns (labels, moves).

    Each pass scores every boundary move (unit u: district a -> adjacent b)
    that lowers the sum of squared population deviations, then applies the
    cheapest ones -- by moment-of-inertia increase, plus ``county_weight`` per
    county newly split -- greedily, at most one move per district per pass so
    every applied move's gain stays exact (the parallel-FM trick of
    partitioners like METIS/ParMETIS). A move is skipped if it would
    disconnect its source district. Stops at ``tol`` or when nothing helps.
    ``movable`` (optional boolean mask) restricts which units may change district.
    """
    labels = labels.copy()
    target = w.sum() / k
    pops = np.bincount(labels, weights=w, minlength=k).astype(float)
    sx = np.bincount(labels, weights=w * xy[:, 0], minlength=k)
    sy = np.bincount(labels, weights=w * xy[:, 1], minlength=k)
    indptr, indices = adj.indptr, adj.indices
    coo = sparse.triu(adj, 1).tocoo()
    er, ec = coo.row, coo.col
    if county is not None:
        _, cid = np.unique(county, return_inverse=True)
        cid = cid.ravel()
        cd = sparse.coo_matrix((w, (cid, labels)), shape=(cid.max() + 1, k)).toarray()
    c0 = np.column_stack([sx, sy]) / np.maximum(pops, 1e-12)[:, None]
    r2 = np.average(np.sum((xy - c0[labels]) ** 2, axis=1), weights=np.maximum(w, 1e-12)) or 1.0
    moves = 0
    for _ in range(max_passes):
        dev = pops / target - 1
        if np.max(np.abs(dev)) <= tol:
            break
        cut = labels[er] != labels[ec]
        u = np.r_[er[cut], ec[cut]]
        dst = np.r_[labels[ec[cut]], labels[er[cut]]]
        if u.size == 0:
            break
        pair = np.unique(np.column_stack([u, dst]), axis=0)
        u, dst = pair[:, 0], pair[:, 1]
        src = labels[u]
        wu = w[u]
        dsq = (pops[src] - wu - target) ** 2 + (pops[dst] + wu - target) ** 2 - (pops[src] - target) ** 2 - (pops[dst] - target) ** 2
        good = (wu > 0) & (dsq < -1e-9 * target ** 2) & (pops[src] - wu > 0)
        if movable is not None:
            good &= movable[u]
        if not good.any():
            break
        u, dst, src, wu = u[good], dst[good], src[good], wu[good]
        cen = np.column_stack([sx, sy]) / np.maximum(pops, 1e-12)[:, None]
        score = (np.sum((xy[u] - cen[dst]) ** 2, axis=1) - np.sum((xy[u] - cen[src]) ** 2, axis=1)) / r2
        if county is not None:
            cu = cid[u]
            score = score + county_weight * ((cd[cu, dst] <= 0).astype(float) - (cd[cu, src] <= wu).astype(float))
        # worst districts first, then cheapest move
        urgency = np.maximum(np.abs(dev[src]), np.abs(dev[dst]))
        order = np.lexsort((score, -np.round(urgency, 4)))
        touched = np.zeros(k, bool)
        applied = 0
        for i in order:
            a_, b_ = src[i], dst[i]
            if touched[a_] or touched[b_]:
                continue
            uu = int(u[i])
            if labels[uu] != a_ or not _connected_without(uu, a_, labels, indptr, indices):
                continue
            labels[uu] = b_
            pops[a_] -= wu[i]
            pops[b_] += wu[i]
            sx[a_] -= wu[i] * xy[uu, 0]
            sy[a_] -= wu[i] * xy[uu, 1]
            sx[b_] += wu[i] * xy[uu, 0]
            sy[b_] += wu[i] * xy[uu, 1]
            if county is not None:
                cd[cid[uu], a_] -= wu[i]
                cd[cid[uu], b_] += wu[i]
            touched[a_] = touched[b_] = True
            applied += 1
            if touched.all():
                break
        moves += applied
        if applied == 0:
            break
    return labels, moves


def partition(xy, w, k: int, adj: sparse.csr_matrix, county=None, seed: int = 0, n_init: int = 1,
              tol: float = 0.001, max_iter: int = 40, county_weight: float = 0.5,
              geodesic: bool = True, init: str = "rcb") -> PartitionResult:
    """Equal-population, compact, contiguous k-partition of weighted graph nodes."""
    xy, w = np.asarray(xy, float), np.asarray(w, float)
    n = len(xy)
    if k < 1 or k > n:
        raise ValueError(f"k={k} must be in [1, n_units={n}]")
    if k == 1:
        return PartitionResult(np.zeros(n, np.int64), _centroids(xy, w, np.zeros(n, np.int64), 1, xy[:1]), 0, 0)
    graph = None
    if geodesic:
        coo = sparse.triu(adj, 1).tocoo()
        length = np.linalg.norm(xy[coo.row] - xy[coo.col], axis=1) + 1e-6
        graph = sparse.csr_matrix((length, (coo.row, coo.col)), shape=adj.shape)
    best = None
    for trial in range(n_init):
        rng = np.random.default_rng([seed, trial])
        labels, centers, iters, hist = lloyd_power(xy, w, k, rng, graph=graph, max_iter=max_iter, init=init)
        val = hist[-1]
        if best is None or val < best[0]:
            best = (val, labels, centers, iters, hist)
    _, labels, centers, iters, hist = best
    labels = enforce_contiguity(labels, adj, w, k)
    labels, moves = refine(labels, xy, w, k, adj, county=county, tol=tol, county_weight=county_weight)
    labels = enforce_contiguity(labels, adj, w, k)  # refine never disconnects; belt and braces
    centers = _centroids(xy, w, labels, k, centers)
    return PartitionResult(labels, centers, iters, moves, hist)
