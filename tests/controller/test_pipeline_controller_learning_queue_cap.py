from __future__ import annotations

from types import SimpleNamespace
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
    controller._job_service._emit_queue_updated = Mock()

    fake_job = Mock()
    fake_job.payload = None
    controller._to_queue_job = Mock(return_value=fake_job)

    count = controller._submit_normalized_jobs(
        [make_test_njr(prompt_source="manual", prompt_pack_id="")],
        source="learning_auto_micro",
        prompt_source="manual",
    )
    assert count == 1
    controller._job_service.submit_job_with_run_mode.assert_called_once_with(
        fake_job,
        emit_queue_updated=False,
    )
    controller._job_service._emit_queue_updated.assert_called_once_with()


def test_submit_normalized_jobs_coalesces_queue_state_notifications() -> None:
    controller = _build_controller_with_queue(depth=1)
    controller._sort_jobs_by_model = lambda rows: rows
    controller._log_add_to_queue_event = Mock()
    controller._learning_enabled = False
    controller._last_run_config = None
    controller._job_service._emit_queue_updated = Mock()

    batch_entries: list[str] = []

    class QueueBatchSpy:
        def coalesce_state_notifications(self):
            class _Context:
                def __enter__(self_inner):
                    batch_entries.append("enter")
                    return self_inner

                def __exit__(self_inner, exc_type, exc, tb):
                    batch_entries.append("exit")
                    return False

            return _Context()

    controller._job_service.job_queue = QueueBatchSpy()

    fake_jobs = [Mock(payload=None), Mock(payload=None)]
    controller._to_queue_job = Mock(side_effect=fake_jobs)

    count = controller._submit_normalized_jobs(
        [
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-a"),
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-b"),
        ],
        source="gui",
        prompt_source="manual",
    )

    assert count == 2
    assert batch_entries == ["enter", "exit"]
    assert controller._job_service.submit_job_with_run_mode.call_count == 2


def test_submit_normalized_jobs_stops_when_shutdown_starts_mid_batch() -> None:
    controller = _build_controller_with_queue(depth=1)
    controller._sort_jobs_by_model = lambda rows: rows
    controller._log_add_to_queue_event = Mock()
    controller._learning_enabled = False
    controller._last_run_config = None
    controller._job_service._emit_queue_updated = Mock()
    controller._app_controller = SimpleNamespace(_is_shutting_down=False)

    fake_jobs = [Mock(payload=None), Mock(payload=None), Mock(payload=None)]
    controller._to_queue_job = Mock(side_effect=fake_jobs)

    submitted_jobs: list[Mock] = []

    def _submit(job, emit_queue_updated=False):
        submitted_jobs.append(job)
        controller._app_controller._is_shutting_down = True

    controller._job_service.submit_job_with_run_mode.side_effect = _submit

    count = controller._submit_normalized_jobs(
        [
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-a"),
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-b"),
            make_test_njr(prompt_source="manual", prompt_pack_id="pack-c"),
        ],
        source="gui",
        prompt_source="manual",
    )

    assert count == 1
    assert submitted_jobs == [fake_jobs[0]]
    assert controller._to_queue_job.call_count == 1
    controller._job_service._emit_queue_updated.assert_called_once_with()
