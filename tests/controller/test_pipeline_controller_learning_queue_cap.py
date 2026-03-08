from __future__ import annotations

from unittest.mock import Mock

from src.controller.pipeline_controller import PipelineController
from tests.helpers.job_helpers import make_test_njr


def _build_controller_with_queue(depth: int) -> PipelineController:
    controller = PipelineController.__new__(PipelineController)
    queue = Mock()
    queue.qsize.return_value = depth
    service = Mock()
    service.queue = queue
    controller._job_service = service
    controller._learning_queue_cap = 3
    return controller


def test_can_enqueue_learning_jobs_under_cap() -> None:
    controller = _build_controller_with_queue(depth=1)
    ok, reason = controller.can_enqueue_learning_jobs(1)
    assert ok is True
    assert reason == ""


def test_can_enqueue_learning_jobs_over_cap() -> None:
    controller = _build_controller_with_queue(depth=3)
    ok, reason = controller.can_enqueue_learning_jobs(1)
    assert ok is False
    assert "queue cap exceeded" in reason


def test_submit_normalized_jobs_blocks_learning_source_when_cap_exceeded() -> None:
    controller = _build_controller_with_queue(depth=3)
    controller._sort_jobs_by_model = lambda rows: rows
    controller._to_queue_job = Mock()
    controller._log_add_to_queue_event = Mock()
    controller._learning_enabled = False
    controller._last_run_config = None

    count = controller._submit_normalized_jobs(
        [make_test_njr(prompt_source="manual", prompt_pack_id="")],
        source="learning_auto_micro",
        prompt_source="manual",
    )
    assert count == 0
    controller._to_queue_job.assert_not_called()
    controller._job_service.submit_job_with_run_mode.assert_not_called()


def test_submit_normalized_jobs_allows_learning_source_under_cap() -> None:
    controller = _build_controller_with_queue(depth=1)
    controller._sort_jobs_by_model = lambda rows: rows
    controller._log_add_to_queue_event = Mock()
    controller._learning_enabled = False
    controller._last_run_config = None

    fake_job = Mock()
    fake_job.payload = None
    controller._to_queue_job = Mock(return_value=fake_job)

    count = controller._submit_normalized_jobs(
        [make_test_njr(prompt_source="manual", prompt_pack_id="")],
        source="learning_auto_micro",
        prompt_source="manual",
    )
    assert count == 1
    controller._job_service.submit_job_with_run_mode.assert_called_once_with(fake_job)
