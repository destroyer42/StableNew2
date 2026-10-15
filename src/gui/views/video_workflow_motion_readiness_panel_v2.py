"""Tk rendering of the Video Workflow "Motion source readiness" panel (PR-VID-196).

Presentation only: the state machine and every staleness rule live in ``MotionReadinessSession``.
The exact prepared-source preview and the bounded driving-video probe touch files, so they run on
a worker owned by the existing ``ThreadRegistry``; every widget read happens before a worker
starts and every widget update is marshalled back to the Tk thread through ``TkUiDispatcher``.
The panel is read-only: it has no control that changes the form, the prompt or what is submitted,
and it names no workflow or model.
"""

from __future__ import annotations

import base64
import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import style_text_widget
from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.view_contracts.video_motion_readiness_contract import (
    STATE_ERROR,
    MotionReadinessSession,
    MotionReadinessView,
    SourcePreviewWork,
    VideoInspectionWork,
)
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.utils.thread_registry import get_thread_registry

DEBOUNCE_MS = 300
_THUMB_CELL_WIDTH = 176  # a 160 px preview plus its gutter
_GUIDANCE_TEXT_ROWS = 12


class WorkflowMotionReadinessPanel(ttk.LabelFrame):
    """Compact, read-only readiness section; hidden while no workflow is selected."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        session: MotionReadinessSession,
        read_inputs: Callable[[], Mapping[str, Any]],
        runner: BackgroundWorkRunner | None = None,
        debounce_ms: int = DEBOUNCE_MS,
    ) -> None:
        super().__init__(master, text="Motion source readiness", padding=8)
        self._session = session
        self._read_inputs = read_inputs
        self._runner = runner
        self._debounce_ms = debounce_ms
        self._closed = False
        self._job: str | None = None
        self._photos: list[tk.PhotoImage] = []
        self._thumb_labels: list[ttk.Label] = []
        self._last_view: MotionReadinessView | None = None
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.columnconfigure(1, weight=1)

        # Source: exact prepared pixels on the left, measured geometry on the right.
        self.source_image_label = ttk.Label(self, style="Dark.TLabel")
        self.source_image_label.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10))
        self.source_text_var = tk.StringVar(value="")
        self.source_label = ttk.Label(
            self, textvariable=self.source_text_var, style="Dark.TLabel", justify="left"
        )
        self.source_label.grid(row=0, column=1, sticky="ew")
        bind_wraplength(self.source_label)

        # Driving video: reported metadata, measured decode result, then the small frames.
        self.video_text_var = tk.StringVar(value="")
        self.video_label = ttk.Label(
            self, textvariable=self.video_text_var, style="Dark.TLabel", justify="left"
        )
        self.video_label.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        bind_wraplength(self.video_label)
        self.frames_frame = ttk.Frame(self, style="Panel.TFrame")
        self.frames_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.frames_frame.bind("<Configure>", self._on_frames_configure, add="+")

        self.timing_var = tk.StringVar(value="")
        self.timing_label = ttk.Label(
            self, textvariable=self.timing_var, style="Dark.TLabel", justify="left"
        )
        self.timing_label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bind_wraplength(self.timing_label)

        self.advisory_var = tk.StringVar(value="")
        self.advisory_label = ttk.Label(
            self, textvariable=self.advisory_var, style="Muted.TLabel", justify="left"
        )
        self.advisory_label.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        bind_wraplength(self.advisory_label)

        self.guidance_section = DisclosureSection(self, title="Motion guidance for this workflow")
        self.guidance_section.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        body = self.guidance_section.body
        body.columnconfigure(0, weight=1)
        self.guidance_text = tk.Text(body, height=_GUIDANCE_TEXT_ROWS, wrap="word")
        style_text_widget(self.guidance_text, elevated=True)
        self.guidance_text.grid(row=0, column=0, sticky="ew")
        self.guidance_text.configure(state="disabled")

        self.refresh_button = ttk.Button(
            self, text="Refresh", style="Dark.TButton", command=lambda: self.request_refresh(force=True)
        )
        self.refresh_button.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.render()

    # ------------------------------------------------------------------ requests (Tk thread)

    def request_refresh(self, *, force: bool = False) -> None:
        """Coalesce rapid selection changes; the session then dedups and starts workers."""

        if self._closed:
            return
        if force:
            self._cancel_job()
            self._run_refresh(force=True)
            return
        if self._job is None:
            self._job = self.after(self._debounce_ms, self._run_refresh_from_timer)

    def _cancel_job(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _run_refresh_from_timer(self) -> None:
        self._job = None
        self._run_refresh(force=False)

    def _run_refresh(self, *, force: bool) -> None:
        if self._closed:
            return
        try:
            inputs = dict(self._read_inputs())
        except Exception:
            return  # the form could not be read; leave what is displayed as it is
        works = self._session.refresh(
            source_path=str(inputs.get("source_path") or ""),
            video_path=str(inputs.get("video_path") or ""),
            readiness=inputs.get("readiness"),
            frame_count=inputs.get("frame_count"),
            selected_frames=inputs.get("selected_frames"),
            force=force,
        )
        for work in works:
            self._start(work)
        self.render()

    # ------------------------------------------------------------------ off-thread work

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = TkUiDispatcher(self.winfo_toplevel())
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Preview the prepared source or probe a driving video without "
                    "blocking Tk",
                ),
                dispatch=dispatcher.invoke,
            )
        return self._runner

    def _start(self, work: SourcePreviewWork | VideoInspectionWork) -> None:
        runner = self._work_runner()
        if isinstance(work, SourcePreviewWork):
            runner.start(
                f"VideoMotionReadiness-Source-{id(self)}",
                lambda: self._session.run_source(work),
                lambda outcome: self._deliver(lambda: self._finish_source(work, outcome)),
            )
        else:
            runner.start(
                f"VideoMotionReadiness-Video-{id(self)}",
                lambda: self._session.run_video(work),
                lambda outcome: self._deliver(lambda: self._finish_video(work, outcome)),
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

    def _finish_source(self, work: SourcePreviewWork, outcome: WorkOutcome) -> None:
        follow_up = self._session.finish_source(work, outcome)
        self.render()
        if follow_up is not None:
            self._start(follow_up)

    def _finish_video(self, work: VideoInspectionWork, outcome: WorkOutcome) -> None:
        follow_up = self._session.finish_video(work, outcome)
        self.render()
        if follow_up is not None:
            self._start(follow_up)

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            self._cancel_job()  # a pending debounce callback must not outlive its widget
            self._session.close()

    # ------------------------------------------------------------------ rendering (Tk thread)

    def render(self) -> None:
        view = self._session.view()
        self._last_view = view
        show = bool(view.source_state != "idle" or view.video_state != "idle" or view.guidance_title)
        if not show:
            self.grid_remove()
            return
        self.grid()
        self._photos = []

        source_lines = list(view.source_lines) or [view.source_message]
        if view.source_state == STATE_ERROR:
            source_lines = [f"Source preview unavailable: {view.source_message}"]
        self.source_text_var.set("\n".join(line for line in source_lines if line))
        photo = self._photo(view.source_png)
        self.source_image_label.configure(image=photo or "")

        video_lines: list[str] = []
        if view.accepts_driving_video:
            if view.reported_lines:
                video_lines.append("Reported by the video file (metadata, not measured):")
                video_lines.extend(f"  {line}" for line in view.reported_lines)
            if view.measured_lines:
                video_lines.append("Measured:")
                video_lines.extend(f"  {line}" for line in view.measured_lines)
            if view.video_message:
                video_lines.append(view.video_message)
            if not video_lines:
                video_lines.append("Select a driving video to inspect it.")
        self.video_text_var.set("\n".join(video_lines))
        if view.accepts_driving_video:
            self.video_label.grid()
        else:
            self.video_label.grid_remove()
        self._render_frames(view)

        self.timing_var.set("\n".join(view.timing_lines))
        if view.timing_lines:
            self.timing_label.grid()
        else:
            self.timing_label.grid_remove()
        advisory = ["Advisories (informational; they never change or block a job):"]
        advisory.extend(f"  - {line}" for line in view.advisory_lines)
        self.advisory_var.set("\n".join(advisory) if view.advisory_lines else view.summary)

        self.guidance_section.set_status(view.guidance_title)
        self.guidance_text.configure(state="normal")
        self.guidance_text.delete("1.0", "end")
        self.guidance_text.insert("1.0", "\n".join(view.guidance_lines))
        self.guidance_text.configure(state="disabled")

    def _photo(self, png: bytes | None) -> tk.PhotoImage | None:
        if not png:
            return None
        try:
            photo = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        except tk.TclError:
            return None
        self._photos.append(photo)  # a PhotoImage with no Python reference is garbage collected
        return photo

    def _render_frames(self, view: MotionReadinessView) -> None:
        for label in self._thumb_labels:
            label.destroy()
        self._thumb_labels = []
        for frame in view.video_frames:
            photo = self._photo(frame.png_bytes)
            if photo is None:
                continue
            label = ttk.Label(
                self.frames_frame, image=photo, text=frame.caption, compound="top", style="Dark.TLabel"
            )
            self._thumb_labels.append(label)
        if self._thumb_labels:
            self.frames_frame.grid()
        else:
            self.frames_frame.grid_remove()
        self._layout_frames()

    def _on_frames_configure(self, _event: Any = None) -> None:
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
    def last_view(self) -> MotionReadinessView | None:
        return self._last_view


__all__ = ["DEBOUNCE_MS", "WorkflowMotionReadinessPanel"]
