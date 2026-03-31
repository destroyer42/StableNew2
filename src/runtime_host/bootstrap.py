from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from src.app.bootstrap import (
    ApplicationKernel,
    build_runtime_host_kernel,
)
from src.app.optional_dependency_probes import OptionalDependencySnapshot
from src.controller.job_history_service import JobHistoryService
from src.controller.job_service import JobService
from src.controller.ports.runtime_ports import ImageRuntimePorts
from src.pipeline.pipeline_runner import normalize_run_result
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job, JobPriority, JobStatus, RetryAttempt, StageCheckpoint
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.runtime_host.local_adapter import build_local_runtime_host
from src.runtime_host.managed_runtime import ManagedRuntimeOwner
from src.runtime_host.port import RuntimeHostPort
from src.services.queue_store_v2 import (
    SCHEMA_VERSION,
    QueueSnapshotV1,
    UnsupportedQueueSchemaError,
    load_queue_snapshot,
    save_queue_snapshot,
)
from src.utils import StructuredLogger
from src.utils.config import ConfigManager
from src.utils.error_envelope_v2 import (
    get_attached_envelope,
    serialize_envelope,
    wrap_exception,
)
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

logger = logging.getLogger(__name__)


def _parse_iso_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.utcnow()


def _priority_from_value(value: Any) -> JobPriority:
    try:
        if isinstance(value, JobPriority):
            return value
        return JobPriority(int(value))
    except Exception:
        return JobPriority.NORMAL


def _record_from_snapshot(snapshot: Mapping[str, Any] | None) -> Any | None:
    if not isinstance(snapshot, Mapping):
        return None
    normalized_source = dict(snapshot)
    if "normalized_job" not in normalized_source:
        normalized_source = {"normalized_job": normalized_source}
    return normalized_job_from_snapshot(normalized_source)


def _build_queue_entry(job: Job) -> dict[str, Any] | None:
    record = getattr(job, "_normalized_record", None)
    snapshot = getattr(job, "snapshot", None) or {}
    if record is None and snapshot:
        record = _record_from_snapshot(snapshot)
    if record is None:
        return None

    metadata: dict[str, Any] = {}
    metadata_fields = {
        "run_mode": job.run_mode,
        "source": job.source,
        "prompt_source": job.prompt_source,
        "prompt_pack_id": job.prompt_pack_id,
    }
    execution_metadata = getattr(job, "execution_metadata", None)
    if execution_metadata is not None:
        metadata_fields["execution_metadata"] = {
            "retry_attempts": [asdict(attempt) for attempt in execution_metadata.retry_attempts],
            "stage_checkpoints": [asdict(checkpoint) for checkpoint in execution_metadata.stage_checkpoints],
            "last_control_action": execution_metadata.last_control_action,
            "return_to_queue_count": execution_metadata.return_to_queue_count,
        }
    for key, value in metadata_fields.items():
        if value is not None:
            metadata[key] = value

    snapshot_dict: dict[str, Any] = {}
    if isinstance(snapshot, Mapping):
        snapshot_dict = dict(snapshot)
    if "normalized_job" not in snapshot_dict:
        snapshot_dict = {"normalized_job": asdict(record)}

    return {
        "queue_id": job.job_id,
        "njr_snapshot": snapshot_dict,
        "priority": int(job.priority),
        "status": job.status.value,
        "created_at": job.created_at.isoformat(),
        "queue_schema": SCHEMA_VERSION,
        "metadata": metadata,
    }


def _job_from_snapshot_entry(entry: Mapping[str, Any]) -> Job | None:
    if not isinstance(entry, Mapping):
        return None
    status_value = str(entry.get("status") or JobStatus.QUEUED.value).lower()
    if status_value != JobStatus.QUEUED.value:
        return None

    snapshot = entry.get("njr_snapshot") or {}
    record = _record_from_snapshot(snapshot if isinstance(snapshot, Mapping) else None)
    if record is None:
        return None

    metadata = entry.get("metadata") or {}
    priority = _priority_from_value(entry.get("priority", JobPriority.NORMAL))
    job = Job(
        job_id=str(entry.get("queue_id") or entry.get("job_id") or record.job_id),
        priority=priority,
        run_mode=str(metadata.get("run_mode") or "queue"),
        source=str(metadata.get("source") or "queue"),
        prompt_source=str(metadata.get("prompt_source") or "manual"),
        prompt_pack_id=metadata.get("prompt_pack_id"),
    )
    job.snapshot = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    job._normalized_record = record  # type: ignore[attr-defined]
    created = _parse_iso_datetime(entry.get("created_at"))
    job.created_at = created
    job.updated_at = created
    job.status = JobStatus.QUEUED
    job.payload = None

    execution_metadata = metadata.get("execution_metadata") or {}
    if isinstance(execution_metadata, Mapping):
        for attempt in execution_metadata.get("retry_attempts") or []:
            if isinstance(attempt, Mapping):
                job.execution_metadata.retry_attempts.append(
                    RetryAttempt(
                        stage=str(attempt.get("stage") or "pipeline"),
                        attempt_index=int(attempt.get("attempt_index") or 0),
                        max_attempts=int(attempt.get("max_attempts") or 0),
                        reason=str(attempt.get("reason") or ""),
                        timestamp=float(attempt.get("timestamp") or 0.0),
                    )
                )
        for checkpoint in execution_metadata.get("stage_checkpoints") or []:
            if isinstance(checkpoint, Mapping):
                job.execution_metadata.stage_checkpoints.append(
                    StageCheckpoint(
                        stage_name=str(checkpoint.get("stage_name") or ""),
                        completed_at=float(checkpoint.get("completed_at") or 0.0),
                        output_paths=[
                            str(path)
                            for path in checkpoint.get("output_paths") or []
                            if path
                        ],
                        metadata=dict(checkpoint.get("metadata") or {}),
                    )
                )
        action = execution_metadata.get("last_control_action")
        if action:
            job.execution_metadata.last_control_action = str(action)
        try:
            job.execution_metadata.return_to_queue_count = int(
                execution_metadata.get("return_to_queue_count") or 0
            )
        except Exception:
            job.execution_metadata.return_to_queue_count = 0
    return job


class RuntimeHostQueueStatePersistence:
    """Persist and restore queue state for the child runtime host."""

    def __init__(self, job_service: JobService) -> None:
        self._job_service = job_service
        self._queue = job_service.job_queue
        self._queue.register_state_listener(self.persist)

    def restore(self) -> None:
        try:
            snapshot = load_queue_snapshot()
        except UnsupportedQueueSchemaError as exc:
            logger.warning(
                "QUEUE_STATE_UNSUPPORTED | schema_version=%s | ignoring persisted child runtime queue state",
                getattr(exc, "schema_version", None),
            )
            return
        except Exception:
            logger.exception("Failed to restore child runtime queue state")
            return

        if snapshot is None:
            return

        self._job_service.auto_run_enabled = bool(snapshot.auto_run_enabled)
        if bool(snapshot.paused):
            logger.info(
                "Ignoring persisted paused child runtime queue state on restore; only queued jobs are restored"
            )

        restored_jobs: list[Job] = []
        for entry in snapshot.jobs:
            job = _job_from_snapshot_entry(entry)
            if job is not None:
                restored_jobs.append(job)

        if restored_jobs:
            self._queue.restore_jobs(restored_jobs)

        logger.info(
            "Restored child runtime queue state: auto_run=%s restored_jobs=%d",
            self._job_service.auto_run_enabled,
            len(restored_jobs),
        )

        if self._job_service.auto_run_enabled and restored_jobs:
            try:
                self._job_service.run_next_now()
            except Exception:
                logger.exception("Failed to auto-start child runtime queue after restore")

    def persist(self) -> None:
        entries: list[dict[str, Any]] = []
        for job in self._queue.list_jobs():
            if job.status != JobStatus.QUEUED:
                continue
            entry = _build_queue_entry(job)
            if entry is not None:
                entries.append(entry)

        paused_getter = getattr(self._queue, "is_paused", None)
        paused = bool(paused_getter()) if callable(paused_getter) else False
        snapshot = QueueSnapshotV1(
            jobs=entries,
            auto_run_enabled=bool(self._job_service.auto_run_enabled),
            paused=paused,
        )
        save_queue_snapshot(snapshot)


@dataclass(frozen=True, slots=True)
class RuntimeHostBootstrap:
    kernel: ApplicationKernel
    history_path: Path
    job_queue: JobQueue
    history_store: JSONLJobHistoryStore
    history_service: JobHistoryService
    job_service: JobService
    runtime_host: RuntimeHostPort
    managed_runtime_owner: ManagedRuntimeOwner


class RuntimeHostJobExecutor:
    """Execute queue jobs inside the child runtime host through PipelineRunner.run_njr()."""

    def __init__(self, kernel: ApplicationKernel) -> None:
        self._kernel = kernel

    def __call__(self, job: Job) -> dict[str, Any]:
        record = getattr(job, "_normalized_record", None)
        if record is None:
            return normalize_run_result(
                {
                    "error": (
                        "Job is missing normalized_record; child runtime host "
                        "execution is NJR-only."
                    )
                },
                default_run_id=job.job_id,
            )

        try:
            result = self._kernel.pipeline_runner.run_njr(record)
        except Exception as exc:  # noqa: BLE001
            envelope = get_attached_envelope(exc)
            if envelope is None:
                envelope = wrap_exception(exc, subsystem="runtime_host")
            return normalize_run_result(
                {
                    "error": str(exc),
                    "error_envelope": serialize_envelope(envelope),
                },
                default_run_id=job.job_id,
            )

        if isinstance(result, Mapping):
            payload = dict(result)
        elif hasattr(result, "to_dict"):
            payload = result.to_dict()
        else:
            payload = {"result": result}
        return normalize_run_result(payload, default_run_id=job.job_id)


def _single_node_runner_factory(
    job_queue: JobQueue,
    run_callable: Any,
) -> SingleNodeJobRunner:
    return SingleNodeJobRunner(
        job_queue,
        run_callable=run_callable,
        poll_interval=0.05,
    )


def _resolve_history_path(history_path: Path | str | None) -> Path:
    if history_path is None:
        return Path("runs") / "runtime_host_job_history.jsonl"
    return Path(history_path)


def build_runtime_host_bootstrap(
    *,
    history_path: Path | str | None = None,
    config_manager: ConfigManager | None = None,
    runtime_ports: ImageRuntimePorts | None = None,
    structured_logger: StructuredLogger | None = None,
    api_url: str | None = None,
    capabilities: OptionalDependencySnapshot | None = None,
    pipeline_runner: Any | None = None,
    start_managed_runtimes: bool = False,
) -> RuntimeHostBootstrap:
    kernel = build_runtime_host_kernel(
        config_manager=config_manager,
        runtime_ports=runtime_ports,
        structured_logger=structured_logger,
        api_url=api_url,
        capabilities=capabilities,
    )
    if pipeline_runner is not None:
        kernel = replace(kernel, pipeline_runner=pipeline_runner)

    resolved_history_path = _resolve_history_path(history_path)
    resolved_history_path.parent.mkdir(parents=True, exist_ok=True)

    history_store = JSONLJobHistoryStore(resolved_history_path)
    job_queue = JobQueue(history_store=history_store)
    history_service = JobHistoryService(job_queue, history_store)
    job_executor = RuntimeHostJobExecutor(kernel)
    job_service = JobService(
        job_queue,
        runner_factory=_single_node_runner_factory,
        history_store=history_store,
        history_service=history_service,
        run_callable=job_executor,
        require_normalized_records=True,
    )
    queue_persistence = RuntimeHostQueueStatePersistence(job_service)
    queue_persistence.restore()
    setattr(job_service, "persist_queue_state", queue_persistence.persist)
    queue_persistence.persist()
    runtime_host = build_local_runtime_host(job_service)
    managed_runtime_owner = ManagedRuntimeOwner()
    if start_managed_runtimes:
        managed_runtime_owner.start_background_bootstrap()
    return RuntimeHostBootstrap(
        kernel=kernel,
        history_path=resolved_history_path,
        job_queue=job_queue,
        history_store=history_store,
        history_service=history_service,
        job_service=job_service,
        runtime_host=runtime_host,
        managed_runtime_owner=managed_runtime_owner,
    )


__all__ = [
    "RuntimeHostBootstrap",
    "RuntimeHostJobExecutor",
    "build_runtime_host_bootstrap",
]