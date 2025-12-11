from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping

from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION, InvalidHistoryRecord

_DEFAULT_TIMESTAMP = "1970-01-01T00:00:00Z"
_LEGACY_KEYS = {
    "pipeline_config",
    "draft",
    "bundle",
    "draft_bundle",
    "job_bundle",
    "bundle_summary",
    "job_bundle_summary",
    "draft_bundle_summary",
    "legacy_job",
    "config_blob",
    "legacy_config_blob",
}


def _coerce_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return _DEFAULT_TIMESTAMP


def _clean_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {}
    return {k: v for k, v in snapshot.items() if k not in _LEGACY_KEYS}


@dataclass
class HistoryRecord:
    """Immutable NJR-only history record used for persistence and replay."""

    id: str
    timestamp: str
    status: str
    history_schema: str = HISTORY_SCHEMA_VERSION
    njr_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    ui_summary: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    history_version: str | None = None  # transitional compatibility

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoryRecord":
        record_id = str(data.get("id") or data.get("job_id") or data.get("jobId") or "")
        snapshot = _clean_snapshot(
            data.get("njr_snapshot")
            or data.get("snapshot")
            or data.get("normalized_job")
            or {}
        )
        timestamp = _coerce_timestamp(
            data.get("timestamp")
            or data.get("created_at")
            or data.get("recorded_at")
        )
        status = str(data.get("status") or data.get("job_status") or "unknown")
        raw_metadata = data.get("metadata") or data.get("run_config") or {}
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        raw_runtime = data.get("runtime") or {}
        runtime = dict(raw_runtime) if isinstance(raw_runtime, Mapping) else {}
        raw_ui_summary = data.get("ui_summary") or {}
        raw_result = data.get("result")
        ui_summary = dict(raw_ui_summary) if isinstance(raw_ui_summary, Mapping) else {}
        result = dict(raw_result) if isinstance(raw_result, Mapping) else None
        return cls(
            id=record_id or snapshot.get("job_id") or "",
            timestamp=timestamp,
            status=status,
            history_schema=str(data.get("history_schema") or HISTORY_SCHEMA_VERSION),
            njr_snapshot=snapshot,
            metadata=metadata,
            runtime=runtime,
            ui_summary=ui_summary,
            result=result,
            history_version=str(data.get("history_version") or data.get("history_schema") or HISTORY_SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-ready dict."""
        base = {
            "id": self.id,
            "timestamp": self.timestamp,
            "status": self.status,
            "history_schema": self.history_schema or HISTORY_SCHEMA_VERSION,
            "njr_snapshot": _clean_snapshot(self.njr_snapshot),
            "ui_summary": dict(self.ui_summary or {}),
            "metadata": dict(self.metadata or {}),
            "runtime": dict(self.runtime or {}),
        }
        if self.result is not None:
            base["result"] = dict(self.result)
        return base

    def to_njr(self) -> "NormalizedJobRecord":
        from src.pipeline.job_models_v2 import NormalizedJobRecord  # Local import to avoid cycle

        snapshot = self.njr_snapshot or {}
        if "normalized_job" not in snapshot:
            raise InvalidHistoryRecord("History record is legacy/view-only (missing normalized_job).")
        return NormalizedJobRecord.from_snapshot(snapshot)
