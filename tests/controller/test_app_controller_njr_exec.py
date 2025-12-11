"""Tests for AppController._execute_job NJR-only execution (PR-CORE1-D11).

Validates that _execute_job:
- Uses NJR path (_run_job) when normalized_record is present (NJR-only)
- Marks job as failed if NJR execution fails
- Rejects jobs without normalized_record (no pipeline_config fallback)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

import pytest

from src.controller.app_controller import AppController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunResult
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


class TestNJRPreferredExecution:
    """Test NJR-preferred execution path in _execute_job."""

    def _canonical_job_result(self, job_id: str) -> dict[str, Any]:
        return PipelineRunResult(
            run_id=job_id,
            success=True,
            error=None,
            variants=[],
            learning_records=[],
            metadata={},
        ).to_dict()

    def test_njr_backed_job_uses_run_job(self, mock_app_controller, dummy_njr):
        """NJR-backed job should call pipeline_controller._run_job."""
        job = Job(job_id="test-job-1", priority=JobPriority.NORMAL)
        job._normalized_record = dummy_njr

        mock_app_controller.pipeline_controller._run_job.return_value = self._canonical_job_result(job.job_id)

        result = mock_app_controller._execute_job(job)

        assert result["success"] is True
        assert result["metadata"]["execution_path"] == "njr"
        assert result["metadata"]["job_id"] == job.job_id
        mock_app_controller.pipeline_controller._run_job.assert_called_once_with(job)
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()

    def test_njr_failure_marks_job_as_failed(self, mock_app_controller, dummy_njr):
        """When _run_job fails for NJR job, mark as failed (no fallback)."""
        job = Job(job_id="test-job-2", priority=JobPriority.NORMAL)
        job._normalized_record = dummy_njr

        mock_app_controller.pipeline_controller._run_job.side_effect = RuntimeError("NJR execution failed")

        result = mock_app_controller._execute_job(job)

        assert result["success"] is False
        assert "NJR execution failed" in result["error"]
        assert result["metadata"]["execution_path"] == "njr"
        assert result["metadata"]["job_id"] == job.job_id
        mock_app_controller.pipeline_controller._run_job.assert_called_once_with(job)
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()

    def test_job_without_njr_is_rejected(self, mock_app_controller):
        """Jobs without normalized_record are rejected (no pipeline_config fallback)."""
        job = Job(job_id="test-job-3", priority=JobPriority.NORMAL)

        result = mock_app_controller._execute_job(job)

        assert result["success"] is False
        assert "missing normalized_record" in (result.get("error") or "").lower()
        assert result["metadata"]["execution_path"] == "missing_njr"
        assert result["metadata"]["job_id"] == job.job_id
        mock_app_controller.pipeline_controller._run_job.assert_not_called()
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()

    def test_njr_without_pipeline_controller_is_rejected(self, mock_app_controller, dummy_njr):
        """If pipeline_controller is None, job is rejected (no fallback)."""
        job = Job(job_id="test-job-4", priority=JobPriority.NORMAL)
        job._normalized_record = dummy_njr

        mock_app_controller.pipeline_controller = None

        result = mock_app_controller._execute_job(job)

        assert result["success"] is False
        assert result["metadata"]["execution_path"] == "missing_njr"
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()

    def test_njr_with_none_record_is_rejected(self, mock_app_controller):
        """If _normalized_record is None, job is rejected."""
        job = Job(job_id="test-job-5", priority=JobPriority.NORMAL)
        job._normalized_record = None

        result = mock_app_controller._execute_job(job)

        assert result["success"] is False
        assert result["metadata"]["execution_path"] == "missing_njr"
        mock_app_controller.pipeline_controller._run_job.assert_not_called()
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()

    def test_payload_job_without_njr_or_pipeline_config_returns_error(self, mock_app_controller):
        """Payload-only jobs should be rejected now that PR-CORE1-B5 removed payload execution paths."""
        job = Job(job_id="test-job-6", priority=JobPriority.NORMAL)
        job.payload = {"packs": []}

        result = mock_app_controller._execute_job(job)

        assert result["success"] is False
        assert "missing normalized_record" in (result.get("error") or "").lower()
        assert result["metadata"]["execution_path"] == "missing_njr"
        mock_app_controller.pipeline_controller._run_job.assert_not_called()
        mock_app_controller._run_pipeline_via_runner_only.assert_not_called()
