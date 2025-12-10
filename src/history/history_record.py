from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

DEFAULT_HISTORY_VERSION = "2.6"
_DEFAULT_TIMESTAMP = "1970-01-01T00:00:00Z"
_LEGACY_KEYS = {
    "pipeline_config",
    "draft",
    "bundle",
    "draft_bundle",
    "job_bundle",
    "bundle_summary",
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
    njr_snapshot: dict[str, Any]
    timestamp: str
    status: str
    history_version: str = DEFAULT_HISTORY_VERSION
    metadata: dict[str, Any] | None = None

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
        metadata = None
        raw_metadata = data.get("metadata") or data.get("run_config") or {}
        if isinstance(raw_metadata, Mapping):
            metadata = dict(raw_metadata)
        return cls(
            id=record_id or snapshot.get("job_id") or "",
            njr_snapshot=snapshot,
            timestamp=timestamp,
            status=status,
            history_version=str(data.get("history_version") or DEFAULT_HISTORY_VERSION),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-ready dict."""
        base = asdict(self)
        base["history_version"] = self.history_version or DEFAULT_HISTORY_VERSION
        base["njr_snapshot"] = _clean_snapshot(self.njr_snapshot)
        base.pop("metadata", None)
        return base
