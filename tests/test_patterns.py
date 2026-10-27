import math

from air_apparent.categorization import categorize
from air_apparent.models import Override
from air_apparent.patterns import (
    build_assignments,
    build_plan,
    case_specs,
    pattern_specs,
    verify_mech_reversibility,
)
from air_apparent.pressures import calculate_pressures


def test_pattern_and_case_counts():
    pats = pattern_specs()
    names = [p.name for p in pats]
    assert len(pats) == 18 and len(case_specs()) == 20
    assert "W_Mech_X" in names and "W_Mech_Y" in names
    assert not [n for n in names if n.startswith("AW_")]
    assert not [n for n in names if n.startswith("W_Mech_") and n[7:] in ("+X", "-X", "+Y", "-Y")]
    cases = {c.name: c.terms for c in case_specs()}
    assert cases["W_Mech_-X"] == (("W_Mech_X", -1.0),)
    assert cases["W_Mech_+Y"] == (("W_Mech_Y", 1.0),)
    assert next(p for p in pats if p.family == "Ecc").status == "provisional"


def test_mechanical_assignments(session):
    a = session.plan.assignments
    jx = [x for x in a if x.pattern == "W_Mech_X" and x.kind == "joint_force"]
    jy = [x for x in a if x.pattern == "W_Mech_Y" and x.kind == "joint_force"]
    assert len(jx) == len(jy) == 72
    ps = session.pressures
    assert math.isclose(jx[0].value, ps.value("EQ_CHILLER01_FX") / 4)  # full precision, not 0.88
    assert not [x for x in a if x.kind == "joint_force" and x.object_ref.startswith("F:")]
    frames = [x for x in a if x.kind == "frame_line_load"]
    assert len(frames) == 4
    assert math.isclose(frames[0].value, 0.14270545387904406)
    assert verify_mech_reversibility(session.cfg, ps) == []




def test_minus_x_uses_max_branch(session):
    a = [x for x in session.plan.assignments if x.pattern == "W_Wall_-X"]
    assert any(x.result_id.endswith("_MAX") for x in a)
    assert not any(x.result_id.endswith("_MIN") for x in a)
    p = [x for x in session.plan.assignments if x.pattern == "W_Wall_+X"]
    assert not any(x.result_id.endswith("_MAX") for x in p)


def test_shell_sign_conversion(session):
    for x in session.plan.assignments:
        if x.kind == "shell_pressure":
            assert math.isclose(x.value, x.sign * x.code_pressure_psf / 1000.0)
    # leeward positive pressure (Max branch) is preserved, not forced to suction
    lw = [x for x in session.plan.assignments if x.result_id == "WALL_LW_X_MAX"]
    assert lw and all(x.code_pressure_psf > 0 for x in lw)


def test_eccentric_assignments_incremental(session):
    ecc = [x for x in session.plan.assignments if x.pattern == "W_Ecc_+X"]
    assert sorted(round(x.value, 6) for x in ecc) == [3600.0, 4320.0]


def test_missing_story_shears_keeps_pattern_empty_and_flagged(cfg, snap):
    from dataclasses import replace
    cfg2 = replace(cfg, loading=replace(cfg.loading, story_shears_kip={}))
    c = categorize(cfg2, snap)
    plan = build_plan(cfg2, snap, c, calculate_pressures(cfg2))
    assert any(d.code == "ecc_no_shears" for d in plan.diagnostics)
    assert len(plan.patterns) == 18


def test_side_faces_follow_their_family_pattern(session):
    a = session.plan.assignments
    ph_side = [x for x in a if x.object_ref in ("A:PH1_N", "A:PH1_S") and x.pattern == "W_PH_+X"]
    assert len(ph_side) == 2 and all(x.result_id == "WALL_SIDE_MIN" for x in ph_side)
    windward = {x.object_ref for x in a if x.pattern == "W_PH_+X" and x.result_id.startswith("PH_")}
    assert windward == {"A:PH1_W", "A:PH2_W"}
    parapet_side = [x for x in a if x.object_ref.startswith("A:P_N") and x.pattern == "W_Parapet_+X"]
    assert parapet_side and all(x.result_id == "WALL_SIDE_MIN" for x in parapet_side)
    wall_targets = {x.object_ref for x in a if x.pattern.startswith("W_Wall_")}
    assert not any(r.startswith(("A:P_", "A:PH")) for r in wall_targets)


def test_penthouse_side_shell_with_arbitrary_name(cfg, snap):
    """A penthouse side shell gets its side pressure under W_PH whatever it is called."""
    from dataclasses import replace
    snap.shells[:] = [replace(s, name="1604") if s.name == "PH1_N" else s for s in snap.shells]
    c = categorize(cfg, snap)
    a, _ = build_assignments(cfg, snap, c, calculate_pressures(cfg))
    assert c.objects["A:1604"].category == "penthouse_body"
    assert any(x.object_ref == "A:1604" and x.pattern == "W_PH_+X" and x.result_id == "WALL_SIDE_MIN" for x in a)


def test_frames_only_equipment_is_deferred(cfg, snap):
    from dataclasses import replace
    first = replace(cfg.equipment[0], support_joints=(), support_frames=("PL1_A", "PL1_B", "PL1_C", "PL1_D"))
    cfg2 = replace(cfg, equipment=(first,) + cfg.equipment[1:])
    plan = build_plan(cfg2, snap, categorize(cfg2, snap), calculate_pressures(cfg2))
    assert any(d.code == "equipment_loads_deferred" and "CHILLER01" in d.message for d in plan.diagnostics)
    assert not [d for d in plan.diagnostics if d.code == "force_conservation"]
    assert len([x for x in plan.assignments if x.pattern == "W_Mech_X" and x.kind == "joint_force"]) == 68
    assert "AA_PREVIEW" not in " ".join(d.message for d in plan.diagnostics)
    assert Override  # imported for symmetry with the categorization tests
