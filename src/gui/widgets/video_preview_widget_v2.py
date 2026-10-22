"""Looping in-app video preview (PR-VID-UX-314). Presentation only.

The clip is decoded by ``prepare_review_preview`` (contained FFmpeg, bounded size, frames and bytes) on a
worker owned by the existing ``ThreadRegistry``; the result returns to the Tk thread through
``TkUiDispatcher`` and is dropped when it went stale or the widget was destroyed.  The Tk thread only turns
one already-decoded frame into a ``PhotoImage`` per tick, holds that single image, and pauses repainting
while the widget is not on screen.  It starts no process, builds no job and reads no queue.

The frames are a *preview*: downscaled and frame-exact, not the original.  ``Open`` on the recent-outputs
panel hands the original file to the system player.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

from PIL import Image, ImageTk

from src.gui.ui_dispatcher import TkUiDispatcher
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.view_contracts.video_preview_contract import STATE_PLAYING, VideoPreviewSession
from src.utils.thread_registry import get_thread_registry
from src.video.review_preview import PreviewResult, prepare_review_preview

HIDDEN_POLL_MS = 250


def _default_decode(path: str, cancel: threading.Event) -> PreviewResult:
    return prepare_review_preview(path, cancel=cancel)


class VideoPreviewWidget(ttk.Frame):
    """A looping preview of one clip, loaded with ``show`` and released with ``stop``."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        decode: Any = None,
        edge: int = 256,
        scale: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._scale = max(1, int(scale))
        side = max(64, int(edge)) * self._scale
        self._closed = False
        self._tick_id: str | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._runner: BackgroundWorkRunner | None = None
        self._decode = decode or _default_decode
        self.caption_var = tk.StringVar(value="")
        self.canvas = tk.Canvas(self, width=side, height=side, highlightthickness=1)
        self.canvas.grid(row=0, column=0)
        self.caption = ttk.Label(
            self,
            textvariable=self.caption_var,
            style="Page.Muted.TLabel",
            justify="left",
            wraplength=side,
        )
        self.caption.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.session = VideoPreviewSession(
            decode=self._decode, runner=self._work_runner(), on_change=self._on_session_change
        )
        self.caption_var.set(self.session.message)
        self.bind("<Destroy>", self._on_destroy, add="+")

    # ------------------------------------------------------------------ public

    def show(self, path: str) -> None:
        """Load and loop the clip at ``path`` (decoded on a worker)."""

        if not self._closed:
            self.session.load(path)

    def stop(self) -> None:
        if not self._closed:
            self.session.stop()

    # ------------------------------------------------------------------ internals

    def _work_runner(self) -> BackgroundWorkRunner:
        if self._runner is None:
            dispatcher = TkUiDispatcher(self.winfo_toplevel())
            self._runner = BackgroundWorkRunner(
                spawn=lambda name, target: get_thread_registry().spawn(
                    target=target,
                    name=name,
                    daemon=False,
                    purpose="Decode a bounded preview of a finished video without blocking Tk",
                ),
                dispatch=lambda fn: dispatcher.invoke(lambda: self._deliver(fn)),
            )
        return self._runner

    def _deliver(self, finish: Any) -> None:
        if self._closed:
            return
        try:
            if self.winfo_exists():
                finish()
        except tk.TclError:
            pass  # the widget tree is going away

    def _on_session_change(self) -> None:
        if self._closed:
            return
        self._cancel_tick()
        try:
            self.caption_var.set(self.session.message)
            if self.session.state == STATE_PLAYING:
                self._render(0)
                self._schedule_tick()
            else:
                self.canvas.delete("all")
                self._photo = None
        except tk.TclError:
            pass

    def _render(self, index: int) -> None:
        clip = self.session.clip
        if clip is None:
            return
        frame = clip.frame_image(index)
        if self._scale > 1:
            frame = frame.resize(
                (frame.width * self._scale, frame.height * self._scale), Image.Resampling.BILINEAR
            )
        self._photo = ImageTk.PhotoImage(frame)  # the only decoded frame the Tk side keeps
        self.canvas.delete("all")
        self.canvas.create_image(
            int(self.canvas.cget("width")) // 2,
            int(self.canvas.cget("height")) // 2,
            image=self._photo,
            anchor="center",
        )

    def _schedule_tick(self, delay: int | None = None) -> None:
        if self._closed:
            return
        try:
            self._tick_id = self.after(
                self.session.interval_ms if delay is None else delay, self._tick
            )
        except tk.TclError:
            self._tick_id = None

    def _cancel_tick(self) -> None:
        tick_id, self._tick_id = self._tick_id, None
        if tick_id is not None:
            try:
                self.after_cancel(tick_id)
            except tk.TclError:
                pass

    def _tick(self) -> None:
        self._tick_id = None
        if self._closed or self.session.state != STATE_PLAYING:
            return
        try:
            if not self.winfo_ismapped():
                self._schedule_tick(HIDDEN_POLL_MS)  # a hidden tab repaints nothing
                return
            self._render(self.session.advance())
        except tk.TclError:
            return
        self._schedule_tick()

    def _on_destroy(self, event: Any = None) -> None:
        if event is not None and event.widget is not self:
            return
        self._closed = True
        self._cancel_tick()
        self.session.close()  # cancels the decode in flight and releases the clip
        self._photo = None


__all__ = ["VideoPreviewWidget"]
