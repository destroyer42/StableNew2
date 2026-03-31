from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Mapping

from src.pipeline.job_requests_v2 import PipelineRunRequest
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import Job, JobPriority, JobStatus, RetryAttempt, StageCheckpoint
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


def _serialize_dataclass(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _parse_job_priority(value: Any) -> JobPriority:
    if isinstance(value, JobPriority):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return JobPriority.NORMAL
        try:
            return JobPriority(int(normalized))
        except Exception:
            pass
        try:
            return JobPriority[normalized.upper()]
        except Exception:
            return JobPriority.NORMAL
    try:
        return JobPriority(int(value))
    except Exception:
        return JobPriority.NORMAL


def serialize_normalized_job_snapshot(record: Any) -> dict[str, Any]:
    return {"normalized_job": _serialize_dataclass(record)}


def serialize_job(
    job: Job,
    *,
    include_result: bool = True,
    include_config_snapshot: bool = True,
    include_randomizer_metadata: bool = True,
    include_execution_metadata: bool = True,
) -> dict[str, Any]:
    data = dict(job.to_dict())
    snapshot = dict(data.get("snapshot") or {})
    record = getattr(job, "_normalized_record", None)
    if record is not None and "normalized_job" not in snapshot:
        snapshot = serialize_normalized_job_snapshot(record)
    data["snapshot"] = snapshot
    if not include_result:
        data.pop("result", None)
    if not include_config_snapshot:
        data.pop("config_snapshot", None)
    if not include_randomizer_metadata:
        data.pop("randomizer_metadata", None)
    data["display_summary"] = job.get_display_summary()
    data["progress"] = float(getattr(job, "progress", 0.0) or 0.0)
    data["eta_seconds"] = getattr(job, "eta_seconds", None)
    if include_execution_metadata:
        data["execution_metadata"] = {
            "external_pids": list(job.execution_metadata.external_pids),
            "retry_attempts": [asdict(attempt) for attempt in job.execution_metadata.retry_attempts],
            "stage_checkpoints": [asdict(checkpoint) for checkpoint in job.execution_metadata.stage_checkpoints],
            "last_control_action": job.execution_metadata.last_control_action,
            "return_to_queue_count": job.execution_metadata.return_to_queue_count,
        }
    else:
        data.pop("execution_metadata", None)
    return data


def serialize_runtime_snapshot_job(job: Job) -> dict[str, Any]:
    data = serialize_job(
        job,
        include_result=False,
        include_config_snapshot=False,
        include_randomizer_metadata=False,
        include_execution_metadata=False,
    )
    data.pop("learning_enabled", None)
    return data


def deserialize_job(data: Mapping[str, Any]) -> Job:
    job = Job(
        job_id=str(data.get("job_id") or ""),
        priority=_parse_job_priority(data.get("priority", JobPriority.NORMAL)),
        run_mode=str(data.get("run_mode") or "queue"),
        source=str(data.get("source") or "unknown"),
        prompt_source=str(data.get("prompt_source") or "manual"),
        prompt_pack_id=(str(data.get("prompt_pack_id")) if data.get("prompt_pack_id") else None),
        config_snapshot=dict(data.get("config_snapshot") or {}) or None,
        randomizer_metadata=dict(data.get("randomizer_metadata") or {}) or None,
        variant_index=(int(data["variant_index"]) if data.get("variant_index") is not None else None),
        variant_total=(int(data["variant_total"]) if data.get("variant_total") is not None else None),
    )
    status_value = str(data.get("status") or JobStatus.QUEUED.value)
    try:
        job.status = JobStatus(status_value)
    except Exception:
        job.status = JobStatus.QUEUED
    job.created_at = _parse_datetime(data.get("created_at")) or job.created_at
    job.updated_at = _parse_datetime(data.get("updated_at")) or job.updated_at
    job.started_at = _parse_datetime(data.get("started_at"))
    job.completed_at = _parse_datetime(data.get("completed_at"))
    job.error_message = data.get("error_message") or None
    result = data.get("result")
    job.result = dict(result) if isinstance(result, Mapping) else None
    snapshot = dict(data.get("snapshot") or {})
    job.snapshot = snapshot
    record = normalized_job_from_snapshot(snapshot)
    if record is not None:
        job._normalized_record = record  # type: ignore[attr-defined]
    execution_metadata = data.get("execution_metadata") or {}
    if isinstance(execution_metadata, Mapping):
        job.execution_metadata.external_pids = [int(pid) for pid in execution_metadata.get("external_pids") or []]
        job.execution_metadata.retry_attempts = [
            RetryAttempt(
                stage=str(item.get("stage") or "pipeline"),
                attempt_index=int(item.get("attempt_index") or 0),
                max_attempts=int(item.get("max_attempts") or 0),
                reason=str(item.get("reason") or ""),
                timestamp=float(item.get("timestamp") or 0.0),
            )
            for item in execution_metadata.get("retry_attempts") or []
            if isinstance(item, Mapping)
        ]
        job.execution_metadata.stage_checkpoints = [
            StageCheckpoint(
                stage_name=str(item.get("stage_name") or ""),
                completed_at=float(item.get("completed_at") or 0.0),
                output_paths=[str(path) for path in item.get("output_paths") or [] if path],
                metadata=dict(item.get("metadata") or {}),
            )
            for item in execution_metadata.get("stage_checkpoints") or []
            if isinstance(item, Mapping)
        ]
        last_control_action = execution_metadata.get("last_control_action")
        job.execution_metadata.last_control_action = (
            str(last_control_action) if last_control_action is not None else None
        )
        job.execution_metadata.return_to_queue_count = int(
            execution_metadata.get("return_to_queue_count") or 0
        )
    try:
        job.progress = float(data.get("progress") or 0.0)
    except Exception:
        job.progress = 0.0
    eta_seconds = data.get("eta_seconds")
    try:
        job.eta_seconds = float(eta_seconds) if eta_seconds is not None else None
    except Exception:
        job.eta_seconds = None
    return job


def serialize_history_entry(entry: JobHistoryEntry) -> dict[str, Any]:
    return json.loads(entry.to_json())


def deserialize_history_entry(data: Mapping[str, Any]) -> JobHistoryEntry:
    return JobHistoryEntry.from_json(json.dumps(dict(data)))


def serialize_run_request(run_request: PipelineRunRequest | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(run_request, PipelineRunRequest):
        return run_request.to_dict()
    return dict(run_request)


def deserialize_run_request(data: Mapping[str, Any]) -> PipelineRunRequest:
    return PipelineRunRequest.from_dict(dict(data))


__all__ = [
    "deserialize_history_entry",
    "deserialize_job",
    "deserialize_run_request",
    "serialize_history_entry",
    "serialize_job",
    "serialize_runtime_snapshot_job",
    "serialize_normalized_job_snapshot",
    "serialize_run_request",
]