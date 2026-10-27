"""Rules R0-R5 and R7 on hand-built snapshots shaped like the seven-story Test Model."""

from dataclasses import replace

import pytest

from air_apparent.categorization.rules import (
    categorize_frames,
    categorize_shells,
    element_type,
    level_of_top,
    shell_geometry,
    story_bands,
)
from air_apparent.models import (
    CategorizationSettings,
    Equipment,
    ExteriorSegment,
    Frame,
    GridLine,
    LevelRoles,
    ModelSnapshot,
    Override,
    ParapetType,
    Penthouse,
    Platform,
    Shell,
    Story,
)

S = CategorizationSettings()
BASE = -0.833
STORIES = [Story("L2", 31.5, 32.333), Story("R", 60.083, 28.583), Story("Parapet_1", 65.083, 5.0),
           Story("Mech", 70.708, 5.625), Story("Penthouse", 75.167, 4.458), Story("Parapet_2", 76.917, 1.75)]
BANDS = [("L2", BASE, 31.5), ("R", 31.5, 60.083), ("Parapet_1", 60.083, 65.083), ("Mech", 65.083, 70.708),
         ("Penthouse", 70.708, 75.167), ("Parapet_2", 75.167, 76.917)]
LV = LevelRoles("R", ("Parapet_1", "Mech"), ("Penthouse",), ("Parapet_2",), "Mech")
G = [GridLine("G1", "y", "J", 0.0), GridLine("G1", "y", "E", 238.0),
     GridLine("G1", "x", "28.5", 2.25), GridLine("G1", "x", "39", 421.75)]
TYP = ParapetType("TYP", "main_roof", 65.917, 5.0)
PF = ParapetType("PF", "picture_frame", 71.541, 10.625)
PHP = ParapetType("PHP", "penthouse", 77.75, 1.75)
PH1 = Penthouse("PH1", 266.083, 301.333, 214.25, 238.0, 60.083, 15.083, 70.0, 25.0, "PHP")
PH2 = Penthouse("PH2", 410.083, 421.75, 0.0, 238.0, 60.083, 15.083, 70.0, 11.0, "PHP")
J_W = ExteriorSegment("J_W", "J", 25.5, 218.417, "-Y")
E_E = ExteriorSegment("E_E", "E", 241.667, "39", "+Y")
W_CUT = ExteriorSegment("W_cut", "28.5", "J", "E", "none")


def wall(name, axis, ordinate, lo, hi, z0, z1):
    if axis == "y":
        corners = ((lo, ordinate, z0), (hi, ordinate, z0), (hi, ordinate, z1), (lo, ordinate, z1))
    else:
        corners = ((ordinate, lo, z0), (ordinate, hi, z0), (ordinate, hi, z1), (ordinate, lo, z1))
    return Shell(name, corners)


def snap(shells=(), frames=(), joints=()):
    return ModelSnapshot(shells=list(shells), frames=list(frames), joints=list(joints), stories=STORIES,
                         base_elevation_ft=BASE, grid_lines=G)


def config(cfg, segments=(J_W,), penthouses=(), parapets=(TYP, PF, PHP), overrides=None, equipment=(),
           platforms=()):
    return replace(cfg, levels=LV, exterior_segments=tuple(segments), grade_datum_model_elevation_ft=BASE,
                   parapets=tuple(parapets), penthouses=tuple(penthouses), overrides=overrides or {},
                   equipment=tuple(equipment), platforms=tuple(platforms))


def test_r0_geometry_collinear_floor_and_sloped():
    kinked = Shell("K", ((2895, -132, 0), (2760, -132, 0), (2761, -132, 0), (2761, -132, 10), (2895, -132, 10)))
    g = shell_geometry(kinked, S)
    assert g.vertical and g.axis_aligned and g.axis == "y" and g.ordinate == -132 and (g.lo, g.hi) == (2760, 2895)
    assert not shell_geometry(Shell("F", ((0, 0, 5), (1, 0, 5), (1, 1, 5), (0, 1, 5))), S).vertical
    d = shell_geometry(Shell("D", ((0, 0, 0), (1, 1, 0), (1, 1, 5), (0, 0, 5))), S)
    assert d.vertical and not d.axis_aligned


def test_r1_level_boundaries():  # Review Focus 3
    bands = story_bands(snap())
    assert bands[:2] == [("L2", BASE, 31.5), ("R", 31.5, 60.083)]
    assert level_of_top(31.5, bands, S) == "L2" and level_of_top(31.52, bands, S) == "L2"
    assert level_of_top(31.6, bands, S) == "R" and level_of_top(60.083, bands, S) == "R"
    assert level_of_top(77.2, bands, S) is None


def test_r2_element_type_from_levels():
    assert element_type("L2", LV, BANDS) == "wall" and element_type("R", LV, BANDS) == "wall"
    assert element_type("Mech", LV, BANDS) == "parapet" and element_type("Parapet_1", LV, BANDS) == "parapet"
    assert element_type("Penthouse", LV, BANDS) == "penthouse_body"
    assert element_type("Parapet_2", LV, BANDS) == "penthouse_parapet"
    assert element_type("Attic", LV, BANDS) is None


def test_r3_placement_outcomes(cfg):
    shells = [wall("J1", "y", 0.0, 100, 112, 31.5, 60.083), wall("CUT", "x", 2.25, 100, 112, BASE, 31.5),
              wall("INT", "x", 200.0, 100, 112, BASE, 31.5), wall("EXT", "y", 0.0, 20, 40, BASE, 31.5)]
    cats, diags = categorize_shells(config(cfg, segments=(J_W, W_CUT)), snap(shells))
    j1 = cats["A:J1"]
    assert (j1.category, j1.level, j1.segment_id, j1.outside, j1.side) == ("main_wall", "R", "J_W", "-Y", "J_W")
    assert j1.outward_normal == (0.0, -1.0, 0.0)
    assert cats["A:CUT"].category == "excluded" and cats["A:CUT"].segment_id == "W_cut"
    assert any(d.code == "declared_unexposed" and d.object_ref == "A:CUT" for d in diags)
    assert cats["A:INT"].category == "unresolved"
    assert any(d.code == "no_exterior_segment" and d.object_ref == "A:INT" and "x=200" in d.message for d in diags)
    assert cats["A:EXT"].category == "main_wall"
    assert any(d.code == "extent_exceeds_segment" and d.object_ref == "A:EXT" for d in diags)


def test_r3_shared_line_split_body_and_penthouse_parapet(cfg):
    shells = [wall("BODY_LO", "y", 238.0, 270, 290, 60.083, 70.708),
              wall("BODY_HI", "y", 238.0, 270, 290, 70.708, 75.167),
              wall("PAR", "y", 238.0, 250, 260, 60.083, 65.083), wall("PHP1", "y", 238.0, 270, 290, 75.167, 76.917),
              wall("BODY_W", "x", 266.083, 220, 230, 60.083, 70.708)]
    cats, diags = categorize_shells(config(cfg, segments=(E_E,), penthouses=(PH1,)), snap(shells))
    assert cats["A:BODY_LO"].category == "penthouse_body" and cats["A:BODY_LO"].component == "PH1"
    assert cats["A:BODY_HI"].category == "penthouse_body" and cats["A:BODY_HI"].side == "PH1_N"
    assert cats["A:PAR"].category == "main_roof_parapet" and cats["A:PAR"].parapet_type == "TYP"
    assert cats["A:PHP1"].category == "penthouse_parapet" and cats["A:PHP1"].outside == "+Y"
    assert cats["A:PHP1"].parapet_type == "PHP"
    assert cats["A:BODY_W"].category == "penthouse_body"
    assert any(d.code == "body_below_penthouse_level" and d.object_ref == "A:BODY_W" for d in diags)


def test_r5_parapet_type_from_stack(cfg):
    shells = [wall("STRIP1", "y", 0.0, 100, 112, 60.083, 65.083), wall("STRIP2", "y", 0.0, 100, 112, 65.083, 68.7),
              wall("STRIP3", "y", 0.0, 100, 112, 68.7, 70.708), wall("LONE", "y", 0.0, 150, 160, 60.083, 65.083),
              wall("SHORT", "y", 0.0, 180, 190, 60.083, 63.0)]
    cats, diags = categorize_shells(config(cfg), snap(shells))
    for name in ("STRIP1", "STRIP2", "STRIP3"):
        assert cats[f"A:{name}"].category == "picture_frame_parapet" and cats[f"A:{name}"].parapet_type == "PF"
    assert cats["A:STRIP1"].level == "Parapet_1" and cats["A:STRIP3"].level == "Mech"
    assert cats["A:LONE"].category == "main_roof_parapet" and cats["A:LONE"].parapet_type == "TYP"
    assert cats["A:SHORT"].category == "unresolved"
    assert any(d.code == "parapet_type_unmatched" and d.object_ref == "A:SHORT" for d in diags)


def test_override_wins(cfg):
    shells = [wall("CROSS", "y", 22.6, 410.083, 421.75, 60.083, 75.167)]
    ov = {"CROSS": Override("penthouse_body", "PH2", "+Y")}
    cats, _ = categorize_shells(config(cfg, segments=(J_W,), penthouses=(PH2,), overrides=ov), snap(shells))
    c = cats["A:CROSS"]
    assert (c.category, c.component, c.outside, c.overridden) == ("penthouse_body", "PH2", "+Y", True)
    assert c.outward_normal == (0.0, 1.0, 0.0)


def test_above_top_story_and_unmapped_level(cfg):
    shells = [wall("HIGH", "y", 0.0, 100, 112, 70.0, 90.0)]
    cats, diags = categorize_shells(config(cfg), snap(shells))
    assert cats["A:HIGH"].category == "unresolved" and any(d.code == "above_top_story" for d in diags)
    lv = replace(LV, parapet=("Parapet_1",))
    cats, diags = categorize_shells(replace(config(cfg), levels=lv),
                                    snap([wall("M", "y", 0.0, 100, 112, 65.083, 70.708)]))
    assert cats["A:M"].category == "unresolved" and any(d.code == "level_unmapped" for d in diags)


def test_r7_frames(cfg):
    frames = [Frame("B1", (0, 0, 70.0), (10, 0, 70.0)), Frame("B2", (0, 5, 70.0), (10, 5, 70.0)),
              Frame("B3", (0, 9, 70.0), (10, 9, 70.0)), Frame("P1", (20, 0, 70.0), (20, 10, 70.0)),
              Frame("P2", (30, 0, 60.0), (30, 10, 60.0)), Frame("U", (40, 0, 70.0), (40, 10, 70.0))]
    eq = Equipment("CH1", 77.0, 8.5, 56.0, 10.0, support_frames=("B1", "B2", "B3", "BX"))
    pl = Platform("PL1", 71.0, 3.5, 12.0, ("P1",), ("P2",))
    cats, diags = categorize_frames(config(cfg, equipment=(eq,), platforms=(pl,)), snap(frames=frames))
    assert cats["F:B1"].category == "equipment_support_frame" and cats["F:B1"].component == "CH1"
    assert cats["F:P1"].category == "mechanical_platform_frame" and cats["F:P1"].side == "X"
    assert cats["F:P2"].side == "Y" and cats["F:U"].category == "excluded"
    assert any(d.code == "missing_support_frame" and "BX" in d.message for d in diags)
    assert any(d.code == "frame_level_unexpected" and d.object_ref == "F:P2" for d in diags)
    assert not any(d.code == "frame_level_unexpected" and d.object_ref == "F:P1" for d in diags)


@pytest.mark.parametrize("name", ["cfg"])
def test_fixture_is_available(request, name):
    assert request.getfixturevalue(name) is not None
