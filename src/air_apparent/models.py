"""Shared typed data structures and stable-ID helpers.

All core modules (pressures, categorization, patterns, combinations) exchange data
only through the dataclasses and ID helpers defined here. Units are ft, psf, kip
unless a field name says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- directions
DIRECTIONS = ("+X", "-X", "+Y", "-Y")
DIR_VECTORS = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0), "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}
DIR_TOKENS = {"+X": "XPOS", "-X": "XNEG", "+Y": "YPOS", "-Y": "YNEG"}
BRANCHES = ("Ext. Only", "Max", "Min")
BRANCH_TOKENS = {"Ext. Only": "EXT", "Max": "MAX", "Min": "MIN"}

# --------------------------------------------------------------------------- categories
MAIN_WALL = "main_wall"
STAIR_PROJECTION = "stair_projection"
MAIN_PARAPET = "main_roof_parapet"
PICTURE_FRAME_PARAPET = "picture_frame_parapet"
PENTHOUSE_BODY = "penthouse_body"
PENTHOUSE_PARAPET = "penthouse_parapet"
PLATFORM_FRAME = "mechanical_platform_frame"
EQUIPMENT_JOINT = "equipment_support_joint"
EQUIPMENT_SUPPORT_FRAME = "equipment_support_frame"
EXCLUDED = "excluded"
UNRESOLVED = "unresolved"
CATEGORIES = (
    MAIN_WALL, STAIR_PROJECTION, MAIN_PARAPET, PICTURE_FRAME_PARAPET, PENTHOUSE_BODY,
    PENTHOUSE_PARAPET, PLATFORM_FRAME, EQUIPMENT_JOINT, EQUIPMENT_SUPPORT_FRAME, EXCLUDED, UNRESOLVED,
)

# Face roles
WINDWARD, LEEWARD, SIDE = "WINDWARD", "LEEWARD", "SIDE"

# Pattern families
WALL, PARAPET, PH, MECH, ECC = "Wall", "Parapet", "PH", "Mech", "Ecc"

# The sixteen per-pattern groups the tool reads, compares and writes (spec section 8).
PATTERN_GROUP_NAMES = tuple(f"W_{family}_{d}" for family in ("Wall", "Parapet", "PH", "Mech") for d in DIRECTIONS)

# --------------------------------------------------------------------------- configuration
@dataclass(frozen=True)
class WindInputs:
    risk_category: str
    basic_wind_speed_mph: float
    directionality_factor_kd: float
    exposure_category: str
    topographic_factor_kzt: float
    gust_effect_factor_g: float
    enclosure_classification: str
    internal_pressure_coefficient_abs: float
    mean_roof_height_above_grade_ft: float


@dataclass(frozen=True)
class PlanDims:
    parallel_l: float
    perpendicular_b: float


@dataclass(frozen=True)
class GeometryConfig:
    target: str
    wind_axes: str
    plan_dimensions_source: str
    x_wind: PlanDims
    y_wind: PlanDims


@dataclass(frozen=True)
class LoadingConfig:
    wall_pressure_branch_by_direction: dict[str, str]
    eccentricity_ratio: float
    mechanical_patterns: str
    story_shears_kip: dict[str, dict[str, float]] = field(default_factory=dict)
    scope: str = "all"  # all | walls_parapets


@dataclass(frozen=True)
class RoofPlane:
    id: str
    model_elevation_ft: float


@dataclass(frozen=True)
class StoryBand:
    id: str
    bottom_model_elevation_ft: float
    top_model_elevation_ft: float
    evaluation_height_above_grade_ft: float


@dataclass(frozen=True)
class ParapetType:
    id: str
    kind: str  # main_roof | picture_frame | penthouse
    top_elevation_above_grade_ft: float
    height_above_roof_ft: float


@dataclass(frozen=True)
class Penthouse:
    id: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    base_model_elevation_ft: float
    body_height_ft: float
    centroid_elevation_above_grade_ft: float
    min_plan_dimension_ft: float
    parapet_type: str | None = None


@dataclass(frozen=True)
class Equipment:
    id: str
    centroid_elevation_above_grade_ft: float
    height_ft: float
    extent_x_ft: float
    extent_y_ft: float
    support_joints: tuple[str, ...] = ()  # four existing joints (joint loads, Patterns)
    support_frames: tuple[str, ...] = ()  # four existing beams (W_Mech grouping)


@dataclass(frozen=True)
class ExteriorSegment:
    """A stretch of exterior wall: a line, a range along it and which side is outside."""

    id: str
    along: str | float  # grid label or ordinate (ft)
    start: str | float  # grid label or ordinate (ft) along the perpendicular axis
    end: str | float
    outside: str  # "+X" | "-X" | "+Y" | "-Y" | "none" (declared unexposed)
    axis: str = ""  # "x" or "y" when ``along`` is numeric; "" when a grid label fixes it
    z_from: float | None = None  # optional height range, model elevation (ft)
    z_to: float | None = None


@dataclass(frozen=True)
class CategorizationSettings:
    plane_tolerance_ft: float = 0.1
    extent_tolerance_ft: float = 0.5
    level_tolerance_ft: float = 0.05


@dataclass(frozen=True)
class LevelRoles:
    main_roof: str
    parapet: tuple[str, ...]
    penthouse_body: tuple[str, ...]
    penthouse_parapet: tuple[str, ...]
    mechanical: str


@dataclass(frozen=True)
class Override:
    category: str
    component: str = ""
    outside: str = ""


@dataclass(frozen=True)
class Platform:
    id: str
    centroid_elevation_above_grade_ft: float
    exposed_depth_ft: float
    min_plan_dimension_ft: float
    frames_x_wind: tuple[str, ...]
    frames_y_wind: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    schema_version: int
    code_edition: str
    units: str
    wind: WindInputs
    geometry: GeometryConfig
    loading: LoadingConfig
    grade_datum_model_elevation_ft: float
    roof_planes: tuple[RoofPlane, ...]
    story_bands: tuple[StoryBand, ...]
    parapets: tuple[ParapetType, ...]
    penthouses: tuple[Penthouse, ...]
    equipment: tuple[Equipment, ...]
    platforms: tuple[Platform, ...]
    rooftop_net_force_coefficient_cf: float
    overrides: dict[str, Override]
    exterior_segments: tuple[ExteriorSegment, ...] = ()
    categorization: CategorizationSettings = CategorizationSettings()
    levels: LevelRoles | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)  # normalized YAML mapping
    source_path: str = ""


# --------------------------------------------------------------------------- diagnostics
@dataclass(frozen=True)
class Diagnostic:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str
    object_ref: str = ""


# --------------------------------------------------------------------------- calculations
@dataclass(frozen=True)
class CalcResult:
    id: str
    description: str
    value: float
    units: str
    reference: str
    inputs: dict[str, Any] = field(default_factory=dict)
    source_cell: str = ""
    notes: str = ""
    status: str = "workbook_reproduction"  # see docs/engineering_basis.md


@dataclass
class PressureSet:
    """All calculation results for one configuration, keyed by stable result ID."""

    edition: str
    results: dict[str, CalcResult] = field(default_factory=dict)
    dims: dict[str, PlanDims] = field(default_factory=dict)  # "X"/"Y" wind axis -> L/B used
    checks: list[CalcResult] = field(default_factory=list)

    def add(self, r: CalcResult) -> CalcResult:
        self.results[r.id] = r
        return r

    def value(self, result_id: str) -> float:
        return self.results[result_id].value


# --------------------------------------------------------------------------- model snapshot
@dataclass(frozen=True)
class Shell:
    name: str
    corners: tuple[tuple[float, float, float], ...]  # model coordinates, ft
    local3: tuple[float, float, float] = (0.0, 0.0, 1.0)  # unit vector of local axis 3
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class Frame:
    name: str
    p1: tuple[float, float, float]
    p2: tuple[float, float, float]
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class Joint:
    name: str
    xyz: tuple[float, float, float]


@dataclass(frozen=True)
class Story:
    name: str
    elevation_ft: float  # top of the story
    height_ft: float = 0.0
    is_master: bool = True
    similar_to: str = ""
    diaphragm: str | None = None
    reference_joint: str | None = None  # joint at the diaphragm centre, if known


@dataclass(frozen=True)
class GridSystem:
    name: str
    kind: str  # "Cartesian" | other
    origin_x_ft: float
    origin_y_ft: float
    rotation_deg: float


@dataclass(frozen=True)
class GridLine:
    system: str
    axis: str  # "x" for a line of constant X, "y" for a line of constant Y
    label: str
    ordinate_ft: float  # global coordinate of the line


@dataclass
class ModelSnapshot:
    shells: list[Shell] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    joints: list[Joint] = field(default_factory=list)
    stories: list[Story] = field(default_factory=list)  # bottom-up
    groups: dict[str, list[str]] = field(default_factory=dict)  # name -> object refs
    existing_loads: dict[str, list[str]] = field(default_factory=dict)  # pattern -> object refs
    existing_patterns: list[str] = field(default_factory=list)
    existing_cases: list[str] = field(default_factory=list)
    existing_combos: list[str] = field(default_factory=list)
    base_elevation_ft: float = 0.0
    grid_systems: list[GridSystem] = field(default_factory=list)
    grid_lines: list[GridLine] = field(default_factory=list)
    labels: dict[str, tuple[str, str]] = field(default_factory=dict)  # object ref -> (label, story)
    read_diagnostics: list[Diagnostic] = field(default_factory=list)  # from the adapter read


@dataclass(frozen=True)
class ModelInfo:
    path: str
    pid: int
    version: str
    units: str
    locked: bool


def shell_ref(name: str) -> str:
    return f"A:{name}"


def frame_ref(name: str) -> str:
    return f"F:{name}"


def joint_ref(name: str) -> str:
    return f"P:{name}"


# --------------------------------------------------------------------------- categorization
@dataclass(frozen=True)
class ObjectCategory:
    ref: str
    category: str
    reason: str
    level: str = ""  # story band containing the object's top edge
    component: str = ""  # penthouse / equipment / platform id
    parapet_type: str = ""  # parapet type id for parapet categories
    outward_normal: tuple[float, float, float] | None = None
    overridden: bool = False
    load_issue: str = ""  # category is known/inferred, but automatic loading needs review
    segment_id: str = ""  # exterior segment or penthouse edge the shell was placed on
    outside: str = ""  # "+X" | "-X" | "+Y" | "-Y" from that segment
    side: str = ""  # side label for group specs (segment id); "X"/"Y"/"XY" for platform frames


@dataclass(frozen=True)
class GroupSpec:
    name: str
    members: tuple[str, ...]
    category: str
    level: str  # story band of the members' top edges
    direction: str
    role: str
    result_id: str
    pattern: str
    component: str = ""
    assignment_sign: int = 1  # sign applied to code pressure to get the ETABS local-3 value
    note: str = ""
    side: str = ""  # segment id (side relative to centre) or mech axis


@dataclass(frozen=True)
class GroupComparison:
    """Rule membership of one W_* group against the model's existing group of that name."""

    name: str
    in_model: int
    by_rules: int
    missing_from_rules: tuple[str, ...]  # refs in the model's group but not the tool's
    extra_in_rules: tuple[str, ...]


@dataclass
class Categorization:
    objects: dict[str, ObjectCategory] = field(default_factory=dict)
    envelope: dict[str, float] = field(default_factory=dict)  # extent of the declared segments
    derived_dims: dict[str, PlanDims] = field(default_factory=dict)
    groups: list[GroupSpec] = field(default_factory=list)  # fine groups (not written to ETABS)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    pattern_groups: dict[str, list[str]] = field(default_factory=dict)  # the sixteen W_* -> refs
    comparison: list[GroupComparison] = field(default_factory=list)


# --------------------------------------------------------------------------- patterns
@dataclass(frozen=True)
class PatternSpec:
    name: str
    family: str
    direction: str  # "+X" etc, or "X"/"Y" for reversible mechanical patterns
    status: str = "ready"  # ready | provisional


@dataclass(frozen=True)
class CaseSpec:
    name: str
    terms: tuple[tuple[str, float], ...]  # (pattern name, scale factor)
    status: str = "ready"


@dataclass(frozen=True)
class Assignment:
    id: str
    kind: str  # shell_pressure | joint_force | frame_line_load | joint_moment
    object_ref: str
    pattern: str
    value: float  # shell: kip/ft2 (ETABS local-3 sign); joint: kip or kip-ft; frame: kip/ft
    units: str
    global_dir: str  # ETABS direction code: "Local3", "X", "Y", "Mz"
    result_id: str
    group: str = ""
    code_pressure_psf: float | None = None
    sign: int = 1
    direction: str = ""
    note: str = ""


@dataclass(frozen=True)
class CombinationSpec:
    name: str
    family: str
    kind: str  # "linear" | "envelope"
    terms: tuple[tuple[str, float], ...]  # (case or combination name, factor)
    status: str = "provisional"


@dataclass
class LoadPlan:
    patterns: list[PatternSpec] = field(default_factory=list)
    cases: list[CaseSpec] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    combinations: list[CombinationSpec] = field(default_factory=list)
    groups: list[GroupSpec] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- stable IDs
def wall_result_id(kind: str, band: str, branch: str) -> str:
    """Wall pressure result IDs. kind: WW (windward), LW_X/LW_Y (leeward), SIDE."""
    return f"WALL_{kind}_{band}_{BRANCH_TOKENS[branch]}" if kind == "WW" else (
        f"WALL_{kind}_{BRANCH_TOKENS[branch]}"
    )


def parapet_result_id(type_id: str, role: str) -> str:
    return f"PARAPET_{type_id}_{'WW' if role == WINDWARD else 'LW'}"


def ph_result_id(ph_id: str) -> str:
    return f"PH_{ph_id}_NET"


def pattern_name(family: str, direction: str) -> str:
    return f"W_{family}_{direction}"


def mech_pattern_name(axis: str) -> str:
    return f"W_Mech_{axis}"


def preview_group_name(*tokens: str) -> str:
    return "AA_PREVIEW_" + "_".join(t.upper().replace(" ", "") for t in tokens if t)
