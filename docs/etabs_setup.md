# ETABS setup and live-integration verification

## Status

`air_apparent.etabs.adapter.ComEtabsAdapter` was written **without access to ETABS**. It has not been
run. Treat it as unverified until every item of the checklist below is signed off.

## Requirements

- Windows, ETABS installed, Python 3.11+, `pip install -e ".[etabs]"` (installs `comtypes`, Windows
  only; the rest of the package never imports it).
- Open the model in ETABS first. If several ETABS instances are open, enter the process ID of the
  intended one in the GUI (`ETABS pid`); the tool refuses to guess. The connection panel shows the
  model path, pid, version, units and lock state.
- The adapter switches the present units to kip-ft-F while connected and restores them on `close()`.
  All calculations use ft / psf / kip; shell pressures are sent as kip/ft2, line loads as kip/ft.

## Operations and conventions to verify

| Item | Convention used | Verify against installed API docs |
| --- | --- | --- |
| Shell pressure | `AreaObj.SetLoadUniform(name, pattern, value, Dir=3 (local 3), Replace=True)`; value = code pressure x sign, where sign = +1 if local axis 3 points into the building | Dir code, sign convention, return values |
| Local axis 3 | row 3 of `AreaObj.GetTransformationMatrix` | indexing, global vs local |
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

## Live verification checklist (not yet done)

1. Connect to a copy of a model with two ETABS instances open; confirm explicit selection.
2. Read geometry; confirm local axis 3 direction of a few shells against the ETABS GUI.
3. Create preview groups; select several in ETABS; edit one manually and confirm detection.
4. Apply; confirm a windward shell shows the expected pressure direction for +X and -X.
5. Confirm joint forces, frame loads, cases (including `W_Mech_-X = -1.0 x W_Mech_X`) and combinations.
6. Run the analysis; compare base shear with the exported resultants (`Fx, Fy, Mz about origin`).
7. Re-apply and confirm no accumulation; export the report.
