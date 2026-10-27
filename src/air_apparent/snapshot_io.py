"""JSON serialisation of :class:`ModelSnapshot` (capture from a live model, load as a test fixture)."""

from __future__ import annotations

import json
from dataclasses import asdict

from .models import Frame, GridLine, GridSystem, Joint, ModelSnapshot, Shell, Story

FORMAT_VERSION = 1


def snapshot_to_json(snap: ModelSnapshot) -> str:
    data = asdict(snap)
    data["format_version"] = FORMAT_VERSION
    return json.dumps(data, indent=1)


def _xyz(v) -> tuple[float, float, float]:
    return (float(v[0]), float(v[1]), float(v[2]))


def snapshot_from_json(text: str) -> ModelSnapshot:
    d = json.loads(text)
    return ModelSnapshot(
        shells=[Shell(s["name"], tuple(_xyz(c) for c in s["corners"]), _xyz(s["local3"]), tuple(s["groups"]))
                for s in d.get("shells", [])],
        frames=[Frame(f["name"], _xyz(f["p1"]), _xyz(f["p2"]), tuple(f["groups"])) for f in d.get("frames", [])],
        joints=[Joint(j["name"], _xyz(j["xyz"])) for j in d.get("joints", [])],
        stories=[Story(**s) for s in d.get("stories", [])],
        groups={k: list(v) for k, v in d.get("groups", {}).items()},
        existing_loads={k: list(v) for k, v in d.get("existing_loads", {}).items()},
        existing_patterns=list(d.get("existing_patterns", [])),
        existing_cases=list(d.get("existing_cases", [])),
        existing_combos=list(d.get("existing_combos", [])),
        base_elevation_ft=float(d.get("base_elevation_ft", 0.0)),
        grid_systems=[GridSystem(**g) for g in d.get("grid_systems", [])],
        grid_lines=[GridLine(**g) for g in d.get("grid_lines", [])],
        labels={k: (v[0], v[1]) for k, v in d.get("labels", {}).items()},
    )
