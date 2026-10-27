from collections import Counter
from dataclasses import replace

from air_apparent.categorization import categorize, detect_group_conflicts
from air_apparent.models import Override, Shell
from air_apparent.pressures import calculate_pressures


def test_demo_fully_categorized(cfg, snap):
    c = categorize(cfg, snap)
    counts = Counter(o.category for o in c.objects.values())
    assert counts["main_wall"] == 40 and counts["main_roof_parapet"] == 16 and counts["picture_frame_parapet"] == 4
    assert counts["penthouse_body"] == 8 and counts["penthouse_parapet"] == 8
    assert counts["equipment_support_joint"] == 72 and counts["mechanical_platform_frame"] == 4
    assert "unresolved" not in counts and c.objects["A:INT_1"].category == "excluded"
    assert len(c.pattern_groups["W_Wall_+X"]) == 40 and len(c.pattern_groups["W_Parapet_+Y"]) == 28
    assert len(c.pattern_groups["W_PH_+X"]) == 6 and len(c.pattern_groups["W_Mech_+X"]) == 2
    assert c.derived_dims["X"].parallel_l == 1472.0 and c.derived_dims["Y"].parallel_l == 240.0
    assert not [d for d in c.diagnostics if d.level == "error"]


def test_fine_groups_stable_and_direction_specific(cfg, snap):
    names = {g.name for g in categorize(cfg, snap).groups}
    assert any(n.startswith("WALL_L2_XPOS_WINDWARD_W_MIN") for n in names)
    assert any(n.startswith("WALL_L2_XNEG_WINDWARD_E_MAX") for n in names)
    assert not any(n.startswith("WALL_L2_XNEG_WINDWARD_E_MIN") for n in names)
    assert any(n.startswith("PARAPET_TYP_YPOS_WINDWARD_S") for n in names)
    assert any(n.startswith("PH1_XNEG_SIDE") for n in names)
    assert "MECH_CHILLER01_JOINTS" in names
    faster = replace(cfg, wind=replace(cfg.wind, basic_wind_speed_mph=150.0))
    assert {g.name for g in categorize(faster, snap).groups} == names
    assert not any(n.startswith("AA_PREVIEW") for n in names)


def test_side_faces_carry_their_family_pattern(cfg, snap):
    groups = {g.name: g for g in categorize(cfg, snap).groups}
    ph_side = next(g for n, g in groups.items() if n.startswith("PH1_XPOS_SIDE"))
    assert ph_side.pattern == "W_PH_+X" and ph_side.result_id == "WALL_SIDE_MIN"
    par_side = next(g for n, g in groups.items() if n.startswith("PARAPET_TYP_XPOS_SIDE"))
    assert par_side.pattern == "W_Parapet_+X" and par_side.result_id == "WALL_SIDE_MIN"
    assert not any(g.pattern.startswith("W_Wall") and g.category != "main_wall" for g in groups.values())


def test_local_axis_signs_split_groups(cfg, snap):
    groups = categorize(cfg, snap).groups
    flipped = [g for g in groups if g.name.endswith("_L3FLIP")]
    assert flipped and all(g.assignment_sign == -1 for g in flipped)
    assert all(g.assignment_sign == 1 for g in groups if not g.name.endswith("_L3FLIP"))


def test_no_conflicts_within_direction(cfg, snap):
    assert detect_group_conflicts(categorize(cfg, snap).groups) == []


def test_comparison_against_existing_groups(cfg, snap):
    snap.groups["W_Wall_+X"] = ["A:W_S_L2_1", "A:NOT_THERE"]
    c = categorize(cfg, snap)
    row = next(r for r in c.comparison if r.name == "W_Wall_+X")
    assert row.in_model == 2 and row.by_rules == 40 and row.missing_from_rules == ("A:NOT_THERE",)
    assert len(c.comparison) == 16


def test_stray_shell_is_reported_not_envelope_defining(cfg, snap):
    stray = Shell("STRAY", ((2000, 0, 0), (2010, 0, 0), (2010, 0, 20), (2000, 0, 20)), (0, -1, 0))
    snap.shells.append(stray)
    c = categorize(cfg, snap)
    assert c.envelope["x_max"] == 1472.0
    assert c.objects["A:STRAY"].category == "unresolved"
    assert any(d.code == "no_exterior_segment" and d.object_ref == "A:STRAY" for d in c.diagnostics)


def test_override_and_missing_objects(cfg, snap):
    cfg2 = replace(cfg, overrides={"INT_1": Override("stair_projection"), "NOPE": Override("excluded")})
    c = categorize(cfg2, snap)
    assert c.objects["A:INT_1"].category in ("stair_projection", "unresolved")
    assert any(d.code == "override_unknown_object" for d in c.diagnostics)


def test_missing_support_joint_and_frame_diagnostics(cfg, snap):
    snap.joints[:] = [j for j in snap.joints if j.name != "CH03_J2"]
    snap.frames[:] = [f for f in snap.frames if f.name != "PL1_C"]
    codes = [d.code for d in categorize(cfg, snap).diagnostics]
    assert "missing_support_joint" in codes and "missing_platform_frame" in codes


def test_dimension_discrepancy_from_segments(cfg, snap):
    wrong = replace(cfg, geometry=replace(
        cfg.geometry,
        x_wind=replace(cfg.geometry.x_wind, parallel_l=1500.0),
        y_wind=replace(cfg.geometry.y_wind, perpendicular_b=1500.0)))
    c = categorize(wrong, snap)
    assert any(d.code == "dimension_discrepancy" for d in c.diagnostics)
    assert c.derived_dims["X"].parallel_l == 1472.0
    ps = calculate_pressures(cfg, c.derived_dims)
    assert ps.dims["X"].parallel_l == 1472.0


def test_unresolved_shell_carries_a_load_issue(cfg, snap):
    stray = Shell("STRAY", ((2000, 0, 0), (2010, 0, 0), (2010, 0, 20), (2000, 0, 20)), (0, -1, 0))
    snap.shells.append(stray)
    c = categorize(cfg, snap)
    assert c.objects["A:STRAY"].load_issue and "no exterior segment" in c.objects["A:STRAY"].load_issue
    assert all(not o.load_issue for o in c.objects.values() if o.category != "unresolved")
