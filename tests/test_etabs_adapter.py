from types import SimpleNamespace

import pytest

from air_apparent.etabs.adapter import AdapterError, ComEtabsAdapter, _area_local3, _case_type, _static_case_terms
from air_apparent.models import Assignment


def test_area_local3_uses_matrix_column_for_global_normal():
    # Actual X-facing wall matrix: its third row points along Y, third column along -X.
    matrix = (0.0, 0.0, -1.0, -1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    assert _area_local3([matrix, 0], "1426") == (-1.0, 0.0, 0.0)


def test_area_local3_surfaces_api_errors():
    with pytest.raises(AdapterError, match="return code 1"):
        _area_local3([None, 1], "1426")


@pytest.mark.parametrize("status", [0, 1])
def test_define_case_accepts_inout_setloads_result_and_checks_final_status(status):
    from air_apparent.models import CaseSpec

    class StaticLinear:
        def SetCase(self, name):
            return 0

        def SetLoads(self, name, count, types, names, factors):
            assert name == "AA_W_Wall_+X" and count == 1
            return [tuple(types), tuple(names), tuple(factors), status]

    adapter = ComEtabsAdapter.__new__(ComEtabsAdapter)
    cases = type("Cases", (), {"StaticLinear": StaticLinear()})()
    adapter.m = type("Model", (), {"LoadCases": cases})()
    spec = CaseSpec("AA_W_Wall_+X", (("AA_W_Wall_+X", 1.0),))
    if status:
        with pytest.raises(AdapterError, match="return code 1"):
            adapter.define_case(spec)
    else:
        adapter.define_case(spec)


def test_static_case_terms_reads_names_and_scale_factors():
    response = [2, ("Load", "Load"), ("W_Wall_+X", "W_Mech_+X"), (1.0, -1.0), 0]

    assert _static_case_terms(response, "W_Wall_+X") == (
        ("W_Wall_+X", 1.0),
        ("W_Mech_+X", -1.0),
    )


@pytest.mark.parametrize("response", [[1, 0], [1, 0, 0], (1, 0, 0)])
def test_case_type_reads_static_linear_case_type(response):
    assert _case_type(response, "W_Wall_+X") == 1


@pytest.mark.parametrize("response", [[3, 1], [3, 2, 1]])
def test_case_type_surfaces_etabs_errors(response):
    with pytest.raises(AdapterError, match="return code 1"):
        _case_type(response, "Eigen")


def test_case_type_ignores_nonzero_modal_subtype():
    assert _case_type([3, 1, 0], "Eigen") == 3


@pytest.mark.parametrize("response", [None, 0, [], [3], [3, 1, 0, 0]])
def test_case_type_rejects_unexpected_results(response):
    with pytest.raises(AdapterError, match=r"GetTypeOAPI\(Eigen\).*unexpected result"):
        _case_type(response, "Eigen")


@pytest.mark.parametrize("include_subtype", [False, True])
def test_read_cases_skips_non_static_linear_cases(include_subtype):
    class StaticLinear:
        def GetLoads(self, name):
            assert name == "Wind"
            return [1, ("Load",), ("W_Wall_+X",), (1.0,), 0]

    class LoadCases:
        @staticmethod
        def GetNameList():
            return [2, ("Eigen", "Wind"), 0]

        @staticmethod
        def GetTypeOAPI(name):
            case_type = 3 if name == "Eigen" else 1
            if include_subtype:
                return [case_type, 1 if name == "Eigen" else 0, 0]
            return [case_type, 0]

    LoadCases.StaticLinear = StaticLinear()
    adapter = ComEtabsAdapter.__new__(ComEtabsAdapter)
    adapter.m = type("Model", (), {"LoadCases": LoadCases()})()

    assert adapter.read_cases() == {"Eigen": (), "Wind": (("W_Wall_+X", 1.0),)}


def test_static_case_terms_surfaces_etabs_errors():
    with pytest.raises(AdapterError, match="return code 1"):
        _static_case_terms([0, (), (), (), 1], "BadCase")


def test_static_case_terms_rejects_inconsistent_item_counts():
    with pytest.raises(AdapterError, match="inconsistent item counts"):
        _static_case_terms([1, ("Load",), ("W_Wall_+X",), (), 0], "BadCase")


@pytest.mark.parametrize("return_code", [0, 1])
def test_read_combinations_uses_names_and_factors_and_checks_return_code(return_code):
    class Combos:
        def GetNameList(self):
            return [1, ("W1_+X",), 0]

        def GetCaseList(self, name):
            return [2, (0, 0), ("W_Wall_+X", "W_Parapet_+X"), (1.0, 0.75), return_code]

        def GetTypeCombo(self, name):
            return [0, 0]

    adapter = ComEtabsAdapter.__new__(ComEtabsAdapter)
    adapter.m = type("Model", (), {"RespCombo": Combos()})()
    if return_code:
        with pytest.raises(AdapterError, match="return code 1"):
            adapter.read_combinations()
    else:
        assert adapter.read_combinations() == {
            "W1_+X": ("linear", (("W_Wall_+X", 1.0), ("W_Parapet_+X", 0.75)))
        }


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


def test_geometry_and_load_operations_restore_present_units():
    units = {"current": 3}

    def names():
        assert units["current"] == 4
        return [0, (), 0]

    def set_load(*args):
        assert units["current"] == 4
        return 0

    model = SimpleNamespace(
        GetPresentUnits=lambda: units["current"],
        SetPresentUnits=lambda value: (units.update(current=value) or 0),
        AreaObj=SimpleNamespace(GetNameList=names, SetLoadUniform=set_load, DeleteLoadUniform=set_load),
    )
    adapter = _adapter_with_api(model)
    adapter._read_model_in_kip_ft = lambda: (units["current"] == 4)

    assert adapter.read_model()
    assignment = Assignment("W_X|A:W1", "shell_pressure", "A:W1", "W_X", 0.02,
                            "kip/ft2", "Local3", "WALL")
    adapter.assign(assignment)
    adapter.clear_assignment("shell_pressure", "A:W1", "W_X")

    assert units["current"] == 3


def test_read_assignments_uses_live_oapi_indices_and_filters_patterns():
    units = {"current": 3}

    def names(*values):
        assert units["current"] == 4
        return [len(values), values, 0]

    def area_load(name):
        assert units["current"] == 4
        return [1, (name,), ("W",), ("Local",), (3,), (0.02,), 0]

    def point_load(name):
        assert units["current"] == 4
        return [1, (name,), ("W",), (0,), ("Global",), (2.0,), (-3.0,),
                (0.0,), (0.0,), (0.0,), (4.0,), 0]

    def frame_load(name):
        assert units["current"] == 4
        return [1, (name,), ("W",), (1,), ("Global",), (4,), (0.0,), (1.0,),
                (0.0,), (1.0,), (5.0,), (5.0,), 0]

    model = SimpleNamespace(
        GetPresentUnits=lambda: units["current"],
        SetPresentUnits=lambda value: (units.update(current=value) or 0),
        AreaObj=SimpleNamespace(GetNameList=lambda: names("A1"), GetLoadUniform=area_load),
        PointObj=SimpleNamespace(GetNameList=lambda: names("P1"), GetLoadForce=point_load),
        FrameObj=SimpleNamespace(GetNameList=lambda: names("F1"), GetLoadDistributed=frame_load),
    )
    assignments = _adapter_with_api(model).read_assignments({"W"})

    assert {(a.kind, a.object_ref, a.value, a.global_dir) for a in assignments} == {
        ("shell_pressure", "A:A1", 0.02, "Local3"),
        ("joint_force", "P:P1", 2.0, "X"),
        ("joint_force", "P:P1", -3.0, "Y"),
        ("joint_moment", "P:P1", 4.0, "Mz"),
        ("frame_line_load", "F:F1", 5.0, "X"),
    }
    assert units["current"] == 3


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


def test_set_group_reuses_model_spelling_and_reads_back():  # Review Focus 4
    calls = []
    gd = SimpleNamespace(GetNameList=lambda: [1, ("w_wall_+x",), 0],
                         GetGroup_1=lambda n: [7] + [True] * 13 + [0],
                         Delete=lambda n: calls.append(("Delete", n)) or 0,
                         SetGroup_1=lambda n, *a: calls.append(("SetGroup_1", n, a[0])) or 0,
                         GetAssignments=lambda n: [1, (5,), ("A1",), 0])
    ao = SimpleNamespace(SetGroupAssign=lambda o, g: calls.append(("assign", o, g)) or (0 if o == "A1" else 3))
    res = _adapter_with_api(SimpleNamespace(GroupDef=gd, AreaObj=ao)).set_group("W_Wall_+X", ["A:A1", "A:A2"])
    assert ("Delete", "w_wall_+x") in calls and ("SetGroup_1", "w_wall_+x", 7) in calls
    assert ("assign", "A1", "w_wall_+x") in calls
    assert res.refused == (("A:A2", 3),) and res.missing_after_readback == ()


def test_set_group_reports_members_missing_after_readback():
    gd = SimpleNamespace(GetNameList=lambda: [0, (), 0], GetGroup_1=lambda n: [0] + [True] * 13 + [0],
                         Delete=lambda n: 0, SetGroup_1=lambda n, *a: 0,
                         GetAssignments=lambda n: [0, (), (), 0])
    fo = SimpleNamespace(SetGroupAssign=lambda o, g: 0)
    res = _adapter_with_api(SimpleNamespace(GroupDef=gd, FrameObj=fo)).set_group("W_Mech_+X", ["F:B1"])
    assert res.refused == () and res.missing_after_readback == ("F:B1",)
