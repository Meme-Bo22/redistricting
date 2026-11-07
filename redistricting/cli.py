"""Command line: ``python -m redistricting --state PA`` or ``--all``."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .data import STATES, state_by_abbr
from .plan import generate_plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="redistricting", description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--state", nargs="+", help="postal code(s), FIPS or name(s)")
    g.add_argument("--all", action="store_true", help="all 50 states")
    ap.add_argument("--out", default="redistricting_out", help="output directory")
    ap.add_argument("--cenpop", help="Census Centers-of-Population block-group file (e.g. CenPop2020_Mean_BG.txt); "
                                     "overrides --pop-year")
    ap.add_argument("--pop-year", type=int, default=2020, choices=[2010, 2020],
                    help="population vintage: 2020 (default, pinned file in research/redistricting_2020) or 2010")
    ap.add_argument("--seats-year", type=int, default=2020, choices=[2010, 2020])
    ap.add_argument("--districts", type=int, help="override the number of districts (e.g. state senate)")
    ap.add_argument("--tolerance", type=float, default=0.001, help="target max |population deviation| (fraction)")
    ap.add_argument("--county-weight", type=float, default=0.5, help="refinement penalty per newly split county")
    ap.add_argument("--n-init", type=int, default=1)
    ap.add_argument("--seed", type=int, help="random seed (default: the state's FIPS code)")
    ap.add_argument("--init", choices=["rcb", "random"], default="rcb",
                    help="starting centres: rcb (deterministic bisection; --seed only adds a 1 m jitter) or "
                         "random (population-weighted random units drawn from --seed)")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--fort14", action="store_true", help="also write the population mesh as fort.14")
    a = ap.parse_args(argv)

    states = list(STATES) if a.all else [state_by_abbr(s) for s in a.state]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    plans, rows = [], []
    for st in states:
        plan = generate_plan(st, k=a.districts, cenpop_path=a.cenpop, seats_year=a.seats_year, seed=a.seed, pop_year=a.pop_year, init=a.init,
                             n_init=a.n_init, tol=a.tolerance, county_weight=a.county_weight)
        d = plan.write(out)
        if a.fort14:
            plan.write_fort14(d / f"{st.abbr}_population.14")
        if not a.no_render:
            from .render import render_plan

            render_plan(plan, d / "map.png")
        s = plan.stats
        rows.append({"state": st.abbr, "districts": plan.k, "units": len(plan.units), **s.as_dict(),
                     "seconds": round(plan.seconds, 2)})
        plans.append(plan)
        print(f"{st.abbr}: {plan.k:>2} districts  max|dev| {s.max_abs_deviation_pct:6.3f}%  "
              f"PP {s.mean_polsby_popper:.3f}  Reock {s.mean_reock:.3f}  counties split {s.counties_split:>3}  "
              f"contiguous {s.all_contiguous}  ({plan.seconds:.1f}s)", flush=True)
    with open(out / "summary.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    if len(plans) > 1 and not a.no_render:
        from .render import render_grid

        render_grid(plans, out / "all_states.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
