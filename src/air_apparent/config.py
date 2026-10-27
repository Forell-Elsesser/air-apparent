"""YAML configuration loading and validation (schema version 1).

YAML is the authoritative source of wind parameters. Errors are reported with field
paths such as ``wind.basic_wind_speed_mph``. Loading uses ``yaml.SafeLoader`` and
rejects duplicate keys and unknown keys.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

import yaml

from .models import (
    BRANCHES,
    CATEGORIES,
    DIRECTIONS,
    Config,
    Equipment,
    GeometryConfig,
    LoadingConfig,
    ParapetType,
    Penthouse,
    PlanDims,
    Platform,
    RoofPlane,
    StoryBand,
    WindInputs,
)

SCHEMA_VERSION = 1
PARAPET_KINDS = ("main_roof", "picture_frame", "penthouse")


class ConfigError(ValueError):
    """Raised with every validation problem found, each prefixed by its field path."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


class _Checker:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, path: str, msg: str) -> None:
        self.errors.append(f"{path}: {msg}")

    def mapping(self, d: Any, path: str, required: tuple[str, ...], optional: tuple[str, ...] = ()):
        if not isinstance(d, dict):
            self.err(path, "must be a mapping")
            return {}
        for k in d:
            if k not in required and k not in optional:
                self.err(f"{path}.{k}" if path else str(k), "unknown key")
        for k in required:
            if k not in d:
                self.err(f"{path}.{k}" if path else k, "required value is missing")
        return d

    def number(self, d: dict, key: str, path: str, *, positive=False, minimum=None, maximum=None,
               default=None) -> float:
        p = f"{path}.{key}" if path else key
        if key not in d:
            if default is not None:
                return default
            return math.nan
        v = d[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            self.err(p, f"must be a finite number, got {v!r}")
            return math.nan
        if positive and v <= 0:
            self.err(p, f"must be > 0, got {v}")
        if minimum is not None and v < minimum:
            self.err(p, f"must be >= {minimum}, got {v}")
        if maximum is not None and v > maximum:
            self.err(p, f"must be <= {maximum}, got {v}")
        return float(v)

    def choice(self, d: dict, key: str, path: str, allowed: tuple, default=None):
        p = f"{path}.{key}" if path else key
        if key not in d:
            return default if default is not None else None
        v = d[key]
        if v not in allowed:
            self.err(p, f"must be one of {list(allowed)}, got {v!r}")
        return v

    def string(self, d: dict, key: str, path: str, default: str | None = None) -> str:
        p = f"{path}.{key}" if path else key
        if key not in d:
            return default if default is not None else ""
        v = d[key]
        if not isinstance(v, str) or not v.strip():
            self.err(p, f"must be a non-empty string, got {v!r}")
            return ""
        return v

    def str_list(self, d: dict, key: str, path: str) -> tuple[str, ...]:
        p = f"{path}.{key}"
        v = d.get(key, [])
        if not isinstance(v, list):
            self.err(p, "must be a list")
            return ()
        out = tuple(str(x) for x in v)
        if len(set(out)) != len(out):
            self.err(p, "contains duplicate entries")
        return out


def load_config(path: str | Path) -> Config:
    """Load and validate a YAML file. Raises ConfigError listing all problems."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError([f"{path}: cannot read file ({exc})"]) from exc
    return parse_config(text, source_path=str(path))


def parse_config(text: str, source_path: str = "") -> Config:
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ConfigError([f"yaml: {exc}"]) from exc
    return validate_config(data, source_path)


def validate_config(data: Any, source_path: str = "") -> Config:  # noqa: C901
    c = _Checker()
    top_req = ("schema_version", "code_edition", "units", "wind", "geometry", "loading",
               "grade", "story_bands")
    top_opt = ("parapets", "penthouses", "equipment", "platforms", "rooftop", "overrides")
    d = c.mapping(data, "", top_req, top_opt)

    version = d.get("schema_version")
    if "schema_version" in d and version != SCHEMA_VERSION:
        c.err("schema_version", f"unsupported version {version!r}; expected {SCHEMA_VERSION}")
    edition = c.string(d, "code_edition", "")
    if "units" in d and d["units"] != "US":
        c.err("units", f"must be 'US', got {d['units']!r}")

    # wind
    w = c.mapping(d.get("wind"), "wind", (
        "risk_category", "basic_wind_speed_mph", "directionality_factor_kd", "exposure_category",
        "topographic_factor_kzt", "gust_effect_factor_g", "enclosure_classification",
        "internal_pressure_coefficient_abs", "mean_roof_height_above_grade_ft"))
    wind = WindInputs(
        risk_category=c.choice(w, "risk_category", "wind", ("I", "II", "III", "IV")),
        basic_wind_speed_mph=c.number(w, "basic_wind_speed_mph", "wind", positive=True),
        directionality_factor_kd=c.number(w, "directionality_factor_kd", "wind", positive=True,
                                          maximum=1.0),
        exposure_category=c.choice(w, "exposure_category", "wind", ("B", "C", "D")),
        topographic_factor_kzt=c.number(w, "topographic_factor_kzt", "wind", minimum=1.0),
        gust_effect_factor_g=c.number(w, "gust_effect_factor_g", "wind", positive=True),
        enclosure_classification=c.choice(w, "enclosure_classification", "wind",
                                          ("enclosed", "partially_enclosed", "open")),
        internal_pressure_coefficient_abs=c.number(w, "internal_pressure_coefficient_abs", "wind",
                                                   minimum=0.0),
        mean_roof_height_above_grade_ft=c.number(w, "mean_roof_height_above_grade_ft", "wind",
                                                 positive=True),
    )

    # geometry
    g = c.mapping(d.get("geometry"), "geometry",
                  ("target", "wind_axes", "plan_dimensions_source", "plan_dimensions_ft"))
    c.choice(g, "target", "geometry", ("entire_model",))
    c.choice(g, "wind_axes", "geometry", ("global_xy",))
    source = c.choice(g, "plan_dimensions_source", "geometry", ("etabs", "yaml"))
    pd = c.mapping(g.get("plan_dimensions_ft"), "geometry.plan_dimensions_ft", ("x_wind", "y_wind"))
    dims = {}
    for axis in ("x_wind", "y_wind"):
        p = f"geometry.plan_dimensions_ft.{axis}"
        m = c.mapping(pd.get(axis), p, ("parallel_l", "perpendicular_b"))
        dims[axis] = PlanDims(c.number(m, "parallel_l", p, positive=True),
                              c.number(m, "perpendicular_b", p, positive=True))
    xw, yw = dims["x_wind"], dims["y_wind"]
    if not math.isclose(xw.parallel_l, yw.perpendicular_b, rel_tol=1e-9):
        c.err("geometry.plan_dimensions_ft.y_wind.perpendicular_b",
              "must equal x_wind.parallel_l (linked dimension)")
    if not math.isclose(xw.perpendicular_b, yw.parallel_l, rel_tol=1e-9):
        c.err("geometry.plan_dimensions_ft.y_wind.parallel_l",
              "must equal x_wind.perpendicular_b (linked dimension)")
    geometry = GeometryConfig(g.get("target", ""), g.get("wind_axes", ""), source or "", xw, yw)

    # loading
    ld = c.mapping(d.get("loading"), "loading",
                   ("wall_pressure_branch_by_direction", "eccentricity_ratio", "mechanical_patterns"),
                   ("story_shears_kip", "scope"))
    branches = ld.get("wall_pressure_branch_by_direction", {})
    if not isinstance(branches, dict):
        c.err("loading.wall_pressure_branch_by_direction", "must be a mapping")
        branches = {}
    for k, v in branches.items():
        if k not in DIRECTIONS:
            c.err(f"loading.wall_pressure_branch_by_direction.{k}", f"unknown direction; use {list(DIRECTIONS)}")
        elif v not in BRANCHES:
            c.err(f"loading.wall_pressure_branch_by_direction.{k}",
                  f"must be one of {list(BRANCHES)}, got {v!r}")
    for k in DIRECTIONS:
        if "wall_pressure_branch_by_direction" in ld and k not in branches:
            c.err(f"loading.wall_pressure_branch_by_direction.{k}", "required value is missing")
    ecc = c.number(ld, "eccentricity_ratio", "loading", positive=True, maximum=1.0)
    mech = c.choice(ld, "mechanical_patterns", "loading", ("reversible_xy",))
    shears: dict[str, dict[str, float]] = {}
    sh_raw = ld.get("story_shears_kip", {})
    if not isinstance(sh_raw, dict):
        c.err("loading.story_shears_kip", "must be a mapping of direction -> story -> kip")
        sh_raw = {}
    for dk, stories in sh_raw.items():
        p = f"loading.story_shears_kip.{dk}"
        if dk not in DIRECTIONS:
            c.err(p, f"unknown direction; use {list(DIRECTIONS)}")
        elif not isinstance(stories, dict) or not stories:
            c.err(p, "must be a non-empty mapping of story -> cumulative shear (kip), top story first")
        else:
            shears[dk] = {}
            for sn, val in stories.items():
                if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
                    c.err(f"{p}.{sn}", f"must be a non-negative number, got {val!r}")
                else:
                    shears[dk][str(sn)] = float(val)
    scope = c.choice(ld, "scope", "loading", ("all", "walls_parapets"), default="all")
    loading = LoadingConfig(dict(branches), ecc, mech or "", shears, scope)

    # grade / roof planes
    gr = c.mapping(d.get("grade"), "grade", ("datum_model_elevation_ft", "roof_planes"))
    datum = c.number(gr, "datum_model_elevation_ft", "grade")
    roofs = []
    for i, r in enumerate(_list(c, gr.get("roof_planes"), "grade.roof_planes")):
        p = f"grade.roof_planes[{i}]"
        m = c.mapping(r, p, ("id", "model_elevation_ft"))
        roofs.append(RoofPlane(c.string(m, "id", p), c.number(m, "model_elevation_ft", p)))
    _unique(c, [r.id for r in roofs], "grade.roof_planes")

    # story bands
    bands = []
    for i, b in enumerate(_list(c, d.get("story_bands"), "story_bands", nonempty=True)):
        p = f"story_bands[{i}]"
        m = c.mapping(b, p, ("id", "bottom_model_elevation_ft", "top_model_elevation_ft",
                             "evaluation_height_above_grade_ft"))
        band = StoryBand(c.string(m, "id", p), c.number(m, "bottom_model_elevation_ft", p),
                         c.number(m, "top_model_elevation_ft", p),
                         c.number(m, "evaluation_height_above_grade_ft", p, positive=True))
        if band.top_model_elevation_ft <= band.bottom_model_elevation_ft:
            c.err(p, "top_model_elevation_ft must exceed bottom_model_elevation_ft")
        bands.append(band)
    _unique(c, [b.id for b in bands], "story_bands")
    for a, b in zip(sorted(bands, key=lambda x: x.bottom_model_elevation_ft),
                    sorted(bands, key=lambda x: x.bottom_model_elevation_ft)[1:], strict=False):
        if b.bottom_model_elevation_ft < a.top_model_elevation_ft - 1e-9:
            c.err("story_bands", f"bands {a.id!r} and {b.id!r} overlap")

    # parapets
    parapets = []
    pp = c.mapping(d.get("parapets", {}), "parapets", (), ("types",))
    for i, m0 in enumerate(_list(c, pp.get("types"), "parapets.types", optional=True)):
        p = f"parapets.types[{i}]"
        m = c.mapping(m0, p, ("id", "kind", "top_elevation_above_grade_ft", "height_above_roof_ft"))
        parapets.append(ParapetType(
            c.string(m, "id", p), c.choice(m, "kind", p, PARAPET_KINDS) or "",
            c.number(m, "top_elevation_above_grade_ft", p, positive=True),
            c.number(m, "height_above_roof_ft", p, positive=True)))
    _unique(c, [x.id for x in parapets], "parapets.types")
    parapet_ids = {x.id for x in parapets}

    # penthouses
    phs = []
    for i, m0 in enumerate(_list(c, d.get("penthouses"), "penthouses", optional=True)):
        p = f"penthouses[{i}]"
        m = c.mapping(m0, p, ("id", "plan_ft", "base_model_elevation_ft", "body_height_ft",
                              "min_plan_dimension_ft"),
                      ("centroid_elevation_above_grade_ft", "parapet_type"))
        pl = c.mapping(m.get("plan_ft"), f"{p}.plan_ft", ("x_min", "x_max", "y_min", "y_max"))
        v = {k: c.number(pl, k, f"{p}.plan_ft") for k in ("x_min", "x_max", "y_min", "y_max")}
        if v["x_max"] <= v["x_min"] or v["y_max"] <= v["y_min"]:
            c.err(f"{p}.plan_ft", "max values must exceed min values")
        base = c.number(m, "base_model_elevation_ft", p)
        hgt = c.number(m, "body_height_ft", p, positive=True)
        cen = c.number(m, "centroid_elevation_above_grade_ft", p, default=math.nan)
        if math.isnan(cen) and not (math.isnan(base) or math.isnan(hgt)):
            cen = base - datum + hgt / 2.0
        pt = m.get("parapet_type")
        if pt is not None and pt not in parapet_ids:
            c.err(f"{p}.parapet_type", f"unknown parapet type {pt!r}")
        phs.append(Penthouse(c.string(m, "id", p), v["x_min"], v["x_max"], v["y_min"], v["y_max"],
                             base, hgt, cen, c.number(m, "min_plan_dimension_ft", p, positive=True),
                             pt))
    _unique(c, [x.id for x in phs], "penthouses")

    # equipment
    eq = []
    for i, m0 in enumerate(_list(c, d.get("equipment"), "equipment", optional=True)):
        p = f"equipment[{i}]"
        m = c.mapping(m0, p, ("id", "centroid_elevation_above_grade_ft", "height_ft", "extent_x_ft",
                              "extent_y_ft", "support_joints"))
        joints = c.str_list(m, "support_joints", p)
        if len(joints) != 4:
            c.err(f"{p}.support_joints", "must list exactly 4 existing support joints")
        eq.append(Equipment(c.string(m, "id", p),
                            c.number(m, "centroid_elevation_above_grade_ft", p, positive=True),
                            c.number(m, "height_ft", p, positive=True),
                            c.number(m, "extent_x_ft", p, positive=True),
                            c.number(m, "extent_y_ft", p, positive=True), joints))
    _unique(c, [x.id for x in eq], "equipment")
    all_joints = [j for e in eq for j in e.support_joints]
    if len(set(all_joints)) != len(all_joints):
        c.err("equipment", "a support joint is mapped more than once")

    # platforms
    pls = []
    for i, m0 in enumerate(_list(c, d.get("platforms"), "platforms", optional=True)):
        p = f"platforms[{i}]"
        m = c.mapping(m0, p, ("id", "centroid_elevation_above_grade_ft", "exposed_depth_ft",
                              "min_plan_dimension_ft", "frames_x_wind", "frames_y_wind"))
        pls.append(Platform(c.string(m, "id", p),
                            c.number(m, "centroid_elevation_above_grade_ft", p, positive=True),
                            c.number(m, "exposed_depth_ft", p, positive=True),
                            c.number(m, "min_plan_dimension_ft", p, positive=True),
                            c.str_list(m, "frames_x_wind", p), c.str_list(m, "frames_y_wind", p)))
    _unique(c, [x.id for x in pls], "platforms")

    # rooftop coefficient
    rt = c.mapping(d.get("rooftop", {}), "rooftop", (), ("net_force_coefficient_cf",))
    cf = c.number(rt, "net_force_coefficient_cf", "rooftop", positive=True, default=1.3)

    # overrides
    ov_raw = d.get("overrides", {}) or {}
    ov: dict[str, str] = {}
    if not isinstance(ov_raw, dict):
        c.err("overrides", "must be a mapping of object name -> category")
    else:
        for k, v in ov_raw.items():
            if v not in CATEGORIES:
                c.err(f"overrides.{k}", f"must be one of {list(CATEGORIES)}, got {v!r}")
            ov[str(k)] = v

    if c.errors:
        raise ConfigError(c.errors)

    normalized = _normalize(d, cf)
    return Config(
        schema_version=SCHEMA_VERSION, code_edition=edition, units="US", wind=wind,
        geometry=geometry, loading=loading, grade_datum_model_elevation_ft=datum,
        roof_planes=tuple(roofs), story_bands=tuple(bands), parapets=tuple(parapets),
        penthouses=tuple(phs), equipment=tuple(eq), platforms=tuple(pls),
        rooftop_net_force_coefficient_cf=cf, overrides=ov, raw=normalized,
        source_path=source_path,
    )


def _list(c: _Checker, v: Any, path: str, *, nonempty=False, optional=False) -> list:
    if v is None:
        if not optional and nonempty:
            c.err(path, "must be a non-empty list")
        return []
    if not isinstance(v, list):
        c.err(path, "must be a list")
        return []
    if nonempty and not v:
        c.err(path, "must be a non-empty list")
    return v


def _unique(c: _Checker, ids: list[str], path: str) -> None:
    if len(set(ids)) != len(ids):
        c.err(path, "ids must be unique")


def _normalize(d: dict, cf: float) -> dict:
    out = copy.deepcopy(d)
    out.setdefault("rooftop", {})["net_force_coefficient_cf"] = cf
    out.setdefault("overrides", {})
    for key in ("parapets", "penthouses", "equipment", "platforms"):
        out.setdefault(key, {"types": []} if key == "parapets" else [])
    return out


def effective_config_yaml(cfg: Config) -> str:
    """Effective (defaults filled) configuration as YAML text."""
    return yaml.safe_dump(cfg.raw, sort_keys=False, default_flow_style=False)
