"""Exercise UI actions without a display server or a live ETABS model."""

import os
from dataclasses import replace
from unittest.mock import Mock

import pytest

from air_apparent.etabs import AdapterError
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


def test_select_after_first_calculate_creates_groups_and_selects_members(session):
    app = make_app(session)
    app.calculate()
    assert len(app.tree.rows) > 1
    group = session.plan.groups[0]
    assert group.name not in session.adapter.groups
    app.tree.selection_set([group.name])
    app.select()
    assert session.adapter.selected == group.name
    assert set(session.adapter.groups[group.name]) == set(group.members)
    assert session.preview_valid
    assert not session.adapter.assignments


def test_repeated_calculate_preserves_rows_and_selection(session):
    app = make_app(session)
    app.calculate()
    rows = dict(app.tree.rows)
    group = session.plan.groups[0].name
    app.tree.selection_set([group])
    app.select()
    for _ in range(2):
        app.calculate()
        assert app.tree.rows == rows
        assert app.tree.selection() == (group,)
        app.select()
        assert session.adapter.selected == group


def test_default_input_and_repeat_flow_use_wind_inputs_template():
    assert DEFAULT_YAML == TEMPLATE
    session = WindSession()
    session.load_config(str(DEFAULT_YAML))
    session.use_offline_demo()
    app = make_app(session)
    app.calculate()
    rows = dict(app.tree.rows)
    assert len(rows) > 1
    app.calculate()
    assert app.tree.rows == rows
    app.tree.selection_set([next(iter(rows))])
    app.select()
    assert session.adapter.selected in rows
    assert session.cfg.source_path == str(DEFAULT_YAML)


def test_single_unresolved_row_exposes_classification_diagnostics(session):
    # Model walls span both pressure bands, so classification requests subdivision.
    session.snapshot.shells = [replace(s, corners=tuple(
        (x, y, 62.0 if z > 0 else 0.0) for x, y, z in s.corners
    )) for s in session.snapshot.shells if s.name.startswith("W_") and "L2" in s.name]
    session.cfg = replace(session.cfg, equipment=(), platforms=())
    session.categorize()
    app = make_app(session)
    app.calculate()
    assert list(app.tree.rows) == ["AA_PREVIEW_UNRESOLVED"]
    messages = "".join(call.args[1] for call in app.text.insert.call_args_list)
    assert "needs_subdivision" in messages and "(A:W_" in messages
    app.tree.selection_set(["AA_PREVIEW_UNRESOLVED"])
    app.select()
    assert session.adapter.selected == "AA_PREVIEW_UNRESOLVED"
    assert len(session.adapter.groups["AA_PREVIEW_UNRESOLVED"]) == len(session.snapshot.shells)


def test_touching_yaml_does_not_clear_rows_or_invalidate_preview(session, tmp_path):
    path = tmp_path / "wind_inputs.yaml"
    path.write_text(REFERENCE.read_text())
    app = make_app(session)
    app._load(str(path))
    app.calculate()
    group = session.plan.groups[0].name
    app.tree.selection_set([group])
    app.select()
    plan = session.plan
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))
    app._refresh_if_yaml_changed()
    assert session.plan is plan and session.preview_valid
    assert app.tree.selection() == (group,)


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
    assert len(app.tree.rows) > 1
    app.tree.selection_set([session.plan.groups[0].name])
    app.select()
    assert session.adapter.selected == session.plan.groups[0].name
    assert session.cfg.wind.basic_wind_speed_mph == 130.0


def test_select_detects_manual_membership_changes(session):
    session.create_preview_groups()
    group = session.plan.groups[0]
    session.adapter.groups[group.name].append("A:UNEXPECTED")
    with pytest.raises(AdapterError, match="added manually"):
        session.select_group(group.name)
    assert not session.preview_valid
    assert session.adapter.selected == ""


def test_select_does_not_overwrite_unowned_group(session):
    group = session.plan.groups[0]
    session.adapter.groups[group.name] = ["A:UNRELATED"]
    with pytest.raises(AdapterError, match="not tool-owned"):
        session.select_group(group.name)
    assert session.adapter.groups[group.name] == ["A:UNRELATED"]
    assert session.adapter.selected == ""
