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
    service.submit_njrs.return_value = ["job-1"]
    controller._job_service = service
    controller._learning_queue_cap = 3
    controller._app_controller = None
    controller._last_run_config = None
    controller._sort_jobs_by_model = lambda rows: rows
    controller._is_queue_submission_blocked = lambda: False
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
    record = make_test_njr(prompt_source="learning", prompt_pack_id="")

    count = controller._submit_normalized_jobs([record], source="learning_auto_micro")

    assert count == 0
    controller._job_service.submit_njrs.assert_not_called()


def test_submit_normalized_jobs_submits_learning_njr_once() -> None:
    controller = _build_controller_with_queue(depth=1)
    record = make_test_njr(prompt_source="learning", prompt_pack_id="")

    count = controller._submit_normalized_jobs([record], source="learning_auto_micro")

    assert count == 1
    controller._job_service.submit_njrs.assert_called_once()
