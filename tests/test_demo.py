import pytest

from air_apparent.etabs import FakeAdapter


def test_demo_snapshot_has_stories_grids_and_labels(cfg, snap):
    assert [s.name for s in snap.stories] == ["L2", "ROOF", "PARAPET_TYP", "PARAPET_PF", "PH_ROOF", "PH_PARAPET"]
    assert snap.stories[1].elevation_ft == 62.0 and snap.stories[1].height_ft == pytest.approx(30.5)
    assert snap.base_elevation_ft == cfg.grade_datum_model_elevation_ft
    assert {(g.axis, g.label): g.ordinate_ft for g in snap.grid_lines} == {
        ("x", "1"): 0.0, ("x", "2"): 1472.0, ("y", "A"): 0.0, ("y", "B"): 240.0}
    assert snap.grid_systems[0].name == "G1" and snap.grid_systems[0].rotation_deg == 0.0
    assert snap.labels["A:W_S_L2_1"] == ("W_S_L2_1", "L2")


def test_fake_adapter_group_api(snap):
    fa = FakeAdapter(snap)
    fa.groups["W_Wall_+X"] = ["A:W_S_L2_1"]
    assert fa.read_groups() == {"W_Wall_+X": ["A:W_S_L2_1"]}
    res = fa.set_group("W_Wall_+X", ["A:W_S_L2_2"])
    assert res.refused == () and res.missing_after_readback == () and fa.groups["W_Wall_+X"] == ["A:W_S_L2_2"]
    fa.select_objects(["A:W_S_L2_2"])
    assert fa.selected_objects == ["A:W_S_L2_2"]
