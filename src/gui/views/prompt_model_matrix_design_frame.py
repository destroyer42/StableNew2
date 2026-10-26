"""Prompt x Model Matrix authoring: the Prompt Slot candidate editor with the matrix's own bounds and shared-settings notice."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.gui.views.prompt_slot_design_frame import PromptSlotDesignFrame
from src.learning.prompt_model_matrix import (
    MAX_CELLS,
    MAX_MODELS,
    MAX_PROMPTS,
    MIN_MODELS,
    MIN_PROMPTS,
    SETTINGS_NOTICE,
    check_bounds,
)
from src.learning.prompt_slot_experiment import PromptSlotDesign, validate_design


class PromptModelMatrixDesignFrame(PromptSlotDesignFrame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        template: Callable[[], str],
        changed: Callable[[], None],
        visible: Callable[[], bool],
        models: Callable[[], int],
    ) -> None:
        self._models = models
        super().__init__(parent, template=template, changed=changed, visible=visible)
        self.configure(text="Prompt candidates for one named slot (rows) x models (columns)")
        ttk.Label(self, text=SETTINGS_NOTICE, wraplength=340, justify="left").grid(
            row=10, column=0, sticky="ew", pady=(4, 0)
        )
        self._render()

    def _selected_models(self) -> int:
        try:
            return int(self._models())
        except (TypeError, ValueError, tk.TclError):
            return 0

    def _render(self) -> None:
        super()._render()
        prompts, models = len(self._candidates), self._selected_models()
        self.count_var.set(
            f"{prompts} prompts x {models} models = {prompts * models} cells. Choose {MIN_PROMPTS}-{MAX_PROMPTS} "
            f"prompts and {MIN_MODELS}-{MAX_MODELS} models, 1-3 images per cell; at most {MAX_CELLS} cells and 36 images."
        )

    def validation_error(self, images: int, models: int | None = None) -> str:
        spec = self.spec()
        count = self._selected_models() if models is None else models
        try:
            check_bounds(len(spec["candidates"]), count, images)
            validate_design(
                PromptSlotDesign(
                    spec["template"],
                    spec["slot"],
                    tuple(spec["candidates"]),
                    spec["fixed_slots"],
                    images,
                )
            )
        except ValueError as exc:
            return str(exc)
        return ""
