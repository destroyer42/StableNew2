from __future__ import annotations

from unittest.mock import Mock

from src.controller.pipeline_controller import PipelineController


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

