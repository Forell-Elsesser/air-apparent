"""ASCE 7-10 horizontal MWFRS pressures for the rectangular enclosed-building MVP.

Scope: walls (windward/leeward/side), MWFRS parapets, rooftop penthouse bodies,
equipment and platform members. Roof uplift and C&C are out of scope.
References are section numbers only; no code text or figures are reproduced.
Status of each result: see docs/engineering_basis.md.
"""

from __future__ import annotations

from ..models import (
    BRANCHES,
    CalcResult,
    Config,
    PlanDims,
    PressureSet,
    parapet_result_id,
    ph_result_id,
    wall_result_id,
)

EXPOSURE = {"B": (7.0, 1200.0), "C": (9.5, 900.0), "D": (11.5, 700.0)}  # (alpha, zg ft)
CP_WINDWARD = 0.8
CP_SIDE = -0.7
GCPN_WINDWARD = 1.5
GCPN_LEEWARD = -1.0
REF_KZ = "Table 26.9-1 / Eq. 27.3-1"


def kz(z_ft: float, exposure: str) -> float:
    alpha, zg = EXPOSURE[exposure]
    return 2.01 * (max(z_ft, 15.0) / zg) ** (2.0 / alpha)


def qz(z_ft: float, cfg: Config) -> float:
    w = cfg.wind
    return (0.00256 * kz(z_ft, w.exposure_category) * w.topographic_factor_kzt
            * w.directionality_factor_kd * w.basic_wind_speed_mph**2)


def leeward_cp(l_over_b: float) -> float:
    """Leeward wall Cp, linearly interpolated in L/B (-0.5 at <=1, -0.3 at 2, -0.2 at >=4)."""
    pts = [(1.0, -0.5), (2.0, -0.3), (4.0, -0.2)]
    if l_over_b <= pts[0][0]:
        return pts[0][1]
    if l_over_b >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if x0 <= l_over_b <= x1:
            return y0 + (y1 - y0) * (l_over_b - x0) / (x1 - x0)
    raise AssertionError("unreachable")


def signed_gcpi(branch: str, gcpi_abs: float) -> float:
    """Signed GCpi in p = q*G*Cp - qi*GCpi for each workbook branch label."""
    return {"Ext. Only": 0.0, "Max": -gcpi_abs, "Min": +gcpi_abs}[branch]


def calculate(cfg: Config, dims: dict[str, PlanDims]) -> PressureSet:
    ps = PressureSet(edition="ASCE 7-10", dims=dict(dims))
    w = cfg.wind
    g = w.gust_effect_factor_g
    h = w.mean_roof_height_above_grade_ft
    qh = qz(h, cfg)
    ps.add(CalcResult("KH", "Velocity pressure exposure coefficient at mean roof height",
                      kz(h, w.exposure_category), "-", REF_KZ,
                      {"h_ft": h, "exposure": w.exposure_category}))
    ps.add(CalcResult("QH", "Velocity pressure at mean roof height", qh, "psf", "Eq. 27.3-1",
                      {"h_ft": h, "V_mph": w.basic_wind_speed_mph, "Kd": w.directionality_factor_kd,
                       "Kzt": w.topographic_factor_kzt}))

    def wall(rid: str, desc: str, q: float, cp: float, branch: str, ref: str, extra: dict) -> None:
        gcpi = signed_gcpi(branch, w.internal_pressure_coefficient_abs)
        p = q * g * cp - qh * gcpi
        ps.add(CalcResult(
            rid, desc, p, "psf", ref,
            {"q_psf": q, "G": g, "Cp": cp, "qi_psf": qh, "GCpi_signed": gcpi, "branch": branch,
             "equation": "p = q*G*Cp - qi*GCpi", **extra},
            notes="positive = pressure toward the surface; branch label is not the code minimum load",
        ))

    for band in cfg.story_bands:
        qb = qz(band.evaluation_height_above_grade_ft, cfg)
        ps.add(CalcResult(f"QZ_{band.id}", f"Velocity pressure for band {band.id}", qb, "psf",
                          "Eq. 27.3-1", {"z_ft": band.evaluation_height_above_grade_ft},
                          notes="story-band approximation: windward evaluated at one height per band"))
        for br in BRANCHES:
            wall(wall_result_id("WW", band.id, br), f"Windward wall, band {band.id}, {br}", qb,
                 CP_WINDWARD, br, "Fig. 27.4-1", {"z_ft": band.evaluation_height_above_grade_ft})
    for axis, key in (("X", "X"), ("Y", "Y")):
        d = dims[axis]
        lb = d.parallel_l / d.perpendicular_b
        cp = leeward_cp(lb)
        ps.add(CalcResult(f"LEEWARD_CP_{axis}", f"Leeward wall Cp, {axis} wind", cp, "-",
                          "Fig. 27.4-1", {"L_ft": d.parallel_l, "B_ft": d.perpendicular_b, "L/B": lb}))
        for br in BRANCHES:
            wall(wall_result_id(f"LW_{key}", "", br), f"Leeward wall, {axis} wind, {br}", qh, cp, br,
                 "Fig. 27.4-1", {"L/B": lb})
    for br in BRANCHES:
        wall(wall_result_id("SIDE", "", br), f"Side wall, {br}", qh, CP_SIDE, br, "Fig. 27.4-1", {})

    # Parapets (MWFRS, Section 27.4.5): p = qp * GCpn at top of parapet; no internal pressure.
    for pt in cfg.parapets:
        qp = qz(pt.top_elevation_above_grade_ft, cfg)
        for role, gc in (("WINDWARD", GCPN_WINDWARD), ("LEEWARD", GCPN_LEEWARD)):
            ps.add(CalcResult(
                parapet_result_id(pt.id, role), f"{pt.kind} parapet {pt.id} {role.lower()}",
                qp * gc, "psf", "Section 27.4.5",
                {"qp_psf": qp, "GCpn": gc, "top_elevation_above_grade_ft": pt.top_elevation_above_grade_ft,
                 "height_above_roof_ft": pt.height_above_roof_ft},
                notes="loaded area = parapet shell area; top elevation is above grade"))

    cf = cfg.rooftop_net_force_coefficient_cf
    rt_ref = "Section 29.5 / Fig. 29.5-1 (unverified)"
    rt_note = "p = qz*G*Cf, Cf from YAML; reproduces workbook; applicability of 29.5 unverified"
    for ph in cfg.penthouses:
        z = ph.centroid_elevation_above_grade_ft
        ps.add(CalcResult(ph_result_id(ph.id), f"Penthouse {ph.id} net along-wind pressure",
                          qz(z, cfg) * g * cf, "psf", rt_ref,
                          {"z_ft": z, "G": g, "Cf": cf, "min_plan_dimension_ft": ph.min_plan_dimension_ft,
                           "body_height_ft": ph.body_height_ft}, notes=rt_note))
    for pl in cfg.platforms:
        p = qz(pl.centroid_elevation_above_grade_ft, cfg) * g * cf
        ps.add(CalcResult(f"PLAT_{pl.id}_P", f"Platform {pl.id} pressure", p, "psf", rt_ref,
                          {"z_ft": pl.centroid_elevation_above_grade_ft, "G": g, "Cf": cf}, notes=rt_note))
        ps.add(CalcResult(f"PLAT_{pl.id}_LINE", f"Platform {pl.id} line load", p * pl.exposed_depth_ft,
                          "plf", rt_ref, {"exposed_depth_ft": pl.exposed_depth_ft}, notes=rt_note))
    for eq in cfg.equipment:
        p = qz(eq.centroid_elevation_above_grade_ft, cfg) * g * cf
        ps.add(CalcResult(f"EQ_{eq.id}_P", f"Equipment {eq.id} pressure", p, "psf", rt_ref,
                          {"z_ft": eq.centroid_elevation_above_grade_ft, "G": g, "Cf": cf}, notes=rt_note))
        for axis, width in (("X", eq.extent_y_ft), ("Y", eq.extent_x_ft)):
            area = eq.height_ft * width
            ps.add(CalcResult(f"EQ_{eq.id}_F{axis}", f"Equipment {eq.id} {axis}-wind resultant",
                              p * area / 1000.0, "kip", rt_ref,
                              {"projected_area_ft2": area, "pressure_psf": p},
                              notes="resultant only; overturning moment not included"))

    _minimum_load_checks(cfg, ps, dims)
    return ps


def _minimum_load_checks(cfg: Config, ps: PressureSet, dims: dict[str, PlanDims]) -> None:
    """Separate check against the 16 psf minimum (Section 27.4.7), external pressures only.

    Windward is height-weighted over bands; the internal pressure cancels in the net.
    """
    total_h = sum(b.top_model_elevation_ft - b.bottom_model_elevation_ft for b in cfg.story_bands)
    for axis in ("X", "Y"):
        ww = sum(ps.value(wall_result_id("WW", b.id, "Ext. Only"))
                 * (b.top_model_elevation_ft - b.bottom_model_elevation_ft)
                 for b in cfg.story_bands) / total_h
        lw = ps.value(wall_result_id(f"LW_{axis}", "", "Ext. Only"))
        net = ww - lw
        ps.checks.append(CalcResult(
            f"MIN_LOAD_{axis}", f"Minimum wall load check, {axis} wind", net, "psf", "Section 27.4.7",
            {"limit_psf": 16.0, "passes": net >= 16.0, "windward_avg_psf": ww, "leeward_psf": lw},
            notes="approximate whole-wall check on external pressures; independent of Min/Max labels",
            status="independent_check_pending"))
