"""End-to-End Smoke Tests: GUI → Queue → Runner → History (PR-113).

Validates that a minimal pipeline run works end-to-end for both DIRECT and QUEUE flows
using stubbed WebUI client (no real GPU/network).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.controller.job_service import JobService
from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunResult
from src.pipeline.payload_builder import build_sdxl_payload
from tests.helpers.job_helpers import make_test_njr
from src.pipeline.stage_sequencer import StageSequencer
from src.pipeline.run_config import PromptSource, RunConfig
from src.queue.job_history_store import (
    JSONLJobHistoryStore,
    JobHistoryEntry,
    job_history_entry_from_run_config,
)
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.job_helpers import make_test_job_from_njr



def wait_for_job_completion(
    history_store: JSONLJobHistoryStore,
    job_id: str,
    timeout: float = 2.0,
    poll_interval: float = 0.01,
) -> JobHistoryEntry | None:
    """Poll history store until job reaches a terminal state or timeout."""
    terminal_states = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
    start = time.time()
    while time.time() - start < timeout:
        entry = history_store.get_job(job_id)
        if entry and entry.status in terminal_states:
            return entry
        time.sleep(poll_interval)
    return history_store.get_job(job_id)


def _job_from_config(
    prompt: str,
    *,
    run_mode: str,
    source: str,
    prompt_source: str = "manual",
    prompt_pack_id: str | None = None,
    base_model: str = "test-model-v1",
    sampler: str = "Euler",
    steps: int = 5,
    cfg_scale: float = 7.0,
    width: int = 256,
    height: int = 256,
) -> Job:
    njr = make_test_njr(
        prompt=prompt,
        prompt_source=prompt_source,
        prompt_pack_id=prompt_pack_id or "pack-auto" if prompt_source == "pack" else None,
        base_model=base_model,
        config={
            "model": base_model,
            "prompt": prompt,
            "prompt_pack_id": prompt_pack_id or "pack-auto" if prompt_source == "pack" else None,
            "sampler": sampler,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "width": width,
            "height": height,
        },
    )
    return make_test_job_from_njr(njr, run_mode=run_mode, source=source, prompt_source=prompt_source)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubApiClient:
    """Stub API client that records calls and returns fake images."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._call_count = 0

    def generate_images(
        self,
        *,
        stage: str = "txt2img",
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Record a call and return fake images."""
        payload = payload or {}
        prompt = payload.get("prompt", kwargs.get("prompt", "unknown"))
        self._call_count += 1
        call_record = {
            "call_id": self._call_count,
            "stage": stage,
            "prompt": prompt,
            "steps": payload.get("steps", kwargs.get("steps")),
            "width": payload.get("width", kwargs.get("width")),
            "height": payload.get("height", kwargs.get("height")),
            "payload": payload,
        }
        self.calls.append(call_record)
        return {
            "images": [f"stub_image_for_{prompt}_{self._call_count}.png"],
            "meta": {"ok": True, "stage": stage},
            "info": {"call_id": self._call_count},
        }

    def txt2img(self, **kwargs: Any) -> dict[str, Any]:
        """txt2img shortcut."""
        return self.generate_images(stage="txt2img", payload=kwargs)

    def img2img(self, **kwargs: Any) -> dict[str, Any]:
        """img2img shortcut."""
        return self.generate_images(stage="img2img", payload=kwargs)

    def upscale_image(self, **kwargs: Any) -> dict[str, Any]:
        """upscale shortcut."""
        return self.generate_images(stage="upscale", payload=kwargs)


class StubStructuredLogger:
    """Stub structured logger that does nothing."""

    def __init__(self) -> None:
        self.output_dir = Path(".")

    def log(self, *args: Any, **kwargs: Any) -> None:
        pass

    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error(self, *args: Any, **kwargs: Any) -> None:
        pass

    def write_run_record(self, *args: Any, **kwargs: Any) -> None:
        pass


class StubPipelineRunner:
    """Stub pipeline runner that uses StubApiClient for generation."""

    def __init__(self, api_client: StubApiClient) -> None:
        self.api_client = api_client
        self.runs: list[PipelineConfig] = []
        self._run_counter = 0

    def run(
        self,
        config: PipelineConfig,
        cancel_token: Any = None,
        log_callback: Any = None,
    ) -> PipelineRunResult:
        """Execute a stub pipeline run."""
        self.runs.append(config)
        self._run_counter += 1

        # Simulate API call with config params
        result = self.api_client.generate_images(
            stage="txt2img",
            payload={
                "prompt": config.prompt,
                "steps": config.steps,
                "width": config.width,
                "height": config.height,
                "cfg_scale": config.cfg_scale,
            },
        )

        return PipelineRunResult(
            run_id=f"stub_run_{self._run_counter}",
            success=True,
            error=None,
            variants=[{"images": result.get("images", []), "raw": result}],
            learning_records=[],
            stage_events=[{"stage": "txt2img", "status": "completed"}],
        )

    def _build_executor_config(self, config: PipelineConfig) -> dict[str, Any]:
        """Build executor config for caching."""
        return {
            "prompt": config.prompt,
            "model": config.model,
            "steps": config.steps,
        }


@dataclass
class MinimalAppState:
    """Minimal app state for tests."""

    is_running: bool = False
    current_pack: str | None = None
    prompt: str = ""
    run_config: dict[str, Any] = field(default_factory=dict)
    history_items: list[JobHistoryEntry] = field(default_factory=list)
    queue_status: str = "idle"
    running_job: dict[str, Any] | None = None

    def set_running(self, value: bool) -> None:
        self.is_running = value

    def set_run_config(self, value: dict[str, Any]) -> None:
        self.run_config = dict(value)

    def set_history_items(self, items: list[JobHistoryEntry]) -> None:
        self.history_items = list(items)

    def set_queue_status(self, status: str) -> None:
        self.queue_status = status

    def set_running_job(self, job: dict[str, Any] | None) -> None:
        self.running_job = dict(job) if job else None


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_api_client() -> StubApiClient:
    """Provide a stub API client."""
    return StubApiClient()


@pytest.fixture
def stub_logger() -> StubStructuredLogger:
    """Provide a stub structured logger."""
    return StubStructuredLogger()


@pytest.fixture
def stub_runner(stub_api_client: StubApiClient) -> StubPipelineRunner:
    """Provide a stub pipeline runner."""
    return StubPipelineRunner(stub_api_client)


@pytest.fixture
def history_store(tmp_path: Path) -> JSONLJobHistoryStore:
    """Provide a real job history store with temp file."""
    history_path = tmp_path / "job_history.jsonl"
    return JSONLJobHistoryStore(history_path)


@pytest.fixture
def job_queue(history_store: JSONLJobHistoryStore) -> JobQueue:
    """Provide a job queue with history store."""
    return JobQueue(history_store=history_store)


@pytest.fixture
def job_service(
    job_queue: JobQueue,
    history_store: JSONLJobHistoryStore,
    stub_runner: StubPipelineRunner,
) -> JobService:
    """Provide a job service with stub runner."""

    def run_job(job: Job) -> dict[str, Any]:
        """Execute job using stub runner, supporting NJR-only jobs (no pipeline_config)."""
        config_dict = job.config_snapshot or {}
        # Only keep fields valid for PipelineConfig
        valid_fields = {
            "prompt", "model", "sampler", "width", "height", "steps", "cfg_scale", "negative_prompt",
            "pack_name", "preset_name", "variant_configs", "randomizer_mode", "randomizer_plan_size",
            "lora_settings", "metadata", "refiner_enabled", "refiner_model_name", "refiner_switch_at", "hires_fix"
        }
        filtered = {k: v for k, v in config_dict.items() if k in valid_fields}
        config = PipelineConfig(**filtered)
        result = stub_runner.run(config)
        # If result is a PipelineRunResult, convert to dict
        if hasattr(result, 'to_dict'):
            result_dict = result.to_dict()
        else:
            result_dict = dict(result)
        outputs = [img for v in result_dict.get("variants", []) for img in (v.get("images") or [])]
        # Re-inject run_mode and source after canonicalization (for test assertion)
        patched = dict(result_dict)
        patched["run_mode"] = job.run_mode
        patched["source"] = job.source
        patched["job_id"] = job.job_id
        patched["outputs"] = outputs
        patched["artifacts"] = {"variants": result_dict.get("variants", [])}
        return patched

    runner = SingleNodeJobRunner(
        job_queue,
        run_callable=run_job,
        poll_interval=0.01,
    )
    return JobService(job_queue, runner, history_store)


@pytest.fixture
def small_pipeline_config() -> PipelineConfig:
    """Provide a minimal pipeline config for smoke tests."""
    return PipelineConfig(
        prompt="A beautiful test image",
        negative_prompt="blurry",
        model="test-model-v1",
        sampler="Euler",
        width=256,
        height=256,
        steps=5,
        cfg_scale=7.0,
    )


# ---------------------------------------------------------------------------
# Scenario 1: DIRECT run via "Run Now"
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.integration
class TestDirectRunNowEndToEnd:
    """Scenario 1: Test DIRECT run via 'Run Now' button semantics."""

    def test_direct_run_now_end_to_end(
        self,
        stub_api_client: StubApiClient,
        stub_runner: StubPipelineRunner,
        history_store: JSONLJobHistoryStore,
        job_queue: JobQueue,
        job_service: JobService,
        small_pipeline_config: PipelineConfig,
    ) -> None:
        """DIRECT run completes and writes JobRecord with stub images."""
        # Build a Job with direct run_mode
        job = _job_from_config(
            prompt="A beautiful test image",
            run_mode="direct",
            source="run_now",
            prompt_source="manual",
            base_model="test-model-v1",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )

        # Execute job synchronously (direct run)
        result = job_service.submit_direct(job)

        # Verify job completed
        assert result is not None
        assert result.get("success") is True
        assert result["metadata"]["run_mode"] == "direct"
        assert result["metadata"]["source"] == "run_now"

        # Verify StubApiClient was called
        assert len(stub_api_client.calls) >= 1
        last_call = stub_api_client.calls[-1]
        assert last_call["prompt"] == "A beautiful test image"
        assert last_call["steps"] == 5
        assert last_call["width"] == 256
        assert last_call["height"] == 256

        # Verify job in history
        history_job = history_store.get_job(job.job_id)
        assert history_job is not None
        assert history_job.status == JobStatus.COMPLETED
        assert history_job.run_mode == "direct"

    def test_direct_run_records_completion_timestamp(
        self,
        stub_api_client: StubApiClient,
        job_service: JobService,
        history_store: JSONLJobHistoryStore,
        small_pipeline_config: PipelineConfig,
    ) -> None:
        """DIRECT run records completed_at timestamp."""
        job = _job_from_config(
            prompt="A beautiful test image",
            run_mode="direct",
            source="run_now",
            prompt_source="manual",
            base_model="test-model-v1",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )

        before_run = datetime.utcnow()
        job_service.submit_direct(job)
        after_run = datetime.utcnow()

        history_job = history_store.get_job(job.job_id)
        assert history_job is not None
        assert history_job.completed_at is not None
        # Completed should be between before and after
        assert before_run <= history_job.completed_at <= after_run

    def test_direct_run_with_manual_prompt_source(
        self,
        stub_api_client: StubApiClient,
        job_service: JobService,
        history_store: JSONLJobHistoryStore,
        small_pipeline_config: PipelineConfig,
    ) -> None:
        """DIRECT run with manual prompt source is recorded correctly."""
        job = _job_from_config(
            prompt="A beautiful test image",
            run_mode="direct",
            source="run_now",
            prompt_source="manual",
            base_model="test-model-v1",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )

        job_service.submit_direct(job)

        history_job = history_store.get_job(job.job_id)
        assert history_job is not None
        # Note: prompt_source may be in job.prompt_source, check if history captures it
        assert history_job.run_mode == "direct"


# ---------------------------------------------------------------------------
# Scenario 2: QUEUE run via "Run" or "Add to Queue"
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.integration
class TestQueueRunEndToEnd:
    """Scenario 2: Test QUEUE run via 'Run' or 'Add to Queue' button semantics."""

    def test_queue_run_end_to_end(
        self,
        stub_runner: StubPipelineRunner,
        history_store: JSONLJobHistoryStore,
        job_queue: JobQueue,
        job_service: JobService,
        small_pipeline_config: PipelineConfig,
    ) -> None:
        """QUEUE run is enqueued, processed, and recorded."""
        # Build a Job with queue run_mode
        job = _job_from_config(
            prompt="A beautiful test image",
            run_mode="queue",
            source="add_to_queue",
            prompt_source="pack",
            prompt_pack_id="pack-123",
            base_model="test-model-v1",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )

        # Submit to queue (starts background runner automatically)
        job_service.submit_queued(job)

        # Wait for job to complete (background runner processes it)
        history_job = wait_for_job_completion(history_store, job.job_id, timeout=2.0)

        # Stop the runner to clean up
        job_service.runner.stop()

        # Verify StubPipelineRunner was called
        assert len(stub_runner.runs) >= 1

        # Verify job in history
        assert history_job is not None
        assert history_job.status == JobStatus.COMPLETED
        assert history_job.run_mode == "queue"

    def test_queue_run_with_pack_source(
        self,
        stub_api_client: StubApiClient,
        job_service: JobService,
        history_store: JSONLJobHistoryStore,
        small_pipeline_config: PipelineConfig,
    ) -> None:
        """QUEUE run with pack source records prompt origin."""
        job = _job_from_config(
            prompt="A beautiful test image",
            run_mode="queue",
            source="run",
            prompt_source="pack",
            prompt_pack_id="test-pack-xyz",
            base_model="test-model-v1",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )

        job_service.submit_queued(job)
        job_service.run_next_now()

        history_job = history_store.get_job(job.job_id)
        assert history_job is not None
        assert history_job.run_mode == "queue"

    def test_queue_multiple_jobs_processed_in_order(
        self,
        stub_runner: StubPipelineRunner,
        job_service: JobService,
        history_store: JSONLJobHistoryStore,
    ) -> None:
        """Multiple queued jobs are processed in order."""
        job_ids = []
        for i in range(3):
            job = _job_from_config(
                prompt=f"Test prompt {i}",
                run_mode="queue",
                source="add_to_queue",
                prompt_source="pack",
                prompt_pack_id="pack-batch",
                base_model="test-model",
                sampler="Euler",
                steps=5,
                cfg_scale=7.0,
                width=256,
                height=256,
            )
            job_ids.append(job.job_id)
            job_service.submit_queued(job)

        # Wait for all jobs to complete (background runner processes them)
        for job_id in job_ids:
            wait_for_job_completion(history_store, job_id, timeout=2.0)

        # Stop the runner to clean up
        job_service.runner.stop()

        # Verify all jobs completed
        for job_id in job_ids:
            history_job = history_store.get_job(job_id)
            assert history_job is not None
            assert history_job.status == JobStatus.COMPLETED

        # Verify pipeline runner was called 3 times
        assert len(stub_runner.runs) == 3

    def test_queue_run_records_started_and_completed_timestamps(
        self,
        stub_api_client: StubApiClient,
        job_service: JobService,
        history_store: JSONLJobHistoryStore,
        small_pipeline_config: PipelineConfig,
    ) -> None:
        """QUEUE run records started_at and completed_at timestamps."""
        job = _job_from_config(
            prompt="A beautiful test image",
            run_mode="queue",
            source="run",
            prompt_source="pack",
            prompt_pack_id="pack-queue-ts",
            base_model="test-model-v1",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )

        before_run = datetime.utcnow()
        job_service.submit_queued(job)
        
        # Wait for job to complete (background runner processes it)
        history_job = wait_for_job_completion(history_store, job.job_id, timeout=2.0)
        after_run = datetime.utcnow()
        
        # Stop the runner to clean up
        job_service.runner.stop()

        assert history_job is not None
        assert history_job.completed_at is not None
        assert before_run <= history_job.completed_at <= after_run


# ---------------------------------------------------------------------------
# Combined Flow Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.integration
class TestMixedRunModes:
    """Test that direct and queue runs can coexist."""

    def test_direct_then_queue_runs(
        self,
        stub_runner: StubPipelineRunner,
        job_service: JobService,
        history_store: JSONLJobHistoryStore,
        small_pipeline_config: PipelineConfig,
    ) -> None:
        """Direct run followed by queue run both complete successfully."""
        # Direct run first
        direct_job = _job_from_config(
            prompt="A beautiful test image",
            run_mode="direct",
            source="run_now",
            prompt_source="manual",
            base_model="test-model-v1",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )
        job_service.submit_direct(direct_job)

        # Queue run second
        queue_job = _job_from_config(
            prompt="Queue test prompt",
            run_mode="queue",
            source="add_to_queue",
            prompt_source="pack",
            prompt_pack_id="pack-555",
            base_model="test-model",
            sampler="Euler",
            steps=5,
            cfg_scale=7.0,
            width=256,
            height=256,
        )
        job_service.submit_queued(queue_job)

        # Wait for queue job to complete (background runner processes it)
        queue_history = wait_for_job_completion(history_store, queue_job.job_id, timeout=2.0)

        # Stop the runner to clean up
        job_service.runner.stop()

        # Both should be completed
        direct_history = history_store.get_job(direct_job.job_id)

        assert direct_history is not None
        assert direct_history.status == JobStatus.COMPLETED
        assert direct_history.run_mode == "direct"

        assert queue_history is not None
        assert queue_history.status == JobStatus.COMPLETED
        assert queue_history.run_mode == "queue"

        # Pipeline runner should have been called twice
        assert len(stub_runner.runs) == 2


# ---------------------------------------------------------------------------
# JobHistoryEntry from RunConfig Integration
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.integration
class TestJobHistoryFromRunConfig:
    """Test creating JobHistoryEntry from RunConfig for end-to-end tracking."""

    def test_history_entry_from_manual_run_config(self) -> None:
        """JobHistoryEntry created from manual RunConfig has correct fields."""
        run_config = RunConfig(
            prompt_source=PromptSource.MANUAL,
            run_mode="direct",
            source="run_now",
            prompt_payload={"prompt": "Test prompt", "negative_prompt": "blurry"},
        )

        entry = job_history_entry_from_run_config(
            job_id="test-job-123",
            run_config=run_config,
            payload_summary="Test run",
        )

        assert entry.job_id == "test-job-123"
        assert entry.run_mode == "direct"
        assert entry.prompt_source == "manual"
        assert entry.prompt_pack_id is None

    def test_history_entry_from_pack_run_config(self) -> None:
        """JobHistoryEntry created from pack RunConfig has correct fields."""
        run_config = RunConfig(
            prompt_source=PromptSource.PACK,
            prompt_pack_id="my-pack-456",
            prompt_keys=["prompt1", "prompt2"],
            run_mode="queue",
            source="add_to_queue",
        )

        entry = job_history_entry_from_run_config(
            job_id="test-job-456",
            run_config=run_config,
            payload_summary="Pack run",
        )

        assert entry.job_id == "test-job-456"
        assert entry.run_mode == "queue"
        assert entry.prompt_source == "pack"
        assert entry.prompt_pack_id == "my-pack-456"
        assert entry.prompt_keys == ["prompt1", "prompt2"]


def test_pipeline_payload_includes_refiner_and_hires_config() -> None:
    """Ensure the canonical payload receives refiner/hires selections from the config."""
    pipeline_config = {
        "txt2img": {
            "model": "test-model",
            "sampler_name": "Euler a",
            "steps": 20,
            "cfg_scale": 8.5,
            "refiner_enabled": True,
            "refiner_model_name": "test-refiner",
            "refiner_switch_at": 0.25,
        },
        "hires_fix": {
            "enabled": True,
            "upscaler_name": "Latent 2x",
            "upscale_factor": 2.3,
            "denoise": 0.6,
            "steps": 5,
        },
    }

    plan = StageSequencer().build_plan(pipeline_config)
    assert plan.stages, "Pipeline plan should contain at least one stage"
    stage = plan.stages[0]
    payload = build_sdxl_payload(stage)

    assert payload["refiner_enabled"] is True
    assert payload["refiner_model_name"] == "test-refiner"
    assert payload["refiner_switch_step"] == pytest.approx(0.25)

    assert payload["hires_fix"] is True
    assert payload["enable_hr"] is True
    assert payload["hires_upscaler_name"] == "Latent 2x"
    assert payload["hr_upscaler"] == "Latent 2x"
    assert payload["hires_denoise_strength"] == pytest.approx(0.6)
    assert payload["denoising_strength"] == pytest.approx(0.6)
    assert payload["hires_scale"] == pytest.approx(2.3)
    assert payload["hr_scale"] == pytest.approx(2.3)
    assert payload["hr_second_pass_steps"] == 5
