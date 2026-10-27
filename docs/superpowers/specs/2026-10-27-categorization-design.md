# Categorization module design: rule-based grouping from story lines, grid lines and declared exterior segments

Date: 2026-10-27. Status: draft for approval (revised after builder check). Supersedes the
envelope-based rules in `src/air_apparent/categorization/rules.py`.

## 1. Intent

The tool must look at the ETABS model it is connected to and decide, for every shell and every
configured frame, which wind-load group it belongs to. Today it does this with a geometric
"rectangular envelope" guess that cannot see grids or stories and that fails on the real Test Model
(bump-outs, a cut line, parapets sliced at non-story elevations). The engineers at
Forell/Elsesser already do this by hand in ETABS, and their result is recorded in the model as
sixteen groups named `W_Wall_±X/±Y`, `W_Parapet_±X/±Y`, `W_PH_±X/±Y` and `W_Mech_±X/±Y`.

The new module reproduces those sixteen groups from explicit, inspectable rules whose inputs are:

- the story lines of the connected model, read through the ETABS Story API;
- the grid lines of the connected model, read through the interactive database tables;
- shell and frame geometry, read in bulk through the object APIs;
- a YAML declaration of the building's exterior wall segments and penthouse footprints.

The engineers' existing `W_*` groups in `examples/Test Model.EDB` are the acceptance test: the
rules must reproduce them, with the exceptions listed in section 9.

## 2. Goals, non-goals, anti-goals

**Goals**

1. Read stories, grid lines, shells, frames, points, labels and `W_*` group membership from a
   running ETABS instance, into the shared `ModelSnapshot`.
2. Categorize every vertical shell by level, element type, face and role for each wind direction,
   using rules that an engineer can read and predict.
3. Produce the sixteen `W_*` group memberships and write them back to ETABS (replace semantics).
4. Report, per group, how the tool's membership compares with whatever `W_*` groups already exist
   in the model.
5. Reproduce the Test Model's groups exactly for parapets, penthouses and mechanical frames, and
   for walls up to the one documented model inconsistency (section 9).

**Non-goals (this project)**

- Pressure values and load assignment. The Patterns module changes only as far as needed to keep
  working with the schema v2 equipment fields (section 5.3); everything else is recorded as a
  follow-up in section 10.
- Writing the finer five-distinction groups to ETABS. They remain internal `GroupSpec`s that the
  Patterns module and the report consume. James decided: only the sixteen `W_*` groups are written.
- Automatic outline tracing. Exterior faces are declared, not inferred. James chose this path.
- An E2K/`$et` text reader. Offline testing uses a snapshot captured from the live model.
- Non-rectangular, rotated or multiple grid systems beyond reporting them.

**Anti-goals** (would make this a failure even if it technically works)

- Silently giving a shell no load. Every vertical shell ends in a group, in a declared exclusion,
  or in a diagnostic that names it and says why.
- Trusting a shell's ETABS story label or local axis 3 for anything. Both are known to be unreliable
  in the Test Model (every upper object is labelled `R`; local axes are arbitrary).
- Touching any group that does not start with `W_`.

## 3. Decisions already made

| Decision | By | Note |
| --- | --- | --- |
| Rules are driven by story lines and grid lines | James | grid lines are a convenience for naming and declaring, not a requirement |
| Stories come from the Story API; grid lines from the interactive tables | James | `cGridSys.GetGridSysCartesian_1` exists in the docs but was not chosen; the reason was not stated and the builder does not revisit it |
| Exterior wall faces are declared in YAML as segments, not inferred | James | "declare the exterior segments path" |
| Only `W_*` groups are read, compared and written | James | all other groups in the sample model are stale artifacts |
| Write back exactly the sixteen per-pattern `W_*` groups | James | not the finer groups |
| Group write-back follows the `objects_group` sequence in CSI Model Assistant | James (pointed to it) | section 8.1 |
| Level = story band containing the shell's top edge | Claude, confirmed by data | ETABS's own association convention; handles parapet strips cut at non-story elevations |
| Element type follows from level | Claude, confirmed by data | section 6 |
| YAML stays in feet; the adapter sets present units to kip-ft before reading | Claude | consistent with the rest of the tool; the model itself is in inches |
| Equipment gains `support_frames` for grouping; `support_joints` stays optional so Patterns keeps working | Claude | the sample model applies equipment loads as frame point loads at beam ends; `W_Mech` groups contain beams only; load application moves to the Patterns follow-up |
| Offline fixture = JSON snapshot captured once from the live Test Model | Claude | avoids a second parser of ETABS data |
| The three 6-in slivers at the west end of grid J are declared as a segment | Claude | they are exterior in the full building; the model loads them in three of four directions, which is the model's inconsistency, not the rule's |
| A segment may be declared `outside: none` to mark a face as deliberately unexposed | Claude | the grid 28.5 cut line; keeps the diagnostics clean |

## 4. Reading the connected model (phase 1)

This is the first deliverable and is independently testable: connect to the Test Model and dump
stories and grid lines that match the `$et` export.

### 4.1 Connection and units

Unchanged: `connect_live(pid)` attaches via `ETABSv1.Helper.GetObjectProcess`. On connect the
adapter records the present units, sets `kip_ft_F` (value 4), and restores them on `close()`. All
API lengths are therefore feet. The GUI must call `close()` on disconnect/exit (today it does not).

### 4.2 Stories

`SapModel.Story.GetStories_2()` returns, in comtypes order:
`(BaseElevation, NumberStories, StoryNames, StoryElevations, StoryHeights, IsMasterStory,
SimilarToStory, SpliceAbove, SpliceHeight, Color, ret)`. Names are top-down.

Snapshot representation:

```python
@dataclass(frozen=True)
class Story:
    name: str
    elevation_ft: float      # top of the story
    height_ft: float
    is_master: bool = True
    similar_to: str = ""
    diaphragm: str | None = None        # unchanged, still unpopulated live
    reference_joint: str | None = None  # unchanged

ModelSnapshot.base_elevation_ft: float
ModelSnapshot.stories: list[Story]     # bottom-up order after reading
```

Derived, not stored: the **story bands**, one per story, `(bottom, top] = (elevation of the story
below or base, elevation of this story]`, named after the story.

Test Model expectation (from the `$et`): base -0.833 ft; L2 31.5; R 60.083; Parapet_1 65.083;
Mech 70.708; Penthouse 75.167; Parapet_2 76.917.

### 4.3 Grid lines

Through `SapModel.DatabaseTables`:

1. `GetAvailableTables()` -> `(NumberTables, TableKey[], TableName[], ImportType[], ret)`.
   Choose the table whose name contains both "Grid" and "Line" (case-insensitive). The exact key is
   not documented; the implementation discovers it and records it in an `info` diagnostic. If none
   or more than one matches, raise `AdapterError` listing the candidates.
2. `GetAllFieldsInTable(key)` -> field keys, names, descriptions, `UnitsString` per field, and
   importability. Columns are mapped by name, not position, and the ordinate column's
   `UnitsString` decides the unit conversion (section 4.3.1).
3. `GetTableForDisplayArray(key, [""], "", ...)` -> `(FieldKeyList, TableVersion,
   FieldsKeysIncluded, NumberRecords, TableData, ret)`. `TableData` is a flat string array, row by
   row, `len(FieldsKeysIncluded)` cells per row.

Columns to extract (the builder confirms the exact names against the live table): grid system
name, grid system type, line direction (X or Y for Cartesian), line ID, ordinate, visibility, and
origin X/Y plus rotation of the system if present in this table or in a sibling "Grid Systems"
table.

Snapshot representation:

```python
@dataclass(frozen=True)
class GridSystem:
    name: str
    kind: str            # "Cartesian" | other
    origin_x_ft: float
    origin_y_ft: float
    rotation_deg: float

@dataclass(frozen=True)
class GridLine:
    system: str
    axis: str            # "x" for a line of constant X (labels 28..39), "y" for constant Y (J..E)
    label: str
    ordinate_ft: float   # in global coordinates (origin and rotation applied)

ModelSnapshot.grid_systems: list[GridSystem]
ModelSnapshot.grid_lines: list[GridLine]
```

#### 4.3.1 Units of table values

The ordinate field's `UnitsString` from `GetAllFieldsInTable` is authoritative: "in" divides by
12, "ft" passes through, "mm"/"m" convert, anything else raises `AdapterError` naming the string.
Only if the string is empty does the reader fall back to a plausibility check against
`PointObj.GetAllPoints`: the X-ordinate span must lie within 0.9 to 1.1 of the point X span, or
within 2% of 12 times it (inches), else `AdapterError`. The builder confirms the live behaviour once
and records it in `docs/etabs_setup.md`.

Only Cartesian systems with zero rotation are used by the rules. Others are kept in the snapshot
and reported as `warning: grid_system_unsupported`.

Test Model expectation: one system `G1`; X lines 28, 28.5, 29, 30 ... 39 at 0, 2.25, 3.0, 43.75,
85.75, ... 421.75 ft; Y lines J, H, G, F, E at 0, 59, 119, 179, 238 ft.

### 4.4 Shells, frames, points, labels

Replace the per-object loops with bulk calls:

- `AreaObj.GetAllAreas()` -> names, design orientation, and for each area its boundary point names
  and X/Y/Z coordinates (`PointDelimiter` marks the last point index of each area). This gives
  `Shell.corners` directly. `GetTransformationMatrix` is no longer needed for categorization; keep
  `local3` populated (one call per shell, or lazily) only because the Patterns sign conversion
  still reads it.
- `FrameObj.GetAllFrames()` -> names, section, story, end point names and coordinates.
- `PointObj.GetAllPoints()` -> names and coordinates.
- `AreaObj.GetLabelNameList()`, `FrameObj.GetLabelNameList()`, `PointObj.GetLabelNameList()` ->
  unique name to `(label, story)`. Stored as `ModelSnapshot.labels: dict[str, tuple[str, str]]`
  keyed by object ref (`A:<name>`, `F:<name>`, `P:<name>`). Used only for reporting and for matching
  the `$et` when debugging; never for rules.

### 4.5 Groups

`GroupDef.GetNameList()`, then `GetAssignments(name)` only for names starting with `W_`.
`ObjectType` codes: 1 point, 2 frame, 5 area (others ignored). Stored in
`ModelSnapshot.groups: dict[str, list[str]]` as today, restricted to `W_*`.

### 4.6 Read-back fixes in the same adapter

Yinchen's commit `05cf210` already corrected `read_cases` and `read_combinations`. The remaining
confirmed index bugs in `read_assignments` are corrected here: `PointObj.GetLoadForce` returns F1,
F2, M3 at tuple positions 5, 6 and 10 (code uses 6, 7, 11); `FrameObj.GetLoadDistributed` returns
Dir at 5 (code uses 6). The built-in group is `All`, not `ALL`; the builder checks case sensitivity
live.

### 4.7 Fake adapter, demo, capture

- `FakeAdapter` and `demo.build_demo_snapshot` gain stories with heights, a base elevation, one
  Cartesian grid system and grid lines at the demo building's four faces, plus the demo YAML gains
  the matching four exterior segments.
- A capture entry point (`python -m air_apparent.capture --pid N out.json`) serialises a live
  `ModelSnapshot` to JSON. The Test Model capture becomes `tests/fixtures/test_model_snapshot.json`
  and is the fixture for every rule test in section 9. The JSON schema is the dataclasses' fields;
  a loader `ModelSnapshot.from_json` is part of the deliverable.

### 4.8 Phase 1 acceptance

Connect to the Test Model (new seven-story version), read, and print stories and grid lines. They
must match section 4.2 and 4.3 expectations to 0.01 ft. The shell count is checked against
`AreaObj.Count()` (the API reports unique objects; the `$et`'s 1425 assignment lines include
label-per-story duplicates).

## 5. YAML schema additions (schema_version 2)

### 5.1 Exterior segments and categorization settings

```yaml
schema_version: 2

exterior_segments:
  # Every stretch of exterior wall of the main building. A wall-band shell matching no segment is
  # reported, never silently unloaded. along / from / to accept a grid label (string) or a number
  # in feet; a grid label resolves against the connected model's grid lines and an unknown label is
  # a config error at read time. axis is required only when along is a number.
  - {id: J_W, along: J, from: 25.5, to: 218.417, outside: "-Y"}
  # outside: none declares a face that is deliberately not exposed (a cut line, an expansion joint).
  - {id: W_cut, along: "28.5", from: J, to: E, outside: none}

categorization:
  plane_tolerance_ft: 0.1      # shell plane vs segment ordinate; must separate grids 28.5 and 29
  range_tolerance_ft: 0.5      # shell midpoint vs segment range
  level_tolerance_ft: 0.05     # shell top vs story elevation

levels:
  main_roof: R                 # the story whose top is the main roof; bands at or below are walls
  parapet: [Parapet_1, Mech]
  penthouse_body: [Penthouse]
  penthouse_parapet: [Parapet_2]
  mechanical: Mech             # band in which W_Mech frames are expected
```

Rules for the declaration:

- `from`/`to` are along the perpendicular axis. `outside` must be perpendicular to the line, or
  `none`. Segment ids are unique; they are the "side relative to centre" names in group specs.
- Two segments on the same line may not have overlapping ranges (config error).
- `plan_dimensions_source: etabs` derives L and B from the declared segments' overall extent
  (max minus min ordinate per axis, `outside: none` segments included), not from a shell envelope.
- `story_bands` (pressure evaluation heights) stay as engineering input. Categorization validates
  that every `story_bands[].id` names a model story and warns on elevation mismatch > 0.1 ft.
- `overrides` entries become mappings; the old bare-string form (`name: category`) is still
  accepted and means "category only":

```yaml
overrides:
  "<unique name>": {category: penthouse_body, component: PH2, outside: "+Y"}
```

### 5.2 Penthouses

Unchanged shape. A penthouse is a rectangle in plan; its four edges carry outward normals. Faces
inside a footprint that the engineers nevertheless load (the Test Model's east strip has two cross
walls) are placed with `overrides`.

### 5.3 Equipment and platforms

```yaml
equipment:
  - id: CHILLER01
    support_frames: [B12, B13, B22, B23]   # existing beams; members of all four W_Mech groups
    support_joints: [...]                  # optional; kept so Patterns can still emit joint loads
platforms:
  - id: PL1
    frames_x_wind: [...]                   # members of W_Mech_+X and W_Mech_-X
    frames_y_wind: [...]                   # members of W_Mech_+Y and W_Mech_-Y
```

Patterns in this project: `mech_assignments` emits joint forces only when `support_joints` is
present; equipment with frames and no joints produces a `warning: equipment_loads_deferred` and no
assignments, and the `force_conservation` check runs only over equipment that has joints. Applying
equipment loads as frame point loads is the section 10 follow-up. Existing configs (`support_joints`
only) keep working; `schema_version: 1` files are rejected with a message naming the new fields.

### 5.4 Test Model declaration (complete)

Feet, three decimals. Grid labels in quotes where numeric-looking. This is the file
`examples/test_model.yaml` uses; every non-categorization value in that file (wind inputs,
pressure bands, equipment and platform dimensions, story shears) is copied from
`examples/reference_sample.yaml` because the file is a test fixture, not the project's configuration.

```yaml
exterior_segments:
  - {id: J_W,     along: J,       from: 25.5,    to: 218.417, outside: "-Y"}
  - {id: J_E,     along: J,       from: 241.667, to: "39",    outside: "-Y"}
  - {id: J_sliver, along: J,      from: 1.75,    to: 2.25,    outside: "-Y"}   # 6 in west of SW bump-out
  - {id: E_W,     along: E,       from: 25.5,    to: 218.417, outside: "+Y"}
  - {id: E_E,     along: E,       from: 241.667, to: "39",    outside: "+Y"}
  - {id: G39,     along: "39",    from: J,       to: E,       outside: "+X"}
  - {id: W_cut,   along: "28.5",  from: J,       to: E,       outside: none}   # building continues west
  # four 11 ft bump-outs; x 2.25-25.5 and 218.417-241.667; beyond J (y -11) and beyond E (y 249)
  - {id: SW_s, axis: y, along: -11.0,   from: "28.5",  to: 25.5,    outside: "-Y"}
  - {id: SW_w,         along: "28.5",   from: -11.0,   to: J,       outside: "-X"}
  - {id: SW_e, axis: x, along: 25.5,    from: -11.0,   to: J,       outside: "+X"}
  - {id: SM_s, axis: y, along: -11.0,   from: 218.417, to: 241.667, outside: "-Y"}
  - {id: SM_w, axis: x, along: 218.417, from: -11.0,   to: J,       outside: "-X"}
  - {id: SM_e, axis: x, along: 241.667, from: -11.0,   to: J,       outside: "+X"}
  - {id: NW_n, axis: y, along: 249.0,   from: "28.5",  to: 25.5,    outside: "+Y"}
  - {id: NW_w,         along: "28.5",   from: E,       to: 249.0,   outside: "-X"}
  - {id: NW_e, axis: x, along: 25.5,    from: E,       to: 249.0,   outside: "+X"}
  - {id: NM_n, axis: y, along: 249.0,   from: 218.417, to: 241.667, outside: "+Y"}
  - {id: NM_w, axis: x, along: 218.417, from: E,       to: 249.0,   outside: "-X"}
  - {id: NM_e, axis: x, along: 241.667, from: E,       to: 249.0,   outside: "+X"}

penthouses:
  - id: PH1
    plan_ft: {x_min: 266.083, x_max: 301.333, y_min: 214.25, y_max: 238.0}
  - id: PH2       # east strip along grid 39
    plan_ft: {x_min: 410.083, x_max: 421.75, y_min: 0.0, y_max: 238.0}

overrides:
  # PH2's internal cross walls at y 22.6 ft (outside +Y) and y 215.417 ft (outside -Y), x 409.75-421.75:
  # one body shell and one parapet shell each; unique names taken from the capture.
```

Parapet types for the fixture: typical top 65.917 ft above the -0.833 ft grade datum (stack top
at Parapet_1, 65.083 model), picture frame 71.542 (Mech, 70.708), penthouse 77.75 (Parapet_2,
76.917). Equipment: the 72 beams that carry point loads in the model, partitioned into 18 entries
of 4 by plan proximity (any partition is acceptable; membership is the union). Platforms: one entry
with `frames_x_wind` = the 63 frames line-loaded in X that are not chiller beams and
`frames_y_wind` = the 21 frames line-loaded in Y.

## 6. Categorization rules

All lengths in feet, all tolerances from section 5. "Band" means a story band from section 4.2.
The rules run per shell, independent of every other shell except R5.

**R0 Candidates.** A shell is a candidate if its corners are coplanar and vertical: all corners
project onto one plan line (collinear in plan, kinked extra points allowed) and its height exceeds
`plane_tolerance_ft`. Non-vertical shells are `excluded` ("floor or sloped shell"). A vertical shell
whose plan line is not parallel to global X or Y is `unresolved: not_axis_aligned`.

**R1 Level.** `level` = the band whose `(bottom, top]` range contains the shell's top edge, with
`level_tolerance_ft` applied at the top. A top above the highest story is `unresolved:
above_top_story`.

**R2 Element type from level.** Bands at or below `levels.main_roof` are walls. Bands listed under
`levels.parapet` are parapets, `levels.penthouse_body` penthouse bodies, `levels.penthouse_parapet`
penthouse parapets. A band not listed is `unresolved: level_unmapped`.

**R3 Placement.**

- Wall and parapet shells are matched against `exterior_segments`: same axis, plane ordinate within
  `plane_tolerance_ft` of the segment's `along`, and plan midpoint within `[from, to]` widened by
  `range_tolerance_ft`. Exactly one match places the shell and gives it `segment_id` and
  `outside`. A segment with `outside: none` places the shell as `excluded: declared_unexposed`.
  No match: `unresolved: no_exterior_segment` with the ordinate and extent in the message (an
  undeclared face, an interior wall on a grid line). More than one match: `error:
  ambiguous_segment`.
- Penthouse body and penthouse parapet shells are matched against each penthouse's four footprint
  edges with the same tolerances; `outside` is the edge's outward normal; `component` is the
  penthouse id. No match: `unresolved: no_penthouse_edge`.
- **Shared lines.** Where a penthouse edge coincides with an exterior segment (PH2 shares J, E and
  grid 39; PH1 shares E), a parapet-band shell is a penthouse body, not a main parapet, when its
  stack (R5) tops out at or above the lowest `levels.penthouse_body` band bottom; otherwise it is
  a main parapet. A parapet-band shell on a penthouse edge that matches no exterior segment is a
  penthouse body with `warning: body_below_penthouse_level`.
- An `overrides` entry wins over R2/R3 and must supply whatever the rules could not.
- A shell whose plan extent exceeds its segment range by more than `range_tolerance_ft` is placed
  but gets `warning: extent_exceeds_segment`.

**R4 Role per direction.** For each wind direction d: `outside` opposite d -> WINDWARD; same as d
-> LEEWARD; perpendicular -> SIDE. `side` label = `segment_id` (or `component` + edge name for
penthouses, e.g. `PH1_N`).

**R5 Parapet type.** For a main-parapet shell, the parapet *stack* is the set of parapet-band shells
on the same segment whose plan extents overlap it. The stack top is the highest top edge in the
stack. The parapet type is the `parapets.types` entry (kind `main_roof` or `picture_frame`) whose
`top_elevation_above_grade_ft` matches the stack top within `level_tolerance_ft`; no match is
`unresolved: parapet_type_unmatched`. Penthouse parapets use the penthouse's `parapet_type`.

**R6 Pattern groups.**

| Element type | Goes into | Directions |
| --- | --- | --- |
| wall | `W_Wall_d` | all four |
| main parapet, penthouse parapet | `W_Parapet_d` | all four |
| penthouse body | `W_PH_d` | the three where its role is not LEEWARD |
| equipment support frame, platform frame | `W_Mech_d` | see R7 |

Side faces of parapets and penthouse bodies therefore live in `W_Parapet`/`W_PH`, matching the
engineers' practice (today's code puts them in `W_Wall`; see section 10).

**R7 Frames.** Equipment `support_frames` go into all four `W_Mech_d`. Platform
`frames_x_wind` go into `W_Mech_±X`, `frames_y_wind` into `W_Mech_±Y`. A frame may appear in both
an equipment and a platform list; membership is the union. A configured frame missing from the
model is `warning: missing_support_frame` / `missing_platform_frame`. A frame whose top elevation
is outside the `levels.mechanical` band gets `warning: frame_level_unexpected`. Unconfigured frames
are `excluded`.

**R8 Fine groups.** For the Patterns module and the report, the tool still builds one `GroupSpec`
per unique (element type, direction, role, side, level, parapet type) with the members' refs,
result id and destination pattern, exactly as today's `GroupSpec` but with `side` and `level`
fields added and the `band` field renamed to `level`. These are the face-based "X+ wall group,
broken into stories" that `docs/spec_patterns.md` consumes. They are not written to ETABS.

## 7. Outputs

```python
@dataclass
class Categorization:
    objects: dict[str, ObjectCategory]       # as today + fields: level, segment_id, outside, side
    pattern_groups: dict[str, list[str]]     # the 16 W_* names -> sorted object refs
    groups: list[GroupSpec]                  # fine groups (R8)
    derived_dims: dict[str, PlanDims]        # from segments' extent
    comparison: list[GroupComparison]        # vs snapshot.groups (existing W_*)
    diagnostics: list[Diagnostic]

@dataclass(frozen=True)
class GroupComparison:
    name: str
    in_model: int
    by_rules: int
    missing_from_rules: tuple[str, ...]      # refs in the model's group but not the tool's
    extra_in_rules: tuple[str, ...]
```

`pattern_groups` always contains all sixteen names, empty lists allowed.

## 8. Write-back and workflow changes

### 8.1 Group write-back procedure

`WindSession.create_preview_groups()` is replaced by `write_pattern_groups()`. For each of the
sixteen names, in the adapter's `set_group(name, members)`:

1. `GroupDef.GetNameList()`; existence is compared case-insensitively.
2. If the group exists: `GroupDef.GetGroup_1(name)` to read its colour and flags, then
   `GroupDef.Delete(name)`. Deleting is the only way to empty it; `SetGroup_1` on an existing name
   keeps the old members. If `Delete` returns non-zero and the name is still listed, raise
   `AdapterError` ("could not be emptied; may still hold earlier members") and stop.
3. `GroupDef.SetGroup_1(name, colour, flags...)` with the values read in step 2, or defaults for a
   new group.
4. One `AreaObj.SetGroupAssign(obj, name)` / `FrameObj.SetGroupAssign(obj, name)` /
   `PointObj.SetGroupAssign(obj, name)` per member, by ref prefix. Non-zero returns are collected,
   not raised, and reported per object.
5. `GroupDef.GetAssignments(name)` read-back; a zero return code is not proof of membership. The
   write result lists refused objects and any member not seen in the read-back.

Roughly seven thousand `SetGroupAssign` calls for the Test Model; no bulk route exists for named
members. Groups starting with `W_` are tool-managed by convention; the ownership manifest records
them. No other group is created, modified or deleted. CSI Model Assistant's tools reference notes
that area objects may not be groupable on some ETABS builds; phase 1 confirms it on 23.

### 8.2 Workflow and GUI

- The `AA_PREVIEW_*` groups and `reconcile_membership` are retired. The pre-apply drift check and
  `select_group` instead re-read the `W_*` groups and compare with `pattern_groups`; a difference
  invalidates the preview exactly as today's drift check does.
- The GUI's group table (`GROUP_COLUMNS`, rows keyed by group name since `05cf210`) shows the
  sixteen `comparison` rows first, then the fine groups. "Select group in ETABS" works on either.
- `plan_dimensions_source: etabs` uses `derived_dims` from segments.
- Apply is unchanged in this project except that it must not require `AA_PREVIEW_*` groups.

## 9. Testing

**Fixture.** `tests/fixtures/test_model_snapshot.json` captured from the live seven-story Test
Model (section 4.7), and `examples/test_model.yaml` as in section 5.4.

**Acceptance assertions.** The model's own `W_*` groups are the expected answer, with one
documented exception. On any other mismatch the builder stops and reports it; whether it is a
YAML error, a rule error or a model inconsistency is James's call, and the exception list below is
only extended with his agreement.

| Group | Expected |
| --- | --- |
| `W_Parapet_±X/±Y` | rule membership == model membership, 695 each |
| `W_PH_+X/-X/+Y/-Y` | == model, 18 / 22 / 22 / 22 |
| `W_Wall_+X/-X/-Y` | == model, 568 each |
| `W_Wall_+Y` | rule gives 568; model has 565; the three extra are exactly the 6 in slivers on `J_sliver` (shells W2029, W2032 at R and W2046 at L2 in the `$et`), which the model loads in the other three directions. Documented model inconsistency. |
| `W_Mech_±X` / `±Y` | == model, 135 / 93 |

**Rule unit tests** with hand-built snapshots: each R-rule, each diagnostic code, tolerance edges
(grid 28.5 vs 29), the collinear-kink shell, a body split at Mech on a shared line, an undeclared
face, an `outside: none` segment, an ambiguous segment, unit-string handling and the span fallback,
grid-label resolution and unknown labels, overlapping segment ranges, schema v1 rejection.

**Phase 1 live check** is manual and recorded in `docs/etabs_setup.md`: stories and grids dumped
from the Test Model match the `$et`; area objects can be grouped through the API on ETABS 23.

Existing tests that encode envelope behaviour (`unsupported_layout`, edge coverage,
`AA_PREVIEW_*` names, `reconcile_membership`) are rewritten or removed with the code they test.

## 10. Follow-ups recorded for other modules (not in this project)

- Patterns: equipment loads as frame point loads at beam ends (`FrameObj.SetLoadPoint`, relative
  distance 1.0) instead of joint loads. The model carries **two** identical point loads per beam end
  per direction (0.8814 kip X, 4.9356 kip Y, each a quarter of one reference chiller), i.e. 36
  chiller-equivalents over 72 beams, not 18; James to confirm whether that is two chillers per
  support set or a doubled assignment before the loads are generated.
- Patterns: four directional mechanical patterns (`W_Mech_+X` ...) per `docs/spec_patterns.md`
  (twenty patterns), instead of two reversible ones.
- Patterns: side faces of parapets and penthouse bodies carry `W_Parapet_d` / `W_PH_d` as the
  destination pattern. `docs/spec_patterns.md` says only the windward penthouse face gets pressure,
  but the model loads penthouse side faces with the side suction under `W_PH`; to be reconciled.
- Patterns: shell assignments in global X/Y direction, as the engineers do, instead of local 3.
- Workflow: GUI must call `adapter.close()` to restore units.

## 11. Constraints

- Windows, ETABS 23, Python 3.11+, `comtypes`. Core modules never import comtypes.
- One running ETABS instance must have the new Test Model open for phase 1 acceptance and for the
  fixture capture. Two instances are open on James's machine today; the pid is passed explicitly.
- Ruff and pytest stay green in CI without ETABS.
- Yinchen is actively editing `ui.py`, `workflow.py` and `adapter.py`; the builder rebases on
  `main` before each phase and keeps changes to those files minimal and well separated.

## 12. Left to the builder

- Internal structure of the rules module (one function per rule is suggested).
- How table columns are matched by name, and the exact discovery heuristic, as long as failure is
  loud and lists what was found.
- JSON layout of the captured snapshot and the capture CLI's argument shape.
- Whether `local3` is read eagerly or lazily.
- How the 72 chiller beams are partitioned into equipment entries for the fixture.
- Test file organisation.
