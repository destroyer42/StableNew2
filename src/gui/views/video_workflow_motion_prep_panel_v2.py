"""Tk rendering of the Video Workflow "Prepare Motion Source" panel (PR-VID-MOTION-210).

Presentation only: every rule (what a result means, what the form carries, staleness, blocking)
lives in ``MotionPreparationSession``.  Preparing decodes video with FFmpeg, so it runs on a worker
owned by the existing ``ThreadRegistry``; every widget is read before the worker starts and every
update is marshalled back to the Tk thread through ``TkUiDispatcher``.  Closing the panel cancels a
running preparation.  The panel is optional by design: with nothing prepared the driving video is
used exactly as it always was.
"""

from __future__ import annotations

import base64
import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any

from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.view_contracts.video_motion_prep_contract import (
    MotionPreparationSession,
    MotionPrepView,
    PreparationWork,
    PrepInputs,
)
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry

# What reading the tab's form can raise (a destroyed widget, a malformed snapshot).
_FORM_READ_ERRORS = (tk.TclError, AttributeError, KeyError, TypeError, ValueError)
_THUMB_CELL_WIDTH = 176  # a 160 px preview plus its gutter
_INTRO = (
    "Optional. Cut the driving video to exactly the frames this workflow will use: choose where the "
    "window starts, and whether to convert the clip to the workflow's frame rate. The result is a "
    "lossless copy that is frozen into the job; the original is never changed."
)


class WorkflowMotionPreparationPanel(ttk.LabelFrame):
    """Prepare / preview / use a driving-video window; hidden when the workflow takes no clip."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        session: MotionPreparationSession,
        read_form: Callable[[], Mapping[str, Any]],
        on_change: Callable[[], None] | None = None,
        runner: BackgroundWorkRunner | None = None,
    ) -> None:
        super().__init__(master, text="Prepare Motion Source (optional)", padding=8)
        self._session = session
        self._read_form = read_form
        self._on_change = on_change
        self._runner = runner
        self._closed = False
        self._photos: list[tk.PhotoImage] = []
        self._thumb_labels: list[ttk.Label] = []
        self._last_view: MotionPrepView | None = None
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.columnconfigure(0, weight=1)

        self.intro_label = ttk.Label(
            self, text=_INTRO, style="Muted.TLabel", justify="left", wraplength=640
        )
        self.intro_label.grid(row=0, column=0, sticky="ew")
        bind_wraplength(self.intro_label)

        options = ttk.Frame(self, style="Panel.TFrame")
        options.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.start_var = tk.StringVar(value="0")
        self.end_var = tk.StringVar(value="")
        self.convert_var = tk.BooleanVar(value=False)
        ttk.Label(options, text="Start (s)", style="Dark.TLabel").pack(side="left", padx=(0, 4))
        self.start_entry = ttk.Entry(
            options, textvariable=self.start_var, style="Dark.TEntry", width=8
        )
        self.start_entry.pack(side="left", padx=(0, 12))
        ttk.Label(options, text="End (s, optional)", style="Dark.TLabel").pack(
            side="left", padx=(0, 4)
        )
        self.end_entry = ttk.Entry(options, textvariable=self.end_var, style="Dark.TEntry", width=8)
        self.end_entry.pack(side="left", padx=(0, 12))
        self.convert_check = ttk.Checkbutton(
            options,
            text="Convert to the workflow's frame rate",
            variable=self.convert_var,
            style="Dark.TCheckbutton",
        )
        self.convert_check.pack(side="left")
        for variable in (self.start_var, self.end_var, self.convert_var):
            variable.trace_add("write", lambda *_args: self._on_edit())

        buttons = ttk.Frame(self, style="Panel.TFrame")
        buttons.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.prepare_button = ttk.Button(
            buttons, text="Prepare Motion Source", style="Dark.TButton", command=self._on_prepare
        )
        self.prepare_button.pack(side="left")
        self.cancel_button = ttk.Button(
            buttons, text="Cancel", style="Dark.TButton", command=self._on_cancel
        )
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.clear_button = ttk.Button(
            buttons, text="Use original video", style="Dark.TButton", command=self._on_clear
        )
        self.clear_button.pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="")
        self.using_var = tk.StringVar(value="")
        self.detail_var = tk.StringVar(value="")
        for row, variable, style in (
            (3, self.status_var, "Dark.TLabel"),
            (4, self.using_var, "Muted.TLabel"),
            (5, self.detail_var, "Dark.TLabel"),
        ):
            label = ttk.Label(self, textvariable=variable, style=style, justify="left")
            label.grid(row=row, column=0, sticky="ew", pady=(6, 0))
            bind_wraplength(label)
        self.frames_frame = ttk.Frame(self, style="Panel.TFrame")
        self.frames_frame.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.frames_frame.bind("<Configure>", lambda _e: self._layout_frames(), add="+")
        self.refresh()

    # ------------------------------------------------------------------ requests (Tk thread)

    def _inputs(self) -> PrepInputs:
        form = dict(self._read_form())
        return PrepInputs(
            available=bool(form.get("available")),
            unavailable_reason=str(form.get("unavailable_reason") or ""),
            workflow_id=str(form.get("workflow_id") or ""),
            workflow_version=str(form.get("workflow_version") or ""),
            frame_count=form.get("frame_count"),
            output_fps=form.get("output_fps"),
            clip_path=str(form.get("clip_path") or ""),
            start_text=self.start_var.get(),
            end_text=self.end_var.get(),
            convert=bool(self.convert_var.get()),
        )

    def _adopt_form(self) -> bool:
        """Hand the session the current form; False when it could not be read."""

        try:
            self._session.refresh(self._inputs())
        except _FORM_READ_ERRORS:
            return False
        return True

    def refresh(self) -> None:
        """Adopt the current form (cheap: no file is read) and redraw."""

        if self._closed or not self._adopt_form():
            return  # an unreadable form leaves what is displayed as it is
        self.render()

    def _on_edit(self) -> None:
        """An option changed here: what the form carries may have changed (a result may be stale)."""

        self.refresh()
        if self._on_change is not None and not self._closed:
            self._on_change()

    def submission_fields(self) -> dict[str, Any]:
        """The extra form keys a submission must carry (the record, a blocker, or nothing)."""

        self._adopt_form()
        return self._session.submission_fields()

    def _on_prepare(self) -> None:
        if self._closed:
            return
        work = self._session.begin(self._inputs())  # every Tk read happens before the worker starts
        self.render()
        if work is not None:
            self._start(work)

    def _on_cancel(self) -> None:
        self._session.cancel()
        self.render()

    def _on_clear(self) -> None:
        self._session.clear()
        self.render()
        if self._on_change is not None:
            self._on_change()

    # ------------------------------------------------------------------ off-thread work

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = TkUiDispatcher(self.winfo_toplevel())
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Prepare a driving video with FFmpeg without blocking Tk",
                ),
                dispatch=dispatcher.invoke,
            )
        return self._runner

    def _start(self, work: PreparationWork) -> None:
        self._work_runner().start(
            f"VideoMotionPreparation-{id(self)}",
            lambda: self._session.run(work),
            lambda outcome: self._deliver(lambda: self._finish(work, outcome)),
        )

    def _deliver(self, finish: Callable[[], None]) -> None:
        """Run ``finish`` on the Tk thread unless the panel was torn down meanwhile."""

        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
            finish()
        except tk.TclError:
            pass  # the widget tree is going away; there is nothing left to update

    def _finish(self, work: PreparationWork, outcome: WorkOutcome) -> None:
        self._session.finish(work, outcome)
        self.render()
        if self._on_change is not None:
            self._on_change()

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            self._session.close()  # cancels a running preparation and drops its late result

    # ------------------------------------------------------------------ rendering (Tk thread)

    def render(self) -> None:
        view = self._session.view()
        self._last_view = view
        if not view.visible:
            self.grid_remove()  # the selected workflow takes no driving video: nothing to offer
            return
        self.grid()
        self.status_var.set(view.status)
        self.using_var.set(view.using)
        detail = [*view.identity_lines]
        if view.explanation_lines:
            detail.append("")
            detail.extend(view.explanation_lines)
        self.detail_var.set("\n".join(detail))
        self.convert_check.configure(text=view.fps_label)
        self.prepare_button.configure(state="normal" if view.can_prepare else "disabled")
        self.cancel_button.configure(state="normal" if view.can_cancel else "disabled")
        self.clear_button.configure(state="normal" if view.can_clear else "disabled")
        entry_state = "normal" if view.available and view.state != "running" else "disabled"
        for widget in (self.start_entry, self.end_entry, self.convert_check):
            widget.configure(state=entry_state)
        self._render_frames(view)

    def _photo(self, png: bytes | None) -> tk.PhotoImage | None:
        if not png:
            return None
        try:
            photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        except tk.TclError:
            return None
        self._photos.append(photo)  # a PhotoImage with no Python reference is garbage collected
        return photo

    def _render_frames(self, view: MotionPrepView) -> None:
        for label in self._thumb_labels:
            label.destroy()
        self._thumb_labels = []
        self._photos = []
        for frame in view.frames:
            photo = self._photo(frame.png_bytes)
            if photo is None:
                continue
            self._thumb_labels.append(
                ttk.Label(
                    self.frames_frame,
                    image=photo,
                    text=frame.caption,
                    compound="top",
                    style="Dark.TLabel",
                    wraplength=_THUMB_CELL_WIDTH,
                )
            )
        if self._thumb_labels:
            self.frames_frame.grid()
        else:
            self.frames_frame.grid_remove()
        self._layout_frames()

    def _layout_frames(self) -> None:
        """Wrap the thumbnails to the width the panel is actually given."""

        if not self._thumb_labels:
            return
        width = max(self.frames_frame.winfo_width(), _THUMB_CELL_WIDTH)
        columns = max(1, width // _THUMB_CELL_WIDTH)
        for index, label in enumerate(self._thumb_labels):
            label.grid(row=index // columns, column=index % columns, sticky="nw", padx=(0, 8))

    @property
    def last_view(self) -> MotionPrepView | None:
        return self._last_view


__all__ = ["WorkflowMotionPreparationPanel"]
