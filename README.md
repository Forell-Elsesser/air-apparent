# air-apparent

Desktop tool that calculates **ASCE 7-10 horizontal MWFRS wind loads** for rectangular data-center
buildings (precast perimeter walls, interior concrete frame, rooftop penthouses, parapets,
mechanical platforms) and assigns them to an open **ETABS** model through the ETABS API.

> Status: initial PR. Offline calculations, categorization, preview groups, load plan, patterns,
> cases and combinations are implemented and tested against the reference workbook. **Live ETABS
> operation has not been verified** (see [docs/etabs_setup.md](docs/etabs_setup.md)). W_Ecc and the
> W1-W4 combinations are provisional project definitions, not yet engineering-reviewed.

## Install and test (no ETABS needed)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # live ETABS on Windows: pip install -e ".[dev,etabs]"
ruff check .
pytest
```

## Run

See the [user guide](docs/user_guide.md) for installation, the complete offline walkthrough,
project input preparation, live ETABS steps, exports, and troubleshooting.

```bash
air-apparent examples/reference_sample.yaml     # Tkinter GUI (needs a Python build with tkinter)
```

In the GUI: *Load/Reload YAML* -> *Offline demo* (or *Connect ETABS*) -> *Inspect* -> *Calculate* ->
*Create/Update preview groups* -> inspect groups in ETABS (*Select group*) -> *Review & apply* ->
*Export report*. YAML is the only source of wind inputs; the GUI displays the effective
configuration and never edits it. Editing the YAML file invalidates previews and calculations.

Scripted use:

```python
from air_apparent.workflow import WindSession
s = WindSession(); s.load_config("examples/reference_sample.yaml"); s.use_offline_demo()
s.read_model(); s.calculate(); s.build_plan(); s.create_preview_groups()
print(s.apply().message, [v.ok for v in s.verify()])
```

## Layout

| Path | Purpose |
| --- | --- |
| `src/air_apparent/models.py` | shared dataclasses and stable-ID helpers |
| `config.py` | YAML loading/validation (schema v1) |
| `pressures/` | ASCE 7-10 pressures, equipment forces, eccentric torsion |
| `categorization/` | whole-model shell/frame/joint categories, face roles, preview groups |
| `patterns/` | pattern/case definitions and assignment plan |
| `combinations/` | W1-W4 combination specs |
| `etabs/` | adapter protocol, in-memory fake, optional COM adapter |
| `workflow.py`, `reporting.py`, `ui.py` | orchestration, exports, Tkinter UI |
| `templates/wind_inputs.yaml`, `examples/reference_sample.yaml` | starting template, workbook benchmark |

Docs: [user guide](docs/user_guide.md), [engineering basis](docs/engineering_basis.md),
[module interfaces](docs/module_interfaces.md),
[ETABS setup](docs/etabs_setup.md), [limitations](docs/limitations.md).

Examples: [sample calculation and ETABS assignment walkthrough](examples/README.md),
including the reference workbook, sample EDB model, and worked benchmark calculations.

## Scope

Horizontal MWFRS for one principal rectangular building (the entire connected model). Roof uplift,
full C&C design and gravity-plus-wind design combinations are **out of scope**. See
[limitations](docs/limitations.md).

License: MIT.
