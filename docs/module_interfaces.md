# Module interfaces

All shared dataclasses live in `src/air_apparent/models.py`. Core modules import only `models`
(never the GUI or live ETABS). Objects are referenced by stable refs: `A:<shell>`, `F:<frame>`,
`P:<joint>`. Calculation results carry stable IDs (e.g. `WALL_WW_L2_MIN`, `WALL_LW_X_MAX`,
`WALL_SIDE_MIN`, `PARAPET_TYP_WW`, `PH_PH1_NET`, `PLAT_PL1_LINE`, `EQ_CHILLER01_FX`) that are used
by groups and assignments. Group names never contain pressure values.

Shared fixtures: `tests/conftest.py` (`cfg`, `snap`, `session`) builds the reference config and a
synthetic offline model (`air_apparent.demo`) so each module can be developed and tested alone.

| Module | Input | Output | Example |
| --- | --- | --- | --- |
| `pressures` | `Config` (+ optional dims) | `PressureSet` (results with value, unit, references, source cells, status) | `calculate_pressures(cfg).value("WALL_SIDE_MIN")` |
| `categorization` | `Config`, `ModelSnapshot` | `Categorization` (object categories, face roles per direction, derived dims, diagnostics) and `list[GroupSpec]` | `cats = categorize(cfg, snap); build_group_specs(cfg, snap, cats)` |
| `patterns` | `Config`, `ModelSnapshot`, `Categorization`, `PressureSet` | `pattern_specs()`, `case_specs()`, `LoadPlan` (assignments incl. eccentric moments) | `build_plan(cfg, snap, cats, ps).assignments` |
| `combinations` | none (pure definitions) | `list[CombinationSpec]` (linear W1-W4 plus envelopes) | `build_combinations()` |

```python
from air_apparent.config import load_config
from air_apparent.demo import build_demo_snapshot
from air_apparent.pressures import calculate_pressures
from air_apparent.categorization import categorize
from air_apparent.patterns import build_plan
cfg = load_config("examples/reference_sample.yaml")
snap = build_demo_snapshot(cfg)
cats = categorize(cfg, snap); ps = calculate_pressures(cfg)
plan = build_plan(cfg, snap, cats, ps)
```

Family/direction conventions: `d` in `+X, -X, +Y, -Y` is the direction the wind acts toward.
A face whose outward normal is `-d` is windward. Patterns: `W_Wall_d`, `W_Parapet_d`, `W_PH_d`,
`W_Ecc_d`, `W_Mech_X`, `W_Mech_Y` (18 total); cases are one per pattern with a factor of 1.0 plus
`W_Mech_+X/-X/+Y/-Y` = +/-1.0 x `W_Mech_X/Y` (20 total). Counts are generated from definitions.
Combinations: W1 (4 + envelope), W2 (8), W3 (4), W4 (16) with factors 1.0 / 0.75 / 0.75 / 0.5625,
each family followed by a `Wn_ENV` envelope. They are provisional project definitions.

## YAML configuration schema (version 1)

Unknown keys, duplicate keys, wrong types/units and out-of-range or disallowed values are reported
with field paths (e.g. `wind.exposure_category`). Safe loading only.

Required: `schema_version` (1), `code_edition`, `units` ("US"), `wind.*` (all of Chp 26 B6, B9-B15,
B18), `geometry.{target: entire_model, wind_axes: global_xy, plan_dimensions_source: etabs|yaml,
plan_dimensions_ft.{x_wind,y_wind}.{parallel_l,perpendicular_b}}`,
`loading.{wall_pressure_branch_by_direction, eccentricity_ratio, mechanical_patterns}`.

Linked workbook cells: `Chp 26!C21 = B22` and `C22 = B21`, so `y_wind.parallel_l` must equal
`x_wind.perpendicular_b` and `y_wind.perpendicular_b` must equal `x_wind.parallel_l`
(validated). When `plan_dimensions_source` is `etabs` the YAML values are comparison values only and
discrepancies against the derived envelope are reported; with `yaml` they are the active values.

Optional sections: `grade` (datum and `roof_planes`; model elevations are distinct from heights above
grade), `story_bands`, `parapets.types`, `penthouses`, `rooftop.net_force_coefficient_cf`,
`platforms`, `equipment`, `overrides` (object name -> category), `loading.story_shears_kip`.
See `templates/wind_inputs.yaml` for commented examples.
