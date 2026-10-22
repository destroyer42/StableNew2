# Subsystem: Learning
# Role: Axis designer for the Two-Axis Grid study type (expresses choices; planning lives in src/learning).

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.ui_tokens import TOKENS
from src.learning.two_axis_grid import (
    LORA,
    MAX_AXIS_VALUES,
    MAX_CELLS,
    MAX_IMAGES_PER_CELL,
    MAX_TOTAL_IMAGES,
    MIN_AXIS_VALUES,
    SUPPORTED_VARIABLES,
    plan_summary,
)

_DEFAULTS = {
    "CFG Scale": ("5, 7, 9", "5", "9", "2"),
    "Steps": ("20, 30, 40", "20", "40", "10"),
    "LoRA Strength": ("0.4, 0.8, 1.2", "0.4", "1.2", "0.4"),
}


class _AxisRow:
    def __init__(
        self, parent: tk.Misc, row: int, title: str, variable: str, on_change: Callable[[], None]
    ) -> None:
        self.variable_var = tk.StringVar(value=variable)
        self.mode_var = tk.StringVar(value="Values")
        defaults = _DEFAULTS[variable]
        self.values_var = tk.StringVar(value=defaults[0])
        self.start_var = tk.StringVar(value=defaults[1])
        self.end_var = tk.StringVar(value=defaults[2])
        self.step_var = tk.StringVar(value=defaults[3])
        self._on_change = on_change
        ttk.Label(parent, text=title).grid(row=row, column=0, sticky="w", pady=2)
        self.variable_combo = ttk.Combobox(
            parent,
            textvariable=self.variable_var,
            values=SUPPORTED_VARIABLES,
            state="readonly",
            width=14,
        )
        self.variable_combo.grid(row=row, column=1, sticky="ew", padx=2)
        self.mode_combo = ttk.Combobox(
            parent,
            textvariable=self.mode_var,
            values=("Values", "Range"),
            state="readonly",
            width=7,
        )
        self.mode_combo.grid(row=row, column=2, padx=2)
        self.values_entry = ttk.Entry(parent, textvariable=self.values_var, width=18)
        self.values_entry.grid(row=row, column=3, sticky="ew", padx=2)
        self.range_frame = ttk.Frame(parent)
        for position, (label, var) in enumerate(
            (("from", self.start_var), ("to", self.end_var), ("step", self.step_var))
        ):
            ttk.Label(self.range_frame, text=label).grid(row=0, column=position * 2)
            ttk.Entry(self.range_frame, textvariable=var, width=6).grid(
                row=0, column=position * 2 + 1, padx=(1, 4)
            )
        self.range_frame.grid(row=row, column=3, sticky="ew", padx=2)
        self.variable_combo.bind("<<ComboboxSelected>>", self._on_variable)
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync())
        for var in (self.values_var, self.start_var, self.end_var, self.step_var):
            var.trace_add("write", lambda *_: self._on_change())
        self._sync(notify=False)

    def _sync(self, notify: bool = True) -> None:
        if self.mode_var.get() == "Range":
            self.values_entry.grid_remove()
            self.range_frame.grid()
        else:
            self.range_frame.grid_remove()
            self.values_entry.grid()
        if notify:
            self._on_change()

    def _on_variable(self, _event: Any = None) -> None:
        values, start, end, step = _DEFAULTS[self.variable_var.get()]
        self.values_var.set(values)
        self.start_var.set(start)
        self.end_var.set(end)
        self.step_var.set(step)
        self._on_change()

    def spec(self) -> dict[str, Any]:
        variable = self.variable_var.get()
        if self.mode_var.get() == "Range":
            return {
                "variable": variable,
                "start": self.start_var.get(),
                "end": self.end_var.get(),
                "step": self.step_var.get(),
            }
        return {
            "variable": variable,
            "values": [item.strip() for item in self.values_var.get().split(",") if item.strip()],
        }

    def load(self, spec: dict[str, Any]) -> None:
        self.variable_var.set(str(spec.get("variable") or self.variable_var.get()))
        if spec.get("values") is None and "start" in spec:
            self.mode_var.set("Range")
            self.start_var.set(str(spec.get("start", "")))
            self.end_var.set(str(spec.get("end", "")))
            self.step_var.set(str(spec.get("step", "")))
        else:
            self.mode_var.set("Values")
            self.values_var.set(", ".join(str(item) for item in spec.get("values") or ()))
        self._sync(notify=False)


class TwoAxisDesignFrame(ttk.LabelFrame):
    """Two axes, the one fixed LoRA when needed, and a live cell/image total."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_change: Callable[[], None] | None = None,
        lora_provider: Callable[[], list[str]] | None = None,
        images_provider: Callable[[], int] | None = None,
    ) -> None:
        super().__init__(master, text="Two-Axis Grid", padding=5)
        self._on_change_callback = on_change
        self._lora_provider = lora_provider
        self._images_provider = images_provider or (lambda: 1)
        self.columnconfigure(3, weight=1)
        ttk.Label(self, text="Axis").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Variable").grid(row=0, column=1, sticky="w")
        ttk.Label(self, text="Mode").grid(row=0, column=2, sticky="w")
        ttk.Label(self, text="Values (comma separated) / range").grid(row=0, column=3, sticky="w")
        self.x_axis = _AxisRow(self, 1, "X (columns)", "CFG Scale", self._changed)
        self.y_axis = _AxisRow(self, 2, "Y (rows)", "Steps", self._changed)
        self.lora_var = tk.StringVar(value="")
        self.lora_label = ttk.Label(self, text="Fixed LoRA:")
        self.lora_combo = ttk.Combobox(self, textvariable=self.lora_var, state="normal", values=())
        self.lora_label.grid(row=3, column=0, sticky="w", pady=2)
        self.lora_combo.grid(row=3, column=1, columnspan=3, sticky="ew", padx=2)
        self.lora_var.trace_add("write", lambda *_: self._changed())
        self.summary_var = tk.StringVar(value="")
        ttk.Label(
            self,
            textvariable=self.summary_var,
            wraplength=360,
            justify="left",
            foreground=TOKENS.colors.text_muted,
        ).grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(
            self,
            text=(
                f"{MIN_AXIS_VALUES}-{MAX_AXIS_VALUES} values per axis, at most {MAX_CELLS} cells, "
                f"1-{MAX_IMAGES_PER_CELL} images per cell, at most {MAX_TOTAL_IMAGES} images. "
                "The same seeds are used in every cell."
            ),
            wraplength=360,
            foreground=TOKENS.colors.text_muted,
        ).grid(row=5, column=0, columnspan=4, sticky="ew")
        self._changed()

    def _uses_lora(self) -> bool:
        return LORA in (self.x_axis.variable_var.get(), self.y_axis.variable_var.get())

    def _changed(self) -> None:
        uses_lora = self._uses_lora()
        for widget in (self.lora_label, self.lora_combo):
            if uses_lora:
                widget.grid()
            else:
                widget.grid_remove()
        if uses_lora and self._lora_provider is not None:
            try:
                self.lora_combo.configure(values=list(self._lora_provider()))
            except Exception:
                self.lora_combo.configure(values=())
        self.refresh_summary()
        if self._on_change_callback is not None:
            self._on_change_callback()

    def spec(self) -> dict[str, Any]:
        return {
            "x": self.x_axis.spec(),
            "y": self.y_axis.spec(),
            "lora_name": self.lora_var.get().strip() if self._uses_lora() else "",
        }

    def load(self, spec: dict[str, Any] | None) -> None:
        if not isinstance(spec, dict):
            return
        self.x_axis.load(dict(spec.get("x") or {}))
        self.y_axis.load(dict(spec.get("y") or {}))
        self.lora_var.set(str(spec.get("lora_name") or ""))
        self._changed()

    def signature(self) -> str:
        import json

        return json.dumps(self.spec(), sort_keys=True)

    def validation_error(self) -> str | None:
        try:
            plan_summary({"grid": self.spec()}, int(self._images_provider()))
        except (ValueError, TypeError, tk.TclError) as exc:
            return str(exc)
        return None

    def refresh_summary(self) -> None:
        try:
            images = int(self._images_provider())
            cells, total = plan_summary({"grid": self.spec()}, images)
            self.summary_var.set(
                f"{cells} cells x {images} image(s) = {total} images will be queued once, after Preview."
            )
        except (ValueError, TypeError, tk.TclError) as exc:
            self.summary_var.set(str(exc))
