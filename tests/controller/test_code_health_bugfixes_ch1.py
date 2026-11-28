"""CODE-HEALTH bug-fix package: regressions for defects found by the AppController/executor review.

(a) the top-bar Stop cancels the running job through the running-job panel's own cancel path;
(b) a cancelled job's running row reads "Stopping..." until the runner releases it (display only);
(c) the global prompt policy falls back to the saved settings when the sidebar has none;
(d) Movie Clips (and every video submission that reads ``AppController.output_dir``) honours the saved output folder.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController
from src.controller.app_controller_services.stopping_display import STOPPING_LABEL, StoppingDisplay
from src.controller.job_service import JobService
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from tests.helpers.job_helpers import make_test_job_from_njr, make_test_njr


class _Runner:
    def __init__(self) -> None:
        self.current_job: Job | None = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_running(self) -> bool:
        return False

    def run_once(self, job: Job) -> dict[str, object]:
        return {}

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        pass


class _SpyJobService(JobService):
    def __init__(self, job_queue: JobQueue, runner: _Runner) -> None:
        super().__init__(job_queue, runner)
        self.cancel_calls: list[bool] = []

    def cancel_current(self, *, return_to_queue: bool = False) -> None:  # type: ignore[override]
        self.cancel_calls.append(return_to_queue)


def _controller() -> tuple[AppController, _SpyJobService, _Runner]:
    runner = _Runner()
    service = _SpyJobService(JobQueue(), runner)
    return AppController(None, job_service=service), service, runner


def _running_job() -> Job:
    job = make_test_job_from_njr(make_test_njr())
    job.status = JobStatus.RUNNING
    return job


# (a) ---------------------------------------------------------------------------------------------------------


def test_top_bar_stop_cancels_the_running_job_through_the_panel_cancel_path(monkeypatch) -> None:
    controller, service, runner = _controller()
    runner.current_job = _running_job()
    panel_path_calls: list[None] = []
    original = controller.on_cancel_current_job

    def _spy() -> None:
        panel_path_calls.append(None)
        original()

    monkeypatch.setattr(controller, "on_cancel_current_job", _spy)

    controller.on_stop_clicked()

    assert panel_path_calls == [None]
    assert service.cancel_calls == [False]


def test_top_bar_stop_with_nothing_running_cancels_nothing() -> None:
    controller, service, _runner = _controller()

    controller.on_stop_clicked()

    assert service.cancel_calls == []


# (b) ---------------------------------------------------------------------------------------------------------


def test_cancelled_job_keeps_a_stopping_row_until_the_runner_releases_it(monkeypatch) -> None:
    controller, service, runner = _controller()
    job = _running_job()
    runner.current_job = job
    scheduled: list[Any] = []
    controller.main_window = SimpleNamespace(
        run_in_main_thread=lambda fn: fn(),
        run_in_main_thread_later=lambda _delay, fn: scheduled.append(fn),
    )

    def _cancel_commits_cancelled(*, return_to_queue: bool = False) -> None:
        # The queue's guarded durable CANCELLED is announced before the backend has stopped.
        job.status = JobStatus.CANCELLED
        controller._on_job_failed(job)

    monkeypatch.setattr(service, "cancel_current", _cancel_commits_cancelled)

    controller.on_cancel_current_job()

    row = controller.app_state.running_job
    assert row is not None and row.job_id == job.job_id
    assert row.status == STOPPING_LABEL
    assert scheduled, "the release check must be deferred while the runner still holds the job"

    scheduled.pop()()  # the runner still holds the job: the row stays and another check is queued
    assert controller.app_state.running_job is not None
    assert controller.app_state.running_job.status == STOPPING_LABEL

    runner.current_job = None  # the backend stopped and the worker released the job
    scheduled.pop()()
    assert controller.app_state.running_job is None
    assert job.status == JobStatus.CANCELLED  # the durable status is untouched


def test_stopping_display_releases_at_once_without_a_deferred_scheduler() -> None:
    job = _running_job()
    published: list[Any] = []
    display = StoppingDisplay(
        current_runner_job=lambda: job,
        publish_running_job=published.append,
        schedule_later=lambda _delay, _fn: False,
    )

    display.begin()
    assert display.holds(job)
    assert published == [job]

    assert display.keeps_row(job) is False  # nothing can re-check later: behave as before
    assert not display.holds(job)


def test_stopping_display_treats_an_inline_scheduler_as_no_deferral() -> None:
    """The main window runs a "later" callback at once when it has no Tk root; that must not recurse."""
    job = _running_job()
    published: list[Any] = []

    def _inline(_delay: int, fn: Any) -> bool:
        fn()
        return True

    display = StoppingDisplay(
        current_runner_job=lambda: job, publish_running_job=published.append, schedule_later=_inline
    )

    display.begin()

    assert published == [job]
    assert display.keeps_row(job) is False


def test_stopping_display_ignores_other_jobs() -> None:
    job = _running_job()
    other = _running_job()
    display = StoppingDisplay(
        current_runner_job=lambda: job,
        publish_running_job=lambda _job: None,
        schedule_later=lambda _delay, _fn: True,
    )

    display.begin()

    assert display.keeps_row(other) is False
    assert display.keeps_row(job) is True


# (c) ---------------------------------------------------------------------------------------------------------


class _SavedPolicy:
    def get_global_positive_enabled(self) -> bool:
        return True

    def get_global_positive_prompt(self) -> str:
        return "saved positive"

    def get_global_negative_enabled(self) -> bool:
        return True

    def get_global_negative_prompt(self) -> str:
        return "saved negative"


def test_global_prompt_policy_falls_back_to_the_saved_settings(monkeypatch) -> None:
    controller, _service, _runner = _controller()
    monkeypatch.setattr(controller, "_config_manager", _SavedPolicy())
    monkeypatch.setattr(controller, "_get_sidebar_panel", lambda: None)

    policy = controller.get_current_global_prompt_policy()

    assert policy["positive_enabled"] is True
    assert policy["positive_text"] == "saved positive"
    assert policy["negative_text"] == "saved negative"


# (d) ---------------------------------------------------------------------------------------------------------


class _Settings:
    def __init__(self, output_dir: Any) -> None:
        self._output_dir = output_dir

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._output_dir if key == "output_dir" else default


def test_output_dir_is_the_saved_output_folder(monkeypatch) -> None:
    controller, _service, _runner = _controller()
    monkeypatch.setattr(controller, "_config_manager", _Settings("  D:/custom_out  "))
    assert controller.output_dir == "D:/custom_out"

    monkeypatch.setattr(controller, "_config_manager", _Settings("  "))
    assert (
        controller.output_dir is None
    )  # an install that never set one keeps each caller's default


def test_movie_clips_use_the_saved_output_folder(monkeypatch) -> None:
    controller, _service, _runner = _controller()
    monkeypatch.setattr(controller, "_config_manager", _Settings("D:/custom_out"))
    captured: dict[str, Any] = {}

    class _Service:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def submit_in_background(self, *_args: Any, **_kwargs: Any) -> None:
            pass

    monkeypatch.setattr(
        "src.controller.movie_clips_submission_service.MovieClipsSubmissionService", _Service
    )

    controller.on_build_movie_clip(["a.png"], {})

    assert captured["output_dir"] == "D:/custom_out"
