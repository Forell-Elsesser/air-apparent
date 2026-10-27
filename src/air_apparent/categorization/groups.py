"""Preview-group specifications and membership reconciliation.

Group names encode geometry, band, direction, face role and pressure *branch* but never a
numerical pressure, so they stay stable when a calculated pressure changes.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import (
    BRANCH_TOKENS,
    DIR_TOKENS,
    DIR_VECTORS,
    DIRECTIONS,
    EQUIPMENT_JOINT,
    LEEWARD,
    MAIN_PARAPET,
    MAIN_WALL,
    PENTHOUSE_BODY,
    PENTHOUSE_PARAPET,
    PICTURE_FRAME_PARAPET,
    PLATFORM_FRAME,
    SIDE,
    STAIR_PROJECTION,
    UNRESOLVED,
    WINDWARD,
    Categorization,
    Config,
    Diagnostic,
    GroupSpec,
    ModelSnapshot,
    mech_pattern_name,
    parapet_result_id,
    pattern_name,
    ph_result_id,
    preview_group_name,
    wall_result_id,
)

PREFIX = "AA_PREVIEW_"
UNRESOLVED_GROUP = PREFIX + "UNRESOLVED"
STAIR_GROUP = PREFIX + "STAIR_PROJECTION"


def face_role(outward_normal: tuple[float, float, float], direction: str) -> str:
    dot = sum(a * b for a, b in zip(outward_normal, DIR_VECTORS[direction], strict=True))
    return WINDWARD if dot < -0.5 else LEEWARD if dot > 0.5 else SIDE


def assignment_sign(local3, outward_normal) -> int:
    """+1 when local axis 3 points into the building (along a positive code pressure)."""
    dot = sum(a * -b for a, b in zip(local3, outward_normal, strict=True))
    return 1 if dot > 0 else -1


def build_group_specs(cfg: Config, snap: ModelSnapshot, cats: Categorization) -> list[GroupSpec]:
    shells = {f"A:{s.name}": s for s in snap.shells}
    buckets: dict[str, dict] = {}

    def add(name, ref, **kw):
        b = buckets.setdefault(name, {"members": [], **kw})
        b["members"].append(ref)

    for ref, oc in cats.objects.items():
        if oc.load_issue:
            # Category groups remain selectable without inventing pressure inputs.
            add(preview_group_name("REVIEW", oc.category.upper()), ref, category=oc.category,
                band="", direction="", role="REVIEW", component=oc.component, sign=1,
                result_id="", pattern="")
            continue
        if oc.category in (MAIN_WALL, MAIN_PARAPET, PICTURE_FRAME_PARAPET, PENTHOUSE_BODY,
                           PENTHOUSE_PARAPET):
            s = shells[ref]
            sign = assignment_sign(s.local3, oc.outward_normal)
            flip = "L3FLIP" if sign < 0 else ""
            for d in DIRECTIONS:
                role = face_role(oc.outward_normal, d)
                axis = d[1]
                branch = cfg.loading.wall_pressure_branch_by_direction[d]
                bt = BRANCH_TOKENS[branch]
                dt = DIR_TOKENS[d]
                side_rid = wall_result_id("SIDE", "", branch)
                kw = dict(category=oc.category, band=oc.band, direction=d, role=role,
                          component=oc.component, sign=sign)
                if oc.category == MAIN_WALL:
                    rid = {WINDWARD: wall_result_id("WW", oc.band, branch),
                           LEEWARD: wall_result_id(f"LW_{axis}", "", branch), SIDE: side_rid}[role]
                    name = preview_group_name("WALL", oc.band, dt, role, bt, flip)
                    add(name, ref, result_id=rid, pattern=pattern_name("Wall", d), **kw)
                elif oc.category in (MAIN_PARAPET, PICTURE_FRAME_PARAPET, PENTHOUSE_PARAPET):
                    tokens = ["PARAPET" if oc.category != PENTHOUSE_PARAPET else "PHPARAPET"]
                    tokens.append(oc.parapet_type if oc.category != PENTHOUSE_PARAPET else oc.component)
                    if role == SIDE:
                        add(preview_group_name(*tokens, dt, role, bt, flip), ref, result_id=side_rid,
                            pattern=pattern_name("Wall", d), **kw)
                    else:
                        add(preview_group_name(*tokens, dt, role, flip), ref,
                            result_id=parapet_result_id(oc.parapet_type, role),
                            pattern=pattern_name("Parapet", d), **kw)
                elif oc.category == PENTHOUSE_BODY:
                    if role == WINDWARD:
                        add(preview_group_name(oc.component, dt, role, flip), ref,
                            result_id=ph_result_id(oc.component), pattern=pattern_name("PH", d), **kw)
                    elif role == SIDE:
                        add(preview_group_name(oc.component, dt, role, bt, flip), ref,
                            result_id=side_rid, pattern=pattern_name("Wall", d), **kw)
                    # LEEWARD: represented by the net force coefficient; no separate load.
        elif oc.category == EQUIPMENT_JOINT:
            add(preview_group_name("MECH", oc.component, "JOINTS"), ref, category=oc.category,
                band="", direction="", role="", component=oc.component, sign=1,
                result_id=f"EQ_{oc.component}_FX|EQ_{oc.component}_FY",
                pattern=f"{mech_pattern_name('X')}|{mech_pattern_name('Y')}")
        elif oc.category == PLATFORM_FRAME:
            pl = next(p for p in cfg.platforms if p.id == oc.component)
            name_ = ref[2:]
            for axis, names in (("X", pl.frames_x_wind), ("Y", pl.frames_y_wind)):
                if name_ in names:
                    add(preview_group_name("MECH", pl.id, "FRAMES", axis), ref, category=oc.category,
                        band="", direction=axis, role="", component=pl.id, sign=1,
                        result_id=f"PLAT_{pl.id}_LINE", pattern=mech_pattern_name(axis))
        elif oc.category == UNRESOLVED:
            add(UNRESOLVED_GROUP, ref, category=UNRESOLVED, band="", direction="", role="",
                component="", sign=1, result_id="", pattern="")
        elif oc.category == STAIR_PROJECTION:
            add(STAIR_GROUP, ref, category=STAIR_PROJECTION, band="", direction="", role="",
                component="", sign=1, result_id="", pattern="")

    specs = []
    for name in sorted(buckets):
        b = buckets[name]
        specs.append(GroupSpec(
            name=name, members=tuple(sorted(b["members"])), category=b["category"], band=b["band"],
            direction=b["direction"], role=b["role"], result_id=b["result_id"], pattern=b["pattern"],
            component=b["component"], assignment_sign=b["sign"]))
    return specs


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


def reconcile_membership(specs: list[GroupSpec], current: dict[str, list[str]]) -> list[Diagnostic]:
    """Compare tool-owned groups read back from ETABS with the specs."""
    diags: list[Diagnostic] = []
    spec_by_name = {g.name: g for g in specs}
    for name, g in spec_by_name.items():
        if name not in current:
            diags.append(Diagnostic("error", "group_missing", f"preview group {name} does not exist"))
            continue
        want, have = set(g.members), set(current[name])
        for m in sorted(want - have):
            diags.append(Diagnostic("error", "group_member_missing", f"{name}: {m} was removed", m))
        for m in sorted(have - want):
            diags.append(Diagnostic("error", "group_member_extra", f"{name}: {m} was added manually", m))
    for name in current:
        if name.startswith(PREFIX) and name not in spec_by_name:
            diags.append(Diagnostic("warning", "group_stale", f"tool-owned group {name} is outdated"))
    return diags
