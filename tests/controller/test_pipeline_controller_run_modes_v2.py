# Subsystem: Controller
# Role: Tests for run mode handling in V2 pipeline (PR-204C).

"""Tests for run mode handling in PipelineController V2.

These tests verify:
1. Direct mode jobs are submitted with run_mode="direct"
2. Queue mode jobs are submitted with run_mode="queue"
3. Run mode is correctly derived from pipeline state
4. JobService.submit_job_with_run_mode is used consistently
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job


# ---------------------------------------------------------------------------
# Fake/Stub Classes (shared with integration tests)
# ---------------------------------------------------------------------------


@dataclass
class FakeConfig:
    """Minimal config for testing."""

    model: str = "test_model"
    prompt: str = "test prompt"
    negative_prompt: str = ""
    sampler: str = "Euler"
    steps: int = 20
    cfg_scale: float = 7.0
    width: int = 512
    height: int = 512
    seed: int = 12345


class FakeStateManager:
    """Fake state manager for testing."""

    def __init__(self) -> None:
        self.current_state = "idle"
        self._can_run = True
        self.batch_runs = 1
        self.pipeline_state = FakePipelineState()

    def can_run(self) -> bool:
        return self._can_run

    def transition_to(self, state: Any) -> None:
        self.current_state = state


class FakePipelineState:
    """Fake pipeline state with run_mode."""

    def __init__(self) -> None:
        self.run_mode = "queue"


class FakeJobBuilder:
    """Fake JobBuilderV2 that returns predetermined jobs."""

    def __init__(self, jobs_to_return: list[NormalizedJobRecord] | None = None) -> None:
        self._jobs_to_return = jobs_to_return or []

    def build_jobs(self, **kwargs: Any) -> list[NormalizedJobRecord]:
        return list(self._jobs_to_return)


class FakeJobService:
    """Fake JobService that records submissions."""

    def __init__(self) -> None:
        self.submitted_jobs: list[tuple[Job, str]] = []

    def submit_job_with_run_mode(self, job: Job) -> None:
        self.submitted_jobs.append((job, job.run_mode))

    def submit_direct(self, job: Job) -> dict | None:
        self.submitted_jobs.append((job, "direct"))
        return {}

    def submit_queued(self, job: Job) -> None:
        self.submitted_jobs.append((job, "queue"))


class FakeWebUIConnection:
    """Fake WebUI connection that always reports ready."""

    def ensure_connected(self, autostart: bool = False) -> Any:
        from src.controller.webui_connection_controller import WebUIConnectionState
        return WebUIConnectionState.READY


def _start_pipeline_with_pack(controller: PipelineController, **kwargs: Any) -> bool:
    controller._last_run_config = {"prompt_pack_id": "test-pack-xyz"}
    return controller.start_pipeline_v2(**kwargs)


def _with_fake_state_manager(
    controller: PipelineController, state_manager: FakeStateManager
) -> PipelineController:
    controller.state_manager = state_manager
    return controller


class FakeJobController:
    """Fake job execution controller."""

    def __init__(self) -> None:
        self._queue = FakeQueue()
        self._runner = FakeRunner()
        self._history = FakeHistory()

    def get_queue(self) -> Any:
        return self._queue

    def get_runner(self) -> Any:
        return self._runner

    def get_history_store(self) -> Any:
        return self._history

    def set_status_callback(self, name: str, callback: Any) -> None:
        pass


class FakeQueue:
    """Fake job queue."""

    def __init__(self) -> None:
        self.jobs: list[Job] = []

    def submit(self, job: Job) -> None:
        self.jobs.append(job)

    def list_jobs(self, status_filter: Any = None) -> list[Job]:
        return list(self.jobs)


class FakeRunner:
    """Fake job runner."""

    def __init__(self) -> None:
        self._on_status_change = None

    def is_running(self) -> bool:
        return False


class FakeHistory:
    """Fake history store."""
    pass


class FakeConfigAssembler:
    """Fake config assembler."""

    def build_from_gui_input(self, **kwargs: Any) -> Any:
        return FakeConfig()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_normalized_job(
    job_id: str = "job-1",
    seed: int = 12345,
) -> NormalizedJobRecord:
    """Create a NormalizedJobRecord for testing."""
    return NormalizedJobRecord(
        job_id=job_id,
        config=FakeConfig(seed=seed),
        path_output_dir="output",
        filename_template="{seed}",
        seed=seed,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=1000.0,
    )


@pytest.fixture
def fake_state_manager() -> FakeStateManager:
    return FakeStateManager()


@pytest.fixture
def fake_job_service() -> FakeJobService:
    return FakeJobService()


# ---------------------------------------------------------------------------
# Test: Run Mode Enforcement
# ---------------------------------------------------------------------------


class TestRunModeEnforcement:
    """Test that run mode is correctly applied to jobs."""

    def test_explicit_direct_mode(self, fake_state_manager: FakeStateManager) -> None:
        """Explicit run_mode='direct' is respected."""
        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        result = _start_pipeline_with_pack(controller, run_mode="direct")

        assert result is True
        job, mode = fake_service.submitted_jobs[0]
        assert job.run_mode == "direct"
        assert mode == "direct"

    def test_explicit_queue_mode(self, fake_state_manager: FakeStateManager) -> None:
        """Explicit run_mode='queue' is respected."""
        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        result = _start_pipeline_with_pack(controller, run_mode="queue")

        assert result is True
        job, mode = fake_service.submitted_jobs[0]
        assert job.run_mode == "queue"
        assert mode == "queue"

    def test_default_uses_state_run_mode(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """When run_mode is None, uses pipeline_state.run_mode."""
        fake_state_manager.pipeline_state.run_mode = "direct"

        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        result = _start_pipeline_with_pack(controller)  # No explicit run_mode

        assert result is True
        job, mode = fake_service.submitted_jobs[0]
        assert job.run_mode == "direct"

    def test_default_queue_when_no_state(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Defaults to queue mode when pipeline_state is not available."""
        # Remove pipeline_state
        delattr(fake_state_manager, "pipeline_state")

        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        result = _start_pipeline_with_pack(controller)

        assert result is True
        job, mode = fake_service.submitted_jobs[0]
        assert job.run_mode == "queue"


# ---------------------------------------------------------------------------
# Test: Multiple Jobs Same Run Mode
# ---------------------------------------------------------------------------


class TestMultipleJobsSameRunMode:
    """Test that all jobs in a batch get the same run mode."""

    def test_all_jobs_get_direct_mode(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """All jobs get direct mode when specified."""
        records = [
            make_normalized_job(job_id="j1"),
            make_normalized_job(job_id="j2"),
            make_normalized_job(job_id="j3"),
        ]
        fake_builder = FakeJobBuilder(jobs_to_return=records)
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        _start_pipeline_with_pack(controller, run_mode="direct")

        assert len(fake_service.submitted_jobs) == 3
        for job, mode in fake_service.submitted_jobs:
            assert job.run_mode == "direct"
            assert mode == "direct"

    def test_all_jobs_get_queue_mode(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """All jobs get queue mode when specified."""
        records = [
            make_normalized_job(job_id="q1"),
            make_normalized_job(job_id="q2"),
        ]
        fake_builder = FakeJobBuilder(jobs_to_return=records)
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        _start_pipeline_with_pack(controller, run_mode="queue")

        assert len(fake_service.submitted_jobs) == 2
        for job, mode in fake_service.submitted_jobs:
            assert job.run_mode == "queue"
            assert mode == "queue"


# ---------------------------------------------------------------------------
# Test: Job Payload Attachment
# ---------------------------------------------------------------------------


class TestJobPayloadAttachment:
    """Test that jobs have execution payloads attached."""

    def test_job_has_payload(self, fake_state_manager: FakeStateManager) -> None:
        """Submitted jobs have callable payload attached."""
        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        _start_pipeline_with_pack(controller)

        job, _ = fake_service.submitted_jobs[0]
        assert job.payload is not None
        assert callable(job.payload)


# ---------------------------------------------------------------------------
# Test: JobService Integration
# ---------------------------------------------------------------------------


class TestJobServiceIntegration:
    """Test that JobService is used correctly."""

    def test_submit_job_with_run_mode_called(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """submit_job_with_run_mode is called for each job."""
        records = [
            make_normalized_job(job_id="srv1"),
            make_normalized_job(job_id="srv2"),
        ]
        fake_builder = FakeJobBuilder(jobs_to_return=records)
        fake_service = FakeJobService()

        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        _start_pipeline_with_pack(controller)

        # Verify correct number of submissions
        assert len(fake_service.submitted_jobs) == 2

        # Verify job IDs
        job_ids = [job.job_id for job, _ in fake_service.submitted_jobs]
        assert "srv1" in job_ids
        assert "srv2" in job_ids


class TestPromptPackRequirement:
    """Verify that pipeline runs require a prompt pack."""

    def test_start_pipeline_without_pack_returns_false(
        self, fake_state_manager: FakeStateManager, fake_job_service: FakeJobService
    ) -> None:
        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        controller = _with_fake_state_manager(
            PipelineController(
                job_builder=fake_builder,
                config_assembler=FakeConfigAssembler(),
            ),
            fake_state_manager,
        )
        controller._job_service = fake_job_service
        controller._webui_connection = FakeWebUIConnection()
        errors: list[Exception] = []

        result = controller.start_pipeline_v2(
            run_mode="queue",
            on_error=lambda exc: errors.append(exc),
        )

        assert result is False
        assert errors and isinstance(errors[0], ValueError)
