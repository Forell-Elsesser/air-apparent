"""Analysis-result provenance and validation, separate from pressure calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .etabs.shears import ShearResults
from .models import DIRECTIONS, ModelSnapshot, PressureSet
from .pressures.eccentricity import EccStory, eccentric_torsion


@dataclass(frozen=True)
class ShearReview:
    direction: str
    scale: float
    source: ShearResults
    rows: tuple[EccStory, ...]
    input_revision: str
    base_shear_kip: float
    base_target_kip_ft: float


@dataclass(frozen=True)
class AdoptedShears:
    review: ShearReview
    reference_joints: tuple[tuple[str, str], ...]


def review_shears(source: ShearResults, direction: str, scale: float, ratio: float,
                  snap: ModelSnapshot, pressures: PressureSet, revision: str) -> ShearReview:
    if direction not in DIRECTIONS:
        raise ValueError("choose +X, -X, +Y or -Y")
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("source multiplier must be finite and greater than zero")
    if source.location != "Bottom":
        raise ValueError("eccentricity requires consistent Bottom story cuts")
    axis = direction[1]
    stories = sorted((s for s in snap.stories if s.elevation_ft > snap.base_elevation_ft + 1e-6),
                     key=lambda s: s.elevation_ft, reverse=True)
    values = {s.story: s.vx_kip if axis == "X" else s.vy_kip for s in source.stories}
    if len(values) != len(source.stories) or set(values) != {s.name for s in stories}:
        raise ValueError("story shear coverage must match every model story above the base elevation")
    signed = [values[s.name] for s in stories]
    if not signed or any(not math.isfinite(v) for v in signed):
        raise ValueError("missing or non-finite story shears")
    # Reactions oppose applied loads; story section-force signs depend on the cut.
    # Keep both raw signs for review, but derive a positive torsion magnitude for
    # the existing +/-E combination branches. Never take abs before summing cases.
    if any(v > 1e-8 for v in signed) and any(v < -1e-8 for v in signed):
        raise ValueError("story shear reverses sign; choose compatible directional wind cases")
    base_raw = source.base_fx_kip if axis == "X" else source.base_fy_kip
    base = abs(base_raw) * scale
    if not math.isfinite(base) or base <= 0:
        raise ValueError("base shear must be finite and nonzero in the selected axis")
    lowest = abs(signed[-1]) * scale
    if not math.isclose(base, lowest, rel_tol=1e-3, abs_tol=0.01):
        raise ValueError(f"base/story shear mismatch: base={base:g}, lowest Bottom={lowest:g} kip; "
                         "check base elevation, story coverage and source cases")
    source_note = f"ETABS Bottom; cases={'+'.join(source.cases)}; multiplier={scale:g}"
    rows = eccentric_torsion([(s.name, abs(values[s.name]) * scale) for s in stories], ratio,
                             pressures.dims[axis].perpendicular_b, source_note)
    return ShearReview(direction, scale, source, tuple(rows), revision, base,
                       base * rows[0].eccentricity_ft)
