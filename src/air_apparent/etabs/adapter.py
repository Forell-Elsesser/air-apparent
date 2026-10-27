"""Narrow ETABS adapter protocol plus the optional live COM implementation.

ETABS 23.3.1 geometry, preview, selection, and load read-back were exercised on a saved model copy.
Load application remains blocked by model and configuration diagnostics. ``comtypes`` is imported
lazily and only on Windows.
"""

from __future__ import annotations

import math
import subprocess
import sys
from contextlib import contextmanager
from typing import Protocol

from ..models import (
    Assignment,
    CaseSpec,
    CombinationSpec,
    Frame,
    Joint,
    ModelInfo,
    ModelSnapshot,
    PatternSpec,
    Shell,
    Story,
)


class AdapterError(RuntimeError):
    """A call failed, returned a non-zero API code, or violated its return contract."""


class EtabsAdapter(Protocol):
    def info(self) -> ModelInfo: ...
    def read_model(self) -> ModelSnapshot: ...
    def read_groups(self) -> dict[str, list[str]]: ...
    def set_group(self, name: str, members: list[str]) -> None:
        """Create the group or replace its membership entirely."""
    def delete_group(self, name: str) -> None: ...
    def select_group(self, name: str) -> None: ...
    def unlock(self) -> None: ...
    def read_manifest(self) -> dict: ...
    def write_manifest(self, manifest: dict) -> None: ...
    def define_pattern(self, spec: PatternSpec) -> None: ...
    def define_case(self, spec: CaseSpec) -> None: ...
    def define_combination(self, spec: CombinationSpec) -> None: ...
    def assign(self, a: Assignment) -> None:
        """Set a load with replace semantics, so reapplying never accumulates."""
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
    def read_model(self) -> ModelSnapshot:
        with self._kip_ft_units():
            return self._read_model_in_kip_ft()

    def _read_model_in_kip_ft(self) -> ModelSnapshot:
        m = self.m
        pts = {}
        for name in m.PointObj.GetNameList()[1] or []:
            x, y, z, r = m.PointObj.GetCoordCartesian(name)
            _ok(r, f"PointObj.GetCoordCartesian({name})")
            pts[name] = (x, y, z)
        snap = ModelSnapshot(joints=[Joint(k, v) for k, v in pts.items()])
        groups = self.read_groups()
        member_of: dict[str, list[str]] = {}
        for g, refs in groups.items():
            for r in refs:
                member_of.setdefault(r, []).append(g)
        for name in m.AreaObj.GetNameList()[1] or []:
            _, plist, r = m.AreaObj.GetPoints(name)
            _ok(r, f"AreaObj.GetPoints({name})")
            local3 = _area_local3(m.AreaObj.GetTransformationMatrix(name), name)
            snap.shells.append(Shell(name, tuple(pts[p] for p in plist), local3,
                                     tuple(member_of.get(f"A:{name}", ()))))
        for name in m.FrameObj.GetNameList()[1] or []:
            p1, p2, r = m.FrameObj.GetPoints(name)
            _ok(r, f"FrameObj.GetPoints({name})")
            snap.frames.append(Frame(name, pts[p1], pts[p2], tuple(member_of.get(f"F:{name}", ()))))
        stories = m.Story.GetStories_2()
        for nm, el in zip(stories[2], stories[3], strict=False):
            snap.stories.append(Story(nm, float(el)))
        snap.groups = groups
        snap.existing_patterns = self.read_patterns()
        snap.existing_cases = list(self.read_cases())
        snap.existing_combos = list(self.m.RespCombo.GetNameList()[1] or [])
        return snap

    def read_groups(self) -> dict[str, list[str]]:
        n, names, ret = self.m.GroupDef.GetNameList()
        out: dict[str, list[str]] = {}
        tag = {1: "P", 2: "F", 5: "A"}
        for g in names or []:
            n2, types, objs, r = self.m.GroupDef.GetAssignments(g)
            _ok(r, f"GroupDef.GetAssignments({g})")
            out[g] = [f"{tag[t]}:{o}" for t, o in zip(types, objs, strict=True) if t in tag]
        return out

    # ---- groups
    def set_group(self, name: str, members: list[str]) -> None:
        if name in self.read_groups():
            _ok(self.m.GroupDef.Delete(name), f"GroupDef.Delete({name})")
        _ok(self.m.GroupDef.SetGroup(name), f"GroupDef.SetGroup({name})")
        for ref in members:
            kind, obj = ref.split(":", 1)
            api = {"A": self.m.AreaObj, "F": self.m.FrameObj, "P": self.m.PointObj}[kind]
            _ok(api.SetGroupAssign(obj, name), f"SetGroupAssign({ref}, {name})")

    def delete_group(self, name: str) -> None:
        _ok(self.m.GroupDef.Delete(name), f"GroupDef.Delete({name})")

    def select_group(self, name: str) -> None:
        _ok(self.m.SelectObj.ClearSelection(), "ClearSelection")
        _ok(self.m.SelectObj.Group(name), f"SelectObj.Group({name})")
        self._etabs.SapModel.View.RefreshView()

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
