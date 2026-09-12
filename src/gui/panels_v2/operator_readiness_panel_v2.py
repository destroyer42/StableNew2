"""Compact operator readiness and first-run guidance surface."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.services.operator_readiness_service import (
    OperatorReadinessRecord,
    OperatorReadinessService,
    OperatorReadinessSnapshot,
    OperatorReadinessState,
    ProductSupportState,
)
from src.services.ui_state_store import UIStateStore, get_ui_state_store

OPERATOR_READINESS_STATE_KEY = "operator_readiness"
INTRO_DISMISSED_KEY = "intro_dismissed"


def format_product_support_label(display_name: str, state: ProductSupportState) -> str:
    """Keep supported tabs unchanged and visibly qualify non-MVP surfaces."""

    if state is ProductSupportState.SUPPORTED:
        return display_name
    if state is ProductSupportState.DEFERRED:
        return f"{display_name} - Deferred"
    return f"{display_name} - Adv"


def is_intro_dismissed(store: UIStateStore | None = None) -> bool:
    state = (store or get_ui_state_store()).load_state() or {}
    readiness_state = state.get(OPERATOR_READINESS_STATE_KEY, {})
    return bool(isinstance(readiness_state, dict) and readiness_state.get(INTRO_DISMISSED_KEY))


def persist_intro_dismissal(store: UIStateStore | None = None) -> bool:
    selected_store = store or get_ui_state_store()
    state = selected_store.load_state() or {}
    readiness_state = state.get(OPERATOR_READINESS_STATE_KEY)
    if not isinstance(readiness_state, dict):
        readiness_state = {}
    state[OPERATOR_READINESS_STATE_KEY] = {**readiness_state, INTRO_DISMISSED_KEY: True}
    return selected_store.save_state(state)


class OperatorReadinessPanelV2(ttk.Frame):
    """Render immutable readiness snapshots without owning runtime policy."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        service: OperatorReadinessService,
        source_image_path_provider: Callable[[], str | None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_open_diagnostics: Callable[[], None] | None = None,
        ui_state_store: UIStateStore | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, padding=10, **kwargs)
        self.service = service
        self._source_image_path_provider = source_image_path_provider
        self._on_close_callback = on_close
        self._on_open_diagnostics_callback = on_open_diagnostics
        self._ui_state_store = ui_state_store or get_ui_state_store()
        self.snapshot: OperatorReadinessSnapshot | None = None
        self.record_widgets: dict[str, dict[str, tk.Widget]] = {}
        self.support_labels: dict[str, ttk.Label] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Operator Readiness", font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.refresh_button = ttk.Button(header, text="Refresh", command=self.refresh)
        self.refresh_button.grid(row=0, column=1, padx=(6, 0))
        self.diagnostics_button = ttk.Button(
            header, text="Open Diagnostics", command=self._open_diagnostics
        )
        self.diagnostics_button.grid(row=0, column=2, padx=(6, 0))
        self.close_button = ttk.Button(header, text="Close", command=self._close)
        self.close_button.grid(row=0, column=3, padx=(6, 0))
        if on_open_diagnostics is None:
            self.diagnostics_button.state(["disabled"])

        self.intro_frame = ttk.LabelFrame(self, text="First-run guidance")
        self.intro_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.intro_frame.columnconfigure(0, weight=1)
        self.intro_text = ttk.Label(
            self.intro_frame,
            justify=tk.LEFT,
            anchor="w",
            wraplength=680,
            text=(
                "Supported path 1: Prompt/Pipeline → A1111 → Queue → exact image "
                "artifacts, history, and Replay.\n"
                "Supported path 2: Selected Image → SVD Img2Vid → native SVD XT → "
                "Queue → exact video artifacts, history, and Replay.\n\n"
                "PromptPacks are user data, not repository files. Queue Auto-run drains "
                "queued work; Send Job dispatches the top job manually. Native SVD does "
                "not use A1111 generation. Recommended Windows/~12GB SVD: XT, 14 frames, "
                "7 fps, 25 steps. 25-frame XT uses more memory. Match Source Aspect "
                "preserves composition near the accepted SVD pixel envelope."
            ),
        )
        self.intro_text.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        self.dismiss_intro_var = tk.BooleanVar(value=False)
        self.dismiss_intro = ttk.Checkbutton(
            self.intro_frame,
            text="Don't show automatically again",
            variable=self.dismiss_intro_var,
            command=self._dismiss_intro_if_selected,
        )
        self.dismiss_intro.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))

        self.intro_reopen_button = ttk.Button(
            self, text="Show first-run guidance", command=self._show_intro
        )
        self.intro_reopen_button.grid(row=2, column=0, sticky="w", pady=(0, 6))

        self.content = ttk.Frame(self)
        self.content.grid(row=3, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)

        self.journeys_frame = ttk.LabelFrame(self.content, text="Supported journeys")
        self.journeys_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.journeys_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.journeys_frame,
            text="A1111 Still Image\nNative SVD XT",
            justify=tk.LEFT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        self.records_frame = ttk.LabelFrame(self.content, text="Readiness")
        self.records_frame.grid(row=1, column=0, sticky="nsew")
        self.records_frame.columnconfigure(1, weight=1)
        self.records_frame.columnconfigure(2, weight=1)

        self.refresh()
        self._set_intro_visible(not is_intro_dismissed(self._ui_state_store))

    def refresh(self) -> OperatorReadinessSnapshot:
        """Collect and render a new read-only snapshot."""

        source_image_path = None
        if self._source_image_path_provider is not None:
            source_image_path = self._source_image_path_provider()
        self.snapshot = self.service.collect(source_image_path=source_image_path)
        self._render_snapshot(self.snapshot)
        return self.snapshot

    def _render_snapshot(self, snapshot: OperatorReadinessSnapshot) -> None:
        for child in self.records_frame.winfo_children():
            child.destroy()
        self.record_widgets.clear()
        self.support_labels.clear()

        support_by_id = {surface.id: surface for surface in snapshot.support_surfaces}
        row = 0
        surface_ids = (
            "prompt",
            "pipeline",
            "svd",
            "learning",
            "review",
            "photo_optimize",
            "movie_clips",
            "character_training",
            "video_workflow",
        )
        for surface_id in surface_ids:
            surface = support_by_id.get(surface_id)
            if surface is None:
                continue
            label = ttk.Label(
                self.records_frame,
                text=format_product_support_label(surface.display_name, surface.state),
                anchor="w",
            )
            label.grid(row=row, column=0, sticky="w", padx=8, pady=3)
            self.support_labels[surface_id] = label
            row += 1

        ttk.Separator(self.records_frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        row += 1
        for record in snapshot.records:
            self._render_record(row, record)
            row += 1

    def _render_record(self, row: int, record: OperatorReadinessRecord) -> None:
        badge = {
            OperatorReadinessState.READY: "[Ready]",
            OperatorReadinessState.ACTION_REQUIRED: "[Action required]",
            OperatorReadinessState.OPTIONAL: "[Optional]",
            OperatorReadinessState.UNKNOWN: "[Unknown]",
        }[record.state]
        badge_label = ttk.Label(self.records_frame, text=badge, anchor="w")
        name_label = ttk.Label(self.records_frame, text=record.display_name, anchor="w")
        detail_lines = [record.summary]
        if record.blocking_reasons:
            detail_lines.append("Blocking: " + "; ".join(record.blocking_reasons))
        if record.operator_actions:
            detail_lines.append("Next: " + "; ".join(record.operator_actions))
        detail_label = ttk.Label(
            self.records_frame,
            text="\n".join(detail_lines),
            justify=tk.LEFT,
            anchor="w",
            wraplength=560,
        )
        badge_label.grid(row=row, column=0, sticky="nw", padx=8, pady=3)
        name_label.grid(row=row, column=1, sticky="nw", padx=8, pady=3)
        detail_label.grid(row=row, column=2, sticky="ew", padx=8, pady=3)
        self.record_widgets[record.id] = {
            "badge": badge_label,
            "name": name_label,
            "detail": detail_label,
        }

    def _dismiss_intro_if_selected(self) -> None:
        if self.dismiss_intro_var.get():
            persist_intro_dismissal(self._ui_state_store)
            self._set_intro_visible(False)

    def _show_intro(self) -> None:
        self.dismiss_intro_var.set(False)
        self._set_intro_visible(True)

    def _set_intro_visible(self, visible: bool) -> None:
        if visible:
            self.intro_frame.grid()
            self.intro_reopen_button.grid_remove()
        else:
            self.intro_frame.grid_remove()
            self.intro_reopen_button.grid()

    def _open_diagnostics(self) -> None:
        if callable(self._on_open_diagnostics_callback):
            self._on_open_diagnostics_callback()

    def _close(self) -> None:
        if callable(self._on_close_callback):
            self._on_close_callback()
        else:
            self.winfo_toplevel().destroy()


__all__ = [
    "INTRO_DISMISSED_KEY",
    "OPERATOR_READINESS_STATE_KEY",
    "OperatorReadinessPanelV2",
    "format_product_support_label",
    "is_intro_dismissed",
    "persist_intro_dismissal",
]
