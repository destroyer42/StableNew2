"""Compact generation-profile selector for the Base Generation panel (PR-IMG-PROFILE-630).

One combobox ("Profile") and one status line are always visible; Restore, Save as Custom, Update Custom, Favorite and the
per-setting evidence sit behind a "Details" toggle. Every sentence comes from ``generation_profile_projection`` and every
action goes to the controller adapter, so this view holds no profile logic and no persistence. Selecting a profile or
pressing Restore changes the editable working settings only: nothing is queued, dispatched or rewritten.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import simpledialog, ttk
from typing import Any

from src.generation_profiles.contract import ProfileRef
from src.gui.theme_v2 import MUTED_LABEL_STYLE
from src.gui.tooltip import attach_tooltip
from src.gui_v2.generation_profile_projection import NO_MODEL_TEXT, StripView

logger = logging.getLogger(__name__)

STRIP_TIP = (
    "A profile is a set of recommended Base Generation values for this model, with its sources. Choosing one fills the "
    "editable settings; it never turns a stage on and never changes jobs already in the draft or queue."
)
_REFRESH_DELAY_MS = 120


def _default_name_prompt(parent: tk.Misc, suggestion: str) -> str | None:
    return simpledialog.askstring(
        "Save as Custom profile",
        "Name for this model's Custom profile:",
        initialvalue=suggestion,
        parent=parent,
    )


class GenerationProfileStrip(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        controller_getter: Callable[[], Any],
        name_prompt: Callable[[tk.Misc, str], str | None] = _default_name_prompt,
        wraplength: int = 420,
    ) -> None:
        super().__init__(parent)
        self._controller_getter = controller_getter
        self._name_prompt = name_prompt
        self._refs: tuple[ProfileRef | None, ...] = (None,)
        self._pending: str | None = None
        self._details_open = False
        self._suppress_select = False
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Profile").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 2))
        self.profile_var = tk.StringVar(value="")
        self.combo = ttk.Combobox(
            self, textvariable=self.profile_var, state="readonly", style="Dark.TCombobox"
        )
        self.combo.grid(row=0, column=1, sticky="ew", pady=(0, 2))
        self.combo.bind("<<ComboboxSelected>>", self._on_selected)
        self.details_button = ttk.Button(self, text="Details", width=8, command=self.toggle_details)
        self.details_button.grid(row=0, column=2, sticky="e", padx=(6, 0), pady=(0, 2))
        attach_tooltip(self.combo, STRIP_TIP)

        self.status_label = ttk.Label(
            self, text=NO_MODEL_TEXT, style=MUTED_LABEL_STYLE, justify="left", wraplength=wraplength
        )
        self.status_label.grid(row=1, column=0, columnspan=3, sticky="ew")

        self.detail_frame = ttk.Frame(self)
        self.detail_frame.columnconfigure(0, weight=1)
        buttons = ttk.Frame(self.detail_frame)
        buttons.grid(row=0, column=0, sticky="w", pady=(4, 2))
        self.restore_button = ttk.Button(
            buttons, text="Restore selected profile", command=self.restore
        )
        self.save_button = ttk.Button(buttons, text="Save as Custom", command=self.save_as_custom)
        self.update_button = ttk.Button(
            buttons, text="Update Custom", command=lambda: self.save_as_custom(update=True)
        )
        self.favorite_button = ttk.Button(
            buttons, text="Favorite for this model", command=self.toggle_favorite
        )
        for column, button in enumerate(
            (self.restore_button, self.save_button, self.update_button, self.favorite_button)
        ):
            button.grid(row=0, column=column, padx=(0, 4))
        self.evidence_label = ttk.Label(
            self.detail_frame,
            text="",
            style=MUTED_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.evidence_label.grid(row=1, column=0, sticky="ew")
        self.message_label = ttk.Label(
            self.detail_frame,
            text="",
            style=MUTED_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.message_label.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        self.bind("<Destroy>", self._on_destroy, add="+")

        controller = self._controller()
        if controller is not None:
            try:
                controller.add_listener(self.schedule_refresh)
            except Exception:  # noqa: BLE001 - without a listener the strip still refreshes on its own actions
                logger.debug("generation profile strip could not subscribe", exc_info=True)
        self.refresh()

    # ------------------------------------------------------------------ plumbing

    def _controller(self) -> Any:
        try:
            return self._controller_getter()
        except Exception:  # noqa: BLE001 - a missing controller leaves the strip inert, never broken
            return None

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self and self._pending is not None:
            try:
                self.after_cancel(self._pending)
            except Exception:  # noqa: BLE001
                logger.debug("generation profile refresh already cancelled", exc_info=True)
            self._pending = None

    def schedule_refresh(self) -> None:
        """Coalesce bursts of working-value edits into one redraw."""

        if self._pending is not None:
            return
        try:
            self._pending = self.after(_REFRESH_DELAY_MS, self._run_scheduled)
        except Exception:  # noqa: BLE001 - destroyed window
            self._pending = None

    def _run_scheduled(self) -> None:
        self._pending = None
        self.refresh()

    # ------------------------------------------------------------------ view

    def refresh(self) -> None:
        controller = self._controller()
        if controller is None:
            return
        try:
            view: StripView = controller.strip_view()
            self._render(view)
        except Exception:  # noqa: BLE001 - an unreadable profile state leaves the last good view in place
            logger.debug("generation profile strip could not refresh", exc_info=True)

    def _render(self, view: StripView) -> None:
        self._refs = view.refs
        self.combo.configure(values=view.labels)
        self._suppress_select = True
        try:
            self.profile_var.set(view.labels[view.selected_index] if view.labels else "")
        finally:
            self._suppress_select = False
        self.status_label.configure(text=view.status)
        self.evidence_label.configure(text=view.details)
        self.restore_button.state(["!disabled"] if view.can_restore else ["disabled"])
        self.save_button.state(["!disabled"] if view.can_save else ["disabled"])
        self.update_button.state(["!disabled"] if view.can_update_custom else ["disabled"])
        self.favorite_button.configure(
            text="Remove favorite" if view.favorite else "Favorite for this model"
        )
        self.favorite_button.state(["!disabled"] if view.can_favorite else ["disabled"])

    def toggle_details(self) -> None:
        self._details_open = not self._details_open
        if self._details_open:
            self.detail_frame.grid(row=2, column=0, columnspan=3, sticky="ew")
            self.details_button.configure(text="Hide")
        else:
            self.detail_frame.grid_remove()
            self.details_button.configure(text="Details")

    # ------------------------------------------------------------------ actions

    def _on_selected(self, _event: object = None) -> None:
        if self._suppress_select:
            return
        controller = self._controller()
        index = self.combo.current()
        if controller is None or not 0 <= index < len(self._refs):
            return
        controller.on_profile_selected(self._refs[index])
        self.refresh()

    def restore(self) -> None:
        controller = self._controller()
        if controller is not None:
            controller.on_restore_selected()
            self.refresh()

    def save_as_custom(self, update: bool = False) -> None:
        controller = self._controller()
        if controller is None:
            return
        name = ""
        if not update:
            suggestion = f"{controller.current_model() or 'Model'} custom"
            name = (self._name_prompt(self, suggestion) or "").strip()
            if not name:
                return
        ok, message = controller.on_save_custom(name, update=update)
        self.message_label.configure(text=message)
        if not self._details_open:
            self.status_label.configure(text=message)
        self.refresh()
        if not ok:
            logger.info("custom profile not saved: %s", message)

    def toggle_favorite(self) -> None:
        controller = self._controller()
        if controller is None:
            return
        _ok, message = controller.on_toggle_favorite()
        self.message_label.configure(text=message)
        self.refresh()


__all__ = ["GenerationProfileStrip", "STRIP_TIP"]
