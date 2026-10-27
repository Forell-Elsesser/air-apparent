import pytest


def test_fixture_matches_model_facts(test_model_snap):
    s = test_model_snap
    assert [st.name for st in s.stories] == ["L2", "R", "Parapet_1", "Mech", "Penthouse", "Parapet_2"]
    assert s.base_elevation_ft == pytest.approx(-0.833, abs=0.01)
    assert sorted(g.label for g in s.grid_lines if g.axis == "y") == ["E", "F", "G", "H", "J"]
    assert len([g for g in s.grid_lines if g.axis == "x"]) == 13
    assert {k: len(v) for k, v in s.groups.items()} == {
        "W_Wall_+X": 568, "W_Wall_-X": 568, "W_Wall_+Y": 565, "W_Wall_-Y": 568,
        "W_Parapet_+X": 695, "W_Parapet_-X": 695, "W_Parapet_+Y": 695, "W_Parapet_-Y": 695,
        "W_PH_+X": 18, "W_PH_-X": 22, "W_PH_+Y": 22, "W_PH_-Y": 22,
        "W_Mech_+X": 135, "W_Mech_-X": 135, "W_Mech_+Y": 93, "W_Mech_-Y": 93}
