"""Thin orchestration: wires config -> adapter -> categorization -> pressures -> plan -> apply."""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

from .categorization import categorize
from .config import effective_config_yaml, load_config, validate_config
from .demo import build_demo_snapshot
from .etabs import AdapterError, EtabsAdapter, FakeAdapter
from .models import (
    PATTERN_GROUP_NAMES,
    Assignment,
    Categorization,
    Config,
    Diagnostic,
    LoadPlan,
    ModelSnapshot,
    PatternSpec,
    PressureSet,
)
from .patterns import (
    build_plan,
    build_pressure_assignments,
    placeholder_pressure_pattern_specs,
)
from .pressures import calculate_pressures

MANIFEST_VERSION = 1


@dataclass
class ApplyResult:
    ok: bool
    message: str
    applied: dict[str, int] = field(default_factory=dict)
    partial: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class VerifyRow:
    check: str
    expected: str
    actual: str
    ok: bool


class WindSession:
    """Holds workflow state and invalidates dependent results when inputs change."""

    def __init__(self) -> None:
        self.adapter: EtabsAdapter | None = None
        self.cfg: Config | None = None
        self.config_hash = ""
        self.snapshot: ModelSnapshot | None = None
        self.cats: Categorization | None = None
        self.pressures: PressureSet | None = None
        self.plan: LoadPlan | None = None
        self.preview_valid = False
        self.groups_written = False  # the sixteen W_ groups have been written for the current categorization
        self.diagnostics: list[Diagnostic] = []
        self.verification: list[VerifyRow] = []
        self.apply_result: ApplyResult | None = None

    # ------------------------------------------------------------------ invalidation
    def _invalidate(self, from_model: bool = False) -> None:
        if from_model:
            self.snapshot = None
        self.cats = self.pressures = self.plan = None
        self.preview_valid = False
        self.groups_written = False
        self.verification = []
        self.apply_result = None

    # ------------------------------------------------------------------ steps 1-2
    def load_config(self, path: str) -> Config:
        cfg = load_config(path)
        self.cfg = cfg
        self.config_hash = hashlib.sha256(effective_config_yaml(cfg).encode()).hexdigest()[:12]
        self._invalidate()
        return cfg

    def use_offline_demo(self) -> None:
        self._need_cfg()
        self.adapter = FakeAdapter(build_demo_snapshot(self.cfg))
        self._invalidate(from_model=True)

    def set_loading_scope(self, scope: str) -> None:
        """Change active scope and invalidate dependent plans, previews and exports."""
        self._need_cfg()
        data = deepcopy(self.cfg.raw)
        data["loading"]["scope"] = scope
        cfg = validate_config(data, source_path=self.cfg.source_path)
        self.cfg = cfg
        self.config_hash = hashlib.sha256(effective_config_yaml(cfg).encode()).hexdigest()[:12]
        self._invalidate()

    def connect(self, adapter: EtabsAdapter) -> None:
        self.adapter = adapter
        self._invalidate(from_model=True)

    # ------------------------------------------------------------------ steps 3-4
    def read_model(self) -> ModelSnapshot:
        self._need_adapter()
        self.snapshot = self.adapter.read_model()
        self._invalidate()
        return self.snapshot

    def categorize(self) -> Categorization:
        self._need_cfg()
        if self.snapshot is None:
            self.read_model()
        self.cats = categorize(self.cfg, self.snapshot)
        self.pressures = self.plan = None
        self.preview_valid = False
        return self.cats

    def calculate(self) -> PressureSet:
        self._need_cfg()
        if self.cats is None:
            self.categorize()
        dims = None
        if self.cfg.geometry.plan_dimensions_source == "etabs":
            if not self.cats.derived_dims:
                raise ValueError("plan_dimensions_source is 'etabs' but no envelope could be derived")
            dims = self.cats.derived_dims
        self.pressures = calculate_pressures(self.cfg, dims)
        self.plan = None
        return self.pressures

    def build_plan(self) -> LoadPlan:
        if self.pressures is None:
            self.calculate()
        self.plan = build_plan(self.cfg, self.snapshot, self.cats, self.pressures)
        self.plan.diagnostics += self._audit()
        return self.plan

    def apply_group_pressures(
        self,
        patterns: Iterable[PatternSpec],
        assignments: Iterable[Assignment],
        allow_unlock: bool = False,
    ) -> ApplyResult:
        """Define pressure patterns and apply each pressure once to its ETABS group.

        ``assignments`` may contain one row per shell member, but the adapter
        receives one group-level call per unique ``(group, pattern, value)``.
        This is the bridge for the category-driven max/min pressure path.
        """

        self._need_adapter()
        if self.cats is None:
            return ApplyResult(False, "categorize the model before applying group pressures")
        if not self.groups_written:
            group_diags = self.write_pattern_groups()
            if group_diags:
                return ApplyResult(False, "category groups could not be initialized",
                                   diagnostics=group_diags)
        group_diags = self.check_group_drift()
        if group_diags:
            return ApplyResult(False, "category groups do not match the current rules",
                               diagnostics=group_diags)
        patterns = list(patterns)
        assignments = list(assignments)
        if any(a.kind != "shell_pressure" or not a.group for a in assignments):
            return ApplyResult(False, "group pressure assignments must be shell pressures with a group")
        if self.adapter.info().locked:
            if not allow_unlock:
                return ApplyResult(False, "model is locked; confirm allow_unlock=True before applying pressures")
            self.adapter.unlock()

        try:
            for spec in patterns:
                self.adapter.define_pattern(spec)
            unique_group_loads = {(a.group, a.pattern, a.value): a for a in assignments}
            for a in unique_group_loads.values():
                self.adapter.assign_group_pressure(a.group, a.pattern, a.value)
        except AdapterError as exc:
            return ApplyResult(False, f"group pressure application failed: {exc}")
        return ApplyResult(True, "group pressures applied", {
            "patterns": len(patterns),
            "assignments": len(unique_group_loads),
        })

    def apply_first_pass_group_pressures(self, allow_unlock: bool = False) -> ApplyResult:
        """Create category groups, then apply the first-pass group pressures."""
        if self.cats is None:
            self.categorize()
        groups = self.cats.groups
        return self.apply_group_pressures(
            placeholder_pressure_pattern_specs(groups),
            build_pressure_assignments(groups),
            allow_unlock=allow_unlock,
        )

    def _audit(self) -> list[Diagnostic]:
        manifest = self.adapter.read_manifest()
        owned = set(manifest.get("patterns", []))
        planned = {p.name for p in self.plan.patterns}
        out = []
        for p in self.snapshot.existing_patterns:
            if p in owned or p in planned:
                continue
            hint = " (looks like an obsolete automatic-wind leftover)" if p.startswith("AW_") else ""
            out.append(Diagnostic("info", "audit_unfamiliar_pattern",
                                  f"existing pattern {p!r} is not tool-owned; left untouched{hint}", p))
        return out

    # ------------------------------------------------------------------ steps 5-6
    def write_pattern_groups(self) -> list[Diagnostic]:
        """Write the sixteen W_* groups with replace semantics (group membership only; no loads)."""
        if self.cats is None:
            self.categorize()
        a = self.adapter
        diags: list[Diagnostic] = []
        for name in PATTERN_GROUP_NAMES:
            res = a.set_group(name, list(self.cats.pattern_groups.get(name, ())))
            for ref, code in res.refused:
                diags.append(Diagnostic("error", "group_assign_refused",
                                        f"{name}: ETABS refused {ref} (return code {code})", ref))
            for ref in res.missing_after_readback:
                diags.append(Diagnostic("error", "group_member_missing",
                                        f"{name}: {ref} is not in the group after writing", ref))
        manifest = a.read_manifest()
        manifest.update({"version": MANIFEST_VERSION, "groups": list(PATTERN_GROUP_NAMES)})
        a.write_manifest(manifest)
        self.preview_valid = not any(d.level == "error" for d in diags)
        self.groups_written = True
        return diags

    create_preview_groups = write_pattern_groups  # transitional alias for the GUI (Task 13)

    def check_group_drift(self) -> list[Diagnostic]:
        """Re-read the W_* groups and compare with the rules' membership; drift invalidates the preview."""
        current = {k.lower(): set(v) for k, v in self.adapter.read_groups("W_").items()}
        diags: list[Diagnostic] = []
        for name in PATTERN_GROUP_NAMES:
            want = set(self.cats.pattern_groups.get(name, ()))
            have = current.get(name.lower())
            if have is None:
                if want:
                    diags.append(Diagnostic("error", "group_drift",
                                            f"{name}: not in the model ({len(want)} members expected)", name))
                continue
            if have != want:
                diags.append(Diagnostic("error", "group_drift",
                                        f"{name}: model has {len(have)} members, rules give {len(want)} "
                                        f"({len(have - want)} added, {len(want - have)} removed)", name))
        if diags:
            self.preview_valid = False
        return diags

    def select_group(self, name: str) -> None:
        """Select a W_* group in ETABS (writing the groups first if needed) or a fine group's members."""
        self._need_adapter()
        if self.cats is None:
            raise ValueError("Calculate first, then select a group from the current categorization")
        if name in PATTERN_GROUP_NAMES:
            if not self.groups_written:
                diags = self.write_pattern_groups()
                if diags:
                    raise AdapterError("; ".join(d.message for d in diags))
            drift = self.check_group_drift()
            if drift:
                raise AdapterError("group drift: " + "; ".join(d.message for d in drift))
            self.adapter.select_group(name)
            return
        spec = next((g for g in self.cats.groups if g.name == name), None)
        if spec is None:
            raise ValueError(f"unknown group {name!r}: use a W_ group or a fine group from the current categorization")
        self.adapter.select_objects(list(spec.members))

    # ------------------------------------------------------------------ step 7
    def apply(self, allow_unlock: bool = False) -> ApplyResult:
        res = self._apply(allow_unlock)
        self.apply_result = res
        return res

    def _apply(self, allow_unlock: bool) -> ApplyResult:
        if self.plan is None or self.cats is None:
            return ApplyResult(False, "no load plan; calculate and build the plan first")
        if not self.preview_valid:
            return ApplyResult(False, "W_ groups have not been written or are outdated; write them and review")
        errors = [d for d in self.plan.diagnostics if d.level == "error"]
        if errors:
            return ApplyResult(False, f"plan has {len(errors)} error(s)", diagnostics=errors)
        a = self.adapter
        drift = self.check_group_drift()
        if drift:
            return ApplyResult(False, "W_ group membership in the model differs from the rules; write the "
                                      "groups again and review", diagnostics=drift)
        manifest = a.read_manifest()
        conflicts = self._name_conflicts(manifest)
        if conflicts:
            return ApplyResult(False, "name conflicts with unrelated model content", diagnostics=conflicts)
        notes = []
        recovered_cases = self._recoverable_cases(manifest)
        for name in sorted(recovered_cases):
            notes.append(Diagnostic("info", "matching_case_reused",
                                    f"reusing matching case {name!r} referencing tool-owned patterns", name))
        if a.info().locked:
            if not allow_unlock:
                return ApplyResult(False, "model is locked; unlocking discards analysis results. "
                                          "Re-run with allow_unlock=True after confirming.")
            a.unlock()
            notes.append(Diagnostic("warning", "unlocked", "model was unlocked; analysis results lost"))
        counts = {"patterns": 0, "assignments": 0, "cleared": 0, "cases": 0, "combinations": 0}
        new_manifest = {**manifest, "version": MANIFEST_VERSION, "patterns": [], "cases": [],
                        "combinations": [], "assignments": list(manifest.get("assignments", []))}
        try:
            for p in self.plan.patterns:
                a.define_pattern(p)
                new_manifest["patterns"].append(p.name)
                counts["patterns"] += 1
            wanted = {(x.kind, x.object_ref, x.pattern) for x in self.plan.assignments}
            for kind, ref, pat in manifest.get("assignments", []):
                if (kind, ref, pat) not in wanted:
                    a.clear_assignment(kind, ref, pat)
                    counts["cleared"] += 1
            for x in self.plan.assignments:
                a.assign(x)
                counts["assignments"] += 1
            new_manifest["assignments"] = sorted([k, r, p] for k, r, p in wanted)
            for c in self.plan.cases:
                if c.name not in recovered_cases:
                    a.define_case(c)
                new_manifest["cases"].append(c.name)
                counts["cases"] += 1
            for kind in ("linear", "envelope"):
                for c in (x for x in self.plan.combinations if x.kind == kind):
                    a.define_combination(c)
                    new_manifest["combinations"].append(c.name)
                    counts["combinations"] += 1
        except AdapterError as exc:
            a.write_manifest(new_manifest)
            return ApplyResult(False, f"stopped after a failure: {exc}. Changes already made were NOT "
                                      "rolled back; applied counts are listed.", counts, True, notes)
        a.write_manifest(new_manifest)
        return ApplyResult(True, "load plan applied", counts, False, notes)

    def _name_conflicts(self, manifest: dict) -> list[Diagnostic]:
        a = self.adapter
        out = []
        recovered_cases = self._recoverable_cases(manifest)
        for label, existing, planned, owned in (
            ("pattern", set(a.read_patterns()), {p.name for p in self.plan.patterns},
             set(manifest.get("patterns", []))),
            ("case", set(a.read_cases()), {c.name for c in self.plan.cases},
             set(manifest.get("cases", []))),
            ("combination", set(a.read_combinations()), {c.name for c in self.plan.combinations},
             set(manifest.get("combinations", []))),
        ):
            for n in sorted((existing & planned) - owned):
                if label == "case" and n in recovered_cases:
                    continue
                out.append(Diagnostic("error", "name_conflict",
                                      f"{label} {n!r} already exists and is not tool-owned", n))
        return out

    def _recoverable_cases(self, manifest: dict) -> set[str]:
        """Reuse exact component cases left by an interrupted apply without overwriting them."""
        owned_patterns = set(manifest.get("patterns", []))
        if not owned_patterns:
            return set()
        existing = self.adapter.read_cases()
        owned_cases = set(manifest.get("cases", []))
        return {c.name for c in self.plan.cases
                if c.name.startswith("AA_") and c.name not in owned_cases and c.terms
                and all(p in owned_patterns for p, _ in c.terms) and existing.get(c.name) == c.terms}

    # ------------------------------------------------------------------ step 8
    def verify(self) -> list[VerifyRow]:
        """Read back and reconcile counts, resultants, moments and factors."""
        rows: list[VerifyRow] = []
        a = self.adapter
        plan = self.plan
        patterns = {p.name for p in plan.patterns}
        readback = a.read_assignments(patterns)
        have = {}
        duplicates = set()
        for assignment in readback:
            key = (assignment.kind, assignment.object_ref, assignment.pattern)
            if key in have:
                duplicates.add(key)
            have[key] = assignment
        want = {(x.kind, x.object_ref, x.pattern): x for x in plan.assignments}
        rows.append(VerifyRow("assignment count", str(len(want)), str(len(readback)),
                              len(readback) == len(want) == len(have)))
        bad = [k for k, v in want.items() if k in duplicates or k not in have
               or not math.isclose(have[k].value, v.value, rel_tol=1e-9, abs_tol=1e-12)
               or have[k].global_dir != v.global_dir]
        rows.append(VerifyRow("assignment values", "0 mismatches", f"{len(bad)} mismatches", not bad))
        pats = set(a.read_patterns())
        missing = [p.name for p in plan.patterns if p.name not in pats]
        rows.append(VerifyRow("patterns defined", str(len(plan.patterns)),
                              str(len(plan.patterns) - len(missing)), not missing))
        cases = a.read_cases()
        bad_cases = [c.name for c in plan.cases if cases.get(c.name) != c.terms]
        rows.append(VerifyRow("case terms/factors", f"{len(plan.cases)} match",
                              f"{len(plan.cases) - len(bad_cases)} match", not bad_cases))
        combos = a.read_combinations()
        bad_combos = [c.name for c in plan.combinations
                      if combos.get(c.name) != (c.kind, c.terms)]
        rows.append(VerifyRow("combination terms/factors", f"{len(plan.combinations)} match",
                              f"{len(plan.combinations) - len(bad_combos)} match", not bad_combos))
        for pat in sorted({p.name for p in plan.patterns}):
            e = _resultant(plan.assignments, self.snapshot, pat)
            r = _resultant(list(have.values()), self.snapshot, pat)
            ok = all(math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9) for x, y in zip(e, r, strict=True))
            if any(abs(x) > 0 for x in e) or any(abs(x) > 0 for x in r):
                rows.append(VerifyRow(f"{pat} resultant Fx,Fy,Mz(origin)",
                                      ", ".join(f"{x:.4f}" for x in e), ", ".join(f"{x:.4f}" for x in r), ok))
        self.verification = rows
        return rows

    # ------------------------------------------------------------------ helpers
    def _need_cfg(self) -> None:
        if self.cfg is None:
            raise ValueError("load a YAML configuration first")

    def _need_adapter(self) -> None:
        if self.adapter is None:
            raise ValueError("connect to ETABS or open the offline demo first")


def _area_and_centroid(corners):
    n = len(corners)
    ax = ay = az = 0.0
    for i in range(n):
        x1, y1, z1 = corners[i]
        x2, y2, z2 = corners[(i + 1) % n]
        ax += (y1 - y2) * (z1 + z2)
        ay += (z1 - z2) * (x1 + x2)
        az += (x1 - x2) * (y1 + y2)
    area = 0.5 * math.sqrt(ax * ax + ay * ay + az * az)
    c = tuple(sum(p[i] for p in corners) / n for i in range(3))
    return area, c


def _resultant(assignments: list[Assignment], snap: ModelSnapshot, pattern: str):
    """(Fx, Fy, Mz about the global origin) of all assignments in a pattern."""
    shells = {s.name: s for s in snap.shells}
    frames = {f.name: f for f in snap.frames}
    joints = {j.name: j for j in snap.joints}
    fx = fy = mz = 0.0
    for a in assignments:
        if a.pattern != pattern:
            continue
        name = a.object_ref[2:]
        if a.kind == "shell_pressure":
            s = shells[name]
            area, (x, y, _) = _area_and_centroid(s.corners)
            f = (a.value * area * s.local3[0], a.value * area * s.local3[1])
        elif a.kind == "joint_force":
            x, y, _ = joints[name].xyz
            f = (a.value, 0.0) if a.global_dir == "X" else (0.0, a.value)
        elif a.kind == "frame_line_load":
            fr = frames[name]
            length = math.dist(fr.p1, fr.p2)
            x, y = (fr.p1[0] + fr.p2[0]) / 2, (fr.p1[1] + fr.p2[1]) / 2
            f = (a.value * length, 0.0) if a.global_dir == "X" else (0.0, a.value * length)
        else:  # joint_moment
            mz += a.value
            continue
        fx += f[0]
        fy += f[1]
        mz += x * f[1] - y * f[0]
    return fx, fy, mz
