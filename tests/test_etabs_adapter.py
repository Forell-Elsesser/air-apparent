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
