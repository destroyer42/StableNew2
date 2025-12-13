# Subsystem: Pipeline/Queue
# Role: Tests for PR-106 RunMode enforcement in PipelineController

"""Tests for run_mode (direct vs queue) enforcement and Job metadata population."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2


class TestJobMetadataFields:
    """Tests for PR-106 Step 1: Job model metadata fields."""

    def test_job_has_source_field(self):
        """Job should have source field with default 'unknown'."""
        job = Job(job_id="test-1")
        assert hasattr(job, "source")
        assert job.source == "unknown"

    def test_job_has_prompt_source_field(self):
        """Job should have prompt_source field with default 'manual'."""
        job = Job(job_id="test-1")
        assert hasattr(job, "prompt_source")
        assert job.prompt_source == "manual"

    def test_job_has_prompt_pack_id_field(self):
        """Job should have prompt_pack_id field with default None."""
        job = Job(job_id="test-1")
        assert hasattr(job, "prompt_pack_id")
        assert job.prompt_pack_id is None

    def test_job_has_config_snapshot_field(self):
        """Job should have config_snapshot field with default None."""
        job = Job(job_id="test-1")
        assert hasattr(job, "config_snapshot")
        assert job.config_snapshot is None

    def test_job_with_custom_metadata(self):
        """Job should accept custom metadata values."""
        job = Job(
            job_id="test-1",
            source="gui",
            prompt_source="pack",
            prompt_pack_id="heroes-journey-v1",
            config_snapshot={"prompt": "test", "steps": 20},
        )
        assert job.source == "gui"
        assert job.prompt_source == "pack"
        assert job.prompt_pack_id == "heroes-journey-v1"
        assert job.config_snapshot == {"prompt": "test", "steps": 20}

    def test_job_to_dict_includes_metadata(self):
        """Job.to_dict() should include all metadata fields."""
        job = Job(
            job_id="test-1",
            source="api",
            prompt_source="randomizer",
            prompt_pack_id="pack-123",
            config_snapshot={"model": "sdxl"},
        )
        data = job.to_dict()
        assert data["source"] == "api"
        assert data["prompt_source"] == "randomizer"
        assert data["prompt_pack_id"] == "pack-123"
        assert data["config_snapshot"] == {"model": "sdxl"}


class TestRunModeEnforcement:
    """Tests for PR-106 Step 3-5: RunMode enforcement via JobService."""

    @pytest.fixture
    def job_queue(self):
        return JobQueue()

    @pytest.fixture
    def mock_runner(self, job_queue):
        runner = SingleNodeJobRunner(
            job_queue=job_queue,
            run_callable=lambda job: {"result": "ok"},
        )
        return runner

    @pytest.fixture
    def job_service(self, job_queue, mock_runner):
        return JobService(job_queue, mock_runner)

    def test_submit_direct_executes_synchronously(self, job_service):
        """submit_direct should execute job immediately and return result."""
        job = Job(
            job_id=str(uuid.uuid4()),
            run_mode="direct",
        )
        result = job_service.submit_direct(job)
        assert result == {"result": "ok"}
        assert job.status == JobStatus.COMPLETED

    def test_submit_queued_adds_to_queue(self, job_service, job_queue):
        """submit_queued should add job to queue without blocking."""
        job = Job(
            job_id=str(uuid.uuid4()),
            run_mode="queue",
        )
        job_service.submit_queued(job)
        # Job should be in queue
        jobs = job_queue.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].job_id == job.job_id

    def test_submit_job_with_run_mode_routes_direct(self, job_service):
        """submit_job_with_run_mode should call submit_direct for 'direct' mode."""
        job = Job(
            job_id=str(uuid.uuid4()),
            run_mode="direct",
        )
        with patch.object(job_service, "submit_direct") as mock_direct:
            job_service.submit_job_with_run_mode(job)
            mock_direct.assert_called_once_with(job)

    def test_submit_job_with_run_mode_routes_queue(self, job_service):
        """submit_job_with_run_mode should call submit_queued for 'queue' mode."""
        job = Job(
            job_id=str(uuid.uuid4()),
            run_mode="queue",
        )
        with patch.object(job_service, "submit_queued") as mock_queued:
            job_service.submit_job_with_run_mode(job)
            mock_queued.assert_called_once_with(job)

    def test_submit_job_with_run_mode_defaults_to_queue(self, job_service):
        """submit_job_with_run_mode should default to queue if run_mode is empty."""
        job = Job(
            job_id=str(uuid.uuid4()),
            run_mode="",
        )
        with patch.object(job_service, "submit_queued") as mock_queued:
            job_service.submit_job_with_run_mode(job)
            mock_queued.assert_called_once_with(job)


class TestPipelineControllerBuildJob:
    """Tests for PR-106 Step 2: PipelineController._build_job helper."""

    def test_build_job_creates_job_with_metadata(self):
        """_build_job should create a Job with all metadata fields populated."""
        from src.controller.pipeline_controller import PipelineController

        controller = PipelineController(app_state=AppStateV2())
        
        job = controller._build_job(
            config=None,
            run_mode="direct",
            source="gui",
            prompt_source="pack",
            prompt_pack_id="test-pack-1",
        )
        
        assert job.run_mode == "direct"
        assert job.source == "gui"
        assert job.prompt_source == "pack"
        assert job.prompt_pack_id == "test-pack-1"
        assert job.priority == JobPriority.NORMAL
        assert job.job_id is not None

    def test_build_job_creates_config_snapshot(self):
        """_build_job should create config_snapshot from PipelineConfig."""
        from src.controller.pipeline_controller import PipelineController
        from src.controller.archive.pipeline_config_types import PipelineConfig

        controller = PipelineController(app_state=AppStateV2())

        config = PipelineConfig(
            prompt="a beautiful sunset",
            model="sd_xl_base_1.0",
            sampler="Euler a",
            steps=25,
            cfg_scale=7.5,
            width=1024,
            height=1024,
        )

        job = controller._build_job(config=config, source="test")
        
        assert job.config_snapshot is not None
        assert job.config_snapshot.get("prompt") == "a beautiful sunset"
        assert job.config_snapshot.get("model") == "sd_xl_base_1.0"
        assert job.config_snapshot.get("steps") == 25

    def test_build_job_defaults(self):
        """_build_job should use sensible defaults for optional fields."""
        from src.controller.pipeline_controller import PipelineController

        controller = PipelineController(app_state=AppStateV2())
        
        job = controller._build_job(config=None)
        
        assert job.run_mode == "queue"
        assert job.source == "gui"
        assert job.prompt_source == "manual"
        assert job.prompt_pack_id is None
        assert job.learning_enabled is False
