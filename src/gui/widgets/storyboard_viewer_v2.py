"""Frame viewer with a whole-cut slider and join ticks for the Storyboard tab (PR-VID-STORY-380). Presentation only.

The viewer holds no frames: it asks its owner for frame ``index`` (``on_frame``), and the owner loads it on a worker and
calls :meth:`show_image`. Playback advances the index at the cut's fps; a frame that arrives late is dropped by the
owner's latest-wins runner, so scrubbing never blocks the UI.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

TICK_PAD = 12


class StoryboardViewerV2(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_frame: Callable[[int], None],
        on_continue: Callable[[int], None],
        readout: Callable[[int], str],
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._on_frame = on_frame
        self._on_continue = on_continue
        self._readout = readout
        self._count = 0
        self._joins: tuple[int, ...] = ()
        self._fps = 16.0
        self._index = 0
        self._after: str | None = None
        self._photo: Any = None
        self._syncing = False
        self.title_var = tk.StringVar(value="")
        self.readout_var = tk.StringVar(value="No cut selected")
        self.note_var = tk.StringVar(value="")
        self.columnconfigure(0, weight=1)
        ttk.Label(self, textvariable=self.title_var, style="Dark.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.image_label = ttk.Label(self, anchor="center")
        self.image_label.grid(row=1, column=0, sticky="nsew")
        self.rowconfigure(1, weight=1)
        self.tick_canvas = tk.Canvas(self, height=10, highlightthickness=0)
        self.tick_canvas.grid(row=2, column=0, sticky="ew", padx=TICK_PAD)
        self.tick_canvas.bind("<Configure>", lambda _e: self._draw_ticks())
        self.slider = ttk.Scale(self, from_=0, to=0, orient="horizontal", command=self._on_slide)
        self.slider.grid(row=3, column=0, sticky="ew")
        controls = ttk.Frame(self, style="Panel.TFrame")
        controls.grid(row=4, column=0, sticky="ew")
        self.prev_button = ttk.Button(controls, text="◀", width=3, command=lambda: self.step(-1))
        self.play_button = ttk.Button(controls, text="Play", width=6, command=self.toggle_play)
        self.next_button = ttk.Button(controls, text="▶", width=3, command=lambda: self.step(1))
        self.prev_button.pack(side="left")
        self.play_button.pack(side="left", padx=2)
        self.next_button.pack(side="left")
        ttk.Label(controls, textvariable=self.readout_var, style="Dark.TLabel").pack(
            side="left", padx=8
        )
        self.continue_button = ttk.Button(
            controls,
            text="Continue from this frame",
            style="Dark.TButton",
            command=lambda: self._on_continue(self._index),
        )
        self.continue_button.pack(side="right")
        ttk.Label(self, textvariable=self.note_var, style="Dark.TLabel", wraplength=520).grid(
            row=5, column=0, sticky="w"
        )

    # ------------------------------------------------------------------ cut

    @property
    def index(self) -> int:
        return self._index

    @property
    def frame_count(self) -> int:
        return self._count

    def set_cut(
        self,
        frame_count: int,
        joins: Sequence[int],
        fps: float,
        *,
        title: str = "",
        start_index: int | None = None,
    ) -> None:
        self.pause()
        self._count = max(0, frame_count)
        self._joins = tuple(joins)
        self._fps = float(fps) if fps > 0 else 16.0
        self.title_var.set(title)
        self._syncing = True
        try:
            self.slider.configure(to=max(0, self._count - 1))
        finally:
            self._syncing = False
        self._draw_ticks()
        state = "normal" if self._count else "disabled"
        for button in (self.prev_button, self.play_button, self.next_button, self.continue_button):
            button.configure(state=state)
        if self._count:
            self.seek(self._count - 1 if start_index is None else start_index)
        else:
            self._index = 0
            self.readout_var.set("No frames yet")

    def clear(self) -> None:
        self.set_cut(0, (), self._fps)
        self.image_label.configure(image="")
        self._photo = None

    def _draw_ticks(self) -> None:
        canvas = self.tick_canvas
        canvas.delete("all")
        if self._count < 2:
            return
        width = max(1, canvas.winfo_width())
        for join in self._joins:
            x = join / (self._count - 1) * (width - 1)
            canvas.create_line(x, 0, x, 10, tags=("tick",))

    # ------------------------------------------------------------------ position

    def seek(self, index: int) -> None:
        if not self._count:
            return
        self._index = max(0, min(self._count - 1, int(index)))
        self._syncing = True
        try:
            self.slider.set(self._index)
        finally:
            self._syncing = False
        self.readout_var.set(self._readout(self._index))
        self._on_frame(self._index)

    def _on_slide(self, value: str) -> None:
        if self._syncing:
            return
        self.pause()
        self.seek(round(float(value)))

    def step(self, delta: int) -> None:
        self.pause()
        self.seek(self._index + delta)

    def show_image(self, photo: Any) -> None:
        self._photo = photo
        self.image_label.configure(image=photo)

    # ------------------------------------------------------------------ playback

    @property
    def playing(self) -> bool:
        return self._after is not None

    def toggle_play(self) -> None:
        if self.playing:
            self.pause()
            return
        if not self._count:
            return
        if self._index >= self._count - 1:
            self.seek(0)
        self.play_button.configure(text="Pause")
        self._after = self.after(self._interval(), self._tick)

    def _interval(self) -> int:
        return max(15, int(1000 / self._fps))

    def _tick(self) -> None:
        self._after = None
        if self._index >= self._count - 1:
            self.play_button.configure(text="Play")
            return
        self.seek(self._index + 1)
        self._after = self.after(self._interval(), self._tick)

    def pause(self) -> None:
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        self.play_button.configure(text="Play")

    def destroy(self) -> None:
        self.pause()
        super().destroy()


__all__ = ["StoryboardViewerV2"]
