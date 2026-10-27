# Categorization Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read stories, grid lines, geometry and `W_*` groups from a live ETABS model, categorize every shell and configured frame by rules driven by story bands and declared exterior segments, and write the sixteen `W_*` pattern groups back to ETABS.

**Architecture:** The live COM adapter is rewritten around bulk reads and a database-table grid reader, feeding a richer `ModelSnapshot` that can be captured to JSON for offline tests. The categorization package is rebuilt as three focused modules: `segments.py` (resolve YAML segments against grid lines and place shells), `rules.py` (per-shell level, element type, role, parapet type, frames) and `groups.py` (sixteen pattern groups, fine groups, comparison with existing groups). `WindSession` writes the pattern groups with replace semantics and gates apply on group drift.

**Tech Stack:** Python 3.11+, dataclasses, PyYAML, pytest, ruff; comtypes against the ETABS 23 OAPI on Windows (live steps only).

**Spec:** `docs/superpowers/specs/2026-10-27-categorization-design.md`

## Global Constraints

- Python >= 3.11; `ruff check .` and `pytest -q` green at every commit, without ETABS.
- Core modules (`models`, `config`, `categorization`, `pressures`, `patterns`, `combinations`) never import `comtypes`, `tkinter` or the live adapter.
- All YAML and snapshot lengths are feet; the adapter sets present units `kip_ft_F` (4) before any read or write and restores them in `close()`.
- Only groups whose names start with `W_` are read, compared, created, emptied or filled. No other group is touched. The sixteen names: `W_Wall_+X W_Wall_-X W_Wall_+Y W_Wall_-Y W_Parapet_+X W_Parapet_-X W_Parapet_+Y W_Parapet_-Y W_PH_+X W_PH_-X W_PH_+Y W_PH_-Y W_Mech_+X W_Mech_-X W_Mech_+Y W_Mech_-Y`.
- Every vertical shell ends in a group, a declared exclusion, or a diagnostic naming it; never silently unloaded.
- Story labels and local axis 3 are never used by a rule.
- Default tolerances: `plane_tolerance_ft 0.1`, `range_tolerance_ft 0.5`, `level_tolerance_ft 0.05`.
- Diagnostic codes are exactly the spec's: `not_axis_aligned`, `above_top_story`, `level_unmapped`, `no_exterior_segment`, `ambiguous_segment`, `declared_unexposed`, `no_penthouse_edge`, `body_below_penthouse_level`, `extent_exceeds_segment`, `parapet_type_unmatched`, `missing_support_frame`, `missing_platform_frame`, `frame_level_unexpected`, `grid_system_unsupported`, `grid_label_unknown`, `segment_overlap`, `equipment_loads_deferred`.
- Live steps need one ETABS 23 instance with the seven-story `examples/Test Model.EDB` open; pass its pid explicitly. Rebase on `main` before each task; Yinchen edits `ui.py`, `workflow.py`, `adapter.py` concurrently.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A numeric grid label written unquoted in YAML (`along: 39`) parses as 39.0 ft, not grid "39". Expected: the segment is still accepted as an ordinate, and categorization emits `warning: numeric_along_matches_label` naming the label so the engineer sees the slip. Test pinned in Task 7.
2. A shell whose plan midpoint sits within `range_tolerance_ft` of the shared endpoint of two adjacent segments on the same line. Expected: placed on the segment that overlaps more of its extent, not `ambiguous_segment`. Test pinned in Task 7.
3. A shell whose top edge is exactly at a story elevation. Expected: level is that story, not the one above. Test pinned in Task 8.
4. A model whose existing group is spelled `w_wall_+x`. Expected: read as `W_Wall_+X`'s existing membership and refilled under the model's own spelling, never a second group. Test pinned in Task 12.
5. A grid table whose ordinate field reports an empty `UnitsString` while the model is in inches. Expected: ordinates land in feet via the span fallback and an `info` diagnostic says so. Test pinned in Task 2.

---

### Task 1: Snapshot model additions and JSON round-trip

**Files:**
- Modify: `src/air_apparent/models.py` (Story, ModelSnapshot, new GridSystem, GridLine)
- Create: `src/air_apparent/snapshot_io.py`
- Test: `tests/test_snapshot_io.py`

**Interfaces:**
- Produces, in `models.py`:
  - `GridSystem(name: str, kind: str, origin_x_ft: float, origin_y_ft: float, rotation_deg: float)` frozen dataclass.
  - `GridLine(system: str, axis: str, label: str, ordinate_ft: float)` frozen; `axis` is `"x"` for a line of constant X, `"y"` for constant Y.
  - `Story` gains `height_ft: float = 0.0`, `is_master: bool = True`, `similar_to: str = ""` after `elevation_ft` (existing positional callers `Story(name, elev, diaphragm, joint)` must be updated to keywords in `demo.py`).
  - `ModelSnapshot` gains `base_elevation_ft: float = 0.0`, `grid_systems: list[GridSystem]`, `grid_lines: list[GridLine]`, `labels: dict[str, tuple[str, str]]` (all default-empty).
- Produces, in `snapshot_io.py`: `snapshot_to_json(snap: ModelSnapshot) -> str` and `snapshot_from_json(text: str) -> ModelSnapshot`; tuples restored as tuples (`Shell.corners`, `Shell.local3`, `Shell.groups`, `Frame.p1/p2`, `Joint.xyz`, label pairs).

- [ ] **Step 1: Write the failing round-trip test**

```python
# tests/test_snapshot_io.py
from air_apparent.models import GridLine, GridSystem, ModelSnapshot, Shell, Story
from air_apparent.snapshot_io import snapshot_from_json, snapshot_to_json

def test_round_trip_preserves_everything():
    snap = ModelSnapshot(
        shells=[Shell("W1", ((0, 0, 0), (10, 0, 0), (10, 0, 12), (0, 0, 12)), (0, -1, 0), ("W_Wall_+X",))],
        stories=[Story("L2", 31.5, 32.333, True, "", "D1", "J7")],
        base_elevation_ft=-0.833,
        grid_systems=[GridSystem("G1", "Cartesian", 0.0, 0.0, 0.0)],
        grid_lines=[GridLine("G1", "x", "28.5", 2.25), GridLine("G1", "y", "J", 0.0)],
        labels={"A:W1": ("W1", "L2")},
        groups={"W_Wall_+X": ["A:W1"]},
    )
    back = snapshot_from_json(snapshot_to_json(snap))
    assert back == snap
    assert isinstance(back.shells[0].corners[0], tuple) and isinstance(back.labels["A:W1"], tuple)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_snapshot_io.py -v`
Expected: FAIL with `ImportError` (no `snapshot_io`, no `GridLine`).

- [ ] **Step 3: Add the dataclasses and fields to `models.py`; update `demo.py`'s `Story(...)` call to keywords; implement `snapshot_io.py` with `dataclasses.asdict` plus an explicit reconstruct per dataclass**

- [ ] **Step 4: Run the new test and the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (62 existing + 1).

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/models.py src/air_apparent/snapshot_io.py src/air_apparent/demo.py tests/test_snapshot_io.py
git commit -m "feat: grid and story fields on ModelSnapshot with JSON round-trip"
```

---

### Task 2: Grid-table discovery and parsing

**Files:**
- Create: `src/air_apparent/etabs/tables.py`
- Test: `tests/test_etabs_tables.py`

**Interfaces:**
- Produces:
  - `find_grid_table(keys: list[str], names: list[str]) -> str` returns the single key whose name contains both "grid" and "line" case-insensitively; raises `AdapterError` listing all names otherwise.
  - `length_factor(units_string: str) -> float | None`: `"in"`->`1/12`, `"ft"`->`1.0`, `"mm"`->`1/304.8`, `"m"`->`1/0.3048`, `""`->`None`, anything else raises `AdapterError` naming the string. Matching is case-insensitive and ignores surrounding whitespace.
  - `parse_grid_table(field_keys: list[str], field_names: list[str], units: list[str], data: list[str], n_records: int, point_x_span_ft: float) -> tuple[list[GridSystem], list[GridLine], list[Diagnostic]]`. Columns are found by normalised name (lowercase, alphanumerics only) against candidate sets: system `{"gridsys","gridsystem","name"}`; type `{"gridsystype","gridsystemtype","type"}`; direction `{"gridlinetype","linetype","direction","dir","axis"}`; id `{"gridid","id","label","gridlabel"}`; ordinate `{"ordinate","coord","coordinate"}`; origin/rotation `{"xo","originx","xorigin"}`, `{"yo","originy","yorigin"}`, `{"rz","rotation","angle"}` (optional, default 0). A direction cell containing "x" (e.g. `X (Cartesian)`) is `axis "x"`, containing "y" is `"y"`; other directions produce no `GridLine` and one `warning: grid_system_unsupported` per system. Unit handling: `length_factor(units of the ordinate column)`; when `None`, compare the X-ordinate span with `point_x_span_ft`: ratio in `[0.9, 1.1]` means feet, within 2% of 12 means inches (divide by 12, emit `info: grid_table_units_inferred`), else raise `AdapterError`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_etabs_tables.py
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

def test_parse_empty_units_falls_back_to_point_span():   # Review Focus 5
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_etabs_tables.py -v`
Expected: FAIL with `ModuleNotFoundError: air_apparent.etabs.tables`.

- [ ] **Step 3: Implement `tables.py` (pure functions, no comtypes import)**

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_etabs_tables.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/etabs/tables.py tests/test_etabs_tables.py
git commit -m "feat: ETABS grid-line table discovery and parsing"
```

---

### Task 3: Live reader rewrite, read-back fixes, capture CLI, phase-1 dump

**Files:**
- Modify: `src/air_apparent/etabs/adapter.py` (`EtabsAdapter` protocol, `ComEtabsAdapter.read_model`, `read_groups`, `read_assignments`, new `_read_stories`, `_read_grids`)
- Create: `src/air_apparent/capture.py`
- Modify: `tests/test_etabs_adapter.py` (fake-API tests, same `SimpleNamespace` style as Yinchen's)
- Modify: `docs/etabs_setup.md` (record the live dump)

**Interfaces:**
- Consumes: Task 1 dataclasses; Task 2 `find_grid_table`, `parse_grid_table`.
- Produces:
  - Protocol `EtabsAdapter.read_groups(self, prefix: str = "W_") -> dict[str, list[str]]`: group names starting with `prefix` case-insensitively, keyed by the model's own spelling.
  - `ComEtabsAdapter.read_model() -> ModelSnapshot` populated as spec 4.2 to 4.5: `base_elevation_ft`, `stories` bottom-up with `height_ft`/`is_master`/`similar_to`, `grid_systems`, `grid_lines`, `shells` from `AreaObj.GetAllAreas` (corners from `PointDelimiter` slices; `local3` from `GetTransformationMatrix(name)[0][6:9]` per shell), `frames` from `FrameObj.GetAllFrames`, `joints` from `PointObj.GetAllPoints`, `labels` from the three `GetLabelNameList` calls, `groups` from `read_groups("W_")`, existing patterns/cases/combos as today.
  - `ComEtabsAdapter.read_assignments()` indexes corrected: joints `r[5], r[6], r[10]`; frames `r[5]` (Dir), `r[10]` (Val1); group argument `"All"`.
  - `capture.main(argv: list[str] | None = None) -> int`, invoked as `python -m air_apparent.capture --pid N OUT.json`; prints base elevation, each story (`name elevation height`), each grid line (`system axis label ordinate`), object counts and the sixteen `W_*` sizes, then writes `snapshot_to_json`.

- [ ] **Step 1: Write failing fake-API tests for `read_assignments` indexing and `_read_stories`**

```python
# tests/test_etabs_adapter.py (append)
def test_read_assignments_uses_documented_tuple_positions():
    api = SimpleNamespace(
        AreaObj=SimpleNamespace(GetLoadUniform=lambda n, t: [1, ("A1",), ("W_Wall_+X",), ("Global",), (4,), (0.5,), 0]),
        PointObj=SimpleNamespace(GetLoadForce=lambda n, t: [1, ("P1",), ("W_Mech_+X",), (0,), ("Global",),
                                                            (1.5,), (0.0,), (0.0,), (0.0,), (0.0,), (7.0,), 0]),
        FrameObj=SimpleNamespace(GetLoadDistributed=lambda n, t: [1, ("B1",), ("W_Mech_+Y",), (1,), ("Global",),
                                                                  (5,), (0,), (1,), (0,), (10,), (0.25,), (0.25,), 0]),
    )
    out = {(a.kind, a.object_ref, a.global_dir): a.value for a in _adapter_with_api(api).read_assignments()}
    assert out[("joint_force", "P:P1", "X")] == 1.5
    assert out[("joint_moment", "P:P1", "Mz")] == 7.0
    assert out[("frame_line_load", "F:B1", "Y")] == 0.25

def test_read_stories_is_bottom_up_with_heights():
    story = SimpleNamespace(GetStories_2=lambda: [-0.833, 2, ("R", "L2"), (60.083, 31.5), (28.583, 32.333),
                                                  (True, True), ("", ""), (False, False), (0, 0), (0, 0), 0])
    base, stories = ComEtabsAdapter._read_stories(SimpleNamespace(Story=story))
    assert base == -0.833 and [s.name for s in stories] == ["L2", "R"]
    assert stories[1].height_ft == 28.583

def test_read_groups_filters_prefix_case_insensitively():
    gd = SimpleNamespace(GetNameList=lambda: [3, ("CLADDING", "w_wall_+x", "W_PH_+Y"), 0],
                         GetAssignments=lambda g: [1, (5,), ("A7",), 0])
    groups = _adapter_with_api(SimpleNamespace(GroupDef=gd)).read_groups("W_")
    assert groups == {"w_wall_+x": ["A:A7"], "W_PH_+Y": ["A:A7"]}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_etabs_adapter.py -v`
Expected: the three new tests FAIL (wrong values / missing `_read_stories` / `read_groups` signature).

- [ ] **Step 3: Implement the adapter changes and `capture.py`**

`_read_stories(m) -> tuple[float, list[Story]]` and `_read_grids(m, point_x_span_ft) -> tuple[list[GridSystem], list[GridLine], list[Diagnostic]]` are static methods taking the `SapModel` so they are testable; `read_model` composes them. `FakeAdapter.read_groups` gains the `prefix` parameter with the same filter. Keep per-shell `GetTransformationMatrix` (eager).

- [ ] **Step 4: Run the suite**

Run: `.venv/Scripts/python.exe -m pytest -q` then `.venv/Scripts/ruff.exe check .`
Expected: all pass, ruff clean.

- [ ] **Step 5 (live): Install comtypes and dump the Test Model**

Run: `.venv/Scripts/python.exe -m pip install -e ".[dev,etabs]"`, then find the pid of the instance with the seven-story Test Model open (`tasklist /FI "IMAGENAME eq ETABS.exe"` or Tools > Active Instance for API in ETABS), then
`.venv/Scripts/python.exe -m air_apparent.capture --pid <PID> "C:\Users\james\AppData\Local\Temp\claude\c--Users-james-Documents-hack-air-apparent\c984e587-7ba4-4fc9-95b1-55e0fe146d76\scratchpad\test_model_dump.json"`.
Expected printed stories: `BASE -0.833` base; `L2 31.5`, `R 60.083`, `Parapet_1 65.083`, `Mech 70.708`, `Penthouse 75.167`, `Parapet_2 76.917` (±0.01). Expected grid lines: 13 X (28 at 0.0 ... 39 at 421.75), 5 Y (J 0, H 59, G 119, F 179, E 238). If the instance shows four stories, it has the old model: ask James to open the new EDB. If `find_grid_table` raises, record the table names it lists, pick the grid-line table by inspection, and adjust the name match in Task 2 (with a test). If a column is not found, print `FieldsKeysIncluded` and extend the candidate sets in Task 2 likewise.

- [ ] **Step 6: Record the live result in `docs/etabs_setup.md`**

Add a section "Phase 1 verified 2026-xx-xx" with the table key, the column keys used, the ordinate `UnitsString`, and the stories/grids printed. Mark checklist items 1 and 2 of that file done.

- [ ] **Step 7: Commit**

```bash
git add src/air_apparent/etabs/adapter.py src/air_apparent/etabs/fake_adapter.py src/air_apparent/capture.py tests/test_etabs_adapter.py docs/etabs_setup.md
git commit -m "feat: live reader with stories, grid lines, bulk geometry and W_ groups; read-back index fixes; capture CLI"
```

---

### Task 4: Capture the Test Model fixture

**Files:**
- Create: `tests/fixtures/test_model_snapshot.json` (live capture from Task 3's CLI)
- Create: `tests/test_fixture_test_model.py`

**Interfaces:**
- Produces the fixture used by Tasks 10 and 11, and `tests/conftest.py` fixture `test_model_snap()` returning `snapshot_from_json(...)` of that file.

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_fixture_test_model.py
def test_fixture_matches_model_facts(test_model_snap):
    s = test_model_snap
    assert [st.name for st in s.stories] == ["L2", "R", "Parapet_1", "Mech", "Penthouse", "Parapet_2"]
    assert s.base_elevation_ft == pytest.approx(-0.833, abs=0.01)
    assert sorted(g.label for g in s.grid_lines if g.axis == "y") == ["E", "F", "G", "H", "J"]
    assert len([g for g in s.grid_lines if g.axis == "x"]) == 13
    assert {k: len(v) for k, v in s.groups.items()} == {
        "W_Wall_+X": 568, "W_Wall_-X": 568, "W_Wall_+Y": 565, "W_Wall_-Y": 568,
        "W_Parapet_+X": 695, "W_Parapet_-X": 695, "W_Parapet_+Y": 695, "W_Parapet_-Y": 695,
        "W_PH_+X": 18, "W_PH_-X": 22, "W_PH_+Y": 22, "W_PH_-Y": 22,
        "W_Mech_+X": 135, "W_Mech_-X": 135, "W_Mech_+Y": 93, "W_Mech_-Y": 93}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fixture_test_model.py -v`
Expected: FAIL (no fixture file / no conftest fixture).

- [ ] **Step 3 (live): Capture**

Run: `.venv/Scripts/python.exe -m air_apparent.capture --pid <PID> tests/fixtures/test_model_snapshot.json`. Add `test_model_snap` to `tests/conftest.py`. If the group sizes differ from the expected dict, stop and report the difference to James before changing the test.

- [ ] **Step 4: Run the test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fixture_test_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/test_model_snapshot.json tests/test_fixture_test_model.py tests/conftest.py
git commit -m "test: captured Test Model snapshot fixture"
```

---

### Task 5: YAML schema version 2

**Files:**
- Modify: `src/air_apparent/models.py` (ExteriorSegment, CategorizationSettings, LevelRoles, Override, Equipment, Config)
- Modify: `src/air_apparent/config.py`
- Modify: `src/air_apparent/categorization/rules.py` (two-line shim: `cfg.overrides.get(name)` becomes `.category` so the old rules still run until Task 8)
- Modify: `templates/wind_inputs.yaml`, `examples/reference_sample.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces, in `models.py`:
  - `ExteriorSegment(id: str, along: str | float, start: str | float, end: str | float, outside: str, axis: str = "")`; `outside` in `{"+X","-X","+Y","-Y","none"}`; `axis` is `"x"`/`"y"` when `along` is numeric, else `""`.
  - `CategorizationSettings(plane_tolerance_ft: float = 0.1, range_tolerance_ft: float = 0.5, level_tolerance_ft: float = 0.05)`.
  - `LevelRoles(main_roof: str, parapet: tuple[str, ...], penthouse_body: tuple[str, ...], penthouse_parapet: tuple[str, ...], mechanical: str)`.
  - `Override(category: str, component: str = "", outside: str = "")`.
  - `Equipment.support_frames: tuple[str, ...] = ()` and `support_joints: tuple[str, ...] = ()` (both keyword, at least one non-empty, each exactly 4 names when present).
  - `Config.exterior_segments: tuple[ExteriorSegment, ...]`, `Config.categorization: CategorizationSettings`, `Config.levels: LevelRoles`, `Config.overrides: dict[str, Override]`; `SCHEMA_VERSION = 2`.
- Validation (field-path errors as today): `schema_version` must be 2, with the message `schema_version: 1 is no longer supported; add exterior_segments and levels (see docs/module_interfaces.md)` for 1; `exterior_segments` required, non-empty, unique ids, `outside` perpendicular to the line when the line axis is known, `axis` required iff `along` is numeric; `levels` required with the five keys; `categorization` optional with positive tolerances; `grade.roof_planes` becomes optional; `overrides` values may be a bare category string or a mapping with `category` and optional `component`, `outside`.
- Demo YAML content (both files): four segments `S: along A from "1" to "2" outside -Y`, `N: along B ... +Y`, `W: along "1" from A to B outside -X`, `E: along "2" ... +X`; `levels: {main_roof: ROOF, parapet: [PARAPET_TYP, PARAPET_PF], penthouse_body: [PH_ROOF], penthouse_parapet: [PH_PARAPET], mechanical: PARAPET_PF}`; `overrides: {INT_1: {category: excluded}}` in the reference sample.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py (append / adjust)
def test_schema_v2_segments_and_levels_load():
    ref = load_config(REFERENCE)
    assert ref.schema_version == 2 and len(ref.exterior_segments) == 4
    assert ref.exterior_segments[0].along == "A" and ref.exterior_segments[0].outside == "-Y"
    assert ref.levels.main_roof == "ROOF" and ref.levels.mechanical == "PARAPET_PF"
    assert ref.categorization.range_tolerance_ft == 0.5
    assert ref.overrides["INT_1"].category == "excluded"

def test_schema_v1_rejected_with_pointer():
    errs = _errors(_ref_text().replace("schema_version: 2", "schema_version: 1"))
    assert any("no longer supported" in e and "exterior_segments" in e for e in errs)

def test_segment_validation():
    text = _ref_text().replace('{id: S, along: A, from: "1", to: "2", outside: "-Y"}',
                               '{id: S, along: 0.0, from: "1", to: "2", outside: "-Y"}')
    assert any(e.startswith("exterior_segments[0].axis") for e in _errors(text))
    text = _ref_text().replace('outside: "-Y"}', 'outside: "-Y"}\n  - {id: S, along: B, from: "1", to: "2", outside: "+Y"}', 1)
    assert any("ids must be unique" in e for e in _errors(text))

def test_equipment_frames_or_joints():
    text = _ref_text().replace("support_joints: [CH01_J1, CH01_J2, CH01_J3, CH01_J4]", "support_frames: [B1, B2, B3]")
    assert any(e.startswith("equipment[0].support_frames") for e in _errors(text))
```

Adjust `test_branch_and_override_validation`'s override case to `overrides: {"7": {category: wall}}` expecting an `overrides.7` error.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement the dataclasses, the loader changes, the YAML edits and the two-line shim in the old `rules.py`**

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (old rules still run on the demo).

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/models.py src/air_apparent/config.py src/air_apparent/categorization/rules.py templates/wind_inputs.yaml examples/reference_sample.yaml tests/test_config.py
git commit -m "feat: YAML schema v2 with exterior segments, level roles and equipment support frames"
```

---

### Task 6: Demo and fake adapter carry stories, grids and group write results

**Files:**
- Modify: `src/air_apparent/demo.py`, `src/air_apparent/etabs/fake_adapter.py`, `src/air_apparent/etabs/adapter.py` (protocol only)
- Test: `tests/test_demo.py` (new)

**Interfaces:**
- Produces:
  - `demo.build_demo_snapshot(cfg)` fills `base_elevation_ft = cfg.grade_datum_model_elevation_ft`, stories bottom-up `L2 31.5`, `ROOF 62.0`, `PARAPET_TYP 67.0`, `PARAPET_PF 72.75`, `PH_ROOF 76.4167`, `PH_PARAPET 76.9167` (heights derived; names fixed), grid system `G1` at origin, grid lines `x: "1"@0, "2"@lx`, `y: "A"@0, "B"@ly`, labels for every object as `(name, story-of-top)`.
  - `GroupWriteResult(refused: tuple[tuple[str, int], ...], missing_after_readback: tuple[str, ...])` frozen dataclass in `adapter.py`; protocol `set_group(name, members) -> GroupWriteResult` and new `select_objects(refs: list[str]) -> None`.
  - `FakeAdapter.set_group` returns an empty `GroupWriteResult`; `FakeAdapter.select_objects` stores `self.selected_objects`; `FakeAdapter.read_groups(prefix="W_")` filters.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_demo.py
def test_demo_snapshot_has_stories_grids_and_labels(cfg, snap):
    assert [s.name for s in snap.stories] == ["L2", "ROOF", "PARAPET_TYP", "PARAPET_PF", "PH_ROOF", "PH_PARAPET"]
    assert snap.stories[1].elevation_ft == 62.0 and snap.stories[1].height_ft == pytest.approx(30.5)
    assert {(g.axis, g.label): g.ordinate_ft for g in snap.grid_lines} == {("x", "1"): 0.0, ("x", "2"): 1472.0, ("y", "A"): 0.0, ("y", "B"): 240.0}
    assert snap.labels["A:W_S_L2_1"] == ("W_S_L2_1", "L2")

def test_fake_adapter_group_api(snap):
    fa = FakeAdapter(snap)
    fa.groups["W_Wall_+X"] = ["A:W_S_L2_1"]
    assert fa.read_groups() == {"W_Wall_+X": ["A:W_S_L2_1"]}
    res = fa.set_group("W_Wall_+X", ["A:W_S_L2_2"])
    assert res.refused == () and fa.groups["W_Wall_+X"] == ["A:W_S_L2_2"]
    fa.select_objects(["A:W_S_L2_2"])
    assert fa.selected_objects == ["A:W_S_L2_2"]
```

- [ ] **Step 2: Run to verify failure** — Run: `.venv/Scripts/python.exe -m pytest tests/test_demo.py -v` — Expected: FAIL.

- [ ] **Step 3: Implement** — `demo.py` stories/grids/labels; `GroupWriteResult`; protocol methods; `FakeAdapter` methods. The existing `OLD_WALLS`/`USER_GROUP` demo groups stay (they must be invisible through `read_groups()`).

- [ ] **Step 4: Run the suite** — Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/demo.py src/air_apparent/etabs/fake_adapter.py src/air_apparent/etabs/adapter.py tests/test_demo.py
git commit -m "feat: demo snapshot with stories and grids; adapter group write result and object selection"
```

---

### Task 7: Segment resolution and shell placement

**Files:**
- Create: `src/air_apparent/categorization/segments.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Consumes: `ExteriorSegment`, `Penthouse`, `GridLine`, `CategorizationSettings`, `Diagnostic` from `models.py`.
- Produces:
  - `ResolvedSegment(id: str, axis: str, ordinate_ft: float, start_ft: float, end_ft: float, outside: str, component: str = "")` frozen.
  - `resolve_segments(segments: Sequence[ExteriorSegment], grid_lines: Sequence[GridLine]) -> tuple[list[ResolvedSegment], list[Diagnostic]]`. A string `along`/`start`/`end` resolves to the grid line with that label (any system); unknown label -> `error: grid_label_unknown` and the segment is dropped. A label used for `along` fixes the axis; `start`/`end` labels must lie on the perpendicular axis (else `error: grid_label_axis`). `start > end` is swapped. Overlapping ranges on the same axis and ordinate (within 1e-6) -> `error: segment_overlap` for both. A numeric `along` equal (within 1e-9) to the ordinate of a grid line whose label spells the same number -> `warning: numeric_along_matches_label` (Review Focus 1).
  - `penthouse_edges(ph: Penthouse) -> list[ResolvedSegment]`: ids `f"{ph.id}_W"` (x = x_min, outside -X, range y_min..y_max), `_E` (+X), `_S` (y = y_min, -Y, range x_min..x_max), `_N` (+Y); `component = ph.id`.
  - `place(axis: str, ordinate: float, lo: float, hi: float, candidates: Sequence[ResolvedSegment], settings: CategorizationSettings) -> tuple[ResolvedSegment | None, str]` where the status is `"placed"`, `"none"` or `"ambiguous"`. A candidate matches when `axis` equal, `abs(ordinate - c.ordinate_ft) <= plane_tolerance_ft`, and the midpoint `(lo+hi)/2` lies in `[c.start_ft - range_tolerance_ft, c.end_ft + range_tolerance_ft]`. Several matches: keep the one(s) with the largest overlap length between `[lo, hi]` and `[start, end]`; a unique maximum is `"placed"` (Review Focus 2), a tie is `"ambiguous"`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_segments.py
import pytest
from air_apparent.categorization.segments import penthouse_edges, place, resolve_segments
from air_apparent.models import CategorizationSettings, ExteriorSegment, GridLine, Penthouse

G = [GridLine("G1", "y", "J", 0.0), GridLine("G1", "y", "E", 238.0), GridLine("G1", "x", "28.5", 2.25), GridLine("G1", "x", "39", 421.75)]
S = CategorizationSettings()

def test_resolve_labels_and_numbers():
    segs, diags = resolve_segments([ExteriorSegment("J_E", "J", 241.667, "39", "-Y"),
                                    ExteriorSegment("SW_s", -11.0, "28.5", 25.5, "-Y", axis="y")], G)
    assert diags == [] and (segs[0].axis, segs[0].ordinate_ft, segs[0].start_ft, segs[0].end_ft) == ("y", 0.0, 241.667, 421.75)
    assert (segs[1].axis, segs[1].ordinate_ft, segs[1].start_ft) == ("y", -11.0, 2.25)

def test_unknown_label_and_overlap_and_numeric_label():
    segs, diags = resolve_segments([ExteriorSegment("a", "Q", 0, 1, "-Y"),
                                    ExteriorSegment("b", "J", 0, 100, "-Y"), ExteriorSegment("c", "J", 50, 150, "-Y"),
                                    ExteriorSegment("d", 39.0, "J", "E", "+X", axis="x")], G)
    codes = sorted(d.code for d in diags)
    assert codes == ["grid_label_unknown", "numeric_along_matches_label", "segment_overlap", "segment_overlap"]
    assert [s.id for s in segs] == ["d"]

def test_penthouse_edges():
    e = {s.id: s for s in penthouse_edges(Penthouse("PH1", 266.083, 301.333, 214.25, 238.0, 60.0, 15.0, 70.0, 25.0))}
    assert (e["PH1_N"].axis, e["PH1_N"].ordinate_ft, e["PH1_N"].outside, e["PH1_N"].component) == ("y", 238.0, "+Y", "PH1")
    assert (e["PH1_W"].start_ft, e["PH1_W"].end_ft) == (214.25, 238.0)

def test_place_tolerances_and_tie_break():
    segs, _ = resolve_segments([ExteriorSegment("J_W", "J", 25.5, 218.417, "-Y"), ExteriorSegment("J_E", "J", 241.667, "39", "-Y"),
                                ExteriorSegment("SW_e", 25.5, -11.0, "J", "+X", axis="x")], G)
    assert place("y", 0.05, 100.0, 112.0, segs, S)[1] == "placed"
    assert place("y", 0.3, 100.0, 112.0, segs, S)[1] == "none"          # plane tolerance 0.1
    assert place("y", 0.0, 219.0, 230.0, segs, S)[1] == "none"          # inside the bump-out gap
    # midpoint within 0.5 ft of the shared endpoint of two touching segments
    touching, _ = resolve_segments([ExteriorSegment("a", "J", 0.0, 100.0, "-Y"), ExteriorSegment("b", "J", 100.0, 200.0, "-Y")], G)
    seg, status = place("y", 0.0, 99.0, 101.8, touching, S)
    assert status == "placed" and seg.id == "b"
    assert place("y", 0.0, 99.0, 101.0, touching, S)[1] == "ambiguous"
```

- [ ] **Step 2: Run to verify failure** — Run: `.venv/Scripts/python.exe -m pytest tests/test_segments.py -v` — Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `segments.py`**

- [ ] **Step 4: Run tests** — Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/categorization/segments.py tests/test_segments.py
git commit -m "feat: resolve declared exterior segments against grid lines and place shells"
```

---

### Task 8: Rules R0 to R5 and R7 (rewrite `rules.py`)

**Files:**
- Modify: `src/air_apparent/categorization/rules.py` (full rewrite; the envelope code is deleted)
- Modify: `src/air_apparent/models.py` (`ObjectCategory`: rename `band` -> `level`, add `segment_id: str = ""`, `outside: str = ""`, `side: str = ""`)
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: Task 7 `resolve_segments`, `penthouse_edges`, `place`; Task 5 `Config.levels/categorization/overrides/exterior_segments`.
- Produces:
  - `ShellGeometry(ref: str, vertical: bool, axis_aligned: bool, axis: str, ordinate: float, lo: float, hi: float, zmin: float, zmax: float)` frozen; `shell_geometry(shell: Shell, settings: CategorizationSettings) -> ShellGeometry` (R0; collinear extra plan points tolerated within `plane_tolerance_ft`).
  - `story_bands(snap: ModelSnapshot) -> list[tuple[str, float, float]]` as `(name, bottom, top)` bottom-up, first bottom = `base_elevation_ft`.
  - `level_of_top(zmax: float, bands, settings) -> str | None` (R1; `None` above the top story).
  - `element_type(level: str, levels: LevelRoles, bands) -> str | None` returning `"wall" | "parapet" | "penthouse_body" | "penthouse_parapet" | None` (R2).
  - `categorize_shells(cfg, snap) -> tuple[dict[str, ObjectCategory], list[Diagnostic]]` applying R0 to R5 with the shared-line precedence of spec 6 R3 and `overrides`; category constants as today (`MAIN_WALL`, `MAIN_PARAPET`, `PICTURE_FRAME_PARAPET`, `PENTHOUSE_BODY`, `PENTHOUSE_PARAPET`, `EXCLUDED`, `UNRESOLVED`, `STAIR_PROJECTION` by override only); `ObjectCategory.level`, `segment_id`, `outside`, `side`, `component`, `parapet_type`, `outward_normal` (vector from `outside` via `DIR_VECTORS`, `None` for excluded/unresolved) populated.
  - `categorize_frames(cfg, snap) -> tuple[dict[str, ObjectCategory], list[Diagnostic]]` (R7): categories `EQUIPMENT_SUPPORT_FRAME = "equipment_support_frame"` (new constant) with `component = equipment id` and `direction` recorded in `reason`; `PLATFORM_FRAME` with `component = platform id` and `side` = `"X"`/`"Y"`/`"XY"` axis set; joints in `support_joints` keep `EQUIPMENT_JOINT`; level check against `levels.mechanical` band using the frame's higher end z.
  - `categorize(cfg, snap) -> Categorization` is defined in Task 9; this task exposes the pieces.

- [ ] **Step 1: Write failing tests** (hand-built snapshots; helper `_wall(name, axis, ordinate, lo, hi, z0, z1)` builds a 4-corner vertical `Shell`; helper `_snap(stories=..., shells=..., grid_lines=G)`; helper `_cfg(segments=..., levels=..., penthouses=..., parapets=..., overrides=...)` built with `dataclasses.replace` on the reference config)

```python
def test_r0_geometry_collinear_and_sloped():
    kinked = Shell("K", ((2895, -132, 0), (2760, -132, 0), (2761, -132, 0), (2761, -132, 10), (2895, -132, 10)))
    g = shell_geometry(kinked, S)
    assert g.vertical and g.axis == "y" and g.ordinate == -132 and (g.lo, g.hi) == (2760, 2895)
    assert not shell_geometry(Shell("F", ((0, 0, 5), (1, 0, 5), (1, 1, 5), (0, 1, 5))), S).vertical
    assert not shell_geometry(Shell("D", ((0, 0, 0), (1, 1, 0), (1, 1, 5), (0, 0, 5))), S).axis_aligned

def test_r1_level_boundaries():   # Review Focus 3
    bands = [("L2", -0.833, 31.5), ("R", 31.5, 60.083), ("Parapet_1", 60.083, 65.083)]
    assert level_of_top(31.5, bands, S) == "L2" and level_of_top(31.52, bands, S) == "L2"
    assert level_of_top(31.6, bands, S) == "R" and level_of_top(60.083, bands, S) == "R"
    assert level_of_top(65.2, bands, S) is None

def test_r2_element_type_from_levels():
    assert element_type("L2", LV, BANDS) == "wall" and element_type("R", LV, BANDS) == "wall"
    assert element_type("Mech", LV, BANDS) == "parapet" and element_type("Parapet_2", LV, BANDS) == "penthouse_parapet"
    assert element_type("Attic", LV, BANDS) is None

def test_r3_placement_outcomes():
    # a J wall (placed), a wall on the cut line (declared_unexposed), an interior wall (no_exterior_segment),
    # a shell straddling an undeclared range beyond tolerance (extent_exceeds_segment)
    ...
    assert cats["A:J1"].category == "main_wall" and cats["A:J1"].segment_id == "J_W" and cats["A:J1"].outside == "-Y"
    assert cats["A:CUT"].category == "excluded" and any(d.code == "declared_unexposed" and d.object_ref == "A:CUT" for d in diags)
    assert cats["A:INT"].category == "unresolved" and any(d.code == "no_exterior_segment" and "x=" in d.message for d in diags)

def test_r3_shared_line_split_body_and_penthouse_parapet():
    # grid E shared by segment E_E and PH1_N; a body piece R..Mech with another piece Mech..Penthouse above
    assert cats["A:BODY_LO"].category == "penthouse_body" and cats["A:BODY_LO"].component == "PH1"
    # a true main parapet R..Parapet_1 on E_E away from PH1 stays a main parapet
    assert cats["A:PAR"].category == "main_roof_parapet"
    # PH parapet band shell on PH1_N
    assert cats["A:PHP"].category == "penthouse_parapet" and cats["A:PHP"].outside == "+Y"
    # a body piece R..Mech on PH1_W (no exterior segment there) is a body with the warning
    assert cats["A:BODY_W"].category == "penthouse_body"
    assert any(d.code == "body_below_penthouse_level" and d.object_ref == "A:BODY_W" for d in diags)

def test_r5_parapet_type_from_stack():
    # three strips on J_W: R..Parapet_1, Parapet_1..68.7, 68.7..Mech -> all picture_frame; a lone R..Parapet_1 strip -> main_roof
    assert cats["A:STRIP1"].category == "picture_frame_parapet" and cats["A:STRIP1"].parapet_type == "PF"
    assert cats["A:LONE"].category == "main_roof_parapet" and cats["A:LONE"].parapet_type == "TYP"
    assert any(d.code == "parapet_type_unmatched" for d in diags_for_unmatched)

def test_override_wins():
    assert cats["A:CROSS"].category == "penthouse_body" and cats["A:CROSS"].outside == "+Y" and cats["A:CROSS"].component == "PH2"

def test_r7_frames():
    assert cats["F:B1"].category == "equipment_support_frame" and cats["F:P1"].category == "mechanical_platform_frame"
    assert any(d.code == "missing_support_frame" for d in diags) and any(d.code == "frame_level_unexpected" for d in diags)
```

- [ ] **Step 2: Run to verify failure** — Run: `.venv/Scripts/python.exe -m pytest tests/test_rules.py -v` — Expected: ImportError on new names.

- [ ] **Step 3: Rewrite `rules.py`; rename `ObjectCategory.band` to `level` and fix the two readers (`groups.py` old code is replaced in Task 9; for this commit, update its `oc.band` references to `oc.level` so the suite stays green)**

- [ ] **Step 4: Run the suite** — Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: new tests pass; old `tests/test_categorization.py` tests that assert envelope behaviour now fail. Delete those tests in this commit (`test_stray_object_does_not_redefine_envelope`, `test_unsupported_layout_detected`, `test_crossing_shell_reported_for_subdivision`, `test_etabs_dimension_discrepancy_reported`'s envelope assertion); they are replaced in Task 9.

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/categorization/rules.py src/air_apparent/categorization/groups.py src/air_apparent/models.py tests/test_rules.py tests/test_categorization.py
git commit -m "feat: rule-based shell and frame categorization from story bands and declared segments"
```

---

### Task 9: Pattern groups, fine groups, comparison, `categorize()`

**Files:**
- Modify: `src/air_apparent/categorization/groups.py` (rewrite), `src/air_apparent/categorization/__init__.py`, `src/air_apparent/models.py` (`GroupSpec.band` -> `level`, add `side: str = ""`; `Categorization` gains `pattern_groups: dict[str, list[str]]`, `comparison: list[GroupComparison]`; new `GroupComparison`; `PATTERN_GROUP_NAMES`)
- Modify: `src/air_apparent/reporting.py` (`group_table` uses `level`/`side`)
- Test: `tests/test_categorization.py` (rewrite), `tests/test_pattern_groups.py`

**Interfaces:**
- Consumes: Task 8 `categorize_shells`, `categorize_frames`; Task 7 resolution for `derived_dims`.
- Produces:
  - `models.PATTERN_GROUP_NAMES: tuple[str, ...]` (the sixteen, in the order listed in Global Constraints).
  - `models.GroupComparison(name: str, in_model: int, by_rules: int, missing_from_rules: tuple[str, ...], extra_in_rules: tuple[str, ...])`.
  - `groups.face_role(outside: str, direction: str) -> str` (`"WINDWARD" | "LEEWARD" | "SIDE"`), replacing the vector version.
  - `groups.build_pattern_groups(objects: dict[str, ObjectCategory]) -> dict[str, list[str]]` (R6, R7): walls and all parapets in all four of their family; penthouse bodies in the three directions where `face_role != "LEEWARD"`; equipment frames in all four `W_Mech_*`; platform frames by axis; refs sorted; all sixteen keys present.
  - `groups.build_group_specs(cfg, snap, objects) -> list[GroupSpec]` (R8): one spec per (category, direction, role, side, level, parapet type, branch) with `name = fine_group_name(...)` (tokens joined by `_`, no prefix, no numbers that are pressures), `pattern` per R6 (`W_Wall_d`, `W_Parapet_d`, `W_PH_d`, `W_Mech_<axis>` for frames), `result_id` as today's rules (wall WW/LW/SIDE by role and branch; parapet WW/LW by role, side faces `WALL_SIDE_<branch>`; penthouse windward `PH_<id>_NET`, side `WALL_SIDE_<branch>`), `assignment_sign` from `local3` versus `outward_normal` as today.
  - `groups.compare_groups(pattern_groups, existing: dict[str, list[str]]) -> list[GroupComparison]` (existing names matched case-insensitively).
  - `groups.detect_group_conflicts` unchanged. `reconcile_membership`, `PREFIX`, `UNRESOLVED_GROUP`, `STAIR_GROUP` removed from the package.
  - `rules.categorize(cfg, snap) -> Categorization` composing everything; `derived_dims` from the resolved segments' extent per axis (`X: PlanDims(x_extent, y_extent)`, `Y: PlanDims(y_extent, x_extent)`), `envelope` = that box; `dimension_discrepancy` warning kept.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pattern_groups.py
def test_face_role():
    assert face_role("-X", "+X") == "WINDWARD" and face_role("+X", "+X") == "LEEWARD" and face_role("-Y", "+X") == "SIDE"

def test_pattern_groups_from_objects():
    objs = {"A:W": ObjectCategory("A:W", "main_wall", "", level="L2", outside="-Y"),
            "A:P": ObjectCategory("A:P", "picture_frame_parapet", "", level="Mech", outside="-Y"),
            "A:B": ObjectCategory("A:B", "penthouse_body", "", level="Penthouse", outside="+X", component="PH2"),
            "F:E": ObjectCategory("F:E", "equipment_support_frame", "", component="CH1"),
            "F:P": ObjectCategory("F:P", "mechanical_platform_frame", "", component="PL1", side="X")}
    g = build_pattern_groups(objs)
    assert set(g) == set(PATTERN_GROUP_NAMES)
    assert all(g[f"W_Wall_{d}"] == ["A:W"] for d in DIRECTIONS) and all(g[f"W_Parapet_{d}"] == ["A:P"] for d in DIRECTIONS)
    assert g["W_PH_+X"] == [] and g["W_PH_-X"] == ["A:B"] and g["W_PH_+Y"] == ["A:B"]
    assert g["W_Mech_+Y"] == ["F:E"] and g["W_Mech_-X"] == ["F:E", "F:P"]

def test_compare_groups_case_insensitive():
    cmp = compare_groups({"W_Wall_+X": ["A:1", "A:2"]}, {"w_wall_+x": ["A:2", "A:3"]})
    assert cmp[0] == GroupComparison("W_Wall_+X", 2, 2, ("A:3",), ("A:1",))

# tests/test_categorization.py (rewrite)
def test_demo_fully_categorized(cfg, snap):
    c = categorize(cfg, snap)
    counts = Counter(o.category for o in c.objects.values())
    assert counts["main_wall"] == 40 and counts["main_roof_parapet"] == 16 and counts["picture_frame_parapet"] == 4
    assert counts["penthouse_body"] == 8 and counts["penthouse_parapet"] == 8
    assert counts["equipment_support_joint"] == 72 and counts["mechanical_platform_frame"] == 4
    assert "unresolved" not in counts and c.objects["A:INT_1"].category == "excluded"
    assert len(c.pattern_groups["W_Wall_+X"]) == 40 and len(c.pattern_groups["W_Parapet_+Y"]) == 28
    assert len(c.pattern_groups["W_PH_+X"]) == 6 and len(c.pattern_groups["W_Mech_+X"]) == 2
    assert c.derived_dims["X"].parallel_l == 1472.0 and not [d for d in c.diagnostics if d.level == "error"]

def test_fine_groups_stable_and_direction_specific(cfg, snap):
    names = {g.name for g in categorize(cfg, snap).groups}
    assert any(n.startswith("WALL_L2_XPOS_WINDWARD_W_MIN") for n in names)
    assert any(n.startswith("WALL_L2_XNEG_WINDWARD_E_MAX") for n in names)
    faster = replace(cfg, wind=replace(cfg.wind, basic_wind_speed_mph=150.0))
    assert {g.name for g in categorize(faster, snap).groups} == names

def test_comparison_against_existing_groups(cfg, snap):
    snap.groups["W_Wall_+X"] = ["A:W_S_L2_1", "A:NOT_THERE"]
    c = categorize(cfg, snap)
    row = next(r for r in c.comparison if r.name == "W_Wall_+X")
    assert row.in_model == 2 and row.by_rules == 40 and row.missing_from_rules == ("A:NOT_THERE",)
```

Keep `test_override_and_missing_objects` (override now a mapping), `test_missing_support_joint_and_frame_diagnostics`, `test_no_conflicts_within_direction`, and a dimension-discrepancy test using segment extent.

- [ ] **Step 2: Run to verify failure** — Expected: ImportError / AttributeError on new names.

- [ ] **Step 3: Implement `groups.py`, `categorize()`, model additions, `reporting.group_table` columns (`level`, `side` added; `band` removed)**

- [ ] **Step 4: Run the suite** — Run: `.venv/Scripts/python.exe -m pytest -q` — Expected: everything passes except `tests/test_workflow.py`, `tests/test_ui.py`, `tests/test_patterns.py` cases that reference `AA_PREVIEW_*`, `create_preview_groups` or PH side faces under `W_Wall`; those are fixed in Tasks 11 to 13. Mark them `xfail(strict=True, reason="task 11/12/13")` in this commit so the suite is green and the debt is visible.

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/categorization src/air_apparent/models.py src/air_apparent/reporting.py tests/test_categorization.py tests/test_pattern_groups.py tests/test_workflow.py tests/test_ui.py tests/test_patterns.py
git commit -m "feat: sixteen W_ pattern groups, fine groups and comparison with existing groups"
```

---

### Task 10: Test Model acceptance

**Files:**
- Create: `examples/test_model.yaml` (spec 5.4 verbatim for segments, penthouses, levels, parapet types; wind/pressure values copied from `reference_sample.yaml`; equipment and platforms derived in Step 1)
- Create: `tests/test_test_model_acceptance.py`

**Interfaces:**
- Consumes: Task 4 fixture, Task 9 `categorize`.

- [ ] **Step 1: Derive the equipment and platform lists from the fixture**

Write a throwaway script in the scratchpad (not committed) that loads the fixture, takes `W_Mech_+X ∩ W_Mech_+Y` (72 beams), clusters them into 18 groups of 4 by plan proximity, and lists the remaining `W_Mech_+X` frames (63) and `W_Mech_+Y` frames (21). Paste the names into `examples/test_model.yaml`: 18 `equipment` entries with `support_frames`, one platform `PL1` with `frames_x_wind` (63) and `frames_y_wind` (21). Add the four `overrides` for the PH2 cross walls: the shells whose plane is `y = 22.6` or `y = 215.417` ft between x 409.75 and 421.75 (two body, two parapet), with `outside` `+Y` and `-Y` respectively.

- [ ] **Step 2: Write the acceptance test**

```python
# tests/test_test_model_acceptance.py
EXPECTED = {**{f"W_Parapet_{d}": 695 for d in DIRECTIONS}, "W_PH_+X": 18, "W_PH_-X": 22, "W_PH_+Y": 22, "W_PH_-Y": 22,
            **{f"W_Wall_{d}": 568 for d in DIRECTIONS}, "W_Mech_+X": 135, "W_Mech_-X": 135, "W_Mech_+Y": 93, "W_Mech_-Y": 93}

def test_rules_reproduce_engineer_groups(test_model_snap):
    cfg = load_config(ROOT / "examples" / "test_model.yaml")
    c = categorize(cfg, test_model_snap)
    assert not [d for d in c.diagnostics if d.level == "error"], [d.message for d in c.diagnostics if d.level == "error"]
    assert {k: len(v) for k, v in c.pattern_groups.items()} == EXPECTED
    for row in c.comparison:
        if row.name == "W_Wall_+Y":
            assert row.missing_from_rules == () and len(row.extra_in_rules) == 3
            assert all(test_model_snap.labels[r][0] in {"W2029", "W2032", "W2046"} for r in row.extra_in_rules)
        else:
            assert row.missing_from_rules == () and row.extra_in_rules == (), row

def test_no_shell_silently_dropped(test_model_snap):
    cfg = load_config(ROOT / "examples" / "test_model.yaml")
    c = categorize(cfg, test_model_snap)
    unresolved = [o for o in c.objects.values() if o.category == "unresolved"]
    assert unresolved == []
    excluded_cut = [o for o in c.objects.values() if o.category == "excluded" and o.segment_id == "W_cut"]
    assert len(excluded_cut) == 16
```

- [ ] **Step 3: Run it**

Run: `.venv/Scripts/python.exe -m pytest tests/test_test_model_acceptance.py -v`
Expected: PASS. On any mismatch, stop: print the differing refs with their labels, planes and z-ranges, and report to James; do not widen tolerances or add exceptions without his agreement (spec 9).

- [ ] **Step 4: Commit**

```bash
git add examples/test_model.yaml tests/test_test_model_acceptance.py
git commit -m "test: Test Model acceptance against the engineers' W_ groups"
```

---

### Task 11: Patterns accepts frames-only equipment and the new side-face patterns

**Files:**
- Modify: `src/air_apparent/patterns/assign.py`
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: `Equipment.support_frames/support_joints`, `GroupSpec.pattern` from Task 9.
- Produces: `mech_assignments` iterates only equipment with `support_joints`; `build_assignments` adds `warning: equipment_loads_deferred` per equipment that has frames but no joints; `force_conservation` runs only over equipment with joints. No other change.

- [ ] **Step 1: Un-xfail and rewrite the affected tests**

`test_side_pressures_under_wall_pattern_and_ph_not_duplicated` becomes `test_side_faces_follow_their_family_pattern`: penthouse side shells (`A:PH1_N`, `A:PH1_S` for +X) carry `W_PH_+X` with `WALL_SIDE_MIN`; parapet side shells carry `W_Parapet_+X`; windward body faces `{"A:PH1_W", "A:PH2_W"}` carry `PH_*_NET` under `W_PH_+X`; no `W_Wall_*` assignment targets a parapet or penthouse shell. Add:

```python
def test_frames_only_equipment_is_deferred(cfg, snap):
    cfg2 = replace(cfg, equipment=(replace(cfg.equipment[0], support_joints=(), support_frames=("PL1_A", "PL1_B", "PL1_C", "PL1_D")),) + cfg.equipment[1:])
    plan = build_plan(cfg2, snap, categorize(cfg2, snap), calculate_pressures(cfg2))
    assert any(d.code == "equipment_loads_deferred" and "CHILLER01" in d.message for d in plan.diagnostics)
    assert not [d for d in plan.diagnostics if d.code == "force_conservation"]
    assert len([a for a in plan.assignments if a.pattern == "W_Mech_X" and a.kind == "joint_force"]) == 68
```

- [ ] **Step 2: Run to verify failure** — Expected: the rewritten tests FAIL.

- [ ] **Step 3: Implement** — [ ] **Step 4: Run the suite** — Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/patterns/assign.py tests/test_patterns.py
git commit -m "feat: patterns tolerate frames-only equipment and route side faces to their family pattern"
```

---

### Task 12: Group write-back and workflow gating

**Files:**
- Modify: `src/air_apparent/etabs/adapter.py` (`ComEtabsAdapter.set_group`, `select_objects`, `select_group`)
- Modify: `src/air_apparent/workflow.py`
- Test: `tests/test_workflow.py` (rewrite the xfailed tests), `tests/test_etabs_adapter.py` (fake-API test of `set_group`)

**Interfaces:**
- Produces:
  - `ComEtabsAdapter.set_group(name, members) -> GroupWriteResult` implementing spec 8.1 exactly: existence via `GroupDef.GetNameList` case-insensitively using the model's spelling thereafter (Review Focus 4); `GetGroup_1` to read colour and the thirteen flags; `Delete`; re-check the name list and raise `AdapterError("group {name} could not be emptied; it may still hold earlier members")` if still present; `SetGroup_1(name, colour, *flags)`; per-member `SetGroupAssign` by ref prefix (`A:`->`AreaObj`, `F:`->`FrameObj`, `P:`->`PointObj`) collecting non-zero codes; `GetAssignments` read-back to fill `missing_after_readback`.
  - `ComEtabsAdapter.select_objects(refs)`: `SelectObj.ClearSelection()` then `SetSelected(obj, True)` on the matching object API per ref, then `View.RefreshView(0, False)`.
  - `WindSession.write_pattern_groups() -> list[Diagnostic]`: requires `self.cats`; for each name in `PATTERN_GROUP_NAMES` calls `adapter.set_group(name, members)`; each refused member -> `error: group_assign_refused` with ref and code; each missing-after-readback -> `error: group_member_missing`; manifest `groups` = the sixteen names; `preview_valid = not errors`. Replaces `create_preview_groups`.
  - `WindSession.check_group_drift() -> list[Diagnostic]`: `adapter.read_groups("W_")` versus `cats.pattern_groups`; a difference -> `error: group_drift` per group naming the counts; sets `preview_valid = False` when any. Replaces `reconcile_groups`.
  - `WindSession.select_group(name)`: a pattern group name -> `check_group_drift()`; raise `AdapterError` if drift; else `adapter.select_group(name)`. A fine group name (in `cats.groups`) -> `adapter.select_objects(spec.members)`. Unknown -> `ValueError`.
  - `_apply` uses `check_group_drift()`; the `_name_conflicts` check no longer considers groups.
  - `_audit` unchanged.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_etabs_adapter.py (append)
def test_set_group_reuses_model_spelling_and_reads_back():   # Review Focus 4
    calls = []
    gd = SimpleNamespace(GetNameList=lambda: [1, ("w_wall_+x",), 0],
                         GetGroup_1=lambda n: [7] + [True] * 13 + [0],
                         Delete=lambda n: calls.append(("Delete", n)) or 0,
                         SetGroup_1=lambda n, *a: calls.append(("SetGroup_1", n, a[0])) or 0,
                         GetAssignments=lambda n: [1, (5,), ("A1",), 0])
    ao = SimpleNamespace(SetGroupAssign=lambda o, g: calls.append(("assign", o, g)) or (0 if o == "A1" else 3))
    res = _adapter_with_api(SimpleNamespace(GroupDef=gd, AreaObj=ao)).set_group("W_Wall_+X", ["A:A1", "A:A2"])
    assert ("Delete", "w_wall_+x") in calls and ("SetGroup_1", "w_wall_+x", 7) in calls
    assert res.refused == (("A:A2", 3),) and res.missing_after_readback == ()

# tests/test_workflow.py (replace xfailed tests)
def test_write_pattern_groups_and_apply(session):
    assert session.write_pattern_groups() == []
    assert set(session.adapter.read_groups()) == set(PATTERN_GROUP_NAMES)
    assert "OLD_WALLS" in session.adapter.groups and "USER_GROUP" in session.adapter.groups
    res = session.apply()
    assert res.ok and res.applied["patterns"] == 18 and res.applied["cases"] == 20

def test_drift_blocks_apply_and_select(session):
    session.write_pattern_groups()
    session.adapter.groups["W_Wall_+X"].append("A:INT_1")
    res = session.apply()
    assert not res.ok and any(d.code == "group_drift" for d in res.diagnostics)
    with pytest.raises(AdapterError, match="group_drift|drift"):
        session.select_group("W_Wall_+X")

def test_existing_w_group_is_replaced_not_conflicted(session):
    session.adapter.groups["W_Wall_+X"] = ["A:INT_1"]
    assert session.write_pattern_groups() == []
    assert "A:INT_1" not in session.adapter.groups["W_Wall_+X"]

def test_select_fine_group_selects_its_members(session):
    spec = session.cats.groups[0]
    session.select_group(spec.name)
    assert session.adapter.selected_objects == list(spec.members)
```

Keep `test_apply_requires_preview`, `test_reapply_is_idempotent`, `test_stale_assignments_cleared_when_plan_shrinks` (call `write_pattern_groups`), `test_locked_model_requires_explicit_unlock`, `test_partial_failure_reported_without_claiming_rollback`, `test_existing_unrelated_pattern_not_taken_over`, `test_audit_flags_aw_leftovers_without_deleting`, `test_yaml_reload_invalidates`, `test_etabs_dimension_source` (now asserts dims from segments), `test_exports`. Delete `test_manual_group_edit_blocks_apply`, `test_group_rebuild_removes_outdated_members_and_stale_groups`, `test_unrelated_group_name_conflict_detected`.

- [ ] **Step 2: Run to verify failure** — Expected: FAIL on missing methods.

- [ ] **Step 3: Implement adapter and workflow changes**

- [ ] **Step 4: Run the suite** — Expected: all pass except the `tests/test_ui.py` xfails.

- [ ] **Step 5 (live): Write the sixteen groups to the Test Model and read them back**

Script in the scratchpad: `WindSession`, `load_config("examples/test_model.yaml")`, `connect(connect_live(PID))`, `read_model()`, `categorize()`, `write_pattern_groups()`, then `check_group_drift()`. Expected: no diagnostics from either call; in ETABS, Select by Group `W_Wall_+X` highlights the perimeter walls. If `SetGroupAssign` on areas returns non-zero on this build, record the code in `docs/etabs_setup.md` and stop. Save the model only if James says so.

- [ ] **Step 6: Commit**

```bash
git add src/air_apparent/etabs/adapter.py src/air_apparent/workflow.py tests/test_workflow.py tests/test_etabs_adapter.py
git commit -m "feat: write W_ pattern groups with replace semantics and gate apply on group drift"
```

---

### Task 13: GUI and report

**Files:**
- Modify: `src/air_apparent/ui.py`, `src/air_apparent/reporting.py`
- Test: `tests/test_ui.py` (rewrite xfailed tests), `tests/test_workflow.py::test_exports`

**Interfaces:**
- Produces:
  - `ui.GROUP_COLUMNS = ("group", "category", "level", "side", "direction", "role", "result_id", "value", "pattern", "members", "sign")`.
  - `App.calculate()` inserts sixteen comparison rows first (`group` = pattern name, `category` = `"pattern"`, `value` = `f"{by_rules} by rules / {in_model} in model"`, `members` = `by_rules`, other cells empty), then the fine groups; the text pane lists `categorize` diagnostics instead of `Model envelope`.
  - Button "Create/Update preview groups" becomes "Write W_ groups" calling `write_pattern_groups`; status reports errors joined.
  - `App.connect()` calls `close()` on a previous adapter if it has one; `main()` registers `root.protocol("WM_DELETE_WINDOW", ...)` that closes the adapter then destroys the root.
  - `reporting.html_report` adds a "Pattern group comparison" table (name, by rules, in model, missing, extra) before the group table; `group_table` rows carry `level` and `side`.

- [ ] **Step 1: Rewrite the xfailed UI tests**

`test_select_after_first_calculate_creates_groups_and_selects_members`: selecting `W_Wall_+X` from the first rows writes the sixteen groups and selects it; `test_single_unresolved_row_exposes_classification_diagnostics` becomes `test_unresolved_shell_is_listed_in_text_not_rows`: remove the `S` face segment from the config (`replace(cfg, exterior_segments=...)`), recategorize, `calculate()`, assert `"no_exterior_segment" in messages and "(A:W_S_" in messages` and that no row has an empty `group`; `test_select_does_not_overwrite_unowned_group` becomes `test_select_detects_drift`. Add to `test_exports`: `assert "Pattern group comparison" in html`.

- [ ] **Step 2: Run to verify failure** — [ ] **Step 3: Implement** — [ ] **Step 4: Run the suite** — Expected: all pass, no xfails remain.

- [ ] **Step 5: Commit**

```bash
git add src/air_apparent/ui.py src/air_apparent/reporting.py tests/test_ui.py tests/test_workflow.py
git commit -m "feat: GUI shows pattern-group comparison and writes W_ groups; report gains comparison table"
```

---

### Task 14: Documentation, dead code, end-to-end live check

**Files:**
- Modify: `docs/module_interfaces.md` (categorization section, schema v2, workflow step 5, interface table), `docs/limitations.md` (envelope limitations replaced by "exterior faces must be declared"; cut lines; frames-only equipment deferred), `docs/user_guide.md` (YAML section 3: segments, levels, overrides; step 4 "Write W_ groups"), `docs/spec_categorization.md` (append "Implemented rules" pointing at the design), `docs/etabs_setup.md` (checklist items 3 and 7 done), `README.md` (layout table rows for `segments.py`, `tables.py`, `capture.py`), `examples/README.md` (test_model.yaml)
- Modify: `src/air_apparent/categorization/rules.py` / `groups.py` (remove any leftover envelope helpers), `tests/conftest.py`

- [ ] **Step 1: Grep for dead references**

Run: `grep -rn "AA_PREVIEW\|reconcile_membership\|_envelope\|EDGE_COVERAGE\|roof_planes\[0\]\|support_joints" src tests docs README.md`
Expected: only `support_joints` in config/models/patterns/demo and no `AA_PREVIEW`/`reconcile_membership`/`_envelope`/`EDGE_COVERAGE`; fix any hit.

- [ ] **Step 2: Update the documents listed above**

- [ ] **Step 3: Full verification**

Run: `.venv/Scripts/ruff.exe check . && .venv/Scripts/python.exe -m pytest -q`
Expected: clean; test count >= 90; no xfail/skip.

- [ ] **Step 4 (live): End-to-end on the Test Model**

Launch `.venv/Scripts/python.exe -m air_apparent.ui examples/test_model.yaml`, Connect ETABS with the pid, Inspect, Calculate, Write W_ groups, select `W_Parapet_+Y` and `W_PH_-X` in ETABS and confirm visually, Export report to the scratchpad and confirm the comparison table shows 15 exact rows and the `W_Wall_+Y` row with 3 extra. Record in `docs/etabs_setup.md`.

- [ ] **Step 5: Commit**

```bash
git add docs README.md examples/README.md src tests
git commit -m "docs: categorization by declared segments; retire envelope rules and preview groups"
```
