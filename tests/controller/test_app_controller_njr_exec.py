"""Tests for AppController._execute_job NJR-only execution (PR-CORE1-B2).

Validates that _execute_job:
- Uses NJR path (_run_job) when normalized_record is present (NJR-only, no fallback)
- Marks job as failed if NJR execution fails (no pipeline_config fallback)
- Uses pipeline_config ONLY for legacy jobs without NJR
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

import pytest

from src.controller.app_controller import AppController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineConfig
from src.queue.job_model import Job, JobPriority


@pytest.fixture
def mock_app_controller():
    """Create AppController with mocked dependencies."""
    with patch("src.controller.app_controller.AppController.__init__", return_value=None):
        controller = AppController.__new__(AppController)
        controller.pipeline_controller = Mock()
        controller._append_log = Mock()
        controller._run_pipeline_via_runner_only = Mock(return_value={"status": "success"})
        return controller


@pytest.fixture
def dummy_njr() -> NormalizedJobRecord:
    """Create a dummy NormalizedJobRecord for testing."""
    return NormalizedJobRecord(
        job_id="test-njr-123",
        config={"prompt": "test prompt", "model": "sdxl"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=12345,
        positive_prompt="test prompt",
        base_model="sdxl",
    )


@pytest.fixture
def dummy_pipeline_config() -> PipelineConfig:
    """Create a dummy PipelineConfig for testing."""
    return PipelineConfig(
        prompt="test prompt",
        model="sdxl",
        sampler="Euler a",
        steps=20,
        cfg_scale=7.5,
        width=1024,
        height=1024,
    )


class TestNJRPreferredExecution:
    """Test NJR-preferred execution path in _execute_job."""

    def test_njr_backed_job_uses_run_job(self, mock_app_controller, dummy_njr, dummy_pipeline_config):
        """NJR-backed job should call pipeline_controller._run_job."""
        # Setup
        job = Job(
            job_id="test-job-1",
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = dummy_njr
        job.pipeline_config = dummy_pipeline_config
        
        mock_app_controller.pipeline_controller._run_job.return_value = {"path": "njr", "status": "ok"}
        
        # Execute
        result = mock_app_controller._execute_job(job)
        
        # Assert
        assert result["mode"] == "njr"
        assert result["job_id"] == "test-job-1"
        mock_app_controller.pipeline_controller._run_job.assert_called_once_with(job)
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()

    def test_njr_failure_marks_job_as_failed_no_fallback(self, mock_app_controller, dummy_njr, dummy_pipeline_config):
        """PR-CORE1-B2: When _run_job fails for NJR job, mark as failed (NO fallback to pipeline_config)."""
        # Setup
        job = Job(
            job_id="test-job-2",
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = dummy_njr
        job.pipeline_config = dummy_pipeline_config
        
        # Make _run_job raise an exception
        mock_app_controller.pipeline_controller._run_job.side_effect = RuntimeError("NJR execution failed")
        
        # Execute
        result = mock_app_controller._execute_job(job)
        
        # Assert: Job is marked as failed (error status), NO fallback to pipeline_config
        assert result["status"] == "error"
        assert result["mode"] == "njr"
        assert result["job_id"] == "test-job-2"
        assert "NJR execution failed" in result["error"]
        mock_app_controller.pipeline_controller._run_job.assert_called_once_with(job)
        # PR-CORE1-B2: pipeline_config fallback should NOT be called for NJR jobs
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()

    def test_legacy_job_without_njr_uses_pipeline_config(self, mock_app_controller, dummy_pipeline_config):
        """Legacy job without NJR should use pipeline_config directly."""
        # Setup
        job = Job(
            job_id="test-job-3",
            priority=JobPriority.NORMAL,
        )
        # No _normalized_record attribute
        job.pipeline_config = dummy_pipeline_config
        
        mock_app_controller._run_pipeline_via_runner_only.return_value = {"status": "success"}
        
        # Execute
        result = mock_app_controller._execute_job(job)
        
        # Assert
        assert result["mode"] == "pipeline_config"
        assert result["job_id"] == "test-job-3"
        mock_app_controller.pipeline_controller._run_job.assert_not_called()
        mock_app_controller._run_pipeline_via_runner_only.assert_called_once_with(dummy_pipeline_config)

    def test_njr_without_pipeline_controller_falls_back(self, mock_app_controller, dummy_njr, dummy_pipeline_config):
        """If pipeline_controller is None, should fall back to pipeline_config."""
        # Setup
        job = Job(
            job_id="test-job-4",
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = dummy_njr
        job.pipeline_config = dummy_pipeline_config
        
        mock_app_controller.pipeline_controller = None  # No controller
        
        # Execute
        result = mock_app_controller._execute_job(job)
        
        # Assert
        assert result["mode"] == "pipeline_config"
        mock_app_controller._run_pipeline_via_runner_only.assert_called_once_with(dummy_pipeline_config)

    def test_njr_with_none_record_falls_back(self, mock_app_controller, dummy_pipeline_config):
        """If _normalized_record is None, should fall back to pipeline_config."""
        # Setup
        job = Job(
            job_id="test-job-5",
            priority=JobPriority.NORMAL,
        )
        job._normalized_record = None  # Explicitly None
        job.pipeline_config = dummy_pipeline_config
        
        # Execute
        result = mock_app_controller._execute_job(job)
        
        # Assert
        assert result["mode"] == "pipeline_config"
        mock_app_controller.pipeline_controller._run_job.assert_not_called()
        mock_app_controller._run_pipeline_via_runner_only.assert_called_once_with(dummy_pipeline_config)

    def test_payload_job_without_njr_or_pipeline_config_returns_error(self, mock_app_controller):
        """Payload-only jobs should be rejected now that PR-CORE1-B5 removed payload execution paths."""
        job = Job(
            job_id="test-job-6",
            priority=JobPriority.NORMAL,
        )
        job.payload = {"packs": []}
        job.pipeline_config = None

        result = mock_app_controller._execute_job(job)

        assert result["status"] == "error"
        assert result["mode"] == "missing"
        assert "No executable path" in result["error"]
        mock_app_controller.pipeline_controller._run_job.assert_not_called()
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()
