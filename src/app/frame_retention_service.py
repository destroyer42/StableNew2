"""Run the video frame retention sweep in the background while the queue is empty (VID-FRAME).

The sweep itself and its protections are ``src/video/frame_retention.py``. Nothing is removed while a job is queued or
running (a waiting job may have frozen a frame as its input), when the queue cannot be read, or when the setting is off.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from src.review.archive import job_queue_of
from src.utils.config import ConfigManager
from src.utils.thread_registry import get_thread_registry
from src.video import storyboard_tree_store
from src.video.frame_retention import FrameSweep, sweep_retained_frames

logger = logging.getLogger(__name__)

SETTING_KEY = "video_frame_cleanup_enabled"
FIRST_RUN_MS = 5 * 60 * 1000
REPEAT_MS = 60 * 60 * 1000


def run_frame_retention(
    app: Any,
    *,
    setting: Callable[[str, Any], Any] | None = None,
    stopping: Callable[[], bool] = lambda: False,
) -> FrameSweep | None:
    """One sweep of the output folder, or ``None`` when it may not run now."""

    read = setting or ConfigManager().get_setting
    queue = job_queue_of(app)
    lister = getattr(queue, "list_active_jobs_ordered", None)
    if not callable(lister):
        return None

    def must_stop() -> bool:
        return stopping() or not read(SETTING_KEY, True) or bool(lister())

    if must_stop():
        return None
    output_root = getattr(app, "output_dir", None) or read("output_dir", "output") or "output"
    return sweep_retained_frames(
        output_root, tree_root=storyboard_tree_store.default_root(), should_stop=must_stop
    )


def schedule_frame_retention(root: Any, app: Any) -> Callable[[], None]:
    """Sweep five minutes after start and hourly after that; returns the call that stops it."""

    stop = threading.Event()
    running = threading.Lock()

    def work() -> None:
        try:
            run_frame_retention(app, stopping=stop.is_set)
        except Exception:  # noqa: BLE001 - retention is housekeeping; it must never affect the app
            logger.warning("The video frame cleanup failed", exc_info=True)
        finally:
            running.release()

    def tick() -> None:
        if stop.is_set():
            return
        if running.acquire(blocking=False):
            try:
                get_thread_registry().spawn(
                    target=work, name="VideoFrameRetention", purpose="Remove day-old video frames"
                )
            except RuntimeError:  # shutting down
                running.release()
                return
        root.after(REPEAT_MS, tick)

    root.after(FIRST_RUN_MS, tick)
    return stop.set


__all__ = ["SETTING_KEY", "run_frame_retention", "schedule_frame_retention"]
