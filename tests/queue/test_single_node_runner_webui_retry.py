import pytest
from unittest.mock import Mock, patch

from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
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

    with patch("src.queue.single_node_runner.get_global_webui_process_manager", return_value=manager):
        result = runner.run_once(job)

    assert result["success"] is True
    assert job.status == JobStatus.COMPLETED
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

    with patch("src.queue.single_node_runner.get_global_webui_process_manager", return_value=manager):
        with pytest.raises(RuntimeError):
            runner.run_once(job_failure)
        success_result = runner.run_once(job_success)

    assert success_result["success"] is True
    assert job_failure.status == JobStatus.FAILED
    assert len(job_failure.execution_metadata.retry_attempts) == 1
    assert job_failure.execution_metadata.retry_attempts[0].reason == "QUEUE_JOB_WEBUI_CRASH_SUSPECTED"
    assert manager.restart_webui.call_count == 1
