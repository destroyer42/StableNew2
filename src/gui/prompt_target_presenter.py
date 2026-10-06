"""Tk application of a ``PromptTargetProjection`` to the Prompt tab (PR-IMG-130B).

Presentation only. It writes labels and enables/disables controls from the projection the pure analysis produced; it
never reads a file name, decides a capability, edits a prompt/embedding/LoRA/optimizer value, or touches PromptPack data.
Availability is a *view* of the stored state: disabling the Prompt Optimizer controls or the embedding "Add" buttons for a
model leaves every stored value as it is, so selecting another model restores the previous presentation exactly.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import HIGHLIGHT_WARNING, TEXT_MUTED
from src.prompting.prompt_compatibility import TARGET_UNVERIFIED, PromptTargetProjection, Severity

logger = logging.getLogger(__name__)

NO_TARGET_LABEL = "Prompt Target: no model selected"
_RANK = {Severity.ACTION_REQUIRED: 0, Severity.ADVISORY: 1, Severity.INFO: 2}


class PromptTargetPresenter:
    def __init__(
        self,
        *,
        banner_var: tk.StringVar,
        detail_var: tk.StringVar,
        detail_label: ttk.Label,
        negative_note_var: tk.StringVar,
        optimizer_note_var: tk.StringVar,
        optimizer_widgets: Callable[[], Sequence[Any]],
        embedding_picker: Callable[[], Any],
    ) -> None:
        self._banner_var = banner_var
        self._detail_var = detail_var
        self._detail_label = detail_label
        self._negative_note_var = negative_note_var
        self._optimizer_note_var = optimizer_note_var
        self._optimizer_widgets = optimizer_widgets
        self._embedding_picker = embedding_picker
        self.last: PromptTargetProjection | None = None

    def apply(self, projection: PromptTargetProjection | None) -> None:
        self.last = projection
        if projection is None:
            self._banner_var.set(NO_TARGET_LABEL)
            self._show_detail("", warn=False)
            self._negative_note_var.set("")
            self._optimizer_note_var.set("")
            self._set_optimizer_available(True)
            self._set_embedding_additions(True, "")
            return
        self._banner_var.set(projection.label)
        # The "unverified" guidance line already says it; every other finding is listed, most urgent first.
        ordered = sorted(projection.findings, key=lambda f: _RANK[f.severity])
        lines = list(projection.guidance) + [f.message for f in ordered if f.code != TARGET_UNVERIFIED]
        self._show_detail("\n".join(lines), warn=bool(projection.action_required))
        self._negative_note_var.set(projection.negative_note)
        self._optimizer_note_var.set(projection.optimizer_note)
        self._set_optimizer_available(projection.optimizer_available)
        self._set_embedding_additions(projection.embedding_additions_allowed, projection.embeddings_note)

    def _show_detail(self, text: str, *, warn: bool) -> None:
        self._detail_var.set(text)
        try:
            self._detail_label.configure(foreground=HIGHLIGHT_WARNING if warn else TEXT_MUTED)
        except Exception:
            logger.debug("Could not style the prompt target detail", exc_info=True)

    def _set_optimizer_available(self, available: bool) -> None:
        for widget in self._optimizer_widgets():
            try:
                widget.state(["!disabled"] if available else ["disabled"])
            except Exception:
                logger.debug("Could not set the optimizer control state", exc_info=True)

    def _set_embedding_additions(self, allowed: bool, note: str) -> None:
        picker = self._embedding_picker()
        setter = getattr(picker, "set_additions_allowed", None)
        if callable(setter):
            try:
                setter(allowed, note)
            except Exception:
                logger.debug("Could not update the embedding picker", exc_info=True)


__all__ = ["NO_TARGET_LABEL", "PromptTargetPresenter"]
