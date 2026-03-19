"""One-time queue/history migration tool for the strict v2.6 NJR runtime."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.history.history_record import HistoryRecord
from src.history.job_history_store import JobHistoryStore
from src.pipeline.job_models_v2 import JobStatusV2, LoRATag, NormalizedJobRecord, StageConfig
from src.queue.job_model import Job, JobPriority
from src.services.queue_store_v2 import (
    SCHEMA_VERSION,
    QueueSnapshotV1,
    save_queue_snapshot,
    validate_queue_item,
)
from src.utils.snapshot_builder_v2 import build_job_snapshot

TARGET_HISTORY_SCHEMA = "2.6"

_QUEUE_STATUS_MAP = {
    "pending": "queued",
    "queued": "queued",
    "running": "queued",
    "paused": "queued",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}

_HISTORY_STATUS_MAP = {
    "pending": "queued",
    "queued": "queued",
    "running": "running",
    "paused": "queued",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}

_TERMINAL_QUEUE_STATUSES = {"completed", "failed", "cancelled"}


@dataclass
class FileMigrationReport:
    file_path: str
    file_kind: str
    existed: bool
    detected_schema: str | None
    target_schema: str
    dry_run: bool
    changed: bool = False
    total_entries: int = 0
    migrated_entries: int = 0
    preserved_entries: int = 0
    skipped_entries: int = 0
    backup_path: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueueHistoryMigrationReport:
    queue: FileMigrationReport | None = None
    history: FileMigrationReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue": self.queue.to_dict() if self.queue else None,
            "history": self.history.to_dict() if self.history else None,
        }


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except Exception:
            return None
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None
    return None


def _to_iso_timestamp(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else _utcnow_iso()


def _to_epoch(value: Any) -> float:
    parsed = _parse_datetime(value)
    return parsed.timestamp() if parsed else time.time()


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json_or_jsonl(path: Path) -> Any:
    raw = _read_text(path).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        entries: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
        return entries


def detect_queue_schema(data_or_path: Path | str | dict[str, Any] | None) -> str | None:
    data = _read_json_or_jsonl(Path(data_or_path)) if isinstance(data_or_path, (str, Path)) else data_or_path
    if data is None:
        return None
    if isinstance(data, dict):
        schema = data.get("schema_version")
        if schema is not None:
            return str(schema)
        if "jobs" in data and isinstance(data.get("jobs"), list):
            return "legacy-queue-list"
        if "pipeline_config" in data:
            return "2.0"
        if "config" in data or "prompts" in data:
            return "2.4"
        if "normalized_record_snapshot" in data:
            return "2.6-precanonical"
        if "njr_snapshot" in data:
            return "2.6"
    return "legacy"


def detect_history_schema(path_or_entries: Path | str | list[dict[str, Any]] | dict[str, Any] | None) -> str | None:
    data = _read_json_or_jsonl(Path(path_or_entries)) if isinstance(path_or_entries, (str, Path)) else path_or_entries
    if data is None:
        return None
    entries = data if isinstance(data, list) else [data]
    versions: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            versions.add("invalid")
            continue
        if entry.get("history_schema") == TARGET_HISTORY_SCHEMA and "njr_snapshot" in entry:
            versions.add(TARGET_HISTORY_SCHEMA)
        elif "pipeline_config" in entry:
            versions.add("2.0")
        elif "normalized_record_snapshot" in entry:
            versions.add("2.6-precanonical")
        elif "config" in entry or "prompts" in entry:
            versions.add("2.4")
        else:
            versions.add("legacy")
    if not versions:
        return None
    if len(versions) == 1:
        return next(iter(versions))
    return "mixed:" + ",".join(sorted(versions))


def _ensure_backup(path: Path, backup_dir: Path | None) -> Path:
    root = backup_dir or (path.parent / "migration_backups")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = root / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, backup_path)
    return backup_path


def _canonicalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = dict(raw.get("pipeline_config") or raw.get("config") or {})
    prompts = raw.get("prompts") if isinstance(raw.get("prompts"), dict) else {}
    if prompts and "prompt" not in config:
        config["prompt"] = str(prompts.get("positive") or "")
    if prompts and "negative_prompt" not in config:
        config["negative_prompt"] = str(prompts.get("negative") or "")
    if "model_name" in config and "model" not in config:
        config["model"] = config.get("model_name")
    if "sampler_name" in config and "sampler" not in config:
        config["sampler"] = config.get("sampler_name")
    return config


def _extract_legacy_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(raw.get("metadata") or {})
    execution_metadata = raw.get("execution_metadata")
    if isinstance(execution_metadata, dict):
        metadata["legacy_execution_metadata"] = dict(execution_metadata)
    outputs = raw.get("outputs")
    if isinstance(outputs, dict):
        metadata["legacy_outputs"] = dict(outputs)
    return metadata


def _lora_tags_from_config(config: dict[str, Any]) -> list[LoRATag]:
    tags: list[LoRATag] = []
    raw_tags = config.get("lora_tags") or []
    if not isinstance(raw_tags, list):
        return tags
    for raw in raw_tags:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        tags.append(LoRATag(name=name, weight=_coerce_float(raw.get("weight"), 1.0)))
    return tags


def _build_stage_chain(config: dict[str, Any]) -> list[StageConfig]:
    return [
        StageConfig(
            stage_type="txt2img",
            enabled=True,
            steps=_coerce_int(config.get("steps"), 20),
            cfg_scale=_coerce_float(config.get("cfg_scale"), 7.0),
            sampler_name=str(config.get("sampler") or config.get("sampler_name") or "Euler a"),
            scheduler=str(config.get("scheduler") or ""),
            model=str(config.get("model") or config.get("model_name") or "unknown"),
            vae=str(config.get("vae") or "") or None,
            extra={"migration_tool": "v2.6"},
        )
    ]


def _build_migrated_njr(raw: dict[str, Any], source_schema: str) -> NormalizedJobRecord:
    if isinstance(raw.get("normalized_record_snapshot"), dict):
        snapshot = raw["normalized_record_snapshot"]
        prompts = snapshot.get("prompts") if isinstance(snapshot.get("prompts"), dict) else {}
        config = dict(snapshot.get("config") or {})
        if prompts and "prompt" not in config:
            config["prompt"] = str(prompts.get("positive") or "")
        if prompts and "negative_prompt" not in config:
            config["negative_prompt"] = str(prompts.get("negative") or "")
        metadata = dict(snapshot.get("execution_metadata") or {})
    else:
        config = _canonicalize_config(raw)
        metadata = {}

    metadata.update(_extract_legacy_metadata(raw))
    prompt = str(raw.get("prompt") or config.get("prompt") or "")
    negative = str(raw.get("negative_prompt") or config.get("negative_prompt") or "")
    created_at = raw.get("created_at") or raw.get("timestamp") or raw.get("recorded_at")

    outputs = raw.get("outputs")
    output_paths: list[str] = []
    if isinstance(outputs, dict):
        output_paths = [str(path) for path in outputs.get("image_paths") or [] if path]

    batch_size = max(1, _coerce_int(config.get("batch_size"), 1))
    n_iter = max(1, _coerce_int(config.get("n_iter"), 1))
    batch_index = max(0, _coerce_int(config.get("batch_index"), 0))
    variant_index = max(0, _coerce_int(config.get("variant_index"), 0))

    return NormalizedJobRecord(
        job_id=str(raw.get("job_id") or raw.get("id") or f"migrated-{int(time.time())}"),
        config=config,
        path_output_dir=str(raw.get("path_output_dir") or raw.get("output_dir") or "output"),
        filename_template=str(raw.get("filename_template") or "{seed}"),
        seed=_coerce_int(config.get("seed"), 0),
        variant_index=variant_index,
        variant_total=max(1, _coerce_int(config.get("variant_total"), 1)),
        batch_index=batch_index,
        batch_total=max(1, _coerce_int(config.get("batch_total"), 1)),
        created_ts=_to_epoch(created_at),
        randomizer_summary={"migrated_from_schema": source_schema},
        prompt_pack_id=str(metadata.get("prompt_pack_id") or raw.get("prompt_pack_id") or ""),
        prompt_pack_name=str(metadata.get("prompt_pack_name") or raw.get("prompt_pack_name") or ""),
        prompt_pack_row_index=max(0, _coerce_int(metadata.get("prompt_pack_row_index"), 0)),
        positive_prompt=prompt,
        negative_prompt=negative,
        positive_embeddings=list(config.get("positive_embeddings") or []),
        negative_embeddings=list(config.get("negative_embeddings") or []),
        lora_tags=_lora_tags_from_config(config),
        matrix_slot_values=dict(config.get("matrix_slot_values") or {}),
        steps=_coerce_int(config.get("steps"), 20),
        cfg_scale=_coerce_float(config.get("cfg_scale"), 7.0),
        width=_coerce_int(config.get("width"), 512),
        height=_coerce_int(config.get("height"), 512),
        sampler_name=str(config.get("sampler") or config.get("sampler_name") or "Euler a"),
        scheduler=str(config.get("scheduler") or ""),
        clip_skip=_coerce_int(config.get("clip_skip"), 0),
        base_model=str(config.get("model") or config.get("model_name") or "unknown"),
        vae=str(config.get("vae") or "") or None,
        stage_chain=_build_stage_chain(config),
        loop_type="pipeline",
        loop_count=n_iter,
        images_per_prompt=batch_size,
        variant_mode="migrated_legacy",
        run_mode="QUEUE",
        queue_source="ADD_TO_QUEUE",
        randomization_enabled=bool(config.get("randomization_enabled", False)),
        matrix_name=config.get("matrix_name"),
        matrix_mode=config.get("matrix_mode"),
        matrix_prompt_mode=config.get("matrix_prompt_mode"),
        config_variant_label="migrated",
        config_variant_index=variant_index,
        config_variant_overrides={},
        aesthetic_enabled=bool(config.get("aesthetic_enabled", False)),
        aesthetic_weight=config.get("aesthetic_weight"),
        aesthetic_text=config.get("aesthetic_text"),
        aesthetic_embedding=config.get("aesthetic_embedding"),
        extra_metadata={"migration_tool": "PR-MIG-203", "migrated_from_schema": source_schema, **metadata},
        output_paths=output_paths,
        thumbnail_path=None,
        status=JobStatusV2.QUEUED,
        error_message=raw.get("error_message"),
    )


def _serialized_njr_snapshot(record: NormalizedJobRecord) -> dict[str, Any]:
    snapshot = build_job_snapshot(Job(job_id=record.job_id, priority=JobPriority.NORMAL), record)
    return {"normalized_job": snapshot["normalized_job"]}


def _migrate_queue_entry(raw: dict[str, Any], source_schema: str, report: FileMigrationReport) -> dict[str, Any] | None:
    if raw.get("queue_schema") == SCHEMA_VERSION and isinstance(raw.get("njr_snapshot"), dict):
        valid, _ = validate_queue_item(raw)
        if valid:
            report.preserved_entries += 1
            return dict(raw)

    status = _QUEUE_STATUS_MAP.get(str(raw.get("status") or "queued").lower(), "queued")
    if status in _TERMINAL_QUEUE_STATUSES:
        report.skipped_entries += 1
        report.warnings.append(
            f"Skipped terminal legacy queue entry {raw.get('job_id') or raw.get('queue_id')}"
        )
        return None

    record = _build_migrated_njr(raw, source_schema)
    metadata = {
        "migration_tool": "PR-MIG-203",
        "migrated_from_schema": source_schema,
        "run_mode": "queue",
        "source": str(raw.get("source") or "migration"),
        "prompt_source": str(raw.get("prompt_source") or "manual"),
    }
    if record.prompt_pack_id:
        metadata["prompt_pack_id"] = record.prompt_pack_id

    migrated = {
        "queue_id": str(raw.get("queue_id") or raw.get("job_id") or record.job_id),
        "njr_snapshot": _serialized_njr_snapshot(record),
        "priority": _coerce_int(raw.get("priority"), int(JobPriority.NORMAL)),
        "status": status,
        "created_at": _to_iso_timestamp(raw.get("created_at") or raw.get("timestamp")),
        "queue_schema": SCHEMA_VERSION,
        "metadata": metadata,
    }
    report.migrated_entries += 1
    return migrated


def _migrate_history_entry(raw: dict[str, Any], source_schema: str, report: FileMigrationReport) -> HistoryRecord:
    if raw.get("history_schema") == TARGET_HISTORY_SCHEMA and isinstance(raw.get("njr_snapshot"), dict):
        report.preserved_entries += 1
        return HistoryRecord.from_dict(raw)

    record = _build_migrated_njr(raw, source_schema)
    execution_metadata = raw.get("execution_metadata") if isinstance(raw.get("execution_metadata"), dict) else {}
    runtime = {
        "started_at": _to_iso_timestamp(
            execution_metadata.get("start_time") or raw.get("started_at") or raw.get("timestamp")
        ),
        "completed_at": _to_iso_timestamp(
            execution_metadata.get("end_time") or raw.get("completed_at") or raw.get("timestamp")
        ),
    }
    if execution_metadata.get("duration_seconds") is not None:
        runtime["duration_seconds"] = _coerce_float(execution_metadata.get("duration_seconds"), 0.0)

    ui_summary = {
        "job_id": record.job_id,
        "model": record.base_model,
        "positive_preview": record.positive_prompt[:120],
        "negative_preview": record.negative_prompt[:120] if record.negative_prompt else None,
        "estimated_images": record.estimated_image_count(),
    }
    result = raw.get("result") if isinstance(raw.get("result"), dict) else None
    if result is None and isinstance(raw.get("outputs"), dict):
        result = {"migrated_outputs": dict(raw["outputs"])}

    report.migrated_entries += 1
    return HistoryRecord(
        id=str(raw.get("id") or raw.get("job_id") or record.job_id),
        timestamp=_to_iso_timestamp(raw.get("timestamp") or raw.get("created_at")),
        status=_HISTORY_STATUS_MAP.get(str(raw.get("status") or "queued").lower(), "queued"),
        history_schema=TARGET_HISTORY_SCHEMA,
        njr_snapshot=_serialized_njr_snapshot(record),
        metadata={
            "migration_tool": "PR-MIG-203",
            "migrated_from_schema": source_schema,
            **_extract_legacy_metadata(raw),
        },
        runtime=runtime,
        ui_summary={k: v for k, v in ui_summary.items() if v is not None},
        result=result,
    )


def migrate_queue_state_file(
    path: Path | str,
    *,
    dry_run: bool = False,
    backup_dir: Path | str | None = None,
) -> FileMigrationReport:
    queue_path = Path(path)
    report = FileMigrationReport(
        file_path=str(queue_path),
        file_kind="queue",
        existed=queue_path.exists(),
        detected_schema=None,
        target_schema=SCHEMA_VERSION,
        dry_run=dry_run,
    )
    if not queue_path.exists():
        report.warnings.append("Queue file does not exist.")
        return report

    raw = _read_json_or_jsonl(queue_path)
    report.detected_schema = detect_queue_schema(raw)
    if raw is None:
        report.warnings.append("Queue file is empty.")
        return report

    if isinstance(raw, dict) and isinstance(raw.get("jobs"), list):
        raw_jobs = [job for job in raw.get("jobs", []) if isinstance(job, dict)]
        auto_run_enabled = bool(raw.get("auto_run_enabled", False))
        paused = bool(raw.get("paused", False))
    elif isinstance(raw, dict):
        raw_jobs = [raw]
        auto_run_enabled = False
        paused = False
    else:
        report.warnings.append("Queue file is not a mapping or queue snapshot.")
        return report

    report.total_entries = len(raw_jobs)
    migrated_jobs: list[dict[str, Any]] = []
    source_schema = report.detected_schema or "legacy"
    for job in raw_jobs:
        migrated = _migrate_queue_entry(job, source_schema, report)
        if migrated is not None:
            migrated_jobs.append(migrated)

    changed = report.migrated_entries > 0 or report.skipped_entries > 0 or source_schema != SCHEMA_VERSION
    report.changed = changed
    if dry_run or not changed:
        return report

    backup_path = _ensure_backup(queue_path, Path(backup_dir) if backup_dir else None)
    report.backup_path = str(backup_path)
    save_queue_snapshot(
        QueueSnapshotV1(
            jobs=migrated_jobs,
            auto_run_enabled=auto_run_enabled,
            paused=paused,
        ),
        queue_path,
    )
    return report


def migrate_history_file(
    path: Path | str,
    *,
    dry_run: bool = False,
    backup_dir: Path | str | None = None,
) -> FileMigrationReport:
    history_path = Path(path)
    report = FileMigrationReport(
        file_path=str(history_path),
        file_kind="history",
        existed=history_path.exists(),
        detected_schema=None,
        target_schema=TARGET_HISTORY_SCHEMA,
        dry_run=dry_run,
    )
    if not history_path.exists():
        report.warnings.append("History file does not exist.")
        return report

    raw = _read_json_or_jsonl(history_path)
    report.detected_schema = detect_history_schema(raw)
    if raw is None:
        report.warnings.append("History file is empty.")
        return report

    entries = raw if isinstance(raw, list) else [raw]
    entries = [entry for entry in entries if isinstance(entry, dict)]
    report.total_entries = len(entries)
    source_schema = report.detected_schema or "legacy"
    migrated_records = [_migrate_history_entry(entry, source_schema, report) for entry in entries]
    changed = report.migrated_entries > 0 or source_schema != TARGET_HISTORY_SCHEMA
    report.changed = changed
    if dry_run or not changed:
        return report

    backup_path = _ensure_backup(history_path, Path(backup_dir) if backup_dir else None)
    report.backup_path = str(backup_path)
    JobHistoryStore(history_path).save(migrated_records)
    return report


def migrate_queue_and_history(
    *,
    queue_path: Path | str | None = None,
    history_path: Path | str | None = None,
    dry_run: bool = False,
    backup_dir: Path | str | None = None,
) -> QueueHistoryMigrationReport:
    report = QueueHistoryMigrationReport()
    if queue_path is not None:
        report.queue = migrate_queue_state_file(
            queue_path,
            dry_run=dry_run,
            backup_dir=backup_dir,
        )
    if history_path is not None:
        report.history = migrate_history_file(
            history_path,
            dry_run=dry_run,
            backup_dir=backup_dir,
        )
    return report


__all__ = [
    "FileMigrationReport",
    "QueueHistoryMigrationReport",
    "detect_history_schema",
    "detect_queue_schema",
    "migrate_history_file",
    "migrate_queue_and_history",
    "migrate_queue_state_file",
]
