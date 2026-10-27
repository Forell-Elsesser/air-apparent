"""Capture a live ETABS model to a JSON snapshot and print a phase-1 summary.

Usage: ``python -m air_apparent.capture --pid <ETABS pid> OUT.json``
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .models import ModelSnapshot
from .snapshot_io import snapshot_to_json


def summarize(snap: ModelSnapshot) -> str:
    lines = [f"base elevation: {snap.base_elevation_ft:.3f} ft", "stories (bottom-up):"]
    for s in snap.stories:
        lines.append(f"  {s.name:12s} elevation {s.elevation_ft:9.3f} ft  height {s.height_ft:7.3f} ft")
    lines.append("grid systems:")
    for g in snap.grid_systems:
        lines.append(f"  {g.name} {g.kind} origin ({g.origin_x_ft:g}, {g.origin_y_ft:g}) rotation {g.rotation_deg:g}")
    lines.append("grid lines:")
    for g in sorted(snap.grid_lines, key=lambda g: (g.system, g.axis, g.ordinate_ft)):
        lines.append(f"  {g.system} {g.axis} {g.label:8s} {g.ordinate_ft:10.3f} ft")
    lines.append(f"objects: {len(snap.shells)} shells, {len(snap.frames)} frames, {len(snap.joints)} joints, "
                 f"{len(snap.labels)} labels")
    lines.append("W_ groups:")
    for name in sorted(snap.groups):
        lines.append(f"  {name:16s} {len(snap.groups[name]):5d}")
    for d in snap.read_diagnostics:
        lines.append(f"[{d.level}] {d.code}: {d.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m air_apparent.capture",
                                 description="Capture the connected ETABS model to a JSON snapshot")
    ap.add_argument("--pid", type=int, default=None, help="ETABS process id (required with several instances)")
    ap.add_argument("out", help="output JSON path")
    args = ap.parse_args(argv)
    from .etabs import connect_live

    adapter = connect_live(args.pid)
    try:
        snap = adapter.read_model()
    finally:
        adapter.close()
    Path(args.out).write_text(snapshot_to_json(snap), encoding="utf-8")
    print(summarize(snap))
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
