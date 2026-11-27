"""Run the video frame retention sweep in the background while the queue is empty (VID-FRAME).

The sweep itself and its protections are ``src/video/frame_retention.py``. The rule ships on, but deletion cannot be
undone, so the first sweep waits for the operator: a dry run counts what would go and ``ask`` shows it with Delete now,
Not now and Turn off. After one Delete now, later sweeps run on schedule without asking. Nothing is removed while a job
is queued or running (a waiting job may have frozen a frame as its input), when the queue cannot be read, or when the
setting is off. All scheduling stays on the Tk thread; only the folder pass runs on a worker.
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
CONFIRMED_KEY = "video_frame_cleanup_confirmed"
CHOICE_DELETE_NOW = "delete_now"
CHOICE_NOT_NOW = "not_now"
CHOICE_TURN_OFF = "turn_off"
FIRST_RUN_MS = 5 * 60 * 1000
REPEAT_MS = 6 * 60 * 60 * 1000  # a pass walks the whole output folder (minutes on a large one)
POLL_MS = 1000

Ask = Callable[[FrameSweep, Callable[[str], None]], None]
Read = Callable[[str, Any], Any]


def run_frame_retention(
    app: Any,
    *,
    setting: Read | None = None,
    stopping: Callable[[], bool] = lambda: False,
    dry_run: bool = False,
) -> FrameSweep | None:
    """One pass over the output folder (counting only when ``dry_run``), or ``None`` when it may not run now."""

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
        output_root,
        tree_root=storyboard_tree_store.default_root(),
        should_stop=must_stop,
        dry_run=dry_run,
    )


def schedule_frame_retention(
    root: Any,
    app: Any,
    *,
    ask: Ask,
    setting: Read | None = None,
    save: Callable[[dict[str, Any]], Any] | None = None,
) -> Callable[[], None]:
    """Look five minutes after start and every six hours after that; returns the call that stops it."""

    config = ConfigManager()
    read = setting or config.get_setting
    write = save or config.update_settings
    stop = threading.Event()
    busy = threading.Lock()  # one folder pass at a time
    asked = threading.Event()  # at most one question per start of the application

    def start_pass(*, dry_run: bool) -> None:
        if stop.is_set() or not busy.acquire(blocking=False):
            return
        done = threading.Event()
        found: list[FrameSweep] = []

        def work() -> None:
            try:
                result = run_frame_retention(
                    app, setting=read, stopping=stop.is_set, dry_run=dry_run
                )
                if result is not None:
                    found.append(result)
            except Exception:  # noqa: BLE001 - retention is housekeeping; it must never affect the app
                logger.warning("The video frame cleanup failed", exc_info=True)
            finally:
                busy.release()
                done.set()

        def collect() -> None:  # on the Tk thread: a worker never touches Tk
            if stop.is_set():
                return
            if not done.is_set():
                root.after(POLL_MS, collect)
            elif dry_run and found and found[0].frames and not asked.is_set():
                asked.set()
                ask(found[0], choose)

        try:
            get_thread_registry().spawn(
                target=work, name="VideoFrameRetention", purpose="Remove day-old video frames"
            )
        except RuntimeError:  # shutting down
            busy.release()
            return
        if dry_run:
            root.after(POLL_MS, collect)

    def choose(choice: str) -> None:
        if choice == CHOICE_DELETE_NOW:
            write({CONFIRMED_KEY: True})
            start_pass(dry_run=False)
        elif choice == CHOICE_TURN_OFF:
            write({SETTING_KEY: False})

    def tick() -> None:
        if stop.is_set():
            return
        if read(SETTING_KEY, True):
            if read(CONFIRMED_KEY, False):
                start_pass(dry_run=False)
            elif not asked.is_set():
                start_pass(dry_run=True)
        root.after(REPEAT_MS, tick)

    root.after(FIRST_RUN_MS, tick)
    return stop.set


__all__ = [
    "CHOICE_DELETE_NOW",
    "CHOICE_NOT_NOW",
    "CHOICE_TURN_OFF",
    "CONFIRMED_KEY",
    "SETTING_KEY",
    "run_frame_retention",
    "schedule_frame_retention",
]
