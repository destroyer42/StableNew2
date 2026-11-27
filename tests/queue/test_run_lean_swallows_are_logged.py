"""RUN-LEAN: failures that were silently ignored on the execution path are logged and still ignored."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner


def test_a_raising_status_handler_is_logged_with_the_job_id(caplog) -> None:
    def handler(job, status):
        raise RuntimeError("handler broke")

    runner = SingleNodeJobRunner(JobQueue(), lambda job: {}, on_status_change=handler)

    with caplog.at_level(logging.WARNING):
        runner._notify(SimpleNamespace(job_id="job-77"), JobStatus.COMPLETED)

    assert "job-77" in caplog.text and "handler broke" in caplog.text


def test_a_raising_queue_listener_is_logged_and_the_others_still_run(caplog) -> None:
    queue = JobQueue()
    seen: list[str] = []

    def broken():
        raise RuntimeError("listener broke")

    queue.register_state_listener(broken)
    queue.register_state_listener(lambda: seen.append("second"))

    with caplog.at_level(logging.WARNING):
        queue._notify_state_listeners()
        with queue.coalesce_state_notifications():
            queue._notify_state_listeners()

    assert seen == ["second", "second"]
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


def test_a_failed_pre_job_cleanup_is_logged_and_does_not_fail_the_job(caplog) -> None:
    def free_vram(**_kwargs):
        raise RuntimeError("cleanup broke")

    runner = SimpleNamespace(_pipeline=SimpleNamespace(client=SimpleNamespace(free_vram=free_vram)))

    with caplog.at_level(logging.WARNING):
        PipelineRunner._cleanup_at_job_start(runner, None, "", "job-88")

    assert "job-88" in caplog.text and "cleanup broke" in caplog.text
