from dataclasses import replace

from air_apparent.categorization import categorize, detect_group_conflicts, face_role
from air_apparent.models import ModelSnapshot, Shell
from air_apparent.pressures import calculate_pressures


def _cat(cfg, snap):
    return categorize(cfg, snap)


def test_whole_model_categorized(cfg, snap):
    c = _cat(cfg, snap)
    counts = {}
    for o in c.objects.values():
        counts[o.category] = counts.get(o.category, 0) + 1
    assert counts["main_wall"] == 40 and counts["picture_frame_parapet"] == 4
    assert counts["main_roof_parapet"] == 16 and counts["penthouse_body"] == 8
    assert counts["penthouse_parapet"] == 8 and counts["equipment_support_joint"] == 72
    assert counts["mechanical_platform_frame"] == 4
    assert "unresolved" not in counts
    assert c.derived_dims["X"].parallel_l == 1472.0
    assert not [d for d in c.diagnostics if d.level == "error"]


def test_face_roles_per_direction():
    assert face_role((-1, 0, 0), "+X") == "WINDWARD"
    assert face_role((1, 0, 0), "+X") == "LEEWARD"
    assert face_role((0, 1, 0), "+X") == "SIDE"
    assert face_role((1, 0, 0), "-X") == "WINDWARD"
    assert face_role((0, -1, 0), "+Y") == "WINDWARD"


def test_group_naming_granular_and_stable(cfg, snap):
    names = {g.name for g in _cat(cfg, snap).groups}
    assert "AA_PREVIEW_WALL_L2_XPOS_WINDWARD_MIN" in names
    assert "AA_PREVIEW_WALL_ROOF_XNEG_WINDWARD_MAX" in names
    assert "AA_PREVIEW_PH1_XNEG_SIDE_MAX" in names or "AA_PREVIEW_PH1_XNEG_SIDE_MAX_L3FLIP" in names
    assert "AA_PREVIEW_PARAPET_TYP_YPOS_WINDWARD" in names or \
        "AA_PREVIEW_PARAPET_TYP_YPOS_WINDWARD_L3FLIP" in names
    assert "AA_PREVIEW_MECH_CHILLER01_JOINTS" in names
    # names do not change when the pressure changes
    faster = replace(cfg, wind=replace(cfg.wind, basic_wind_speed_mph=150.0))
    assert {g.name for g in _cat(faster, snap).groups} == names
    assert not any(ch.isdigit() and "." in n for n in names for ch in n)


def test_direction_specific_branch_in_groups(cfg, snap):
    groups = {g.name: g for g in _cat(cfg, snap).groups}
    assert any(n.startswith("AA_PREVIEW_WALL_L2_XNEG_WINDWARD_MAX") for n in groups)
    assert not any(n.startswith("AA_PREVIEW_WALL_L2_XNEG_WINDWARD_MIN") for n in groups)
    assert any(n.startswith("AA_PREVIEW_WALL_L2_YNEG_WINDWARD_MIN") for n in groups)


def test_local_axis_signs_split_groups(cfg, snap):
    groups = _cat(cfg, snap).groups
    flipped = [g for g in groups if g.name.endswith("_L3FLIP")]
    assert flipped and all(g.assignment_sign == -1 for g in flipped)
    assert all(g.assignment_sign == 1 for g in groups if not g.name.endswith("_L3FLIP"))


def test_no_conflicts_within_direction(cfg, snap):
    assert detect_group_conflicts(_cat(cfg, snap).groups) == []


def test_crossing_shell_reported_for_subdivision(cfg, snap):
    s = snap.shells[0]
    tall = Shell("TALL", tuple((x, y, 62.0 if z > 0 else 0.0) for x, y, z in s.corners), s.local3)
    snap2 = ModelSnapshot(shells=snap.shells[1:] + [tall], frames=snap.frames, joints=snap.joints,
                          stories=snap.stories)
    c = _cat(cfg, snap2)
    assert c.objects["A:TALL"].category == "unresolved"
    assert any(d.code == "needs_subdivision" and "band" in d.message for d in c.diagnostics)
    assert "AA_PREVIEW_UNRESOLVED" in {g.name for g in c.groups}


def test_stray_object_does_not_redefine_envelope(cfg, snap):
    stray = Shell("STRAY", ((2000, 0, 0), (2010, 0, 0), (2010, 0, 20), (2000, 0, 20)), (0, -1, 0))
    snap.shells.append(stray)
    c = _cat(cfg, snap)
    assert c.envelope["x_max"] == 1472.0
    assert c.objects["A:STRAY"].category == "unresolved"


def test_unsupported_layout_detected(cfg, snap):
    # remove half of the south face: the envelope edge is no longer fully covered
    kept = [s for s in snap.shells if not s.name.startswith("W_S_L2_") or s.name.endswith(("1", "2"))]
    snap2 = ModelSnapshot(shells=kept, frames=snap.frames, joints=snap.joints, stories=snap.stories)
    assert any(d.code == "unsupported_layout" and d.level == "error" for d in _cat(cfg, snap2).diagnostics)


def test_override_and_missing_objects(cfg, snap):
    cfg2 = replace(cfg, overrides={"INT_1": "stair_projection", "NOPE": "excluded"})
    c = _cat(cfg2, snap)
    assert c.objects["A:INT_1"].category in ("stair_projection", "unresolved")
    assert any(d.code == "override_unknown_object" for d in c.diagnostics)


def test_missing_support_joint_and_frame_diagnostics(cfg, snap):
    snap.joints[:] = [j for j in snap.joints if j.name != "CH03_J2"]
    snap.frames[:] = [f for f in snap.frames if f.name != "PL1_C"]
    codes = [d.code for d in _cat(cfg, snap).diagnostics]
    assert "missing_support_joint" in codes and "missing_platform_frame" in codes


def test_etabs_dimension_discrepancy_reported(cfg, snap):
    wrong = replace(cfg, geometry=replace(
        cfg.geometry,
        x_wind=replace(cfg.geometry.x_wind, parallel_l=1500.0),
        y_wind=replace(cfg.geometry.y_wind, perpendicular_b=1500.0)))
    c = _cat(wrong, snap)
    assert any(d.code == "dimension_discrepancy" for d in c.diagnostics)
    assert c.derived_dims["X"].parallel_l == 1472.0
    ps = calculate_pressures(cfg, c.derived_dims)
    assert ps.dims["X"].parallel_l == 1472.0
