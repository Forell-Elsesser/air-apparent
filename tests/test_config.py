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
    errs = _errors(_ref_text().replace("schema_version: 1\n", "schema_version: 1\nunits: \"US\"\n", 1))
    assert any("duplicate key" in e for e in errs)


def test_safe_loading_rejects_python_tags():
    errs = _errors(_ref_text() + "\nevil: !!python/object/apply:os.system ['echo hi']\n")
    assert errs


def test_branch_and_override_validation():
    errs = _errors(_ref_text().replace('"-X": "Max"', '"-X": "Maximum"'))
    assert any(e.startswith("loading.wall_pressure_branch_by_direction.-X") for e in errs)
    errs = _errors(_ref_text().replace("overrides: {}", 'overrides: {"7": "wall"}'))
    assert any(e.startswith("overrides.7") for e in errs)


def test_duplicate_support_joint_mapping():
    text = _ref_text().replace("CH02_J1", "CH01_J1")
    assert any("mapped more than once" in e for e in _errors(text))
