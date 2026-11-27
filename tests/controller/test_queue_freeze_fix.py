"""Add to Queue must hand submission to a background thread, so the GUI thread never waits for it."""

import threading

from src.controller.app_controller import AppController


class _BlockedSubmission:
    """A pipeline controller whose submission does not finish until the test lets it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.thread_name = ""

    def enqueue_draft_jobs(self, *, run_config=None) -> int:
        self.thread_name = threading.current_thread().name
        self.entered.set()
        self.release.wait(30.0)
        self.finished.set()
        return 0


def test_on_add_to_queue_runs_async():
    """on_add_to_queue returns while the submission is still blocked, on another thread."""
    controller = AppController(main_window=None, threaded=False)
    submission = _BlockedSubmission()
    controller.pipeline_controller = submission
    try:
        controller.on_add_to_queue()

        assert not submission.finished.is_set(), "on_add_to_queue waited for the submission"
        assert submission.entered.wait(10.0), "the submission never started"
        assert submission.thread_name != threading.current_thread().name
    finally:
        submission.release.set()
    assert submission.finished.wait(10.0)
