"""Pattern/case definitions and the object assignment plan (no GUI, no ETABS)."""

from .assign import (
    PLACEHOLDER_PRESSURE_PSF,
    PressurePatternPair,
    build_assignments,
    build_plan,
    build_placeholder_pressure_assignments,
    pair_pressure_patterns,
    placeholder_pressure_pattern_specs,
    verify_mech_reversibility,
)
from .specs import case_specs, pattern_specs

__all__ = [
    "PLACEHOLDER_PRESSURE_PSF",
    "PressurePatternPair",
    "build_assignments",
    "build_plan",
    "build_placeholder_pressure_assignments",
    "case_specs",
    "pair_pressure_patterns",
    "placeholder_pressure_pattern_specs",
    "pattern_specs",
    "verify_mech_reversibility",
]
