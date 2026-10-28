# User guide

Use this guide to install air-apparent, complete the offline example, and prepare a model for live
ETABS integration. Commands below use Windows PowerShell from the repository root. The application
is a desktop GUI; wind inputs are edited in a YAML file.

The current scope is ASCE 7-10 horizontal MWFRS wind loading for one rectangular building aligned
with global X/Y. Workbook reproduction and offline tests are available. Independent engineering
review and live ETABS verification are still pending; native GUI startup and live ETABS shear
extraction remain unverified, and eccentric loads and W1-W4 combinations are provisional. See
[engineering basis](engineering_basis.md) and [limitations](limitations.md).

## 1. Install and launch

Install Python 3.11 or newer with Tkinter, then open PowerShell in your checkout of air-apparent.
Check Python and install the package into a virtual environment:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

These commands use the virtual environment directly; activating it is optional. If the environment
already exists, reuse it. For live ETABS integration on Windows, also install the optional dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[etabs]"
```

Launch with the supplied offline inputs:

```powershell
.\.venv\Scripts\air-apparent.exe examples/reference_sample.yaml
```

Alternatively, launch the same GUI through Python:

```powershell
.\.venv\Scripts\python.exe -m air_apparent.ui examples/reference_sample.yaml
```

The window has a row of workflow buttons, an **ETABS pid:** field, a **Config / Diagnostics** tab,
a **Preview groups / assignment table** tab, and a status message at the bottom. The supplied YAML
loads at startup. Without a YAML argument the app loads `templates/wind_inputs.yaml`.
You can use **Load/Reload YAML...** to select a different file.

## 2. Complete the offline walkthrough

This path uses synthetic geometry and an in-memory adapter. No running ETABS instance is required,
and applying the plan in this mode changes only the in-memory demonstration model. The supplied
YAML is not a ready-to-apply configuration for the sample EDB or a project model.

### Step 1: Load the reference inputs

If you launched with the command above, the file is already loaded. Otherwise click
**Load/Reload YAML...** and choose [reference_sample.yaml](../examples/reference_sample.yaml).
The **Config / Diagnostics** tab shows the effective configuration. Expect the status to say
that YAML is loaded and dependent results have been invalidated.

### Step 2: Open and inspect the demonstration model

Click **Offline demo**, then **Inspect**. The status changes from opening synthetic geometry to
**Model read and categorized**. In **Config / Diagnostics**, review the category counts, envelope,
derived dimensions, and any categorization messages. The reference building plan is 1,472 ft in X
by 240 ft in Y.

**Inspect** reads the model again and invalidates previous calculations and preview validity. After
using it, continue with **Calculate** and rebuild the preview groups.

### Step 3: Calculate and review the load plan

Click **Calculate**, then open **Preview groups / assignment table**. Each row describes a group:

| Column | What to review |
| --- | --- |
| `group`, `category`, `band` | Which feature and elevation band the objects belong to. |
| `direction`, `role` | Wind direction and windward, leeward, or side treatment. |
| `result_id`, `value` | The calculation result and its pressure, force, or line-load value. |
| `pattern` | The destination load pattern. |
| `members`, `sign` | Number of grouped objects and shell local-axis sign conversion. |

Directions describe where wind acts toward: `+X` wind acts toward global positive X. Group names
identify the treatment; they do not contain numerical pressures. The displayed result value is
not necessarily the signed assignment value sent to ETABS: shell assignments also use the sign
column and convert psf to kip/ft2.

### Step 4: Export a report before applying

Click **Export report** and choose an output folder for this run. Open `report.html` in a browser.
Review calculation results, pressure branches, minimum-load checks, eccentric torsion, combinations,
and **Diagnostics and unresolved items**. This report contains plan diagnostics that are not all
shown in the group table. The GUI's **Config / Diagnostics** tab also lists calculation results
and every plan diagnostic after Calculate.

The reference example uses illustrative cumulative story shears and selects the Max pressure branch
for `-X`, with Min for the other directions. These are example inputs, not general project defaults.
The report will not have read-back verification rows until the plan has been successfully applied.

### Step 5: Create the preview groups

Click **Create/Update preview groups**. Expect **Preview groups created/updated (no loads applied)**.
In offline mode the groups exist only in memory. Selecting a table row and clicking
**Select group in ETABS** records the selection in the fake adapter; it does not open a visual model.

### Step 6: Apply and check read-back

Click **Review & apply**. Review the confirmation dialog, then choose **Yes** to apply the offline
plan. The reference run defines **18 patterns, 20 cases, and 36 combinations**. Assignment counts
depend on the configuration and geometry.

After a successful apply, **Config / Diagnostics** shows **load plan applied**, applied counts,
and verification lines beginning with `OK` or `FAIL`. Expect all checks to be `OK` for the unchanged
reference example. A `FAIL` is a mismatch to investigate, even if the status says the plan applied.

### Step 7: Export the verified run

Click **Export report** again and select the same folder to replace the earlier preview exports,
or a new folder to preserve both versions. Open the HTML report and review **ETABS read-back
verification**. In this walkthrough that section compares against the fake adapter's stored data.

Offline model state is temporary. Restarting the application or clicking **Offline demo** again
creates a fresh demonstration model; exported reports remain on disk.

## 3. Prepare project inputs

Copy [wind_inputs.yaml](../templates/wind_inputs.yaml) to a project-specific file, then edit it in
your text editor. The GUI displays inputs but does not edit them. Keep the template and reference
example available for comparison.

| Section | What to establish for the project |
| --- | --- |
| `schema_version`, `code_edition`, `units` | Currently `1`, `ASCE 7-10`, and `US`. |
| `wind` | Project wind parameters and mean roof height above grade. |
| `geometry` | Whole-model/global-XY scope, dimension source, and linked X/Y plan dimensions. |
| `loading` | Pressure branch for each direction, eccentricity ratio, and reversible mechanical patterns. |
| `grade`, `story_bands` | Model elevation of grade, roof planes, band boundaries, and pressure evaluation heights above grade. Put the main roof plane first. |
| `parapets`, `penthouses` | Actual feature types, footprints, dimensions, and elevations, if present. |
| `equipment`, `platforms` | Equipment dimensions, exactly four existing support joints per unit, and existing platform frame names for each axis, if present. |
| `overrides` | Explicit shell-category overrides only where the default geometry rules need correction. |

The supported dimension sources are:

- `etabs`: use plan dimensions derived from shell geometry; YAML dimensions remain required
  comparison values.
- `yaml`: use YAML plan dimensions for calculations while still using model geometry for
  categorization and assignment.

For either source, Y-wind parallel length must equal X-wind perpendicular width, and Y-wind
perpendicular width must equal X-wind parallel length. Model elevations are absolute model Z
coordinates; evaluation heights and feature elevations labeled above grade use the grade datum.
Shells crossing a roof or pressure-band boundary need subdivision in the model.

`loading.story_shears_kip` is optional and contains cumulative story shears by direction, in kip,
ordered from the top story downward. They remain available as manual inputs. Alternatively, use the
**Shear / Eccentricity** tab to retrieve **Base Reactions** and **Story Forces** after running analysis
in ETABS. The application does not run analysis. Without shear inputs, eccentric patterns remain
empty with warnings; they do not constitute a complete eccentric-wind design.

1. Establish the uneccentric wind loads, then run their static-linear cases in ETABS. Use cases
   representing the current configuration and required wind components, without eccentricity.
2. Inspect and Calculate. In **Shear / Eccentricity**, select a direction and enter the source case
   names, separated by commas. **Fill current wind case names** lists the current plan's component
   cases for that direction; confirm that these are the cases actually analyzed in ETABS.
3. **Extract & review shears** reads results only. It preserves the current load plan, lock state,
   units and database display selections. Envelopes, combinations, incomplete cases, duplicate rows
   and inconsistent story coverage are rejected. Multiple source cases are summed with their signs
   before taking the directional magnitude. Auto-wind eccentric settings are not inferred: the
   selected cases must be uneccentric.
4. Review the raw signed base reactions and Bottom-of-story shears. The multiplier defaults to 1.0;
   change it only to undo a known source reduction. There is no automatic 4/3. Existing W2/W4
   combination factors are unchanged. Base shear is an equilibrium check, not an extra floor force.
5. The table uses `e = ratio * perpendicular width`, `T_i = e * V_i`, and
   `Mz_i = T_i - T_(story above)`. The top target above the building is zero. This is an equivalent
   floor-load idealization using Bottom cuts, for one rigid diaphragm per story. The lowest Bottom
   shear must agree with the base reaction magnitude within 0.1% or 0.01 kip. Mixed-sign or
   downward-decreasing cumulative shears require review instead of automatic assignment.
6. Enter one existing diaphragm joint per story as `ROOF=jointName, L2=jointName`. Each joint must
   be at the corresponding story elevation and assigned to a rigid diaphragm. Semi-rigid or
   multiple-diaphragm layouts require a distributed torsion load path outside this feature.
7. **Use reviewed direction** adopts only that direction's eccentric inputs in the current session.
   It requires scope `all`; it never silently expands `walls_parapets`. If scope must change,
   select it explicitly, Calculate and extract again. Then Calculate, recreate and review preview
   groups, and use the existing Review & apply flow. Applying to a locked model still requires
   the existing unlock confirmation and discards analysis results.

YAML values remain intact. **Return all directions to YAML** restores them. Inspect/re-read,
configuration reload, connection change or scope change clears imported shears and pending reviews.
Exports retain the raw ETABS source, multiplier, floor derivation and reference joints in
`assignment_plan.json` and `report.html`; `effective_config.yaml` retains the original configuration.
Live extraction still needs verification against an analyzed ETABS model.

See [configuration schema and interfaces](module_interfaces.md) for the full contract. The sample
EDB and workbook are described in [examples](../examples/README.md); their presence does not mean
the reference YAML's object mappings match that EDB.

## 4. Connect to ETABS and review a live plan

Live operation is an integration-verification workflow at present. Use a saved working copy of the
model and follow the [ETABS verification checklist](etabs_setup.md). The eccentric-load limitation
above must be resolved before a complete live plan with eccentric assignments can be applied.

### Step 1: Open the intended model

Open the saved working copy in ETABS before connecting. The application attaches to a running
instance; it does not launch ETABS or open an EDB for you. The whole connected model is the target.
Its envelope must represent one supported rectangular building aligned with global X/Y.

### Step 2: Load project YAML and connect

Launch air-apparent and use **Load/Reload YAML...** to select the prepared project file. If multiple
ETABS instances are open, find the intended instance's process ID in Windows Task Manager's Details
tab and enter it in **ETABS pid:**. Click **Connect ETABS**.

With exactly one instance, leaving the PID blank lets the connector select it. Check the model
path, PID, version, units, and lock state in the status message before proceeding. Connection sets
ETABS present units to kip-ft-F. The current GUI does not call the adapter's unit-restoration method
on exit; restore your preferred display units in ETABS when finished.

### Step 3: Inspect and calculate

Click **Inspect** and review categorization diagnostics, the envelope, and derived dimensions.
Correct geometry, mappings, or YAML as needed, then inspect again. Click **Calculate** to build the
plan. Export a report before applying and review all plan diagnostics, not just the group table.
Error-level diagnostics block apply; warnings can still permit an incomplete plan to be applied.

### Step 4: Create groups and inspect members in ETABS

Click **Create/Update preview groups**. This writes `AA_PREVIEW_*` groups and their ownership
manifest but does not assign loads. Select a row in **Preview groups / assignment table**, then
click **Select group in ETABS** and inspect the selected objects in ETABS. Repeat for representative
walls, parapets, penthouses, equipment joints, and platform frames that are present in your model.

Review member locations and shell local axes against the intended direction and treatment. The
selection action clears ETABS's previous object selection. If membership is wrong, correct its
source and rebuild the preview; manual group edits are detected and block apply.

### Step 5: Apply the reviewed plan, when integration is ready

Once the plan has no errors and its loads and warnings have been reviewed, click **Review & apply**.
Check the counts in the confirmation dialog. A locked model triggers a separate prompt: unlocking
discards existing analysis results. Declining that prompt leaves the apply blocked.

The workflow writes patterns, assignments, cases, and combinations, then performs read-back checks.
If a write fails, dependent writes stop and partial counts are reported; prior writes are not rolled
back. Preserve that information and inspect the model before retrying. Live repeat-application
behavior still needs verification even though the offline tests check replacement without load
accumulation.

### Step 6: Verify, export, and save

Review every `OK`/`FAIL` read-back line, export the report, and compare representative loads and
case/combination definitions in ETABS. The automatic checks compare stored loads and definitions
with the plan; they do not run analysis or establish structural adequacy. Analysis and comparison
of resulting forces are separate ETABS checks in the integration checklist.

Save the model in ETABS after accepting the changes; the application does not save the EDB for you.
Keep the adjacent `<model filename>.air_apparent.json` ownership manifest with that model. The tool
uses it to distinguish generated content from unrelated content on later runs. Reopening without
the manifest can produce name conflicts; do not delete it to bypass an ownership check.

## 5. Understand the exported files

**Export report** requires a calculated plan and writes four files to the folder you choose. Using
the same folder again overwrites these files.

| File | Contents |
| --- | --- |
| `effective_config.yaml` | Configuration used by the session, with normalized defaults. |
| `assignment_plan.json` | Pattern, case, and combination definitions; group summaries; individual assignments. |
| `assignment_plan.csv` | One row per assignment with object, pattern, result ID, value, units, direction, and notes. |
| `report.html` | Inputs, calculations, checks, groups, eccentric derivation, combinations, diagnostics, and available read-back verification. |

A report exported before apply describes the proposed loads. Read-back verification is included
only after verification has run. Keep the source YAML as well as the exported files for the run.

## 6. Update inputs or geometry and rerun

After changing YAML, reload it with **Load/Reload YAML...**. The GUI also detects changes to the
file's contents before button actions and reloads it when they change. A timestamp-only change
does not clear the table or invalidate the results. Rebuild dependent results using
**Inspect** -> **Calculate** -> **Create/Update preview groups** -> review -> **Review & apply** ->
**Export report**.

After editing ETABS geometry, click **Inspect** to read it again before calculating. **Calculate**
can reuse an existing snapshot, so clicking Calculate alone does not guarantee fresh geometry.
If YAML changes affect synthetic geometry during an offline run, click **Offline demo** again
before Inspect to regenerate that geometry from the new inputs.

Rebuilding previews removes obsolete owned groups and replaces membership. Reapplying clears
obsolete owned assignments, but does not delete obsolete pattern, case, or combination definitions.
Review leftover definitions separately when the scope changes.

## 7. Troubleshooting

| Symptom or diagnostic | Next action |
| --- | --- |
| `air-apparent` is not recognized or its launcher cannot run | From the repository root, use `.\.venv\Scripts\python.exe -m air_apparent.ui examples/reference_sample.yaml` after installation. |
| `No module named tkinter` | Use a Python installation with Tcl/Tk support. Test it with `.\.venv\Scripts\python.exe -m tkinter`, then close the test window. |
| `Configuration invalid` | Read field-path messages in Config / Diagnostics; correct YAML indentation, keys, types, values, and linked dimensions, then reload. |
| Unsupported code edition | The pressure calculator supports ASCE 7-10 only; other editions require implementation. |
| No ETABS instances / select a PID | Open the saved model in ETABS; identify the intended PID when multiple instances exist. |
| `comtypes is required` | Install the `[etabs]` extra into the same environment used to launch the GUI. |
| `unsupported_layout` / unresolved objects | Inspect the envelope and affected objects. Check rectangular/global-XY scope and feature mappings; unresolved objects receive no loads. |
| `needs_subdivision` | Subdivide the indicated shells at the reported boundary in ETABS, then Inspect and Calculate again. |
| `dimension_discrepancy` | Compare envelope dimensions with YAML and confirm the chosen dimension source. |
| `missing_support_joint` / `missing_platform_frame` | Check unique object names and mappings against the connected model. |
| `ecc_no_shears` | The eccentric pattern is empty. Establish the shear inputs and reference-joint path before relying on it. |
| `ecc_no_reference_joint` | Supply and validate the story's existing rigid-diaphragm joint in Shear / Eccentricity when adopting analyzed shears. |
| Preview missing/outdated or membership differs | Recalculate if inputs changed, recreate preview groups, and review membership again. |
| `group_name_conflict` / `name_conflict` | Check that the model and ownership manifest belong together. Resolve unrelated name collisions deliberately; do not remove unrelated content or the manifest merely to bypass the check. |
| Plan has errors, but the cause is unclear | Read Config / Diagnostics after Calculate, or export `report.html` and read Diagnostics and unresolved items. |
| Apply stops partway | Record the failure and partial counts; inspect what changed. No rollback is performed. |
| Read-back shows `FAIL` | Compare expected/actual values and definitions before accepting the result; retain the report for diagnosis. |
| Export produces nothing | Click Calculate first to create a plan, then choose an output folder. |

For module interactions see [module interfaces](module_interfaces.md). For engineering assumptions
and exclusions see [engineering basis](engineering_basis.md) and [limitations](limitations.md).
