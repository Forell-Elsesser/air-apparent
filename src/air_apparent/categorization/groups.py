"""Group specifications built from categorized objects.

Three products: the sixteen ``W_*`` pattern groups that are written to ETABS (R6/R7), the fine
groups the Patterns module and the report consume (R8), and the comparison of the pattern groups
with whatever ``W_*`` groups the model already holds. Fine-group names encode feature, level,
direction, role, side and pressure branch but never a numerical pressure.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import (
    BRANCH_TOKENS,
    DIR_TOKENS,
    DIR_VECTORS,
    DIRECTIONS,
    EQUIPMENT_JOINT,
    EQUIPMENT_SUPPORT_FRAME,
    LEEWARD,
    MAIN_PARAPET,
    MAIN_WALL,
    PATTERN_GROUP_NAMES,
    PENTHOUSE_BODY,
    PENTHOUSE_PARAPET,
    PICTURE_FRAME_PARAPET,
    PLATFORM_FRAME,
    SIDE,
    WINDWARD,
    Config,
    Diagnostic,
    GroupComparison,
    GroupSpec,
    ModelSnapshot,
    ObjectCategory,
    mech_pattern_name,
    parapet_result_id,
    pattern_name,
    ph_result_id,
    wall_result_id,
)

PARAPET_CATEGORIES = (MAIN_PARAPET, PICTURE_FRAME_PARAPET, PENTHOUSE_PARAPET)


def face_role(outside: str, direction: str) -> str:
    """WINDWARD when the face points against the wind, LEEWARD when with it, SIDE otherwise."""
    dot = sum(a * b for a, b in zip(DIR_VECTORS[outside], DIR_VECTORS[direction], strict=True))
    return WINDWARD if dot < -0.5 else LEEWARD if dot > 0.5 else SIDE


def assignment_sign(local3, outward_normal) -> int:
    """+1 when local axis 3 points into the building (along a positive code pressure)."""
    dot = sum(a * -b for a, b in zip(local3, outward_normal, strict=True))
    return 1 if dot > 0 else -1


def fine_group_name(*tokens: str) -> str:
    return "_".join(t.upper().replace(" ", "") for t in tokens if t)


def _mech_axes(oc: ObjectCategory) -> tuple[str, ...]:
    return tuple(a for a in ("X", "Y") if a in (oc.side or "XY"))


def build_pattern_groups(objects: dict[str, ObjectCategory]) -> dict[str, list[str]]:
    """Membership of the sixteen ``W_*`` groups (spec R6, R7); every name present, lists sorted."""
    groups: dict[str, list[str]] = {name: [] for name in PATTERN_GROUP_NAMES}
    for ref, oc in objects.items():
        if oc.category == MAIN_WALL:
            for d in DIRECTIONS:
                groups[f"W_Wall_{d}"].append(ref)
        elif oc.category in PARAPET_CATEGORIES:
            for d in DIRECTIONS:
                groups[f"W_Parapet_{d}"].append(ref)
        elif oc.category == PENTHOUSE_BODY and oc.outside:
            for d in DIRECTIONS:
                if face_role(oc.outside, d) != LEEWARD:
                    groups[f"W_PH_{d}"].append(ref)
        elif oc.category == EQUIPMENT_SUPPORT_FRAME:
            for d in DIRECTIONS:
                groups[f"W_Mech_{d}"].append(ref)
        elif oc.category == PLATFORM_FRAME:
            for axis in _mech_axes(oc):
                groups[f"W_Mech_+{axis}"].append(ref)
                groups[f"W_Mech_-{axis}"].append(ref)
    return {name: sorted(refs) for name, refs in groups.items()}


def build_group_specs(cfg: Config, snap: ModelSnapshot, objects: dict[str, ObjectCategory]) -> list[GroupSpec]:
    """Fine groups (R8): one per (category, direction, role, side, level, type, branch, sign)."""
    shells = {f"A:{s.name}": s for s in snap.shells}
    buckets: dict[str, dict] = {}

    def add(name: str, ref: str, **kw) -> None:
        buckets.setdefault(name, {"members": [], **kw})["members"].append(ref)

    for ref, oc in objects.items():
        if oc.category in (MAIN_WALL, *PARAPET_CATEGORIES, PENTHOUSE_BODY):
            if not oc.outside or oc.outward_normal is None:
                continue
            sign = assignment_sign(shells[ref].local3, oc.outward_normal)
            flip = "L3FLIP" if sign < 0 else ""
            for d in DIRECTIONS:
                role = face_role(oc.outside, d)
                branch = cfg.loading.wall_pressure_branch_by_direction[d]
                bt, dt = BRANCH_TOKENS[branch], DIR_TOKENS[d]
                side_rid = wall_result_id("SIDE", "", branch)
                kw = dict(category=oc.category, level=oc.level, direction=d, role=role, component=oc.component,
                          side=oc.side, sign=sign)
                if oc.category == MAIN_WALL:
                    rid = {WINDWARD: wall_result_id("WW", oc.level, branch),
                           LEEWARD: wall_result_id(f"LW_{d[1]}", "", branch), SIDE: side_rid}[role]
                    add(fine_group_name("WALL", oc.level, dt, role, oc.side, bt, flip), ref,
                        result_id=rid, pattern=pattern_name("Wall", d), **kw)
                elif oc.category in PARAPET_CATEGORIES:
                    head = "PHPARAPET" if oc.category == PENTHOUSE_PARAPET else "PARAPET"
                    tag = oc.component if oc.category == PENTHOUSE_PARAPET else oc.parapet_type
                    if role == SIDE:
                        add(fine_group_name(head, tag, dt, role, oc.side, bt, flip), ref,
                            result_id=side_rid, pattern=pattern_name("Parapet", d), **kw)
                    else:
                        add(fine_group_name(head, tag, dt, role, oc.side, flip), ref,
                            result_id=parapet_result_id(oc.parapet_type, role),
                            pattern=pattern_name("Parapet", d), **kw)
                else:  # penthouse body: net pressure on the windward face, side suction on side faces
                    if role == WINDWARD:
                        add(fine_group_name(oc.component, dt, role, oc.side, flip), ref,
                            result_id=ph_result_id(oc.component), pattern=pattern_name("PH", d), **kw)
                    elif role == SIDE:
                        add(fine_group_name(oc.component, dt, role, oc.side, bt, flip), ref,
                            result_id=side_rid, pattern=pattern_name("PH", d), **kw)
        elif oc.category == EQUIPMENT_JOINT:
            add(fine_group_name("MECH", oc.component, "JOINTS"), ref, category=oc.category, level="",
                direction="", role="", component=oc.component, side="", sign=1,
                result_id=f"EQ_{oc.component}_FX|EQ_{oc.component}_FY",
                pattern=f"{mech_pattern_name('X')}|{mech_pattern_name('Y')}")
        elif oc.category == EQUIPMENT_SUPPORT_FRAME:
            add(fine_group_name("MECH", oc.component, "FRAMES"), ref, category=oc.category, level="",
                direction="", role="", component=oc.component, side="XY", sign=1, result_id="",
                pattern=f"{mech_pattern_name('X')}|{mech_pattern_name('Y')}")
        elif oc.category == PLATFORM_FRAME:
            for axis in _mech_axes(oc):
                add(fine_group_name("MECH", oc.component, "FRAMES", axis), ref, category=oc.category, level="",
                    direction=axis, role="", component=oc.component, side=axis, sign=1,
                    result_id=f"PLAT_{oc.component}_LINE", pattern=mech_pattern_name(axis))

    specs = []
    for name in sorted(buckets):
        b = buckets[name]
        specs.append(GroupSpec(
            name=name, members=tuple(sorted(b["members"])), category=b["category"], level=b["level"],
            direction=b["direction"], role=b["role"], result_id=b["result_id"], pattern=b["pattern"],
            component=b["component"], assignment_sign=b["sign"], side=b["side"]))
    return specs


def compare_groups(pattern_groups: dict[str, list[str]],
                   existing: dict[str, list[str]]) -> list[GroupComparison]:
    """Rule membership versus the model's existing groups, matched by name case-insensitively."""
    lower = {k.lower(): v for k, v in existing.items()}
    out = []
    for name in PATTERN_GROUP_NAMES:
        want = set(pattern_groups.get(name, ()))
        have = set(lower.get(name.lower(), ()))
        out.append(GroupComparison(name, len(have), len(want), tuple(sorted(have - want)), tuple(sorted(want - have))))
    return out


def detect_group_conflicts(groups: list[GroupSpec]) -> list[Diagnostic]:
    """An object may not receive two treatments for the same destination pattern."""
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)
    for g in groups:
        for pattern in filter(None, g.pattern.split("|")):
            for m in g.members:
                seen[(pattern, m)].append(g.name)
    return [Diagnostic("error", "group_conflict",
                       f"{m} appears in several groups for pattern {p}: {sorted(names)}", m)
            for (p, m), names in sorted(seen.items()) if len(names) > 1]
