"""Grid-line table discovery and parsing for the ETABS database-tables API.

Pure functions over the arrays the API returns, so they are unit-testable without comtypes.
The exact table key and column names are not documented; columns are matched by normalised
name against candidate sets and failure is loud, listing what was found.
"""

from __future__ import annotations

import re

from ..models import Diagnostic, GridLine, GridSystem
from .errors import AdapterError

_SYSTEM = {"gridsys", "gridsystem", "name", "gridsysname"}
_KIND = {"gridsystype", "gridsystemtype", "type", "systype"}
_DIRECTION = {"gridlinetype", "linetype", "direction", "dir", "axis", "axisdir"}
_ID = {"gridid", "id", "label", "gridlabel", "lineid"}
_ORDINATE = {"ordinate", "coord", "coordinate", "ord"}
_ORIGIN_X = {"xo", "originx", "xorigin", "x0"}
_ORIGIN_Y = {"yo", "originy", "yorigin", "y0"}
_ROTATION = {"rz", "rotation", "angle", "rotz"}

_UNIT_FACTORS = {
    "in": 1.0 / 12.0, "inch": 1.0 / 12.0, "inches": 1.0 / 12.0,
    "ft": 1.0, "feet": 1.0, "foot": 1.0,
    "mm": 1.0 / 304.8, "cm": 1.0 / 30.48, "m": 1.0 / 0.3048,
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_grid_table(keys: list[str], names: list[str]) -> str:
    """Key of the single table whose name contains both 'grid' and 'line' (case-insensitive)."""
    matches = [k for k, n in zip(keys, names, strict=True)
               if "grid" in n.lower() and "line" in n.lower()]
    if len(matches) != 1:
        raise AdapterError(f"expected exactly one grid-line table, found {len(matches)}; "
                           f"available tables: {list(names)}")
    return matches[0]


def length_factor(units_string: str) -> float | None:
    """Multiplier that converts a table length in ``units_string`` to feet; ``None`` when unknown."""
    u = units_string.strip().lower()
    if not u:
        return None
    try:
        return _UNIT_FACTORS[u]
    except KeyError:
        raise AdapterError(f"unsupported length unit {units_string!r} in grid table") from None


def _column(field_keys: list[str], field_names: list[str], candidates: set[str]) -> int | None:
    for i, (k, n) in enumerate(zip(field_keys, field_names, strict=True)):
        if _norm(k) in candidates or _norm(n) in candidates:
            return i
    return None


def _infer_factor(ordinates: list[float], point_x_span_ft: float) -> tuple[float, Diagnostic]:
    span = (max(ordinates) - min(ordinates)) if ordinates else 0.0
    if span <= 0 or point_x_span_ft <= 0:
        raise AdapterError("grid table has no unit string and the units cannot be inferred from a single line")
    ratio = span / point_x_span_ft
    if 0.9 <= ratio <= 1.1:
        return 1.0, Diagnostic("info", "grid_table_units_inferred",
                               "grid table units inferred as feet from the model extent")
    if abs(ratio - 12.0) <= 0.24:
        return 1.0 / 12.0, Diagnostic("info", "grid_table_units_inferred",
                                      "grid table units inferred as inches from the model extent; divided by 12")
    raise AdapterError(f"grid table ordinate span is {ratio:.3g} x the model's point extent; units unknown")


def parse_grid_table(
    field_keys: list[str], field_names: list[str], units: list[str], data: list[str], n_records: int,
    point_x_span_ft: float,
) -> tuple[list[GridSystem], list[GridLine], list[Diagnostic]]:
    """Turn the flat ``TableData`` array into grid systems and lines in global feet."""
    cols = {
        "system": _column(field_keys, field_names, _SYSTEM),
        "direction": _column(field_keys, field_names, _DIRECTION),
        "id": _column(field_keys, field_names, _ID),
        "ordinate": _column(field_keys, field_names, _ORDINATE),
    }
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        raise AdapterError(f"grid table is missing columns {missing}; fields present: {list(field_keys)}")
    kind_col = _column(field_keys, field_names, _KIND)
    ox_col = _column(field_keys, field_names, _ORIGIN_X)
    oy_col = _column(field_keys, field_names, _ORIGIN_Y)
    rz_col = _column(field_keys, field_names, _ROTATION)
    width = len(field_keys)
    rows = [data[i * width:(i + 1) * width] for i in range(n_records)]

    diags: list[Diagnostic] = []
    factor = length_factor(units[cols["ordinate"]]) if cols["ordinate"] < len(units) else None
    if factor is None:
        x_ords = [float(r[cols["ordinate"]]) for r in rows if _axis_of(r[cols["direction"]]) == "x"]
        all_ords = [float(r[cols["ordinate"]]) for r in rows]
        factor, note = _infer_factor(x_ords or all_ords, point_x_span_ft)
        diags.append(note)

    systems: dict[str, GridSystem] = {}
    lines: list[GridLine] = []
    unsupported: set[str] = set()
    for r in rows:
        name = r[cols["system"]]
        if name not in systems:
            ox = float(r[ox_col]) * factor if ox_col is not None and r[ox_col] else 0.0
            oy = float(r[oy_col]) * factor if oy_col is not None and r[oy_col] else 0.0
            rz = float(r[rz_col]) if rz_col is not None and r[rz_col] else 0.0
            kind = r[kind_col] if kind_col is not None and r[kind_col] else "Cartesian"
            systems[name] = GridSystem(name, kind, ox, oy, rz)
        sysrec = systems[name]
        axis = _axis_of(r[cols["direction"]])
        if axis is None or abs(sysrec.rotation_deg) > 1e-9:
            unsupported.add(name)
            continue
        origin = sysrec.origin_x_ft if axis == "x" else sysrec.origin_y_ft
        lines.append(GridLine(name, axis, r[cols["id"]], float(r[cols["ordinate"]]) * factor + origin))
    for name in sorted(unsupported):
        diags.append(Diagnostic("warning", "grid_system_unsupported",
                                f"grid system {name!r} is not an unrotated Cartesian system; its lines are not used",
                                name))
    return list(systems.values()), lines, diags


def _axis_of(direction_cell: str) -> str | None:
    m = re.match(r"\s*([A-Za-z])", direction_cell or "")
    if not m:
        return None
    first = m.group(1).lower()
    return first if first in ("x", "y") else None
