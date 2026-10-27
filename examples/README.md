# Sample calculation and ETABS assignment example

These files illustrate the wind-load calculation and assignment workflow:

| File | Purpose |
| --- | --- |
| [Data Center Wind Loading (ASCE 7-10).xlsx](<Data Center Wind Loading (ASCE 7-10).xlsx>) | Sample calculation workbook for the ASCE 7-10 wind-loading process. |
| [Test Model.EDB](<Test Model.EDB>) | Sample ETABS model illustrating load assignments and treatment of the process. |
| [reference_sample.yaml](reference_sample.yaml) | Runnable inputs for the application's offline benchmark and synthetic demo geometry. |

The workbook supplies calculation context; the EDB supplies a model-based example of
how the loads are assigned. Inclusion of the model does not establish that the
application generated its existing assignments or that the live ETABS adapter has
been verified. The YAML's synthetic object names, geometry, and placeholder story
shears have not been established as a direct mapping to `Test Model.EDB`.

## Sample calculation

The following worked values are recorded in the repository's
[workbook benchmark fixture](../tests/fixtures/workbook_benchmarks.json) and
[engineering basis](../docs/engineering_basis.md). They describe the existing
benchmark; they are not a new independent review of the workbook or the EDB.

The reference inputs are wind speed V = 120 mph, Exposure C, Kd = 0.85,
Kzt = 1.0, gust factor G = 0.85, enclosed internal pressure coefficient
|GCpi| = 0.18, and mean roof height h = 62 ft. The plan dimensions are
1,472 ft by 240 ft; see `Chp 26` and the YAML comments for input-cell references.

1. **Roof velocity pressure.** Using Kh = 1.1444475264 (`Chp 27!B10`):

   `qh = 0.00256 * Kh * Kzt * Kd * V^2 = 35.8605765708 psf`

   This is the benchmark for `Chp 27!B11`.

2. **Roof windward wall, Min branch.** With Cp = 0.8 and signed GCpi = +0.18:

   `p = qh * G * Cp - qh * GCpi = 17.9302882854 psf`

   This matches the recorded `Chp 27!D53` benchmark. The Max branch uses signed
   GCpi = -0.18 and gives 30.8400958509 psf (`Chp 27!D52`). "Min" and "Max"
   are internal-pressure branch names. The sample YAML selects Max for -X and
   Min for the other directions; that selection is a sample project choice.

3. **Equipment force and joint distribution.** The benchmark equipment pressure
   is 41.4753318196 psf (`Chp 29!I19`). For an 8.5 ft high unit with plan
   extents of 56 ft in X and 10 ft in Y:

   `Fx = 41.4753318196 * 8.5 * 10 / 1000 = 3.5254032047 kip`

   `Fy = 41.4753318196 * 8.5 * 56 / 1000 = 19.7422579461 kip`

   These reproduce the recorded `Chp 29!B23:B24` values. The application's
   example splits each directional force equally across four support joints:
   approximately 0.881351 kip per joint for X or 4.935564 kip per joint for Y.
   These are alternative directional load cases. Equipment overturning moments
   are not included in the current implementation.

## Relating the calculations to model assignments

Use a working copy of the EDB in ETABS. Review the model's units, object local
axes, load patterns, cases, combinations, and assigned loads before interpreting
the example. Compare wall and parapet pressures, equipment joint forces, and
platform line loads with the corresponding workbook calculations. Shell pressure
signs depend on local axis 3; a workbook pressure sign alone does not establish
the correct ETABS assignment direction. The adapter converts psf to kip/ft2 and
plf to kip/ft when working in kip-ft units.

To reproduce the application's separate offline example, install the package as
described in the [main README](../README.md), then run:

```powershell
air-apparent examples/reference_sample.yaml
```

Choose **Offline demo**, **Inspect**, and **Calculate**, then review the load plan
and exported report. To use the supplied EDB with the application, first establish
the actual geometry, object mappings, roof elevations, equipment supports, and
story-shear inputs; the offline YAML is not a ready-to-apply configuration for it.
Follow the [ETABS setup and verification checklist](../docs/etabs_setup.md) for
live integration.

Workbook agreement, independent engineering review, and live ETABS verification
are separate checks. See the [engineering basis](../docs/engineering_basis.md)
and [limitations](../docs/limitations.md) for the current status, including the
provisional eccentric-torsion and W1-W4 definitions.
