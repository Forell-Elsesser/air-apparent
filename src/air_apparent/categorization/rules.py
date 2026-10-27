"""Rule-based categorization of shells and frames (spec section 6: R0-R5 and R7).

Inputs are the story bands of the connected model, the declared exterior segments and penthouse
footprints, and plain geometry. Story labels and local axes are never consulted. Every vertical
shell ends in a category, a declared exclusion, or a diagnostic that names it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..models import (
    DIR_VECTORS,
    EQUIPMENT_JOINT,
    EQUIPMENT_SUPPORT_FRAME,
    EXCLUDED,
    MAIN_PARAPET,
    MAIN_WALL,
    PENTHOUSE_BODY,
    PENTHOUSE_PARAPET,
    PICTURE_FRAME_PARAPET,
    PLATFORM_FRAME,
    UNRESOLVED,
    Categorization,
    CategorizationSettings,
    Config,
    Diagnostic,
    LevelRoles,
    ModelSnapshot,
    ObjectCategory,
    PlanDims,
    Shell,
    frame_ref,
    joint_ref,
    shell_ref,
)
from .segments import ResolvedSegment, penthouse_edges, place, resolve_segments

Band = tuple[str, float, float]  # (story name, bottom, top)
_EPS = 1e-6
WALL, PARAPET, PH_BODY, PH_PARAPET = "wall", "parapet", "penthouse_body", "penthouse_parapet"


# --------------------------------------------------------------------------- R0 geometry
@dataclass(frozen=True)
class ShellGeometry:
    ref: str
    vertical: bool
    axis_aligned: bool
    axis: str  # "x" (plane of constant X) or "y"
    ordinate: float
    lo: float  # plan extent along the perpendicular axis
    hi: float
    zmin: float
    zmax: float


def _collinear(plan: list[tuple[float, float]], tol: float) -> bool:
    (ax, ay), (bx, by) = max(((p, q) for p in plan for q in plan), key=lambda pq: math.dist(pq[0], pq[1]))
    length = math.hypot(bx - ax, by - ay)
    if length < _EPS:
        return False
    return all(abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / length <= tol for px, py in plan)


def shell_geometry(shell: Shell, settings: CategorizationSettings) -> ShellGeometry:
    tol = settings.plane_tolerance_ft
    zs = [c[2] for c in shell.corners]
    zmin, zmax = min(zs), max(zs)
    plan: list[tuple[float, float]] = []
    for x, y, _ in shell.corners:
        if not any(math.hypot(x - a, y - b) < _EPS for a, b in plan):
            plan.append((x, y))
    ref = shell_ref(shell.name)
    vertical = (zmax - zmin) > tol and len(plan) >= 2 and _collinear(plan, tol)
    if not vertical:
        return ShellGeometry(ref, False, False, "", 0.0, 0.0, 0.0, zmin, zmax)
    xs, ys = [p[0] for p in plan], [p[1] for p in plan]
    if max(xs) - min(xs) <= tol:
        return ShellGeometry(ref, True, True, "x", sum(xs) / len(xs), min(ys), max(ys), zmin, zmax)
    if max(ys) - min(ys) <= tol:
        return ShellGeometry(ref, True, True, "y", sum(ys) / len(ys), min(xs), max(xs), zmin, zmax)
    return ShellGeometry(ref, True, False, "", 0.0, 0.0, 0.0, zmin, zmax)


# --------------------------------------------------------------------------- R1 / R2 levels
def story_bands(snap: ModelSnapshot) -> list[Band]:
    """One band per story, bottom-up: (name, bottom, top]."""
    out: list[Band] = []
    bottom = snap.base_elevation_ft
    for s in sorted(snap.stories, key=lambda s: s.elevation_ft):
        out.append((s.name, bottom, s.elevation_ft))
        bottom = s.elevation_ft
    return out


def level_of_top(zmax: float, bands: Sequence[Band], settings: CategorizationSettings) -> str | None:
    for name, _bottom, top in bands:
        if zmax <= top + settings.level_tolerance_ft:
            return name
    return None


def element_type(level: str, levels: LevelRoles, bands: Sequence[Band]) -> str | None:
    names = [b[0] for b in bands]
    if level not in names:
        return None
    if levels.main_roof in names and names.index(level) <= names.index(levels.main_roof):
        return WALL
    if level in levels.parapet:
        return PARAPET
    if level in levels.penthouse_body:
        return PH_BODY
    if level in levels.penthouse_parapet:
        return PH_PARAPET
    return None


# --------------------------------------------------------------------------- R3 / R5 shells
def _normal(outside: str) -> tuple[float, float, float] | None:
    return DIR_VECTORS.get(outside)


def categorize_shells(cfg: Config, snap: ModelSnapshot) -> tuple[dict[str, ObjectCategory], list[Diagnostic]]:  # noqa: C901
    settings = cfg.categorization
    bands = story_bands(snap)
    diags: list[Diagnostic] = []
    objects: dict[str, ObjectCategory] = {}
    levels = cfg.levels
    if levels is None:
        diags.append(Diagnostic("error", "levels_missing", "YAML has no levels section; no shell can be categorized"))
        return objects, diags
    band_names = {b[0] for b in bands}
    for name in (levels.main_roof, *levels.parapet, *levels.penthouse_body, *levels.penthouse_parapet):
        if name not in band_names:
            diags.append(Diagnostic("warning", "level_not_in_model", f"levels: story {name!r} is not in the model"))
    segs, sdiags = resolve_segments(cfg.exterior_segments, snap.grid_lines)
    diags += sdiags
    edges = [e for ph in cfg.penthouses for e in penthouse_edges(ph)]
    ph_by_id = {ph.id: ph for ph in cfg.penthouses}
    grade = cfg.grade_datum_model_elevation_ft
    roof_top = next((top for name, _b, top in bands if name == levels.main_roof), None)
    body_bottoms = [bottom for name, bottom, _t in bands if name in levels.penthouse_body]
    body_bottom = min(body_bottoms) if body_bottoms else None
    shell_names = {s.name for s in snap.shells}
    for k in cfg.overrides:
        if k not in shell_names:
            diags.append(Diagnostic("warning", "override_unknown_object",
                                    f"override target {k!r} is not a shell in the model", k))
    geoms = {s.name: shell_geometry(s, settings) for s in snap.shells}
    above_roof = [g for g in geoms.values()
                  if g.vertical and g.axis_aligned and roof_top is not None
                  and g.zmin >= roof_top - settings.level_tolerance_ft]

    def stack_top(g: ShellGeometry) -> float:
        """Highest top edge among the above-roof shells on this plane whose plan extents overlap this one."""
        return max((o.zmax for o in above_roof if o.axis == g.axis
                    and abs(o.ordinate - g.ordinate) <= settings.plane_tolerance_ft
                    and min(o.hi, g.hi) - max(o.lo, g.lo) > _EPS), default=g.zmax)

    def parapet_type_for(top: float) -> str:
        for t in cfg.parapets:
            if t.kind in ("main_roof", "picture_frame") and abs(t.top_elevation_above_grade_ft - (top - grade)) \
                    <= settings.level_tolerance_ft:
                return t.id
        return ""

    for s in snap.shells:
        g = geoms[s.name]
        ref = g.ref
        ov = cfg.overrides.get(s.name)
        level = level_of_top(g.zmax, bands, settings) if g.vertical else ""
        fields: dict = {"level": level or ""}
        diag: Diagnostic | None = None
        if not g.vertical:
            category, reason = EXCLUDED, "floor or sloped shell; no horizontal MWFRS load"
        elif not g.axis_aligned:
            category, reason = UNRESOLVED, "vertical shell not parallel to global X or Y"
            diag = Diagnostic("warning", "not_axis_aligned", f"{ref}: {reason}", ref)
        elif level is None:
            category, reason = UNRESOLVED, f"top at z={g.zmax:g} ft is above the highest story"
            diag = Diagnostic("warning", "above_top_story", f"{ref}: {reason}", ref)
        else:
            etype = element_type(level, levels, bands)
            where = (f"{g.axis}={g.ordinate:g} ft, extent {g.lo:g}-{g.hi:g} ft, z {g.zmin:g}-{g.zmax:g} ft")
            z_mid = (g.zmin + g.zmax) / 2
            if etype is None:
                category, reason = UNRESOLVED, f"level {level!r} has no role in levels"
                diag = Diagnostic("warning", "level_unmapped", f"{ref}: {reason}", ref)
            elif etype in (WALL, PARAPET):
                seg, status = place(g.axis, g.ordinate, g.lo, g.hi, z_mid, segs, settings)
                edge, estatus = (place(g.axis, g.ordinate, g.lo, g.hi, z_mid, edges, settings)
                                 if etype == PARAPET else (None, "none"))
                if status == "ambiguous":
                    category, reason = UNRESOLVED, f"{where} matches two exterior segments equally"
                    diag = Diagnostic("error", "ambiguous_segment", f"{ref}: {reason}", ref)
                elif seg is not None and seg.outside == "none":
                    category, reason = EXCLUDED, f"on segment {seg.id}, declared not exposed"
                    fields.update(segment_id=seg.id, side=seg.id)
                    diag = Diagnostic("info", "declared_unexposed", f"{ref}: {reason}", ref)
                elif seg is not None:
                    fields.update(segment_id=seg.id, outside=seg.outside, side=seg.id,
                                  outward_normal=_normal(seg.outside))
                    if etype == WALL:
                        category, reason = MAIN_WALL, f"on exterior segment {seg.id}, level {level}"
                    else:
                        top = stack_top(g)
                        split_body = (edge is not None and body_bottom is not None
                                      and top > body_bottom + settings.level_tolerance_ft)
                        if split_body:
                            category, reason = PENTHOUSE_BODY, f"on {edge.id}; stack reaches {top:g} ft (split body)"
                            fields.update(segment_id=edge.id, outside=edge.outside, side=edge.id,
                                          component=edge.component, outward_normal=_normal(edge.outside))
                        else:
                            ptype = parapet_type_for(top)
                            if not ptype:
                                category = UNRESOLVED
                                reason = f"parapet stack top {top - grade:g} ft above grade matches no parapet type"
                                diag = Diagnostic("warning", "parapet_type_unmatched", f"{ref}: {reason}", ref)
                            else:
                                kind = next(t.kind for t in cfg.parapets if t.id == ptype)
                                category = PICTURE_FRAME_PARAPET if kind == "picture_frame" else MAIN_PARAPET
                                reason = f"parapet type {ptype} on exterior segment {seg.id}, level {level}"
                                fields.update(parapet_type=ptype)
                    if seg is not None and (g.lo < seg.start_ft - settings.extent_tolerance_ft
                                            or g.hi > seg.end_ft + settings.extent_tolerance_ft):
                        diags.append(Diagnostic("warning", "extent_exceeds_segment",
                                                f"{ref}: extent {g.lo:g}-{g.hi:g} ft exceeds segment {seg.id} "
                                                f"({seg.start_ft:g}-{seg.end_ft:g} ft)", ref))
                elif edge is not None:
                    category, reason = PENTHOUSE_BODY, f"on penthouse edge {edge.id} below the penthouse level"
                    fields.update(segment_id=edge.id, outside=edge.outside, side=edge.id, component=edge.component,
                                  outward_normal=_normal(edge.outside))
                    diag = Diagnostic("warning", "body_below_penthouse_level", f"{ref}: {reason}", ref)
                else:
                    category, reason = UNRESOLVED, f"{where} matches no exterior segment"
                    diag = Diagnostic("warning", "no_exterior_segment", f"{ref}: {reason}", ref)
            else:  # penthouse body or penthouse parapet
                edge, estatus = place(g.axis, g.ordinate, g.lo, g.hi, z_mid, edges, settings)
                if estatus == "ambiguous":
                    category, reason = UNRESOLVED, f"{where} matches two penthouse edges equally"
                    diag = Diagnostic("error", "ambiguous_segment", f"{ref}: {reason}", ref)
                elif edge is None:
                    category, reason = UNRESOLVED, f"{where} lies on no penthouse footprint edge"
                    diag = Diagnostic("warning", "no_penthouse_edge", f"{ref}: {reason}", ref)
                else:
                    category = PENTHOUSE_BODY if etype == PH_BODY else PENTHOUSE_PARAPET
                    reason = f"on penthouse edge {edge.id}, level {level}"
                    fields.update(segment_id=edge.id, outside=edge.outside, side=edge.id, component=edge.component,
                                  outward_normal=_normal(edge.outside))
                    if etype == PH_PARAPET:
                        fields.update(parapet_type=ph_by_id[edge.component].parapet_type or "")
                    tol = settings.extent_tolerance_ft
                    if g.lo < edge.start_ft - tol or g.hi > edge.end_ft + tol:
                        diags.append(Diagnostic("warning", "extent_exceeds_segment",
                                                f"{ref}: extent {g.lo:g}-{g.hi:g} ft exceeds edge {edge.id}", ref))
        if ov is not None:
            category, reason = ov.category, f"override: {ov.category}"
            fields["overridden"] = True
            if ov.component:
                fields["component"] = ov.component
            if ov.outside:
                fields.update(outside=ov.outside, outward_normal=_normal(ov.outside),
                              side=fields.get("side") or f"{ov.component or 'override'}_{ov.outside}")
            diag = None
            if category in (EXCLUDED, UNRESOLVED):
                fields.pop("outward_normal", None)
                fields.pop("outside", None)
            elif fields.get("outward_normal") is None:
                category, reason = UNRESOLVED, f"override {ov.category} needs an outside direction"
                diag = Diagnostic("warning", "override_needs_outside", f"{ref}: {reason}", ref)
        # Classification and load readiness are separate: an unresolved shell keeps its reason as a
        # load issue so the review table and the GUI can list it.
        objects[ref] = ObjectCategory(ref, category, reason, load_issue=reason if category == UNRESOLVED else "",
                                      **fields)
        if diag is not None:
            diags.append(diag)
    return objects, diags


# --------------------------------------------------------------------------- R7 frames / joints
def categorize_frames(cfg: Config, snap: ModelSnapshot) -> tuple[dict[str, ObjectCategory], list[Diagnostic]]:
    settings = cfg.categorization
    bands = story_bands(snap)
    diags: list[Diagnostic] = []
    out: dict[str, ObjectCategory] = {}
    frames = {f.name: f for f in snap.frames}
    joints = {j.name for j in snap.joints}
    mech = cfg.levels.mechanical if cfg.levels else ""

    def check_level(ref: str, name: str) -> None:
        f = frames[name]
        lvl = level_of_top(max(f.p1[2], f.p2[2]), bands, settings)
        if mech and lvl != mech:
            diags.append(Diagnostic("warning", "frame_level_unexpected",
                                    f"{ref}: top is in band {lvl!r}, expected the mechanical band {mech!r}", ref))

    for eq in cfg.equipment:
        for n in eq.support_frames:
            ref = frame_ref(n)
            if n not in frames:
                diags.append(Diagnostic("warning", "missing_support_frame",
                                        f"equipment {eq.id}: configured support beam {n!r} not found in model", ref))
                continue
            out[ref] = ObjectCategory(ref, EQUIPMENT_SUPPORT_FRAME, f"configured support beam of {eq.id}",
                                      component=eq.id, side="XY")
            check_level(ref, n)
        for n in eq.support_joints:
            ref = joint_ref(n)
            if n not in joints:
                diags.append(Diagnostic("warning", "missing_support_joint",
                                        f"equipment {eq.id}: configured support joint {n!r} not found in model", ref))
                continue
            out[ref] = ObjectCategory(ref, EQUIPMENT_JOINT, f"configured support of {eq.id}", component=eq.id)
    for pl in cfg.platforms:
        for axis, names in (("X", pl.frames_x_wind), ("Y", pl.frames_y_wind)):
            for n in names:
                ref = frame_ref(n)
                if n not in frames:
                    diags.append(Diagnostic("warning", "missing_platform_frame",
                                            f"platform {pl.id}: configured {axis}-wind frame {n!r} not found in model",
                                            ref))
                    continue
                prev = out.get(ref)
                if prev is not None and prev.category == EQUIPMENT_SUPPORT_FRAME:
                    continue  # equipment beams are already in every W_Mech group
                side = axis if prev is None or axis in prev.side else "XY"
                out[ref] = ObjectCategory(ref, PLATFORM_FRAME, f"configured platform {pl.id}", component=pl.id,
                                          side=side)
                if prev is None:
                    check_level(ref, n)
    for f in snap.frames:
        out.setdefault(frame_ref(f.name), ObjectCategory(
            frame_ref(f.name), EXCLUDED, "frame not configured as equipment support or platform member"))
    for j in snap.joints:
        out.setdefault(joint_ref(j.name), ObjectCategory(
            joint_ref(j.name), EXCLUDED, "joint not mapped to equipment; no direct wind load"))
    return out, diags


# --------------------------------------------------------------------------- composition
def _segment_extent(segs: Sequence[ResolvedSegment]) -> dict[str, float]:
    xs = [s.ordinate_ft for s in segs if s.axis == "x"]
    ys = [s.ordinate_ft for s in segs if s.axis == "y"]
    if not xs or not ys:
        return {}
    return {"x_min": min(xs), "x_max": max(xs), "y_min": min(ys), "y_max": max(ys)}


def categorize(cfg: Config, snap: ModelSnapshot) -> Categorization:
    from .groups import build_group_specs, build_pattern_groups, compare_groups

    out = Categorization()
    shells, sdiags = categorize_shells(cfg, snap)
    frames, fdiags = categorize_frames(cfg, snap)
    out.objects = {**shells, **frames}
    out.diagnostics = sdiags + fdiags + list(snap.read_diagnostics)
    bands = story_bands(snap)
    by_name = {b[0]: b for b in bands}
    for b in cfg.story_bands:
        if b.id not in by_name:
            out.diagnostics.append(Diagnostic("warning", "story_band_unknown_story",
                                              f"story_bands {b.id!r} names no story in the model"))
        elif abs(by_name[b.id][2] - b.top_model_elevation_ft) > 0.1:
            out.diagnostics.append(Diagnostic("warning", "story_band_elevation_mismatch",
                                              f"story_bands {b.id!r} top {b.top_model_elevation_ft:g} ft vs model "
                                              f"{by_name[b.id][2]:g} ft"))
    segs, _ = resolve_segments(cfg.exterior_segments, snap.grid_lines)
    env = _segment_extent(segs)
    out.envelope = env
    if env:
        lx, ly = env["x_max"] - env["x_min"], env["y_max"] - env["y_min"]
        out.derived_dims = {"X": PlanDims(lx, ly), "Y": PlanDims(ly, lx)}
        y = {"X": cfg.geometry.x_wind, "Y": cfg.geometry.y_wind}
        for axis, d in out.derived_dims.items():
            for name, a, b in (("parallel_l", d.parallel_l, y[axis].parallel_l),
                               ("perpendicular_b", d.perpendicular_b, y[axis].perpendicular_b)):
                if abs(a - b) > 0.005 * b:
                    out.diagnostics.append(Diagnostic(
                        "warning", "dimension_discrepancy",
                        f"{axis}-wind {name}: declared segments span {a:g} ft vs YAML {b:g} ft"))
    out.groups = build_group_specs(cfg, snap, out.objects)
    out.pattern_groups = build_pattern_groups(out.objects)
    out.comparison = compare_groups(out.pattern_groups, snap.groups)
    return out
