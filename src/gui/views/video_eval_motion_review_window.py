"""Tk window for reviewing a controlled-motion eval run (PR-VID-MOTION-410).

Presentation only. The state machine is ``MotionReviewSession`` (Tk-free) on the existing ``ComparisonClock``. Loading and
decoding run on workers owned by the existing ``ThreadRegistry``; results return on the Tk thread through
``TkUiDispatcher`` and are dropped by the session when stale. The window shows the source image, the effective driving
reference and up to two generated results on one clock, discloses every difference in rate, length or identity, and rates
nothing: ratings stay in ``ratings.csv`` (``docs/runbooks/video_eval_kit.md``). It builds no job and starts no process other
than the contained, bounded FFmpeg preview decode. Nothing plays until Play is pressed.
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from src.gui import theme_v2
from src.gui.ui_dispatcher import tk_dispatcher_for
from src.gui.view_contracts.video_eval_motion_review_contract import (
    SLOT_DRIVER,
    SLOT_LEFT,
    SLOT_RIGHT,
    SLOT_SOURCE,
    MediaWork,
    MotionReviewSession,
    anchor_text,
)
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.gui.view_contracts.video_review_contract import PLAYBACK_TICK_MS
from src.utils.os_shell import ShellResult, open_file, reveal_in_file_manager
from src.utils.thread_registry import get_thread_registry
from src.video.review_preview import prepare_review_preview
from src.video.video_eval_motion_review import load_motion_review

_DISPLAY_EDGE = 300
_SOURCE_EDGE = 512
_SLOT_TITLES = {
    SLOT_SOURCE: "Source image",
    SLOT_DRIVER: "Driving reference",
    SLOT_LEFT: "Result A",
    SLOT_RIGHT: "Result B",
}


def load_source_image(path: str, cancel: Any = None) -> Image.Image:
    """The source image as a bounded RGB thumbnail (never the full-resolution decode)."""

    with Image.open(path) as image:
        image.thumbnail((_SOURCE_EDGE, _SOURCE_EDGE))
        return image.convert("RGB")


class VideoEvalMotionReviewWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        run_dir: str | Path,
        visibility_mode_provider: Callable[[], str] | None = None,
        runner: BackgroundWorkRunner | None = None,
        load: Callable[..., Any] = load_motion_review,
        preview_fn: Callable[..., Any] = prepare_review_preview,
        image_fn: Callable[..., Any] = load_source_image,
        opener: Callable[[str], ShellResult] = open_file,
        revealer: Callable[[str], ShellResult] = reveal_in_file_manager,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(master)
        self.title("Motion Review")
        self.geometry("1280x900")
        self.minsize(820, 560)
        self._closed = False
        self._tick_id: str | None = None
        self._runner = runner
        self._opener, self._revealer, self._now = opener, revealer, now
        self._run_dir = str(run_dir)
        self._syncing = False
        self._session = MotionReviewSession(
            load=lambda path, cancel: load(path, cancel),
            prepare_preview=lambda path, cancel: preview_fn(path, cancel=cancel),
            prepare_image=lambda path, cancel: image_fn(path, cancel),
            visibility=visibility_mode_provider or (lambda: "nsfw"),
            on_change=self._render,
        )
        self.status_var = tk.StringVar(value=self._session.status)
        self.position_var = tk.StringVar()
        self.play_var = tk.StringVar(value="Play")
        self.case_var, self.left_var, self.right_var = (tk.StringVar() for _ in range(3))
        self._panels: dict[str, dict[str, Any]] = {}
        self._photos: dict[str, Any] = {}
        self._anchor_labels: dict[str, list[ttk.Label]] = {}
        self._combos: dict[str, ttk.Combobox] = {}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.after(0, self._on_load)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        top = ttk.Frame(self, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")
        ttk.Button(top, text="Reload", command=self._on_load).pack(side="left", padx=(0, 8))
        for key, text, var, command in (
            ("case", "Case", self.case_var, self._on_case),
            ("left", "Result A", self.left_var, self._on_arms),
            ("right", "Result B", self.right_var, self._on_arms),
        ):
            ttk.Label(top, text=text).pack(side="left", padx=(8, 3))
            combo = ttk.Combobox(
                top,
                textvariable=var,
                state="readonly",
                width=26,
                style=theme_v2.DARK_COMBOBOX_STYLE,
            )
            combo.pack(side="left")
            combo.bind("<<ComboboxSelected>>", partial(self._selected, command))
            self._combos[key] = combo
        ttk.Label(self, textvariable=self.status_var, wraplength=1100).grid(
            row=1, column=0, sticky="ew", padx=10
        )
        body = ttk.Frame(self, padding=(10, 4))
        body.grid(row=2, column=0, sticky="nsew")
        for column, key in enumerate(_SLOT_TITLES):
            body.columnconfigure(column, weight=1)
            frame = ttk.LabelFrame(body, text=_SLOT_TITLES[key], padding=4)
            frame.grid(row=0, column=column, sticky="nsew", padx=3)
            image = ttk.Label(frame, anchor="center")
            image.pack(fill="both", expand=True)
            caption = tk.StringVar()
            ttk.Label(frame, textvariable=caption, wraplength=_DISPLAY_EDGE, justify="left").pack(
                fill="x"
            )
            info = tk.Text(frame, height=6, width=34, wrap="word", state="disabled")
            theme_v2.style_text_widget(info)
            info.pack(fill="x", pady=(3, 0))
            original = ttk.Button(frame, text="Open original", command=partial(self._open, key))
            original.pack(side="left", pady=(3, 0))
            reveal = ttk.Button(frame, text="Reveal", command=partial(self._reveal, key))
            reveal.pack(side="left", pady=(3, 0), padx=(4, 0))
            self._panels[key] = {
                "image": image,
                "caption": caption,
                "info": info,
                "open": original,
                "reveal": reveal,
            }
        transport = ttk.Frame(self, padding=(10, 4))
        transport.grid(row=3, column=0, sticky="ew")
        for text, command in (("|<", self._session.restart), ("<", lambda: self._session.step(-1))):
            ttk.Button(transport, text=text, width=3, command=command).pack(side="left")
        ttk.Button(transport, textvariable=self.play_var, width=7, command=self._on_play).pack(
            side="left", padx=3
        )
        ttk.Button(transport, text=">", width=3, command=lambda: self._session.step(1)).pack(
            side="left"
        )
        self.scale = ttk.Scale(transport, from_=0, to=1, command=self._on_scrub)
        self.scale.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(transport, textvariable=self.position_var).pack(side="left")
        strip = ttk.LabelFrame(
            self, text="First, middle and last moment (the same times in every clip)", padding=4
        )
        strip.grid(row=4, column=0, sticky="ew", padx=10)
        for column, key in enumerate((SLOT_DRIVER, SLOT_LEFT, SLOT_RIGHT)):
            cell = ttk.Frame(strip)
            cell.grid(row=0, column=column, padx=6)
            labels = [ttk.Label(cell) for _ in range(3)]
            for label in labels:
                label.pack(side="left", padx=1)
            self._anchor_labels[key] = labels
            anchor_caption = ttk.Label(cell, text="")
            anchor_caption.pack(side="bottom")
            self._panels.setdefault(f"anchor_{key}", {})["caption"] = anchor_caption
        self.notes = tk.Text(self, height=8, wrap="word", state="disabled")
        theme_v2.style_text_widget(self.notes)
        self.notes.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 10))

    @staticmethod
    def _selected(handler: Callable[[], None], _event: Any = None) -> None:
        handler()

    # ------------------------------------------------------------------ workers

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = tk_dispatcher_for(self)
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Load and decode motion review media without blocking Tk",
                ),
                dispatch=dispatcher.invoke,
            )
        return self._runner

    def _deliver(self, finish: Callable[[], None]) -> None:
        if not self._closed:
            try:
                finish()
            except tk.TclError:
                pass  # the widget tree is going away

    def _on_load(self) -> None:
        work = self._session.begin_load(self._run_dir)
        if work is None:
            return

        def done(outcome: WorkOutcome) -> None:
            self._deliver(lambda: self._finish_load(work, outcome))

        self._work_runner().start("MotionReview-Load", lambda: self._session.run_load(work), done)

    def _finish_load(self, work: Any, outcome: WorkOutcome) -> None:
        self._refill_choices(self._session.finish_load(work, outcome))

    def _refill_choices(self, works: list[MediaWork] | None) -> None:
        cases = self._session.case_choices()
        self._combos["case"]["values"] = [label for _id, label in cases]
        arms = self._session.arm_choices()
        for key in ("left", "right"):
            self._combos[key]["values"] = ["", *(label for _id, label in arms)]
        self._sync_choice_vars()
        self._start_media(works or [])

    def _start_media(self, works: list[MediaWork]) -> None:
        for work in works:
            self._work_runner().start(
                f"MotionReview-{work.slot}",
                partial(self._session.run_media, work),
                partial(self._media_done, work),
            )

    def _media_done(self, work: MediaWork, outcome: WorkOutcome) -> None:
        def finish() -> None:
            self._session.finish_media(work, outcome)

        self._deliver(finish)

    def _sync_choice_vars(self) -> None:
        self._syncing = True
        try:
            cases = dict(self._session.case_choices())
            self.case_var.set(cases.get(self._session.case_id or "", ""))
            arms = dict(self._session.arm_choices())
            self.left_var.set(arms.get(self._session.arms[0] or "", ""))
            self.right_var.set(arms.get(self._session.arms[1] or "", ""))
        finally:
            self._syncing = False

    def _id_for(self, label: str, choices: list[tuple[str, str]]) -> str | None:
        return next((key for key, text in choices if text == label), None)

    def _on_case(self) -> None:
        if self._syncing:
            return
        case_id = self._id_for(self.case_var.get(), self._session.case_choices())
        self._start_media(self._session.select_case(case_id))
        self._refill_choices(None)

    def _on_arms(self) -> None:
        if self._syncing:
            return
        arms = self._session.arm_choices()
        works = self._session.select_arms(
            self._id_for(self.left_var.get(), arms), self._id_for(self.right_var.get(), arms)
        )
        self._start_media(works)
        self._sync_choice_vars()

    # ------------------------------------------------------------------ transport

    def _on_play(self) -> None:
        if self._session.clock.playing:
            self._session.pause()
        else:
            self._session.play(self._now())
            self._schedule_tick()

    def _on_scrub(self, value: str) -> None:
        if self._syncing:
            return
        position = int(round(float(value) * self._session.clock.last_position))
        if position != self._session.clock.position:
            self._session.pause()
            self._session.seek(position)

    def _schedule_tick(self) -> None:
        if self._tick_id is None and not self._closed:
            self._tick_id = self.after(PLAYBACK_TICK_MS, self._tick)

    def _tick(self) -> None:
        self._tick_id = None
        if self._closed:
            return
        self._session.tick(self._now())
        if self._session.clock.playing:
            self._schedule_tick()

    def _open(self, key: str) -> None:
        self._launch(self._session.original_path(key), self._opener)

    def _reveal(self, key: str) -> None:
        self._launch(self._session.original_path(key), self._revealer)

    def _launch(self, path: str | None, action: Callable[[str], ShellResult]) -> None:
        if path is None:
            self.status_var.set("That file is not available on disk now.")
            return
        result = action(path)
        if not result.ok:
            self.status_var.set(result.message)

    # ------------------------------------------------------------------ rendering

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _show_image(self, key: str, image: Image.Image | None) -> None:
        label: ttk.Label = self._panels[key]["image"]
        if image is None:
            self._photos.pop(key, None)
            label.configure(image="")
            return
        scaled = image.copy()
        scaled.thumbnail((_DISPLAY_EDGE, _DISPLAY_EDGE))
        photo = ImageTk.PhotoImage(scaled, master=self)
        self._photos[key] = photo  # keep a reference; Tk does not
        label.configure(image=photo)

    def _render(self) -> None:
        if self._closed:
            return
        session = self._session
        self.status_var.set(session.status)
        self.play_var.set("Pause" if session.clock.playing else "Play")
        self.position_var.set(session.position_text())
        last = session.clock.last_position
        self._syncing = True
        try:
            self.scale.set(0 if last <= 0 else session.clock.position / last)
        finally:
            self._syncing = False
        rows = {
            role: (label, note) for role, label, note in session.role_rows() if role != "result"
        }
        for key in (SLOT_SOURCE, SLOT_DRIVER, SLOT_LEFT, SLOT_RIGHT):
            panel = self._panels[key]
            slot = session.slot(key)
            image: Image.Image | None = None
            caption = ""
            if key == SLOT_SOURCE:
                caption = rows.get("source", ("", ""))[1]
                image = slot.image if slot is not None and slot.state == "ready" else None
            elif slot is not None and slot.clip is not None:
                info = session.frame_info(key)
                image = slot.clip.frame_image(info.index) if info is not None else None
                caption = slot.message
                if info is not None and info.held:
                    caption += " (held on its last frame)"
            elif slot is not None:
                caption = slot.message or "Loading..."
            if key == SLOT_DRIVER:
                caption = f"{rows.get('driver', ('', ''))[1]}\n{caption}".strip()
            if slot is None and key in (SLOT_SOURCE, SLOT_DRIVER) and session.media_hidden:
                caption = "Hidden in SFW mode."
            panel["caption"].set(caption)
            self._show_image(key, image)
            body = "\n".join(session.settings_rows(key)) if key in (SLOT_LEFT, SLOT_RIGHT) else ""
            self._set_text(panel["info"], body)
            panel["open"].state(["!disabled"] if session.original_path(key) else ["disabled"])
            panel["reveal"].state(["!disabled"] if session.original_path(key) else ["disabled"])
        for key in (SLOT_DRIVER, SLOT_LEFT, SLOT_RIGHT):
            infos = session.anchor_frames(key)
            slot = session.slot(key)
            for label, position in zip(
                self._anchor_labels[key], session.anchor_positions(), strict=True
            ):
                frame = None
                if slot is not None and slot.clip is not None:
                    shown = session.frame_info(key, position)
                    frame = slot.clip.frame_image(shown.index).copy() if shown is not None else None
                if frame is None:
                    label.configure(image="")
                    continue
                frame.thumbnail((96, 96))
                photo = ImageTk.PhotoImage(frame, master=self)
                self._photos[f"{key}{position}"] = photo
                label.configure(image=photo)
            self._panels[f"anchor_{key}"]["caption"].configure(
                text=anchor_text(infos) if infos else ""
            )
        lines = [f"{label}: {value}" for label, value in session.case_rows()]
        lines.extend(["", *session.notes()])
        self._set_text(self.notes, "\n".join(lines))

    def _on_destroy(self, event: Any = None) -> None:
        if event is not None and event.widget is not self:
            return
        self._closed = True
        if self._tick_id is not None:
            try:
                self.after_cancel(self._tick_id)
            except tk.TclError:
                pass
            self._tick_id = None
        self._session.close()


def open_motion_review(
    master: tk.Misc,
    run_dir: str | Path,
    *,
    visibility_mode_provider: Callable[[], str] | None = None,
    runner: BackgroundWorkRunner | None = None,
) -> VideoEvalMotionReviewWindow:
    return VideoEvalMotionReviewWindow(
        master, run_dir=run_dir, visibility_mode_provider=visibility_mode_provider, runner=runner
    )


__all__ = ["VideoEvalMotionReviewWindow", "load_source_image", "open_motion_review"]
