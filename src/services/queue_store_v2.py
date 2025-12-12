"""Queue persistence store for V2 queue system using the NJR-only schema.

Provides load/save functionality for queue state that survives app restarts.
Every job entry stores exactly one NormalizedJobRecord snapshot plus metadata.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.utils.jsonl_codec import JSONLCodec
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_STATE_PATH = Path("state") / "queue_state_v2.json"

SCHEMA_VERSION = "2.6"

QUEUE_JOB_DEPRECATED_FIELDS = {
    "_normalized_record",
    "pipeline_config",
    "legacy_config_blob",
    "job_bundle_summary",
    "draft_bundle_summary",
    "bundle",
    "config_blob",
}

REQUIRED_QUEUE_FIELDS = {
    "queue_id": str,
    "njr_snapshot": dict,
    "priority": int,
    "status": str,
    "created_at": str,
    "queue_schema": str,
}

OPTIONAL_QUEUE_FIELDS = {"metadata": dict}

LEGACY_SNAPSHOT_FIELDS = {
    "pipeline_config",
    "legacy_config_blob",
    "config_blob",
    "job_bundle_summary",
    "draft_bundle_summary",
    "bundle",
    "draft",
    "job_bundle",
    "bundle_summary",
    "normalized_job",
    "snapshot",
    "_normalized_record",
}


@dataclass
class QueueSnapshot:
    """Serializable queue state snapshot using schema v2.6."""

    jobs: list[dict[str, Any]] = field(default_factory=list)
    auto_run_enabled: bool = False
    paused: bool = False
    schema_version: str = SCHEMA_VERSION


QueueSnapshotV1 = QueueSnapshot

_QUEUE_CODEC = JSONLCodec(logger=logger.warning)


def _read_legacy_queue_state(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logger.warning("Failed to parse legacy queue state: %s", exc)
        return None

def _coerce_iso_timestamp(value: str | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return datetime.utcnow().isoformat()


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _strip_snapshot_keys(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in dict(snapshot or {}).items() if k not in LEGACY_SNAPSHOT_FIELDS}


def _njr_to_snapshot(record: NormalizedJobRecord) -> dict[str, Any]:
    snapshot = asdict(record)
    status = getattr(record, "status", None)
    if status is not None and hasattr(status, "value"):
        snapshot["status"] = status.value
    completed_at = snapshot.get("completed_at")
    if isinstance(completed_at, datetime):
        snapshot["completed_at"] = completed_at.isoformat()
    return snapshot


class QueueMigrationEngine:
    """Normalizes legacy queue entries to the v2.6 NJR-only schema."""

    def migrate_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        working = dict(item or {})

        job_id = working.get("job_id")
        record_id = working.get("id")
        queue_id = str(working.get("queue_id") or job_id or record_id or uuid4())

        snapshot = self._extract_snapshot(working)
        # Hydrate prompt fields for legacy compat
        from src.pipeline.job_models_v2 import NormalizedJobRecord
        from src.history.legacy_prompt_hydration_v26 import hydrate_prompt_fields
        njr = None
        if "normalized_job" in snapshot:
            try:
                njr = NormalizedJobRecord(**snapshot["normalized_job"])
            except Exception:
                pass
        if njr is not None:
            hydrate_prompt_fields(working, njr)
            snapshot["normalized_job"] = njr.__dict__

        raw_metadata = working.get("metadata")
        normalized = {
            "queue_id": queue_id,
            "njr_snapshot": snapshot,
            "priority": _coerce_int(working.get("priority"), 0),
            "status": str(working.get("status") or "queued"),
            "created_at": _coerce_iso_timestamp(working.get("created_at")),
            "queue_schema": SCHEMA_VERSION,
            "metadata": dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {},
        }

        return normalized

    def migrate_all(self, items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [self.migrate_item(item) for item in items or []]

    def _extract_snapshot(self, working: Mapping[str, Any]) -> dict[str, Any]:
        source = working.get("njr_snapshot") or working.get("snapshot") or working.get("_normalized_record")

        if isinstance(source, NormalizedJobRecord):
            return _strip_snapshot_keys(_njr_to_snapshot(source))

        if isinstance(source, Mapping):
            hydrated = normalized_job_from_snapshot(source)
            if hydrated:
                return _strip_snapshot_keys(_njr_to_snapshot(hydrated))
            return _strip_snapshot_keys(source)

        # Legacy shapes without normalized_job are non-runnable; return empty snapshot
        return {}


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

    metadata = item.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata must be dict")

    snapshot = item.get("njr_snapshot")
    if not isinstance(snapshot, dict) or "normalized_job" not in snapshot:
        errors.append("njr_snapshot must include normalized_job (legacy entries are view-only)")

    return (not errors, errors)


def get_queue_state_path(base_dir: Path | str | None = None) -> Path:
    """Get the path for the queue state file.
    
    Args:
        base_dir: Optional base directory. If None, uses current working directory.
        
    Returns:
        Path to the queue state JSON file.
    """
    if base_dir:
        return Path(base_dir) / "queue_state_v2.json"
    return DEFAULT_QUEUE_STATE_PATH


def load_queue_snapshot(path: Path | str | None = None) -> QueueSnapshotV1 | None:
    """Load queue state from disk.
    
    Args:
        path: Optional path to the queue state file. Uses default if not provided.
        
    Returns:
        QueueSnapshotV1 if loaded successfully, None if file missing or invalid.
    """
    state_path = Path(path) if path else get_queue_state_path()
    
    if not state_path.exists():
        logger.debug(f"Queue state file not found: {state_path}")
        return None

    entries = _QUEUE_CODEC.read_jsonl(state_path)
    data: dict[str, Any] | None = entries[-1] if entries else None
    if data is None:
        data = _read_legacy_queue_state(state_path)
    if not data:
        return None

    schema_version_raw = data.get("schema_version", SCHEMA_VERSION)
    schema_version = str(schema_version_raw)
    if schema_version != SCHEMA_VERSION:
        logger.warning(
            "Queue state schema version %s detected, normalizing to %s",
            schema_version,
            SCHEMA_VERSION,
        )

    engine = QueueMigrationEngine()
    migrated_jobs = engine.migrate_all(data.get("jobs", []))
    validated_jobs: list[dict[str, Any]] = []
    for job in migrated_jobs:
        valid, errs = validate_queue_item(job)
        if not valid:
            logger.warning("Queue job failed validation: %s", errs)
            # PR-CORE1-D17: Mark as legacy_view_only and still include
            if "metadata" in job and isinstance(job["metadata"], dict):
                job["metadata"]["legacy_view_only"] = True
            else:
                job["metadata"] = {"legacy_view_only": True}
            validated_jobs.append(job)
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
    """Save queue state to disk.
    
    Args:
        snapshot: The queue snapshot to save.
        path: Optional path to the queue state file. Uses default if not provided.
        
    Returns:
        True if saved successfully, False on error.
    """
    state_path = Path(path) if path else get_queue_state_path()
    
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)

        engine = QueueMigrationEngine()
        normalized_jobs = engine.migrate_all(snapshot.jobs)

        data = {
            "jobs": normalized_jobs,
            "auto_run_enabled": bool(snapshot.auto_run_enabled),
            "paused": bool(snapshot.paused),
            "schema_version": SCHEMA_VERSION,
        }

        temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        _QUEUE_CODEC.write_jsonl(temp_path, [data])
        temp_path.replace(state_path)

        logger.debug(f"Saved queue state: {len(normalized_jobs)} jobs")
        logger.info(
            "QUEUE_STATE_SAVED | Persisted queue state",
            extra={
                "job_count": len(normalized_jobs),
                "auto_run": snapshot.auto_run_enabled,
                "paused": snapshot.paused,
                "path": str(state_path),
                "subsystem": "queue_store_v2",
            },
        )
        return True
        
    except Exception as e:
        logger.error(f"Failed to save queue state: {e}")
        return False


def delete_queue_snapshot(path: Path | str | None = None) -> bool:
    """Delete the queue state file.
    
    Args:
        path: Optional path to the queue state file. Uses default if not provided.
        
    Returns:
        True if deleted or didn't exist, False on error.
    """
    state_path = Path(path) if path else get_queue_state_path()
    
    try:
        if state_path.exists():
            state_path.unlink()
            logger.info(f"Deleted queue state file: {state_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete queue state: {e}")
        return False


__all__ = [
    "QueueSnapshotV1",
    "QueueMigrationEngine",
    "validate_queue_item",
    "load_queue_snapshot",
    "save_queue_snapshot",
    "delete_queue_snapshot",
    "get_queue_state_path",
]
