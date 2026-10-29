"""Tk window for comparing and rating the clips of one Video Workflow experiment (PR-VID-QUALITY-211).

Presentation only.  The state machine is ``VideoReviewSession`` and the comparison clock is
``ComparisonClock`` (both Tk-free).  Everything that touches the repository, the file system, FFmpeg or the
evidence file runs on a worker owned by the existing ``ThreadRegistry``; results come back to the Tk thread
through ``TkUiDispatcher`` and are dropped by the session when they went stale (window closed, review
reloaded, selection changed).  The window builds no job, calls no backend and starts no process other than
the contained, bounded FFmpeg preview decode.

The embedded frames are *review previews*: downscaled and frame-exact, not the original.  "Open original"
hands the recorded artifact to the system viewer.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from src.gui import theme_v2
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.view_contracts.video_review_contract import (
    PLAYBACK_TICK_MS,
    LoadWork,
    PreviewWork,
    SaveWork,
    VideoReviewSession,
    outcome_choices,
    parse_rating_choices,
)
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.learning.video_quality_review import DIMENSIONS
from src.learning.video_review_service import VideoReviewService
from src.utils.thread_registry import get_thread_registry
from src.video.review_preview import prepare_review_preview

logger = logging.getLogger(__name__)

_DISPLAY_ZOOM = 2
_NO_PREFERENCE = "(no preference)"
_PREVIEW_NOTICE = (
    "Review previews: downscaled, frame-exact samples decoded on the CPU for comparison. They do not "
    "preserve every visual property of the original; use Open original for full quality."
)


def _default_open_file(path: str) -> None:
    try:
        startfile = getattr(os, "startfile", None)  # Windows only
        if startfile is not None:
            startfile(path)  # the recorded artifact, opened by the OS default viewer
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except OSError as exc:  # a missing viewer must not break the review
        logger.warning("Could not open %s in the system viewer: %s", path, exc)


class _Side:
    """The widgets and variables of one comparison side (left or right)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.choice_var = tk.StringVar()
        self.combo: ttk.Combobox | None = None
        self.image_label: ttk.Label | None = None
        self.caption_var = tk.StringVar()
        self.info_var = tk.StringVar()
        self.photo: ImageTk.PhotoImage | None = None
        self.shown: tuple[str | None, int, int] | None = None
        self.overall_var = tk.StringVar()
        self.outcome_var = tk.StringVar()
        self.dimension_vars: dict[str, tk.StringVar] = {}
        self.notes: tk.Text | None = None
        self.message_var = tk.StringVar()
        self.save_button: ttk.Button | None = None
        self.original_button: ttk.Button | None = None
        self.form_frame: ttk.LabelFrame | None = None
        self.bound_job: str | None = None


class VideoExperimentReviewWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        service: VideoReviewService,
        initial_job_id: str = "",
        visibility_mode_provider: Callable[[], str] | None = None,
        runner: BackgroundWorkRunner | None = None,
        preview_fn: Callable[..., Any] = prepare_review_preview,
        opener: Callable[[str], None] = _default_open_file,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(master)
        self.title("Video Experiment Review")
        self.geometry("1180x860")
        self.minsize(760, 520)
        self._closed = False
        self._syncing = False
        self._tick_id: str | None = None
        self._static_key: tuple[str, list[tuple[str, str, str, str]]] = ("", [])
        self._runner = runner
        self._opener = opener
        self._now = now
        self._visibility = visibility_mode_provider or (lambda: "nsfw")
        self._session = VideoReviewSession(
            load=lambda job_id, cancel: service.load(job_id, cancel=cancel),
            prepare_preview=lambda path, cancel: preview_fn(path, cancel=cancel),
            save_clip=service.save_clip_review,
            save_preference=service.save_preference,
            file_exists=os.path.isfile,
            on_change=self._render,
        )
        self.job_var = tk.StringVar(value=initial_job_id)
        self.status_var = tk.StringVar(value=self._session.status)
        self.position_var = tk.StringVar()
        self.clock_notes_var = tk.StringVar()
        self.play_var = tk.StringVar(value="Play")
        self.pref_var = tk.StringVar(value=_NO_PREFERENCE)
        self.pref_reason_var = tk.StringVar()
        self.pref_message_var = tk.StringVar()
        self.sides = (_Side("left"), _Side("right"))
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        if initial_job_id.strip():
            self.after_idle(self._on_load)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(3, weight=1)
        ttk.Label(top, text="Job id").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(top, textvariable=self.job_var, width=44)
        entry.grid(row=0, column=1, sticky="w", padx=6)
        entry.bind("<Return>", lambda _e: self._on_load())
        self.load_button = ttk.Button(top, text="Load experiment", command=self._on_load)
        self.load_button.grid(row=0, column=2, sticky="w")
        self.status_label = ttk.Label(top, textvariable=self.status_var, wraplength=900)
        self.status_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        top.bind(
            "<Configure>", lambda e: self.status_label.configure(wraplength=max(200, e.width - 24))
        )

        scroll = ScrollableFrame(self)
        scroll.grid(row=1, column=0, sticky="nsew")
        body = scroll.inner
        body.columnconfigure(0, weight=1)
        self._build_overview(body).grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        self._build_comparison(body).grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        self._build_reviews(body).grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self._build_preference(body).grid(row=3, column=0, sticky="ew", padx=8, pady=(4, 12))

    def _build_overview(self, parent: tk.Misc) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Experiment", padding=8)
        frame.columnconfigure(0, weight=1)
        self.overview_text = tk.Text(frame, height=9, wrap="word", state="disabled")
        theme_v2.style_text_widget(self.overview_text, elevated=True)
        self.overview_text.grid(row=0, column=0, sticky="ew")
        columns = ("arm", "value", "job", "state")
        self.arm_tree = ttk.Treeview(frame, columns=columns, show="headings", height=4)
        for column, title, width in (
            ("arm", "Arm", 90),
            ("value", "Tested value", 220),
            ("job", "Job", 240),
            ("state", "State", 420),
        ):
            self.arm_tree.heading(column, text=title)
            self.arm_tree.column(column, width=width, stretch=True, anchor="w")
        self.arm_tree.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        return frame

    def _build_comparison(self, parent: tk.Misc) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Side-by-side comparison", padding=8)
        frame.columnconfigure((0, 1), weight=1, uniform="side")
        ttk.Label(
            frame, text=_PREVIEW_NOTICE, wraplength=1000, style=theme_v2.MUTED_LABEL_STYLE
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for column, side in enumerate(self.sides):
            holder = ttk.Frame(frame)
            holder.grid(row=1, column=column, sticky="nsew", padx=4)
            holder.columnconfigure(0, weight=1)
            combo = ttk.Combobox(holder, textvariable=side.choice_var, state="readonly", width=34)
            combo.grid(row=0, column=0, sticky="w")
            combo.bind("<<ComboboxSelected>>", lambda _e: self._on_pair_selected())
            side.combo = combo
            side.image_label = ttk.Label(holder, anchor="center", relief="sunken")
            side.image_label.grid(row=1, column=0, sticky="nsew", pady=4, ipadx=4, ipady=4)
            ttk.Label(holder, textvariable=side.caption_var, wraplength=480).grid(
                row=2, column=0, sticky="w"
            )
            ttk.Label(
                holder, textvariable=side.info_var, wraplength=480, style=theme_v2.MUTED_LABEL_STYLE
            ).grid(row=3, column=0, sticky="w")
            side.original_button = ttk.Button(
                holder, text="Open original", command=partial(self._on_open_original, side)
            )
            side.original_button.grid(row=4, column=0, sticky="w", pady=(4, 0))
        transport = ttk.Frame(frame)
        transport.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        transport.columnconfigure(5, weight=1)
        self.restart_button = ttk.Button(transport, text="Restart", command=self._on_restart)
        self.back_button = ttk.Button(transport, text="< Frame", command=lambda: self._on_step(-1))
        self.play_button = ttk.Button(transport, textvariable=self.play_var, command=self._on_play)
        self.forward_button = ttk.Button(
            transport, text="Frame >", command=lambda: self._on_step(1)
        )
        for index, button in enumerate(
            (self.restart_button, self.back_button, self.play_button, self.forward_button)
        ):
            button.grid(row=0, column=index, padx=(0, 4))
        self.scrub = ttk.Scale(
            transport, from_=0, to=0, orient="horizontal", command=self._on_scrub
        )
        self.scrub.grid(row=0, column=5, sticky="ew", padx=8)
        ttk.Label(frame, textvariable=self.position_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Label(
            frame,
            textvariable=self.clock_notes_var,
            wraplength=1000,
            style=theme_v2.MUTED_LABEL_STYLE,
        ).grid(row=4, column=0, columnspan=2, sticky="w")
        return frame

    def _build_reviews(self, parent: tk.Misc) -> ttk.Frame:
        host = ttk.Frame(parent)
        host.columnconfigure((0, 1), weight=1, uniform="review")
        for column, side in enumerate(self.sides):
            frame = ttk.LabelFrame(host, text="Review", padding=8)
            frame.grid(row=0, column=column, sticky="nsew", padx=4)
            frame.columnconfigure(1, weight=1)
            side.form_frame = frame
            ttk.Label(frame, text="Overall rating (1 worst - 5 best)").grid(
                row=0, column=0, sticky="w"
            )
            self._combo(frame, side.overall_var, list(parse_rating_choices()), 0, "overall", side)
            ttk.Label(frame, text="Requested action").grid(row=1, column=0, sticky="w", pady=(4, 0))
            labels = [label for _value, label in outcome_choices()]
            outcome = self._combo(frame, side.outcome_var, labels, 1, "outcome", side)
            outcome.configure(width=22)
            for offset, (key, label, question) in enumerate(DIMENSIONS, start=2):
                ttk.Label(frame, text=f"{label} - {question}", wraplength=300).grid(
                    row=offset, column=0, sticky="w", pady=(4, 0)
                )
                side.dimension_vars[key] = tk.StringVar()
                self._combo(
                    frame, side.dimension_vars[key], list(parse_rating_choices()), offset, key, side
                )
            row = 2 + len(DIMENSIONS)
            ttk.Label(frame, text="Observed failures / notes").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(6, 0)
            )
            side.notes = tk.Text(frame, height=4, wrap="word")
            theme_v2.style_text_widget(side.notes, elevated=True)
            side.notes.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
            side.notes.bind("<KeyRelease>", partial(self._on_notes_key, side), add="+")
            side.save_button = ttk.Button(
                frame, text="Save review", command=partial(self._on_save, side)
            )
            side.save_button.grid(row=row + 2, column=0, sticky="w", pady=(6, 0))
            ttk.Label(frame, textvariable=side.message_var, wraplength=420).grid(
                row=row + 3, column=0, columnspan=2, sticky="w"
            )
        return host

    def _combo(
        self,
        frame: tk.Misc,
        variable: tk.StringVar,
        values: list[str],
        row: int,
        field: str,
        side: _Side,
    ) -> ttk.Combobox:
        combo = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=8)
        combo.grid(row=row, column=1, sticky="e")
        variable.trace_add("write", lambda *_a, f=field, s=side: self._on_field(s, f))
        return combo

    def _build_preference(self, parent: tk.Misc) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(
            parent, text="Manual preference (your choice, not a computed winner)", padding=8
        )
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Preferred arm").grid(row=0, column=0, sticky="w")
        self.pref_combo = ttk.Combobox(
            frame, textvariable=self.pref_var, state="readonly", width=34
        )
        self.pref_combo.grid(row=0, column=1, sticky="w", padx=6)
        self.pref_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_preference())
        ttk.Label(frame, text="Why").grid(row=1, column=0, sticky="w", pady=(4, 0))
        reason = ttk.Entry(frame, textvariable=self.pref_reason_var)
        reason.grid(row=1, column=1, sticky="ew", padx=6, pady=(4, 0))
        self.pref_reason_var.trace_add("write", lambda *_a: self._on_preference())
        self.pref_button = ttk.Button(
            frame, text="Save preference", command=self._on_save_preference
        )
        self.pref_button.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(frame, textvariable=self.pref_message_var, wraplength=700).grid(
            row=2, column=1, sticky="w", padx=6, pady=(6, 0)
        )
        return frame

    # ------------------------------------------------------------------ background work

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Load, decode and save a Video Experiment Review without blocking Tk",
                ),
                dispatch=dispatcher.invoke,
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
            finish()
        except tk.TclError:
            pass  # the widget tree is going away

    def _on_destroy(self, event: Any = None) -> None:
        if event is None or event.widget is self:
            self._closed = True
            self._cancel_tick()
            self._session.close()  # cancels loads/decodes and frees frame memory

    # ------------------------------------------------------------------ handlers

    def _on_load(self) -> None:
        work = self._session.begin_load(self.job_var.get())
        if work is None:
            return
        self._work_runner().start(
            f"VideoReview-Load-{id(self)}",
            lambda: self._session.run_load(work),
            lambda outcome: self._deliver(lambda: self._finish_load(work, outcome)),
        )

    def _finish_load(self, work: LoadWork, outcome: WorkOutcome) -> None:
        if self._session.finish_load(work, outcome):
            for side in self.sides:  # a reload replaces the forms: rebuild the widgets from them
                side.bound_job = None
                side.shown = None
            self._start_previews(self._session.select_pair(*self._session.pair))
        self._render()

    def _start_previews(self, works: list[PreviewWork]) -> None:
        for work in works:
            self._work_runner().start(
                f"VideoReview-Preview-{work.job_id[:8]}",
                partial(self._session.run_preview, work),
                partial(self._deliver_preview, work),
            )

    def _deliver_preview(self, work: PreviewWork, outcome: WorkOutcome) -> None:
        self._deliver(partial(self._finish_preview, work, outcome))

    def _finish_preview(self, work: PreviewWork, outcome: WorkOutcome) -> None:
        self._session.finish_preview(work, outcome)
        self._render()

    def _on_pair_selected(self) -> None:
        jobs = [self._choice_job(side) for side in self.sides]
        self._start_previews(self._session.select_pair(jobs[0], jobs[1]))
        self._render()

    def _choice_job(self, side: _Side) -> str | None:
        label = side.choice_var.get()
        return next((job for job, text in self._session.available_choices() if text == label), None)

    def _on_restart(self) -> None:
        self._session.clock.restart()
        self._render()

    def _on_step(self, delta: int) -> None:
        self._session.clock.step(delta)
        self._render()

    def _on_play(self) -> None:
        clock = self._session.clock
        if clock.playing:
            clock.pause()
            self._cancel_tick()
        else:
            clock.play(self._now())
            self._schedule_tick()
        self._render()

    def _on_scrub(self, value: str) -> None:
        if self._syncing:
            return
        self._session.clock.pause()
        self._session.clock.seek(int(float(value)))
        self._render()

    def _cancel_tick(self) -> None:
        tick_id, self._tick_id = self._tick_id, None
        if tick_id is not None:
            try:
                self.after_cancel(tick_id)
            except tk.TclError:
                pass

    def _schedule_tick(self) -> None:
        if self._tick_id is None and not self._closed:
            self._tick_id = self.after(PLAYBACK_TICK_MS, self._tick)

    def _tick(self) -> None:
        self._tick_id = None
        if self._closed:
            return
        self._session.clock.tick(self._now())
        self._render_playback()
        if self._session.clock.playing:
            self._schedule_tick()

    def _on_field(self, side: _Side, field: str) -> None:
        if self._syncing or side.bound_job is None:
            return
        if field == "overall":
            value = side.overall_var.get()
        elif field == "outcome":
            label = side.outcome_var.get()
            value = next((v for v, text in outcome_choices() if text == label), "")
        else:
            value = side.dimension_vars[field].get()
        self._session.set_field(side.bound_job, field, value)

    def _on_notes_key(self, side: _Side, _event: Any = None) -> None:
        self._on_notes(side)

    def _on_notes(self, side: _Side) -> None:
        if side.bound_job is not None and side.notes is not None:
            self._session.set_field(side.bound_job, "notes", side.notes.get("1.0", "end-1c"))

    def _on_save(self, side: _Side) -> None:
        job_id = side.bound_job
        work = self._session.begin_save(job_id) if job_id else None
        self._render()
        if work is None:
            return
        self._work_runner().start(
            f"VideoReview-Save-{work.job_id[:8]}",
            lambda: self._session.run_save(work),
            lambda outcome: self._deliver(lambda: self._finish_save(work, outcome)),
        )

    def _finish_save(self, work: SaveWork, outcome: WorkOutcome) -> None:
        self._session.finish_save(work, outcome)
        self._render()

    def _on_preference(self) -> None:
        if self._syncing:
            return
        label = self.pref_var.get()
        job = next((j for j, text in self._session.available_choices() if text == label), None)
        self._session.set_preference(job, self.pref_reason_var.get())

    def _on_save_preference(self) -> None:
        work = self._session.begin_save_preference()
        self._render()
        if work is None:
            return
        self._work_runner().start(
            f"VideoReview-SavePreference-{id(self)}",
            lambda: self._session.run_save(work),
            lambda outcome: self._deliver(lambda: self._finish_save(work, outcome)),
        )

    def _on_open_original(self, side: _Side) -> None:
        path = self._session.original_path(side.bound_job)
        if path:
            self._opener(path)
        else:
            side.info_var.set("The original file is no longer available at its recorded path.")

    # ------------------------------------------------------------------ rendering

    def _render(self) -> None:
        if self._closed:
            return
        try:
            self._render_now()
        except tk.TclError:
            pass  # the window is being destroyed

    def _render_now(self) -> None:
        session = self._session
        mode = self._visibility()
        self.status_var.set(session.status)
        self.load_button.configure(state="disabled" if session.busy_loading else "normal")
        overview = "\n".join(f"{label}: {value}" for label, value in session.overview_rows(mode))
        arm_rows = [
            (row["label"], row["value"], row["job_id"], row["state_text"])
            for row in session.arm_rows(mode)
        ]
        if (overview, arm_rows) != self._static_key:
            self._static_key = (overview, arm_rows)
            self._set_text(self.overview_text, overview)
            self.arm_tree.delete(*self.arm_tree.get_children())
            for values in arm_rows:
                self.arm_tree.insert("", "end", values=values)
        choices = session.available_choices()
        labels = [text for _job, text in choices]
        self._syncing = True
        try:
            for index, side in enumerate(self.sides):
                job = session.pair[index]
                if side.combo is not None:
                    side.combo.configure(values=labels)
                side.choice_var.set(next((text for j, text in choices if j == job), ""))
                self._render_side(side, job)
            self._render_clock()
            self.pref_combo.configure(values=[_NO_PREFERENCE, *labels])
            self.pref_var.set(
                next((text for j, text in choices if j == session.preference_job), _NO_PREFERENCE)
            )
            if self.pref_reason_var.get() != session.preference_reason:
                self.pref_reason_var.set(session.preference_reason)
        finally:
            self._syncing = False
        self.pref_message_var.set(session.preference_message)
        self.pref_button.configure(
            state="normal" if session.group is not None and "" not in session.saving else "disabled"
        )

    def _render_playback(self) -> None:
        """The per-tick update: frames, scrubber and position text only."""

        if self._closed:
            return
        try:
            for index, side in enumerate(self.sides):
                job = self._session.pair[index]
                self._render_frame(side, job, self._session.slot(job))
            self._render_clock()
        except tk.TclError:
            pass  # the window is being destroyed

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _render_side(self, side: _Side, job_id: str | None) -> None:
        session = self._session
        arm = session.arm(job_id)
        slot = session.slot(job_id)
        rebind = side.bound_job != job_id
        side.bound_job = job_id
        if arm is None:
            side.caption_var.set("No clip selected.")
            side.info_var.set("")
        else:
            side.caption_var.set(
                f"{arm.label}: tested value {session.arm_value_text(arm, self._visibility())}"
            )
            if slot is None:
                side.info_var.set(arm.state_text)
            elif slot.state == "loading":
                side.info_var.set("Preparing review preview...")
            else:
                side.info_var.set(slot.message)
        if side.original_button is not None:
            side.original_button.configure(
                state="normal" if session.original_path(job_id) else "disabled"
            )
        self._render_frame(side, job_id, slot)
        form = session.forms.get(job_id or "")
        usable = session.can_review(job_id)
        if side.form_frame is not None:
            title = f"Review of {arm.label}" if arm is not None else "Review"
            if job_id and session.is_dirty(job_id):
                title += "  (unsaved edits)"
            side.form_frame.configure(text=title)
        if rebind and form is not None:
            side.overall_var.set(form.overall)
            side.outcome_var.set(next((t for v, t in outcome_choices() if v == form.outcome), ""))
            for key, var in side.dimension_vars.items():
                var.set(form.dimensions.get(key, ""))
            if side.notes is not None:
                side.notes.delete("1.0", "end")
                side.notes.insert("1.0", form.notes)
        elif rebind:
            side.overall_var.set("")
            side.outcome_var.set("")
            for var in side.dimension_vars.values():
                var.set("")
            if side.notes is not None:
                side.notes.delete("1.0", "end")
        side.message_var.set(session.messages.get(job_id or "", ""))
        if side.save_button is not None:
            busy = bool(job_id) and job_id in session.saving
            side.save_button.configure(state="normal" if usable and not busy else "disabled")

    def _render_frame(self, side: _Side, job_id: str | None, slot: Any) -> None:
        label = side.image_label
        if label is None:
            return
        clip = slot.clip if slot is not None and slot.state == "ready" else None
        timing = self._session.timing_for(job_id)
        if clip is None or timing is None:
            if side.shown is not None:
                label.configure(image="")
                side.photo = None
                side.shown = None
            return
        index = self._session.clock.frame_index(timing)
        key = (job_id, index, slot.token)
        if side.shown == key:
            return
        image = clip.frame_image(index)
        image = image.resize(
            (image.width * _DISPLAY_ZOOM, image.height * _DISPLAY_ZOOM), Image.Resampling.BILINEAR
        )
        side.photo = ImageTk.PhotoImage(image, master=self)
        label.configure(image=side.photo)
        side.shown = key

    def _render_clock(self) -> None:
        clock = self._session.clock
        has_clip = any(self._session.timing_for(job) is not None for job in self._session.pair)
        self._syncing = True
        try:
            self.scrub.configure(to=max(0, clock.last_position))
            self.scrub.set(clock.position)
        finally:
            self._syncing = False
        state = "normal" if has_clip else "disabled"
        for widget in (
            self.restart_button,
            self.back_button,
            self.play_button,
            self.forward_button,
            self.scrub,
        ):
            widget.configure(state=state)
        self.play_var.set("Pause" if clock.playing else "Play")
        timings = [
            t
            for t in (self._session.timing_for(job) for job in self._session.pair)
            if t is not None
        ]
        self.position_var.set(
            clock.position_text(timings) if has_clip else "No preview to play yet."
        )
        self.clock_notes_var.set("\n".join(clock.notes()))


def build_review_service(controller: Any) -> VideoReviewService | None:
    """The review service over the application's canonical repository, or ``None`` without one."""

    from src.learning.learning_paths import get_learning_records_path

    repository: Any = getattr(getattr(controller, "job_service", None), "history_store", None)
    if not callable(getattr(repository, "get_job", None)) or not callable(
        getattr(repository, "list_experiment_sibling_entries", None)
    ):
        return None
    return VideoReviewService(repository, get_learning_records_path())


def open_video_experiment_review(
    parent: tk.Misc, controller: Any, job_id: str = ""
) -> VideoExperimentReviewWindow | None:
    """Open a review window for ``job_id`` (or an empty one to type a job id); ``None`` if unavailable."""

    service = build_review_service(controller)
    if service is None:
        return None

    def visibility() -> str:
        state = getattr(controller, "app_state", None)
        return str(getattr(state, "content_visibility_mode", "nsfw") or "nsfw")

    return VideoExperimentReviewWindow(
        parent,
        service=service,
        initial_job_id=job_id,
        visibility_mode_provider=visibility,
    )


__all__ = [
    "VideoExperimentReviewWindow",
    "build_review_service",
    "open_video_experiment_review",
]
