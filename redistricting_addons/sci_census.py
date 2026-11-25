"""Social-ties maps redrawn on real Census borders, so every district is one piece (added 2026-11-15).

In short (for people): the social-ties maps (``sci_districts`` by county, ``sci_zcta`` by ZIP-code area) were grown
on the toys' own neighbour links, which are partly guessed from block-group centres (about a quarter are not real
shared borders). On real borders some of their districts fall into pieces, a few by a lot. This redraws both maps on
the Census shared-border graph with the same method and settings, checks that every district is one piece, and
writes the new maps beside the old ones (the old files are kept).

For AI agents (detailed):
- Runs ``sci_districts.optimise(st, "adjusted", bursts, burst, seed, compact=True, graph="census")`` and
  ``sci_zcta.optimise((st, bursts, burst, seed, True, "census"))``: Census graph from ``redistricting_addons.graphs``
  (with water links), start ``ensemble.tree_seed(seed=1)`` (the solver's plan is not contiguous there), compactness
  cap = median cut edges of ``<ST>.county20.census.json``, neutral comparison with the Census-graph ensembles.
- Writes ``site/data/sci/districts/<ST>.adjusted.compact.census.json`` and ``<ST>.zcta.census.json`` (same format as
  the site-graph files, ``params.graph = "census"``) and ``docs/SCI_CENSUS.md`` (pieces of the old and new maps on
  the Census graph, population deviation, 2020 Democratic seats beside the Census-graph neutral median).
- ``python -m redistricting_addons.sci_census [--states ..] [--workers 5] [--bursts 3000] [--report-only]``;
  files already written are skipped unless ``--force``.
"""
from __future__ import annotations

import argparse
import json
from multiprocessing import Pool

import numpy as np

from .ensemble import ROOT, load_state

DIST = ROOT / "site" / "data" / "sci" / "districts"
ENS = ROOT / "site" / "data" / "ensembles"
KINDS = (("adjusted.compact", "Social ties by county"), ("zcta", "Social ties by ZIP"))
# added: the other versions too (no shape limit, raw friendship index, ZIP with no shape limit)
MORE = (("adjusted", "Social ties by county, no shape limit"), ("raw.compact", "Social ties by county, raw index"),
        ("raw", "Social ties by county, raw index, no shape limit"), ("zcta.free", "Social ties by ZIP, no shape limit"))
ALL_KINDS = KINDS + MORE


def pieces(graph, labels) -> int:
    """Number of connected pieces of all districts together on ``graph`` (equals k when every district is one)."""
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components
    lab = np.asarray(labels, np.int64)
    e = graph.edges[lab[graph.edges[:, 0]] == lab[graph.edges[:, 1]]]
    a = sparse.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(graph.n, graph.n))
    _, comp = connected_components(a, directed=False)
    return len(np.unique(comp))


def _job(args):
    st, kind, bursts, burst, seed = args
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    except Exception:
        pass
    from . import sci_districts, sci_zcta
    if kind.startswith("zcta"):
        sci_zcta.optimise((st, bursts, burst, seed, kind == "zcta", "census"))
    else:
        obj, compact = kind.split(".")[0], kind.endswith(".compact")
        res = sci_districts.optimise(st, obj, bursts, burst, seed, compact=compact, graph="census")
        if res:
            DIST.mkdir(parents=True, exist_ok=True)
            (DIST / f"{st}.{kind}.census.json").write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    return st, kind


def _median(hist: dict) -> int:
    h = {int(k): v for k, v in hist.items()}
    ks = sorted(h)
    c = np.cumsum([h[k] for k in ks]) / sum(h.values())
    return ks[int(np.searchsorted(c, 0.5))]


def report():
    rows = []
    for p in sorted((ROOT / "site" / "data").glob("[A-Z][A-Z].json")):
        st = p.stem
        if not st.isupper():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d["seats"] < 2:
            continue
        g = load_state(p, graph="census", sci=False)
        e = g.elections.get("pres2020")
        ens_p = ENS / f"{st}.county20.census.json"
        med = _median(json.loads(ens_p.read_text(encoding="utf-8"))["elections"]["pres2020"]["seats_d_histogram"]) \
            if ens_p.exists() else None
        row = {"st": st, "k": g.k, "med": med}
        for kind, _ in KINDS:
            for tag, suf in (("old", ""), ("new", ".census")):
                f = DIST / f"{st}.{kind}{suf}.json"
                if not f.exists():
                    continue
                lab = np.asarray(json.loads(f.read_text(encoding="utf-8"))["labels"], np.int64)
                pops = np.bincount(lab, weights=g.pop, minlength=g.k)
                D = np.bincount(lab, weights=e["d"], minlength=g.k)
                R = np.bincount(lab, weights=e["r"], minlength=g.k)
                row[f"{kind}.{tag}"] = {"pieces": pieces(g, lab) - g.k,
                                        "dev": float(np.max(np.abs(pops / (g.pop.sum() / g.k) - 1)) * 100),
                                        "seats": int(np.sum(D / np.maximum(D + R, 1) > 0.5))}
        rows.append(row)

    def cnt(kind, tag):
        return sum(1 for r in rows if r.get(f"{kind}.{tag}", {}).get("pieces", 0) > 0)

    done = [r for r in rows if all(f"{k}.new" in r for k, _ in KINDS)]
    lines = ["# Social-ties maps on real borders", "", "## In short (for people)", "",
             "The social-ties maps were grown on the toys' own neighbour links, which are partly guessed from block-group "
             "centres. Checked on real Census borders, some of their districts fall into pieces: "
             f"{cnt('adjusted.compact', 'old')} of {len(rows)} county maps and {cnt('zcta', 'old')} ZIP maps have at "
             "least one district in more than one piece, some with large parts tens of kilometres away.", "",
             f"Both maps were redrawn on real borders with the same method and settings (Connecticut has only the ZIP map). In the {len(done)} states with both, "
             f"districts left in pieces: county maps {cnt('adjusted.compact', 'new')}, ZIP maps "
             f"{cnt('zcta', 'new')}. Democratic seats with 2020 votes, added up over those states: county map "
             f"{sum(r['adjusted.compact.old']['seats'] for r in done if 'adjusted.compact.old' in r)} before, "
             f"{sum(r['adjusted.compact.new']['seats'] for r in done)} now; ZIP map "
             f"{sum(r['zcta.old']['seats'] for r in done if 'zcta.old' in r)} before, {sum(r['zcta.new']['seats'] for r in done)} now; "
             f"neutral median {sum(r['med'] for r in done if r['med'] is not None)}. The old files are kept; the new ones end "
             "in `.census.json`.", "", "---", "", "## For AI agents (detailed)", "",
             "Generated by `python -m redistricting_addons.sci_census` (module docstring has the method). Pieces = extra "
             "connected pieces beyond one per district on the Census shared-border graph (with water links). Dev = largest "
             "district population deviation, %. Seats = 2020 Democratic seats. Neutral = median of "
             "`<ST>.county20.census.json`.", "",
             "| State | Seats | County map: pieces old → new | dev new | seats old → new | ZIP map: pieces old → new | dev new | seats old → new | Neutral median |",
             "| --- | --: | --- | --: | --- | --- | --: | --- | --: |"]
    for r in rows:
        cells = []
        for k, _ in KINDS:
            o, n = r.get(f"{k}.old"), r.get(f"{k}.new")
            cells += [f"{o['pieces'] if o else ''} → {n['pieces'] if n else ''}", f"{n['dev']:.2f}%" if n else "",
                      f"{o['seats'] if o else ''} → {n['seats'] if n else ''}"]
        lines.append(f"| {r['st']} | {r['k']} | " + " | ".join(cells) + f" | {'' if r['med'] is None else r['med']} |")
    (ROOT / "docs" / "SCI_CENSUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m redistricting_addons.sci_census", description=__doc__.split("\n\n")[0])
    ap.add_argument("--states", nargs="*")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--bursts", type=int, default=3000)
    ap.add_argument("--burst", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="redo states whose .census.json files exist")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--all", action="store_true", help="also the no-shape-limit, raw-index and ZIP no-limit versions")
    a = ap.parse_args(argv)
    if not a.report_only:
        sts = a.states or sorted(p.stem for p in (ROOT / "site" / "data").glob("[A-Z][A-Z].json") if p.stem.isupper())
        sts = [s for s in sts if json.loads((ROOT / "site" / "data" / f"{s}.json").read_text(encoding="utf-8"))["seats"] > 1]
        kinds = ALL_KINDS if a.all else KINDS
        jobs = [(st, k, a.bursts, a.burst, a.seed) for st in sts for k, _ in kinds
                if a.force or not (DIST / f"{st}.{k}.census.json").exists()]
        with Pool(a.workers) as pool:
            for st, k in pool.imap_unordered(_job, jobs):
                print(f"{st} {k}: done", flush=True)
    rows = report()
    print(f"wrote docs/SCI_CENSUS.md ({len(rows)} states)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
