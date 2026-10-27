import json

from air_apparent.reporting import export_all
from air_apparent.workflow import WindSession
from tests.conftest import REFERENCE


def test_apply_requires_preview(session):
    res = session.apply()
    assert not res.ok and "preview" in res.message


def test_full_flow_and_readback(session):
    assert session.create_preview_groups() == []
    assert "AA_PREVIEW_UNRESOLVED" not in session.adapter.groups
    assert "OLD_WALLS" in session.adapter.groups  # unrelated groups preserved
    assert not session.adapter.assignments  # preview created no loads
    res = session.apply()
    assert res.ok, res
    assert res.applied["patterns"] == 18 and res.applied["cases"] == 20
    rows = session.verify()
    assert rows and all(r.ok for r in rows)


def test_reapply_is_idempotent(session):
    session.create_preview_groups()
    session.apply()
    before = {k: v.value for k, v in session.adapter.assignments.items()}
    session.apply()
    assert {k: v.value for k, v in session.adapter.assignments.items()} == before


def test_stale_assignments_cleared_when_plan_shrinks(session):
    session.create_preview_groups()
    session.apply()
    n = len(session.adapter.assignments)
    session.snapshot.frames[:] = [f for f in session.snapshot.frames if f.name != "PL1_A"]
    session.adapter.snapshot.frames = list(session.snapshot.frames)
    session.read_model()
    session.build_plan()
    session.create_preview_groups()
    res = session.apply()
    assert res.ok and res.applied["cleared"] == 1
    assert len(session.adapter.assignments) == n - 1


def test_manual_group_edit_blocks_apply(session):
    session.create_preview_groups()
    g = "AA_PREVIEW_WALL_L2_XPOS_WINDWARD_MIN"
    name = next(n for n in session.adapter.groups if n.startswith(g))
    session.adapter.groups[name].append("A:INT_1")
    res = session.apply()
    assert not res.ok and any(d.code == "group_member_extra" for d in res.diagnostics)
    assert not session.adapter.assignments


def test_group_rebuild_removes_outdated_members_and_stale_groups(session):
    session.create_preview_groups()
    stale = "AA_PREVIEW_OLD_TOOL_GROUP"
    session.adapter.groups[stale] = ["A:INT_1"]
    manifest = session.adapter.read_manifest()
    manifest["groups"].append(stale)
    session.adapter.write_manifest(manifest)
    name = "AA_PREVIEW_WALL_L2_XPOS_LEEWARD_MIN"
    name = next(n for n in session.adapter.groups if n.startswith(name))
    session.adapter.groups[name].append("A:INT_1")
    assert session.create_preview_groups() == []
    assert stale not in session.adapter.groups
    assert "A:INT_1" not in session.adapter.groups[name]


def test_unrelated_group_name_conflict_detected(session):
    session.adapter.groups[session.cats.groups[0].name] = ["A:INT_1"]
    diags = session.create_preview_groups()
    assert any(d.code == "group_name_conflict" for d in diags)
    assert not session.preview_valid


def test_locked_model_requires_explicit_unlock(session):
    session.create_preview_groups()
    session.adapter.locked = True
    res = session.apply()
    assert not res.ok and "locked" in res.message and session.adapter.unlocked_count == 0
    res = session.apply(allow_unlock=True)
    assert res.ok and any(d.code == "unlocked" for d in res.diagnostics)


def test_partial_failure_reported_without_claiming_rollback(session):
    session.create_preview_groups()
    session.adapter.fail_on = "define_case:W_Wall_+Y"
    res = session.apply()
    assert not res.ok and res.partial and "NOT rolled back" in res.message
    assert res.applied["assignments"] == len(session.plan.assignments)
    assert res.applied["combinations"] == 0  # dependent writes stopped
    assert not any(c.startswith("define_combination") for c in session.adapter.calls)


def test_existing_unrelated_pattern_not_taken_over(session):
    session.adapter.extra_patterns.append("W_Wall_+X")
    session.adapter.extra_patterns.append("AW_OLD")
    session.read_model()
    session.build_plan()
    session.create_preview_groups()
    res = session.apply()
    assert not res.ok and any(d.code == "name_conflict" for d in res.diagnostics)


def test_audit_flags_aw_leftovers_without_deleting(session):
    session.adapter.extra_patterns.append("AW_OLD")
    session.read_model()
    plan = session.build_plan()
    assert any(d.code == "audit_unfamiliar_pattern" and "AW_OLD" in d.message for d in plan.diagnostics)
    session.create_preview_groups()
    session.apply()
    assert "AW_OLD" in session.adapter.read_patterns()


def test_yaml_reload_invalidates(session, tmp_path):
    session.create_preview_groups()
    p = tmp_path / "w.yaml"
    p.write_text(REFERENCE.read_text().replace("basic_wind_speed_mph: 120.0", "basic_wind_speed_mph: 130.0"))
    session.load_config(str(p))
    assert session.plan is None and session.pressures is None and not session.preview_valid


def test_etabs_dimension_source(session, tmp_path):
    text = REFERENCE.read_text().replace('plan_dimensions_source: "yaml"', 'plan_dimensions_source: "etabs"')
    text = text.replace("parallel_l: 1472.0 ", "parallel_l: 1400.0 ").replace(
        "perpendicular_b: 1472.0 ", "perpendicular_b: 1400.0 ")
    p = tmp_path / "w.yaml"
    p.write_text(text)
    s = WindSession()
    s.load_config(str(REFERENCE))
    s.use_offline_demo()  # synthetic model is 1472 ft long
    s.load_config(str(p))  # YAML now claims 1400 ft and asks for ETABS-derived dimensions
    s.read_model()
    s.calculate()
    assert s.pressures.dims["X"].parallel_l == 1472.0
    assert any(d.code == "dimension_discrepancy" for d in s.cats.diagnostics)


def test_exports(session, tmp_path):
    session.create_preview_groups()
    session.apply()
    session.verify()
    files = export_all(session, tmp_path)
    assert {f.name for f in files} == {"effective_config.yaml", "assignment_plan.json",
                                       "assignment_plan.csv", "report.html",
                                       "pressure_results.txt", "pressure_results.json"}
    data = json.loads((tmp_path / "assignment_plan.json").read_text())
    assert len(data["assignments"]) == len(session.plan.assignments)
    html = (tmp_path / "report.html").read_text()
    assert "Live ETABS verification" in html and "provisional" in html.lower()
    assert "WALL_WW_L2_MIN" in html


def test_walls_parapets_only_applies_without_equipment_or_torsion_targets(session):
    from dataclasses import replace

    session.cfg = replace(session.cfg, loading=replace(session.cfg.loading, scope="walls_parapets"))
    session.snapshot.joints.clear()
    session.snapshot.frames.clear()
    session.snapshot.stories.clear()
    session.categorize()
    plan = session.build_plan()
    assert len(plan.patterns) == len(plan.cases) == 8
    assert not plan.combinations
    assert plan.assignments and all(a.pattern.startswith(("AA_W_Wall_", "AA_W_Parapet_"))
                                    for a in plan.assignments)
    session.adapter.extra_patterns.extend(["W_Wall_+X", "W_Parapet_+X"])
    assert not any(d.level == "error" for d in plan.diagnostics)
    session.create_preview_groups()
    result = session.apply()
    assert result.ok, result
    assert result.applied["combinations"] == 0
    assert all(r.ok for r in session.verify())


def test_wall_scope_config_roundtrips():
    from air_apparent.config import effective_config_yaml, load_config, parse_config

    cfg = load_config(REFERENCE.with_name("walls_parapets_only.yaml"))
    assert cfg.loading.scope == "walls_parapets"
    assert parse_config(effective_config_yaml(cfg)).loading.scope == "walls_parapets"


def test_changing_scope_clears_torsion_errors_and_invalidates_previews(session):
    from air_apparent.config import effective_config_yaml, parse_config

    session.snapshot.stories.clear()
    session.build_plan()
    assert any(d.code == "ecc_no_reference_joint" for d in session.plan.diagnostics)
    session.create_preview_groups()
    previous_hash = session.config_hash
    session.set_loading_scope("walls_parapets")
    assert session.plan is None and not session.preview_valid
    assert session.config_hash != previous_hash
    assert parse_config(effective_config_yaml(session.cfg)).loading.scope == "walls_parapets"
    plan = session.build_plan()
    assert not any(d.level == "error" for d in plan.diagnostics)
    assert len(plan.patterns) == 8 and not plan.combinations
    session.create_preview_groups()
    assert session.apply().ok


def test_reference_sample_applies_wall_scope_without_torsion_targets():
    s = WindSession()
    s.load_config(str(REFERENCE))
    s.use_offline_demo()
    s.read_model()
    s.snapshot.stories.clear()
    s.build_plan()
    s.create_preview_groups()
    result = s.apply()
    assert result.ok, result
    assert not any(p.family == "Ecc" for p in s.plan.patterns)


def test_retry_reuses_exact_case_left_by_interrupted_scoped_apply(session):
    session.set_loading_scope("walls_parapets")
    session.build_plan()
    session.create_preview_groups()
    case = session.plan.cases[0]
    session.adapter.fail_on = "define_case:" + case.name
    assert session.apply().partial
    # Simulate ETABS completing SetLoads before the old client misread its success response.
    session.adapter.cases[case.name] = case
    session.adapter.fail_on = ""
    before = len(session.adapter.calls)
    result = session.apply()
    assert result.ok, result
    assert "define_case:" + case.name not in session.adapter.calls[before:]
    assert any(d.code == "matching_case_reused" for d in result.diagnostics)
    assert case.name in session.adapter.read_manifest()["cases"]


def test_retry_does_not_reuse_mismatched_case(session):
    from dataclasses import replace

    session.set_loading_scope("walls_parapets")
    session.build_plan()
    session.create_preview_groups()
    case = session.plan.cases[0]
    session.adapter.fail_on = "define_case:" + case.name
    session.apply()
    session.adapter.fail_on = ""
    session.adapter.cases[case.name] = replace(case, terms=((case.terms[0][0], 2.0),))
    assert any(d.code == "name_conflict" for d in session.apply().diagnostics)

