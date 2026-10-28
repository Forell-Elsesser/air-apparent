"""Read-only analysis-table extraction; no analysis runs or model edits."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .adapter import AdapterError, _ok


@dataclass(frozen=True)
class StoryShear:
    story: str
    vx_kip: float
    vy_kip: float


@dataclass(frozen=True)
class ShearResults:
    cases: tuple[str, ...]
    base_fx_kip: float
    base_fy_kip: float
    stories: tuple[StoryShear, ...]
    model_path: str
    location: str = "Bottom"


def _number(value: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"invalid shear result {value!r}") from exc
    if not math.isfinite(result):
        raise AdapterError(f"non-finite shear result {value!r}")
    return result


def _table(db, key: str) -> list[dict[str, str]]:
    # Verified against the installed ETABSv1 type library: six output values,
    # including the in/out FieldKeyList before TableVersion.
    r = db.GetTableForDisplayArray(key, [], "All", 0, [], 0, [])
    _ok(r[-1], f"GetTableForDisplayArray({key})")
    fields, count, data = r[2], r[3], r[4]
    if not fields or not count or not data:
        raise AdapterError(f"{key}: no analysis results; run the source cases in ETABS first")
    if len(data) != count * len(fields):
        raise AdapterError(f"{key}: inconsistent table dimensions")
    keys = [f.lower() for f in fields]
    return [dict(zip(keys, data[i:i + len(keys)], strict=True))
            for i in range(0, len(data), len(keys))]


def read_shears(adapter, cases: tuple[str, ...]) -> ShearResults:
    """Sum explicit static-linear cases at the same story/location, retaining signs.

    Bottom-of-story cuts are used consistently. Base reactions are a separate
    equilibrium check, never an extra story or a floor force. Envelopes and
    multi-step cases cannot supply compatible simultaneous values.
    """
    m = adapter.m
    if not cases or len(cases) != len(set(cases)):
        raise AdapterError("select one or more distinct uneccentric static-linear wind cases")
    if not m.GetModelIsLocked():
        raise AdapterError("analysis results require a locked model; run analysis in ETABS first")
    available = adapter.read_cases()
    status = m.Analyze.GetCaseStatus()
    _ok(status[-1], "Analyze.GetCaseStatus")
    statuses = dict(zip(status[1], status[2], strict=True))
    for case in cases:
        if case not in available:
            raise AdapterError(f"{case!r} is not an analysis case (combinations are not accepted)")
        kind = m.LoadCases.GetTypeOAPI(case)
        _ok(kind[-1], f"LoadCases.GetTypeOAPI({case})")
        if kind[0] != 1 or statuses.get(case) != 4:
            raise AdapterError(f"{case}: requires completed static-linear results")
        if any("ecc" in name.lower() for name, factor in available[case] if factor):
            raise AdapterError(f"{case}: contains eccentric loading; choose uneccentric wind cases")

    db = m.DatabaseTables
    saved_cases = db.GetLoadCasesSelectedForDisplay()
    saved_combos = db.GetLoadCombinationsSelectedForDisplay()
    _ok(saved_cases[-1], "GetLoadCasesSelectedForDisplay")
    _ok(saved_combos[-1], "GetLoadCombinationsSelectedForDisplay")

    def select(method, names):
        result = method(list(names))
        _ok(result, method.__name__ if hasattr(method, "__name__") else "table display selection")

    with adapter._kip_ft_units():
        try:
            select(db.SetLoadCasesSelectedForDisplay, cases)
            select(db.SetLoadCombinationsSelectedForDisplay, [])
            story_rows = _table(db, "Story Forces")
            base_rows = _table(db, "Base Reactions")
        finally:
            # Attempt both restores even if one fails.
            try:
                select(db.SetLoadCasesSelectedForDisplay, saved_cases[1] or [])
            finally:
                select(db.SetLoadCombinationsSelectedForDisplay, saved_combos[1] or [])

    def selected(rows, required):
        if any(not required.issubset(row) for row in rows):
            raise AdapterError(f"analysis table is missing required fields: {sorted(required)}")
        out = [row for row in rows if row["outputcase"] in cases]
        if {row["outputcase"] for row in out} != set(cases):
            raise AdapterError("analysis tables do not contain every requested source case")
        if any(row.get("steptype", "").strip().lower() not in ("", "none") for row in out):
            raise AdapterError("envelope or multi-step output cannot be used for eccentricity")
        return out

    story_rows = selected(story_rows, {"story", "outputcase", "location", "vx", "vy"})
    base_rows = selected(base_rows, {"outputcase", "fx", "fy"})
    bottom = [r for r in story_rows if r["location"].lower() == "bottom"]
    by_story = {}
    for r in bottom:
        by_story.setdefault(r["story"], {})
        if r["outputcase"] in by_story[r["story"]]:
            raise AdapterError(f"duplicate Bottom results for {r['story']} / {r['outputcase']}")
        by_story[r["story"]][r["outputcase"]] = (_number(r["vx"]), _number(r["vy"]))
    if not by_story or any(set(values) != set(cases) for values in by_story.values()):
        raise AdapterError("incomplete Bottom story shear coverage for the selected cases")
    if len(base_rows) != len(cases):
        raise AdapterError("expected exactly one base reaction row per static-linear case")
    return ShearResults(
        cases, sum(_number(r["fx"]) for r in base_rows), sum(_number(r["fy"]) for r in base_rows),
        tuple(StoryShear(name, sum(v[0] for v in values.values()), sum(v[1] for v in values.values()))
              for name, values in by_story.items()), m.GetModelFilename())
