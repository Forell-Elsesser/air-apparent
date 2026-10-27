"""Provisional W1-W4 horizontal MWFRS load-combination definitions."""

from __future__ import annotations

from itertools import product

from ..models import DIRECTIONS, CombinationSpec
from .terms import directional_sum_terms, eccentricity_term
from .validation import validate_combinations

F_W2 = 0.75
F_W3 = 0.75
F_W4 = 0.5625
ECC_SIGNS = (("+", 1.0), ("-", -1.0))


def build_combinations(case_names: set[str] | None = None) -> list[CombinationSpec]:
    """Build W1-W4 linear combinations and family envelopes.

    When ``case_names`` is omitted, the names are obtained from the existing pattern/case
    definitions. This module consumes those names and does not define or alter load patterns
    or analysis cases.
    """
    if case_names is None:
        # Import lazily to avoid a package-import cycle: patterns builds the LoadPlan and calls
        # this function from inside build_plan().
        from ..patterns.specs import case_specs

        case_names = {case.name for case in case_specs()}

    linear: list[CombinationSpec] = []

    # W1: one direction, no eccentricity term.
    w1 = [CombinationSpec(f"W1_{d}", "W1", "linear", tuple(directional_sum_terms(d)))
          for d in DIRECTIONS]
    linear.extend(w1)

    # W2: one direction plus or minus 100% eccentricity, both scaled by 0.75.
    w2 = []
    for direction, (sign_name, sign_factor) in product(DIRECTIONS, ECC_SIGNS):
        terms = directional_sum_terms(direction, F_W2)
        terms.append(eccentricity_term(direction, sign_factor * F_W2))
        w2.append(CombinationSpec(f"W2_{direction}_{sign_name}E", "W2", "linear", tuple(terms)))
    linear.extend(w2)

    # W3: orthogonal directional wind cases, each scaled by 0.75.
    w3 = []
    for dx, dy in product(("+X", "-X"), ("+Y", "-Y")):
        terms = directional_sum_terms(dx, F_W3) + directional_sum_terms(dy, F_W3)
        w3.append(CombinationSpec(f"W3_{dx}_{dy}", "W3", "linear", tuple(terms)))
    linear.extend(w3)

    # W4: orthogonal wind cases and signed eccentricity terms, all scaled by 0.5625.
    w4 = []
    for dx, dy, (sx, fx), (sy, fy) in product(
        ("+X", "-X"), ("+Y", "-Y"), ECC_SIGNS, ECC_SIGNS
    ):
        terms = (directional_sum_terms(dx, F_W4) + directional_sum_terms(dy, F_W4)
                 + [eccentricity_term(dx, fx * F_W4), eccentricity_term(dy, fy * F_W4)])
        w4.append(CombinationSpec(f"W4_{dx}_{dy}_{sx}EX_{sy}EY", "W4", "linear", tuple(terms)))
    linear.extend(w4)

    envelopes = []
    for family, members in (("W1", w1), ("W2", w2), ("W3", w3), ("W4", w4)):
        envelopes.append(CombinationSpec(
            f"{family}_ENV", family, "envelope", tuple((member.name, 1.0) for member in members)
        ))

    combinations = linear + envelopes
    validate_combinations(combinations, case_names)
    return combinations
