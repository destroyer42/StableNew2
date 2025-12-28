from unittest.mock import Mock, patch

import pytest

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import (
    SingleNodeJobRunner,
    _clear_timeout_tracking,
    _consecutive_timeout_counts,
    _is_webui_crash_exception,
    _TIMEOUT_ESCALATION_THRESHOLD,
)
from src.utils.error_envelope_v2 import wrap_exception


def _build_crash_exception(
    *,
    stage: str = "txt2img",
    status: int | None = 500,
    webui_unavailable: bool = False,
    message: str = "Simulated WebUI failure",
) -> Exception:
    exc = RuntimeError(message)
    wrap_exception(
        exc,
        subsystem="pipeline",
        stage=stage,
        context={
            "diagnostics": {
                "request_summary": {
                    "endpoint": f"/sdapi/v1/{stage}",
                    "method": "POST",
                    "stage": stage,
                    "status": status,
                    "session_id": "session-123",
                },
                "webui_unavailable": webui_unavailable,
                "crash_suspected": False,
                "error_message": message,
            }
        },
    )
    return exc


def _build_timeout_exception(
    *,
    stage: str = "txt2img",
    message: str = "Read timed out",
) -> Exception:
    """Build a timeout exception for testing timeout escalation."""
    exc = RuntimeError(message)
    wrap_exception(
        exc,
        subsystem="pipeline",
        stage=stage,
        context={
            "diagnostics": {
                "request_summary": {
                    "endpoint": f"/sdapi/v1/{stage}",
                    "method": "POST",
                    "stage": stage,
                    "status": None,  # Timeout has no HTTP status
                    "session_id": "session-123",
                },
                "webui_unavailable": False,
                "crash_suspected": False,
                "error_message": message,
            }
        },
    )
    return exc


def test_runner_retries_webui_crash_once():
    queue = JobQueue()
    failure = _build_crash_exception()
    calls: list[str] = []

    def run_callable(job: Job) -> dict:
        calls.append(job.job_id)
        if len(calls) == 1:
            raise failure
        return {"success": True}

    runner = SingleNodeJobRunner(queue, run_callable, poll_interval=0.01)
    job = Job(job_id="job-1")
    manager = Mock()
    manager.restart_webui.return_value = True

    with patch(
        "src.queue.single_node_runner.get_global_webui_process_manager", return_value=manager
    ):
        result = runner.run_once(job)

    assert result["success"] is True
    # Note: job.status is not set by run_once - it's set by the queue loop
    # Just verify the retry mechanism worked
    assert len(job.execution_metadata.retry_attempts) == 1
    attempt = job.execution_metadata.retry_attempts[0]
    assert attempt.attempt_index == 2
    assert attempt.reason == "QUEUE_JOB_WEBUI_CRASH_SUSPECTED"
    manager.restart_webui.assert_called_once()


def test_runner_retries_webui_connection_failure_and_queue_continues():
    queue = JobQueue()
    failure = _build_crash_exception(
        stage="txt2img",
        webui_unavailable=True,
        message="Connection refused while contacting WebUI",
    )

    def run_callable(job: Job) -> dict:
        if job.job_id == "always-fail":
            raise failure
        return {"success": True}

    runner = SingleNodeJobRunner(queue, run_callable, poll_interval=0.01)
    job_failure = Job(job_id="always-fail")
    job_success = Job(job_id="job-2")
    manager = Mock()
    manager.restart_webui.return_value = True

    with patch(
        "src.queue.single_node_runner.get_global_webui_process_manager", return_value=manager
    ):
        with pytest.raises(RuntimeError):
            runner.run_once(job_failure)
        success_result = runner.run_once(job_success)

    assert success_result["success"] is True
    # Note: job.status is not set by run_once - it's set by the queue loop
    # PR-WEBUI-RECOVERY-001: Now retries 4 times (5 total attempts) before giving up
    assert len(job_failure.execution_metadata.retry_attempts) == 4
    assert (
        job_failure.execution_metadata.retry_attempts[0].reason == "QUEUE_JOB_WEBUI_CRASH_SUSPECTED"
    )
    # 4 retries = 4 restart calls
    assert manager.restart_webui.call_count == 4


# === PR-WEBUI-RECOVERY-001: New tests for HTTP 500 detection and timeout escalation ===


class TestHttp500Detection:
    """Tests for HTTP 500 crash detection (PR-WEBUI-RECOVERY-001)."""

    def test_http_500_triggers_crash_recovery(self):
        """HTTP 500 on crash-eligible stage should trigger recovery."""
        exc = _build_crash_exception(
            stage="txt2img",
            status=500,
            message="Internal server error",
        )
        crash_eligible, stage = _is_webui_crash_exception(exc, job_id="test-job")
        assert crash_eligible is True
        assert stage == "txt2img"

    def test_http_500_on_non_crash_stage_no_recovery(self):
        """HTTP 500 on non-crash-eligible stage should not trigger recovery."""
        exc = _build_crash_exception(
            stage="options",  # Not in _CRASH_ELIGIBLE_STAGES
            status=500,
            message="Internal server error",
        )
        crash_eligible, stage = _is_webui_crash_exception(exc, job_id="test-job")
        # options is not crash-eligible, but the function still returns stage
        assert crash_eligible is False

    def test_http_400_no_recovery(self):
        """HTTP 400 (client error) should not trigger recovery."""
        exc = _build_crash_exception(
            stage="txt2img",
            status=400,
            message="Bad request",
        )
        crash_eligible, stage = _is_webui_crash_exception(exc, job_id="test-job")
        assert crash_eligible is False


class TestTimeoutEscalation:
    """Tests for timeout escalation logic (PR-WEBUI-RECOVERY-001)."""

    def setup_method(self):
        """Clear timeout tracking before each test."""
        _consecutive_timeout_counts.clear()

    def teardown_method(self):
        """Clear timeout tracking after each test."""
        _consecutive_timeout_counts.clear()

    def test_single_timeout_no_crash(self):
        """Single timeout should not trigger crash recovery."""
        exc = _build_timeout_exception(message="Read timed out")
        crash_eligible, stage = _is_webui_crash_exception(exc, job_id="test-job")
        assert crash_eligible is False
        assert _consecutive_timeout_counts.get("test-job") == 1

    def test_two_timeouts_no_crash(self):
        """Two consecutive timeouts should not trigger crash recovery."""
        exc = _build_timeout_exception(message="Read timed out")
        
        # First timeout
        crash_eligible, _ = _is_webui_crash_exception(exc, job_id="test-job")
        assert crash_eligible is False
        
        # Second timeout
        crash_eligible, _ = _is_webui_crash_exception(exc, job_id="test-job")
        assert crash_eligible is False
        assert _consecutive_timeout_counts.get("test-job") == 2

    def test_three_timeouts_triggers_crash(self):
        """Three consecutive timeouts should trigger crash recovery."""
        exc = _build_timeout_exception(message="Read timed out")
        
        # First two timeouts - no crash
        for _ in range(_TIMEOUT_ESCALATION_THRESHOLD - 1):
            crash_eligible, _ = _is_webui_crash_exception(exc, job_id="test-job")
            assert crash_eligible is False
        
        # Third timeout - should escalate to crash
        crash_eligible, stage = _is_webui_crash_exception(exc, job_id="test-job")
        assert crash_eligible is True
        assert stage == "txt2img"

    def test_non_timeout_error_resets_counter(self):
        """Non-timeout error should reset the timeout counter."""
        timeout_exc = _build_timeout_exception(message="Read timed out")
        crash_exc = _build_crash_exception(status=500)
        
        # Build up timeout count
        _is_webui_crash_exception(timeout_exc, job_id="test-job")
        _is_webui_crash_exception(timeout_exc, job_id="test-job")
        assert _consecutive_timeout_counts.get("test-job") == 2
        
        # Non-timeout error resets counter
        _is_webui_crash_exception(crash_exc, job_id="test-job")
        assert _consecutive_timeout_counts.get("test-job") is None

    def test_clear_timeout_tracking(self):
        """_clear_timeout_tracking should remove job from tracking."""
        _consecutive_timeout_counts["test-job"] = 5
        _clear_timeout_tracking("test-job")
        assert "test-job" not in _consecutive_timeout_counts

    def test_different_jobs_tracked_separately(self):
        """Timeout counts should be tracked separately per job."""
        exc = _build_timeout_exception(message="Read timed out")
        
        # Job 1 gets 2 timeouts
        _is_webui_crash_exception(exc, job_id="job-1")
        _is_webui_crash_exception(exc, job_id="job-1")
        
        # Job 2 gets 1 timeout
        _is_webui_crash_exception(exc, job_id="job-2")
        
        assert _consecutive_timeout_counts.get("job-1") == 2
        assert _consecutive_timeout_counts.get("job-2") == 1

    def test_timeout_without_job_id_no_tracking(self):
        """Timeout without job_id should not track or escalate."""
        exc = _build_timeout_exception(message="Read timed out")
        
        # Call many times without job_id
        for _ in range(10):
            crash_eligible, _ = _is_webui_crash_exception(exc, job_id=None)
            assert crash_eligible is False
        
        # No tracking occurred
        assert len(_consecutive_timeout_counts) == 0
