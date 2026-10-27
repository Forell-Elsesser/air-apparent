"""Conversion of calculation results + categories into object assignments."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from ..categorization import detect_group_conflicts
from ..models import (
    DIR_VECTORS,
    DIRECTIONS,
    Assignment,
    Categorization,
    Config,
    Diagnostic,
    GroupSpec,
    LEEWARD,
    LoadPlan,
    MAIN_PARAPET,
    MAIN_WALL,
    ModelSnapshot,
    PatternSpec,
    PENTHOUSE_BODY,
    PENTHOUSE_PARAPET,
    PICTURE_FRAME_PARAPET,
    PressureSet,
    SIDE,
    WINDWARD,
    mech_pattern_name,
)
from ..pressures import eccentric_torsion
from .specs import case_specs, pattern_specs


PLACEHOLDER_PRESSURE_PSF = 1.0
"""Temporary pressure magnitude used until the pressure module is wired in."""


@dataclass(frozen=True)
class PressurePair:
    """Maximum and minimum shell pressures, in psf."""

    max_psf: float
    min_psf: float


# First-pass values transcribed from pressure_results.txt.  Keep these
# provisional until the pressure module exposes structured results.
FIRST_PASS_PARAPET_PRESSURE = PressurePair(56.288522, -37.525681)
FIRST_PASS_PENTHOUSE_PRESSURE = PressurePair(40.588834, -40.588834)
FIRST_PASS_WALL_PRESSURES = {
    "L2": {
        "WINDWARD": PressurePair(27.600229, 14.690421),
        "LEEWARD_X": PressurePair(0.358606, -12.551202),
        "LEEWARD_Y": PressurePair(-8.785841, -21.695649),
        "SIDE": PressurePair(-14.882139, -27.791947),
    },
    "ROOF": {
        "WINDWARD": PressurePair(30.840096, 17.930288),
        "LEEWARD_X": PressurePair(0.358606, -12.551202),
        "LEEWARD_Y": PressurePair(-8.785841, -21.695649),
        "SIDE": PressurePair(-14.882139, -27.791947),
    },
}


@dataclass(frozen=True)
class PressurePatternPair:
    """The two ETABS load patterns associated with one shell-group pattern."""

    base_pattern: str
    max_pressure_pattern: str
    min_pressure_pattern: str
    max_pressure_psf: float = PLACEHOLDER_PRESSURE_PSF
    min_pressure_psf: float = -PLACEHOLDER_PRESSURE_PSF


def pair_pressure_patterns(base_patterns: Iterable[str]) -> list[PressurePatternPair]:
    """Create a max/min load-pattern pair for supported shell-group patterns."""

    pairs: list[PressurePatternPair] = []
    seen: set[str] = set()
    for base_pattern in base_patterns:
        if base_pattern in seen:
            continue
        seen.add(base_pattern)
        if not (
            base_pattern.startswith("W_Wall_")
            or base_pattern.startswith("W_Parapet_")
            or base_pattern.startswith("W_PH_")
        ):
            continue
        if base_pattern.endswith(("_p_max", "_p_min")):
            raise ValueError(f"base pattern already has a pressure suffix: {base_pattern!r}")
        pairs.append(PressurePatternPair(
            base_pattern=base_pattern,
            max_pressure_pattern=f"{base_pattern}_p_max",
            min_pressure_pattern=f"{base_pattern}_p_min",
        ))
    return pairs


def placeholder_pressure_pattern_specs(groups: Iterable[GroupSpec]) -> list[PatternSpec]:
    """Return ETABS pattern definitions for the placeholder max/min pairs."""

    pairs = pair_pressure_patterns(g.pattern for g in groups)
    return [
        PatternSpec(name, "Pressure", pair.base_pattern[-2:], "provisional")
        for pair in pairs
        for name in (pair.max_pressure_pattern, pair.min_pressure_pattern)
    ]


def build_placeholder_pressure_assignments(
    groups: Iterable[GroupSpec],
    pressure_psf: float = PLACEHOLDER_PRESSURE_PSF,
) -> list[Assignment]:
    """Assign temporary ``+/- pressure_psf`` values to shell-group members."""

    if pressure_psf <= 0:
        raise ValueError("pressure_psf must be positive")

    groups = list(groups)
    pairs = {p.base_pattern: p for p in pair_pressure_patterns(g.pattern for g in groups)}
    out: list[Assignment] = []
    for g in groups:
        pair = pairs.get(g.pattern)
        if pair is None or not g.members:
            continue
        for member in g.members:
            for pattern, code_pressure_psf in (
                (pair.max_pressure_pattern, pressure_psf),
                (pair.min_pressure_pattern, -pressure_psf),
            ):
                out.append(Assignment(
                    f"{pattern}|{member}", "shell_pressure", member, pattern,
                    g.assignment_sign * code_pressure_psf / 1000.0, "kip/ft2", "Local3",
                    f"PLACEHOLDER_{g.pattern}", group=g.name,
                    code_pressure_psf=code_pressure_psf, sign=g.assignment_sign,
                    direction=g.direction,
                    note="temporary +/-1 psf placeholder; replace with pressure-module output"))
    return out


def first_pass_pressure_pair(group: GroupSpec) -> PressurePair | None:
    """Return the provisional pressure pair for one categorized shell group."""
    if not group.members:
        return None
    if group.category in {MAIN_PARAPET, PICTURE_FRAME_PARAPET, PENTHOUSE_PARAPET}:
        return FIRST_PASS_PARAPET_PRESSURE
    if group.category == PENTHOUSE_BODY:
        return FIRST_PASS_PENTHOUSE_PRESSURE if group.role == WINDWARD else None
    if group.category != MAIN_WALL:
        return None

    band_pressures = FIRST_PASS_WALL_PRESSURES.get(group.band)
    if band_pressures is None:
        return None
    if group.role == WINDWARD:
        return band_pressures["WINDWARD"]
    if group.role == SIDE:
        return band_pressures["SIDE"]
    if group.role == LEEWARD:
        return band_pressures[f"LEEWARD_{group.direction[1]}"]
    return None


def build_pressure_assignments(groups: Iterable[GroupSpec]) -> list[Assignment]:
    """Assign first-pass max/min pressures to categorized shell groups."""
    groups = list(groups)
    pairs = {p.base_pattern: p for p in pair_pressure_patterns(g.pattern for g in groups)}
    out: list[Assignment] = []
    for group in groups:
        pair = pairs.get(group.pattern)
        pressure_pair = first_pass_pressure_pair(group)
        if pair is None or pressure_pair is None:
            continue
        for member in group.members:
            for pattern, code_pressure_psf in (
                (pair.max_pressure_pattern, pressure_pair.max_psf),
                (pair.min_pressure_pattern, pressure_pair.min_psf),
            ):
                out.append(Assignment(
                    f"{pattern}|{member}", "shell_pressure", member, pattern,
                    group.assignment_sign * code_pressure_psf / 1000.0, "kip/ft2", "Local3",
                    f"FIRST_PASS_{group.pattern}_{group.role}", group=group.name,
                    code_pressure_psf=code_pressure_psf, sign=group.assignment_sign,
                    direction=group.direction,
                    note="first-pass pressure_results.txt mapping; replace with pressure-module output"))
    return out


def mech_assignments(cfg: Config, ps: PressureSet, direction: str,
                     present: set[str] | None = None) -> list[Assignment]:
    """Signed mechanical assignments for one global direction (+X, -X, +Y, -Y).

    ``present`` limits assignments to objects (refs) that exist in the model.
    """
    axis, sgn = direction[1], DIR_VECTORS[direction][0 if direction[1] == "X" else 1]
    pattern = mech_pattern_name(axis)
    out: list[Assignment] = []
    for eq in cfg.equipment:
        force = ps.value(f"EQ_{eq.id}_F{axis}")
        for j in eq.support_joints:
            if present is not None and f"P:{j}" not in present:
                continue
            out.append(Assignment(
                f"{pattern}|P:{j}", "joint_force", f"P:{j}", pattern, sgn * force / 4.0, "kip", axis,
                f"EQ_{eq.id}_F{axis}", group=f"MECH_{eq.id}_JOINTS", direction=direction,
                note="equal share of horizontal resultant; overturning moment not included"))
    for pl in cfg.platforms:
        frames = pl.frames_x_wind if axis == "X" else pl.frames_y_wind
        plf = ps.value(f"PLAT_{pl.id}_LINE")
        for fr in frames:
            if present is not None and f"F:{fr}" not in present:
                continue
            out.append(Assignment(
                f"{pattern}|F:{fr}", "frame_line_load", f"F:{fr}", pattern, sgn * plf / 1000.0,
                "kip/ft", axis, f"PLAT_{pl.id}_LINE", group=f"MECH_{pl.id}_FRAMES_{axis}",
                direction=direction))
    return out


def verify_mech_reversibility(cfg: Config, ps: PressureSet) -> list[Diagnostic]:
    """Every mechanical assignment for -d must be the exact negative of the one for +d."""
    diags: list[Diagnostic] = []
    for axis in ("X", "Y"):
        pos = {a.id: a.value for a in mech_assignments(cfg, ps, f"+{axis}")}
        neg = {a.id: a.value for a in mech_assignments(cfg, ps, f"-{axis}")}
        if pos.keys() != neg.keys() or any(pos[k] != -neg[k] for k in pos):
            diags.append(Diagnostic("error", "mech_not_reversible",
                                    f"W_Mech_{axis}: -{axis} assignments are not exact reversals"))
    return diags


def build_assignments(cfg: Config, snap: ModelSnapshot, cats: Categorization,
                      ps: PressureSet) -> tuple[list[Assignment], list[Diagnostic]]:
    out: list[Assignment] = []
    diags: list[Diagnostic] = []
    for g in cats.groups:
        if cfg.loading.scope == "walls_parapets" and not g.pattern.startswith(("W_Wall_", "W_Parapet_")):
            continue
        if not g.pattern or not g.result_id or "|" in g.pattern:
            continue
        if g.result_id not in ps.results:
            diags.append(Diagnostic("error", "missing_result",
                                    f"{g.name}: no calculation result {g.result_id}"))
            continue
        res = ps.results[g.result_id]
        if g.category in ("mechanical_platform_frame",):
            continue  # handled by mech_assignments
        p = res.value
        for m in g.members:
            out.append(Assignment(
                f"{g.pattern}|{m}", "shell_pressure", m, g.pattern, g.assignment_sign * p / 1000.0,
                "kip/ft2", "Local3", g.result_id, group=g.name, code_pressure_psf=p,
                sign=g.assignment_sign, direction=g.direction,
                note="code pressure positive toward surface; sign converts to local axis 3"))
    present = set(cats.objects)
    if cfg.loading.scope == "walls_parapets":
        return out, diags
    mech = mech_assignments(cfg, ps, "+X", present) + mech_assignments(cfg, ps, "+Y", present)
    out += mech
    diags += verify_mech_reversibility(cfg, ps)
    for eq in cfg.equipment:
        if not eq.support_joints:
            diags.append(Diagnostic("warning", "equipment_loads_deferred",
                                    f"{eq.id}: configured by support frames only; its loads are not generated "
                                    "until equipment loads move to frame point loads (frames are grouped)"))
            continue
        if not any(f"P:{j}" in present for j in eq.support_joints):
            diags.append(Diagnostic("warning", "equipment_not_in_model",
                                    f"{eq.id}: no configured support joints exist; equipment receives no load"))
            continue
        total = sum(a.value for a in mech if a.object_ref in {f"P:{j}" for j in eq.support_joints}
                    and a.pattern.endswith("X"))
        if abs(total - ps.value(f"EQ_{eq.id}_FX")) > 1e-9:
            diags.append(Diagnostic("error", "force_conservation", f"{eq.id}: joint forces do not sum "
                                                                    "to the resultant"))
    e_assign, e_diags = _eccentric(cfg, snap, ps)
    return out + e_assign, diags + e_diags


def _eccentric(cfg: Config, snap: ModelSnapshot, ps: PressureSet):
    out: list[Assignment] = []
    diags: list[Diagnostic] = []
    stories = {s.name: s for s in snap.stories}
    for d in DIRECTIONS:
        shears = cfg.loading.story_shears_kip.get(d)
        pat = f"W_Ecc_{d}"
        if not shears:
            diags.append(Diagnostic("warning", "ecc_no_shears",
                                    f"{pat}: no story shears supplied; pattern has no assignments "
                                    "(provisional)"))
            continue
        axis = d[1]
        b = ps.dims[axis].perpendicular_b
        try:
            rows = eccentric_torsion(list(shears.items()), cfg.loading.eccentricity_ratio, b, "yaml")
        except ValueError as exc:
            diags.append(Diagnostic("error", "ecc_invalid_shears", f"{pat}: {exc}"))
            continue
        for r in rows:
            st = stories.get(r.story)
            if st is None or not st.reference_joint:
                diags.append(Diagnostic("error", "ecc_no_reference_joint",
                                        f"{pat}: story {r.story!r} has no diaphragm reference joint"))
                continue
            out.append(Assignment(
                f"{pat}|P:{st.reference_joint}", "joint_moment", f"P:{st.reference_joint}", pat,
                r.applied_moment_kip_ft, "kip-ft", "Mz", f"ECC_{d}", direction=d,
                note=f"e={r.eccentricity_ft:g} ft; target={r.target_torsion_kip_ft:g}; "
                     f"shear={r.cumulative_shear_kip:g} ({r.shear_source}); "
                     "incremental floor moment (provisional)"))
    return out, diags


def build_plan(cfg: Config, snap: ModelSnapshot, cats: Categorization, ps: PressureSet) -> LoadPlan:
    from ..combinations import build_combinations

    assignments, diags = build_assignments(cfg, snap, cats, ps)
    diags = list(cats.diagnostics) + detect_group_conflicts(cats.groups) + diags
    review = [o for o in cats.objects.values() if o.load_issue]
    if review:
        diags.append(Diagnostic("warning", "load_review_required",
                                f"{len(review)} classified object(s) need load review and receive no automatic load; "
                                "see AA_PREVIEW_REVIEW_* groups"))
    unresolved = [o for o in cats.objects.values() if o.category == "unresolved"]
    if unresolved:
        diags.append(Diagnostic("warning", "unresolved_objects",
                                f"{len(unresolved)} unresolved object(s) receive no load; see the "
                                "per-object diagnostics"))
    patterns, cases, combinations = pattern_specs(), case_specs(), build_combinations()
    groups = list(cats.groups)
    if cfg.loading.scope == "walls_parapets":
        patterns = [p for p in patterns if p.family in ("Wall", "Parapet")]
        pattern_names = {p.name for p in patterns}
        cases = [c for c in cases if all(p in pattern_names for p, _ in c.terms)]
        # W1-W4 include other families/torsion. Do not publish reduced versions under their names.
        combinations = []
        groups = [g for g in groups if not g.pattern or g.pattern in pattern_names]
        # The live model may already contain manually authored W_Wall/W_Parapet definitions.
        # Use separate component names instead of taking ownership of those existing loads.
        rename = {p.name: "AA_" + p.name for p in patterns}
        patterns = [replace(p, name=rename[p.name]) for p in patterns]
        cases = [replace(c, name="AA_" + c.name,
                         terms=tuple((rename[p], f) for p, f in c.terms)) for c in cases]
        assignments = [replace(a, id=rename[a.pattern] + "|" + a.object_ref,
                               pattern=rename[a.pattern]) for a in assignments]
        groups = [replace(g, pattern=rename.get(g.pattern, g.pattern)) for g in groups]
        diags.append(Diagnostic("info", "loading_scope",
                                "Wall/parapet component loads only; equipment, penthouse net forces, "
                                "torsion and W1-W4 combinations are omitted."))
    plan = LoadPlan(
        patterns=patterns, cases=cases, assignments=assignments,
        combinations=combinations, groups=groups, diagnostics=diags,
        notes=["Horizontal MWFRS only: roof uplift and C&C design are out of scope.",
               "W_Ecc and W1-W4 definitions are provisional (not yet engineering-reviewed).",
               "Equipment overturning moments are not included."])
    return plan
