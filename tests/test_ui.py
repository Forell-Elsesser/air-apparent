"""Exercise UI actions without a display server or a live ETABS model."""

import os
from dataclasses import replace
from unittest.mock import Mock

import pytest

from air_apparent.etabs import AdapterError
from air_apparent.models import PATTERN_GROUP_NAMES
from air_apparent.ui import DEFAULT_YAML, App
from air_apparent.workflow import WindSession
from tests.conftest import REFERENCE, TEMPLATE


class GroupTree:
    def __init__(self):
        self.rows = {}
        self.selected = ()

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *names):
        for name in names:
            self.rows.pop(name)
        self.selected = tuple(n for n in self.selected if n in self.rows)

    def insert(self, parent, position, *, iid, values):
        self.rows[iid] = values

    def selection(self):
        return self.selected

    def selection_set(self, names):
        self.selected = tuple(names)

    def set(self, name, column):
        assert column == "group"
        return self.rows[name][0]


def make_app(session):
    app = App.__new__(App)
    app.s = session
    app.tree = GroupTree()
    app.text = Mock()
    app.status = Mock()
    app.path_label = Mock()
    return app


W = "W_Wall_+X"


def test_select_pattern_row_after_first_calculate_writes_groups_and_selects(session):
    app = make_app(session)
    app.calculate()
    rows = list(app.tree.rows)
    assert rows[:16] == list(PATTERN_GROUP_NAMES) and len(rows) > 16
    assert W not in session.adapter.groups
    app.tree.selection_set([W])
    app.select()
    assert session.adapter.selected == W
    assert set(session.adapter.groups[W]) == set(session.cats.pattern_groups[W])
    assert session.preview_valid and not session.adapter.assignments


def test_pattern_rows_show_rules_versus_model_counts(session):
    session.adapter.groups[W] = ["A:W_S_L2_1", "A:NOT_THERE"]
    session.read_model()
    app = make_app(session)
    app.calculate()
    assert app.tree.rows[W][0] == W and "40 by rules" in app.tree.rows[W][7] and "2 in model" in app.tree.rows[W][7]
    assert app.tree.rows["W_PH_-Y"][9] == 6


def test_repeated_calculate_preserves_rows_and_selection(session):
    app = make_app(session)
    app.calculate()
    rows = dict(app.tree.rows)
    app.tree.selection_set([W])
    app.select()
    for _ in range(2):
        app.calculate()
        assert app.tree.rows == rows
        assert app.tree.selection() == (W,)
        app.select()
        assert session.adapter.selected == W


def test_default_input_and_repeat_flow_use_wind_inputs_template():
    assert DEFAULT_YAML == TEMPLATE
    session = WindSession()
    session.load_config(str(DEFAULT_YAML))
    session.use_offline_demo()
    app = make_app(session)
    app.calculate()
    rows = dict(app.tree.rows)
    assert len(rows) > 16
    app.calculate()
    assert app.tree.rows == rows
    app.tree.selection_set([W])
    app.select()
    assert session.adapter.selected == W
    assert session.cfg.source_path == str(DEFAULT_YAML)


def test_unresolved_shell_is_listed_in_text_not_rows(session):
    session.cfg = replace(session.cfg,
                          exterior_segments=tuple(s for s in session.cfg.exterior_segments if s.id != "S"))
    session.categorize()
    app = make_app(session)
    app.calculate()
    messages = "".join(call.args[1] for call in app.text.insert.call_args_list)
    assert "no_exterior_segment" in messages and "(A:W_S_" in messages
    assert all(row[0] for row in app.tree.rows.values())
    assert not any(name.startswith("WALL_L2_YPOS_WINDWARD_S") for name in app.tree.rows)


def test_touching_yaml_does_not_clear_rows_or_invalidate_preview(session, tmp_path):
    path = tmp_path / "wind_inputs.yaml"
    path.write_text(REFERENCE.read_text())
    app = make_app(session)
    app._load(str(path))
    app.calculate()
    app.tree.selection_set([W])
    app.select()
    plan = session.plan
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    app._refresh_if_yaml_changed()
    assert session.plan is plan and session.preview_valid
    assert app.tree.selection() == (W,)


def test_changed_yaml_clears_stale_rows_then_recalculates_and_selects(session, tmp_path):
    path = tmp_path / "wind_inputs.yaml"
    original = REFERENCE.read_text()
    path.write_text(original)
    app = make_app(session)
    app._load(str(path))
    app.calculate()
    path.write_text(original.replace("basic_wind_speed_mph: 120.0", "basic_wind_speed_mph: 130.0"))
    app._refresh_if_yaml_changed()
    assert not app.tree.rows
    assert session.plan is None and not session.preview_valid
    app.calculate()
    assert len(app.tree.rows) > 16
    app.tree.selection_set([W])
    app.select()
    assert session.adapter.selected == W
    assert session.cfg.wind.basic_wind_speed_mph == 130.0


def test_select_detects_drift(session):
    session.write_pattern_groups()
    session.adapter.groups[W].append("A:UNEXPECTED")
    with pytest.raises(AdapterError, match="drift"):
        session.select_group(W)
    assert not session.preview_valid
    assert session.adapter.selected == ""


def test_select_fine_group_row_selects_its_members(session):
    app = make_app(session)
    app.calculate()
    name = list(app.tree.rows)[16]
    spec = next(g for g in session.cats.groups if g.name == name)
    app.tree.selection_set([name])
    app.select()
    assert session.adapter.selected_objects == list(spec.members)


def test_write_groups_button_reports_result(session):
    app = make_app(session)
    app.calculate()
    app.groups()
    assert session.preview_valid and set(session.adapter.read_groups()) == set(PATTERN_GROUP_NAMES)
    assert "16" in app.status.set.call_args.args[0]
