import pytest

from air_apparent.etabs import AdapterError
from air_apparent.etabs.tables import find_grid_table, length_factor, parse_grid_table

FIELDS = ["GridSys", "GridLineType", "ID", "Ordinate"]
NAMES = ["Grid System", "Grid Line Type", "Grid ID", "Ordinate"]


def _rows(*rows):
    return [c for r in rows for c in r], len(rows)


def test_find_grid_table_picks_single_match_or_raises():
    assert find_grid_table(["A", "B"], ["Story Definitions", "Grid Definitions - Grid Lines"]) == "B"
    with pytest.raises(AdapterError, match="Story Definitions"):
        find_grid_table(["A"], ["Story Definitions"])


def test_length_factor():
    assert length_factor(" in ") == pytest.approx(1 / 12) and length_factor("FT") == 1.0
    assert length_factor("") is None
    with pytest.raises(AdapterError, match="furlong"):
        length_factor("furlong")


def test_parse_in_inches_with_units_string():
    data, n = _rows(["G1", "X (Cartesian)", "28.5", "27"], ["G1", "Y (Cartesian)", "J", "0"])
    systems, lines, diags = parse_grid_table(FIELDS, NAMES, ["", "", "", "in"], data, n, 421.75)
    assert [(g.axis, g.label, g.ordinate_ft) for g in lines] == [("x", "28.5", 2.25), ("y", "J", 0.0)]
    assert systems[0].name == "G1" and not [d for d in diags if d.level == "error"]


def test_parse_empty_units_falls_back_to_point_span():  # Review Focus 5
    data, n = _rows(["G1", "X (Cartesian)", "28", "0"], ["G1", "X (Cartesian)", "39", "5061"])
    _, lines, diags = parse_grid_table(FIELDS, NAMES, ["", "", "", ""], data, n, 421.75)
    assert lines[1].ordinate_ft == pytest.approx(421.75)
    assert any(d.code == "grid_table_units_inferred" for d in diags)


def test_parse_rejects_implausible_span():
    data, n = _rows(["G1", "X (Cartesian)", "28", "0"], ["G1", "X (Cartesian)", "39", "50"])
    with pytest.raises(AdapterError):
        parse_grid_table(FIELDS, NAMES, ["", "", "", ""], data, n, 421.75)


def test_non_cartesian_direction_is_reported_not_parsed():
    data, n = _rows(["C1", "R (Cylindrical)", "R1", "10"])
    _, lines, diags = parse_grid_table(FIELDS, NAMES, ["", "", "", "ft"], data, n, 421.75)
    assert lines == [] and any(d.code == "grid_system_unsupported" for d in diags)
