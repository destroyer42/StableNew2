"""Queue persistence store for V2 queue system using the NJR-only schema.

Provides load/save functionality for queue state that survives app restarts.
Every job entry stores exactly one NormalizedJobRecord snapshot plus metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from src.utils.jsonl_codec import JSONLCodec

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_STATE_PATH = Path("state") / "queue_state_v2.json"

SCHEMA_VERSION = "2.6"

REQUIRED_QUEUE_FIELDS = {
    "queue_id": str,
    "njr_snapshot": dict,
    "priority": int,
    "status": str,
    "created_at": str,
    "queue_schema": str,
}

OPTIONAL_QUEUE_FIELDS = {"metadata": dict}


class UnsupportedQueueSchemaError(Exception):
    """Raised when a persisted queue snapshot uses an unsupported schema."""

    def __init__(self, schema_version: Any) -> None:
        super().__init__(f"Unsupported queue schema version: {schema_version!r}")
        self.schema_version = schema_version


@dataclass
class QueueSnapshot:
    """Serializable queue state snapshot using schema v2.6."""

    jobs: list[dict[str, Any]] = field(default_factory=list)
    auto_run_enabled: bool = False
    paused: bool = False
    schema_version: str = SCHEMA_VERSION


QueueSnapshotV1 = QueueSnapshot

_QUEUE_CODEC = JSONLCodec(logger=logger.warning)


def validate_queue_item(item: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Ensure a normalized queue job matches schema v2.6."""
    errors: list[str] = []

    for field, expected in REQUIRED_QUEUE_FIELDS.items():
        if field not in item:
            errors.append(f"missing {field}")
            continue
        value = item[field]
        if not isinstance(value, expected):
            errors.append(f"{field} must be {expected.__name__}, got {type(value).__name__}")
        if field == "queue_schema" and isinstance(value, str) and value != SCHEMA_VERSION:
            errors.append(f"queue_schema must be {SCHEMA_VERSION}, got {value}")

    metadata = item.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata must be dict")

    snapshot = item.get("njr_snapshot")
    if not isinstance(snapshot, dict) or "normalized_job" not in snapshot:
        errors.append("njr_snapshot must include normalized_job")

    return (not errors, errors)


def get_queue_state_path(base_dir: Path | str | None = None) -> Path:
    """Get the path for the queue state file."""
    if base_dir:
        return Path(base_dir) / "queue_state_v2.json"
    return DEFAULT_QUEUE_STATE_PATH


def load_queue_snapshot(path: Path | str | None = None) -> QueueSnapshotV1 | None:
    """Load queue state from disk using the strict v2.6 schema."""
    state_path = Path(path) if path else get_queue_state_path()

    if not state_path.exists():
        logger.debug("Queue state file not found: %s", state_path)
        return None

    entries = _QUEUE_CODEC.read_jsonl(state_path)
    data: dict[str, Any] | None = entries[-1] if entries else None
    if not data:
        return None

    schema_version = str(data.get("schema_version", ""))
    if schema_version != SCHEMA_VERSION:
        raise UnsupportedQueueSchemaError(schema_version)

    validated_jobs: list[dict[str, Any]] = []
    for raw in data.get("jobs", []):
        if not isinstance(raw, Mapping):
            logger.warning("Dropping queue job with invalid shape (not a mapping)")
            continue
        job = dict(raw)
        valid, errs = validate_queue_item(job)
        if not valid:
            logger.warning("Dropping invalid queue job: %s", errs)
            continue
        validated_jobs.append(job)

    snapshot = QueueSnapshotV1(
        jobs=validated_jobs,
        auto_run_enabled=bool(data.get("auto_run_enabled", False)),
        paused=bool(data.get("paused", False)),
        schema_version=SCHEMA_VERSION,
    )

    logger.info(
        "Loaded queue state: %d jobs, auto_run=%s, paused=%s",
        len(snapshot.jobs),
        snapshot.auto_run_enabled,
        snapshot.paused,
    )
    return snapshot


def save_queue_snapshot(snapshot: QueueSnapshotV1, path: Path | str | None = None) -> bool:
    """Save queue state to disk using the strict v2.6 schema."""
    state_path = Path(path) if path else get_queue_state_path()

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)

        validated_jobs: list[dict[str, Any]] = []
        for raw in snapshot.jobs:
            if not isinstance(raw, Mapping):
                logger.warning("Skipping non-mapping queue job during save")
                continue
            job = dict(raw)
            valid, errs = validate_queue_item(job)
            if not valid:
                logger.warning("Skipping invalid queue job during save: %s", errs)
                continue
            validated_jobs.append(job)

        data = {
            "jobs": validated_jobs,
            "auto_run_enabled": bool(snapshot.auto_run_enabled),
            "paused": bool(snapshot.paused),
            "schema_version": SCHEMA_VERSION,
        }

        temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        _QUEUE_CODEC.write_jsonl(temp_path, [data])
        temp_path.replace(state_path)

        logger.debug("Saved queue state: %d jobs", len(validated_jobs))
        logger.info(
            "QUEUE_STATE_SAVED | Persisted queue state",
            extra={
                "job_count": len(validated_jobs),
                "auto_run": snapshot.auto_run_enabled,
                "paused": snapshot.paused,
                "path": str(state_path),
                "subsystem": "queue_store_v2",
            },
        )
        return True

    except Exception as e:  # pragma: no cover - defensive
        logger.error("Failed to save queue state: %s", e)
        return False


def delete_queue_snapshot(path: Path | str | None = None) -> bool:
    """Delete the queue state file."""
    state_path = Path(path) if path else get_queue_state_path()

    try:
        if state_path.exists():
            state_path.unlink()
            logger.info("Deleted queue state file: %s", state_path)
        return True
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Failed to delete queue state: %s", e)
        return False


__all__ = [
    "QueueSnapshotV1",
    "UnsupportedQueueSchemaError",
    "validate_queue_item",
    "load_queue_snapshot",
    "save_queue_snapshot",
    "delete_queue_snapshot",
    "get_queue_state_path",
]
