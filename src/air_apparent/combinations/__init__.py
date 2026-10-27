"""Load-combination specifications W1-W4 (provisional project definitions).

W_d = W_Wall_d + W_Parapet_d + W_PH_d + W_Mech_d ;  E_d = W_Ecc_d.
Individual linear combinations are kept; envelopes only reference them.
No gravity-plus-wind design combinations are generated in this version.
"""

from __future__ import annotations

from itertools import product

from ..models import DIRECTIONS, CombinationSpec, pattern_name

F_W2 = 0.75
F_W3 = 0.75
F_W4 = 0.5625
SIGNS = (("+", 1.0), ("-", -1.0))


def mech_case_name(direction: str) -> str:
    """Analysis case name of a mechanical direction (signed factor on a reversible pattern)."""
    return f"W_Mech_{direction}"


def case_for(family: str, direction: str) -> str:
    return mech_case_name(direction) if family == "Mech" else pattern_name(family, direction)


def directional_sum_terms(direction: str, factor: float = 1.0) -> list[tuple[str, float]]:
    """Terms of W_d: wall + parapet + penthouse + mechanical cases, scaled by ``factor``."""
    return [(case_for(f, direction), factor) for f in ("Wall", "Parapet", "PH", "Mech")]


def ecc_term(direction: str, factor: float) -> tuple[str, float]:
    return (pattern_name("Ecc", direction), factor)


def build_combinations() -> list[CombinationSpec]:
    combos: list[CombinationSpec] = []
    w1 = []
    for d in DIRECTIONS:
        w1.append(CombinationSpec(f"W1_{d}", "W1", "linear", tuple(directional_sum_terms(d))))
    combos += w1
    w2 = []
    for d, (sn, sf) in product(DIRECTIONS, SIGNS):
        terms = directional_sum_terms(d, F_W2) + [ecc_term(d, sf * F_W2)]
        w2.append(CombinationSpec(f"W2_{d}_{sn}E", "W2", "linear", tuple(terms)))
    combos += w2
    w3 = []
    for dx, dy in product(("+X", "-X"), ("+Y", "-Y")):
        terms = directional_sum_terms(dx, F_W3) + directional_sum_terms(dy, F_W3)
        w3.append(CombinationSpec(f"W3_{dx}_{dy}", "W3", "linear", tuple(terms)))
    combos += w3
    w4 = []
    for dx, dy, (sx, fx), (sy, fy) in product(("+X", "-X"), ("+Y", "-Y"), SIGNS, SIGNS):
        terms = (directional_sum_terms(dx, F_W4) + directional_sum_terms(dy, F_W4)
                 + [ecc_term(dx, fx * F_W4), ecc_term(dy, fy * F_W4)])
        w4.append(CombinationSpec(f"W4_{dx}_{dy}_{sx}EX_{sy}EY", "W4", "linear", tuple(terms)))
    combos += w4
    for fam, members in (("W1", w1), ("W2", w2), ("W3", w3), ("W4", w4)):
        combos.append(CombinationSpec(f"{fam}_ENV", fam, "envelope",
                                      tuple((m.name, 1.0) for m in members)))
    return combos
