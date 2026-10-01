# Subsystem: Controller
# Role: Tests for run mode handling in V2 pipeline (PR-204C).

"""Tests for queue-only run mode handling in PipelineController V2."""

from __future__ import annotations

from typing import Any

import pytest

from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord, SourceKind
from tests.helpers.njr_factory import make_pipeline_njr

# ---------------------------------------------------------------------------
# Fake/Stub Classes (shared with integration tests)
# ---------------------------------------------------------------------------


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
    """Fake JobService that records canonical NJR batch submissions."""

    def __init__(self) -> None:
        self.submissions: list[tuple[list[NormalizedJobRecord], SubmissionPolicy | None]] = []

    @property
    def submitted_records(self) -> list[NormalizedJobRecord]:
        return [record for batch, _policy in self.submissions for record in batch]

    def submit_njrs(
        self,
        records: list[NormalizedJobRecord],
        policy: SubmissionPolicy | None = None,
    ) -> list[str]:
        self.submissions.append((list(records), policy))
        return [record.job_id for record in records]


class FakeWebUIConnection:
    """Fake WebUI connection that always reports ready."""

    def ensure_connected(self, autostart: bool = False) -> Any:
        from src.controller.webui_connection_controller import WebUIConnectionState

        return WebUIConnectionState.READY


def _start_pipeline_with_pack(controller: PipelineController, **kwargs: Any) -> bool:
    controller._last_run_config = {"prompt_pack_id": "test-pack-xyz"}
    return controller.start_pipeline_v2(**kwargs)


def _attach_pipeline_state(
    controller: PipelineController, state: FakePipelineState | None = None
) -> FakePipelineState:
    if state is None:
        state = FakePipelineState()
    controller.gui_get_pipeline_state = lambda: state
    return state


def _prepare_controller(
    fake_builder: FakeJobBuilder, fake_service: FakeJobService
) -> PipelineController:
    controller = PipelineController(job_builder=fake_builder)
    # Typed GUI intent (prompt) drives the state-based preview build.
    controller.gui_get_pipeline_overrides = lambda: {"prompt": "test prompt"}
    controller._job_service = fake_service
    controller._webui_connection = FakeWebUIConnection()
    _attach_pipeline_state(controller)
    return controller


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_normalized_job(
    job_id: str = "job-1",
    seed: int = 12345,
) -> NormalizedJobRecord:
    """Create a NormalizedJobRecord for testing."""
    return make_pipeline_njr(
        job_id=job_id,
        config={"model": "test_model", "prompt": "test prompt", "seed": seed},
        seed=seed,
    )


@pytest.fixture
def fake_job_service() -> FakeJobService:
    return FakeJobService()


# ---------------------------------------------------------------------------
# Test: Run Mode Enforcement
# ---------------------------------------------------------------------------


def _start_capturing(controller: PipelineController, **kwargs: Any) -> tuple[bool, list[dict]]:
    completions: list[dict] = []
    started = _start_pipeline_with_pack(controller, on_complete=completions.append, **kwargs)
    return started, completions


class TestRunModeEnforcement:
    """Fresh runtime execution is queue-only; legacy run modes are normalized."""

    def test_explicit_direct_mode_is_coerced_to_queue(self) -> None:
        """Explicit run_mode='direct' is normalized to queue."""
        record = make_normalized_job()
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder([record]), fake_service)

        result, completions = _start_capturing(controller, run_mode="direct")

        assert result is True
        assert completions == [{"submitted_jobs": 1, "run_mode": "queue"}]
        assert [r.job_id for r in fake_service.submitted_records] == [record.job_id]

    def test_explicit_queue_mode(self) -> None:
        """Explicit run_mode='queue' is respected."""
        record = make_normalized_job()
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder([record]), fake_service)

        result, completions = _start_capturing(controller, run_mode="queue")

        assert result is True
        assert completions == [{"submitted_jobs": 1, "run_mode": "queue"}]
        assert [r.job_id for r in fake_service.submitted_records] == [record.job_id]

    def test_default_uses_state_run_mode(self) -> None:
        """When run_mode is None, a non-queue state run mode is normalized to queue."""
        record = make_normalized_job()
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder([record]), fake_service)
        state = _attach_pipeline_state(controller)
        state.run_mode = "direct"

        result, completions = _start_capturing(controller)  # No explicit run_mode

        assert result is True
        assert completions[0]["run_mode"] == "queue"
        assert state.run_mode == "queue"
        assert len(fake_service.submitted_records) == 1

    def test_default_queue_when_no_state(self) -> None:
        """Defaults to queue mode when pipeline_state is not available."""
        record = make_normalized_job()
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder([record]), fake_service)
        controller.gui_get_pipeline_state = lambda: None

        result, completions = _start_capturing(controller)

        assert result is True
        assert completions[0]["run_mode"] == "queue"
        assert len(fake_service.submitted_records) == 1


# ---------------------------------------------------------------------------
# Test: Multiple Jobs Same Run Mode
# ---------------------------------------------------------------------------


class TestMultipleJobsSameRunMode:
    """A batch is submitted atomically through one canonical JobService call."""

    def test_all_jobs_get_queue_mode_when_direct_requested(self) -> None:
        """All jobs are submitted as one queue batch even when direct is requested."""
        records = [
            make_normalized_job(job_id="j1"),
            make_normalized_job(job_id="j2"),
            make_normalized_job(job_id="j3"),
        ]
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder(records), fake_service)

        result, completions = _start_capturing(controller, run_mode="direct")

        assert result is True
        assert completions == [{"submitted_jobs": 3, "run_mode": "queue"}]
        assert len(fake_service.submissions) == 1
        assert {r.job_id for r in fake_service.submitted_records} == {"j1", "j2", "j3"}

    def test_all_jobs_get_queue_mode(self) -> None:
        """All jobs are submitted as one queue batch when queue is specified."""
        records = [
            make_normalized_job(job_id="q1"),
            make_normalized_job(job_id="q2"),
        ]
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder(records), fake_service)

        result, completions = _start_capturing(controller, run_mode="queue")

        assert result is True
        assert completions == [{"submitted_jobs": 2, "run_mode": "queue"}]
        assert len(fake_service.submissions) == 1
        assert {r.job_id for r in fake_service.submitted_records} == {"q1", "q2"}


# ---------------------------------------------------------------------------
# Test: JobService Integration
# ---------------------------------------------------------------------------


class TestJobServiceIntegration:
    """Test that JobService.submit_njrs is the submission boundary."""

    def test_submit_njrs_called_with_every_record(self) -> None:
        """submit_njrs receives every NJR built for the run, with a SubmissionPolicy."""
        records = [
            make_normalized_job(job_id="srv1"),
            make_normalized_job(job_id="srv2"),
        ]
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder(records), fake_service)

        _start_pipeline_with_pack(controller)

        assert len(fake_service.submissions) == 1
        submitted, policy = fake_service.submissions[0]
        assert isinstance(policy, SubmissionPolicy)
        job_ids = [record.job_id for record in submitted]
        assert "srv1" in job_ids
        assert "srv2" in job_ids
        assert all(isinstance(record, NormalizedJobRecord) for record in submitted)


class TestPromptPackRequirement:
    """Verify that pipeline runs support pack and manual provenance."""

    def test_start_pipeline_without_pack_submits_manual_jobs(
        self, fake_job_service: FakeJobService
    ) -> None:
        record = make_normalized_job()
        controller = _prepare_controller(FakeJobBuilder([record]), fake_job_service)

        result = controller.start_pipeline_v2(run_mode="queue")

        assert result is True
        (submitted,) = fake_job_service.submitted_records
        assert submitted.source.kind is not SourceKind.PROMPT_PACK
        assert not submitted.prompt_pack_id


class TestCanonicalStartPipeline:
    """Verify the public start_pipeline entrypoint uses the canonical NJR path."""

    def test_start_pipeline_submits_preview_jobs(self) -> None:
        record = make_normalized_job()
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder([record]), fake_service)
        completions: list[dict] = []

        result = controller.start_pipeline(
            run_config={"run_mode": "direct", "prompt_source": "manual"},
            on_complete=completions.append,
        )

        assert result is True
        assert completions == [{"submitted_jobs": 1, "run_mode": "queue"}]
        assert [r.job_id for r in fake_service.submitted_records] == [record.job_id]
