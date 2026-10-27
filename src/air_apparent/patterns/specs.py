"""Pattern and analysis-case definitions."""

from __future__ import annotations

from ..models import DIRECTIONS, CaseSpec, PatternSpec, mech_pattern_name, pattern_name


def pattern_specs() -> list[PatternSpec]:
    """16 directional patterns (Wall/Parapet/PH/Ecc x 4) + 2 reversible mechanical patterns."""
    specs = [PatternSpec(pattern_name(f, d), f, d, "provisional" if f == "Ecc" else "ready")
             for f in ("Wall", "Parapet", "PH", "Ecc") for d in DIRECTIONS]
    specs += [PatternSpec(mech_pattern_name(a), "Mech", a) for a in ("X", "Y")]
    return specs


def case_specs() -> list[CaseSpec]:
    """Component analysis cases: one per directional pattern, four signed mechanical cases."""
    cases = [CaseSpec(p.name, ((p.name, 1.0),), p.status) for p in pattern_specs() if p.family != "Mech"]
    for d in DIRECTIONS:
        cases.append(CaseSpec(f"W_Mech_{d}", ((mech_pattern_name(d[1]), 1.0 if d[0] == "+" else -1.0),)))
    return cases
