"""Declared exterior segments: resolution against grid lines and placement of shells on them.

A segment is a line (constant X or constant Y), a range along it, which side is outside, and an
optional height range. Shells are placed on the segment that overlaps the largest share of their
plan extent (spec section 6, R3); nothing is inferred from an envelope or from local axes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..models import CategorizationSettings, Diagnostic, ExteriorSegment, GridLine, Penthouse

_EPS = 1e-6


@dataclass(frozen=True)
class ResolvedSegment:
    id: str
    axis: str  # "x" for a line of constant X, "y" for constant Y
    ordinate_ft: float
    start_ft: float  # along the perpendicular axis
    end_ft: float
    outside: str  # "+X" | "-X" | "+Y" | "-Y" | "none"
    component: str = ""  # penthouse id for footprint edges
    z_from: float | None = None
    z_to: float | None = None


def _lookup(label: str, grid_lines: Sequence[GridLine]) -> GridLine | None:
    return next((g for g in grid_lines if g.label == label), None)


def resolve_segments(segments: Sequence[ExteriorSegment],
                     grid_lines: Sequence[GridLine]) -> tuple[list[ResolvedSegment], list[Diagnostic]]:
    """Turn YAML segments (grid labels or feet) into numeric segments; report what cannot resolve."""
    out: list[ResolvedSegment] = []
    diags: list[Diagnostic] = []
    for seg in segments:
        bad = False
        if isinstance(seg.along, str):
            line = _lookup(seg.along, grid_lines)
            if line is None:
                diags.append(Diagnostic("error", "grid_label_unknown",
                                        f"segment {seg.id}: grid line {seg.along!r} is not in the model", seg.id))
                continue
            axis, ordinate = line.axis, line.ordinate_ft
        else:
            axis, ordinate = seg.axis, float(seg.along)
            twin = next((g for g in grid_lines if g.axis == axis and _same_number(g.label, ordinate)), None)
            if twin is not None:
                diags.append(Diagnostic("warning", "numeric_along_matches_label",
                                        f"segment {seg.id}: along={ordinate:g} was read as {ordinate:g} ft; quote it "
                                        f"as \"{twin.label}\" if you meant grid line {twin.label} "
                                        f"at {twin.ordinate_ft:g} ft", seg.id))
        perp = "y" if axis == "x" else "x"
        ends: list[float] = []
        for key, ref in (("from", seg.start), ("to", seg.end)):
            if isinstance(ref, str):
                line = _lookup(ref, grid_lines)
                if line is None:
                    diags.append(Diagnostic("error", "grid_label_unknown",
                                            f"segment {seg.id}: grid line {ref!r} ({key}) is not in the model", seg.id))
                    bad = True
                    continue
                if line.axis != perp:
                    diags.append(Diagnostic("error", "grid_label_axis",
                                            f"segment {seg.id}: {key}={ref!r} must be a line of constant "
                                            f"{perp.upper()}", seg.id))
                    bad = True
                    continue
                ends.append(line.ordinate_ft)
            else:
                ends.append(float(ref))
        if bad:
            continue
        lo, hi = sorted(ends)
        out.append(ResolvedSegment(seg.id, axis, ordinate, lo, hi, seg.outside, "", seg.z_from, seg.z_to))
    overlapping: set[str] = set()
    for i, a in enumerate(out):
        for b in out[i + 1:]:
            if a.axis == b.axis and abs(a.ordinate_ft - b.ordinate_ft) < _EPS \
                    and min(a.end_ft, b.end_ft) - max(a.start_ft, b.start_ft) > _EPS and _heights_overlap(a, b):
                overlapping.update((a.id, b.id))
    for sid in sorted(overlapping):
        diags.append(Diagnostic("error", "segment_overlap",
                                f"segment {sid}: overlaps another segment on the same line in range and height", sid))
    return [s for s in out if s.id not in overlapping], diags


def _same_number(label: str, value: float) -> bool:
    try:
        return abs(float(label) - value) < 1e-9
    except ValueError:
        return False


def _heights_overlap(a: ResolvedSegment, b: ResolvedSegment) -> bool:
    lo = max(a.z_from if a.z_from is not None else -1e30, b.z_from if b.z_from is not None else -1e30)
    hi = min(a.z_to if a.z_to is not None else 1e30, b.z_to if b.z_to is not None else 1e30)
    return hi - lo > _EPS


def penthouse_edges(ph: Penthouse) -> list[ResolvedSegment]:
    """The four footprint edges of a penthouse with their outward normals."""
    return [
        ResolvedSegment(f"{ph.id}_W", "x", ph.x_min, ph.y_min, ph.y_max, "-X", ph.id),
        ResolvedSegment(f"{ph.id}_E", "x", ph.x_max, ph.y_min, ph.y_max, "+X", ph.id),
        ResolvedSegment(f"{ph.id}_S", "y", ph.y_min, ph.x_min, ph.x_max, "-Y", ph.id),
        ResolvedSegment(f"{ph.id}_N", "y", ph.y_max, ph.x_min, ph.x_max, "+Y", ph.id),
    ]


def place(axis: str, ordinate: float, lo: float, hi: float, z_mid: float,
          candidates: Sequence[ResolvedSegment],
          settings: CategorizationSettings) -> tuple[ResolvedSegment | None, str]:
    """Place a shell (plane ``axis=ordinate``, plan extent ``lo..hi``) on the best segment.

    Returns ``(segment, "placed")``, ``(None, "none")`` or ``(None, "ambiguous")``.
    """
    width = hi - lo
    scored: list[tuple[float, ResolvedSegment]] = []
    for c in candidates:
        if c.axis != axis or abs(c.ordinate_ft - ordinate) > settings.plane_tolerance_ft:
            continue
        if c.z_from is not None and z_mid < c.z_from - _EPS:
            continue
        if c.z_to is not None and z_mid > c.z_to + _EPS:
            continue
        overlap = min(hi, c.end_ft) - max(lo, c.start_ft)
        if overlap <= _EPS or (width > _EPS and overlap < 0.5 * width - _EPS):
            continue
        scored.append((overlap, c))
    if not scored:
        return None, "none"
    scored.sort(key=lambda t: -t[0])
    if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < _EPS:
        return None, "ambiguous"
    return scored[0][1], "placed"
