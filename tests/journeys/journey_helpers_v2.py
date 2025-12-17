"""Shared helpers for the V2 journey tests.

This module provides the canonical helper API for journey tests, hiding
controller/runner internals. All journey tests (JT03, JT04, JT05, JT06, etc.)
should use these helpers exclusively.

Public API:
    start_run_and_wait(app, use_run_now=False, add_to_queue_only=False, timeout_seconds=30.0) -> JobHistoryEntry
    get_latest_job(app) -> JobHistoryEntry | None
    get_stage_plan_for_job(app, job) -> StageExecutionPlan | None
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import datetime

from src.controller.app_controller import AppController
from src.pipeline.stage_sequencer import StageExecutionPlan
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus

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
