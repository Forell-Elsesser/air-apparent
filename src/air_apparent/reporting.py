"""Exports: effective YAML, assignment plan (JSON/CSV) and a concise HTML report."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import asdict
from pathlib import Path

from .config import effective_config_yaml
from .workflow import WindSession


def plan_rows(session: WindSession) -> list[dict]:
    """One row per assignment with the numeric pressure/force kept out of group names."""
    rows = []
    for a in session.plan.assignments:
        rows.append({
            "pattern": a.pattern, "object": a.object_ref, "kind": a.kind, "group": a.group,
            "result_id": a.result_id, "direction": a.direction, "code_pressure_psf": a.code_pressure_psf,
            "sign": a.sign, "value": a.value, "units": a.units, "etabs_dir": a.global_dir, "note": a.note,
        })
    return rows


def group_table(session: WindSession) -> list[dict]:
    ps = session.pressures
    out = []
    for g in session.plan.groups:
        vals = []
        for rid in filter(None, g.result_id.split("|")):
            r = ps.results.get(rid)
            vals.append(f"{r.value:.4f} {r.units}" if r else "n/a")
        out.append({"group": g.name, "category": g.category, "band": g.band, "direction": g.direction,
                    "role": g.role, "result_id": g.result_id, "value": " | ".join(vals),
                    "pattern": g.pattern, "members": len(g.members), "sign": g.assignment_sign})
    return out


def export_all(session: WindSession, outdir: str | Path) -> list[Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    p_yaml = out / "effective_config.yaml"
    p_yaml.write_text(effective_config_yaml(session.cfg), encoding="utf-8")
    rows = plan_rows(session)
    p_json = out / "assignment_plan.json"
    p_json.write_text(json.dumps({
        "patterns": [asdict(p) for p in session.plan.patterns],
        "cases": [asdict(c) for c in session.plan.cases],
        "combinations": [asdict(c) for c in session.plan.combinations],
        "groups": group_table(session), "assignments": rows}, indent=2), encoding="utf-8")
    p_csv = out / "assignment_plan.csv"
    with p_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["pattern"])
        w.writeheader()
        w.writerows(rows)
    p_html = out / "report.html"
    p_html.write_text(html_report(session), encoding="utf-8")
    return [p_yaml, p_json, p_csv, p_html]


def _table(headers: list[str], rows: list[list]) -> str:
    h = "".join(f"<th>{html.escape(str(x))}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table border='1' cellspacing='0' cellpadding='3'><tr>{h}</tr>{body}</table>"


def html_report(session: WindSession) -> str:  # noqa: C901
    cfg, ps, plan, cats = session.cfg, session.pressures, session.plan, session.cats
    sec: list[str] = []
    sec.append("<h1>air-apparent wind load report</h1>")
    sec.append(f"<p>Code edition: <b>{html.escape(cfg.code_edition)}</b>. Scope: horizontal MWFRS only "
               "(no roof uplift, no C&amp;C design). <b>Provisional: not independently code-validated; "
               "W_Ecc and combinations are not yet engineering-reviewed.</b></p>")
    sec.append(f"<h2>Input provenance</h2><p>YAML: {html.escape(cfg.source_path or '(in memory)')} "
               f"(effective-config hash {session.config_hash})</p>")
    sec.append(f"<pre>{html.escape(effective_config_yaml(cfg))}</pre>")
    sec.append("<h2>Pressure branches</h2>" + _table(
        ["direction", "branch"], [[d, b] for d, b in cfg.loading.wall_pressure_branch_by_direction.items()]))
    sec.append("<p>Branch labels: Ext. Only = external; Max = external + qh|GCpi|; Min = external - qh|GCpi|. "
               "'Min' is a branch label, not the code minimum wind load.</p>")
    sec.append("<h2>Calculation results</h2>" + _table(
        ["id", "description", "value", "units", "reference", "status", "signed GCpi"],
        [[r.id, r.description, f"{r.value:.6g}", r.units, r.reference, r.status,
          r.inputs.get("GCpi_signed", "")] for r in ps.results.values()]))
    sec.append("<h2>Minimum-load checks</h2>" + _table(
        ["id", "value", "limit", "passes", "status"],
        [[c.id, f"{c.value:.3f} psf", c.inputs["limit_psf"], c.inputs["passes"], c.status]
         for c in ps.checks]))
    counts: dict[str, int] = {}
    for o in cats.objects.values():
        counts[o.category] = counts.get(o.category, 0) + 1
    sec.append("<h2>Categorization</h2>" + _table(["category", "objects"], sorted(counts.items())))
    sec.append("<h2>Group / assignment table</h2>" + _table(
        ["group", "category", "band", "dir", "role", "result", "value", "pattern", "members", "sign"],
        [list(r.values()) for r in group_table(session)]))
    ecc = [a for a in plan.assignments if a.kind == "joint_moment"]
    sec.append("<h2>Eccentric torsion derivation (provisional)</h2>" + _table(
        ["pattern", "joint", "moment kip-ft", "note"], [[a.pattern, a.object_ref, f"{a.value:.4g}", a.note]
                                                        for a in ecc]))
    sec.append("<h2>Combinations (provisional)</h2>" + _table(
        ["name", "kind", "terms"], [[c.name, c.kind, "; ".join(f"{f:g}*{n}" for n, f in c.terms)]
                                    for c in plan.combinations]))
    sec.append("<h2>Diagnostics and unresolved items</h2>" + _table(
        ["level", "code", "message"], [[d.level, d.code, d.message] for d in plan.diagnostics]))
    if session.verification:
        sec.append("<h2>ETABS read-back verification</h2>" + _table(
            ["check", "expected", "actual", "ok"],
            [[v.check, v.expected, v.actual, v.ok] for v in session.verification]))
    sec.append("<h2>Verification status</h2><ul><li>Workbook agreement: reproduced by tests/test_pressures.py"
               "</li><li>Independent engineering checks: pending</li><li>Live ETABS verification: "
               "not performed unless a live adapter was used (see docs/etabs_setup.md)</li></ul>")
    return "<html><head><meta charset='utf-8'><title>Wind report</title></head><body>" + "".join(sec) + \
        "</body></html>"
