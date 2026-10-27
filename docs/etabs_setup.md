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
| Shell pressure | `AreaObj.SetLoadUniform(name, pattern, value, Dir=3 (local 3), Replace=True)`; value = code pressure x sign, where sign = +1 if local axis 3 points into the building | Setter not exercised; Apply was blocked |
| Local axis 3 | column 3 (indices 2, 5, 8) of `AreaObj.GetTransformationMatrix` | global normal verified on live X-facing walls |
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

## Live verification still outstanding

1. Connect to a copy of a model with two ETABS instances open; confirm explicit selection.
2. Read geometry; confirm local axis 3 direction of a few shells against the ETABS GUI.
3. Create preview groups; select several in ETABS; edit one manually and confirm detection.
4. Apply; confirm a windward shell shows the expected pressure direction for +X and -X.
5. Confirm joint forces, frame loads, cases (including `W_Mech_-X = -1.0 x W_Mech_X`) and combinations.
6. Run the analysis; compare base shear with the exported resultants (`Fx, Fy, Mz about origin`).
7. Re-apply and confirm no accumulation; export the report.

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
