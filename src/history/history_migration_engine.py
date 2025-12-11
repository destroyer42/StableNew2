from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable, Mapping

from src.history.history_schema_v26 import (
    ALLOWED_FIELDS,
    DEPRECATED_FIELDS,
    HISTORY_SCHEMA_VERSION,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.legacy_njr_adapter import (
    build_njr_from_history_dict,
    build_njr_from_legacy_pipeline_config,
)
from src.pipeline.pipeline_runner import PipelineConfig
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

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
_DEFAULT_TIMESTAMP = "1970-01-01T00:00:00Z"


def _strip_legacy_keys(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in _LEGACY_KEYS}


def _coerce_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return _DEFAULT_TIMESTAMP


def _njr_to_snapshot(njr: NormalizedJobRecord) -> dict[str, Any]:
    snapshot = asdict(njr)
    status = getattr(njr, "status", None)
    if status is not None and hasattr(status, "value"):
        snapshot["status"] = status.value
    completed_at = snapshot.get("completed_at")
    if isinstance(completed_at, datetime):
        snapshot["completed_at"] = completed_at.isoformat()
    return snapshot


class HistoryMigrationEngine:
    """
    Converts legacy history entries into NJR snapshots.
    Deterministic, idempotent, schema-validated.
    """

    def migrate_entry(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        raw = dict(entry or {})
        snapshot = self._extract_snapshot(raw)
        snapshot = dict(snapshot or {})
        record_id = str(
            raw.get("id")
            or raw.get("job_id")
            or raw.get("jobId")
            or snapshot.get("job_id")
            or ""
        )
        if record_id:
            snapshot["job_id"] = record_id
        timestamp = _coerce_timestamp(
            raw.get("timestamp") or raw.get("created_at") or raw.get("recorded_at")
        )
        status = str(raw.get("status") or raw.get("job_status") or "unknown")
        migrated = {
            "id": record_id,
            "timestamp": timestamp,
            "status": status,
            "njr_snapshot": snapshot,
        }
        return self.normalize_schema(migrated)

    def migrate_all(self, entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Apply migration in stable order and guarantee idempotence."""
        items = list(entries or [])
        return [self.migrate_entry(entry) for entry in items]

    def normalize_schema(self, entry: dict[str, Any]) -> dict[str, Any]:
        """
        Ensures entry matches History Schema v2.6 exactly.
        Adds missing fields, removes deprecated keys, and enforces canonical ordering.
        """
        normalized: dict[str, Any] = {}
        working = dict(entry or {})

        # Drop deprecated fields
        for key in list(working.keys()):
            if key in DEPRECATED_FIELDS:
                working.pop(key, None)

        # Required fields
        normalized["id"] = str(working.get("id", ""))
        normalized["timestamp"] = _coerce_timestamp(working.get("timestamp"))
        normalized["status"] = str(working.get("status", "unknown"))
        normalized["history_schema"] = HISTORY_SCHEMA_VERSION
        normalized["history_version"] = str(working.get("history_version") or HISTORY_SCHEMA_VERSION)

        snapshot = working.get("njr_snapshot") or working.get("snapshot") or {}
        if not isinstance(snapshot, Mapping):
            snapshot = {}
        normalized["njr_snapshot"] = _strip_legacy_keys(dict(snapshot))

        # Optional defaults
        normalized["ui_summary"] = self._build_ui_summary_from_njr(normalized["njr_snapshot"])
        normalized["metadata"] = self._ensure_dict(working.get("metadata"))
        normalized["runtime"] = self._ensure_dict(working.get("runtime"))
        normalized["result"] = self._ensure_dict(working.get("result"))

        return self._strip_entry_unknown(normalized)

    def _extract_snapshot(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        if "njr_snapshot" in entry and isinstance(entry["njr_snapshot"], Mapping):
            if entry.get("history_schema") == HISTORY_SCHEMA_VERSION:
                return _strip_legacy_keys(deepcopy(entry["njr_snapshot"]))
            hydrated = self._hydrate_snapshot(entry["njr_snapshot"])
            if hydrated is not None:
                return _njr_to_snapshot(hydrated)
            return _strip_legacy_keys(deepcopy(entry["njr_snapshot"]))

        snapshot = entry.get("snapshot")
        if isinstance(snapshot, Mapping):
            hydrated = self._hydrate_snapshot(snapshot)
            if hydrated is not None:
                return _njr_to_snapshot(hydrated)
            return _strip_legacy_keys(deepcopy(snapshot))

        # Legacy shapes without normalized_job are treated as non-runnable (view-only)
        return {}

    def _hydrate_snapshot(self, snapshot: Mapping[str, Any] | None) -> NormalizedJobRecord | None:
        """Attempt to coerce any snapshot-like mapping into a full NJR."""
        if not snapshot:
            return None
        try_constructor = getattr(NormalizedJobRecord, "from_snapshot", None)
        if callable(try_constructor):
            try:
                return try_constructor(snapshot)
            except Exception:
                pass
        normalized_section = snapshot if "normalized_job" in snapshot else {"normalized_job": snapshot}
        return normalized_job_from_snapshot(normalized_section)

    def _coerce_pipeline_config(self, data: Mapping[str, Any]) -> PipelineConfig:
        prompt = str(data.get("prompt", "") or data.get("positive_prompt", "") or "")
        negative_prompt = str(data.get("negative_prompt", "") or data.get("neg_prompt", "") or "")
        model = str(data.get("model") or data.get("model_name") or "unknown")
        sampler = str(data.get("sampler") or data.get("sampler_name") or "Euler a") or "Euler a"
        scheduler = str(data.get("scheduler") or data.get("scheduler_name") or "")
        width = int(data.get("width") or 512)
        height = int(data.get("height") or 512)
        steps = int(data.get("steps") or 20)
        cfg_scale = float(data.get("cfg_scale") or 7.0)
        metadata = {}
        raw_metadata = data.get("metadata") or data.get("run_config") or {}
        if isinstance(raw_metadata, Mapping):
            metadata = dict(raw_metadata)
        config = PipelineConfig(
            prompt=prompt,
            model=model,
            sampler=sampler,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            negative_prompt=negative_prompt,
            metadata=metadata,
        )
        if scheduler:
            config.metadata["scheduler"] = scheduler
        return config

    def _build_ui_summary_from_njr(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Derive a compact UI/display summary from an NJR snapshot."""
        if not isinstance(snapshot, Mapping):
            return {}
        return {
            "job_id": snapshot.get("job_id", ""),
            "prompt": snapshot.get("positive_prompt", ""),
            "negative_prompt": snapshot.get("negative_prompt", ""),
            "model": snapshot.get("base_model") or snapshot.get("model") or "",
            "sampler": snapshot.get("sampler_name") or snapshot.get("sampler") or "",
            "steps": snapshot.get("steps", 0),
            "cfg_scale": snapshot.get("cfg_scale", 0.0),
            "width": snapshot.get("width", 0),
            "height": snapshot.get("height", 0),
            "status": snapshot.get("status") or "",
        }

    def _ensure_dict(self, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def _strip_entry_unknown(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Remove keys not part of the allowed schema set (entry-level only)."""
        return {k: v for k, v in entry.items() if k in ALLOWED_FIELDS}
