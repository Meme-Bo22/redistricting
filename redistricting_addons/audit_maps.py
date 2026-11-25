"""Audit every stored district map: one piece per district on real Census borders, within 1% (added 2026-11-15).

In short (for people): checks every map the toys show or compare against, for every state: the usable official and
Fair Lines maps, all social-ties maps drawn on real borders, and the typical and final maps kept from every neutral
ensemble on real borders. Each district must be one connected piece on the Census shared-border graph and within 1%
of equal population. Writes docs/MAP_AUDIT.md; exits 1 if any map fails.

For AI agents (detailed): files checked are ``site/data/plans/<ST>.*.census.json``,
``site/data/sci/districts/<ST>.*.census.json`` and ``site/data/ensembles/maps/<ST>.*.json`` (``typical`` and every
``final``). Contiguity: one connected component per district on ``load_state(graph="census")`` (with water links).
Balance: max |district population / ideal - 1| <= ``--tol`` (0.0101, ReCom's 1% plus rounding).
``python -m redistricting_addons.audit_maps [--tol 0.0101]``.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

import numpy as np

from .ensemble import ROOT, contiguous, load_state

SOURCES = {"plans": ROOT / "site" / "data" / "plans", "sci": ROOT / "site" / "data" / "sci" / "districts",
           "ensembles": ROOT / "site" / "data" / "ensembles" / "maps"}


def files():
    for kind, d in SOURCES.items():
        pat = "[A-Z][A-Z].*.json" if kind == "ensembles" else "[A-Z][A-Z].*.census.json"
        for p in sorted(d.glob(pat)):
            yield kind, p


def maps_in(kind, p):
    d = json.loads(p.read_text(encoding="utf-8"))
    if kind == "ensembles":
        yield "typical", d["typical"]
        for i, f in enumerate(d.get("final", []), 1):
            yield f"final {i}", f
    else:
        yield "map", d["labels"]


def audit(tol=0.0101):
    graphs, results = {}, []
    for kind, p in files():
        st = p.name[:2]
        if st not in graphs:
            graphs[st] = load_state(ROOT / "site" / "data" / f"{st}.json", graph="census", sci=False)
        g = graphs[st]
        scheme = p.name[3:-5]
        for which, lab in maps_in(kind, p):
            lab = np.asarray(lab, np.int64)
            ok_c = bool(contiguous(g, lab, g.k)) and len(np.unique(lab)) == g.k
            dev = float(np.max(np.abs(np.bincount(lab, weights=g.pop, minlength=g.k) / (g.pop.sum() / g.k) - 1)))
            results.append({"st": st, "source": kind, "scheme": scheme, "map": which, "contiguous": ok_c,
                            "dev_pct": round(dev * 100, 3), "ok": ok_c and dev <= tol})
    return results


def report(results):
    by = defaultdict(lambda: [0, 0, set(), set()])
    for r in results:
        b = by[(r["source"], r["scheme"])]
        b[0] += 1
        b[1] += r["ok"]
        b[2].add(r["st"])
        if not r["ok"]:
            b[3].add(r["st"])
    bad = [r for r in results if not r["ok"]]
    lines = ["# Map audit: every stored map on real borders", "", "## In short (for people)", "",
             f"{len(results)} stored maps checked across {len({r['st'] for r in results})} states. "
             + ("Every one has each district in one piece on real Census borders and within 1% of equal population."
                if not bad else f"{len(bad)} fail (listed below)."), "", "---", "", "## For AI agents (detailed)", "",
             "`python -m redistricting_addons.audit_maps` (module docstring). Scheme = file name after the state code.",
             "", "| Source | Scheme | Maps | Pass | States | States failing |", "| --- | --- | --: | --: | --: | --- |"]
    for (src, sch), (n, ok, sts, badst) in sorted(by.items()):
        lines.append(f"| {src} | `{sch}` | {n} | {ok} | {len(sts)} | {' '.join(sorted(badst))} |")
    if bad:
        lines += ["", "Failing maps:", ""] + [f"- {r['st']} {r['source']} {r['scheme']} {r['map']}: contiguous "
                                             f"{r['contiguous']}, deviation {r['dev_pct']}%" for r in bad]
    (ROOT / "docs" / "MAP_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m redistricting_addons.audit_maps", description=__doc__.split("\n\n")[0])
    ap.add_argument("--tol", type=float, default=0.0101)
    a = ap.parse_args(argv)
    res = audit(a.tol)
    bad = report(res)
    print(f"audit: {len(res)} maps, {len(bad)} failing; wrote docs/MAP_AUDIT.md")
    for r in bad[:50]:
        print("  FAIL", r)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
