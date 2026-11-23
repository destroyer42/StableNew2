"""Compare-only synchronized playback of sibling takes' own clips (PR-VID-STORY-380, spec 7.2). Presentation only.

Built on ``ComparisonClock`` and the bounded review preview decode (at most 120 frames and 256 px per clip), so it plays the
siblings' own new clips, not their whole cuts. There is no rating and no evidence save: a storyboard's Keep / Drop marks
are the only judgement it keeps. Decoding runs on the work runner; the window drops late results after it closes.
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from PIL import ImageTk

from src.gui.view_contracts.edit_work_runner import build_edit_work_runner
from src.gui.view_contracts.video_review_contract import ClipTiming, ComparisonClock
from src.video.review_preview import PreviewClip, PreviewResult, prepare_review_preview

PLAYBACK_TICK_MS = 33


class _Side:
    def __init__(self, parent: ttk.Frame, label: str, column: int) -> None:
        self.label = label
        self.clip: PreviewClip | None = None
        self.photo: Any = None
        self.status = tk.StringVar(value="Decoding…")
        holder = ttk.Frame(parent)
        holder.grid(row=0, column=column, sticky="nsew", padx=4)
        ttk.Label(holder, text=label).pack(anchor="w")
        self.image_label = ttk.Label(holder, anchor="center")
        self.image_label.pack()
        ttk.Label(holder, textvariable=self.status, wraplength=300).pack(anchor="w")


class StoryboardCompareWindowV2(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        clips: Sequence[tuple[str, str]],
        preview_fn: Callable[..., PreviewResult] = prepare_review_preview,
    ) -> None:
        super().__init__(parent)
        self.title("Compare takes side by side")
        self.clips: tuple[tuple[str, str], ...] = tuple(clips)
        self.clock = ComparisonClock()
        self.runner = build_edit_work_runner(self)
        self._preview_fn = preview_fn
        self._tick_id: str | None = None
        self._timings: list[ClipTiming] = []
        self._pending = len(self.clips)
        self.position_var = tk.StringVar(value="Decoding clips…")
        row = ttk.Frame(self)
        row.pack(fill="both", expand=True, padx=8, pady=8)
        self.sides = [_Side(row, label, column) for column, (label, _path) in enumerate(self.clips)]
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=8)
        self.restart_button = ttk.Button(controls, text="⏮", width=3, command=self._restart)
        self.back_button = ttk.Button(controls, text="◀", width=3, command=lambda: self._step(-1))
        self.play_button = ttk.Button(controls, text="Play", width=7, command=self.toggle_play)
        self.forward_button = ttk.Button(controls, text="▶", width=3, command=lambda: self._step(1))
        for button in (
            self.restart_button,
            self.back_button,
            self.play_button,
            self.forward_button,
        ):
            button.pack(side="left", padx=1)
            button.configure(state="disabled")
        self.slider = ttk.Scale(
            controls, from_=0, to=0, orient="horizontal", command=self._on_slide
        )
        self.slider.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(self, textvariable=self.position_var).pack(anchor="w", padx=8, pady=(0, 8))
        for index, (_label, path) in enumerate(self.clips):
            self._decode(index, path)

    def has_rating_controls(self) -> bool:
        return False

    # ------------------------------------------------------------------ decoding

    def _decode(self, index: int, path: str) -> None:
        preview_fn = self._preview_fn
        self.runner.submit(
            f"decode:{index}",
            lambda: preview_fn(path),
            on_result=lambda result: self._decoded(index, result),
            on_error=lambda error: self._decoded(index, None, str(error)),
        )

    def _decoded(self, index: int, result: PreviewResult | None, error: str = "") -> None:
        side = self.sides[index]
        if result is not None and result.ok and result.clip is not None:
            side.clip = result.clip
            side.status.set("")
        else:
            side.status.set(error or (result.message if result is not None else "No preview."))
        self._pending -= 1
        if self._pending <= 0:
            self._ready()

    def _ready(self) -> None:
        timings = [
            ClipTiming(
                side.label,
                side.clip.frame_count,
                side.clip.effective_fps,
                fps_assumed=side.clip.fps_is_assumed,
                reported_frame_count=side.clip.reported_frame_count,
            )
            for side in self.sides
            if side.clip is not None
        ]
        self._timings = timings
        self.clock.configure(timings)
        if not timings:
            self.position_var.set("None of these clips could be decoded.")
            return
        self.slider.configure(to=self.clock.last_position)
        for button in (
            self.restart_button,
            self.back_button,
            self.play_button,
            self.forward_button,
        ):
            button.configure(state="normal")
        notes = " ".join(self.clock.notes())
        self._render(notes)

    # ------------------------------------------------------------------ transport

    def _render(self, notes: str = "") -> None:
        timings = {timing.label: timing for timing in self._timings}
        for side in self.sides:
            timing = timings.get(side.label)
            if side.clip is None or timing is None:
                continue
            image = side.clip.frame_image(self.clock.frame_index(timing))
            side.photo = ImageTk.PhotoImage(image, master=self)
            side.image_label.configure(image=side.photo)
        text = self.clock.position_text(self._timings)
        self.position_var.set(f"{text}   {notes}".strip())
        self.slider.set(self.clock.position)

    def toggle_play(self) -> None:
        if self.clock.playing:
            self._pause()
            return
        self.clock.play(time.monotonic())
        self.play_button.configure(text="Pause")
        self._tick_id = self.after(PLAYBACK_TICK_MS, self._tick)

    def _pause(self) -> None:
        self.clock.pause()
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        self.play_button.configure(text="Play")

    def _tick(self) -> None:
        self._tick_id = None
        changed = self.clock.tick(time.monotonic())
        if changed:
            self._render()
        if self.clock.playing:
            self._tick_id = self.after(PLAYBACK_TICK_MS, self._tick)
        else:
            self.play_button.configure(text="Play")

    def _step(self, delta: int) -> None:
        self._pause()
        self.clock.step(delta)
        self._render()

    def _restart(self) -> None:
        self._pause()
        self.clock.restart()
        self._render()

    def _on_slide(self, value: str) -> None:
        position = round(float(value))
        if position != self.clock.position and self._timings_ready():
            self._pause()
            self.clock.seek(position)
            self._render()

    def _timings_ready(self) -> bool:
        return bool(self._timings)

    def destroy(self) -> None:
        self._pause()
        self.runner.close()
        super().destroy()


__all__ = ["StoryboardCompareWindowV2"]
