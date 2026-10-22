"""Toolkit-neutral state of the in-app looping video preview (PR-VID-UX-314).

``VideoPreviewSession`` owns one question: which clip is being previewed and which frame is next.  It
performs no I/O and imports no Tk.  Decoding is an injected callable that the injected
``BackgroundWorkRunner`` runs on an owned worker; the outcome comes back on the UI thread and is ignored
when it went stale.

Rules (each has a test):

* a clip is decoded only through ``decode`` on the worker, never on the UI thread;
* memory is bounded by the decoder: one clip is at most ``MAX_PREVIEW_BYTES`` of raw frames, and the session
  holds exactly one clip, so starting another (or ``stop``/``close``) releases the previous one;
* loading a new clip, stopping or closing cancels the decode in flight and makes its late result a no-op, so
  a destroyed widget is never touched;
* a failed or empty decode is a visible state with an operator-readable message, never an exception.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.video.review_preview import PreviewClip, PreviewResult, describe_preview

STATE_IDLE = "idle"
STATE_LOADING = "loading"
STATE_PLAYING = "playing"
STATE_FAILED = "failed"

#: Playback is capped so a high-frame-rate clip never asks Tk to repaint faster than it can.
MAX_PLAYBACK_FPS = 30.0
MIN_TICK_MS = 20

Decode = Callable[[str, threading.Event], PreviewResult]


@dataclass(frozen=True)
class PreviewView:
    """What the widget shows: a state and one honest line of text."""

    state: str
    message: str


class VideoPreviewSession:
    def __init__(
        self,
        *,
        decode: Callable[[str, threading.Event], PreviewResult],
        runner: BackgroundWorkRunner,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._decode = decode
        self._runner = runner
        self._on_change = on_change
        self._cancel = threading.Event()
        self._token = 0
        self._closed = False
        self.path = ""
        self.state = STATE_IDLE
        self.message = "Select a clip to preview it."
        self.clip: PreviewClip | None = None
        self.position = 0

    # ------------------------------------------------------------------ queries

    @property
    def view(self) -> PreviewView:
        return PreviewView(self.state, self.message)

    @property
    def interval_ms(self) -> int:
        """Milliseconds between frames at the clip's own rate (capped), or the minimum tick."""

        if self.clip is None:
            return MIN_TICK_MS
        fps = min(max(self.clip.effective_fps, 1.0), MAX_PLAYBACK_FPS)
        return max(MIN_TICK_MS, int(round(1000.0 / fps)))

    @property
    def frame_count(self) -> int:
        return self.clip.frame_count if self.clip is not None else 0

    # ------------------------------------------------------------------ commands (UI thread)

    def load(self, path: str) -> None:
        """Start decoding ``path`` on the worker; whatever was loading or playing is released first."""

        if self._closed:
            return
        text = str(path or "").strip()
        self._release()
        if not text:
            self._set(STATE_IDLE, "Select a clip to preview it.")
            return
        self.path = text
        self._set(STATE_LOADING, f"Preparing preview of {Path(text).name}...")
        token, cancel = self._token, self._cancel
        decode = self._decode
        self._runner.start(
            "video-recent-output-preview",
            lambda: WorkOutcome(value=decode(text, cancel)),
            lambda outcome: self._finish(token, text, outcome),
        )

    def stop(self) -> None:
        """Release the clip and cancel any decode; the next ``load`` starts clean."""

        if self._closed:
            return
        self._release()
        self.path = ""
        self._set(STATE_IDLE, "Select a clip to preview it.")

    def close(self) -> None:
        """Final: nothing delivered afterwards touches the session or its owner."""

        self._release()
        self._closed = True
        self._on_change = None

    def advance(self) -> int:
        """The next frame index of the loop (wraps to the first frame)."""

        if self.clip is None or self.clip.frame_count < 1:
            return 0
        self.position = (self.position + 1) % self.clip.frame_count
        return self.position

    # ------------------------------------------------------------------ internals

    def _release(self) -> None:
        self._cancel.set()  # the decode in flight, if any, stops and its result is stale
        self._cancel = threading.Event()
        self._token += 1
        self.clip = None
        self.position = 0

    def _finish(self, token: int, path: str, outcome: WorkOutcome) -> None:
        if self._closed or token != self._token:
            return
        result = outcome.value
        if outcome.error or not isinstance(result, PreviewResult):
            self._set(STATE_FAILED, outcome.error or "The preview could not be prepared.")
            return
        if not result.ok or result.clip is None:
            self._set(STATE_FAILED, result.message or "No preview could be decoded for this clip.")
            return
        self.clip = result.clip
        self.position = 0
        self._set(STATE_PLAYING, describe_preview(result.clip))

    def _set(self, state: str, message: str) -> None:
        self.state, self.message = state, message
        callback = self._on_change
        if callback is not None:
            callback()


__all__ = [
    "MAX_PLAYBACK_FPS",
    "MIN_TICK_MS",
    "STATE_FAILED",
    "STATE_IDLE",
    "STATE_LOADING",
    "STATE_PLAYING",
    "Decode",
    "PreviewView",
    "VideoPreviewSession",
]
