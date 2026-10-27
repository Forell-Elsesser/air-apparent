# Limitations (initial PR)

- **Scope:** horizontal MWFRS only. No roof uplift, no C&C design, no automatic gravity-plus-wind
  design combinations. Earlier C&C parapet assignments are historical and are not used.
- **Edition:** ASCE 7-10 only. Any other `code_edition` raises `UnsupportedEditionError`; it is never
  mapped to ASCE 7-10. New editions are added by registering a module in
  `air_apparent.pressures.SUPPORTED_EDITIONS`.
- **Layout:** one principal rectangular building = the whole model. Non-rectangular or multi-block
  layouts, non-axis-aligned walls, and stray exterior objects are reported (`unsupported_layout`,
  `UNRESOLVED` group); the model is never split into blocks automatically.
- **Subdivision:** shells crossing a roof plane or a pressure-band boundary are reported with the
  required subdivision and receive no load.
- **Story-band approximation:** windward pressure is evaluated at one height per band (workbook:
  L2 = 31.5 ft, roof = 62 ft).
- **Rooftop coefficient:** `p = qz*G*Cf` with `Cf = 1.3` (YAML) reproduces the workbook but its
  correspondence to ASCE 7-10 Section 29.5 / Fig. 29.5-1 is **unverified**. The recorded minimum plan
  dimensions are stored but not used by the calculation.
- **Equipment overturning moments are NOT included.** Four equal horizontal joint forces at the
  support plane do not reproduce the support reactions of a force acting above that plane.
- **Eccentricity (`W_Ecc_d`)** needs cumulative story shears from YAML (or, later, fresh ETABS
  results). The placeholder values in `examples/reference_sample.yaml` are illustrative. The applied
  floor moment is placed at each story's diaphragm reference joint; distribution for the model's
  actual diaphragm type (rigid/semi-rigid) and inherent torsion are not verified. W_Ecc and W1-W4 are
  provisional.
- **Stair projections** are categorized (override only) but no wind treatment is defined.
- **Model-coordination issues** (missing platform frame, missing mechanical gravity loads, grid/floor
  load changes) are not repaired. Only configured support joints and platform frames are checked for
  existence (`missing_support_joint`, `missing_platform_frame`); there is no check for unconfigured
  missing members.
- **Envelope combinations** give independent extrema, not one simultaneous load state; concurrent
  force vectors are preserved only in the individual linear combinations.
- **Live ETABS:** not verified. See `docs/etabs_setup.md`.
- No rollback is implemented: a failed apply reports exactly what was done and stops dependent writes.
