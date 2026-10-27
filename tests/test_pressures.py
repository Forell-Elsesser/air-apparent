import json
import math
from pathlib import Path

import pytest

from air_apparent.pressures import (
    UnsupportedEditionError,
    calculate_pressures,
    eccentric_torsion,
)
from air_apparent.pressures.asce7_10 import kz, leeward_cp, signed_gcpi

FIX = json.loads((Path(__file__).parent / "fixtures" / "workbook_benchmarks.json").read_text())


def test_workbook_reproduction(cfg):
    ps = calculate_pressures(cfg)
    for e in FIX["entries"]:
        assert math.isclose(ps.value(e["result_id"]), e["value"], rel_tol=1e-8), e["cell"]
        assert ps.results[e["result_id"]].units == e["units"]


def test_unsupported_edition_never_falls_back(cfg):
    from dataclasses import replace
    with pytest.raises(UnsupportedEditionError):
        calculate_pressures(replace(cfg, code_edition="ASCE 7-16"))


def test_branch_signed_gcpi():
    assert signed_gcpi("Max", 0.18) == -0.18
    assert signed_gcpi("Min", 0.18) == 0.18
    assert signed_gcpi("Ext. Only", 0.18) == 0.0


def test_branch_equation_and_traceability(cfg):
    ps = calculate_pressures(cfg)
    ext = ps.value("WALL_LW_X_EXT")
    qh = ps.value("QH")
    assert math.isclose(ps.value("WALL_LW_X_MAX"), ext + 0.18 * qh)
    assert math.isclose(ps.value("WALL_LW_X_MIN"), ext - 0.18 * qh)
    r = ps.results["WALL_LW_X_MAX"]
    assert r.inputs["GCpi_signed"] == -0.18 and r.reference and r.units == "psf"
    # leeward net can be positive (pressure) under Max
    assert ps.value("WALL_LW_X_MAX") > 0


def test_independent_checks():
    # Independent of the workbook: Kz at z = 15 ft Exposure C per Eq. 27.3-1 constants
    assert math.isclose(kz(15.0, "C"), 2.01 * (15 / 900) ** (2 / 9.5))
    assert kz(10.0, "C") == kz(15.0, "C")  # z < 15 ft uses 15 ft
    assert leeward_cp(0.5) == -0.5 and leeward_cp(1.0) == -0.5
    assert math.isclose(leeward_cp(1.5), -0.4) and leeward_cp(2.0) == -0.3
    assert math.isclose(leeward_cp(3.0), -0.25) and leeward_cp(9.0) == -0.2


def test_rooftop_force_conservation_and_minimum_check(cfg):
    ps = calculate_pressures(cfg)
    assert math.isclose(ps.value("EQ_CHILLER01_FX") * 1000, ps.value("EQ_CHILLER01_P") * 8.5 * 10)
    assert all(c.inputs["passes"] for c in ps.checks)


def test_eccentric_torsion_is_incremental():
    rows = eccentric_torsion([("ROOF", 100.0), ("L2", 220.0)], 0.15, 240.0)
    assert [r.target_torsion_kip_ft for r in rows] == [3600.0, 7920.0]
    assert [r.applied_moment_kip_ft for r in rows] == [3600.0, 4320.0]
    assert sum(r.applied_moment_kip_ft for r in rows) == rows[-1].target_torsion_kip_ft
    assert rows[0].eccentricity_ft == 36.0
    with pytest.raises(ValueError):
        eccentric_torsion([("ROOF", 100.0), ("L2", 50.0)], 0.15, 240.0)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_derived_plan_dimension_is_rejected(cfg, value):
    from air_apparent.models import PlanDims

    dims = {"X": PlanDims(100.0, value), "Y": PlanDims(value, 100.0)}

    with pytest.raises(ValueError, match="must be finite and greater than zero"):
        calculate_pressures(cfg, dims)
def test_directional_output_ids_preserve_story_and_axis_pressures(cfg):
    from air_apparent.pressures import calculate_pressures
    from air_apparent.reporting import pressure_output_results

    ps = calculate_pressures(cfg)
    groups = pressure_output_results(ps)
    expected = [f"W_{family}_{d}" for family in ("Parapet", "PH") for d in ("-X", "-Y", "+X", "+Y")]
    expected += [f"W_Wall_Story{n}_{d}" for d in ("-X", "-Y", "+X", "+Y") for n in (1, 2)]
    assert [g.id for g in groups] == expected
    by_id = {g.id: g for g in groups}
    x = by_id["W_Wall_Story1_-X"]
    y = by_id["W_Wall_Story1_-Y"]
    assert x.story_band == "L2"
    assert by_id["W_Wall_Story2_+X"].story_band == "ROOF"
    assert x.components[0].value == ps.value("WALL_WW_L2_MAX")
    assert x.components[2].value == ps.value("WALL_LW_X_MAX")
    assert y.components[2].value == ps.value("WALL_LW_Y_MAX")
    assert x.components[2].value != y.components[2].value
    assert len(ps.results) == 85
