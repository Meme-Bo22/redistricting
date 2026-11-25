"""The official and Fair Lines maps made usable on real Census borders: every district one piece, within 1% (added 2026-11-15).

In short (for people): the toys store the official map (approximated from block-group centres) and the Fair Lines
solver's map on their own neighbour links, which are partly guessed. On real Census borders many of their districts
are in pieces (22 official maps, 29 solver maps of 50). This makes a usable copy of each: stray pieces join the
neighbouring district they touch most, then block groups along district edges are moved one at a time from the
fullest districts to emptier neighbours, never splitting a district, until every district is within 1% of equal
population. The originals are kept; the copies are in ``site/data/plans/``.

For AI agents (detailed):
- Graph: ``ensemble.load_state(graph="census")`` (shared-border graph with water links). Contiguity = one connected
  component per district on it.
- ``make_contiguous``: repeatedly gives the least populous stray piece (any district component but its most
  populous) to the neighbouring district sharing most links with it.
- ``balance``: while the largest deviation exceeds ``tol`` (default 0.009), takes the district furthest from the
  ideal; if over, moves one of its boundary units to the least populous neighbouring district (preferring units
  with the most links into it), if under, pulls one from the fullest neighbour; a move is made only if the donor stays
  connected (checked by connected components of the donor minus the unit). Stops after ``max_moves``.
- Output ``site/data/plans/<ST>.<official|solver>.census.json``: ``labels``, ``moved_units``, ``moved_pop``,
  ``max_dev_pct`` before and after, ``pieces_before``. ``python -m redistricting_addons.plans_census [--states ..]``.
"""
from __future__ import annotations

import argparse
import json
from multiprocessing import Pool

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from .ensemble import ROOT, load_state

OUT = ROOT / "site" / "data" / "plans"


def _adj(g):
    e = g.edges
    a = sparse.coo_matrix((np.ones(2 * len(e)), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])),
                          shape=(g.n, g.n)).tocsr()
    a.data[:] = 1
    return a


def components(adj, lab, d):
    """Unit index arrays of the connected pieces of district ``d``."""
    idx = np.flatnonzero(lab == d)
    if idx.size == 0:
        return []
    _, comp = connected_components(adj[idx][:, idx], directed=False)
    return [idx[comp == c] for c in np.unique(comp)]


def extra_pieces(adj, lab, k) -> int:
    return sum(max(0, len(components(adj, lab, d)) - 1) for d in range(k))


def make_contiguous(adj, lab, pop, k):
    lab = lab.copy()
    moved_u = moved_p = 0
    for _ in range(100000):
        strays = []
        for d in range(k):
            ps = components(adj, lab, d)
            if len(ps) > 1:
                big = max(ps, key=lambda u: pop[u].sum())
                strays += [(pop[u].sum(), d, u) for u in ps if u is not big]
        if not strays:
            break
        _, d, u = min(strays, key=lambda t: t[0])
        nb = adj[u].indices
        other = lab[nb][lab[nb] != d]
        if other.size == 0:
            break
        lab[u] = np.bincount(other, minlength=k).argmax()
        moved_u += len(u)
        moved_p += int(pop[u].sum())
    return lab, moved_u, moved_p


def _stays_connected(adj, lab, d, u):
    idx = np.flatnonzero(lab == d)
    idx = idx[idx != u]
    if idx.size == 0:
        return False
    n, _ = connected_components(adj[idx][:, idx], directed=False)
    return n == 1


def balance(adj, lab, pop, k, tol=0.009, max_moves=200000):
    lab = lab.copy()
    ideal = pop.sum() / k
    dp = np.bincount(lab, weights=pop, minlength=k)
    moves = moved_p = 0
    blocked = set()
    while moves < max_moves:
        dev = dp / ideal - 1
        order = np.argsort(-np.abs(dev))
        if abs(dev[order[0]]) <= tol:
            break
        done = False
        for a in order:
            if abs(dev[a]) <= tol:
                break
            over = dev[a] > 0
            ua = np.flatnonzero(lab == a)
            # boundary pairs (unit in a, neighbouring district b)
            sub = adj[ua]
            rows = np.repeat(ua, np.diff(sub.indptr))
            nb = lab[sub.indices]
            m = nb != a
            pairs = np.c_[rows[m], nb[m]]
            if not len(pairs):
                continue
            if over:  # give one of a's units to its emptiest neighbour
                targets = np.unique(pairs[:, 1])
                b = targets[np.argmin(dp[targets])]
                cand = pairs[pairs[:, 1] == b][:, 0]
                donor, recv = a, b
            else:  # take a unit from the fullest neighbour
                sub_b = None
                targets = np.unique(pairs[:, 1])
                b = targets[np.argmax(dp[targets])]
                ub = np.flatnonzero(lab == b)
                sb = adj[ub]
                rows_b = np.repeat(ub, np.diff(sb.indptr))
                cand = rows_b[lab[sb.indices] == a]
                donor, recv = b, a
            if (donor, recv) in blocked:
                continue
            uniq, cnt = np.unique(cand, return_counts=True)
            for u in uniq[np.argsort(-cnt)][:40]:
                if _stays_connected(adj, lab, donor, u):
                    lab[u] = recv
                    dp[donor] -= pop[u]
                    dp[recv] += pop[u]
                    moves += 1
                    moved_p += int(pop[u])
                    done = True
                    break
            if done:
                blocked.clear()
                break
            blocked.add((donor, recv))
        if not done:
            break
    return lab, moves, moved_p


def resplit_pairs(g, lab, k, tol=0.009, seed=0, max_rounds=500):
    """Added 2026-11-24 (California's official map stuck at 14.5%): fallback when ``balance`` cannot move single
    units. The worst district is merged with the neighbour whose combined population is closest to two ideal
    districts, and the pair is re-split by a random spanning-tree cut so both are within ``tol`` (ReCom's step).
    Only those two districts change; both stay one piece. Returns labels and the number of pairs re-split."""
    from .ensemble import _bipartition, _region
    rng = np.random.default_rng(seed)
    lab = lab.copy()
    ideal = g.pop.sum() / k
    e0, e1 = g.edges[:, 0], g.edges[:, 1]
    done = 0
    for _ in range(max_rounds):
        dp = np.bincount(lab, weights=g.pop, minlength=k)
        dev = dp / ideal - 1
        if np.max(np.abs(dev)) <= tol:
            break
        progress = False
        for a in np.argsort(-np.abs(dev)):
            if abs(dev[a]) <= tol:
                break
            m = ((lab[e0] == a) & (lab[e1] != a)) | ((lab[e1] == a) & (lab[e0] != a))
            nbs = np.unique(np.where(lab[e0[m]] == a, lab[e1[m]], lab[e0[m]]))
            for b in sorted(nbs, key=lambda b: abs(dp[a] + dp[b] - 2 * ideal)):
                if abs(dp[a] + dp[b] - 2 * ideal) > 2 * ideal * tol:
                    break  # no neighbour makes a pair of two balanced districts
                mask = (lab == a) | (lab == b)
                nodes, eu, ev, em = _region(g, mask)
                side = _bipartition(nodes.size, eu, ev, np.ones(int(em.sum())), g.pop[nodes], ideal, tol, rng, tries=300)
                if side is None:
                    continue
                lab[nodes[side]] = a
                lab[nodes[~side]] = b
                done += 1
                progress = True
                break
            if progress:
                break
        if not progress:
            break
    return lab, done


def fix(st: str, which: str):
    g = load_state(ROOT / "site" / "data" / f"{st}.json", graph="census", sci=False)
    if g.k < 2 or which not in g.plans:
        return None
    adj = _adj(g)
    lab0 = np.asarray(g.plans[which], np.int64)
    ideal = g.pop.sum() / g.k
    dev0 = float(np.max(np.abs(np.bincount(lab0, weights=g.pop, minlength=g.k) / ideal - 1)) * 100)
    before = extra_pieces(adj, lab0, g.k)
    lab, mu, mp = make_contiguous(adj, lab0, g.pop, g.k)
    lab, bm, bp = balance(adj, lab, g.pop, g.k)
    dev = float(np.max(np.abs(np.bincount(lab, weights=g.pop, minlength=g.k) / ideal - 1)) * 100)
    resplit = 0
    if dev > 0.9:  # added: single-unit moves got stuck; re-split the worst pairs (only then, so other states are unchanged)
        lab, resplit = resplit_pairs(g, lab, g.k)
        lab, bm2, bp2 = balance(adj, lab, g.pop, g.k)
        bm, bp = bm + bm2, bp + bp2
        dev = float(np.max(np.abs(np.bincount(lab, weights=g.pop, minlength=g.k) / ideal - 1)) * 100)
    out = {"v": 1, "abbr": st, "plan": which, "districts": g.k, "labels": lab.tolist(),
           "pieces_before": before, "pieces_after": extra_pieces(adj, lab, g.k),
           "max_dev_pct_before": round(dev0, 3), "max_dev_pct": round(dev, 3),
           "moved_units": int(mu + bm), "moved_pop": int(mp + bp),
           "changed_units": int(np.count_nonzero(lab != lab0)),
           **({"resplit_pairs": resplit} if resplit else {}),
           "method": "stray pieces to the neighbouring district with most shared links, then contiguity-keeping "
                     "single-unit moves along district edges until every district is within 0.9% (Census graph)"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{st}.{which}.census.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return {k: v for k, v in out.items() if k != "labels"}


def _job(args):
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    except Exception:
        pass
    return fix(*args)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m redistricting_addons.plans_census", description=__doc__.split("\n\n")[0])
    ap.add_argument("--states", nargs="*")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args(argv)
    sts = a.states or sorted(p.stem for p in (ROOT / "site" / "data").glob("[A-Z][A-Z].json") if p.stem.isupper())
    with Pool(a.workers) as pool:
        for r in pool.imap_unordered(_job, [(st, w) for st in sts for w in ("official", "solver")]):
            if r:
                print(f"{r['abbr']} {r['plan']}: pieces {r['pieces_before']} -> {r['pieces_after']}, dev "
                      f"{r['max_dev_pct_before']}% -> {r['max_dev_pct']}%, {r['changed_units']} units changed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
