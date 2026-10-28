"""Separate analysis-result review tab; pressure and classification views stay independent."""

from __future__ import annotations


class ShearTabMixin:
    def _build_shear_tab(self, notebook) -> None:
        tk, ttk = self.tk, self.ttk
        panel = ttk.Frame(notebook)
        notebook.add(panel, text="Shear / Eccentricity")
        ttk.Label(panel, text="After ETABS analysis: Extract -> Review -> Use -> Calculate -> "
                  "Preview groups -> Review & apply. Extraction reads results without changing loads.",
                  wraplength=1100).pack(anchor="w", padx=6, pady=6)
        controls = ttk.Frame(panel)
        controls.pack(fill="x", padx=6)
        self.shear_direction = tk.StringVar(value="+X")
        self.shear_cases = tk.StringVar()
        self.shear_scale = tk.StringVar(value="1.0")
        ttk.Label(controls, text="Direction").pack(side="left")
        ttk.Combobox(controls, textvariable=self.shear_direction, values=("+X", "-X", "+Y", "-Y"),
                     state="readonly", width=5).pack(side="left", padx=4)
        ttk.Label(controls, text="Source cases (comma-separated)").pack(side="left")
        ttk.Entry(controls, textvariable=self.shear_cases, width=60).pack(side="left", padx=4)
        ttk.Label(controls, text="Multiplier").pack(side="left")
        ttk.Entry(controls, textvariable=self.shear_scale, width=8).pack(side="left", padx=4)
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", padx=6, pady=6)
        for label, action in (("Fill current wind case names", self.fill_shear_cases),
                              ("Extract & review shears", self.extract_shears),
                              ("Use reviewed direction", self.use_reviewed_shears),
                              ("Return all directions to YAML", self.reset_shears)):
            ttk.Button(buttons, text=label, command=lambda fn=action: self._run(fn)).pack(side="left", padx=3)
        ttk.Label(panel, text="Select uneccentric directional static-linear wind cases, including all required "
                  "components. Multiplier defaults to 1; no automatic 4/3. W2/W4 factors remain separate. "
                  "Mz is a magnitude for +/-E branches. Adopting torsion requires load scope 'all'; "
                  "wall/parapet scope remains unchanged.", wraplength=1100).pack(anchor="w", padx=6)
        self.shear_summary = tk.StringVar(value="No extracted results. YAML shear inputs remain active.")
        ttk.Label(panel, textvariable=self.shear_summary, wraplength=1100).pack(anchor="w", padx=6, pady=6)
        columns = ("story", "raw_V_kip", "V_used_kip", "e_ft", "target_T_kip_ft", "floor_Mz_kip_ft")
        self.shear_tree = ttk.Treeview(panel, columns=columns, show="headings", height=10)
        for column in columns:
            self.shear_tree.heading(column, text=column)
            self.shear_tree.column(column, width=145, anchor="e")
        self.shear_tree.pack(fill="both", expand=True, padx=6)
        self.shear_references = tk.StringVar()
        ttk.Label(panel, text="Existing rigid-diaphragm reference joints (STORY=joint, STORY=joint). "
                  "One rigid diaphragm per story; equivalent floor Mz = differences of Bottom-cut eV targets.",
                  wraplength=1100).pack(anchor="w", padx=6, pady=(6, 0))
        ttk.Entry(panel, textvariable=self.shear_references).pack(fill="x", padx=6, pady=6)
        self._pending_shear = None
        self._shear_view_revision = self.s.input_revision

    def _refresh_shear_state(self) -> None:
        if hasattr(self, "shear_tree") and self._shear_view_revision != self.s.input_revision:
            self._clear_shear_view()

    def _clear_shear_view(self) -> None:
        self._pending_shear = None
        self._shear_view_revision = self.s.input_revision
        self.shear_tree.delete(*self.shear_tree.get_children())
        self.shear_summary.set("No extracted results. YAML shear inputs remain active.")
        self.shear_references.set("")

    def fill_shear_cases(self) -> None:
        if self.s.plan is None:
            raise ValueError("Calculate first to identify the current component case names")
        self.shear_cases.set(", ".join(c.name for c in self.s.plan.cases
            if c.name.endswith(self.shear_direction.get()) and "ecc" not in c.name.lower()))

    def _shear_request(self):
        return (tuple(c.strip() for c in self.shear_cases.get().split(",") if c.strip()),
                self.shear_direction.get(), float(self.shear_scale.get()))

    def extract_shears(self) -> None:
        self._refresh_shear_state()
        self._pending_shear = None
        self.shear_tree.delete(*self.shear_tree.get_children())
        self.shear_summary.set("Extraction not completed. The current plan is unchanged.")
        request = self._shear_request()
        review = self.s.extract_shear_review(*request)
        self._pending_shear = (request, review)
        values = {r.story: r.vx_kip if review.direction[1] == "X" else r.vy_kip for r in review.source.stories}
        for r in review.rows:
            self.shear_tree.insert("", "end", iid=r.story, values=(r.story, f"{values[r.story]:.6g}",
                f"{r.cumulative_shear_kip:.6g}", f"{r.eccentricity_ft:.6g}",
                f"{r.target_torsion_kip_ft:.6g}", f"{r.applied_moment_kip_ft:.6g}"))
        self.shear_summary.set(
            f"REVIEW ONLY {review.direction}; model: {review.source.model_path}; "
            f"cases: {', '.join(review.source.cases)}; Bottom cuts; multiplier={review.scale:g}. "
            f"Raw base Fx={review.source.base_fx_kip:g}, Fy={review.source.base_fy_kip:g} kip. "
            f"Scaled |base shear|={review.base_shear_kip:g} kip; base eV={review.base_target_kip_ft:g} kip-ft; "
            f"sum floor Mz={sum(r.applied_moment_kip_ft for r in review.rows):g} kip-ft. "
            "Base/story agreement passed (0.1% or 0.01 kip).")
        if not self.shear_references.get().strip():
            self.shear_references.set(", ".join(f"{s.name}={s.reference_joint or ''}"
                for s in sorted(self.s.snapshot.stories, key=lambda s: s.elevation_ft, reverse=True)
                if s.name in values))
        self.status.set("Shears extracted for review; current plan and YAML unchanged")

    def use_reviewed_shears(self) -> None:
        if self._pending_shear is None or self._pending_shear[0] != self._shear_request():
            raise ValueError("extract and review the current direction, source cases and multiplier first")
        references = {}
        for item in self.shear_references.get().split(","):
            story, sep, joint = item.strip().partition("=")
            if not sep or not story or not joint.strip() or story in references:
                raise ValueError("reference mapping must be unique STORY=joint entries for every reviewed story")
            references[story] = joint.strip()
        self.s.use_shear_review(self._pending_shear[1], references)
        self.tree.delete(*self.tree.get_children())
        self.shear_summary.set(self.shear_summary.get() + " Adopted; rebuild preview before apply.")
        self.status.set("Reviewed shear adopted in session; Calculate and recreate preview groups before apply")

    def reset_shears(self) -> None:
        self.s.use_yaml_shears()
        self._clear_shear_view()
        self.tree.delete(*self.tree.get_children())
        self.status.set("Original YAML shear inputs restored; Calculate and review preview again")
