"""RUN-LEAN: jobs queued with nothing running leave a record saying why."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from src.queue.job_queue import JobQueue
from src.services.queue_idle_report import QueueIdleReporter
from src.services.watchdog_system_v2 import SystemWatchdogV2
from tests.helpers.job_helpers import make_test_job_from_njr, make_test_njr


def _service(*, auto_run: bool = True, worker: bool = True, jobs: int = 2) -> SimpleNamespace:
    queue = JobQueue()
    for index in range(jobs):
        queue.submit(make_test_job_from_njr(make_test_njr(job_id=f"idle-{index}")))
    return SimpleNamespace(
        job_queue=queue,
        auto_run_enabled=auto_run,
        runner=SimpleNamespace(is_running=lambda: worker),
    )


def _records(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "QUEUE_IDLE" in r.getMessage()]


def test_nothing_is_reported_before_a_minute_of_idleness(caplog) -> None:
    reporter, service = QueueIdleReporter(), _service()

    with caplog.at_level(logging.INFO):
        reporter.observe(1000.0, service)
        reporter.observe(1059.0, service)

    assert _records(caplog) == []


def test_a_paused_queue_is_reported_once_with_its_reason_and_again_when_it_resumes(caplog) -> None:
    reporter, service = QueueIdleReporter(), _service()
    service.job_queue.pause()

    with caplog.at_level(logging.INFO):
        for now in (1000.0, 1061.0, 1100.0):
            reporter.observe(now, service)
        service.job_queue.resume()
        service.job_queue.claim_next_job()
        reporter.observe(1200.0, service)

    first, last = _records(caplog)
    assert "2 job(s) queued" in first and "the queue is paused" in first
    assert last.startswith("QUEUE_IDLE_END")


def test_the_reason_names_what_is_stopping_dispatch(caplog) -> None:
    cases = [
        (_service(auto_run=False), None, "auto-run is off"),
        (_service(worker=False), None, "no queue worker is running"),
        (_service(), SimpleNamespace(_deferred_autostart=True), "waiting for the WebUI"),
        (_service(), None, "has not started a job"),
    ]
    held = _service()
    held.job_queue.hold_dispatch_for_update(reason="update requested")
    cases.append((held, None, "held for an app update (update requested)"))

    for service, controller, expected in cases:
        caplog.clear()
        reporter = QueueIdleReporter()
        with caplog.at_level(logging.INFO):
            reporter.observe(0.0, service, controller)
            reporter.observe(61.0, service, controller)
        assert expected in _records(caplog)[0]


def test_an_empty_queue_is_never_idle(caplog) -> None:
    reporter, service = QueueIdleReporter(), _service(jobs=0)

    with caplog.at_level(logging.INFO):
        reporter.observe(0.0, service)
        reporter.observe(600.0, service)

    assert _records(caplog) == []


def test_the_system_watchdog_samples_the_queue() -> None:
    seen: list[tuple[object, object]] = []
    job_controller = object()
    app = SimpleNamespace(
        job_service=object(), pipeline_controller=SimpleNamespace(_job_controller=job_controller)
    )
    watchdog = SystemWatchdogV2(app, diagnostics_service=None)
    watchdog._queue_idle = SimpleNamespace(
        observe=lambda _now, service, ctl: seen.append((service, ctl))
    )
    watchdog._queue_running_but_stalled = lambda _now: False

    watchdog._check()

    assert seen == [(app.job_service, job_controller)]
