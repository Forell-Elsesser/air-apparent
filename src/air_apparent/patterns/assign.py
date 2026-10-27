"""Conversion of calculation results + categories into object assignments."""

from __future__ import annotations

from ..categorization import detect_group_conflicts
from ..models import (
    DIR_VECTORS,
    DIRECTIONS,
    Assignment,
    Categorization,
    Config,
    Diagnostic,
    LoadPlan,
    ModelSnapshot,
    PressureSet,
    mech_pattern_name,
)
from ..pressures import eccentric_torsion
from .specs import case_specs, pattern_specs


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
                f"EQ_{eq.id}_F{axis}", group=f"AA_PREVIEW_MECH_{eq.id}_JOINTS", direction=direction,
                note="equal share of horizontal resultant; overturning moment not included"))
    for pl in cfg.platforms:
        frames = pl.frames_x_wind if axis == "X" else pl.frames_y_wind
        plf = ps.value(f"PLAT_{pl.id}_LINE")
        for fr in frames:
            if present is not None and f"F:{fr}" not in present:
                continue
            out.append(Assignment(
                f"{pattern}|F:{fr}", "frame_line_load", f"F:{fr}", pattern, sgn * plf / 1000.0,
                "kip/ft", axis, f"PLAT_{pl.id}_LINE", group=f"AA_PREVIEW_MECH_{pl.id}_FRAMES_{axis}",
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
    mech = mech_assignments(cfg, ps, "+X", present) + mech_assignments(cfg, ps, "+Y", present)
    out += mech
    diags += verify_mech_reversibility(cfg, ps)
    for eq in cfg.equipment:
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
    unresolved = [o for o in cats.objects.values() if o.category == "unresolved"]
    if unresolved:
        diags.append(Diagnostic("warning", "unresolved_objects",
                                f"{len(unresolved)} unresolved object(s) receive no load; see "
                                "AA_PREVIEW_UNRESOLVED"))
    plan = LoadPlan(
        patterns=pattern_specs(), cases=case_specs(), assignments=assignments,
        combinations=build_combinations(), groups=list(cats.groups), diagnostics=diags,
        notes=["Horizontal MWFRS only: roof uplift and C&C design are out of scope.",
               "W_Ecc and W1-W4 definitions are provisional (not yet engineering-reviewed).",
               "Equipment overturning moments are not included."])
    return plan
