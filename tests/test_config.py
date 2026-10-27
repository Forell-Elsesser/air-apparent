import pytest

from air_apparent.config import ConfigError, load_config, parse_config
from tests.conftest import REFERENCE, TEMPLATE

WORKBOOK_FIELDS = [
    "risk_category", "basic_wind_speed_mph", "directionality_factor_kd", "exposure_category",
    "topographic_factor_kzt", "gust_effect_factor_g", "enclosure_classification",
    "internal_pressure_coefficient_abs", "mean_roof_height_above_grade_ft",
]


def test_reference_and_template_load():
    ref = load_config(REFERENCE)
    load_config(TEMPLATE)
    for f in WORKBOOK_FIELDS:
        assert f in ref.raw["wind"]
    assert ref.geometry.plan_dimensions_source == "yaml"
    assert ref.loading.scope == "walls_parapets"
    assert ref.geometry.x_wind.parallel_l == ref.geometry.y_wind.perpendicular_b == 1472.0
    assert ref.geometry.x_wind.perpendicular_b == ref.geometry.y_wind.parallel_l == 240.0
    assert ref.loading.wall_pressure_branch_by_direction == {
        "+X": "Min", "-X": "Max", "+Y": "Min", "-Y": "Min"}
    assert len(ref.equipment) == 18


def _errors(text):
    with pytest.raises(ConfigError) as e:
        parse_config(text)
    return e.value.errors


def _ref_text():
    return REFERENCE.read_text()


def test_field_path_errors():
    errs = _errors(_ref_text().replace("basic_wind_speed_mph: 120.0", "basic_wind_speed_mph: -3"))
    assert any(e.startswith("wind.basic_wind_speed_mph:") for e in errs)
    errs = _errors(_ref_text().replace('exposure_category: "C"', 'exposure_category: "Z"'))
    assert any(e.startswith("wind.exposure_category:") for e in errs)


def test_unknown_key_and_missing_required():
    errs = _errors(_ref_text().replace("wind:\n", "wind:\n  bogus: 1\n", 1))
    assert "wind.bogus: unknown key" in errs
    errs = _errors(_ref_text().replace("  risk_category: \"IV\"", "#"))
    assert "wind.risk_category: required value is missing" in errs


def test_linked_dimensions_enforced():
    errs = _errors(_ref_text().replace("parallel_l: 240.0 ", "parallel_l: 250.0 "))
    assert any(e.startswith("geometry.plan_dimensions_ft.y_wind.parallel_l") for e in errs)


def test_duplicate_keys_rejected():
    errs = _errors(_ref_text().replace("schema_version: 2\n", "schema_version: 2\nunits: \"US\"\n", 1))
    assert any("duplicate key" in e for e in errs)


def test_safe_loading_rejects_python_tags():
    errs = _errors(_ref_text() + "\nevil: !!python/object/apply:os.system ['echo hi']\n")
    assert errs


def test_branch_and_override_validation():
    errs = _errors(_ref_text().replace('"-X": "Max"', '"-X": "Maximum"'))
    assert any(e.startswith("loading.wall_pressure_branch_by_direction.-X") for e in errs)
    errs = _errors(_ref_text().replace("overrides:", 'overrides:\n  "7": {category: wall}\n  #', 1))
    assert any(e.startswith("overrides.7") for e in errs)


def test_duplicate_support_joint_mapping():
    text = _ref_text().replace("CH02_J1", "CH01_J1")
    assert any("mapped more than once" in e for e in _errors(text))


def test_schema_v2_segments_and_levels_load():
    ref = load_config(REFERENCE)
    assert ref.schema_version == 2 and len(ref.exterior_segments) == 4
    assert ref.exterior_segments[0].along == "A" and ref.exterior_segments[0].outside == "-Y"
    assert ref.exterior_segments[0].z_from is None
    assert ref.levels.main_roof == "ROOF" and ref.levels.mechanical == "PARAPET_PF"
    assert ref.categorization.extent_tolerance_ft == 0.5
    assert ref.overrides["INT_1"].category == "excluded"


def test_schema_v1_rejected_with_pointer():
    errs = _errors(_ref_text().replace("schema_version: 2", "schema_version: 1"))
    assert any("no longer supported" in e and "exterior_segments" in e for e in errs)


def test_segment_validation():
    text = _ref_text().replace('{id: S, along: A, from: "1", to: "2", outside: "-Y"}',
                               '{id: S, along: 0.0, from: "1", to: "2", outside: "-Y"}')
    assert any(e.startswith("exterior_segments[0].axis") for e in _errors(text))
    dup = '  - {id: S, along: B, from: "1", to: "2", outside: "+Y"}'
    text = _ref_text().replace('outside: "-Y"}', 'outside: "-Y"}\n' + dup, 1)
    assert any("ids must be unique" in e for e in _errors(text))
    text = _ref_text().replace('{id: S, along: A, from: "1", to: "2", outside: "-Y"}',
                               '{id: S, along: A, from: "1", to: "2", outside: "-Y", z_from: 50.0, z_to: 40.0}')
    assert any(e.startswith("exterior_segments[0].z_to") for e in _errors(text))


def test_equipment_frames_or_joints():
    joints = "support_joints: [CH01_J1, CH01_J2, CH01_J3, CH01_J4]"
    text = _ref_text().replace(joints, "support_frames: [B1, B2, B3]")
    assert any(e.startswith("equipment[0].support_frames") for e in _errors(text))
    text = _ref_text().replace(joints, "support_frames: [B1, B2, B3, B4]")
    assert parse_config(text).equipment[0].support_frames == ("B1", "B2", "B3", "B4")
