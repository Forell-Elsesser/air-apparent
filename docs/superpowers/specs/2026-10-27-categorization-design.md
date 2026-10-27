# Categorization module design: rule-based grouping from story lines, grid lines and declared exterior segments

Date: 2026-10-27. Status: draft for approval (revised after builder check and after a read-only
live check against the Test Model, see section 9.1). Supersedes the envelope-based rules in
`src/air_apparent/categorization/rules.py`.

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
rules must reproduce them, with the exceptions listed in section 9. A throwaway script applying
these rules to the live model already does (section 9.1).

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
| Stories come from the Story API; grid lines from the interactive tables | James | both verified live (section 4) |
| Exterior wall faces are declared in YAML as segments, not inferred | James | "declare the exterior segments path" |
| Only `W_*` groups are read, compared and written | James | all other groups in the sample model are stale artifacts |
| Write back exactly the sixteen per-pattern `W_*` groups | James | not the finer groups |
| Group write-back follows the `objects_group` sequence in CSI Model Assistant | James (pointed to it) | section 8.1 |
| Level = story band containing the shell's top edge | Claude, confirmed live | ETABS's own association convention; handles parapet strips cut at non-story elevations |
| Element type follows from level | Claude, confirmed live | section 6 |
| A segment may carry a height range (`z_from`/`z_to`) | Claude, forced by the data | the Test Model's four bump-outs stop at 47.75 ft; the main J and E walls behind them are exposed from 46 ft up |
| Placement = the segment overlapping the majority of the shell's plan extent, against the declared range with no widening | Claude, forced by the data | the earlier midpoint-with-tolerance rule misplaced 17 boundary shells and left 13 ambiguous |
| YAML stays in feet; the adapter sets present units to kip-ft before reading | Claude | database tables follow present units too (verified) |
| Equipment gains `support_frames` for grouping; `support_joints` stays optional so Patterns keeps working | Claude | `W_Mech` groups contain beams only; load application moves to the Patterns follow-up |
| Offline fixture = JSON snapshot captured once from the live Test Model | Claude | avoids a second parser of ETABS data |
| The 6 in sliver column at the west end of grid J is declared as a segment | Claude | it is exterior; the model loads its five pieces inconsistently (section 9) |
| A segment may be declared `outside: none` to mark a face as deliberately unexposed | Claude | the grid 28.5 cut line; keeps the diagnostics clean |

## 4. Reading the connected model (phase 1)

Everything in this section was exercised on 2026-10-27 against the live seven-story Test Model
(ETABS 23.4.0 beta, pid 62104) with a read-only script; the facts below are observed, not assumed.

### 4.1 Connection and units

Unchanged: `connect_live(pid)` attaches via `ETABSv1.Helper.GetObjectProcess`. On connect the
adapter records the present units, sets `kip_ft_F` (value 4), and restores them on `close()`. All
API lengths are therefore feet. The GUI must call `close()` on disconnect/exit (today it does not).
The Test Model's database units are kip-in (enum 3).

### 4.2 Stories

`SapModel.Story.GetStories_2()` returns, in comtypes order:
`(BaseElevation, NumberStories, StoryNames, StoryElevations, StoryHeights, IsMasterStory,
SimilarToStory, SpliceAbove, SpliceHeight, Color, ret)`. **On ETABS 23.4 the arrays come back
bottom-up** (L2 first), the opposite of the E2K file. The reader sorts by elevation and never
assumes an order.

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
ModelSnapshot.stories: list[Story]     # bottom-up after reading
```

Derived, not stored: the **story bands**, one per story, `(bottom, top] = (elevation of the story
below or base, elevation of this story]`, named after the story.

Observed: base -0.833 ft; L2 31.5; R 60.083; Parapet_1 65.083; Mech 70.708; Penthouse 75.167;
Parapet_2 76.917.

### 4.3 Grid lines

Through `SapModel.DatabaseTables`. Observed on ETABS 23.4:

- `GetAvailableTables()` lists 125 tables. Two are grid-related, and the key equals the name:
  `Grid Definitions - Grid Lines` and `Grid Definitions - General`. The reader selects the key
  containing "Grid" and "Line" and not "General"; anything other than exactly one match raises
  `AdapterError` listing the candidates.
- `GetAllFieldsInTable("Grid Definitions - Grid Lines")` fields: `Name`, `LineType`, `ID`,
  `Ordinate` (units), `Angle` (deg), `X1`, `Y1`, `X2`, `Y2` (units), `BubbleLoc`, `Visible`.
- `GetTableForDisplayArray(key, [""], "", 0, [], 0, [])` returns columns `Name, LineType, ID,
  Ordinate, BubbleLoc, Visible` for Cartesian lines; `LineType` is `X (Cartesian)` or
  `Y (Cartesian)`; 18 rows for the Test Model. Columns are mapped by key, never by position.
- `Grid Definitions - General` holds the systems: `Tower, Name, Type, Ux, Uy, Rz, StoryRange,
  BubbleSize, Color, GUID`, one row (`T1`, `G1`, `Cartesian`, 0, 0, 0).
- **Table values follow the present units.** With database units kip-in the ordinate of grid 28.5
  reads `27`; after `SetPresentUnits(kip_ft_F)` it reads `2.25`, and the field's `UnitsString`
  changes from `in` to `ft`. The reader therefore reads tables after setting kip-ft and checks that
  the ordinate `UnitsString` is `ft`; anything else raises `AdapterError`. No span heuristic.

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
    ordinate_ft: float   # global coordinates (origin and rotation applied)

ModelSnapshot.grid_systems: list[GridSystem]
ModelSnapshot.grid_lines: list[GridLine]
```

Only Cartesian systems with zero rotation are used by the rules. Others are kept in the snapshot
and reported as `warning: grid_system_unsupported`.

Observed: X lines 28, 28.5, 29, 30 ... 39 at 0, 2.25, 3.0, 43.75, 85.75, ... 421.75 ft; Y lines J,
H, G, F, E at 0, 59, 119, 179, 238 ft.

### 4.4 Shells, frames, points, labels

Bulk calls replace the per-object loops:

- `AreaObj.GetAllAreas()` -> `(NumberNames, MyName, DesignOrientation, NumberBoundaryPts,
  PointDelimiter, PointNames, PointX, PointY, PointZ, ret)`. `PointDelimiter[i]` is the **0-based
  index of the last boundary point of area i** (observed: values 3, 7, 11, ... and the last equals
  `NumberBoundaryPts - 1`). The Test Model has 1425 areas and 5722 boundary points. The API's
  unique names are integers (e.g. `1426`); labels come separately.
- `FrameObj.GetAllFrames()` -> names, section, story, end point names and coordinates. 222 frames.
- `PointObj.GetAllPoints()` -> names and coordinates.
- `AreaObj.GetLabelNameList()` etc. -> unique name to `(label, story)`; e.g. `1426 -> (W1, L2)`.
  Stored as `ModelSnapshot.labels: dict[str, tuple[str, str]]` keyed by object ref. Used only for
  reporting and for matching the `$et` when debugging; never for rules.
- `GetTransformationMatrix` is no longer needed for categorization; `local3` stays populated (per
  shell, or lazily) only because the Patterns sign conversion still reads it.

### 4.5 Groups

`GroupDef.GetNameList()` (44 groups in the Test Model), then `GetAssignments(name)` only for the
16 names starting with `W_`. `ObjectType` codes: 1 point, 2 frame, 5 area. Stored in
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

Connect to the Test Model, read, and print stories and grid lines. They must match sections 4.2
and 4.3 to 0.01 ft. The shell count must equal `AreaObj.Count()` (1425).

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
  # Optional height range in model elevation (ft) for faces that are exterior only above or below
  # something, such as the main wall above a low bump-out. A shell matches on its z-midpoint.
  - {id: J_SM_top, along: J, from: 218.417, to: 241.667, outside: "-Y", z_from: 46.0}
  # outside: none declares a face that is deliberately not exposed (a cut line, an expansion joint).
  - {id: W_cut, along: "28.5", from: J, to: E, outside: none}

categorization:
  plane_tolerance_ft: 0.1      # shell plane vs segment ordinate; must separate grids 28.5 and 29
  extent_tolerance_ft: 0.5     # a shell poking further than this beyond its segment gets a warning
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
- Two segments on the same line may not overlap in both range and height (config error).
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

### 5.4 Test Model declaration (complete, verified live)

Feet, three decimals. Grid labels in quotes where numeric-looking. This is the file
`examples/test_model.yaml` uses; every non-categorization value in that file (wind inputs,
pressure bands, equipment and platform dimensions, story shears) is copied from
`examples/reference_sample.yaml` because the file is a test fixture, not the project's configuration.

The four bump-outs are 11 ft deep and run from grade to 47.75 ft. Their own faces need no height
range (each is the only segment on its plane). The main J and E walls behind them are exposed from
46 ft up, which is where the engineers split the shells; those four stretches carry `z_from: 46`.

```yaml
exterior_segments:
  - {id: J_W,      along: J,     from: 25.5,    to: 218.417, outside: "-Y"}
  - {id: J_E,      along: J,     from: 241.667, to: "39",    outside: "-Y"}
  - {id: J_sliver, along: J,     from: 1.75,    to: 2.25,    outside: "-Y"}   # 6 in west of grid 28.5
  - {id: J_SW_top, along: J,     from: 2.25,    to: 25.5,    outside: "-Y", z_from: 46.0}
  - {id: J_SM_top, along: J,     from: 218.417, to: 241.667, outside: "-Y", z_from: 46.0}
  - {id: E_W,      along: E,     from: 25.5,    to: 218.417, outside: "+Y"}
  - {id: E_E,      along: E,     from: 241.667, to: "39",    outside: "+Y"}
  - {id: E_NW_top, along: E,     from: 2.25,    to: 25.5,    outside: "+Y", z_from: 46.0}
  - {id: E_NM_top, along: E,     from: 218.417, to: 241.667, outside: "+Y", z_from: 46.0}
  - {id: G39,      along: "39",  from: J,       to: E,       outside: "+X"}
  - {id: W_cut,    along: "28.5", from: J,      to: E,       outside: none}   # building continues west
  # bump-outs beyond J (y -11) and beyond E (y 249), x 2.25-25.5 and 218.417-241.667
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

- Candidate segments for a wall or parapet shell: same axis, plane ordinate within
  `plane_tolerance_ft` of the segment's `along`, the shell's z-midpoint inside the segment's
  `[z_from, z_to]` when given, and the shell's plan extent overlapping the segment's declared
  `[from, to]` (no widening) by at least half the shell's width. The shell is placed on the
  candidate with the **largest overlap**; it gets that segment's `segment_id` and `outside`. Two
  candidates with equal overlap are `error: ambiguous_segment`. No candidate: `unresolved:
  no_exterior_segment` with the ordinate, extent and z-range in the message. A segment with
  `outside: none` places the shell as `excluded: declared_unexposed`.
- Penthouse body and penthouse parapet shells are matched the same way against each penthouse's
  four footprint edges; `outside` is the edge's outward normal; `component` is the penthouse id.
  No match: `unresolved: no_penthouse_edge`.
- **Shared lines.** Where a penthouse edge coincides with an exterior segment (PH2 shares J, E and
  grid 39; PH1 shares E), a parapet-band shell is a penthouse body, not a main parapet, when its
  stack (R5) tops out at or above the lowest `levels.penthouse_body` band bottom; otherwise it is
  a main parapet. A parapet-band shell on a penthouse edge that matches no exterior segment is a
  penthouse body with `warning: body_below_penthouse_level`. (The Test Model has no such shell.)
- An `overrides` entry wins over R2/R3 and must supply whatever the rules could not.
- A shell whose plan extent exceeds its segment range by more than `extent_tolerance_ft` is placed
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
that area objects may not be groupable on some ETABS builds; the Test Model's `W_*` groups contain
areas, so ETABS 23 supports it.

### 8.2 Workflow and GUI

- The `AA_PREVIEW_*` groups and `reconcile_membership` are retired. The pre-apply drift check and
  `select_group` instead re-read the `W_*` groups and compare with `pattern_groups`; a difference
  invalidates the preview exactly as today's drift check does.
- The GUI's group table (`GROUP_COLUMNS`, rows keyed by group name since `05cf210`) shows the
  sixteen `comparison` rows first, then the fine groups. "Select group in ETABS" works on either.
- `plan_dimensions_source: etabs` uses `derived_dims` from segments.
- Apply is unchanged in this project except that it must not require `AA_PREVIEW_*` groups.

## 9. Testing

### 9.1 Live check already performed (2026-10-27)

A throwaway script (not kept in the repo) connected read-only to the Test Model, read everything in
section 4, applied rules R0-R6 with the section 5.4 declaration, and compared with the model's
groups. Present units were switched to kip-ft for the read and restored afterwards; nothing was
written. Result:

| Group | Model | Rules | Difference |
| --- | --- | --- | --- |
| `W_PH_+X / -X / +Y / -Y` | 18 / 22 / 22 / 22 | same | none |
| `W_Parapet_±X/±Y` | 695 each | 695 | none |
| `W_Wall_+X / -X / -Y` | 568 | 569 | rules add API object `2850` (label W2048 at L2), the lowest 7.2 ft piece of the 6 in sliver column at the west end of J, x 1.75-2.25 ft, which the model loads in no direction |
| `W_Wall_+Y` | 565 | 569 | rules add `2850`, `2848`, `2846`, `2844` (W2048, W2046, W2032, W2029), the sliver column below 46 ft; the top piece `2842` (W2027) is in all four model groups |
| `W_Mech_±X / ±Y` | 135 / 93 | configured lists | every member is a beam whose top is in the Mech band |

Nothing in any model group is missing from the rules. Of the vertical shells the rules do not place
(108 `no_exterior_segment` and 16 `declared_unexposed`), none is in any model group. No shell was
ambiguous. The only disagreement is the sliver column, which the model itself loads inconsistently.

### 9.2 Fixture and acceptance assertions

**Fixture.** `tests/fixtures/test_model_snapshot.json` captured from the live seven-story Test
Model (section 4.7), and `examples/test_model.yaml` as in section 5.4.

**Acceptance assertions** encode the 9.1 table exactly. The model's own `W_*` groups are the expected
answer, with the sliver column as the one documented exception. On any other mismatch the builder
stops and reports it; whether it is a YAML error, a rule error or a model inconsistency is James's
call, and the exception list is only extended with his agreement.

**Rule unit tests** with hand-built snapshots: each R-rule, each diagnostic code, tolerance edges
(grid 28.5 vs 29), the collinear-kink shell, a body split at Mech on a shared line, an undeclared
face, an `outside: none` segment, a tied overlap (ambiguous), a shell straddling two segments
(largest overlap wins), a `z_from` segment, unit-string check, grid-label resolution and unknown
labels, overlapping segment ranges, schema v1 rejection.

**Phase 1 live check** is manual and recorded in `docs/etabs_setup.md`: stories and grids dumped
from the Test Model match section 4.

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

- Windows, ETABS 23, Python 3.11+, `comtypes` (1.4.17 works on Python 3.14). Core modules never
  import comtypes.
- One running ETABS instance must have the Test Model open for phase 1 acceptance and for the
  fixture capture; the pid changes with every launch and is passed explicitly.
- Ruff and pytest stay green in CI without ETABS.
- Yinchen is actively editing `ui.py`, `workflow.py` and `adapter.py`; the builder rebases on
  `main` before each phase and keeps changes to those files minimal and well separated.

## 12. Left to the builder

- Internal structure of the rules module (one function per rule is suggested).
- JSON layout of the captured snapshot and the capture CLI's argument shape.
- Whether `local3` is read eagerly or lazily.
- How the 72 chiller beams are partitioned into equipment entries for the fixture.
- Test file organisation.
