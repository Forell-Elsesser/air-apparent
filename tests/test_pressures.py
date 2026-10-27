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
