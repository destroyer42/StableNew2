"""One image's existing overall/details rating controls in guided qualification review."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.media_inspector import MediaInspector
from src.learning.controlled_study_display import visibility_prompt
from src.learning.rating_schema import RatingCategory, get_active_categories


class RatingCard(ttk.LabelFrame):
    """One ordinary image rating, never a pair vote or an independent writer."""

    def __init__(self, parent: Any, window: Any, title: str) -> None:
        super().__init__(parent, text=title, padding=6)
        self.window, self.sample = window, None
        self.columnconfigure(0, weight=1)
        self.caption = tk.StringVar(self)
        ttk.Label(self, textvariable=self.caption, wraplength=400).pack(fill="x")
        self.media = MediaInspector(self, allow_original=False, fit_to_widget=True, height=300)
        self.media.pack(fill="both", expand=True)
        self.status = tk.StringVar(self)
        ttk.Label(self, textvariable=self.status, wraplength=400).pack(fill="x")
        self.rating = tk.IntVar(self, value=0)
        scores = ttk.Frame(self)
        scores.pack(fill="x", pady=5)
        ttk.Label(scores, text="Overall:").pack(side="left")
        for value in range(1, 6):
            ttk.Radiobutton(
                scores, text=str(value), value=value, variable=self.rating, command=self.stage
            ).pack(side="left", padx=4)
        details = DisclosureSection(self, title="Rating details", expanded=False)
        details.pack(fill="x")
        self.flags: dict[str, tk.BooleanVar] = {}
        self.subscores: dict[str, tk.IntVar] = {}
        for key in ("people", "animals", "landscape", "architecture", "close_up"):
            var = tk.BooleanVar(self, value=key == "people")
            self.flags[key] = var
            ttk.Checkbutton(
                details.body,
                text=key.replace("_", " "),
                variable=var,
                command=self._context_changed,
            ).pack(anchor="w")
        self.subscore_frame = ttk.Frame(details.body)
        self.subscore_frame.pack(fill="x")
        ttk.Label(details.body, text="Notes").pack(anchor="w")
        self.notes = tk.Text(details.body, height=3, width=30, wrap="word")
        self.notes.pack(fill="x")
        self.notes.bind("<FocusOut>", lambda _event: self.stage())
        ttk.Button(self, text="Discard Draft", command=self._discard).pack(anchor="w")

    def payload(self) -> dict[str, Any]:
        return {
            "overall_rating": self.rating.get(),
            "notes": self.notes.get("1.0", "end").strip(),
            "context_flags": {k: v.get() for k, v in self.flags.items()},
            "subscores": {k: v.get() for k, v in self.subscores.items() if v.get()},
        }

    def stage(self) -> None:
        if self.sample and self.window.session.live:
            self.window.session.stage(self.sample.image_ref, self.payload())
            self.status.set(self.window.session.payload(self.sample.image_ref)[1])

    def _discard(self) -> None:
        if self.sample and self.window.session.live:
            self.window.learning_controller.discard_review_draft(self.sample.image_ref)
            self.show(self.sample)

    def _context_changed(self) -> None:
        payload = self.payload()
        self._subscore_controls(payload)
        self.stage()

    def _subscore_controls(self, payload: dict[str, Any]) -> None:
        for child in self.subscore_frame.winfo_children():
            child.destroy()
        self.subscores = {}
        categories = {
            c.key: c for c in get_active_categories({k: v.get() for k, v in self.flags.items()})
        }
        for key in payload.get("subscores") or {}:
            categories.setdefault(key, RatingCategory(key, key.replace("_", " ").title()))
        for key, category in categories.items():
            row = ttk.Frame(self.subscore_frame)
            row.pack(fill="x")
            ttk.Label(row, text=category.label).pack(side="left")
            var = tk.IntVar(self, value=int((payload.get("subscores") or {}).get(key, 0)))
            self.subscores[key] = var
            for value in range(1, 6):
                ttk.Radiobutton(
                    row, text=str(value), value=value, variable=var, command=self.stage
                ).pack(side="left")

    def show(self, sample: Any) -> None:
        self.sample = sample
        if sample is None:
            self.caption.set("No matched candidate. Individual results remain reviewable.")
            self.media.clear()
            self.status.set("")
            return
        self.caption.set(
            f"{self.window.findings.setting}: {sample.value} · "
            + (
                f"observed seed {sample.seed}"
                if sample.seed is not None
                else "seed association unverified"
            )
        )
        self.media.set_image_reference(
            sample.image_ref,
            subject={
                "name": sample.image_ref,
                "prompt": visibility_prompt(self.window.session.experiment),
            },
        )
        payload, status = self.window.session.payload(sample.image_ref)
        self.rating.set(int(payload.get("overall_rating") or 0))
        for key, var in self.flags.items():
            var.set(
                bool((payload.get("context_flags") or {}).get(key, key == "people" and not payload))
            )
        self._subscore_controls(payload)
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", str(payload.get("notes") or ""))
        self.status.set(
            status
            + (" · Excluded: " + sample.reason if sample.reason else " · Execution evidence valid")
        )
