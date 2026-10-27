from air_apparent.categorization.groups import build_pattern_groups, compare_groups, face_role
from air_apparent.models import DIRECTIONS, PATTERN_GROUP_NAMES, GroupComparison, ObjectCategory


def test_face_role():
    assert face_role("-X", "+X") == "WINDWARD" and face_role("+X", "+X") == "LEEWARD"
    assert face_role("-Y", "+X") == "SIDE" and face_role("+Y", "-Y") == "WINDWARD"


def test_pattern_group_names_are_the_sixteen():
    assert len(PATTERN_GROUP_NAMES) == 16 and PATTERN_GROUP_NAMES[0] == "W_Wall_+X"
    assert all(n.split("_")[1] in ("Wall", "Parapet", "PH", "Mech") for n in PATTERN_GROUP_NAMES)


def test_pattern_groups_from_objects():
    objs = {"A:W": ObjectCategory("A:W", "main_wall", "", level="L2", outside="-Y"),
            "A:P": ObjectCategory("A:P", "picture_frame_parapet", "", level="Mech", outside="-Y"),
            "A:Q": ObjectCategory("A:Q", "penthouse_parapet", "", level="Parapet_2", outside="+X", component="PH2"),
            "A:B": ObjectCategory("A:B", "penthouse_body", "", level="Penthouse", outside="+X", component="PH2"),
            "A:U": ObjectCategory("A:U", "unresolved", ""),
            "F:E": ObjectCategory("F:E", "equipment_support_frame", "", component="CH1", side="XY"),
            "F:P": ObjectCategory("F:P", "mechanical_platform_frame", "", component="PL1", side="X"),
            "F:Z": ObjectCategory("F:Z", "excluded", "")}
    g = build_pattern_groups(objs)
    assert set(g) == set(PATTERN_GROUP_NAMES)
    assert all(g[f"W_Wall_{d}"] == ["A:W"] for d in DIRECTIONS)
    assert all(g[f"W_Parapet_{d}"] == ["A:P", "A:Q"] for d in DIRECTIONS)
    assert g["W_PH_+X"] == [] and g["W_PH_-X"] == ["A:B"] and g["W_PH_+Y"] == ["A:B"] and g["W_PH_-Y"] == ["A:B"]
    assert g["W_Mech_+Y"] == ["F:E"] and g["W_Mech_-Y"] == ["F:E"]
    assert g["W_Mech_-X"] == ["F:E", "F:P"] and g["W_Mech_+X"] == ["F:E", "F:P"]


def test_compare_groups_case_insensitive():
    cmp = compare_groups({"W_Wall_+X": ["A:1", "A:2"], "W_Wall_-X": []}, {"w_wall_+x": ["A:2", "A:3"]})
    assert cmp[0] == GroupComparison("W_Wall_+X", 2, 2, ("A:3",), ("A:1",))
    assert cmp[1] == GroupComparison("W_Wall_-X", 0, 0, (), ())
