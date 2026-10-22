"""PR-VID-UX-314: the bounded, asynchronous, looping in-app video preview.

The contract tests use a manual runner (work and delivery are triggered by the test).  The widget tests use
the production ``ThreadRegistry`` worker and ``TkUiDispatcher`` with a real, tiny FFmpeg ``testsrc`` clip
generated on the CPU.  No GPU, Comfy process, model or network is involved.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Any

import pytest

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.gui.view_contracts.video_preview_contract import (
    MAX_PLAYBACK_FPS,
    MIN_TICK_MS,
    STATE_FAILED,
    STATE_IDLE,
    STATE_LOADING,
    STATE_PLAYING,
    VideoPreviewSession,
)
from src.gui.widgets.video_preview_widget_v2 import VideoPreviewWidget
from src.video.review_preview import (
    MAX_PREVIEW_BYTES,
    MAX_PREVIEW_FRAMES,
    PreviewClip,
    PreviewResult,
    prepare_review_preview,
)
from tests.helpers.video_review_211 import FFMPEG_AVAILABLE, make_clip


class _ManualRunner(BackgroundWorkRunner):
    """Collects (work, deliver) pairs so a test decides when each runs."""

    def __init__(self) -> None:
        self.queue: list[tuple[Any, Any]] = []
        super().__init__(
            spawn=lambda name, target: self.queue.append(target), dispatch=lambda fn: fn()
        )

    def run_all(self) -> None:
        while self.queue:
            self.queue.pop(0)()


def _clip(frames: int = 4, fps: float | None = 12.0, name: str = "x.mp4") -> PreviewClip:
    width, height = 4, 2
    return PreviewClip(
        path=name,
        width=width,
        height=height,
        source_width=width * 8,
        source_height=height * 8,
        fps=fps,
        frame_count=frames,
        reported_frame_count=frames,
        duration_seconds=frames / (fps or 24.0),
        raw=bytes(range(frames)) * (width * height * 3),
    )


def _ok(path: str, clip: PreviewClip | None = None) -> PreviewResult:
    return PreviewResult(path=path, status="ok", clip=clip or _clip(name=path))


# ------------------------------------------------------------------ session contract (no Tk)


def test_loading_decodes_only_on_the_worker_and_never_on_the_calling_thread() -> None:
    seen: list[int] = []

    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        seen.append(threading.get_ident())
        return _ok(path)

    runner = _ManualRunner()
    session = VideoPreviewSession(decode=decode, runner=runner)
    session.load("a.mp4")
    assert session.state == STATE_LOADING and seen == []  # nothing decoded on the caller's thread

    worker = threading.Thread(target=runner.run_all)
    worker.start()
    worker.join()
    assert seen and seen[0] != threading.get_ident()
    assert session.state == STATE_PLAYING and session.clip is not None


def test_a_newer_load_makes_the_older_result_stale_and_releases_its_cancel_event() -> None:
    cancels: list[threading.Event] = []

    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        cancels.append(cancel)
        return _ok(path)

    runner = _ManualRunner()
    session = VideoPreviewSession(decode=decode, runner=runner)
    session.load("first.mp4")
    session.load("second.mp4")
    assert len(runner.queue) == 2
    runner.run_all()
    assert cancels[0].is_set() and not cancels[1].is_set()  # the superseded decode was told to stop
    assert (
        session.clip is not None and session.clip.path == "second.mp4"
    )  # only the current clip is held


def test_stop_and_close_cancel_the_decode_and_drop_late_results() -> None:
    cancels: list[threading.Event] = []
    changes: list[str] = []
    runner = _ManualRunner()
    session = VideoPreviewSession(
        decode=lambda path, cancel: (cancels.append(cancel), _ok(path))[1],
        runner=runner,
        on_change=lambda: changes.append(session.state),
    )
    session.load("a.mp4")
    session.stop()
    runner.run_all()
    assert cancels[0].is_set() and session.state == STATE_IDLE and session.clip is None

    session.load("b.mp4")
    session.close()
    seen = len(changes)
    runner.run_all()
    assert len(changes) == seen and session.clip is None  # a closed session is never touched again
    session.load("c.mp4")
    assert runner.queue == []  # and starts nothing


def test_a_failed_or_empty_decode_is_a_visible_state_not_an_exception() -> None:
    runner = _ManualRunner()
    failed = PreviewResult(path="a.mp4", status="failed", message="FFmpeg was not found.")
    session = VideoPreviewSession(decode=lambda p, c: failed, runner=runner)
    session.load("a.mp4")
    runner.run_all()
    assert session.state == STATE_FAILED and "FFmpeg was not found" in session.message

    def explode(path: str, cancel: threading.Event) -> PreviewResult:
        raise RuntimeError("decoder crashed")

    session = VideoPreviewSession(decode=explode, runner=runner)
    session.load("b.mp4")
    runner.run_all()
    assert session.state == STATE_FAILED and "decoder crashed" in session.message

    session.load("")
    assert session.state == STATE_IDLE


def test_playback_loops_over_the_decoded_frames_at_a_capped_rate() -> None:
    runner = _ManualRunner()
    session = VideoPreviewSession(
        decode=lambda p, c: _ok(p, _clip(frames=3, fps=12.0)), runner=runner
    )
    assert (
        session.interval_ms == MIN_TICK_MS and session.advance() == 0
    )  # nothing loaded: nothing to advance
    session.load("a.mp4")
    runner.run_all()
    assert [session.advance() for _ in range(7)] == [1, 2, 0, 1, 2, 0, 1]
    assert session.interval_ms == 83  # 12 fps

    runner = _ManualRunner()
    session = VideoPreviewSession(decode=lambda p, c: _ok(p, _clip(fps=240.0)), runner=runner)
    session.load("fast.mp4")
    runner.run_all()
    assert session.interval_ms == round(
        1000 / MAX_PLAYBACK_FPS
    )  # never repaints faster than Tk can


# ------------------------------------------------------------------ the decoder's own bounds


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg/FFprobe are not installed")
def test_a_long_clip_is_decoded_within_the_frame_and_byte_bounds(tmp_path: Path) -> None:
    clip = make_clip(tmp_path, "long.mp4", frames=MAX_PREVIEW_FRAMES + 40, rate=30, size="320x240")
    result = prepare_review_preview(clip)
    assert result.ok and result.clip is not None
    preview = result.clip
    assert preview.frame_count == MAX_PREVIEW_FRAMES  # never the whole clip
    assert len(preview.raw) <= MAX_PREVIEW_BYTES
    assert max(preview.width, preview.height) <= 256  # downscaled inside FFmpeg


# ------------------------------------------------------------------ the Tk widget


@pytest.fixture
def shown_root(tk_root):
    tk_root.deiconify()
    try:
        yield tk_root
    finally:
        tk_root.withdraw()


def _pump_until(root: tk.Misc, predicate, timeout: float = 15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.gui
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg/FFprobe are not installed")
def test_the_widget_decodes_off_the_gui_thread_and_loops_one_frame_at_a_time(
    shown_root, tmp_path
) -> None:
    clip = make_clip(tmp_path, "tiny.mp4", frames=12, rate=24, size="64x48")
    decode_threads: list[int] = []

    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        decode_threads.append(threading.get_ident())
        return prepare_review_preview(path, cancel=cancel)

    widget = VideoPreviewWidget(shown_root, decode=decode, edge=128)
    widget.pack()
    try:
        widget.show(str(clip))
        assert widget.session.state == STATE_LOADING
        assert _pump_until(shown_root, lambda: widget.session.state == STATE_PLAYING)
        assert decode_threads and all(t != threading.get_ident() for t in decode_threads)
        assert "Review preview" in widget.caption_var.get()

        assert _pump_until(
            shown_root, lambda: widget.session.position >= 3
        )  # frames advance on Tk's clock
        assert widget._photo is not None  # exactly one decoded frame is held for display
        assert len(widget.canvas.find_all()) == 1
        assert widget.session.clip is not None and widget.session.clip.frame_count == 12

        widget.stop()
        assert widget.session.clip is None and widget._photo is None
        assert widget.canvas.find_all() == ()
    finally:
        widget.destroy()


@pytest.mark.gui
def test_a_missing_file_shows_a_message_and_a_new_clip_replaces_the_previous_one(
    shown_root, tmp_path
) -> None:
    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        if "good" in path:
            return _ok(path)
        return PreviewResult(
            path=path, status="failed", message=f"The video file does not exist: {path}"
        )

    widget = VideoPreviewWidget(shown_root, decode=decode, edge=64)
    widget.pack()
    try:
        widget.show("good.mp4")
        assert _pump_until(shown_root, lambda: widget.session.state == STATE_PLAYING)
        widget.show(str(tmp_path / "missing.mp4"))
        assert _pump_until(shown_root, lambda: widget.session.state == STATE_FAILED)
        assert "does not exist" in widget.caption_var.get()
        assert (
            widget.session.clip is None and widget._photo is None
        )  # the previous clip was released
    finally:
        widget.destroy()


@pytest.mark.gui
def test_destroying_the_widget_during_a_decode_cancels_it_and_touches_nothing_afterwards(
    shown_root,
) -> None:
    started, release = threading.Event(), threading.Event()
    cancelled: list[bool] = []
    errors: list[BaseException] = []

    def decode(path: str, cancel: threading.Event) -> PreviewResult:
        started.set()
        release.wait(10)
        cancelled.append(cancel.is_set())
        return _ok(path)

    widget = VideoPreviewWidget(shown_root, decode=decode, edge=64)
    widget.pack()
    session = widget.session
    widget.show("slow.mp4")
    assert _pump_until(shown_root, started.is_set)
    widget.destroy()
    release.set()
    previous_hook = threading.excepthook
    threading.excepthook = lambda args: errors.append(args.exc_value)
    try:
        assert _pump_until(shown_root, lambda: bool(cancelled))
        for _ in range(20):  # let any late delivery run on the Tk thread
            shown_root.update()
            time.sleep(0.01)
    finally:
        threading.excepthook = previous_hook
    assert cancelled == [True]  # the decoder was told to stop
    assert session.clip is None and session.state in {
        STATE_LOADING,
        STATE_IDLE,
    }  # nothing was applied
    assert errors == []


@pytest.mark.gui
def test_a_hidden_widget_repaints_nothing(tk_root) -> None:
    widget = VideoPreviewWidget(tk_root, decode=lambda p, c: _ok(p), edge=64)
    widget.pack()  # the test root is withdrawn: the widget is never mapped
    try:
        widget.show("a.mp4")
        assert _pump_until(tk_root, lambda: widget.session.state == STATE_PLAYING)
        for _ in range(15):
            tk_root.update()
            time.sleep(0.02)
        assert (
            widget.session.position == 0 and widget._photo is not None
        )  # frame 0 only, no loop while hidden
    finally:
        widget.destroy()
