"""Fair congressional districting by meshing science.

Population is meshed (a Delaunay graph of Census block-group centroids,
pruned to the state's territory) and the mesh is partitioned the way one
decomposes a computational mesh for parallel work: equal load (population),
minimal interface (compactness), connected subdomains (contiguity).

    >>> from redistricting import generate_plan       # doctest: +SKIP
    >>> plan = generate_plan("PA")                     # doctest: +SKIP
    >>> plan.stats.max_abs_deviation_pct               # doctest: +SKIP
"""
from .data import STATES, State, load_units, seats, state_by_abbr
from .solver import partition
from .plan import Plan, generate_plan, plan_from_units

__all__ = ["STATES", "State", "Plan", "generate_plan", "plan_from_units", "partition", "load_units",
           "seats", "state_by_abbr"]
__version__ = "0.1.0"
