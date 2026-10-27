"""Small Tkinter front end. It displays the YAML configuration; it never edits wind inputs."""

from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import asdict
from pathlib import Path

from .config import ConfigError, effective_config_yaml
from .reporting import export_all, group_table, pressure_output_results
from .workflow import WindSession

DEFAULT_YAML = Path(__file__).resolve().parents[2] / "templates" / "wind_inputs.yaml"
GROUP_COLUMNS = ("group", "category", "band", "direction", "role", "result_id", "value", "pattern",
                 "members", "sign")


class App:
    def __init__(self, root, default_yaml: str = str(DEFAULT_YAML)) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root = root
        root.title("air-apparent - ASCE 7-10 horizontal MWFRS wind loads for ETABS")
        self.s = WindSession()
        self.yaml_path = default_yaml
        self._yaml_digest = b""
        self.status = tk.StringVar(value="Load a YAML file to begin.")
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=6, pady=4)
        self.path_label = ttk.Label(bar, text="YAML: (none)")
        self.path_label.pack(side="left")
        ttk.Label(bar, text="Load scope:").pack(side="left", padx=(20, 4))
        self.scope = tk.StringVar(value="walls_parapets")
        scope_picker = ttk.Combobox(bar, textvariable=self.scope, state="readonly", width=18,
                                   values=("walls_parapets", "all"))
        scope_picker.pack(side="left")
        scope_picker.bind("<<ComboboxSelected>>", lambda _: self._run(self.change_scope))
        row = ttk.Frame(root)
        row.pack(fill="x", padx=6)
        self.pid = tk.StringVar()
        for text, cmd in (
            ("Load/Reload YAML...", self.load_yaml), ("Offline demo", self.demo),
            ("Connect ETABS", self.connect), ("Inspect", self.inspect), ("Calculate", self.calculate),
            ("Create/Update preview groups", self.groups), ("Select group in ETABS", self.select),
            ("Review & apply", self.apply), ("Export report", self.export),
        ):
            ttk.Button(row, text=text, command=lambda c=cmd: self._run(c)).pack(side="left", padx=2)
        ttk.Label(row, text="ETABS pid:").pack(side="left", padx=(8, 2))
        ttk.Entry(row, textvariable=self.pid, width=7).pack(side="left")
        nb = ttk.Notebook(root)
        self.nb = nb
        nb.pack(fill="both", expand=True, padx=6, pady=4)
        self.text = tk.Text(nb, wrap="none", height=24)
        nb.add(self.text, text="Config / Diagnostics")
        self.pressure_tab = ttk.Frame(nb)
        nb.add(self.pressure_tab, text="Pressure results")
        self.pressure_summary = tk.StringVar(value="Click Calculate to compute and display pressures.")
        ttk.Label(self.pressure_tab, textvariable=self.pressure_summary, wraplength=1200,
                  justify="left").pack(fill="x", padx=8, pady=6)
        pressure_list = ttk.Frame(self.pressure_tab)
        pressure_list.pack(fill="both", expand=True)
        pressure_cols = ("description", "value", "units", "reference")
        self.pressure_tree = ttk.Treeview(pressure_list, columns=pressure_cols, show="tree headings", height=14)
        self.pressure_tree.heading("#0", text="Result ID / component")
        self.pressure_tree.column("#0", width=240)
        for column, width in zip(pressure_cols, (370, 110, 70, 220), strict=True):
            self.pressure_tree.heading(column, text=column.replace("_", " "))
            self.pressure_tree.column(column, width=width, anchor="e" if column == "value" else "w")
        pressure_scroll = ttk.Scrollbar(pressure_list, orient="vertical", command=self.pressure_tree.yview)
        self.pressure_tree.configure(yscrollcommand=pressure_scroll.set)
        pressure_scroll.pack(side="right", fill="y")
        self.pressure_tree.pack(fill="both", expand=True)
        self.pressure_tree.bind("<<TreeviewSelect>>", lambda _: self._show_pressure_detail())
        ttk.Label(self.pressure_tab, text="Selected result: calculation inputs, equation and status").pack(
            anchor="w", padx=8, pady=(6, 0))
        self.pressure_detail = tk.Text(self.pressure_tab, height=10, wrap="word", state="disabled")
        self.pressure_detail.pack(fill="x", padx=8, pady=6)
        cols = ("group", "category", "band", "direction", "role", "result_id", "value", "pattern",
                "members", "sign")
        self.tree = ttk.Treeview(nb, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110)
        nb.add(self.tree, text="Preview groups / assignment table")
        detail = ttk.Frame(nb)
        nb.add(detail, text="Object classification / reasons")
        self.objects = ttk.Treeview(detail, columns=("object", "category", "loading", "reason"), show="headings")
        for column, width in (("object", 100), ("category", 180), ("loading", 140), ("reason", 750)):
            self.objects.heading(column, text=column)
            self.objects.column(column, width=width)
        scroll = ttk.Scrollbar(detail, orient="vertical", command=self.objects.yview)
        self.objects.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.objects.pack(fill="both", expand=True)
        ttk.Label(root, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")
        if default_yaml and Path(default_yaml).exists():
            self._run(lambda: self._load(default_yaml))

    # -------------------------------------------------------------- plumbing
    def _run(self, fn) -> None:
        try:
            self._refresh_if_yaml_changed()
            fn()
        except ConfigError as exc:
            self.tree.delete(*self.tree.get_children())
            self.s.preview_valid = False
            self.text.delete("1.0", "end")
            self.text.insert("end", "Configuration errors:\n" + "\n".join(exc.errors))
            self.status.set("Configuration invalid")
        except Exception as exc:  # surfaced to the engineer, never swallowed silently
            self.text.insert("end", "\n" + traceback.format_exc())
            self.status.set(f"Error: {exc}")

    def _refresh_if_yaml_changed(self) -> None:
        if not self.yaml_path or self.s.cfg is None:
            return
        path = Path(self.yaml_path)
        if not path.is_file():
            self.tree.delete(*self.tree.get_children())
            self.s.preview_valid = False
            raise ConfigError([f"Input YAML no longer exists: {path}"])
        if hashlib.sha256(path.read_bytes()).digest() != self._yaml_digest:
            self._load(self.yaml_path)
            self.status.set("YAML changed on disk: reloaded; previews and calculations invalidated")

    def _load(self, path: str) -> None:
        path = str(Path(path).resolve())
        self.s.load_config(path)
        self.scope.set(self.s.cfg.loading.scope)
        self.yaml_path = path
        self._yaml_digest = hashlib.sha256(Path(path).read_bytes()).digest()
        self.path_label.config(text=f"YAML: {path}")
        self.text.delete("1.0", "end")
        self.text.insert("end", effective_config_yaml(self.s.cfg))
        self.tree.delete(*self.tree.get_children())
        self.objects.delete(*self.objects.get_children())
        self._clear_pressure_results()
        self.status.set("YAML loaded; dependent results invalidated")

    def change_scope(self) -> None:
        self.s.set_loading_scope(self.scope.get())
        self.text.delete("1.0", "end")
        self.text.insert("end", effective_config_yaml(self.s.cfg))
        self.tree.delete(*self.tree.get_children())
        self.objects.delete(*self.objects.get_children())
        self._clear_pressure_results()
        self.status.set(f"Load scope: {self.scope.get()}; calculate and recreate preview groups before applying")

    # -------------------------------------------------------------- actions
    def load_yaml(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml *.yml")])
        if path:
            self._load(path)

    def demo(self) -> None:
        self.s.use_offline_demo()
        self.tree.delete(*self.tree.get_children())
        self._clear_pressure_results()
        self.status.set("Offline demonstration model opened (synthetic geometry)")

    def connect(self) -> None:
        from .etabs import connect_live, list_instances
        pid = int(self.pid.get()) if self.pid.get().strip() else None
        ad = connect_live(pid)
        self.s.connect(ad)
        self.tree.delete(*self.tree.get_children())
        self._clear_pressure_results()
        i = ad.info()
        self.status.set(f"Connected: {i.path} pid={i.pid} version={i.version} units={i.units} "
                        f"locked={i.locked} ({len(list_instances())} instance(s) open)")

    def inspect(self) -> None:
        self.s.read_model()
        self.s.categorize()
        self.tree.delete(*self.tree.get_children())
        self._clear_pressure_results()
        self._show_classification()
        self.status.set(self._classification_status())

    def _classification_status(self) -> str:
        n = sum(bool(o.load_issue) for o in self.s.cats.objects.values())
        return f"Objects classified; {n} need load review. See Object classification / reasons"

    def _show_classification(self) -> None:
        cats = self.s.cats
        counts: dict[str, int] = {}
        for o in cats.objects.values():
            counts[o.category] = counts.get(o.category, 0) + 1
        self.text.delete("1.0", "end")
        self.text.insert("end", effective_config_yaml(self.s.cfg) + "\n--- categorization ---\n")
        self.text.insert("end", "\n".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        self.text.insert("end", f"\nenvelope: {cats.envelope}\nderived dims: {cats.derived_dims}\n")
        self.text.insert("end", f"Model stories (ft): {[(s.name, s.elevation_ft) for s in self.s.snapshot.stories]}\n")
        self.text.insert("end", "\n".join(
            f"[{d.level}] {d.code} {d.object_ref}: {d.message}" for d in cats.diagnostics))
        self.objects.delete(*self.objects.get_children())
        for o in sorted(cats.objects.values(), key=lambda o: (not bool(o.load_issue), o.ref)):
            loading = "Review required" if o.load_issue else "Excluded" if o.category == "excluded" else "Configured"
            self.objects.insert("", "end", values=(o.ref, o.category, loading, o.reason))

    def calculate(self) -> None:
        self.s.read_model() if self.s.snapshot is None else None
        self.s.calculate()
        self._show_pressure_results()
        self.nb.select(self.pressure_tab)
        self.s.build_plan()
        selected = set(self.tree.selection())
        self._show_classification()
        self.text.insert("end", "\n--- load plan diagnostics ---\n" + "\n".join(
            f"[{d.level}] {d.code} {d.object_ref}: {d.message}" for d in self.s.plan.diagnostics))
        self.tree.delete(*self.tree.get_children())
        for r in group_table(self.s):
            self.tree.insert("", "end", iid=r["group"], values=[r[c] for c in GROUP_COLUMNS])
        retained = selected.intersection(self.tree.get_children())
        if retained:
            self.tree.selection_set(sorted(retained))
        self.text.delete("1.0", "end")
        self.text.insert("end", effective_config_yaml(self.s.cfg) + "\n--- Calculation results ---\n")
        for r in self.s.pressures.results.values():
            self.text.insert("end", f"{r.id}: {r.value:.6g} {r.units}\n")
        self.text.insert("end", "\n--- Preview diagnostics ---\n")
        self.text.insert("end", f"Model envelope: {self.s.cats.envelope}\n")
        for d in self.s.plan.diagnostics:
            obj = f" ({d.object_ref})" if d.object_ref else ""
            self.text.insert("end", f"[{d.level}] {d.code}{obj}: {d.message}\n")
        self.status.set(f"Calculated: {len(self.s.pressures.results)} results, "
                        f"{len(self.s.plan.assignments)} assignments. {self._classification_status()}")

    def _clear_pressure_results(self) -> None:
        self.pressure_tree.delete(*self.pressure_tree.get_children())
        self.pressure_summary.set("Click Calculate to compute and display pressures.")
        self.pressure_detail.configure(state="normal")
        self.pressure_detail.delete("1.0", "end")
        self.pressure_detail.configure(state="disabled")

    def _show_pressure_results(self) -> None:
        self._clear_pressure_results()
        cfg, ps = self.s.cfg, self.s.pressures
        results = pressure_output_results(ps)
        self.pressure_summary.set(
            f"{len(results)} pressure outputs: walls (Max/Min), parapets and penthouses. Input: {self.yaml_path}. "
            f"V = {cfg.wind.basic_wind_speed_mph:g} mph; Exposure {cfg.wind.exposure_category}; "
            f"roof height = {cfg.wind.mean_roof_height_above_grade_ft:g} ft; "
            f"plan dimensions from {cfg.geometry.plan_dimensions_source}.\n"
            f"Positive = toward surface; negative = suction. Application scope: {cfg.loading.scope}. "
            "Expand a result to see component pressures; select a row for details. "
            "Calculation alone does not apply loads to ETABS.")
        for r in results:
            self.pressure_tree.insert("", "end", iid=r.id, text=r.id, values=(r.description, "", "psf", ""))
            for c in r.components:
                self.pressure_tree.insert(r.id, "end", iid=f"{r.id}|{c.id}", text=c.description,
                                          values=(c.description, f"{c.value:.6f}", c.units, c.reference))
        first = next((r.id for r in results if r.id.startswith("W_Wall_Story1_")), None)
        if first:
            self.pressure_tree.selection_set(first)
            self.pressure_tree.see(first)
            self._show_pressure_detail()

    def _show_pressure_detail(self) -> None:
        selection = self.pressure_tree.selection()
        if not selection or self.s.pressures is None:
            return
        selected = selection[0]
        if "|" not in selected:
            group = next(g for g in pressure_output_results(self.s.pressures) if g.id == selected)
            detail = f"{group.id}\n{group.description}\nWind direction: {group.direction}\n\n"
            detail += "\n".join(f"{r.description}: {r.value:.6f} {r.units}" for r in group.components)
            self.pressure_detail.configure(state="normal")
            self.pressure_detail.delete("1.0", "end")
            self.pressure_detail.insert("end", detail)
            self.pressure_detail.configure(state="disabled")
            return
        r = self.s.pressures.results[selected.split("|", 1)[1]]
        detail = f"{r.description}: {r.value:.6f} {r.units}\n"
        i = r.inputs
        if all(k in i for k in ("q_psf", "G", "Cp", "qi_psf", "GCpi_signed")):
            detail += (f"p = q × G × Cp − qi × GCpi\n"
                       f"  = {i['q_psf']:.6f} × {i['G']:g} × {i['Cp']:g} "
                       f"− {i['qi_psf']:.6f} × ({i['GCpi_signed']:g}) = {r.value:.6f} psf\n\n")
        detail += json.dumps(asdict(r), indent=2)
        self.pressure_detail.configure(state="normal")
        self.pressure_detail.delete("1.0", "end")
        self.pressure_detail.insert("end", detail)
        self.pressure_detail.configure(state="disabled")

    def groups(self) -> None:
        if self.s.plan is None:
            self.calculate()
        diags = self.s.create_preview_groups()
        message = "Preview groups created/updated (no loads applied). " + self._classification_status()
        self.status.set(message if not diags else "; ".join(d.message for d in diags))

    def select(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.status.set("Select a row in the group table first")
            return
        name = self.tree.set(sel[0], "group")
        self.s.select_group(str(name))
        self.status.set(f"Selected {name} in ETABS")

    def apply(self) -> None:
        from tkinter import messagebox
        if self.s.plan is None or not self.s.preview_valid:
            self.status.set("Create/update preview groups and review them in ETABS first")
            return
        errors = [d for d in self.s.plan.diagnostics if d.level == "error"]
        if errors:
            self._show_apply_errors("Load plan cannot be applied", errors)
            return
        n = len(self.s.plan.assignments)
        review = sum(bool(o.load_issue) for o in self.s.cats.objects.values())
        warnings = [d for d in self.s.plan.diagnostics if d.level == "warning"]
        summary = (f"Scope: {self.s.cfg.loading.scope}.\n"
                   f"{review} objects need load review and receive no automatic load.\n"
                   f"{len(warnings)} warnings are listed in Config / Diagnostics.\n\n")
        if not messagebox.askyesno("Apply load plan", summary + f"Apply {n} assignments, "
                                   f"{len(self.s.plan.patterns)} patterns, {len(self.s.plan.cases)} cases and "
                                   f"{len(self.s.plan.combinations)} combinations to the model?"):
            return
        res = self.s.apply()
        if not res.ok and "locked" in res.message and messagebox.askyesno(
                "Model locked", "Unlocking the model discards analysis results. Unlock and continue?"):
            res = self.s.apply(allow_unlock=True)
        self.text.insert("end", f"\n{res.message}\n{res.applied}\n")
        if res.diagnostics:
            self.text.insert("end", "\n".join(
                f"[{d.level}] {d.code} {d.object_ref}: {d.message}" for d in res.diagnostics) + "\n")
        if not res.ok and res.diagnostics:
            self._show_apply_errors(res.message, res.diagnostics)
        if res.ok:
            self.s.verify()
            self.text.insert("end", "\n".join(f"{'OK ' if v.ok else 'FAIL'} {v.check}: {v.expected} / "
                                              f"{v.actual}" for v in self.s.verification))
        self.status.set(res.message)

    def _show_apply_errors(self, message, diagnostics) -> None:
        from tkinter import messagebox

        details = "\n".join(f"{d.code}: {d.message}" for d in diagnostics)
        self.text.insert("end", f"\n--- apply blocked ---\n{message}\n{details}\n")
        self.nb.select(self.text)
        self.text.see("end")
        self.status.set(message)
        messagebox.showerror("Apply blocked", message + "\n\n" + "\n".join(details.splitlines()[:8])
                             + "\n\nFull details are in Config / Diagnostics.")

    def export(self) -> None:
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d and self.s.plan is not None:
            files = export_all(self.s, d)
            self.status.set("Exported: " + ", ".join(p.name for p in files))


def main() -> None:
    import argparse
    import tkinter as tk

    ap = argparse.ArgumentParser(description="air-apparent wind loads for ETABS")
    ap.add_argument("yaml", nargs="?", default=str(DEFAULT_YAML),
                    help="wind inputs YAML to load at startup (default: templates/wind_inputs.yaml)")
    args = ap.parse_args()
    root = tk.Tk()
    App(root, args.yaml)
    root.mainloop()


if __name__ == "__main__":
    main()
