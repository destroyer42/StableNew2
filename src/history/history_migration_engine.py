from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable, Mapping

from src.history.history_record import DEFAULT_HISTORY_VERSION
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
        raw = _strip_legacy_keys(dict(entry or {}))
        snapshot = self._extract_snapshot(raw)
        record_id = str(
            raw.get("id")
            or raw.get("job_id")
            or raw.get("jobId")
            or snapshot.get("job_id")
            or ""
        )
        timestamp = _coerce_timestamp(
            raw.get("timestamp") or raw.get("created_at") or raw.get("recorded_at")
        )
        status = str(raw.get("status") or raw.get("job_status") or "unknown")
        migrated = {
            "id": record_id,
            "timestamp": timestamp,
            "status": status,
            "njr_snapshot": snapshot,
            "history_version": DEFAULT_HISTORY_VERSION,
        }
        return migrated

    def migrate_all(self, entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        migrated: list[dict[str, Any]] = []
        for entry in list(entries or []):
            migrated.append(self.migrate_entry(entry))
        return migrated

    def _extract_snapshot(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        if "njr_snapshot" in entry and isinstance(entry["njr_snapshot"], Mapping):
            return _strip_legacy_keys(deepcopy(entry["njr_snapshot"]))

        snapshot = entry.get("snapshot")
        if isinstance(snapshot, Mapping):
            njr = normalized_job_from_snapshot(snapshot)
            if njr is None:
                normalized_section = snapshot.get("normalized_job")
                if isinstance(normalized_section, Mapping):
                    njr = normalized_job_from_snapshot({"normalized_job": normalized_section})
            if njr is not None:
                return _njr_to_snapshot(njr)
            return _strip_legacy_keys(deepcopy(snapshot))

        pipeline_config = entry.get("pipeline_config")
        if isinstance(pipeline_config, PipelineConfig):
            return _njr_to_snapshot(build_njr_from_legacy_pipeline_config(pipeline_config))
        if isinstance(pipeline_config, Mapping):
            config = self._coerce_pipeline_config(pipeline_config)
            return _njr_to_snapshot(build_njr_from_legacy_pipeline_config(config))

        njr = build_njr_from_history_dict(entry)
        return _njr_to_snapshot(njr)

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
