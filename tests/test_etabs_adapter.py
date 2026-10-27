from types import SimpleNamespace

import pytest

from air_apparent.etabs.adapter import AdapterError, ComEtabsAdapter, _area_local3, _case_type, _static_case_terms


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
