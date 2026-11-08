"""Compatibility probe dialog (MEC-901): choose 2–4 lineage recipes, a prompt and an image budget, then queue.

The dialog only collects the operator's design; the catalog window prepares, confirms and admits it through
``QualificationBatchService`` (canonical Learning → JobService path). Nothing generates without the explicit
confirmation the window shows.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from src.learning.compatibility_probe import (
    DEFAULT_IMAGES_PER_RECIPE,
    DEFAULT_NEGATIVE,
    DEFAULT_PROMPT,
    MAX_IMAGES_PER_RECIPE,
    MAX_RECIPES,
    MIN_RECIPES,
    ProbeDesign,
    ProbeRecipe,
)


def recipe_line(recipe: ProbeRecipe) -> str:
    s = recipe.settings
    return (
        f"{s['width']}×{s['height']}, {s['sampler_name']} / {s['scheduler']}, "
        f"{s['steps']} steps, CFG {float(s['cfg_scale']):g}"
    )


class CompatibilityProbeDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        model: str,
        sha256: str,
        family: str,
        recipes: Sequence[ProbeRecipe],
        preselected: Sequence[str],
        unavailable: Sequence[str],
        notes: Sequence[str],
        on_queue: Callable[[CompatibilityProbeDialog], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Compatibility Probe — {model}")
        self.geometry("880x720")
        self.model, self.sha256, self.family = model, sha256, family
        self.recipes = {recipe.key: recipe for recipe in recipes}
        self._stale = False
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=(
                f"{model}\nSHA-256 {sha256[:16]}…   Family StableNew sees: {family}\n\n"
                "Renders one prompt with the same seeds under each recipe you tick. Compare the images to see "
                "whether this checkpoint runs here and which lineage's settings suit it (SD 1.5, SDXL, Turbo, "
                "Flux…). Exploratory: nothing is classified or published; you decide that after reviewing."
            ),
            wraplength=840,
            justify="left",
        ).pack(anchor="w")
        box = ttk.LabelFrame(frame, text=f"Recipes (choose {MIN_RECIPES}–{MAX_RECIPES})", padding=6)
        box.pack(fill="x", pady=6)
        self.selected: dict[str, tk.BooleanVar] = {}
        for recipe in recipes:
            var = tk.BooleanVar(value=recipe.key in preselected)
            var.trace_add("write", lambda *_: self._update_total())
            self.selected[recipe.key] = var
            row = ttk.Frame(box)
            row.pack(fill="x", anchor="w")
            ttk.Checkbutton(row, text=recipe.label, variable=var).pack(side="left")
            ttk.Label(row, text="   " + recipe_line(recipe), foreground="#555").pack(side="left")
            ttk.Label(
                box,
                text="      " + recipe.note + f" Source: {recipe.source}",
                wraplength=820,
                foreground="#777",
            ).pack(anchor="w")
        for problem in unavailable:
            ttk.Label(box, text="Not offered: " + problem, foreground="#a33", wraplength=820).pack(
                anchor="w"
            )
        form = ttk.Frame(frame)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Prompt").grid(row=0, column=0, sticky="w")
        self.prompt = tk.StringVar(value=DEFAULT_PROMPT)
        ttk.Entry(form, textvariable=self.prompt).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(form, text="Negative").grid(row=1, column=0, sticky="w")
        self.negative = tk.StringVar(value=DEFAULT_NEGATIVE)
        ttk.Entry(form, textvariable=self.negative).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Label(form, text="Images per recipe").grid(row=2, column=0, sticky="w")
        self.images = tk.IntVar(value=DEFAULT_IMAGES_PER_RECIPE)
        ttk.Spinbox(
            form,
            from_=1,
            to=MAX_IMAGES_PER_RECIPE,
            textvariable=self.images,
            width=4,
            command=self._update_total,
        ).grid(row=2, column=1, sticky="w", padx=4)
        self.total = tk.StringVar()
        ttk.Label(frame, textvariable=self.total).pack(anchor="w", pady=(6, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=6)
        self.queue_button = ttk.Button(buttons, text="Queue Probe…", command=lambda: on_queue(self))
        self.queue_button.pack(side="left")
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        self.status = tk.StringVar(value="Nothing is generated until you confirm.")
        ttk.Label(frame, textvariable=self.status, wraplength=840).pack(anchor="w")
        self.text = ScrolledText(frame, height=8, wrap="word", state="disabled")
        self.text.pack(fill="both", expand=True)
        if notes:
            self.show("\n".join(notes))
        self._update_total()

    def chosen(self) -> list[ProbeRecipe]:
        return [self.recipes[key] for key, var in self.selected.items() if var.get()]

    def _images(self) -> int:
        try:
            return int(self.images.get())
        except (tk.TclError, ValueError):
            return 0

    def _update_total(self) -> None:
        count, images = len(self.chosen()), self._images()
        self.total.set(f"{count} recipes × {images} images = {count * images} images")

    def design(self) -> ProbeDesign:
        """The operator's design, validated; raises ValueError with a message for the status line."""
        design = ProbeDesign(
            model=self.model,
            sha256=self.sha256,
            family=self.family,
            recipes=tuple(self.chosen()),
            prompt=self.prompt.get().strip(),
            negative=self.negative.get().strip(),
            images_per_recipe=self._images(),
        )
        design.validate()
        return design

    def mark_stale(self, reason: str) -> None:
        self._stale = True
        self.queue_button.configure(state="disabled")
        self.status.set(reason)

    def show(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.configure(state="disabled")
