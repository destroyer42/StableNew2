"""Current-truth regressions for queue persistence and preview-to-queue submission."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from types import MethodType, SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController
from src.controller.job_execution_controller import JobExecutionController
from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job, JobPriority
from src.services.queue_store_v2 import QueueSnapshotV1


def _make_normalized_record(job_id: str) -> NormalizedJobRecord:
    record = NormalizedJobRecord(
        job_id=job_id,
        config={"prompt_pack_id": "pack-1", "model": "test-model"},
        path_output_dir="output",
        filename_template="{seed}",
        prompt_pack_id="pack-1",
        seed=42,
    )
    record.prompt_source = "pack"
    return record


@dataclass
class MockQueue:
    jobs: list[Job] = field(default_factory=list)
    restore_called: bool = False
    restored_jobs: list[Job] | None = None
    listeners: list[Any] = field(default_factory=list)

    def list_jobs(self) -> list[Job]:
        return list(self.jobs)

    def restore_jobs(self, jobs: list[Job]) -> None:
        self.restore_called = True
        self.restored_jobs = list(jobs)
        self.jobs.extend(jobs)

    def register_state_listener(self, callback: Any) -> None:
        self.listeners.append(callback)


class TestQueuePersistenceIntegrity:
    def test_restore_marks_deferred_autostart_without_starting_runner(self, monkeypatch) -> None:
        entry = {
            "queue_id": "test-job-1",
            "njr_snapshot": {"normalized_job": asdict(_make_normalized_record("test-job-1"))},
            "priority": 1,
            "status": "queued",
            "created_at": "2025-12-25T00:00:00",
            "queue_schema": "2.6",
            "metadata": {},
        }
        snapshot = QueueSnapshotV1(jobs=[entry], auto_run_enabled=True, paused=False)
        mock_runner = SimpleNamespace(
            start=lambda: None,
            stop=lambda: None,
            is_running=lambda: False,
        )
        mock_runner.start_calls = 0

        def _start() -> None:
            mock_runner.start_calls += 1

        mock_runner.start = _start
        mock_queue = MockQueue()
        monkeypatch.setattr(
            "src.controller.job_execution_controller.load_queue_snapshot",
            lambda *_, **__: snapshot,
        )

        controller = JobExecutionController(
            runner=mock_runner,
            queue=mock_queue,
            execute_job=lambda job: {"ok": True},
        )

        assert controller._deferred_autostart is True
        assert mock_runner.start_calls == 0
        assert mock_queue.restore_called is True
        assert mock_queue.restored_jobs is not None
        assert len(mock_queue.restored_jobs) == 1

        controller.trigger_deferred_autostart()

        assert mock_runner.start_calls == 1
        assert controller._deferred_autostart is False

    def test_restore_handles_empty_snapshot_gracefully(self, monkeypatch) -> None:
        mock_queue = MockQueue()
        monkeypatch.setattr(
            "src.controller.job_execution_controller.load_queue_snapshot",
            lambda *_, **__: None,
        )

        controller = JobExecutionController(
            runner=SimpleNamespace(start=lambda: None, stop=lambda: None, is_running=lambda: False),
            queue=mock_queue,
            execute_job=lambda job: {"ok": True},
        )

        assert mock_queue.restore_called is False
        assert controller._deferred_autostart is False
        assert mock_queue.jobs == []

    def test_restore_filters_non_queued_jobs(self, monkeypatch) -> None:
        snapshot = QueueSnapshotV1(
            jobs=[
                {
                    "queue_id": "queued-job",
                    "njr_snapshot": {"normalized_job": asdict(_make_normalized_record("queued-job"))},
                    "priority": 1,
                    "status": "queued",
                    "created_at": "2025-12-25T00:00:00",
                    "queue_schema": "2.6",
                    "metadata": {},
                },
                {
                    "queue_id": "completed-job",
                    "njr_snapshot": {
                        "normalized_job": asdict(_make_normalized_record("completed-job"))
                    },
                    "priority": 1,
                    "status": "completed",
                    "created_at": "2025-12-25T00:00:00",
                    "queue_schema": "2.6",
                    "metadata": {},
                },
            ],
            auto_run_enabled=False,
            paused=False,
        )
        mock_queue = MockQueue()
        monkeypatch.setattr(
            "src.controller.job_execution_controller.load_queue_snapshot",
            lambda *_, **__: snapshot,
        )

        controller = JobExecutionController(
            runner=SimpleNamespace(start=lambda: None, stop=lambda: None, is_running=lambda: False),
            queue=mock_queue,
            execute_job=lambda job: {"ok": True},
        )

        assert mock_queue.restore_called is True
        assert mock_queue.restored_jobs is not None
        assert [job.job_id for job in mock_queue.restored_jobs] == ["queued-job"]
        assert controller._deferred_autostart is False


class TestQueueSubmissionLimits:
    def test_submit_large_batch_of_jobs(self) -> None:
        controller = object.__new__(PipelineController)
        submitted_jobs: list[Job] = []
        controller._job_service = SimpleNamespace(
            submit_job_with_run_mode=lambda job, emit_queue_updated=False: submitted_jobs.append(job),
            _emit_queue_updated=lambda: None,
            job_queue=None,
        )
        controller._last_run_config = None
        controller._sort_jobs_by_model = MethodType(lambda self, records: list(records), controller)
        controller._ensure_record_prompt_pack_metadata = MethodType(
            lambda self, record, prompt_pack_id, prompt_pack_name: None,
            controller,
        )
        controller._log_add_to_queue_event = MethodType(lambda self, job_id: None, controller)
        controller._run_job = MethodType(lambda self, job: {}, controller)
        controller._to_queue_job = MethodType(
            lambda self, record, **kwargs: Job(
                job_id=record.job_id,
                priority=JobPriority.NORMAL,
                run_mode=kwargs["run_mode"],
                source=kwargs["source"],
                prompt_source=kwargs["prompt_source"],
                prompt_pack_id=kwargs.get("prompt_pack_id"),
                config_snapshot=record.to_queue_snapshot(),
            ),
            controller,
        )

        records = [_make_normalized_record(f"job-{index}") for index in range(20)]

        submitted = controller.submit_preview_jobs_to_queue(records=records)

        assert submitted == 20
        assert len(submitted_jobs) == 20
        assert [job.job_id for job in submitted_jobs] == [f"job-{index}" for index in range(20)]


class TestQueueSubmissionErrorHandling:
    def _build_app_controller(self, pipeline_controller: Any) -> AppController:
        controller = object.__new__(AppController)
        controller.pipeline_controller = pipeline_controller
        controller.app_state = SimpleNamespace(
            preview_jobs=[],
            clear_job_draft=lambda: None,
            set_preview_jobs=lambda jobs: None,
        )
        controller._append_messages: list[str] = []
        controller._append_log = lambda text: controller._append_messages.append(text)
        controller._ui_dispatch = lambda fn: fn()
        controller._queue_submit_in_progress = True
        controller._submit_preview_jobs_to_queue_async = MethodType(
            AppController._submit_preview_jobs_to_queue_async,
            controller,
        )
        return controller

    def test_async_queue_submission_resets_flag_and_logs_error(self) -> None:
        pipeline_controller = SimpleNamespace(
            submit_preview_jobs_to_queue=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("Test error")
            ),
            enqueue_draft_jobs=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Test error")),
        )
        controller = self._build_app_controller(pipeline_controller)
        preview_jobs = [SimpleNamespace(job_id="job-1")]

        controller._submit_preview_jobs_to_queue_async(
            pipeline_controller,
            preview_jobs,
            {"run_mode": "queue"},
            "MainThread",
        )

        assert controller._queue_submit_in_progress is False
        assert any("Test error" in message for message in controller._append_messages)

    def test_async_queue_submission_clears_preview_on_success(self) -> None:
        preview_jobs = [SimpleNamespace(job_id="job-1"), SimpleNamespace(job_id="job-2")]
        cleared: list[list[Any]] = []
        app_state = SimpleNamespace(
            preview_jobs=list(preview_jobs),
            clear_job_draft=lambda: cleared.append(["draft"]),
            set_preview_jobs=lambda jobs: cleared.append(list(jobs)),
        )
        pipeline_controller = SimpleNamespace(
            submit_preview_jobs_to_queue=lambda **kwargs: len(kwargs["records"]),
        )
        controller = object.__new__(AppController)
        controller.pipeline_controller = pipeline_controller
        controller.app_state = app_state
        controller._append_messages = []
        controller._append_log = lambda text: controller._append_messages.append(text)
        controller._ui_dispatch = lambda fn: fn()
        controller._queue_submit_in_progress = True
        controller._submit_preview_jobs_to_queue_async = MethodType(
            AppController._submit_preview_jobs_to_queue_async,
            controller,
        )

        controller._submit_preview_jobs_to_queue_async(
            pipeline_controller,
            preview_jobs,
            {"run_mode": "queue"},
            "MainThread",
        )

        assert controller._queue_submit_in_progress is False
        assert ["draft"] in cleared
        assert [] in cleared
        assert any("Submitted 2 job(s)" in message for message in controller._append_messages)
