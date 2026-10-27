"""Whole-model shell/frame/joint categorization using simple, inspectable rules.

Rules (documented in docs/module_interfaces.md):
1. Explicit YAML overrides (shells, by object name) force the category.
2. Horizontal shells are excluded; sloped or non-axis-aligned shells are unresolved.
3. Vertical shells on a configured penthouse footprint edge are penthouse body/parapet.
4. Remaining vertical shells are matched to the main-building envelope (bounding rectangle of
   the dominant axis-aligned wall lines). Below the main roof plane = main wall; above =
   parapet (type matched by top elevation above grade). Inside the envelope = excluded.
5. Shells crossing a roof plane or pressure-band boundary are unresolved with a subdivision note.
6. Frames/joints are categorized only through YAML platform/equipment mappings.
Existing ETABS groups are never used as authority.
"""

from __future__ import annotations

import math
from collections import defaultdict

from ..models import (
    CATEGORIES,
    EQUIPMENT_JOINT,
    EXCLUDED,
    MAIN_PARAPET,
    MAIN_WALL,
    PENTHOUSE_BODY,
    PENTHOUSE_PARAPET,
    PICTURE_FRAME_PARAPET,
    PLATFORM_FRAME,
    STAIR_PROJECTION,
    UNRESOLVED,
    Categorization,
    Config,
    Diagnostic,
    ModelSnapshot,
    ObjectCategory,
    Penthouse,
    PlanDims,
    Shell,
    frame_ref,
    joint_ref,
    shell_ref,
)
from .groups import build_group_specs

TOL = 0.25  # ft, geometric tolerance
TOP_TOL = 0.1  # ft, parapet top elevation match tolerance
EDGE_COVERAGE_MIN = 0.98

_Vec = tuple[float, float, float]


class _Facts:
    """Geometry of a vertical, axis-aligned shell."""

    def __init__(self, shell: Shell):
        zs = [c[2] for c in shell.corners]
        self.zmin, self.zmax = min(zs), max(zs)
        pts: list[tuple[float, float]] = []
        for c in shell.corners:
            if not any(math.hypot(c[0] - p[0], c[1] - p[1]) < 1e-6 for p in pts):
                pts.append((c[0], c[1]))
        self.pts = pts
        self.vertical = len(pts) == 2 and (self.zmax - self.zmin) > TOL
        self.axis = ""  # "x" if constant-x line (face normal along X), "y" likewise
        self.coord = 0.0
        self.lo = self.hi = 0.0
        if self.vertical:
            (x0, y0), (x1, y1) = pts
            if abs(x0 - x1) < TOL:
                self.axis, self.coord = "x", (x0 + x1) / 2
                self.lo, self.hi = sorted((y0, y1))
            elif abs(y0 - y1) < TOL:
                self.axis, self.coord = "y", (y0 + y1) / 2
                self.lo, self.hi = sorted((x0, x1))

    @property
    def length(self) -> float:
        return self.hi - self.lo


def _normal_of(axis: str, sign: int) -> _Vec:
    return (float(sign), 0.0, 0.0) if axis == "x" else (0.0, float(sign), 0.0)


def _ph_hit(f: _Facts, ph: Penthouse) -> _Vec | None:
    edges = (("x", ph.x_min, -1, ph.y_min, ph.y_max), ("x", ph.x_max, 1, ph.y_min, ph.y_max),
             ("y", ph.y_min, -1, ph.x_min, ph.x_max), ("y", ph.y_max, 1, ph.x_min, ph.x_max))
    for axis, coord, sign, lo, hi in edges:
        if f.axis == axis and abs(f.coord - coord) <= TOL and f.lo >= lo - TOL and f.hi <= hi + TOL:
            return _normal_of(axis, sign)
    return None


def _envelope(cfg: Config, facts: dict[str, _Facts]) -> dict[str, float]:
    """Dominant wall lines among below-roof, axis-aligned vertical shells."""
    main_roof = cfg.roof_planes[0].model_elevation_ft
    totals: dict[str, dict[float, float]] = {"x": defaultdict(float), "y": defaultdict(float)}
    for f in facts.values():
        if f.vertical and f.axis and f.zmax <= main_roof + TOL:
            totals[f.axis][round(f.coord * 4) / 4] += f.length
    env: dict[str, float] = {}
    for axis, key in (("x", "x"), ("y", "y")):
        t = totals[axis]
        if not t:
            continue
        big = max(t.values())
        main = sorted(c for c, v in t.items() if v >= 0.5 * big)
        env[f"{key}_min"], env[f"{key}_max"] = main[0], main[-1]
    return env


def categorize(cfg: Config, snap: ModelSnapshot) -> Categorization:  # noqa: C901
    out = Categorization()
    diags = out.diagnostics
    facts = {s.name: _Facts(s) for s in snap.shells}
    env = _envelope(cfg, facts) if snap.shells else {}
    out.envelope = env
    main_roof = cfg.roof_planes[0].model_elevation_ft
    grade = cfg.grade_datum_model_elevation_ft
    parapet_types = {p.id: p for p in cfg.parapets}
    shell_names = {s.name for s in snap.shells}
    for k in cfg.overrides:
        if k not in shell_names:
            diags.append(Diagnostic("warning", "override_unknown_object",
                                    f"override target {k!r} is not a shell in the model", k))

    have_env = all(k in env for k in ("x_min", "x_max", "y_min", "y_max"))
    if snap.shells and not have_env:
        diags.append(Diagnostic("error", "unsupported_layout",
                                "cannot determine a rectangular main-building envelope"))

    def on_env_edge(f: _Facts) -> _Vec | None:
        if not have_env or not f.axis:
            return None
        lo_key, hi_key = (("x_min", "x_max") if f.axis == "x" else ("y_min", "y_max"))
        span = (("y_min", "y_max") if f.axis == "x" else ("x_min", "x_max"))
        if f.lo < env[span[0]] - TOL or f.hi > env[span[1]] + TOL:
            return None
        if abs(f.coord - env[lo_key]) <= TOL:
            return _normal_of(f.axis, -1)
        if abs(f.coord - env[hi_key]) <= TOL:
            return _normal_of(f.axis, 1)
        return None

    def inside_env(f: _Facts) -> bool:
        return have_env and f.axis != "" and (
            env["x_min"] - TOL <= min(p[0] for p in f.pts) and max(p[0] for p in f.pts) <= env["x_max"] + TOL
            and env["y_min"] - TOL <= min(p[1] for p in f.pts) and max(p[1] for p in f.pts) <= env["y_max"] + TOL)

    def put(ref: str, cat: str, reason: str, **kw) -> None:
        out.objects[ref] = ObjectCategory(ref, cat, reason, **kw)

    def unresolved(ref: str, reason: str, code: str = "unresolved_object") -> None:
        put(ref, UNRESOLVED, reason)
        diags.append(Diagnostic("warning", code, reason, ref))

    for s in snap.shells:
        ref = shell_ref(s.name)
        f = facts[s.name]
        override = cfg.overrides.get(s.name)
        if not f.vertical:
            if len({round(c[2], 3) for c in s.corners}) == 1:
                put(ref, override or EXCLUDED, "horizontal shell; no horizontal MWFRS load in MVP",
                    overridden=bool(override))
            else:
                unresolved(ref, "sloped or non-planar shell; unsupported geometry")
            continue
        if not f.axis:
            unresolved(ref, "vertical shell not parallel to global X or Y; unsupported layout",
                       "unsupported_layout")
            continue
        # Penthouse?
        ph_found = next(((ph, n) for ph in cfg.penthouses if (n := _ph_hit(f, ph)) is not None
                         and f.zmin >= ph.base_model_elevation_ft - TOL), None)
        category = override
        n_out: _Vec | None = None
        comp = ptype = ""
        band = ""
        reason = ""
        if ph_found:
            ph, n_out = ph_found
            comp = ph.id
            body_top = ph.base_model_elevation_ft + ph.body_height_ft
            if f.zmin >= body_top - TOL:
                category = category or PENTHOUSE_PARAPET
                ptype = _match_parapet(parapet_types, f.zmax - grade, "penthouse")
                reason = f"on footprint edge of {ph.id}, above body top {body_top:g}"
            elif f.zmax > body_top + TOL:
                unresolved(ref, f"shell crosses top of penthouse {ph.id} body (z={body_top:g}); "
                                "subdivide at the penthouse roof", "needs_subdivision")
                continue
            else:
                category = category or PENTHOUSE_BODY
                reason = f"on footprint edge of {ph.id}, within body height"
        else:
            n_out = on_env_edge(f)
            if n_out is None:
                if category in (STAIR_PROJECTION,) and have_env:
                    n_out = _outward_from_center(f, env)
                    reason = "override: stair projection"
                elif inside_env(f):
                    category = category or EXCLUDED
                    reason = "interior to main-building envelope"
                    put(ref, category, reason, overridden=bool(override))
                    continue
                elif category:
                    pass
                else:
                    unresolved(ref, "outside the main-building envelope (stray object or unsupported "
                                    "layout); classify with an override", "unsupported_layout")
                    continue
            if n_out is not None and category not in (STAIR_PROJECTION,):
                if f.zmax <= main_roof + TOL:
                    cuts = [b.bottom_model_elevation_ft for b in cfg.story_bands]
                    cuts += [b.top_model_elevation_ft for b in cfg.story_bands]
                    bad = [z for z in cuts if f.zmin + TOL < z < f.zmax - TOL]
                    in_band = [b for b in cfg.story_bands if f.zmin >= b.bottom_model_elevation_ft - TOL
                               and f.zmax <= b.top_model_elevation_ft + TOL]
                    if bad:
                        unresolved(ref, f"shell crosses pressure-band boundary at z={bad[0]:g}; "
                                        "subdivide the shell there", "needs_subdivision")
                        continue
                    if not in_band:
                        unresolved(ref, "shell lies outside all configured story bands")
                        continue
                    band = in_band[0].id
                    category = category or MAIN_WALL
                    reason = f"on main envelope edge, band {band}"
                elif f.zmin >= main_roof - TOL:
                    ptype = _match_parapet(parapet_types, f.zmax - grade, "main")
                    if not ptype:
                        unresolved(ref, f"parapet top {f.zmax - grade:g} ft above grade matches no "
                                        "configured parapet type")
                        continue
                    kind = parapet_types[ptype].kind
                    category = category or (PICTURE_FRAME_PARAPET if kind == "picture_frame"
                                            else MAIN_PARAPET)
                    reason = f"parapet type {ptype} on main envelope above roof plane"
                else:
                    unresolved(ref, f"shell crosses main roof plane (z={main_roof:g}); "
                                    "subdivide at the roof plane", "needs_subdivision")
                    continue
        if category in (PENTHOUSE_PARAPET, MAIN_PARAPET, PICTURE_FRAME_PARAPET) and not ptype:
            unresolved(ref, "parapet top elevation matches no configured parapet type of this kind")
            continue
        if category in (PENTHOUSE_BODY, PENTHOUSE_PARAPET) and not comp:
            unresolved(ref, f"override {category} requires location on a penthouse footprint edge")
            continue
        if category is None or category not in CATEGORIES:
            unresolved(ref, "no rule matched")
            continue
        if category not in (EXCLUDED, UNRESOLVED) and n_out is None:
            unresolved(ref, f"override {category} could not determine the outward face normal")
            continue
        if category == STAIR_PROJECTION:
            diags.append(Diagnostic("warning", "stair_projection_no_treatment",
                                    "stair projection categorized; no wind treatment is defined in the "
                                    "MVP, review manually", ref))
        # local axis 3 must be normal to the shell
        if n_out is not None and abs(sum(a * b for a, b in zip(s.local3, n_out, strict=True))) < 0.99 \
                and category not in (EXCLUDED, UNRESOLVED):
            unresolved(ref, "local axis 3 is not normal to the shell face; check local axes")
            continue
        put(ref, category, reason or "explicit override", band=band, component=comp,
            parapet_type=ptype, outward_normal=n_out, overridden=bool(override))

    _frames_and_joints(cfg, snap, out)
    _dimensions(cfg, snap, facts, out, env, have_env)
    out.groups = build_group_specs(cfg, snap, out)
    return out


def _match_parapet(types: dict, top_above_grade: float, kind_family: str) -> str:
    for t in types.values():
        if (t.kind == "penthouse") == (kind_family == "penthouse") \
                and abs(t.top_elevation_above_grade_ft - top_above_grade) <= TOP_TOL:
            return t.id
    return ""


def _outward_from_center(f: _Facts, env: dict[str, float]) -> _Vec:
    cx, cy = (env["x_min"] + env["x_max"]) / 2, (env["y_min"] + env["y_max"]) / 2
    if f.axis == "x":
        return _normal_of("x", 1 if f.coord >= cx else -1)
    return _normal_of("y", 1 if f.coord >= cy else -1)


def _frames_and_joints(cfg: Config, snap: ModelSnapshot, out: Categorization) -> None:
    frames = {f.name for f in snap.frames}
    joints = {j.name for j in snap.joints}
    cat = out.objects
    for pl in cfg.platforms:
        for direction, names in (("X", pl.frames_x_wind), ("Y", pl.frames_y_wind)):
            for n in names:
                if n not in frames:
                    out.diagnostics.append(Diagnostic(
                        "warning", "missing_platform_frame",
                        f"platform {pl.id}: configured {direction}-wind frame {n!r} not found in model",
                        frame_ref(n)))
                    continue
                cat[frame_ref(n)] = ObjectCategory(frame_ref(n), PLATFORM_FRAME,
                                                   f"configured platform {pl.id}", component=pl.id)
    for eq in cfg.equipment:
        for n in eq.support_joints:
            if n not in joints:
                out.diagnostics.append(Diagnostic(
                    "warning", "missing_support_joint",
                    f"equipment {eq.id}: configured support joint {n!r} not found in model",
                    joint_ref(n)))
                continue
            cat[joint_ref(n)] = ObjectCategory(joint_ref(n), EQUIPMENT_JOINT,
                                               f"configured support of {eq.id}", component=eq.id)
    for f in snap.frames:
        cat.setdefault(frame_ref(f.name), ObjectCategory(
            frame_ref(f.name), EXCLUDED, "frame not mapped to a platform; no direct wind load"))
    for j in snap.joints:
        cat.setdefault(joint_ref(j.name), ObjectCategory(
            joint_ref(j.name), EXCLUDED, "joint not mapped to equipment; no direct wind load"))


def _dimensions(cfg, snap, facts, out: Categorization, env, have_env: bool) -> None:
    if not have_env:
        return
    lx = env["x_max"] - env["x_min"]
    ly = env["y_max"] - env["y_min"]
    out.derived_dims = {"X": PlanDims(lx, ly), "Y": PlanDims(ly, lx)}
    y = {"X": cfg.geometry.x_wind, "Y": cfg.geometry.y_wind}
    for axis, d in out.derived_dims.items():
        for name, a, b in (("parallel_l", d.parallel_l, y[axis].parallel_l),
                           ("perpendicular_b", d.perpendicular_b, y[axis].perpendicular_b)):
            if abs(a - b) > 0.005 * b:
                out.diagnostics.append(Diagnostic(
                    "warning", "dimension_discrepancy",
                    f"{axis}-wind {name}: ETABS envelope {a:g} ft vs YAML {b:g} ft"))
    # edge coverage check for unsupported layouts
    main_roof = cfg.roof_planes[0].model_elevation_ft
    low = [f for f in facts.values() if f.vertical and f.axis and f.zmax <= main_roof + TOL]
    if not low:
        return
    zlow = min(f.zmin for f in low)
    for axis, key, span in (("x", "x_min", ly), ("x", "x_max", ly), ("y", "y_min", lx),
                            ("y", "y_max", lx)):
        covered = sum(f.length for f in low if f.axis == axis and abs(f.coord - env[key]) <= TOL
                      and abs(f.zmin - zlow) <= TOL)
        if covered < EDGE_COVERAGE_MIN * span:
            out.diagnostics.append(Diagnostic(
                "error", "unsupported_layout",
                f"envelope edge {key}={env[key]:g} is only {covered / span:.0%} covered by wall "
                "shells at the lowest level; layout is not a single rectangular building"))
