"""Review Probe Result dialog (MEC-902): record an advisory verdict, then optionally classify explicitly."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from src.learning.probe_verdict import LINEAGES, RUNS_LABELS, RUNS_YES, ProbeVerdict

_NO_RECIPE = "(none stood out)"


class ProbeVerdictDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        model: str,
        sha256: str,
        summary: str,
        recipes: Sequence[str],
        probe_ids: Sequence[str],
        existing: ProbeVerdict | None,
        on_save: Callable[[ProbeVerdictDialog], object],
        on_classify: Callable[[ProbeVerdictDialog], None],
        on_library: Callable[[], object],
    ) -> None:
        super().__init__(parent)
        self.title(f"Review Probe Result — {model}")
        self.geometry("820x640")
        self.model, self.sha256, self.probe_ids = model, sha256, tuple(probe_ids)
        self._stale = False
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=(
                "Compare the probe images in Experiment Library first. Then record what you saw. The verdict "
                "is advisory: it is shown in the catalog and changes nothing else. Classifying is a separate "
                "step you choose below."
            ),
            wraplength=780,
            justify="left",
        ).pack(anchor="w")
        text = ScrolledText(frame, height=8, wrap="word")
        text.insert("1.0", summary)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, pady=4)
        form = ttk.Frame(frame)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Does it work here?").grid(row=0, column=0, sticky="w")
        self.runs = tk.StringVar(value=existing.runs if existing else RUNS_YES)
        radios = ttk.Frame(form)
        radios.grid(row=0, column=1, sticky="w")
        for key, label in RUNS_LABELS.items():
            ttk.Radiobutton(radios, text=label, value=key, variable=self.runs).pack(
                side="left", padx=4
            )
        ttk.Label(form, text="Looks like").grid(row=1, column=0, sticky="w")
        self._lineage_keys = {label: key for key, (label, _base) in LINEAGES.items()}
        self.lineage = tk.StringVar(
            value=LINEAGES[existing.lineage][0] if existing else LINEAGES["unknown"][0]
        )
        ttk.Combobox(
            form, textvariable=self.lineage, values=list(self._lineage_keys), state="readonly"
        ).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(form, text="Best recipe").grid(row=2, column=0, sticky="w")
        self.best = tk.StringVar(value=(existing.best_recipe if existing else "") or _NO_RECIPE)
        ttk.Combobox(
            form, textvariable=self.best, values=[_NO_RECIPE, *recipes], state="readonly", width=80
        ).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Label(form, text="Notes").grid(row=3, column=0, sticky="nw")
        self.notes = tk.Text(form, height=4, wrap="word")
        self.notes.grid(row=3, column=1, sticky="ew", padx=4)
        if existing and existing.notes:
            self.notes.insert("1.0", existing.notes)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="Save Verdict", command=lambda: on_save(self)).pack(side="left")
        self.classify_button = ttk.Button(
            buttons, text="Apply Classification…", command=lambda: on_classify(self)
        )
        self.classify_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="Experiment Library", command=on_library).pack(side="left", padx=4)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        self.status = tk.StringVar(
            value="Apply Classification writes a small sidecar next to the checkpoint so StableNew knows its "
            "family. It asks first and never overwrites an existing file."
        )
        ttk.Label(frame, textvariable=self.status, wraplength=780).pack(anchor="w")

    def verdict(self) -> ProbeVerdict:
        best = self.best.get()
        verdict = ProbeVerdict(
            sha256=self.sha256,
            model=self.model,
            runs=self.runs.get(),
            lineage=self._lineage_keys.get(self.lineage.get(), "unknown"),
            best_recipe="" if best == _NO_RECIPE else best,
            notes=self.notes.get("1.0", "end").strip(),
            probe_ids=self.probe_ids,
        )
        verdict.validate()
        return verdict

    def mark_stale(self, reason: str) -> None:
        self._stale = True
        self.classify_button.configure(state="disabled")
        self.status.set(reason)
