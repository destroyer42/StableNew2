"""Owns the one Align Motion session, workspace window and status row of the Video Workflow tab (PR-VID-MOTION-420).

The tab supplies a ``read_inputs`` callable (Tk reads happen there, on the UI thread) and a visibility gate; this
host builds the session's ports from the Video Workflow controller, keeps a single non-modal workspace window and
hands the tab the one thing it needs at submission time: ``submission_fields``.  It imports no job, queue or
runtime code and never edits the form: only an explicit Apply and Prepare in the workspace change what the form
submits, and a stale, failed or running alignment submits a blocker instead of a silent fallback.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any

from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.view_contracts.video_motion_alignment_contract import (
    STATUS_NOT_APPLIED,
    AlignInputs,
    AlignPorts,
    MotionAlignmentSession,
)
from src.gui.views.motion_alignment_dialog import MotionAlignmentDialog
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry
from src.video.motion_alignment import AlignmentIntent


class AlignmentHost:
    def __init__(
        self,
        owner: tk.Misc,
        *,
        controller: Callable[[], Any],
        read_inputs: Callable[[], AlignInputs],
        media_allowed: Callable[[], bool],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._owner = owner
        self._controller = controller
        self._read_inputs = read_inputs
        self._dialog: MotionAlignmentDialog | None = None
        self._closed = False
        dispatcher = tk_dispatcher_for(owner)
        runner = BackgroundWorkRunner(
            spawn=lambda name, target: get_thread_registry().spawn(
                target=target,
                name=name,
                daemon=False,
                purpose="Align driving motion without blocking Tk",
            ),
            dispatch=lambda fn: dispatcher.invoke(lambda: None if self._closed else fn()),
        )
        self.session = MotionAlignmentSession(
            ports=self.ports(media_allowed), runner=runner, on_change=on_change
        )

    def ports(self, media_allowed: Callable[[], bool]) -> AlignPorts:
        def ctl() -> Any:
            controller = self._controller()
            if controller is None:
                raise RuntimeError("The Video Workflow controller is not available.")
            return controller

        def observations(asset_id: str) -> Any:
            controller = self._controller()
            if controller is None:
                return None  # annotations are optional context; no controller simply means none
            return controller.motion_asset_observations(asset_id)

        def load(
            form: Mapping[str, Any],
            request: Mapping[str, Any],
            indices: Any,
            cancel: threading.Event,
        ) -> Any:
            return ctl().load_alignment_frames(form, request, indices, cancel)

        def render(loaded: Any, intent: AlignmentIntent) -> Any:
            return ctl().render_alignment_frames(loaded, intent)

        def prepare(
            form: Mapping[str, Any], request: Mapping[str, Any], cancel: threading.Event
        ) -> Any:
            return ctl().prepare_aligned_motion_source(form, request, cancel)

        return AlignPorts(
            load=load,
            render=render,
            prepare=prepare,
            driver_observations=observations,
            media_allowed=media_allowed,
        )

    # ------------------------------------------------------------------ the tab's view of it

    def refresh(self) -> None:
        """Adopt the form as it is now (call after any change to the source, clip, window or workflow)."""

        if not self._closed:
            self.session.refresh(self._read_inputs())

    def submission_fields(self) -> dict[str, Any]:
        return self.session.submission_fields()

    def discard(self) -> None:
        self.session.discard()

    def open(self) -> None:
        self.refresh()
        dialog = self._dialog
        try:
            if dialog is None or not dialog.winfo_exists():
                dialog = MotionAlignmentDialog(
                    self._owner, session=self.session, on_close=self._forget
                )
                self._dialog = dialog
            else:
                dialog.lift()
                self.session.open_workspace()
        except tk.TclError:
            self._dialog = None

    def _forget(self) -> None:
        self._dialog = None

    @property
    def dialog(self) -> MotionAlignmentDialog | None:
        return self._dialog

    def close(self) -> None:
        self._closed = True
        dialog = self._dialog
        if dialog is not None:
            try:
                dialog.destroy()
            except tk.TclError:
                pass
        self.session.close()


class AlignmentRow(ttk.Frame):
    """One line under the driving-motion form: the alignment's status and the two actions."""

    def __init__(self, master: tk.Misc, *, host: AlignmentHost) -> None:
        super().__init__(master, style="Panel.TFrame")
        self._host = host
        self.columnconfigure(1, weight=1)
        self.status_var = tk.StringVar(self)
        self.button = ttk.Button(self, text="Align Motion...", command=host.open)
        self.button.grid(row=0, column=0, sticky="w")
        self.label = ttk.Label(
            self, textvariable=self.status_var, justify="left", style="Dark.TLabel"
        )
        self.label.grid(row=0, column=1, sticky="ew", padx=8)
        bind_wraplength(self.label)
        self.discard_button = ttk.Button(self, text="Discard alignment", command=host.discard)
        self.discard_button.grid(row=0, column=2, sticky="e")
        self._unsubscribe = host.session.subscribe(self.render)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.render()

    def refresh(self) -> None:
        self._host.refresh()
        self.render()

    def render(self) -> None:
        try:
            view = self._host.session.view()
            if not view.available and not view.unavailable_reason:
                self.grid_remove()  # the selected workflow takes no driving video: nothing to align
                return
            self.grid()
            self.status_var.set(f"Alignment: {view.status_label}. {view.status_text}")
            self.button.configure(state="normal" if view.available else "disabled")
            self.discard_button.configure(state="normal" if view.can_discard else "disabled")
            if view.status == STATUS_NOT_APPLIED and not view.available:
                self.status_var.set(view.unavailable_reason)
        except tk.TclError:
            return

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._unsubscribe()


__all__ = ["AlignmentHost", "AlignmentRow"]
