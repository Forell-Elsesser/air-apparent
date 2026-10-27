from air_apparent.models import GridLine, GridSystem, ModelSnapshot, Shell, Story
from air_apparent.snapshot_io import snapshot_from_json, snapshot_to_json


def test_round_trip_preserves_everything():
    snap = ModelSnapshot(
        shells=[Shell("W1", ((0, 0, 0), (10, 0, 0), (10, 0, 12), (0, 0, 12)), (0, -1, 0), ("W_Wall_+X",))],
        stories=[Story("L2", 31.5, 32.333, True, "", "D1", "J7")],
        base_elevation_ft=-0.833,
        grid_systems=[GridSystem("G1", "Cartesian", 0.0, 0.0, 0.0)],
        grid_lines=[GridLine("G1", "x", "28.5", 2.25), GridLine("G1", "y", "J", 0.0)],
        labels={"A:W1": ("W1", "L2")},
        groups={"W_Wall_+X": ["A:W1"]},
    )
    back = snapshot_from_json(snapshot_to_json(snap))
    assert back == snap
    assert isinstance(back.shells[0].corners[0], tuple) and isinstance(back.labels["A:W1"], tuple)
