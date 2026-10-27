"""Synthetic offline demonstration model built from a configuration.

The geometry is invented for demonstration/testing (a rectangular building with perimeter
panels, parapets, two penthouses, platform frames and chillers). It is NOT project data.
"""

from __future__ import annotations

from .models import (
    Config,
    Frame,
    Joint,
    ModelSnapshot,
    Shell,
    Story,
)


def _wall(name, p0, p1, z0, z1, local3):
    (x0, y0), (x1, y1) = p0, p1
    return Shell(name, ((x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1)), local3)


def _edge_panels(prefix, lo, hi, n, fixed, axis, z0, z1, normal, flip_every=0):
    """Panels along a face. axis 'y' means a face of constant y (running along X)."""
    out = []
    step = (hi - lo) / n
    for i in range(n):
        a, b = lo + i * step, lo + (i + 1) * step
        p0, p1 = ((a, fixed), (b, fixed)) if axis == "y" else ((fixed, a), (fixed, b))
        flip = flip_every and i % flip_every == 1
        n3 = normal if flip else tuple(-c for c in normal)
        out.append(_wall(f"{prefix}{i + 1}", p0, p1, z0, z1, n3))
    return out


def build_demo_snapshot(cfg: Config) -> ModelSnapshot:
    lx = cfg.geometry.x_wind.parallel_l
    ly = cfg.geometry.x_wind.perpendicular_b
    grade = cfg.grade_datum_model_elevation_ft
    roof = cfg.roof_planes[0].model_elevation_ft
    shells: list[Shell] = []
    faces = (
        ("S", "y", 0.0, lx, 8, (0, -1.0, 0)), ("N", "y", ly, lx, 8, (0, 1.0, 0)),
        ("W", "x", 0.0, ly, 2, (-1.0, 0, 0)), ("E", "x", lx, ly, 2, (1.0, 0, 0)),
    )
    for tag, axis, fixed, span, n, normal in faces:
        for b in cfg.story_bands:
            shells += _edge_panels(f"W_{tag}_{b.id}_", 0.0, span, n, fixed, axis,
                                   b.bottom_model_elevation_ft, b.top_model_elevation_ft, normal,
                                   flip_every=2 if tag == "E" else 0)
        pf = next((p for p in cfg.parapets if p.kind == "picture_frame"), None)
        typ = next((p for p in cfg.parapets if p.kind == "main_roof"), None)
        ptype = pf if (tag in ("W", "E") and pf) else typ
        if ptype:
            shells += _edge_panels(f"P_{tag}_", 0.0, span, n, fixed, axis, roof,
                                   ptype.top_elevation_above_grade_ft + grade, normal)
    # interior wall (excluded) and a floor slab (excluded)
    shells.append(_wall("INT_1", (lx / 2, 0.0), (lx / 2, ly), 0.0, cfg.story_bands[0].top_model_elevation_ft,
                        (1.0, 0, 0)))
    shells.append(Shell("SLAB_L2", ((0, 0, 31.5), (lx, 0, 31.5), (lx, ly, 31.5), (0, ly, 31.5)),
                        (0, 0, 1.0)))
    php = {p.id: p for p in cfg.parapets}
    for ph in cfg.penthouses:
        top = ph.base_model_elevation_ft + ph.body_height_ft
        ptop = php[ph.parapet_type].top_elevation_above_grade_ft + grade if ph.parapet_type else None
        for tag, p0, p1, normal in (
            ("S", (ph.x_min, ph.y_min), (ph.x_max, ph.y_min), (0, -1.0, 0)),
            ("N", (ph.x_min, ph.y_max), (ph.x_max, ph.y_max), (0, 1.0, 0)),
            ("W", (ph.x_min, ph.y_min), (ph.x_min, ph.y_max), (-1.0, 0, 0)),
            ("E", (ph.x_max, ph.y_min), (ph.x_max, ph.y_max), (1.0, 0, 0)),
        ):
            inward = tuple(-c for c in normal)
            shells.append(_wall(f"{ph.id}_{tag}", p0, p1, ph.base_model_elevation_ft, top, inward))
            if ptop:
                shells.append(_wall(f"{ph.id}_P_{tag}", p0, p1, top, ptop, inward))

    frames: list[Frame] = []
    for pl in cfg.platforms:
        z = pl.centroid_elevation_above_grade_ft - 1.0 + grade
        x0, y0, w = 20.0, 100.0, pl.min_plan_dimension_ft
        corners = {"A": ((x0, y0), (x0, y0 + w)), "B": ((x0 + w, y0), (x0 + w, y0 + w)),
                   "C": ((x0, y0), (x0 + w, y0)), "D": ((x0, y0 + w), (x0 + w, y0 + w))}
        for n in pl.frames_x_wind + pl.frames_y_wind:
            (a, b), (c, d) = corners[n[-1]]
            frames.append(Frame(n, (a, b, z), (c, d, z)))
    joints: list[Joint] = []
    for i, eq in enumerate(cfg.equipment):
        x0, y0 = 150.0 + 70.0 * i, 150.0
        z = eq.centroid_elevation_above_grade_ft - eq.height_ft / 2 + grade
        pts = [(x0, y0), (x0 + eq.extent_x_ft, y0), (x0, y0 + eq.extent_y_ft),
               (x0 + eq.extent_x_ft, y0 + eq.extent_y_ft)]
        joints += [Joint(n, (x, y, z)) for n, (x, y) in zip(eq.support_joints, pts, strict=True)]
    stories = []
    for b in reversed(cfg.story_bands):
        jn = f"CEN_{b.id}"
        joints.append(Joint(jn, (lx / 2, ly / 2, b.top_model_elevation_ft)))
        stories.append(Story(b.id, b.top_model_elevation_ft, diaphragm=f"D_{b.id}", reference_joint=jn))
    return ModelSnapshot(
        shells=shells, frames=frames, joints=joints, stories=stories,
        groups={"OLD_WALLS": ["A:W_S_L2_1"], "USER_GROUP": ["A:INT_1"]},
    )
