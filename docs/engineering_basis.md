# Engineering basis

Scope: ASCE 7-10 horizontal MWFRS only. Verification status uses three separate levels:

1. **Workbook agreement** - results reproduce the reference workbook (`tests/fixtures/workbook_benchmarks.json`,
   26 cells with source cells, relative tolerance 1e-8). Done.
2. **Independent engineering check** - agreement with the authoritative ASCE 7-10 text. **Pending.**
   The code references below are those recorded in the workbook; they are not yet confirmed.
3. **Live ETABS integration** - geometry, API unit handling, preview groups, selection, and existing
   load read-back were checked against ETABS 23.3.1. Load application and analysis remain unverified
   because the model/configuration has unresolved layout and object-mapping diagnostics (see
   `etabs_setup.md`).

## Workbook references (unverified)

| Sheet | Recorded references |
| --- | --- |
| Chp 26 | Table 1.5-1; Fig. 26.5-1; Sec. 26.6 and Table 26.6-1; Secs. 26.7, 26.8, 26.9, 26.11; Fig. 26.8-1 |
| Chp 27 | Table 26.9-1; Table 27.3-1 Note 1; Eq. 27.3-1; Fig. 27.4-1; Eq. 27.4-1; Sec. 27.4.5 |
| Chp 29 | Sec. 29.5 and Fig. 29.5-1 (rooftop); Sec. 27.4.5 (penthouse parapets) |

To verify against an authoritative source: the workbook label "Fig. 26.11-1" (and whether it is
Fig. 26.8-1 or another figure); whether more specific rooftop provisions govern the Sec. 29.5
calculations; and the 16 psf minimum-load requirement (Sec. 27.4.7), which is implemented only
approximately (external pressures) and flagged `independent_check_pending`. No code pages or
figures are reproduced.

## Implemented

- Velocity pressure: `Kz = 2.01 (max(z,15)/zg)^(2/alpha)`, `qz = 0.00256 Kz Kzt Kd V^2` (Exposure B/C/D
  constants). Workbook: Kh = 1.1444475264, qh = 35.8605765708 psf at 62 ft.
- Walls: `p = q G Cp - qh GCpi_signed`. Branch labels: `Ext. Only` (GCpi = 0), `Max` = external +
  qh|GCpi| (signed GCpi = -|GCpi|), `Min` = external - qh|GCpi| (signed GCpi = +|GCpi|). The signed
  value is reported with each result. "Min" is a branch label, not the code minimum load. Windward
  Cp = 0.8, side Cp = -0.7, leeward Cp interpolated on L/B. Windward pressure uses two evaluation
  heights (L2 31.5 ft and roof 62 ft); this story-band approximation is explicit in the results.
- One branch per wind direction from YAML (project example: -X = Max, others Min); a single internal
  pressure sign is used for all surfaces in the same loading state. Leeward net pressure can be positive
  (e.g. X leeward Max = +0.3586 psf); signs are converted to ETABS convention explicitly.
- Parapets: `p = qp GCpn` (+1.5 windward, -1.0 leeward, no internal pressure), `qp` at the top elevation
  above grade. Main-roof, picture-frame and penthouse parapets are separate types. Loaded area uses
  height above the supporting roof.
- Penthouses: net body pressure assigned to the windward body face only; side pressures (from the
  selected branch) go in `W_Wall` on penthouse side shells without duplicating leeward/body force.
- Rooftop (penthouse, platform, equipment): `p = qz(centroid) G Cf` with `Cf = 1.3`. This was
  **back-solved from the workbook** and is unverified against Sec. 29.5. Penthouse PH2's centroid
  elevation (69.4896416531 ft) was likewise back-solved from I17; confirm from the real model.
- Equipment: `F = p h extent / 1000` kip, split equally over four existing joints (joint loads).
  Platform members get uniform line loads on frames. **Overturning moments are not included.**
  Force conservation and duplicate mappings are checked.
- Eccentric torsion: `e = 0.15 x B_perp`; cumulative target `T = V e`; applied floor moment =
  target at this story - target at the story above. Shear source, ratio, length and reference axis
  are recorded. Provisional; inherent torsion and diaphragm distribution are not verified.
- Mechanical patterns: two reversible patterns; reversibility of all assignments is verified.
