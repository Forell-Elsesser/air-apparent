from types import SimpleNamespace

from air_apparent.etabs.adapter import ComEtabsAdapter


def _adapter_with_api(api):
    adapter = object.__new__(ComEtabsAdapter)
    adapter.m = api
    return adapter


def test_read_cases_uses_case_names_and_factors_from_etabs_results():
    cases = SimpleNamespace(
        GetNameList=lambda: [2, ("Empty", "Wind"), 0],
        GetTypeOAPI=lambda name: [1, 0, 0],
        StaticLinear=SimpleNamespace(GetLoads=lambda name: {
            "Empty": [0, (), (), (), 0],
            "Wind": [1, ("Load",), ("W_Wall_+X",), (1.0,), 0],
        }[name]),
    )
    adapter = _adapter_with_api(SimpleNamespace(LoadCases=cases))

    assert adapter.read_cases() == {"Empty": (), "Wind": (("W_Wall_+X", 1.0),)}


def test_read_cases_does_not_query_static_loads_for_other_case_types():
    cases = SimpleNamespace(
        GetNameList=lambda: [1, ("Eigen",), 0],
        GetTypeOAPI=lambda name: [3, 1, 0],
        StaticLinear=SimpleNamespace(GetLoads=lambda name: (_ for _ in ()).throw(AssertionError(name))),
    )
    adapter = _adapter_with_api(SimpleNamespace(LoadCases=cases))

    assert adapter.read_cases() == {"Eigen": ()}


def test_read_combinations_uses_case_names_and_factors_from_etabs_results():
    combinations = SimpleNamespace(
        GetNameList=lambda: [1, ("W_ENV",), 0],
        GetCaseList=lambda name: [2, (0, 0), ("W1", "W2"), (1.0, 1.0), 0],
        GetTypeCombo=lambda name: [1, 0],
    )
    adapter = _adapter_with_api(SimpleNamespace(RespCombo=combinations))

    assert adapter.read_combinations() == {
        "W_ENV": ("envelope", (("W1", 1.0), ("W2", 1.0))),
    }


def test_read_assignments_uses_documented_tuple_positions():
    api = SimpleNamespace(
        AreaObj=SimpleNamespace(GetLoadUniform=lambda n, t: [1, ("A1",), ("W_Wall_+X",), ("Global",), (4,), (0.5,), 0]),
        PointObj=SimpleNamespace(GetLoadForce=lambda n, t: [1, ("P1",), ("W_Mech_+X",), (0,), ("Global",),
                                                            (1.5,), (0.0,), (0.0,), (0.0,), (0.0,), (7.0,), 0]),
        FrameObj=SimpleNamespace(GetLoadDistributed=lambda n, t: [1, ("B1",), ("W_Mech_+Y",), (1,), ("Global",),
                                                                  (5,), (0,), (1,), (0,), (10,), (0.25,), (0.25,), 0]),
    )
    out = {(a.kind, a.object_ref, a.global_dir): a.value for a in _adapter_with_api(api).read_assignments()}
    assert out[("joint_force", "P:P1", "X")] == 1.5
    assert out[("joint_moment", "P:P1", "Mz")] == 7.0
    assert out[("frame_line_load", "F:B1", "Y")] == 0.25


def test_read_stories_is_bottom_up_with_heights():
    story = SimpleNamespace(GetStories_2=lambda: [-0.833, 2, ("R", "L2"), (60.083, 31.5), (28.583, 32.333),
                                                  (True, True), ("", ""), (False, False), (0, 0), (0, 0), 0])
    base, stories = ComEtabsAdapter._read_stories(SimpleNamespace(Story=story))
    assert base == -0.833 and [s.name for s in stories] == ["L2", "R"]
    assert stories[1].height_ft == 28.583


def test_read_groups_filters_prefix_case_insensitively():
    gd = SimpleNamespace(GetNameList=lambda: [3, ("CLADDING", "w_wall_+x", "W_PH_+Y"), 0],
                         GetAssignments=lambda g: [1, (5,), ("A7",), 0])
    groups = _adapter_with_api(SimpleNamespace(GroupDef=gd)).read_groups("W_")
    assert groups == {"w_wall_+x": ["A:A7"], "W_PH_+Y": ["A:A7"]}
