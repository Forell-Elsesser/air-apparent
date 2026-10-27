"""Small Tkinter front end. It displays the YAML configuration; it never edits wind inputs."""

from __future__ import annotations

import os
import traceback
from pathlib import Path

from .config import ConfigError, effective_config_yaml
from .reporting import export_all, group_table
from .workflow import WindSession


class App:
    def __init__(self, root, default_yaml: str = "") -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root = root
        root.title("air-apparent - ASCE 7-10 horizontal MWFRS wind loads for ETABS")
        self.s = WindSession()
        self.yaml_path = default_yaml
        self._mtime = 0.0
        self.status = tk.StringVar(value="Load a YAML file to begin.")
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=6, pady=4)
        self.path_label = ttk.Label(bar, text="YAML: (none)")
        self.path_label.pack(side="left")
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
        nb.pack(fill="both", expand=True, padx=6, pady=4)
        self.text = tk.Text(nb, wrap="none", height=24)
        nb.add(self.text, text="Config / Diagnostics")
        cols = ("group", "category", "band", "direction", "role", "result_id", "value", "pattern",
                "members", "sign")
        self.tree = ttk.Treeview(nb, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110)
        nb.add(self.tree, text="Preview groups / assignment table")
        ttk.Label(root, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")
        if default_yaml and Path(default_yaml).exists():
            self._run(lambda: self._load(default_yaml))

    # -------------------------------------------------------------- plumbing
    def _run(self, fn) -> None:
        try:
            self._refresh_if_yaml_changed()
            fn()
        except ConfigError as exc:
            self.text.delete("1.0", "end")
            self.text.insert("end", "Configuration errors:\n" + "\n".join(exc.errors))
            self.status.set("Configuration invalid")
        except Exception as exc:  # surfaced to the engineer, never swallowed silently
            self.text.insert("end", "\n" + traceback.format_exc())
            self.status.set(f"Error: {exc}")

    def _refresh_if_yaml_changed(self) -> None:
        if self.yaml_path and os.path.exists(self.yaml_path) and \
                os.path.getmtime(self.yaml_path) != self._mtime and self.s.cfg is not None:
            self._load(self.yaml_path)
            self.status.set("YAML changed on disk: reloaded; previews and calculations invalidated")

    def _load(self, path: str) -> None:
        self.s.load_config(path)
        self.yaml_path, self._mtime = path, os.path.getmtime(path)
        self.path_label.config(text=f"YAML: {path}")
        self.text.delete("1.0", "end")
        self.text.insert("end", effective_config_yaml(self.s.cfg))
        self.tree.delete(*self.tree.get_children())
        self.status.set("YAML loaded; dependent results invalidated")

    # -------------------------------------------------------------- actions
    def load_yaml(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml *.yml")])
        if path:
            self._load(path)

    def demo(self) -> None:
        self.s.use_offline_demo()
        self.status.set("Offline demonstration model opened (synthetic geometry)")

    def connect(self) -> None:
        from .etabs import connect_live, list_instances
        pid = int(self.pid.get()) if self.pid.get().strip() else None
        ad = connect_live(pid)
        self.s.connect(ad)
        i = ad.info()
        self.status.set(f"Connected: {i.path} pid={i.pid} version={i.version} units={i.units} "
                        f"locked={i.locked} ({len(list_instances())} instance(s) open)")

    def inspect(self) -> None:
        self.s.read_model()
        cats = self.s.categorize()
        counts: dict[str, int] = {}
        for o in cats.objects.values():
            counts[o.category] = counts.get(o.category, 0) + 1
        self.text.delete("1.0", "end")
        self.text.insert("end", effective_config_yaml(self.s.cfg) + "\n--- categorization ---\n")
        self.text.insert("end", "\n".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        self.text.insert("end", f"\nenvelope: {cats.envelope}\nderived dims: {cats.derived_dims}\n")
        self.text.insert("end", "\n".join(f"[{d.level}] {d.code}: {d.message}" for d in cats.diagnostics))
        self.status.set("Model read and categorized")

    def calculate(self) -> None:
        self.s.read_model() if self.s.snapshot is None else None
        self.s.calculate()
        self.s.build_plan()
        self.tree.delete(*self.tree.get_children())
        for r in group_table(self.s):
            self.tree.insert("", "end", values=list(r.values()))
        self.status.set(f"Calculated: {len(self.s.pressures.results)} results, "
                        f"{len(self.s.plan.assignments)} assignments (review before applying)")

    def groups(self) -> None:
        if self.s.plan is None:
            self.calculate()
        diags = self.s.create_preview_groups()
        self.status.set("Preview groups created/updated (no loads applied)" if not diags
                        else "; ".join(d.message for d in diags))

    def select(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.status.set("Select a row in the group table first")
            return
        name = self.tree.item(sel[0])["values"][0]
        self.s.select_group(str(name))
        self.status.set(f"Selected {name} in ETABS")

    def apply(self) -> None:
        from tkinter import messagebox
        if self.s.plan is None or not self.s.preview_valid:
            self.status.set("Create/update preview groups and review them in ETABS first")
            return
        n = len(self.s.plan.assignments)
        if not messagebox.askyesno("Apply load plan", f"Apply {n} assignments, "
                                   f"{len(self.s.plan.patterns)} patterns, {len(self.s.plan.cases)} cases and "
                                   f"{len(self.s.plan.combinations)} combinations to the model?"):
            return
        res = self.s.apply()
        if not res.ok and "locked" in res.message and messagebox.askyesno(
                "Model locked", "Unlocking the model discards analysis results. Unlock and continue?"):
            res = self.s.apply(allow_unlock=True)
        self.text.insert("end", f"\n{res.message}\n{res.applied}\n")
        if res.ok:
            self.s.verify()
            self.text.insert("end", "\n".join(f"{'OK ' if v.ok else 'FAIL'} {v.check}: {v.expected} / "
                                              f"{v.actual}" for v in self.s.verification))
        self.status.set(res.message)

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
    ap.add_argument("yaml", nargs="?", default="", help="wind inputs YAML to load at startup")
    args = ap.parse_args()
    root = tk.Tk()
    App(root, args.yaml)
    root.mainloop()


if __name__ == "__main__":
    main()
