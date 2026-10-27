# ETABS setup and live-integration verification

## Status

`air_apparent.etabs.adapter.ComEtabsAdapter` was exercised against ETABS 23.3.1 using an isolated
saved copy of `examples/Test Model.EDB`. Geometry reads, preview-group creation and selection, unit
restoration, and existing-assignment read-back were verified live. Applying new loads was blocked by
model/configuration errors; no loads were applied. This is separate from automated tests and E2K
export inspection.

## Requirements

- Windows, ETABS installed, Python 3.11+, `pip install -e ".[etabs]"` (installs `comtypes`, Windows
  only; the rest of the package never imports it).
- Open the model in ETABS first. If several ETABS instances are open, enter the process ID of the
  intended one in the GUI (`ETABS pid`); the tool refuses to guess. The connection panel shows the
  model path, pid, version, units and lock state.
- Geometry reads, load assignment, load deletion, and load read-back each temporarily switch the
  present units to kip-ft-F and restore the units active before that operation. `close()` restores
  the units active when the adapter connected. Calculations use ft / psf / kip; shell pressures are
  sent as kip/ft2, line loads as kip/ft.

## Operations and conventions to verify

| Item | Convention used | Verify against installed API docs |
| --- | --- | --- |
| Shell pressure | `AreaObj.SetLoadUniform(name, pattern, value, Dir=3 (local 3), Replace=True)`; value = code pressure x sign, where sign = +1 if local axis 3 points into the building | Dir code, sign convention, return values |
| Local axis 3 | column 3 (indices 2, 5, 8) of `AreaObj.GetTransformationMatrix` | global normal verified on a live X-facing wall |
| Equipment | `PointObj.SetLoadForce` on existing joints (not frame-end loads) | argument order |
| Platform | `FrameObj.SetLoadDistributed` global X/Y, force/length | Dir codes |
| Eccentric torsion | joint moment Mz at each story's diaphragm reference joint | how stories/diaphragms expose a reference joint |
| Patterns | `LoadPatterns.Add(name, Wind, 0.0, AddLoadCase=False)` (zero self weight, no auto wind) | type enum value |
| Cases / combos | `LoadCases.StaticLinear`, `RespCombo` (linear and envelope) | enum codes |
| Groups | `GroupDef.SetGroup/Delete/GetAssignments`, `SetGroupAssign`, `SelectObj.Group` | return tuples |

Every call is wrapped so a non-zero return code raises `AdapterError`; dependent writes stop and the
partial state is reported (no rollback).

## Safety behaviour

- Preview groups are tool-owned (`AA_PREVIEW_*`, recorded in an ownership manifest stored next to the
  model as `<model>.air_apparent.json`). Unrelated groups are never modified; a same-named group that
  is not tool-owned is reported as a naming conflict.
- Re-applying an unchanged plan uses replace semantics and clears assignments that the manifest says
  were previously tool-created but are no longer planned.
- Existing patterns/cases/combinations that are not tool-owned are never deleted or overwritten
  (`name_conflict` aborts the apply). Unfamiliar definitions are listed as audit findings (for
  example obsolete `AW_...` patterns).
- A locked model is not unlocked unless the engineer confirms; unlocking discards analysis results.

## Live verification status

1. Connect to an explicitly selected ETABS process and read geometry: verified on ETABS 23.3.1.
2. Read local axis 3 from the transformation matrix: verified against live X-facing walls.
3. Create and select preview groups, then read group membership back: verified in two runs.
4. Apply loads and verify their direction: not completed; model/layout diagnostics blocked Apply.
5. Verify joint forces, frame loads, cases, and combinations after Apply: not completed.
6. Run analysis and compare resultants: not completed.
7. Re-apply and verify no accumulation: not completed because Apply was blocked.

## Phase 1 verified (2026-10-27, ETABS 23.4.0 beta, Test Model seven-story version)

`python -m air_apparent.capture --pid <pid> out.json` read the live model in about two seconds:

- `Story.GetStories_2` returned the stories **bottom-up** (L2 first) on this build; the reader sorts by
  elevation and never relies on the order. Base -0.833 ft; L2 31.5; R 60.083; Parapet_1 65.083;
  Mech 70.708; Penthouse 75.167; Parapet_2 76.917 ft, all matching the `$et` export.
- Grid lines come from the database table whose key and name are both `Grid Definitions - Grid Lines`
  (columns `Name, LineType, ID, Ordinate, BubbleLoc, Visible`; `LineType` reads `X (Cartesian)` /
  `Y (Cartesian)`). Grid systems (origin, rotation) come from `Grid Definitions - General`
  (`Name, Type, Ux, Uy, Rz`). Table values follow the present units and the `UnitsString` reported by
  `GetAllFieldsInTable` changes with them, so the reader converts by that string. 13 X lines (28 at 0
  to 39 at 421.75 ft) and 5 Y lines (J 0 to E 238 ft) matched the `$et`.
- `AreaObj.GetAllAreas` returned 1425 areas with `PointDelimiter[i]` = 0-based index of the last
  boundary point of area i (inclusive). 222 frames, 2782 points, 44 groups of which 16 start with `W_`.
- comtypes 1.4.17 wrappers accept calls without placeholder arguments for by-ref parameters; the
  out-parameters come back as a list in declaration order with the return code last.
- `AreaObj.GetLoadUniform("All", 1)` and `PointObj.GetLoadForce("All", 1)` returned code 1 on this
  build, so `read_assignments` falls back to one call per object when the group route is refused.
- Checklist items 1 (explicit pid selection) and 2 (geometry read) above are done; the local-axis-3
  visual check is not needed by categorization, which never uses local axes.

## Group write-back verified (2026-10-27, same build)

`WindSession.write_pattern_groups()` wrote all sixteen `W_*` groups to the open Test Model in about
1.2 seconds (one `SetGroupAssign` per member after `GetGroup_1`, `Delete`, `SetGroup_1`), ETABS
refused no object, and `check_group_drift()` read back exactly the rule membership. Area objects are
groupable through the API on ETABS 23.4. Present units were restored on `close()`. The model was not
saved. Checklist item 3 above is therefore done for the `W_*` groups.

## Test Model findings

The checked-in E2K export records wall coordinates in inches. Its L2 wall bounds are X=2.25..421.75
ft and Y approximately 0..238 ft, a 419.5 x 238 ft footprint. ETABS 23.3.1 returned the same bounds
when the geometry API was called in kip-ft-F.

The YAML remains unchanged. Its X-wind dimension comparison values are 1,472 x 240 ft. Its 0-ft
grade/band boundary cuts 213 shells that extend from -0.8333 to 31.5 ft. The configured 62-ft roof
plane cuts 243 shells between the ETABS R story at 60.0833 ft and Parapet_1 at 65.0833 ft. The
template's single 67-ft parapet top does not match the model's parapet elevations (65.0833, 68.7083,
69.2083, 70.7083, and 76.9167 ft). These are configuration/model-coordination decisions; no
engineering inputs were inferred.

The lowest-level model wall coverage is 49%, 60%, 82%, and 88% on the four envelope edges. These
layout errors remain error-level diagnostics and block Apply. There are also 16 sloped/non-planar
shells and 48 shells outside the envelope; they remain flagged for review. The live model contains
unowned wind patterns, cases, and combinations whose names conflict with the planned definitions;
the tool must not overwrite those objects.

Two live Connect/Inspect/Calculate/Preview/Select runs produced identical 419.5 x 238 ft dimensions,
31 preview groups with identical membership, and selected a 498-shell review group. Apply correctly
refused both runs because of the layout errors. The 5,133 existing assignments in the planned
pattern names were unchanged. This verifies preview and existing-load read-back only; it does not
verify load setters, a successful apply/read-back cycle, or analysis. No loads were applied.
