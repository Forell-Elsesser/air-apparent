"""In-memory ETABS stand-in used by the offline demo and the tests."""

from __future__ import annotations

import copy
from dataclasses import replace

from ..models import (
    Assignment,
    CaseSpec,
    CombinationSpec,
    ModelInfo,
    ModelSnapshot,
    PatternSpec,
)
from .adapter import AdapterError, GroupWriteResult


class FakeAdapter:
    def __init__(self, snapshot: ModelSnapshot, locked: bool = False, fail_on: str = ""):
        self.snapshot = snapshot
        self.locked = locked
        self.fail_on = fail_on  # substring of an operation name that should fail, e.g. "assign"
        self.groups: dict[str, list[str]] = {k: list(v) for k, v in snapshot.groups.items()}
        self.patterns: dict[str, PatternSpec] = {}
        self.extra_patterns: list[str] = list(snapshot.existing_patterns)
        self.cases: dict[str, CaseSpec] = {}
        self.combos: dict[str, CombinationSpec] = {}
        self.assignments: dict[tuple[str, str, str], Assignment] = {}
        self.manifest: dict = {}
        self.selected: str = ""
        self.selected_objects: list[str] = []
        self.unlocked_count = 0
        self.calls: list[str] = []

    def _op(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_on and self.fail_on in name:
            raise AdapterError(f"injected failure in {name}")

    def info(self) -> ModelInfo:
        return ModelInfo("offline-demo.edb", 0, "fake", "kip, ft, F", self.locked)

    def read_model(self) -> ModelSnapshot:
        snap = copy.deepcopy(self.snapshot)
        snap.groups = self.read_groups("W_")
        member_of: dict[str, list[str]] = {}
        for g, refs in snap.groups.items():
            for r in refs:
                member_of.setdefault(r, []).append(g)
        snap.shells = [replace(s, groups=tuple(member_of.get(f"A:{s.name}", ()))) for s in snap.shells]
        snap.frames = [replace(f, groups=tuple(member_of.get(f"F:{f.name}", ()))) for f in snap.frames]
        snap.existing_patterns = self.read_patterns()
        snap.existing_cases = list(self.cases)
        snap.existing_combos = list(self.combos)
        return snap

    def read_groups(self, prefix: str = "W_") -> dict[str, list[str]]:
        return {k: list(v) for k, v in self.groups.items()
                if not prefix or k.lower().startswith(prefix.lower())}

    def set_group(self, name: str, members: list[str]) -> GroupWriteResult:
        self._op(f"set_group:{name}")
        name = next((k for k in self.groups if k.lower() == name.lower()), name)  # keep the model's spelling
        self.groups[name] = list(members)
        return GroupWriteResult()

    def delete_group(self, name: str) -> None:
        self._op(f"delete_group:{name}")
        self.groups.pop(name, None)

    def select_group(self, name: str) -> None:
        self._op(f"select_group:{name}")
        if name not in self.groups:
            raise AdapterError(f"group {name} does not exist")
        self.selected = name

    def select_objects(self, refs: list[str]) -> None:
        self._op(f"select_objects:{len(refs)}")
        self.selected_objects = list(refs)

    def unlock(self) -> None:
        self._op("unlock")
        self.locked = False
        self.unlocked_count += 1

    def read_manifest(self) -> dict:
        return copy.deepcopy(self.manifest)

    def write_manifest(self, manifest: dict) -> None:
        self.manifest = copy.deepcopy(manifest)

    def define_pattern(self, spec: PatternSpec) -> None:
        self._op(f"define_pattern:{spec.name}")
        self.patterns[spec.name] = spec

    def define_case(self, spec: CaseSpec) -> None:
        self._op(f"define_case:{spec.name}")
        for pat, _ in spec.terms:
            if pat not in self.patterns:
                raise AdapterError(f"case {spec.name} references undefined pattern {pat}")
        self.cases[spec.name] = spec

    def define_combination(self, spec: CombinationSpec) -> None:
        self._op(f"define_combination:{spec.name}")
        for ref, _ in spec.terms:
            if ref not in self.cases and ref not in self.combos:
                raise AdapterError(f"combination {spec.name} references undefined {ref}")
        self.combos[spec.name] = spec

    def assign(self, a: Assignment) -> None:
        self._op(f"assign:{a.pattern}:{a.object_ref}")
        if a.pattern not in self.patterns:
            raise AdapterError(f"pattern {a.pattern} is not defined")
        self.assignments[(a.kind, a.object_ref, a.pattern)] = a  # replace semantics

    def clear_assignment(self, kind: str, object_ref: str, pattern: str) -> None:
        self._op(f"clear:{pattern}:{object_ref}")
        self.assignments.pop((kind, object_ref, pattern), None)

    def read_assignments(self, patterns: set[str] | None = None) -> list[Assignment]:
        assignments = self.assignments.values()
        if patterns is not None:
            assignments = (a for a in assignments if a.pattern in patterns)
        return list(assignments)

    def read_patterns(self) -> list[str]:
        return sorted(set(self.extra_patterns) | set(self.patterns))

    def read_cases(self):
        return {k: v.terms for k, v in self.cases.items()}

    def read_combinations(self):
        return {k: (v.kind, v.terms) for k, v in self.combos.items()}
