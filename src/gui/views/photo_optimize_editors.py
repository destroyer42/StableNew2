"""Scoped Photo Optimize editing and review widgets; no store writes or queue authority."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui.view_contracts.workspace_density_contract import wrap_width
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.photo_optimize.editing import PromptEdit, field_defaults, pipeline_mask


def review_dialog(parent, title: str, text: str, *, accept="Confirm") -> bool:
    """Scrollable, complete review. No truncation of selected asset or job details."""
    window = tk.Toplevel(parent)
    window.title(title)
    window.geometry("850x600")
    window.rowconfigure(0, weight=1)
    window.columnconfigure(0, weight=1)
    answer = [False]
    body = tk.Text(window, wrap="word")
    body.insert("1.0", text)
    body.configure(state="disabled")
    body.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(window, command=body.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    body.configure(yscrollcommand=scrollbar.set)
    actions = ttk.Frame(window)
    actions.grid(row=1, column=0, columnspan=2, sticky="ew")

    def confirm():
        answer[0] = True
        window.destroy()

    ttk.Button(actions, text=accept, command=confirm).pack(side="right")
    ttk.Button(actions, text="Cancel", command=window.destroy).pack(side="right")
    window.transient(parent.winfo_toplevel())
    window.grab_set()
    parent.wait_window(window)
    return answer[0]


class PhotoBatchEditor(ttk.Frame):
    def __init__(self, parent, *, review):
        super().__init__(parent)
        self.masks = {}
        self.values = {}
        self.mixed_labels = {}
        self.combos = {}
        self.summary = tk.StringVar(value="No photos selected")
        self.wrapped_labels = []
        summary_label = ttk.Label(self, textvariable=self.summary, wraplength=600)
        summary_label.grid(row=0, column=0, columnspan=3, sticky="ew")
        hint_label = ttk.Label(
            self,
            text="Checked = Apply; unchecked = Leave Unchanged. Editing here never autosaves.",
            wraplength=600,
        )
        hint_label.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.wrapped_labels.extend([summary_label, hint_label])
        self.columnconfigure(1, weight=1)
        for row, (key, default) in enumerate(field_defaults().items(), start=2):
            mask = self.masks[key] = tk.BooleanVar(value=False)
            value = self.values[key] = tk.StringVar(value=str(default))
            ttk.Checkbutton(self, text=key, variable=mask).grid(row=row, column=0, sticky="w")
            if isinstance(default, bool):
                options = ["True", "False"]
            elif key == "geometry_policy":
                options = ["auto", "custom"]
            else:
                options = []
            combo = self.combos[key] = ttk.Combobox(
                self, textvariable=value, values=options, width=24
            )
            combo.grid(row=row, column=1, sticky="ew")
            label = self.mixed_labels[key] = ttk.Label(self, text="")
            label.grid(row=row, column=2, sticky="w")
        row += 1
        self.prompt_modes = {}
        self.prompt_text = {}
        for key in ("prompt", "negative_prompt"):
            self.masks[key] = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                self, text=f"Saved {key} transformation", variable=self.masks[key]
            ).grid(row=row, column=0, sticky="w")
            self.prompt_modes[key] = tk.StringVar(value="append")
            ttk.Combobox(
                self,
                textvariable=self.prompt_modes[key],
                values=["append", "replace", "modify"],
                state="readonly",
            ).grid(row=row, column=1, sticky="ew")
            row += 1
            self.prompt_text[key] = tk.Text(self, height=3, width=24, wrap="word")
            self.prompt_text[key].grid(row=row, column=0, columnspan=3, sticky="ew")
            row += 1
        semantics_label = ttk.Label(
            self,
            text="Saved transformations use Review semantics. Empty text leaves prompts unchanged. "
            "Dimensions require Apply Custom + width + height for Auto photos.",
            wraplength=600,
        )
        semantics_label.grid(row=row, column=0, columnspan=3, sticky="ew")
        self.wrapped_labels.append(semantics_label)
        self.review_button = ttk.Button(self, text="Review selected-photo changes…", command=review)
        self.review_button.grid(row=row + 1, column=0, columnspan=3, sticky="ew")
        self.bind("<Configure>", self._fit_wraps, add="+")

    def _fit_wraps(self, _event=None):
        """Wrap the explanatory labels to the width this editor was given instead of a fixed 600 px."""
        width = wrap_width(self.winfo_width(), margin=16)
        for label in self.wrapped_labels:
            if int(label.cget("wraplength") or 0) != width:
                label.configure(wraplength=width)

    def project_selection(self, values, count):
        self.summary.set(
            f"Batch Edit: {count} selected photo(s). Active photo is independent of this set."
        )
        for key, variable in self.values.items():
            value = values.get(key)
            if value is None:
                continue
            self.mixed_labels[key].configure(text="Mixed" if value.mixed else "Same")
            if not self.masks[key].get():
                variable.set("" if value.mixed else str(value.value))

    def collect_mask(self):
        mask = {}
        for key, default in field_defaults().items():
            if not self.masks[key].get():
                continue
            raw = self.values[key].get()
            if isinstance(default, bool):
                if raw not in {"True", "False"}:
                    raise ValueError(f"Choose True or False for {key}")
                value = raw == "True"
            elif isinstance(default, int):
                value = int(raw)
            elif isinstance(default, float):
                value = float(raw)
            else:
                value = raw
            mask[key] = value
        for key in self.prompt_text:
            if self.masks[key].get():
                mask[key] = PromptEdit(
                    self.prompt_modes[key].get(), self.prompt_text[key].get("1.0", "end").strip()
                )
        return mask

    def resources(self, resources):
        for key, combo in self.combos.items():
            kind = (
                "schedulers"
                if key.endswith("scheduler")
                else "samplers"
                if key.endswith(("sampler", "sampler_name"))
                else "models"
                if key == "model"
                else "vaes"
                if key == "vae"
                else "adetailer_models"
                if key.endswith("adetailer_model")
                else "upscalers"
                if key.endswith("upscaler")
                else None
            )
            if kind:
                combo.configure(values=resources.get(kind, []))


def pipeline_copy_dialog(parent, snapshot, scope, on_review):
    window = tk.Toplevel(parent)
    window.title(f"Live Pipeline copy — {scope}")
    window.geometry("900x650")
    ttk.Label(
        window,
        text=f"Copy to {scope}. Choose field groups; then review every photo's before/after. "
        "Unselected groups, saved prompts, notes, tags and history remain unchanged.",
        wraplength=800,
    ).pack(fill="x")
    groups = {}
    selected_fields = {}
    candidates = pipeline_mask(
        snapshot, {"model", "vae", "stages", "img2img", "adetailer", "upscale", "geometry"}
    )
    choices = ttk.Frame(window)
    choices.pack(fill="x")

    def group_for(key):
        if key == "geometry_policy" or key in {"config.img2img.width", "config.img2img.height"}:
            return "geometry"
        if key.startswith("config."):
            return key.split(".")[1]
        return "stages" if key.startswith("stage.") else key

    def toggle(group):
        for key, variable in selected_fields.items():
            if group_for(key) == group:
                variable.set(groups[group].get())

    for name in ("model", "vae", "stages", "img2img", "adetailer", "upscale", "geometry"):
        groups[name] = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            choices,
            text=name + (" (explicit Custom override)" if name == "geometry" else ""),
            variable=groups[name],
            command=lambda name=name: toggle(name),
        ).pack(side="left")
    ttk.Label(
        window,
        text="Captured live Pipeline fields below. Groups select fields; uncheck any field to preserve it. "
        "Prompts and geometry are not implicit stage-copy fields.",
        wraplength=850,
    ).pack(fill="x")
    scroll = ScrollableFrame(window)
    scroll.pack(fill="both", expand=True)
    for row, (key, value) in enumerate(candidates.items()):
        selected_fields[key] = tk.BooleanVar(value=False)
        ttk.Checkbutton(scroll.inner, text=key, variable=selected_fields[key]).grid(
            row=row, column=0, sticky="w"
        )
        rendered = parent._visibility_resolver().redact_text(repr(value))
        ttk.Label(scroll.inner, text=rendered, wraplength=450).grid(row=row, column=1, sticky="w")

    def review():
        selected = {
            key: candidates[key] for key, variable in selected_fields.items() if variable.get()
        }
        if not selected:
            return
        window.destroy()
        on_review(selected)

    ttk.Button(window, text="Review copy…", command=review).pack(side="right")
    ttk.Button(window, text="Cancel", command=window.destroy).pack(side="right")
    window.transient(parent.winfo_toplevel())
    window.grab_set()
