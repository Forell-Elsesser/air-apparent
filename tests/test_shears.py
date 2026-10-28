"""Analysis-table contracts, equilibrium and workflow isolation."""

import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from air_apparent.etabs.adapter import AdapterError, ComEtabsAdapter
from air_apparent.etabs.shears import ShearResults, StoryShear
from air_apparent.reporting import export_all
from tests.test_ui import GroupTree, make_app


def result(session, direction="+X"):
    cases = (f"W_Wall_{direction}",)
    session.adapter.analysis_shears[cases] = ShearResults(
        cases, -220.0, -300.0, (StoryShear("L2", 220.0, 300.0), StoryShear("ROOF", 100.0, 125.0)),
        session.adapter.info().path)
    return cases


def refs():
    return {"ROOF": "CEN_ROOF", "L2": "CEN_L2"}


def test_extract_preserves_plan_preview_yaml_and_model(session):
    session.create_preview_groups()
    plan, pressures, cfg = session.plan, session.pressures, session.cfg
    cases = result(session)
    before = copy.deepcopy(vars(session.adapter))
    review = session.extract_shear_review(cases, "+X")
    assert session.plan is plan and session.pressures is pressures and session.cfg is cfg
    assert session.preview_valid and vars(session.adapter) == before
    assert [r.story for r in review.rows] == ["ROOF", "L2"]
    assert [r.applied_moment_kip_ft for r in review.rows] == [3600, 4320]
    assert review.base_target_kip_ft == sum(r.applied_moment_kip_ft for r in review.rows)


def test_adopt_updates_only_eccentric_direction_then_preview_apply_verify(session):
    original, cfg = session.plan, session.cfg
    review = session.extract_shear_review(result(session), "+X", 4 / 3)
    session.create_preview_groups()
    session.use_shear_review(review, refs())
    assert session.cfg is cfg and session.pressures is not None
    assert session.plan is None and not session.preview_valid
    plan = session.build_plan()
    assert [a for a in plan.assignments if a.pattern != "W_Ecc_+X"] == [
        a for a in original.assignments if a.pattern != "W_Ecc_+X"]
    moments = [a for a in plan.assignments if a.pattern == "W_Ecc_+X"]
    assert sum(a.value for a in moments) == pytest.approx(7920 * 4 / 3)
    assert all("ETABS Bottom" in a.note for a in moments)
    assert not session.apply().ok
    session.create_preview_groups()
    assert session.apply().ok
    assert all(r.ok for r in session.verify())


@pytest.mark.parametrize("change,message", [
    (lambda s: replace(s, base_fx_kip=-500), "base/story shear mismatch"),
    (lambda s: replace(s, stories=s.stories[:1]), "coverage"),
    (lambda s: replace(s, stories=(s.stories[0], StoryShear("ROOF", -100, 125))), "reverses sign"),
    (lambda s: replace(s, stories=(s.stories[0], StoryShear("ROOF", 250, 125))), "must not decrease"),
    (lambda s: replace(s, stories=(s.stories[0], StoryShear("ROOF", float("nan"), 125))), "non-finite"),
    (lambda s: replace(s, location="Top"), "Bottom"),
    (lambda s: replace(s, model_path="other.edb"), "different ETABS model"),
])
def test_bad_results_preserve_current_plan(session, change, message):
    cases = result(session)
    session.adapter.analysis_shears[cases] = change(session.adapter.analysis_shears[cases])
    plan = session.plan
    with pytest.raises(ValueError, match=message):
        session.extract_shear_review(cases, "+X")
    assert session.plan is plan and not session.adopted_shears


@pytest.mark.parametrize("scale", [0, -1, float("inf"), float("nan")])
def test_invalid_multiplier_rejected(session, scale):
    with pytest.raises(ValueError, match="multiplier"):
        session.extract_shear_review(result(session), "+X", scale)


def test_y_direction_width_and_negative_shears(session):
    cases = result(session, "-Y")
    source = session.adapter.analysis_shears[cases]
    session.adapter.analysis_shears[cases] = replace(source, stories=tuple(
        replace(r, vy_kip=-r.vy_kip) for r in source.stories))
    review = session.extract_shear_review(cases, "-Y")
    assert review.base_target_kip_ft == pytest.approx(300 * .15 * 1472)
    assert all(r.applied_moment_kip_ft >= 0 for r in review.rows)


@pytest.mark.parametrize("mapping", [{}, {"ROOF": "missing", "L2": "CEN_L2"},
                                     {"ROOF": "CEN_L2", "L2": "CEN_ROOF"}])
def test_invalid_references_fail_atomically(session, mapping):
    review = session.extract_shear_review(result(session), "+X")
    plan = session.plan
    with pytest.raises(ValueError):
        session.use_shear_review(review, mapping)
    assert session.plan is plan and not session.adopted_shears


def test_diaphragm_failure_keeps_plan(session):
    review = session.extract_shear_review(result(session), "+X")
    plan = session.plan
    session.adapter.validate_eccentric_reference = Mock(side_effect=AdapterError("semi-rigid"))
    with pytest.raises(AdapterError, match="semi-rigid"):
        session.use_shear_review(review, refs())
    assert session.plan is plan and not session.adopted_shears


def test_model_refresh_discards_imports_and_stale_review(session):
    review = session.extract_shear_review(result(session), "+X")
    session.use_shear_review(review, refs())
    session.read_model()
    assert not session.adopted_shears
    session.calculate()
    with pytest.raises(ValueError, match="stale"):
        session.use_shear_review(review, refs())


def test_wall_scope_is_not_implicitly_expanded(session):
    session.set_loading_scope("walls_parapets")
    session.calculate()
    review = session.extract_shear_review(result(session), "+X")
    with pytest.raises(ValueError, match="excluded"):
        session.use_shear_review(review, refs())
    assert session.cfg.loading.scope == "walls_parapets" and not session.adopted_shears


def test_switching_model_after_adoption_blocks_apply_before_writes(session):
    review = session.extract_shear_review(result(session), "+X")
    session.use_shear_review(review, refs())
    session.build_plan()
    session.create_preview_groups()
    session.adapter.info = lambda: SimpleNamespace(path="other.edb")
    before = list(session.adapter.calls)
    assert "model changed" in session.apply().message
    assert session.adapter.calls == before and not session.adapter.assignments


def test_scalar_table_selection_status_is_supported():
    adapter, tables, units = table_adapter()
    for name in ("SetLoadCasesSelectedForDisplay", "SetLoadCombinationsSelectedForDisplay"):
        original = getattr(tables, name)
        setattr(tables, name, lambda names, fn=original: fn(names)[-1])
    assert adapter.read_shears(("A", "B")).base_fx_kip == -180
    assert tables.cases == ["DEAD"] and tables.combos == ["USER_ENV"] and units["current"] == 3


def test_reset_restores_yaml_and_export_preserves_provenance(session, tmp_path):
    original = session.plan
    review = session.extract_shear_review(result(session), "+X")
    session.use_shear_review(review, refs())
    session.build_plan()
    export_all(session, tmp_path)
    data = json.loads((tmp_path / "assignment_plan.json").read_text())
    assert data["eccentricity_analysis_sources"]["+X"]["review"]["source"]["cases"] == ["W_Wall_+X"]
    assert "ETABS analysis shear sources" in (tmp_path / "report.html").read_text()
    session.use_yaml_shears()
    assert not session.adopted_shears and not session.preview_valid
    assert session.build_plan().assignments == original.assignments


class Tables:
    def __init__(self):
        self.cases, self.combos = ["DEAD"], ["USER_ENV"]
        self.fail = ""
        self.fields = ["Story", "OutputCase", "Location", "VX", "VY", "StepType"]
        self.story = [["ROOF", "A", "Top", "999", "999", ""],
                      ["ROOF", "A", "Bottom", "100", "0", ""],
                      ["L2", "A", "Bottom", "220", "0", ""],
                      ["ROOF", "B", "Bottom", "-20", "0", ""],
                      ["L2", "B", "Bottom", "-40", "0", ""]]
        self.base = [["A", "-220", "0", ""], ["B", "40", "0", ""]]

    def GetLoadCasesSelectedForDisplay(self):
        return [len(self.cases), tuple(self.cases), 0]

    def GetLoadCombinationsSelectedForDisplay(self):
        return [len(self.combos), tuple(self.combos), 0]

    def SetLoadCasesSelectedForDisplay(self, names):
        self.cases = list(names)
        return [tuple(names), 0]

    def SetLoadCombinationsSelectedForDisplay(self, names):
        self.combos = list(names)
        return [tuple(names), 0]

    def GetTableForDisplayArray(self, key, fields, group, version, included, count, data):
        assert self.cases == ["A", "B"] and self.combos == [] and group == "All"
        if key == self.fail:
            raise AdapterError("injected table read failure")
        fields, rows = ((self.fields, self.story) if key == "Story Forces" else
                        (["OutputCase", "FX", "FY", "StepType"], self.base))
        return [[], 1, fields, len(rows), [v for row in rows for v in row], 0]


def table_adapter():
    tables, units = Tables(), {"current": 3}
    adapter = object.__new__(ComEtabsAdapter)
    adapter.m = SimpleNamespace(
        DatabaseTables=tables, GetModelIsLocked=lambda: True, GetModelFilename=lambda: "live.edb",
        GetPresentUnits=lambda: units["current"],
        SetPresentUnits=lambda value: (units.update(current=value) or 0),
        Analyze=SimpleNamespace(GetCaseStatus=lambda: [2, ("A", "B"), (4, 4), 0]),
        LoadCases=SimpleNamespace(GetTypeOAPI=lambda case: [1, 0, 0]))
    adapter.read_cases = lambda: {"A": (("WindA", 1.0),), "B": (("WindB", 1.0),)}
    return adapter, tables, units


def test_api_contract_sums_signed_cases_before_abs_and_restores_display():
    adapter, tables, units = table_adapter()
    source = adapter.read_shears(("A", "B"))
    assert source.base_fx_kip == -180
    assert source.stories == (StoryShear("ROOF", 80, 0), StoryShear("L2", 180, 0))
    assert tables.cases == ["DEAD"] and tables.combos == ["USER_ENV"] and units["current"] == 3


@pytest.mark.parametrize("failure", ["Story Forces", "Base Reactions"])
def test_api_failure_restores_selection_and_units(failure):
    adapter, tables, units = table_adapter()
    tables.fail = failure
    with pytest.raises(AdapterError, match="injected"):
        adapter.read_shears(("A", "B"))
    assert tables.cases == ["DEAD"] and tables.combos == ["USER_ENV"] and units["current"] == 3


@pytest.mark.parametrize("change,message", [
    (lambda t: t.story.append(t.story[1]), "duplicate"),
    (lambda t: t.story.pop(), "incomplete"),
    (lambda t: t.story[1].__setitem__(5, "Max"), "multi-step"),
    (lambda t: t.story[1].__setitem__(3, "nan"), "non-finite"),
    (lambda t: t.base.clear(), "no analysis results"),
    (lambda t: t.fields.__setitem__(3, "not_VX"), "missing required fields"),
])
def test_malformed_api_results_rejected(change, message):
    adapter, tables, units = table_adapter()
    change(tables)
    with pytest.raises(AdapterError, match=message):
        adapter.read_shears(("A", "B"))
    assert tables.cases == ["DEAD"] and tables.combos == ["USER_ENV"] and units["current"] == 3


@pytest.mark.parametrize("cases", [(), ("A", "A"), ("USER_ENV",)])
def test_invalid_source_selection_rejected(cases):
    adapter, tables, units = table_adapter()
    with pytest.raises(AdapterError):
        adapter.read_shears(cases)
    assert tables.cases == ["DEAD"] and units["current"] == 3


@pytest.mark.parametrize("kind,status,locked", [(2, 4, True), (1, 3, True), (1, 4, False)])
def test_analysis_must_be_completed_static_linear(kind, status, locked):
    adapter, tables, units = table_adapter()
    adapter.m.LoadCases.GetTypeOAPI = lambda case: [kind, 0, 0]
    adapter.m.Analyze.GetCaseStatus = lambda: [2, ("A", "B"), (status, status), 0]
    adapter.m.GetModelIsLocked = lambda: locked
    with pytest.raises(AdapterError):
        adapter.read_shears(("A", "B"))
    assert tables.cases == ["DEAD"] and units["current"] == 3


def test_ui_extract_use_calculate_reset(session):
    app = make_app(session)
    app.shear_tree = GroupTree()
    app._shear_view_revision = session.input_revision
    for name, value in (("shear_cases", result(session)[0]), ("shear_direction", "+X"), ("shear_scale", "1"),
                        ("shear_references", ""), ("shear_summary", "")):
        state = {"value": value}
        variable = Mock()
        variable.get.side_effect = lambda data=state: data["value"]
        variable.set.side_effect = lambda text, data=state: data.update(value=text)
        setattr(app, name, variable)
    plan = session.plan
    app.extract_shears()
    assert session.plan is plan and len(app.shear_tree.rows) == 2
    app.use_reviewed_shears()
    assert session.plan is None and "+X" in session.adopted_shears
    app.calculate()
    assert session.plan is not None and app.tree.rows
    app.reset_shears()
    assert not session.adopted_shears and session.plan is None
