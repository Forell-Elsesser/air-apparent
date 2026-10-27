"""Narrow ETABS adapter protocol plus the optional live COM implementation.

LIVE VERIFICATION STATUS: ``ComEtabsAdapter`` has NOT been exercised against a running ETABS
instance. API signatures were written from memory of the ETABS OAPI documentation and must be
verified against the installed version's documentation (see docs/etabs_setup.md) before use.
``comtypes`` is imported lazily and only on Windows.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol

from ..models import (
    Assignment,
    CaseSpec,
    CombinationSpec,
    Diagnostic,
    Frame,
    GridLine,
    GridSystem,
    Joint,
    ModelInfo,
    ModelSnapshot,
    PatternSpec,
    Shell,
    Story,
)
from .errors import AdapterError
from .tables import find_grid_table, length_factor, parse_grid_table

__all__ = ["AdapterError", "ComEtabsAdapter", "EtabsAdapter", "GroupWriteResult", "connect_live", "list_instances"]


@dataclass(frozen=True)
class GroupWriteResult:
    """Outcome of a group write: members ETABS refused (with return codes) and members absent on read-back."""

    refused: tuple[tuple[str, int], ...] = ()
    missing_after_readback: tuple[str, ...] = ()


class EtabsAdapter(Protocol):
    def info(self) -> ModelInfo: ...
    def read_model(self) -> ModelSnapshot: ...
    def read_groups(self, prefix: str = "W_") -> dict[str, list[str]]:
        """Groups whose names start with ``prefix`` (case-insensitive), keyed by the model's spelling."""
    def set_group(self, name: str, members: list[str]) -> GroupWriteResult:
        """Create the group or replace its membership entirely."""
    def delete_group(self, name: str) -> None: ...
    def select_group(self, name: str) -> None: ...
    def select_objects(self, refs: list[str]) -> None:
        """Select exactly these objects (``A:``/``F:``/``P:`` refs) in the ETABS view."""
    def unlock(self) -> None: ...
    def read_manifest(self) -> dict: ...
    def write_manifest(self, manifest: dict) -> None: ...
    def define_pattern(self, spec: PatternSpec) -> None: ...
    def define_case(self, spec: CaseSpec) -> None: ...
    def define_combination(self, spec: CombinationSpec) -> None: ...
    def assign(self, a: Assignment) -> None:
        """Set a load with replace semantics, so reapplying never accumulates."""
    def clear_assignment(self, kind: str, object_ref: str, pattern: str) -> None: ...
    def read_assignments(self) -> list[Assignment]: ...
    def read_patterns(self) -> list[str]: ...
    def read_cases(self) -> dict[str, tuple[tuple[str, float], ...]]: ...
    def read_combinations(self) -> dict[str, tuple[str, tuple[tuple[str, float], ...]]]: ...


_PROG_ID = "CSI.ETABS.API.ETABSObject"
_KIP_FT_F = 4  # eUnits.kip_ft_F
_DIR_CODE = {"X": 4, "Y": 5, "Local3": 3}


def list_instances() -> list[tuple[int, str]]:
    """(pid, image name) of running ETABS processes. Windows only."""
    if sys.platform != "win32":
        return []
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq ETABS.exe"],
                         capture_output=True, text=True, check=False).stdout
    rows = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].strip('"').lower() == "etabs.exe":
            rows.append((int(parts[1]), parts[0].strip('"')))
    return rows


def connect_live(pid: int | None = None) -> ComEtabsAdapter:
    """Attach to a running ETABS. ``pid`` is required when several instances are open."""
    instances = list_instances()
    if pid is None:
        if len(instances) != 1:
            raise AdapterError(f"{len(instances)} ETABS instances open; select one explicitly by pid")
        pid = instances[0][0]
    elif pid not in {p for p, _ in instances}:
        raise AdapterError(f"no running ETABS process with pid {pid}")
    return ComEtabsAdapter(pid)


def _ok(ret, what: str) -> None:
    if ret != 0:
        raise AdapterError(f"{what} failed (return code {ret})")


class ComEtabsAdapter:  # pragma: no cover - requires Windows + ETABS
    def __init__(self, pid: int):
        try:
            import comtypes.client
        except ImportError as exc:  # pragma: no cover
            raise AdapterError("comtypes is required for live ETABS (pip install '.[etabs]')") from exc
        helper = comtypes.client.CreateObject("ETABSv1.Helper")
        helper = helper.QueryInterface(comtypes.gen.ETABSv1.cHelper)
        self._etabs = helper.GetObjectProcess(_PROG_ID, pid)
        if self._etabs is None:
            raise AdapterError(f"could not attach to ETABS pid {pid}")
        self._pid = pid
        self.m = self._etabs.SapModel
        self._prior_units = self.m.GetPresentUnits()
        _ok(self.m.SetPresentUnits(_KIP_FT_F), "SetPresentUnits(kip_ft_F)")

    def close(self) -> None:
        self.m.SetPresentUnits(self._prior_units)

    # ---- info
    def info(self) -> ModelInfo:
        return ModelInfo(self.m.GetModelFilename(), self._pid, str(self.m.GetVersion()[0]),
                         "kip, ft, F", bool(self.m.GetModelIsLocked()))

    def unlock(self) -> None:
        _ok(self.m.SetModelIsLocked(False), "SetModelIsLocked(False)")

    # ---- read
    @staticmethod
    def _read_stories(m) -> tuple[float, list[Story]]:
        """Base elevation and stories sorted bottom-up (the API's order is not relied on)."""
        r = m.Story.GetStories_2()
        _ok(r[10], "Story.GetStories_2")
        stories = [Story(str(r[2][i]), float(r[3][i]), float(r[4][i]), bool(r[5][i]), str(r[6][i] or ""))
                   for i in range(int(r[1]))]
        stories.sort(key=lambda s: s.elevation_ft)
        return float(r[0]), stories

    @staticmethod
    def _read_grids(m, point_x_span_ft: float) -> tuple[list[GridSystem], list[GridLine], list[Diagnostic]]:
        """Grid systems and lines through the interactive tables, in global feet."""
        db = m.DatabaseTables
        avail = db.GetAvailableTables()
        _ok(avail[4], "DatabaseTables.GetAvailableTables")
        keys, names = [str(k) for k in avail[1]], [str(n) for n in avail[2]]
        key = find_grid_table(keys, names)
        fields = db.GetAllFieldsInTable(key)
        _ok(fields[7], f"DatabaseTables.GetAllFieldsInTable({key!r})")
        name_of = dict(zip(fields[2], fields[3], strict=True))
        unit_of = dict(zip(fields[2], fields[5], strict=True))
        table = db.GetTableForDisplayArray(key, [""], "")
        _ok(table[5], f"DatabaseTables.GetTableForDisplayArray({key!r})")
        included = [str(k) for k in table[2]]
        systems, lines, diags = parse_grid_table(
            included, [str(name_of.get(k, k)) for k in included], [str(unit_of.get(k, "")) for k in included],
            [str(v) for v in table[4]], int(table[3]), point_x_span_ft)
        diags.insert(0, Diagnostic("info", "grid_table_key", f"grid lines read from table {key!r}"))
        general = [k for k, n in zip(keys, names, strict=True)
                   if "grid" in n.lower() and "general" in n.lower()]
        if general:
            systems, lines, extra = _apply_grid_system_table(db, general[0], systems, lines)
            diags += extra
        return systems, lines, diags

    def read_model(self) -> ModelSnapshot:
        m = self.m
        base, stories = self._read_stories(m)
        pr = m.PointObj.GetAllPoints()
        _ok(pr[5], "PointObj.GetAllPoints")
        joints = [Joint(str(n), (float(x), float(y), float(z)))
                  for n, x, y, z in zip(pr[1], pr[2], pr[3], pr[4], strict=True)]
        xs = [j.xyz[0] for j in joints]
        systems, lines, diags = self._read_grids(m, (max(xs) - min(xs)) if xs else 0.0)
        groups = self.read_groups("W_")
        member_of: dict[str, list[str]] = {}
        for g, refs in groups.items():
            for ref in refs:
                member_of.setdefault(ref, []).append(g)
        ar = m.AreaObj.GetAllAreas()
        _ok(ar[9], "AreaObj.GetAllAreas")
        delims = [int(d) for d in ar[4]]
        inclusive = bool(delims) and delims[-1] == int(ar[3]) - 1
        shells: list[Shell] = []
        start = 0
        for name, d in zip(ar[1], delims, strict=True):
            end = d + 1 if inclusive else d
            corners = tuple((float(ar[6][i]), float(ar[7][i]), float(ar[8][i])) for i in range(start, end))
            start = end
            tm = m.AreaObj.GetTransformationMatrix(name)
            _ok(tm[1], f"AreaObj.GetTransformationMatrix({name})")
            local3 = (float(tm[0][6]), float(tm[0][7]), float(tm[0][8]))
            shells.append(Shell(str(name), corners, local3, tuple(member_of.get(f"A:{name}", ()))))
        fr = m.FrameObj.GetAllFrames()
        _ok(fr[20], "FrameObj.GetAllFrames")
        frames = [Frame(str(n), (float(x1), float(y1), float(z1)), (float(x2), float(y2), float(z2)),
                        tuple(member_of.get(f"F:{n}", ())))
                  for n, x1, y1, z1, x2, y2, z2 in zip(fr[1], fr[6], fr[7], fr[8], fr[9], fr[10], fr[11], strict=True)]
        labels: dict[str, tuple[str, str]] = {}
        for prefix, api in (("A", m.AreaObj), ("F", m.FrameObj), ("P", m.PointObj)):
            lr = api.GetLabelNameList()
            _ok(lr[4], f"{prefix}:GetLabelNameList")
            for n, lab, st in zip(lr[1], lr[2], lr[3], strict=True):
                labels[f"{prefix}:{n}"] = (str(lab), str(st))
        snap = ModelSnapshot(shells=shells, frames=frames, joints=joints, stories=stories, groups=groups,
                             base_elevation_ft=base, grid_systems=systems, grid_lines=lines, labels=labels,
                             read_diagnostics=diags)
        snap.existing_patterns = self.read_patterns()
        snap.existing_cases = list(self.read_cases())
        snap.existing_combos = list(self.read_combinations())
        return snap

    def read_groups(self, prefix: str = "W_") -> dict[str, list[str]]:
        n, names, ret = self.m.GroupDef.GetNameList()
        _ok(ret, "GroupDef.GetNameList")
        out: dict[str, list[str]] = {}
        tag = {1: "P", 2: "F", 5: "A"}
        for g in names or []:
            if prefix and not str(g).lower().startswith(prefix.lower()):
                continue
            n2, types, objs, r = self.m.GroupDef.GetAssignments(g)
            _ok(r, f"GroupDef.GetAssignments({g})")
            out[str(g)] = [f"{tag[t]}:{o}" for t, o in zip(types, objs, strict=True) if t in tag]
        return out

    # ---- groups
    def _object_api(self, ref: str):
        kind, obj = ref.split(":", 1)
        return getattr(self.m, {"A": "AreaObj", "F": "FrameObj", "P": "PointObj"}[kind]), obj

    def set_group(self, name: str, members: list[str]) -> GroupWriteResult:
        """Replace a group's membership (spec 8.1): read flags, delete, recreate, assign, read back."""
        gd = self.m.GroupDef
        n, names, ret = gd.GetNameList()
        _ok(ret, "GroupDef.GetNameList")
        existing = next((str(g) for g in names or [] if str(g).lower() == name.lower()), None)
        colour, flags = -1, ()
        if existing is not None:
            name = existing  # keep the model's own spelling
            r = gd.GetGroup_1(name)
            _ok(r[-1], f"GroupDef.GetGroup_1({name})")
            colour, flags = int(r[0]), tuple(bool(v) for v in r[1:-1])
            deleted = gd.Delete(name)
            still = [str(g) for g in (gd.GetNameList()[1] or []) if str(g).lower() == name.lower()]
            if deleted != 0 and still:
                raise AdapterError(f"group {name} could not be emptied (code {deleted}); "
                                   "it may still hold earlier members")
        _ok(gd.SetGroup_1(name, colour, *flags), f"GroupDef.SetGroup_1({name})")
        refused: list[tuple[str, int]] = []
        for ref in members:
            api, obj = self._object_api(ref)
            code = api.SetGroupAssign(obj, name)
            if code != 0:
                refused.append((ref, int(code)))
        n2, types, objs, r = gd.GetAssignments(name)
        _ok(r, f"GroupDef.GetAssignments({name})")
        tag = {1: "P", 2: "F", 5: "A"}
        present = {f"{tag[t]}:{o}" for t, o in zip(types or (), objs or (), strict=True) if t in tag}
        refused_refs = {ref for ref, _ in refused}
        missing = tuple(ref for ref in members if ref not in present and ref not in refused_refs)
        return GroupWriteResult(tuple(refused), missing)

    def delete_group(self, name: str) -> None:
        _ok(self.m.GroupDef.Delete(name), f"GroupDef.Delete({name})")

    def select_group(self, name: str) -> None:
        _ok(self.m.SelectObj.ClearSelection(), "ClearSelection")
        _ok(self.m.SelectObj.Group(name), f"SelectObj.Group({name})")
        self._etabs.SapModel.View.RefreshView(0, False)

    def select_objects(self, refs: list[str]) -> None:
        _ok(self.m.SelectObj.ClearSelection(), "ClearSelection")
        for ref in refs:
            api, obj = self._object_api(ref)
            _ok(api.SetSelected(obj, True), f"SetSelected({ref})")
        self._etabs.SapModel.View.RefreshView(0, False)

    # ---- manifest (stored next to the model file)
    def _manifest_path(self) -> str:
        return str(self.m.GetModelFilename()) + ".air_apparent.json"

    def read_manifest(self) -> dict:
        import json
        import os
        p = self._manifest_path()
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}

    def write_manifest(self, manifest: dict) -> None:
        import json
        with open(self._manifest_path(), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)

    # ---- definitions
    def define_pattern(self, spec: PatternSpec) -> None:
        if spec.name in self.read_patterns():
            return
        _ok(self.m.LoadPatterns.Add(spec.name, 6, 0.0, False), f"LoadPatterns.Add({spec.name})")  # 6 = Wind

    def define_case(self, spec: CaseSpec) -> None:
        sl = self.m.LoadCases.StaticLinear
        _ok(sl.SetCase(spec.name), f"StaticLinear.SetCase({spec.name})")
        n = len(spec.terms)
        _ok(sl.SetLoads(spec.name, n, ["Load"] * n, [t[0] for t in spec.terms],
                        [t[1] for t in spec.terms]), f"StaticLinear.SetLoads({spec.name})")

    def define_combination(self, spec: CombinationSpec) -> None:
        rc = self.m.RespCombo
        _ok(rc.Add(spec.name, 1 if spec.kind == "envelope" else 0), f"RespCombo.Add({spec.name})")
        known_cases = set(self.read_cases())
        for ref, f in spec.terms:
            ctype = 0 if ref in known_cases else 1
            _ok(rc.SetCaseList(spec.name, ctype, ref, f), f"RespCombo.SetCaseList({spec.name},{ref})")

    # ---- assignments
    def assign(self, a: Assignment) -> None:
        kind, obj = a.object_ref.split(":", 1)
        if a.kind == "shell_pressure":
            _ok(self.m.AreaObj.SetLoadUniform(obj, a.pattern, a.value, 3, True, "Local"),
                f"AreaObj.SetLoadUniform({obj})")
        elif a.kind == "joint_force":
            vals = [0.0] * 6
            vals[0 if a.global_dir == "X" else 1] = a.value
            _ok(self.m.PointObj.SetLoadForce(obj, a.pattern, vals, True, "Global"),
                f"PointObj.SetLoadForce({obj})")
        elif a.kind == "joint_moment":
            _ok(self.m.PointObj.SetLoadForce(obj, a.pattern, [0, 0, 0, 0, 0, a.value], True, "Global"),
                f"PointObj.SetLoadForce({obj}) moment")
        elif a.kind == "frame_line_load":
            _ok(self.m.FrameObj.SetLoadDistributed(obj, a.pattern, 1, _DIR_CODE[a.global_dir], 0.0, 1.0,
                                                   a.value, a.value, "Global", True, True),
                f"FrameObj.SetLoadDistributed({obj})")
        else:
            raise AdapterError(f"unknown assignment kind {a.kind}")

    def clear_assignment(self, kind: str, object_ref: str, pattern: str) -> None:
        _, obj = object_ref.split(":", 1)
        api = {"shell_pressure": lambda: self.m.AreaObj.DeleteLoadUniform(obj, pattern),
               "joint_force": lambda: self.m.PointObj.DeleteLoadForce(obj, pattern),
               "joint_moment": lambda: self.m.PointObj.DeleteLoadForce(obj, pattern),
               "frame_line_load": lambda: self.m.FrameObj.DeleteLoadDistributed(obj, pattern)}[kind]
        _ok(api(), f"clear {kind} {object_ref} {pattern}")

    def _loads(self, api, getter: str, width: int) -> list[tuple]:
        """Rows of a Get*Load* call, by the built-in group ``All`` or, if that is refused, per object."""
        r = getattr(api, getter)("All", 1)  # item type 1 = group
        if r[-1] == 0:
            return [tuple(r[i][k] for i in range(1, width)) for k in range(int(r[0]))]
        rows: list[tuple] = []
        for name in api.GetNameList()[1] or []:
            r = getattr(api, getter)(name, 0)
            _ok(r[-1], f"{getter}({name})")
            rows += [tuple(r[i][k] for i in range(1, width)) for k in range(int(r[0]))]
        return rows

    def read_assignments(self) -> list[Assignment]:
        """Tuple positions follow the documented out-parameter order (see docs/etabs_setup.md)."""
        out: list[Assignment] = []
        m = self.m
        for nm, pat, _csys, _dir, v in self._loads(m.AreaObj, "GetLoadUniform", 6):
            out.append(Assignment(f"{pat}|A:{nm}", "shell_pressure", f"A:{nm}", pat, v, "kip/ft2",
                                  "Local3", ""))
        for nm, pat, _step, _csys, f1, f2, _f3, _m1, _m2, m3 in self._loads(m.PointObj, "GetLoadForce", 11):
            if f1:
                out.append(Assignment(f"{pat}|P:{nm}", "joint_force", f"P:{nm}", pat, f1, "kip", "X", ""))
            if f2:
                out.append(Assignment(f"{pat}|P:{nm}", "joint_force", f"P:{nm}", pat, f2, "kip", "Y", ""))
            if m3:
                out.append(Assignment(f"{pat}|P:{nm}", "joint_moment", f"P:{nm}", pat, m3, "kip-ft", "Mz", ""))
        frame_rows = self._loads(m.FrameObj, "GetLoadDistributed", 12)
        for nm, pat, _type, _csys, d, _rd1, _rd2, _d1, _d2, v1, _v2 in frame_rows:
            out.append(Assignment(f"{pat}|F:{nm}", "frame_line_load", f"F:{nm}", pat, v1, "kip/ft",
                                  "X" if d == 4 else "Y", ""))
        return out

    def read_patterns(self) -> list[str]:
        return list(self.m.LoadPatterns.GetNameList()[1] or [])

    def read_cases(self) -> dict[str, tuple[tuple[str, float], ...]]:
        """Read static-linear terms and retain other case names with no linear terms."""
        out = {}
        cases = self.m.LoadCases
        for name in cases.GetNameList()[1] or []:
            case_type = cases.GetTypeOAPI(name)
            _ok(case_type[2], f"LoadCases.GetTypeOAPI({name})")
            if case_type[0] != 1:
                out[name] = ()
                continue
            r = cases.StaticLinear.GetLoads(name)
            _ok(r[4], f"StaticLinear.GetLoads({name})")
            out[name] = tuple(zip(r[2], r[3], strict=False)) if r[0] else ()
        return out

    def read_combinations(self) -> dict[str, tuple[str, tuple[tuple[str, float], ...]]]:
        out = {}
        for name in self.m.RespCombo.GetNameList()[1] or []:
            r = self.m.RespCombo.GetCaseList(name)
            _ok(r[4], f"RespCombo.GetCaseList({name})")
            kind = "envelope" if self.m.RespCombo.GetTypeCombo(name)[0] == 1 else "linear"
            out[name] = (kind, tuple(zip(r[2], r[3], strict=False)))
        return out


def _apply_grid_system_table(db, key: str, systems: list[GridSystem], lines: list[GridLine]):
    """Origin and rotation from the 'Grid Definitions - General' table, applied to the parsed lines."""
    fields = db.GetAllFieldsInTable(key)
    _ok(fields[7], f"DatabaseTables.GetAllFieldsInTable({key!r})")
    unit_of = dict(zip(fields[2], fields[5], strict=True))
    table = db.GetTableForDisplayArray(key, [""], "")
    _ok(table[5], f"DatabaseTables.GetTableForDisplayArray({key!r})")
    cols = [str(k) for k in table[2]]
    width = len(cols)
    rows = [[str(v) for v in table[4][i * width:(i + 1) * width]] for i in range(int(table[3]))]
    idx = {c.lower(): i for i, c in enumerate(cols)}
    if not {"name", "ux", "uy"} <= set(idx):
        return systems, lines, []
    factor = length_factor(str(unit_of.get(cols[idx["ux"]], ""))) or 1.0
    by_name = {s.name: s for s in systems}
    diags: list[Diagnostic] = []
    for r in rows:
        name = r[idx["name"]]
        if name not in by_name:
            continue
        old = by_name[name]
        rz = float(r[idx["rz"]]) if "rz" in idx and r[idx["rz"]] else 0.0
        kind = r[idx["type"]] if "type" in idx and r[idx["type"]] else old.kind
        by_name[name] = GridSystem(name, kind, float(r[idx["ux"]] or 0) * factor, float(r[idx["uy"]] or 0) * factor, rz)
    out_lines: list[GridLine] = []
    dropped: set[str] = set()
    for ln in lines:
        s = by_name.get(ln.system)
        if s is None:
            out_lines.append(ln)
        elif abs(s.rotation_deg) > 1e-9 or s.kind.lower() != "cartesian":
            dropped.add(ln.system)
        else:
            out_lines.append(GridLine(ln.system, ln.axis, ln.label,
                                      ln.ordinate_ft + (s.origin_x_ft if ln.axis == "x" else s.origin_y_ft)))
    for name in sorted(dropped):
        diags.append(Diagnostic("warning", "grid_system_unsupported",
                                f"grid system {name!r} is rotated or not Cartesian; its lines are not used", name))
    return list(by_name.values()), out_lines, diags
