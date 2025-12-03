"""Shared helpers for the V2 journey tests."""

from __future__ import annotations

import time
from typing import Iterable

from src.controller.app_controller import AppController
from src.pipeline.stage_sequencer import StageExecutionPlan
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus


_DEFAULT_TIMEOUT = 20.0


def _snapshot_history_ids(history_store, limit: int = 20) -> set[str]:
    return {entry.job_id for entry in history_store.list_jobs(limit=limit)}


def _wait_for_history_entry(
    history_store, known_ids: Iterable[str], timeout: float = _DEFAULT_TIMEOUT
) -> JobHistoryEntry:
    deadline = time.time() + timeout
    while time.time() < deadline:
        entries = history_store.list_jobs(limit=5)
        for entry in entries:
            if entry.job_id not in known_ids:
                return entry
        time.sleep(0.1)
    raise TimeoutError("Timed out waiting for new job history entry.")


def _wait_for_job_completion(job_service, job_id: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = job_service.job_queue.get_job(job_id)
        if job and job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for job {job_id} to complete.")


def start_run_and_wait(
    controller: AppController, *, use_run_now: bool = False, timeout: float = _DEFAULT_TIMEOUT
) -> JobHistoryEntry:
    history_store = getattr(controller.job_service, "history_store", None)
    if history_store is None:
        raise RuntimeError("Job history store is not available for journey helper.")

    known_ids = _snapshot_history_ids(history_store)
    if use_run_now:
        controller.on_run_job_now_v2()
    else:
        controller.start_run_v2()

    entry = _wait_for_history_entry(history_store, known_ids, timeout=timeout)
    _wait_for_job_completion(controller.job_service, entry.job_id, timeout=timeout)
    return entry


def get_latest_job(controller: AppController) -> JobHistoryEntry | None:
    history_store = getattr(controller.job_service, "history_store", None)
    if history_store is None:
        return None
    entries = history_store.list_jobs(limit=1)
    return entries[0] if entries else None


def get_stage_plan(controller: AppController) -> StageExecutionPlan | None:
    pipeline_ctrl = getattr(controller, "pipeline_controller", None)
    if pipeline_ctrl is None:
        return None
    return getattr(pipeline_ctrl, "get_last_stage_execution_plan_for_tests", lambda: None)()
