import math

from air_apparent.categorization import categorize
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


def test_side_pressures_under_wall_pattern_and_ph_not_duplicated(session):
    a = session.plan.assignments
    ph_side = [x for x in a if x.object_ref.startswith("A:PH1_") and x.pattern == "W_Wall_+X"]
    assert ph_side, "penthouse side shells must receive W_Wall side pressure"
    assert all(x.result_id == "WALL_SIDE_MIN" for x in ph_side)
    assert not [x for x in a if x.pattern.startswith("W_PH_") and "SIDE" in x.result_id]
    ph_x = [x for x in a if x.pattern == "W_PH_+X"]
    # only windward body faces carry the net force; leeward body faces carry none
    assert {x.object_ref for x in ph_x} == {"A:PH1_W", "A:PH2_W"}
    parapet_side = [x for x in a if x.pattern == "W_Wall_+X" and x.object_ref.startswith("A:P_N")]
    assert parapet_side and all(x.result_id == "WALL_SIDE_MIN" for x in parapet_side)


def test_missing_ph_side_regression_with_synthetic_object(cfg, snap):
    """A penthouse side shell with an arbitrary name must always get its side pressure."""
    from dataclasses import replace
    snap.shells[:] = [replace(s, name="1604") if s.name == "PH1_N" else s for s in snap.shells]
    c = categorize(cfg, snap)
    a, _ = build_assignments(cfg, snap, c, calculate_pressures(cfg))
    assert any(x.object_ref == "A:1604" and x.pattern == "W_Wall_+X" for x in a)
    assert c.objects["A:1604"].category == "penthouse_body"


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
