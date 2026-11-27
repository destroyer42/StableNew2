"""N6 Generate workspace: the Packs x Models batch builder, the Queue and Recent outputs on one page.

The Simple workspace opens here. The builder is the N5 ``BatchBuilderPanel`` embedded (Plan and Queue run on the N5
service's background tasks); it reads packs, models and stage toggles from the Pipeline tab's PromptPack card each
time the tab is shown, when WebUI resources change while it is shown, and on Refresh lists. The Queue and Recent outputs are the shared ``QueuePanelV2`` and
``JobHistoryPanelV2`` views over ``AppStateV2``: this tab owns their hot-surface refresh, like the Pipeline shell
(GUI ownership map rules 8 and 9), and refreshes a surface only while it is on screen. It adds no queue, history or
submission authority.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.batch_builder_dialog import BatchBuilderPanel, batch_callbacks, batch_sources
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.theme_v2 import CARD_FRAME_STYLE, SURFACE_FRAME_STYLE

logger = logging.getLogger(__name__)

#: AppStateV2 keys that change what the Queue or Recent outputs show.
_SURFACE_KEYS: dict[str, tuple[str, ...]] = {
    "queue_jobs": ("queue",),
    "running_job": ("queue",),
    "queue_status": ("queue",),
    "is_queue_paused": ("queue",),
    "auto_run_queue": ("queue",),
    "history_items": ("history",),
}

INTRO_TEXT = (
    "Pick PromptPacks and models, Plan to see the exact totals, then Queue the batch. A model with a saved "
    "recipe uses it; other models use the Pipeline tab's settings (turn on Advanced to change them)."
)


class GenerateTabFrameV2(ttk.Frame):
    """Batch builder on the left; Queue and Recent outputs on the right."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        app_state: Any = None,
        app_controller: Any = None,
        sidebar_provider: Callable[[], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, **kwargs)
        self.app_state = app_state
        self.app_controller = app_controller
        self._sidebar_provider = sidebar_provider or (lambda: None)
        self._dirty: set[str] = set()
        self._flush_scheduled = False
        self._subscriptions: list[tuple[str, Callable[[], None]]] = []

        self.columnconfigure(0, weight=3, minsize=480)
        self.columnconfigure(1, weight=2, minsize=360)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text=INTRO_TEXT, wraplength=1100, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 4)
        )

        left = ttk.Frame(self, padding=8, style=CARD_FRAME_STYLE)
        left.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        header = ttk.Frame(left, style=CARD_FRAME_STYLE)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Packs × Models batch", font=("TkDefaultFont", 11, "bold")).pack(
            side="left"
        )
        self.refresh_button = ttk.Button(header, text="Refresh lists", command=self.refresh_sources)
        self.refresh_button.pack(side="right")
        plan_batch, queue_batch = batch_callbacks(self._controller)
        self.batch_panel = BatchBuilderPanel(
            left,
            packs=(),
            models=(),
            plan_batch=plan_batch,
            queue_batch=queue_batch,
            summary_height=10,
            wraplength=640,
        )
        self.batch_panel.grid(row=1, column=0, sticky="nsew")

        right = ttk.Frame(self, padding=8, style=CARD_FRAME_STYLE)
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.queue_panel = QueuePanelV2(
            right,
            controller=app_controller,
            app_state=app_state,
            manage_app_state_subscriptions=False,
        )
        self.queue_panel.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        recent = ttk.Frame(right, style=CARD_FRAME_STYLE)
        recent.grid(row=1, column=0, sticky="nsew")
        recent.columnconfigure(0, weight=1)
        recent.rowconfigure(1, weight=1)
        ttk.Label(recent, text="Recent outputs", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.recent_outputs_panel = JobHistoryPanelV2(
            recent,
            controller=app_controller,
            app_state=app_state,
            manage_app_state_subscriptions=False,
        )
        self.recent_outputs_panel.grid(row=1, column=0, sticky="nsew")

        self._subscribe()
        self._mark_dirty("queue", "history")
        for surface in (self.queue_panel, self.recent_outputs_panel):
            surface.bind("<Map>", lambda _event: self._schedule_flush(), add="+")
        self.bind("<Map>", self._on_map, add="+")

    # -- builder sources -------------------------------------------------------------------------------------------

    def _controller(self) -> Any:
        sidebar = self._sidebar_provider()
        return getattr(sidebar, "controller", None) or self.app_controller

    def refresh_sources(self) -> bool:
        """Re-read packs, models and stage toggles from the Pipeline tab's PromptPack card (cheap, in memory)."""

        sources = batch_sources(self._sidebar_provider())
        if sources is None:
            self.batch_panel.status_label.configure(
                text="The Pipeline tab's PromptPack list is not ready yet. Try Refresh lists in a moment."
            )
            return False
        self.batch_panel.set_sources(sources)
        return True

    def _on_map(self, event: tk.Event) -> None:
        if event.widget is self:
            self.refresh_sources()  # in memory; an unchanged list keeps the current plan
        self._schedule_flush()

    def _on_resources_changed(self, _resources: Any = None) -> None:
        """New models from the WebUI reach the builder while it is on screen (otherwise on the next show)."""

        try:
            if self.winfo_exists() and self.winfo_ismapped():
                self.after_idle(self.refresh_sources)
        except tk.TclError:
            return

    # -- hot surfaces (owned here; panels never subscribe themselves) -----------------------------------------------

    def _subscribe(self) -> None:
        add_resource_listener = getattr(self.app_state, "add_resource_listener", None)
        if callable(add_resource_listener):
            add_resource_listener(self._on_resources_changed)
        subscribe = getattr(self.app_state, "subscribe", None)
        if not callable(subscribe):
            return
        for key, surfaces in _SURFACE_KEYS.items():

            def callback(_surfaces: tuple[str, ...] = surfaces) -> None:
                self._mark_dirty(*_surfaces)

            try:
                subscribe(key, callback)
            except (AttributeError, TypeError, ValueError):
                logger.debug("Generate tab could not subscribe to %s", key, exc_info=True)
                continue
            self._subscriptions.append((key, callback))

    def _mark_dirty(self, *surfaces: str) -> None:
        self._dirty.update(surfaces)
        self._schedule_flush()

    def _schedule_flush(self, delay_ms: int = 1) -> None:
        if self._flush_scheduled or not self._dirty:
            return
        self._flush_scheduled = True
        try:
            self.after(delay_ms, self._flush)
        except tk.TclError:
            self._flush_scheduled = False

    @staticmethod
    def _visible(widget: tk.Misc) -> bool:
        try:
            return bool(widget.winfo_ismapped())
        except tk.TclError:
            return False

    def _flush(self) -> None:
        """Refresh dirty surfaces that are on screen; hidden ones stay dirty until they map."""

        self._flush_scheduled = False
        if self.app_state is None:
            self._dirty.clear()
            return
        for name, panel in (("queue", self.queue_panel), ("history", self.recent_outputs_panel)):
            if name not in self._dirty or not self._visible(panel):
                continue
            self._dirty.discard(name)
            try:
                panel.update_from_app_state(self.app_state)
            except (AttributeError, KeyError, TypeError, ValueError, tk.TclError):
                logger.warning("Generate tab %s refresh failed", name, exc_info=True)

    def on_content_visibility_mode_changed(self, mode: str) -> None:
        for panel in (self.queue_panel, self.recent_outputs_panel):
            callback = getattr(panel, "on_content_visibility_mode_changed", None)
            if callable(callback):
                callback(mode)

    def destroy(self) -> None:
        unsubscribe = getattr(self.app_state, "unsubscribe", None)
        if callable(unsubscribe):
            for key, callback in self._subscriptions:
                try:
                    unsubscribe(key, callback)
                except (AttributeError, KeyError, TypeError, ValueError):
                    continue
        self._subscriptions.clear()
        super().destroy()


__all__ = ["GenerateTabFrameV2", "INTRO_TEXT"]
