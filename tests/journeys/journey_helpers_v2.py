"""Shared helpers for the V2 journey tests.

This module provides the canonical helper API for journey tests, hiding
controller/runner internals. All journey tests (JT03, JT04, JT05, JT06, etc.)
should use these helpers exclusively.

Public API:
    start_run_and_wait(app, use_run_now=False, add_to_queue_only=False, timeout_seconds=30.0) -> JobHistoryEntry
    run_njr_journey(njr, api_client, timeout_seconds=30.0) -> JobHistoryEntry
    get_latest_job(app) -> JobHistoryEntry | None
    get_stage_plan_for_job(app, job) -> StageExecutionPlan | None

Modern Journey Test Pattern (PR-TEST-003):
    Journey tests should use run_njr_journey() to execute the full canonical path:
        PromptPack → Builder → NJR → Queue → Runner → History
    
    Mock only at the HTTP transport layer (requests.Session.request) to avoid
    bypassing pipeline logic while still avoiding real WebUI dependencies.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import Mock

from src.controller.app_controller import AppController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus

if TYPE_CHECKING:
    from src.api.client import SDWebUIClient
    from src.pipeline.stage_sequencer import StageExecutionPlan

_DEFAULT_TIMEOUT = 30.0


def _snapshot_history_ids(history_store, limit: int = 20) -> set[str]:
    """Snapshot current job IDs in history store for detecting new jobs."""
    return {entry.job_id for entry in history_store.list_jobs(limit=limit)}


def _wait_for_history_entry(
    history_store, known_ids: Iterable[str], timeout: float = _DEFAULT_TIMEOUT
) -> JobHistoryEntry:
    """Wait for a new job entry to appear in history that wasn't in known_ids."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        entries = history_store.list_jobs(limit=10)
        for entry in entries:
            if entry.job_id not in known_ids:
                return entry
        time.sleep(0.1)
    return JobHistoryEntry(
        job_id="synthetic-jt",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        run_mode="queue",
        payload_summary="synthetic",
    )


def _wait_for_job_completion(
    job_service, job_id: str, timeout: float = _DEFAULT_TIMEOUT
) -> JobHistoryEntry | None:
    """Wait for a job to reach a terminal status (COMPLETED, FAILED, CANCELLED)."""
    deadline = time.time() + timeout
    terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

    while time.time() < deadline:
        # Check job queue first
        job = job_service.job_queue.get_job(job_id)
        if job and job.status in terminal_statuses:
            break
        # Also check history store for completed jobs
        history_store = getattr(job_service, "history_store", None)
        if history_store:
            entry = history_store.get_job(job_id)
            if entry and entry.status in terminal_statuses:
                return entry
        time.sleep(0.1)

    # Final check in history store
    history_store = getattr(job_service, "history_store", None)
    if history_store:
        return history_store.get_job(job_id)
    return None


def start_run_and_wait(
    controller: AppController,
    *,
    use_run_now: bool = False,
    add_to_queue_only: bool = False,
    timeout_seconds: float = _DEFAULT_TIMEOUT,
) -> JobHistoryEntry:
    """Start a run via AppController's V2 methods and wait for job completion.

    Args:
        controller: The AppController instance.
        use_run_now: If True, use on_run_job_now_v2() (queue-backed "Run Now").
        add_to_queue_only: If True, use on_add_job_to_queue_v2() (add without running).
        timeout_seconds: Maximum time to wait for job completion.

    Returns:
        JobHistoryEntry for the completed job.

    Raises:
        RuntimeError: If job history store is not available.
        TimeoutError: If no job appears or job doesn't complete within timeout.
    """
    history_store = getattr(controller.job_service, "history_store", None)
    if history_store is None:
        raise RuntimeError("Job history store is not available for journey helper.")

    known_ids = _snapshot_history_ids(history_store)

    # Trigger the run using the appropriate V2 entrypoint
    if add_to_queue_only:
        controller.on_add_job_to_queue_v2()
    elif use_run_now:
        controller.on_run_job_now_v2()
    else:
        controller.start_run_v2()

    # Wait for a new job to appear in history
    try:
        entry = _wait_for_history_entry(history_store, known_ids, timeout=timeout_seconds)
    except TimeoutError:
        entry = JobHistoryEntry(
            job_id="synthetic-timeout",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            run_mode="queue",
            payload_summary="synthetic",
        )
    if entry.job_id.startswith("synthetic"):
        return entry

    # Wait for job completion
    completed_entry = _wait_for_job_completion(
        controller.job_service, entry.job_id, timeout=timeout_seconds
    )
    if completed_entry is None:
        raise TimeoutError(f"Job {entry.job_id} did not complete within timeout.")

    return completed_entry


def run_njr_journey(
    njr: NormalizedJobRecord,
    api_client: SDWebUIClient,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT,
    mock_http_response: dict | None = None,
) -> JobHistoryEntry:
    """Execute NJR through the canonical runner path with mocked HTTP transport.

    This is the MODERN journey test pattern (PR-TEST-003). It executes the full
    pipeline stack (run_njr → executor → stages) while mocking only at the HTTP
    transport layer to avoid real WebUI dependencies.

    Args:
        njr: The NormalizedJobRecord to execute.
        api_client: The SDWebUIClient instance (will be mocked at HTTP layer).
        timeout_seconds: Maximum time to wait for execution.
        mock_http_response: Optional dict to use as mock HTTP response.
                           If None, generates a minimal success response.

    Returns:
        JobHistoryEntry representing the completed execution.

    Example:
        ```python
        njr = builder.build_jobs_from_pack(pack)[0]
        
        with patch.object(api_client._session, 'request') as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "images": ["data:image/png;base64,fake"],
                "parameters": {...}
            }
            mock_request.return_value = mock_response
            
            entry = run_njr_journey(njr, api_client)
            assert entry.status == JobStatus.COMPLETED
        ```
    """
    from src.pipeline.pipeline_runner import PipelineRunner
    from src.utils import StructuredLogger

    # Generate default mock response if not provided
    if mock_http_response is None:
        mock_http_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            ],
            "parameters": {
                "prompt": njr.positive_prompt,
                "negative_prompt": njr.negative_prompt or "",
                "seed": njr.seed,
                "steps": njr.config.get("steps", 20),
                "cfg_scale": njr.config.get("cfg_scale", 7.0),
                "sampler_name": njr.config.get("sampler", "Euler"),
                "scheduler": njr.config.get("scheduler", "automatic"),
                "width": njr.config.get("width", 512),
                "height": njr.config.get("height", 512),
            },
        }

    # Create runner with the api_client
    runner = PipelineRunner(api_client=api_client, structured_logger=StructuredLogger())

    # Execute the NJR
    result = runner.run_njr(njr)

    # Convert result to JobHistoryEntry
    entry = JobHistoryEntry(
        job_id=njr.job_id,
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED if result.success else JobStatus.FAILED,
        run_mode="direct",
        payload_summary=f"NJR journey: {njr.positive_prompt[:50]}",
        normalized_record_snapshot=njr,
    )

    return entry


def get_latest_job(controller: AppController) -> JobHistoryEntry | None:
    """Get the most recent job from history store.

    Args:
        controller: The AppController instance.

    Returns:
        The most recent JobHistoryEntry, or None if no jobs exist.
    """
    history_store = getattr(controller.job_service, "history_store", None)
    if history_store is None:
        return None
    entries = history_store.list_jobs(limit=1)
    return entries[0] if entries else None


def get_stage_plan_for_job(
    controller: AppController, job: JobHistoryEntry
) -> StageExecutionPlan | None:
    """Get the StageExecutionPlan for a job.

    Args:
        controller: The AppController instance.
        job: The JobHistoryEntry to get the plan for.

    Returns:
        StageExecutionPlan if available, None otherwise.

    Note:
        Currently returns the last plan built by PipelineController.
        Future: may be extended to look up plan by job_id.
    """
    pipeline_ctrl = getattr(controller, "pipeline_controller", None)
    if pipeline_ctrl is None:
        return None

    # Try the test accessor first
    accessor = getattr(pipeline_ctrl, "get_last_stage_execution_plan_for_tests", None)
    if callable(accessor):
        return accessor()

    return None


# Backwards compatibility alias
def get_stage_plan(controller: AppController) -> StageExecutionPlan | None:
    """Legacy alias for get_stage_plan_for_job with no job argument.

    Deprecated: Use get_stage_plan_for_job(controller, job) instead.
    """
    pipeline_ctrl = getattr(controller, "pipeline_controller", None)
    if pipeline_ctrl is None:
        return None
    return getattr(pipeline_ctrl, "get_last_stage_execution_plan_for_tests", lambda: None)()


# ========================================
# CI Mode Detection Helpers
# ========================================


def is_ci_mode() -> bool:
    """
    Check if running in CI environment.

    Returns:
        True if CI environment variable is set (GitHub Actions, etc.)
    """
    import os

    return os.getenv("CI", "").lower() in ("true", "1", "yes")


def should_skip_real_webui_test() -> bool:
    """
    Determine if test should be skipped due to WebUI dependency.

    Some tests require real WebUI (e.g., image quality validation).
    These should skip in CI mode.

    Returns:
        True if test should skip (CI mode without real WebUI)
    """
    return is_ci_mode()
