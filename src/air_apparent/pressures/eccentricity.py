"""Eccentric-torsion targets and incremental floor moments (no ETABS calls)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EccStory:
    story: str
    cumulative_shear_kip: float
    eccentricity_ft: float
    target_torsion_kip_ft: float
    applied_moment_kip_ft: float
    shear_source: str
    reference_axis: str = "global Z through the diaphragm reference point"


def eccentricity_length(ratio: float, perpendicular_dim_ft: float) -> float:
    """e = ratio x dimension perpendicular to the wind direction."""
    return ratio * perpendicular_dim_ft


def eccentric_torsion(
    story_shears: list[tuple[str, float]], ratio: float, perpendicular_dim_ft: float,
    shear_source: str = "yaml",
) -> list[EccStory]:
    """Convert cumulative story shears (top story first) to incremental floor moments.

    applied moment = target torsion at this story - target torsion at the story above.
    """
    e = eccentricity_length(ratio, perpendicular_dim_ft)
    if not math.isfinite(e) or ratio < 0 or perpendicular_dim_ft <= 0:
        raise ValueError("eccentricity requires finite non-negative ratio and positive width")
    out: list[EccStory] = []
    prev_target = 0.0
    prev_shear = 0.0
    for name, shear in story_shears:
        if not math.isfinite(shear) or shear < 0:
            raise ValueError(f"{name}: cumulative shear must be finite and non-negative")
        if shear < prev_shear - 1e-9:
            raise ValueError(
                f"cumulative shear must not decrease going down: {name} has {shear} < {prev_shear}"
            )
        target = shear * e
        if not math.isfinite(target):
            raise ValueError(f"{name}: eccentric torsion must be finite")
        out.append(EccStory(name, shear, e, target, target - prev_target, shear_source))
        prev_target, prev_shear = target, shear
    return out
