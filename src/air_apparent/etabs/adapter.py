"""Narrow ETABS adapter protocol plus the optional live COM implementation.

LIVE VERIFICATION STATUS: ``ComEtabsAdapter`` has NOT been exercised against a running ETABS
instance. API signatures were written from memory of the ETABS OAPI documentation and must be
verified against the installed version's documentation (see docs/etabs_setup.md) before use.
``comtypes`` is imported lazily and only on Windows.
"""

from __future__ import annotations

import subprocess
import sys
import math
from contextlib import contextmanager
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
    def assign_group_pressure(self, group: str, pattern: str, value: float) -> None:
        """Apply a uniform local-3 shell pressure to every area in a group."""
    def clear_assignment(self, kind: str, object_ref: str, pattern: str) -> None: ...
    def read_assignments(self, patterns: set[str] | None = None) -> list[Assignment]: ...
    def read_patterns(self) -> list[str]: ...
    def read_cases(self) -> dict[str, tuple[tuple[str, float], ...]]: ...
    def read_combinations(self) -> dict[str, tuple[str, tuple[tuple[str, float], ...]]]: ...


_PROG_ID = "CSI.ETABS.API.ETABSObject"
_KIP_FT_F = 4  # eUnits.kip_ft_F
_DIR_CODE = {"X": 4, "Y": 5, "Local3": 3}
_STATIC_LINEAR_CASE_TYPE = 1  # eLoadCaseType.StaticLinear


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
    # comtypes includes updated in/out arguments before the final API status,
    # e.g. StaticLinear.SetLoads returns [LoadType, LoadName, SF, 0].
    if isinstance(ret, (list, tuple)) and ret:
        ret = ret[-1]
    if ret != 0:
        raise AdapterError(f"{what} failed (return code {ret})")


def _static_case_terms(response, name: str) -> tuple[tuple[str, float], ...]:
    if len(response) != 5:
        raise AdapterError(f"LoadCases.StaticLinear.GetLoads({name}) returned an unexpected result")
    count, _, load_names, scale_factors, ret = response
    _ok(ret, f"LoadCases.StaticLinear.GetLoads({name})")
    if count == 0:
        return ()
    if len(load_names) != count or len(scale_factors) != count:
        raise AdapterError(f"LoadCases.StaticLinear.GetLoads({name}) returned inconsistent item counts")
    return tuple(zip(load_names, scale_factors, strict=True))


def _case_type(response, name: str) -> int:
    # ETABS returns CaseType, SubType, then the API return code through comtypes.
    # Also accept the two-value form used by wrappers that omit SubType.
    if not isinstance(response, (list, tuple)) or len(response) not in (2, 3):
        raise AdapterError(
            f"LoadCases.GetTypeOAPI({name}) returned an unexpected result: {response!r}"
        )
    case_type, ret = response[0], response[-1]
    _ok(ret, f"LoadCases.GetTypeOAPI({name})")
    return case_type


def _area_local3(response, name: str) -> tuple[float, float, float]:
    val, ret = response
    _ok(ret, f"AreaObj.GetTransformationMatrix({name})")
    # Columns transform local basis vectors into global coordinates.
    return (val[2], val[5], val[8])


def _area_load_direction(csys: str, direction: int) -> str:
    if csys == "Local" and direction in (1, 2, 3):
        return f"Local{direction}"
    if csys == "Global" and direction in (4, 5, 6):
        return f"Global{'XYZ'[direction - 4]}"
    if csys == "Projected" and direction in (7, 8, 9):
        return f"Projected{'XYZ'[direction - 7]}"
    raise AdapterError(f"unsupported area load coordinates: {csys} direction {direction}")


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

    def close(self) -> None:
        _ok(self.m.SetPresentUnits(self._prior_units), "restore present units")

    @contextmanager
    def _kip_ft_units(self):
        prior_units = self.m.GetPresentUnits()
        _ok(self.m.SetPresentUnits(_KIP_FT_F), "SetPresentUnits(kip_ft_F)")
        try:
            yield
        finally:
            _ok(self.m.SetPresentUnits(prior_units), "restore present units")

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
        with self._kip_ft_units():
            return self._read_model_in_kip_ft()

    def _read_model_in_kip_ft(self) -> ModelSnapshot:
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
            local3 = _area_local3(m.AreaObj.GetTransformationMatrix(name), name)
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
        snap.existing_combos = list(self.m.RespCombo.GetNameList()[1] or [])
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
        with self._kip_ft_units():
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

    def assign_group_pressure(self, group: str, pattern: str, value: float) -> None:
        """Apply a uniform local-3 pressure to all shells in an ETABS group."""
        _ok(
            self.m.AreaObj.SetLoadUniform(group, pattern, value, 3, True, "Local", 1),
            f"AreaObj.SetLoadUniform(group={group})",
        )

    def clear_assignment(self, kind: str, object_ref: str, pattern: str) -> None:
        with self._kip_ft_units():
            _, obj = object_ref.split(":", 1)
            api = {"shell_pressure": lambda: self.m.AreaObj.DeleteLoadUniform(obj, pattern),
                   "joint_force": lambda: self.m.PointObj.DeleteLoadForce(obj, pattern),
                   "joint_moment": lambda: self.m.PointObj.DeleteLoadForce(obj, pattern),
                   "frame_line_load": lambda: self.m.FrameObj.DeleteLoadDistributed(obj, pattern)}[kind]
            _ok(api(), f"clear {kind} {object_ref} {pattern}")

    def read_assignments(self, patterns: set[str] | None = None) -> list[Assignment]:
        out: list[Assignment] = []
        with self._kip_ft_units():
            m = self.m
            areas = m.AreaObj.GetNameList()
            _ok(areas[-1], "AreaObj.GetNameList")
            for name in areas[1] or []:
                r = m.AreaObj.GetLoadUniform(name)
                _ok(r[-1], f"AreaObj.GetLoadUniform({name})")
                for nm, pat, csys, direction, value in zip(
                        r[1], r[2], r[3], r[4], r[5], strict=True):
                    if patterns is not None and pat not in patterns:
                        continue
                    axis = _area_load_direction(csys, direction)
                    out.append(Assignment(f"{pat}|A:{nm}", "shell_pressure", f"A:{nm}", pat, value,
                                          "kip/ft2", axis, ""))

            points = m.PointObj.GetNameList()
            _ok(points[-1], "PointObj.GetNameList")
            for name in points[1] or []:
                r = m.PointObj.GetLoadForce(name)
                _ok(r[-1], f"PointObj.GetLoadForce({name})")
                for nm, pat, csys, f1, f2, m3 in zip(
                        r[1], r[2], r[4], r[5], r[6], r[10], strict=True):
                    if patterns is not None and pat not in patterns:
                        continue
                    if csys != "Global":
                        raise AdapterError(f"unsupported joint load coordinates for P:{nm} / {pat}: {csys}")
                    if f1:
                        out.append(Assignment(f"{pat}|P:{nm}", "joint_force", f"P:{nm}", pat,
                                              f1, "kip", "X", ""))
                    if f2:
                        out.append(Assignment(f"{pat}|P:{nm}", "joint_force", f"P:{nm}", pat,
                                              f2, "kip", "Y", ""))
                    if m3:
                        out.append(Assignment(f"{pat}|P:{nm}", "joint_moment", f"P:{nm}", pat,
                                              m3, "kip-ft", "Mz", ""))

            frames = m.FrameObj.GetNameList()
            _ok(frames[-1], "FrameObj.GetNameList")
            for name in frames[1] or []:
                r = m.FrameObj.GetLoadDistributed(name)
                _ok(r[-1], f"FrameObj.GetLoadDistributed({name})")
                for nm, pat, load_type, csys, direction, relative1, relative2, value1, value2 in zip(
                        r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[10], r[11], strict=True):
                    if patterns is not None and pat not in patterns:
                        continue
                    if csys != "Global" or direction not in (4, 5):
                        raise AdapterError(f"unsupported frame load coordinates for F:{nm} / {pat}: "
                                           f"{csys} direction {direction}")
                    if load_type != 1 or not math.isclose(relative1, 0.0) \
                            or not math.isclose(relative2, 1.0):
                        raise AdapterError(f"unsupported frame load distribution for F:{nm} / {pat}")
                    if value1 != value2:
                        raise AdapterError(f"non-uniform frame load on F:{nm} / {pat} cannot be "
                                           "represented by a single assignment value")
                    out.append(Assignment(f"{pat}|F:{nm}", "frame_line_load", f"F:{nm}", pat, value1,
                                          "kip/ft", "X" if direction == 4 else "Y", ""))
        return out

    def read_patterns(self) -> list[str]:
        return list(self.m.LoadPatterns.GetNameList()[1] or [])

    def read_cases(self) -> dict[str, tuple[tuple[str, float], ...]]:
        """Read static-linear terms and retain other case names with no linear terms."""
        out = {}
        for name in self.m.LoadCases.GetNameList()[1] or []:
            if _case_type(self.m.LoadCases.GetTypeOAPI(name), name) != _STATIC_LINEAR_CASE_TYPE:
                out[name] = ()
                continue
            r = self.m.LoadCases.StaticLinear.GetLoads(name)
            out[name] = _static_case_terms(r, name)
        return out

    def read_combinations(self) -> dict[str, tuple[str, tuple[tuple[str, float], ...]]]:
        out = {}
        for name in self.m.RespCombo.GetNameList()[1] or []:
            count, _, names, factors, ret = self.m.RespCombo.GetCaseList(name)
            _ok(ret, f"RespCombo.GetCaseList({name})")
            if len(names or ()) != count or len(factors or ()) != count:
                raise AdapterError(f"RespCombo.GetCaseList({name}) returned inconsistent item counts")
            combo_type, ret = self.m.RespCombo.GetTypeCombo(name)
            _ok(ret, f"RespCombo.GetTypeCombo({name})")
            kind = "envelope" if combo_type == 1 else "linear"
            out[name] = (kind, tuple(zip(names or (), factors or (), strict=True)))
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
