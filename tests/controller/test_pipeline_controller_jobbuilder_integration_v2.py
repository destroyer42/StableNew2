# Subsystem: Controller
# Role: Tests for PipelineController + JobBuilderV2 integration (PR-204C).

"""Tests for PipelineController + JobBuilderV2 integration.

These tests verify:
1. PipelineController builds the base config from typed GUI intent and hands it to JobBuilderV2
2. Built NormalizedJobRecords are submitted as one batch through JobService.submit_njrs
3. JobService turns each NJR into a queued Job that preserves NJR metadata
4. The NJR queue snapshot is the canonical nested, versioned envelope
"""

from __future__ import annotations

from typing import Any

import pytest

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_queue import JobQueue
from src.queue.stub_runner import StubRunner
from tests.helpers.njr_factory import make_pipeline_njr

# ---------------------------------------------------------------------------
# Fake/Stub Classes
# ---------------------------------------------------------------------------


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
        config_variant_plan: Any = None,
        rng_seed: int | None = None,
        **kwargs: Any,
    ) -> list[NormalizedJobRecord]:
        """Record call and return predetermined jobs."""
        self.calls.append(
            {
                "base_config": base_config,
                "randomization_plan": randomization_plan,
                "batch_settings": batch_settings,
                "output_settings": output_settings,
                "config_variant_plan": config_variant_plan,
                "rng_seed": rng_seed,
            }
        )
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
    controller._last_run_config = {"prompt_pack_id": "test-pack-123"}
    return controller.start_pipeline_v2(**kwargs)


def _prepare_controller(
    fake_builder: FakeJobBuilder,
    fake_service: Any,
    gui_overrides: dict[str, Any] | None = None,
) -> PipelineController:
    controller = PipelineController(job_builder=fake_builder)
    # Typed GUI intent drives the state-based preview build.
    overrides = gui_overrides if gui_overrides is not None else {"prompt": "test prompt"}
    controller.gui_get_pipeline_overrides = lambda: dict(overrides)
    controller._job_service = fake_service
    controller._webui_connection = FakeWebUIConnection()
    return controller


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
    **overrides: Any,
) -> NormalizedJobRecord:
    """Create a NormalizedJobRecord for testing."""
    return make_pipeline_njr(
        job_id=job_id,
        config={"model": "test_model", "prompt": "test prompt", "seed": seed},
        seed=seed,
        variant_index=variant_index,
        variant_total=variant_total,
        batch_index=batch_index,
        batch_total=batch_total,
        **overrides,
    )


@pytest.fixture
def fake_job_service() -> FakeJobService:
    return FakeJobService()


# ---------------------------------------------------------------------------
# Test: Single Job Queue Mode
# ---------------------------------------------------------------------------


class TestSingleJobQueueMode:
    """Test single job submission in queue mode."""

    def test_single_job_submitted_to_job_service(self) -> None:
        """Single job from builder is submitted via JobService.submit_njrs."""
        record = make_normalized_job(job_id="test-job-1")
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder([record]), fake_service)

        result = _start_pipeline_with_pack(controller, run_mode="queue")

        assert result is True
        assert len(fake_service.submissions) == 1
        assert [r.job_id for r in fake_service.submitted_records] == ["test-job-1"]

    def test_builder_called_with_correct_config(self) -> None:
        """JobBuilderV2 is called with the config merged from typed GUI intent."""
        fake_builder = FakeJobBuilder([make_normalized_job()])
        controller = _prepare_controller(
            fake_builder,
            FakeJobService(),
            gui_overrides={
                "prompt": "specific prompt",
                "txt2img": {"model": "specific_model", "steps": 33},
            },
        )

        _start_pipeline_with_pack(controller, run_mode="queue")

        assert len(fake_builder.calls) == 1
        base_config = fake_builder.calls[0]["base_config"]
        assert base_config["txt2img"]["model"] == "specific_model"
        assert base_config["txt2img"]["steps"] == 33
        assert base_config["prompt"] == "specific prompt"


# ---------------------------------------------------------------------------
# Test: Multiple Jobs
# ---------------------------------------------------------------------------


class TestMultipleJobSubmission:
    """Test multiple job submission."""

    def test_multiple_jobs_all_submitted(self) -> None:
        """Multiple jobs from builder are all submitted in one batch, in order."""
        records = [
            make_normalized_job(job_id="job-1", variant_index=0, variant_total=3),
            make_normalized_job(job_id="job-2", variant_index=1, variant_total=3),
            make_normalized_job(job_id="job-3", variant_index=2, variant_total=3),
        ]
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder(records), fake_service)

        result = _start_pipeline_with_pack(controller, run_mode="queue")

        assert result is True
        assert len(fake_service.submissions) == 1
        assert [r.job_id for r in fake_service.submitted_records] == ["job-1", "job-2", "job-3"]

    def test_variant_metadata_preserved(self) -> None:
        """Variant index and total are preserved in submitted NJR provenance."""
        records = [
            make_normalized_job(job_id="v1", variant_index=0, variant_total=2),
            make_normalized_job(job_id="v2", variant_index=1, variant_total=2),
        ]
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder(records), fake_service)

        _start_pipeline_with_pack(controller, run_mode="queue")

        submitted = fake_service.submitted_records
        assert (submitted[0].variant_index, submitted[0].variant_total) == (0, 2)
        assert (submitted[1].variant_index, submitted[1].variant_total) == (1, 2)


# ---------------------------------------------------------------------------
# Test: Empty Builder Output
# ---------------------------------------------------------------------------


class TestEmptyBuilderOutput:
    """Test behavior when builder returns no jobs."""

    def test_empty_jobs_returns_false(self) -> None:
        """Returns False when builder produces no jobs."""
        fake_builder = FakeJobBuilder([])
        fake_service = FakeJobService()
        controller = _prepare_controller(fake_builder, fake_service)

        result = _start_pipeline_with_pack(controller)

        assert result is False
        assert len(fake_builder.calls) == 1  # genuinely consulted, not skipped as incomplete
        assert fake_service.submissions == []

    def test_no_crash_on_empty_output(self) -> None:
        """No exception when builder returns empty list and no job service is wired."""
        fake_builder = FakeJobBuilder([])
        controller = PipelineController(job_builder=fake_builder)
        controller.gui_get_pipeline_overrides = lambda: {"prompt": "test prompt"}
        controller._webui_connection = FakeWebUIConnection()

        result = _start_pipeline_with_pack(controller)

        assert result is False
        assert len(fake_builder.calls) == 1


# ---------------------------------------------------------------------------
# Test: Metadata Preservation (NJR -> queued Job via JobService.submit_njrs)
# ---------------------------------------------------------------------------


class TestMetadataPreservation:
    """Test that NJR metadata is preserved when JobService creates the queued Job."""

    @staticmethod
    def _real_job_service() -> tuple[JobService, JobQueue]:
        queue = JobQueue()
        service = JobService(queue, runner_factory=lambda jq, rc: StubRunner(jq))
        return service, queue

    def test_config_snapshot_contains_job_fields(self) -> None:
        """The queued Job's snapshot embeds the submitted NJR's identity and provenance."""
        record = make_normalized_job(
            job_id="meta-test",
            seed=99999,
            variant_index=2,
            variant_total=5,
            prompt_pack_id="test-pack-123",
        )
        service, queue = self._real_job_service()
        controller = _prepare_controller(FakeJobBuilder([record]), service)

        assert _start_pipeline_with_pack(controller) is True

        (job,) = queue.list_jobs()
        njr_snapshot = job.snapshot["normalized_job"]
        assert njr_snapshot["job_id"] == "meta-test"
        assert njr_snapshot["provenance"]["seed"] == 99999
        assert njr_snapshot["provenance"]["variant_index"] == 2
        assert njr_snapshot["provenance"]["variant_total"] == 5
        assert njr_snapshot["workload"]["config"]["model"] == "test_model"
        assert njr_snapshot["workload"]["config"]["prompt"] == "test prompt"
        assert njr_snapshot["source"]["id"] == "test-pack-123"
        assert job.variant_index == 2
        assert job.variant_total == 5

    def test_source_and_prompt_source_preserved(self) -> None:
        """Job source/prompt_source/pack identity derive from the NJR source descriptor."""
        record = make_normalized_job(prompt_pack_id="test-pack-123")
        service, queue = self._real_job_service()
        controller = _prepare_controller(FakeJobBuilder([record]), service)

        _start_pipeline_with_pack(controller, source="api", prompt_source="pack")

        (job,) = queue.list_jobs()
        assert job.run_mode == "queue"
        assert job.prompt_source == "pack"
        assert job.prompt_pack_id == "test-pack-123"


# ---------------------------------------------------------------------------
# Test: Cannot Run State
# ---------------------------------------------------------------------------


class TestCannotRunState:
    """Test behavior when state manager reports cannot run."""

    def test_cannot_run_returns_false(self) -> None:
        """Returns False when state_manager.can_run() is False."""
        fake_service = FakeJobService()
        controller = _prepare_controller(FakeJobBuilder([make_normalized_job()]), fake_service)
        controller.state_manager.can_run = lambda: False

        result = _start_pipeline_with_pack(controller)

        assert result is False
        assert fake_service.submissions == []


# ---------------------------------------------------------------------------
# Test: NormalizedJobRecord.to_queue_snapshot
# ---------------------------------------------------------------------------


class TestNormalizedJobRecordSnapshot:
    """Test to_queue_snapshot: the canonical, versioned NJR envelope."""

    def test_snapshot_contains_all_fields(self) -> None:
        """Snapshot carries identity, workload, output plan and provenance, and round-trips."""
        record = make_pipeline_njr(
            job_id="snap-1",
            config={"model": "snap_model", "prompt": "snap prompt", "seed": 11111},
            positive_prompt="snap prompt",
            negative_prompt="bad things",
            seed=11111,
            variant_index=1,
            variant_total=3,
            batch_index=2,
            batch_total=4,
            randomizer_summary={"mode": "FIXED"},
            path_output_dir="/output/snap",
            filename_template="{seed}_{steps}",
        )

        snapshot = record.to_queue_snapshot()

        assert snapshot["job_id"] == "snap-1"
        assert snapshot["workload"]["config"]["model"] == "snap_model"
        assert snapshot["workload"]["positive_prompt"] == "snap prompt"
        assert snapshot["workload"]["negative_prompt"] == "bad things"
        assert snapshot["output_plan"]["base_output_dir"] == "/output/snap"
        assert snapshot["output_plan"]["filename_template"] == "{seed}_{steps}"
        provenance = snapshot["provenance"]
        assert provenance["seed"] == 11111
        assert provenance["variant_index"] == 1
        assert provenance["variant_total"] == 3
        assert provenance["batch_index"] == 2
        assert provenance["batch_total"] == 4
        assert provenance["randomizer_summary"] == {"mode": "FIXED"}
        assert NormalizedJobRecord.from_dict(snapshot).to_queue_snapshot() == snapshot

    def test_snapshot_with_dict_config(self) -> None:
        """Snapshot preserves a dict workload config verbatim."""
        record = make_pipeline_njr(
            job_id="dict-1",
            config={"model": "dict_model", "prompt": "dict prompt", "seed": 22222},
            positive_prompt="dict prompt",
            seed=22222,
            path_output_dir="/dict/output",
        )

        snapshot = record.to_queue_snapshot()

        assert snapshot["workload"]["config"] == {
            "model": "dict_model",
            "prompt": "dict prompt",
            "seed": 22222,
        }
        assert snapshot["provenance"]["seed"] == 22222
        assert snapshot["output_plan"]["base_output_dir"] == "/dict/output"
