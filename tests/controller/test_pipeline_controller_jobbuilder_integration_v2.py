# Subsystem: Controller
# Role: Tests for PipelineController + JobBuilderV2 integration (PR-204C).

"""Tests for PipelineController + JobBuilderV2 integration.

These tests verify:
1. PipelineController correctly uses JobBuilderV2 to construct jobs
2. NormalizedJobRecord → Job conversion preserves metadata
3. JobService receives correct jobs via submit_job_with_run_mode
4. Direct vs queue mode is correctly applied
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job


# ---------------------------------------------------------------------------
# Fake/Stub Classes
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

    def can_run(self) -> bool:
        return self._can_run

    def transition_to(self, state: Any) -> None:
        self.current_state = state


class FakeJobBuilder:
    """Fake JobBuilderV2 that records calls and returns deterministic results."""

    def __init__(self, jobs_to_return: list[NormalizedJobRecord] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._jobs_to_return = jobs_to_return or []

    def build_jobs(
        self,
        *,
        base_config: Any,
        randomization_plan: Any = None,
        batch_settings: Any = None,
        output_settings: Any = None,
        rng_seed: int | None = None,
    ) -> list[NormalizedJobRecord]:
        """Record call and return predetermined jobs."""
        self.calls.append({
            "base_config": base_config,
            "randomization_plan": randomization_plan,
            "batch_settings": batch_settings,
            "output_settings": output_settings,
            "rng_seed": rng_seed,
        })
        return list(self._jobs_to_return)


class FakeJobService:
    """Fake JobService that records submissions."""

    def __init__(self) -> None:
        self.submitted_jobs: list[tuple[Job, str]] = []

    def submit_job_with_run_mode(self, job: Job) -> None:
        """Record job submission."""
        self.submitted_jobs.append((job, job.run_mode))


class FakeWebUIConnection:
    """Fake WebUI connection that always reports ready."""

    def ensure_connected(self, autostart: bool = False) -> Any:
        from src.controller.webui_connection_controller import WebUIConnectionState
        return WebUIConnectionState.READY


def _start_pipeline_with_pack(controller: PipelineController, **kwargs: Any) -> bool:
    controller._last_run_config = {"prompt_pack_id": "test-pack-123"}
    return controller.start_pipeline_v2(**kwargs)

    def get_state(self) -> Any:
        from src.controller.webui_connection_controller import WebUIConnectionState
        return WebUIConnectionState.READY


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

    def submit_pipeline_run(self, payload: Any) -> str:
        return "fake-job-id"

    def cancel_job(self, job_id: str) -> None:
        pass

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
        self.started = False
        self._on_status_change = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def is_running(self) -> bool:
        return self.started


class FakeHistory:
    """Fake history store."""
    pass


class FakeConfigAssembler:
    """Fake config assembler that returns predetermined config."""

    def __init__(self, config: Any = None) -> None:
        self._config = config or FakeConfig()

    def build_from_gui_input(self, **kwargs: Any) -> Any:
        return self._config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_normalized_job(
    job_id: str = "job-1",
    seed: int = 12345,
    variant_index: int = 0,
    variant_total: int = 1,
    batch_index: int = 0,
    batch_total: int = 1,
) -> NormalizedJobRecord:
    """Create a NormalizedJobRecord for testing."""
    return NormalizedJobRecord(
        job_id=job_id,
        config=FakeConfig(seed=seed),
        path_output_dir="output",
        filename_template="{seed}",
        seed=seed,
        variant_index=variant_index,
        variant_total=variant_total,
        batch_index=batch_index,
        batch_total=batch_total,
        created_ts=1000.0,
    )


@pytest.fixture
def fake_state_manager() -> FakeStateManager:
    return FakeStateManager()


@pytest.fixture
def fake_job_service() -> FakeJobService:
    return FakeJobService()


# ---------------------------------------------------------------------------
# Test: Single Job Queue Mode
# ---------------------------------------------------------------------------


class TestSingleJobQueueMode:
    """Test single job submission in queue mode."""

    def test_single_job_submitted_to_job_service(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Single job from builder is submitted via JobService."""
        # Arrange
        record = make_normalized_job(job_id="test-job-1")
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        result = _start_pipeline_with_pack(controller, run_mode="queue")

        # Assert
        assert result is True
        assert len(fake_service.submitted_jobs) == 1
        submitted_job, mode = fake_service.submitted_jobs[0]
        assert mode == "queue"
        assert submitted_job.job_id == "test-job-1"

    def test_builder_called_with_correct_config(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """JobBuilderV2 is called with the assembled config."""
        # Arrange
        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_config = FakeConfig(model="specific_model")
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(config=fake_config),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        _start_pipeline_with_pack(controller, run_mode="queue")

        # Assert
        assert len(fake_builder.calls) == 1
        call = fake_builder.calls[0]
        assert call["base_config"].model == "specific_model"


# ---------------------------------------------------------------------------
# Test: Multiple Jobs
# ---------------------------------------------------------------------------


class TestMultipleJobSubmission:
    """Test multiple job submission."""

    def test_multiple_jobs_all_submitted(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Multiple jobs from builder are all submitted."""
        # Arrange
        records = [
            make_normalized_job(job_id="job-1", variant_index=0, variant_total=3),
            make_normalized_job(job_id="job-2", variant_index=1, variant_total=3),
            make_normalized_job(job_id="job-3", variant_index=2, variant_total=3),
        ]
        fake_builder = FakeJobBuilder(jobs_to_return=records)
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        result = _start_pipeline_with_pack(controller, run_mode="queue")

        # Assert
        assert result is True
        assert len(fake_service.submitted_jobs) == 3
        submitted_ids = [job.job_id for job, _ in fake_service.submitted_jobs]
        assert submitted_ids == ["job-1", "job-2", "job-3"]

    def test_variant_metadata_preserved(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Variant index and total are preserved in submitted jobs."""
        # Arrange
        records = [
            make_normalized_job(job_id="v1", variant_index=0, variant_total=2),
            make_normalized_job(job_id="v2", variant_index=1, variant_total=2),
        ]
        fake_builder = FakeJobBuilder(jobs_to_return=records)
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        _start_pipeline_with_pack(controller, run_mode="queue")

        # Assert
        jobs = [job for job, _ in fake_service.submitted_jobs]
        assert jobs[0].variant_index == 0
        assert jobs[0].variant_total == 2
        assert jobs[1].variant_index == 1
        assert jobs[1].variant_total == 2


# ---------------------------------------------------------------------------
# Test: Direct Mode
# ---------------------------------------------------------------------------


class TestDirectMode:
    """Test direct mode submission."""

    def test_direct_mode_sets_run_mode(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Direct mode sets run_mode='direct' on jobs."""
        # Arrange
        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        result = _start_pipeline_with_pack(controller, run_mode="direct")

        # Assert
        assert result is True
        assert len(fake_service.submitted_jobs) == 1
        submitted_job, mode = fake_service.submitted_jobs[0]
        assert mode == "direct"
        assert submitted_job.run_mode == "direct"


# ---------------------------------------------------------------------------
# Test: Empty Builder Output
# ---------------------------------------------------------------------------


class TestEmptyBuilderOutput:
    """Test behavior when builder returns no jobs."""

    def test_empty_jobs_returns_false(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Returns False when builder produces no jobs."""
        # Arrange
        fake_builder = FakeJobBuilder(jobs_to_return=[])
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        result = _start_pipeline_with_pack(controller)

        # Assert
        assert result is False
        assert len(fake_service.submitted_jobs) == 0

    def test_no_crash_on_empty_output(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """No exception when builder returns empty list."""
        # Arrange
        fake_builder = FakeJobBuilder(jobs_to_return=[])

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._webui_connection = FakeWebUIConnection()

        # Act & Assert - no exception
        result = _start_pipeline_with_pack(controller)
        assert result is False


# ---------------------------------------------------------------------------
# Test: Metadata Preservation
# ---------------------------------------------------------------------------


class TestMetadataPreservation:
    """Test that job metadata is preserved through conversion."""

    def test_config_snapshot_contains_job_fields(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Config snapshot includes all expected fields."""
        # Arrange
        record = make_normalized_job(
            job_id="meta-test",
            seed=99999,
            variant_index=2,
            variant_total=5,
        )
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        _start_pipeline_with_pack(controller)

        # Assert
        job, _ = fake_service.submitted_jobs[0]
        snapshot = job.config_snapshot
        assert snapshot["job_id"] == "meta-test"
        assert snapshot["seed"] == 99999
        assert snapshot["variant_index"] == 2
        assert snapshot["variant_total"] == 5
        assert snapshot["model"] == "test_model"
        assert snapshot["prompt"] == "test prompt"
        assert snapshot["prompt_pack_id"] == "test-pack-123"

    def test_source_and_prompt_source_preserved(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Source and prompt_source are set on job."""
        # Arrange
        record = make_normalized_job()
        fake_builder = FakeJobBuilder(jobs_to_return=[record])
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service
        controller._webui_connection = FakeWebUIConnection()

        # Act
        _start_pipeline_with_pack(
            controller,
            source="api",
            prompt_source="pack",
            prompt_pack_id="test-pack-123",
        )

        # Assert
        job, _ = fake_service.submitted_jobs[0]
        assert job.source == "api"
        assert job.prompt_source == "pack"
        assert job.prompt_pack_id == "test-pack-123"


# ---------------------------------------------------------------------------
# Test: Cannot Run State
# ---------------------------------------------------------------------------


class TestCannotRunState:
    """Test behavior when state manager reports cannot run."""

    def test_cannot_run_returns_false(
        self, fake_state_manager: FakeStateManager
    ) -> None:
        """Returns False when state_manager.can_run() is False."""
        # Arrange
        fake_state_manager._can_run = False
        fake_builder = FakeJobBuilder(jobs_to_return=[make_normalized_job()])
        fake_service = FakeJobService()

        controller = PipelineController(
            state_manager=fake_state_manager,
            job_builder=fake_builder,
            config_assembler=FakeConfigAssembler(),
        )
        controller._job_service = fake_service

        # Act
        result = _start_pipeline_with_pack(controller)

        # Assert
        assert result is False
        assert len(fake_service.submitted_jobs) == 0


# ---------------------------------------------------------------------------
# Test: NormalizedJobRecord.to_queue_snapshot
# ---------------------------------------------------------------------------


class TestNormalizedJobRecordSnapshot:
    """Test to_queue_snapshot method."""

    def test_snapshot_contains_all_fields(self) -> None:
        """Snapshot includes all expected fields."""
        record = NormalizedJobRecord(
            job_id="snap-1",
            config=FakeConfig(
                model="snap_model",
                prompt="snap prompt",
                negative_prompt="bad things",
                seed=11111,
            ),
            path_output_dir="/output/snap",
            filename_template="{seed}_{steps}",
            seed=11111,
            variant_index=1,
            variant_total=3,
            batch_index=2,
            batch_total=4,
            created_ts=2000.0,
            randomizer_summary={"mode": "FIXED"},
        )

        snapshot = record.to_queue_snapshot()

        assert snapshot["job_id"] == "snap-1"
        assert snapshot["model"] == "snap_model"
        assert snapshot["prompt"] == "snap prompt"
        assert snapshot["negative_prompt"] == "bad things"
        assert snapshot["seed"] == 11111
        assert snapshot["output_dir"] == "/output/snap"
        assert snapshot["filename_template"] == "{seed}_{steps}"
        assert snapshot["variant_index"] == 1
        assert snapshot["variant_total"] == 3
        assert snapshot["batch_index"] == 2
        assert snapshot["batch_total"] == 4
        assert snapshot["created_ts"] == 2000.0
        assert snapshot["randomizer_summary"] == {"mode": "FIXED"}

    def test_snapshot_with_dict_config(self) -> None:
        """Snapshot works with dict config."""
        record = NormalizedJobRecord(
            job_id="dict-1",
            config={
                "model": "dict_model",
                "prompt": "dict prompt",
                "seed": 22222,
            },
            path_output_dir="/dict/output",
            filename_template="{seed}",
            seed=22222,
        )

        snapshot = record.to_queue_snapshot()

        assert snapshot["model"] == "dict_model"
        assert snapshot["prompt"] == "dict prompt"
        assert snapshot["seed"] == 22222
