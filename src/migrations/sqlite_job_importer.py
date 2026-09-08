"""Offline, backup-first import of legacy queue/history state into SQLite."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.pipeline.job_models_v2 import LoRATag, NormalizedJobRecord, StageConfig, migrate_legacy_njr
from src.queue.job_model import (
    Job,
    JobExecutionMetadata,
    JobPriority,
    JobStatus,
    RetryAttempt,
    StageCheckpoint,
)
from src.queue.job_repository import JobRepository
from src.utils.error_envelope_v2 import deserialize_envelope
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

_STATUS_MAP = {
    "pending": JobStatus.QUEUED,
    "paused": JobStatus.QUEUED,
    "queued": JobStatus.QUEUED,
    "running": JobStatus.QUEUED,
    "completed": JobStatus.COMPLETED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
    "canceled": JobStatus.CANCELLED,
}


class LegacyImportError(RuntimeError):
    """Raised when an import cannot be performed without losing certainty."""


@dataclass(frozen=True)
class SourceEvidence:
    path: str
    kind: str
    sha256: str
    byte_count: int
    records_discovered: int


@dataclass
class ImportAnalysis:
    database_path: str
    sources: list[SourceEvidence] = field(default_factory=list)
    records_discovered: int = 0
    valid_identities: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    invalid_records: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    existing_count: int = 0
    expected_resulting_count: int = 0
    expected_runnable: int = 0
    expected_terminal: int = 0
    _jobs: list[tuple[Job, str, str]] = field(default_factory=list, repr=False)

    @property
    def can_import(self) -> bool:
        return not self.conflicts and not self.invalid_records

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_jobs", None)
        value["can_import"] = self.can_import
        return value


@dataclass
class ImportResult:
    analysis: ImportAnalysis
    dry_run: bool
    imported: list[str] = field(default_factory=list)
    idempotent_duplicates: list[str] = field(default_factory=list)
    backup_directory: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis.to_dict(),
            "dry_run": self.dry_run,
            "imported": self.imported,
            "idempotent_duplicates": self.idempotent_duplicates,
            "backup_directory": self.backup_directory,
            "validation": self.validation,
        }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _read_records(path: Path, kind: str) -> tuple[list[dict[str, Any]], SourceEvidence]:
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8-sig").strip()
    if not text:
        records: list[dict[str, Any]] = []
    else:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
        if kind == "queue" and isinstance(parsed, Mapping) and isinstance(parsed.get("jobs"), list):
            parsed = parsed["jobs"]
        records = [dict(item) for item in (parsed if isinstance(parsed, list) else [parsed]) if isinstance(item, Mapping)]
        total_items = len(parsed) if isinstance(parsed, list) else 1
        if len(records) != total_items:
            raise LegacyImportError(f"{path}: contains non-object records")
    return records, SourceEvidence(
        path=str(path.resolve()),
        kind=kind,
        sha256=_sha256_bytes(raw_bytes),
        byte_count=len(raw_bytes),
        records_discovered=len(records),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
        except ValueError:
            return None
    return None


def _priority(value: Any) -> JobPriority:
    try:
        return JobPriority(int(value))
    except (TypeError, ValueError):
        return JobPriority.NORMAL


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


def _legacy_config(raw: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(raw.get("pipeline_config") or raw.get("config") or {})
    prompts = raw.get("prompts") if isinstance(raw.get("prompts"), Mapping) else {}
    if prompts and "prompt" not in config:
        config["prompt"] = str(prompts.get("positive") or "")
    if prompts and "negative_prompt" not in config:
        config["negative_prompt"] = str(prompts.get("negative") or "")
    if "model_name" in config and "model" not in config:
        config["model"] = config["model_name"]
    return config


def _legacy_loras(config: Mapping[str, Any]) -> list[LoRATag]:
    return [
        LoRATag(name=str(item["name"]), weight=_coerce_float(item.get("weight"), 1.0))
        for item in config.get("lora_tags") or []
        if isinstance(item, Mapping) and item.get("name")
    ]


def _build_migrated_njr(raw: Mapping[str, Any], source_schema: str) -> NormalizedJobRecord:
    precursor = raw.get("normalized_record_snapshot")
    if isinstance(precursor, Mapping):
        config = dict(precursor.get("config") or {})
        prompts = precursor.get("prompts")
        if isinstance(prompts, Mapping):
            config.setdefault("prompt", str(prompts.get("positive") or ""))
            config.setdefault("negative_prompt", str(prompts.get("negative") or ""))
    else:
        config = _legacy_config(raw)
    metadata = dict(raw.get("metadata") or {})
    if isinstance(raw.get("execution_metadata"), Mapping):
        metadata["legacy_execution_metadata"] = dict(raw["execution_metadata"])
    if isinstance(raw.get("outputs"), Mapping):
        metadata["legacy_outputs"] = dict(raw["outputs"])
    created = _parse_datetime(raw.get("created_at") or raw.get("timestamp"))
    return migrate_legacy_njr(
        {
            "job_id": str(raw.get("queue_id") or raw.get("job_id") or raw.get("id") or f"migrated-{time.time_ns()}"),
            "config": config,
            "path_output_dir": str(raw.get("path_output_dir") or raw.get("output_dir") or "output"),
            "filename_template": str(raw.get("filename_template") or "{seed}"),
            "seed": _coerce_int(config.get("seed"), 0),
            "variant_index": max(0, _coerce_int(config.get("variant_index"), 0)),
            "variant_total": max(1, _coerce_int(config.get("variant_total"), 1)),
            "batch_index": max(0, _coerce_int(config.get("batch_index"), 0)),
            "batch_total": max(1, _coerce_int(config.get("batch_total"), 1)),
            "created_ts": created.timestamp() if created else time.time(),
            "randomizer_summary": {"migrated_from_schema": source_schema},
            "prompt_source": "pack" if raw.get("prompt_pack_id") else "cli",
            "prompt_pack_id": str(raw.get("prompt_pack_id") or ""),
            "prompt_pack_name": str(raw.get("prompt_pack_name") or ""),
            "prompt_pack_row_index": max(0, _coerce_int(raw.get("prompt_pack_row_index"), 0)),
            "positive_prompt": str(raw.get("prompt") or config.get("prompt") or ""),
            "negative_prompt": str(raw.get("negative_prompt") or config.get("negative_prompt") or ""),
            "positive_embeddings": list(config.get("positive_embeddings") or []),
            "negative_embeddings": list(config.get("negative_embeddings") or []),
            "lora_tags": [asdict(tag) for tag in _legacy_loras(config)],
            "matrix_slot_values": dict(config.get("matrix_slot_values") or {}),
            "stage_chain": [asdict(StageConfig(
                stage_type="txt2img",
                enabled=True,
                steps=_coerce_int(config.get("steps"), 20),
                cfg_scale=_coerce_float(config.get("cfg_scale"), 7.0),
                sampler_name=str(config.get("sampler") or config.get("sampler_name") or "Euler a"),
                model=str(config.get("model") or config.get("model_name") or "unknown"),
                extra={"migration_tool": "PR-MVP-040"},
            ))],
            "loop_type": "pipeline",
            "loop_count": max(1, _coerce_int(config.get("n_iter"), 1)),
            "images_per_prompt": max(1, _coerce_int(config.get("batch_size"), 1)),
            "variant_mode": "migrated_legacy",
            "config_variant_label": "migrated",
            "config_variant_index": max(0, _coerce_int(config.get("variant_index"), 0)),
            "extra_metadata": {
                "migration_tool": "PR-MVP-040",
                "migrated_from_schema": source_schema,
                **metadata,
            },
        }
    )


def _execution_metadata(raw: Mapping[str, Any], interrupted: bool) -> JobExecutionMetadata:
    container = raw.get("execution_metadata") or (raw.get("metadata") or {}).get("execution_metadata") or {}
    if not isinstance(container, Mapping):
        container = {}
    retries = []
    for item in container.get("retry_attempts") or []:
        if isinstance(item, Mapping):
            retries.append(RetryAttempt(
                stage=str(item.get("stage") or "pipeline"),
                attempt_index=int(item.get("attempt_index") or 0),
                max_attempts=int(item.get("max_attempts") or 0),
                reason=str(item.get("reason") or "legacy import"),
                timestamp=float(item.get("timestamp") or 0.0),
            ))
    checkpoints = []
    for item in container.get("stage_checkpoints") or []:
        if isinstance(item, Mapping):
            checkpoints.append(StageCheckpoint(
                stage_name=str(item.get("stage_name") or ""),
                completed_at=float(item.get("completed_at") or 0.0),
                output_paths=[str(path) for path in item.get("output_paths") or [] if path],
                metadata=dict(item.get("metadata") or {}),
            ))
    action = "legacy_running_requeued" if interrupted else container.get("last_control_action")
    return JobExecutionMetadata(
        external_pids=[],
        retry_attempts=retries,
        stage_checkpoints=checkpoints,
        last_control_action=str(action) if action else None,
        return_to_queue_count=int(container.get("return_to_queue_count") or 0) + int(interrupted),
    )


def _extract_result(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    result = raw.get("result")
    if isinstance(result, Mapping):
        return dict(result)
    outputs = raw.get("outputs")
    if isinstance(outputs, Mapping):
        return {"migrated_outputs": dict(outputs)}
    return None


def _record_to_job(raw: Mapping[str, Any], source_kind: str) -> Job:
    snapshot = raw.get("njr_snapshot") or raw.get("snapshot")
    record = normalized_job_from_snapshot(snapshot) if isinstance(snapshot, Mapping) else None
    if record is None:
        record = _build_migrated_njr(dict(raw), f"legacy-{source_kind}")
        snapshot = {"normalized_job": record.to_dict()}
    identity = str(raw.get("queue_id") or raw.get("job_id") or raw.get("id") or record.job_id).strip()
    if not identity:
        raise LegacyImportError("record has no stable job identity")
    if identity != record.job_id:
        raise LegacyImportError(
            f"identity {identity!r} disagrees with immutable NJR {record.job_id!r}"
        )
    raw_status = str(raw.get("status") or "queued").lower()
    if raw_status not in _STATUS_MAP:
        raise LegacyImportError(f"job {identity}: unsupported status {raw_status!r}")
    status = _STATUS_MAP[raw_status]
    created = _parse_datetime(raw.get("created_at") or raw.get("timestamp")) or datetime.utcnow()
    metadata_raw = raw.get("metadata")
    metadata: Mapping[str, Any] = metadata_raw if isinstance(metadata_raw, Mapping) else {}
    snapshot_mapping: Mapping[str, Any] = snapshot if isinstance(snapshot, Mapping) else {}
    job = Job(
        job_id=identity,
        priority=_priority(raw.get("priority")),
        status=status,
        created_at=created,
        updated_at=_parse_datetime(raw.get("updated_at")) or created,
        started_at=_parse_datetime(raw.get("started_at")),
        completed_at=_parse_datetime(raw.get("completed_at")),
        error_message=(str(raw["error_message"]) if raw.get("error_message") else None),
        error_envelope=deserialize_envelope(raw.get("error_envelope") if isinstance(raw.get("error_envelope"), Mapping) else None),
        result=_extract_result(raw),
        run_mode=str(metadata.get("run_mode") or raw.get("run_mode") or "queue"),
        source=str(metadata.get("source") or raw.get("source") or "legacy_import"),
        prompt_source=str(metadata.get("prompt_source") or raw.get("prompt_source") or "manual"),
        prompt_pack_id=metadata.get("prompt_pack_id") or raw.get("prompt_pack_id"),
        snapshot=dict(snapshot_mapping),
        execution_metadata=_execution_metadata(raw, raw_status == "running"),
    )
    if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED} and job.completed_at is None:
        job.completed_at = job.updated_at
    job._normalized_record = record
    return job


def _existing_state(database_path: Path) -> tuple[int, dict[str, str]]:
    if not database_path.exists():
        return 0, {}
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        rows = connection.execute("SELECT job_id, njr_fingerprint FROM jobs").fetchall()
    except sqlite3.Error as exc:
        raise LegacyImportError(f"Cannot inspect existing repository {database_path}: {exc}") from exc
    finally:
        if "connection" in locals():
            connection.close()
    return len(rows), {str(row[0]): str(row[1]) for row in rows}


def analyze_legacy_state(
    *,
    database_path: Path | str,
    sources: Sequence[tuple[Path | str, str]],
) -> ImportAnalysis:
    """Build a no-write import plan from explicit ``(path, queue|history)`` sources."""
    db_path = Path(database_path)
    analysis = ImportAnalysis(database_path=str(db_path.resolve()))
    analysis.existing_count, existing = _existing_state(db_path)
    candidates: dict[str, tuple[Job, str, str]] = {}
    for source_value, source_kind in sources:
        source = Path(source_value)
        if source_kind not in {"queue", "history"}:
            raise ValueError(f"Unsupported source kind: {source_kind}")
        if not source.exists():
            analysis.warnings.append(f"Source not found: {source}")
            continue
        try:
            records, evidence = _read_records(source, source_kind)
        except (OSError, UnicodeError, json.JSONDecodeError, LegacyImportError) as exc:
            analysis.invalid_records.append(f"{source}: {exc}")
            continue
        analysis.sources.append(evidence)
        analysis.records_discovered += len(records)
        for index, raw in enumerate(records, start=1):
            try:
                job = _record_to_job(raw, source_kind)
                assert job._normalized_record is not None
                serialized = _canonical_json(job._normalized_record.to_dict())
                record_fingerprint = _sha256_bytes(serialized.encode("utf-8"))
                item = (job, evidence.sha256, record_fingerprint)
                previous = candidates.get(job.job_id)
                if previous is not None:
                    if previous[2] == record_fingerprint:
                        analysis.duplicates.append(job.job_id)
                    else:
                        analysis.conflicts.append(f"legacy records disagree for {job.job_id}")
                    continue
                canonical_fingerprint = _sha256_bytes(
                    _canonical_json({
                        "schema_version": "2.6",
                        "job_id": job.job_id,
                        "normalized_job": job._normalized_record.to_dict(),
                    }).encode("utf-8")
                )
                if job.job_id in existing and existing[job.job_id] != canonical_fingerprint:
                    analysis.conflicts.append(f"repository identity conflict for {job.job_id}")
                candidates[job.job_id] = item
            except Exception as exc:
                analysis.invalid_records.append(f"{source}:{index}: {exc}")
    for identity, item in candidates.items():
        if identity in existing:
            analysis.duplicates.append(identity)
            continue
        analysis.valid_identities.append(identity)
        analysis._jobs.append(item)
        if item[0].status == JobStatus.QUEUED:
            analysis.expected_runnable += 1
        else:
            analysis.expected_terminal += 1
    analysis.valid_identities.sort()
    analysis.duplicates = sorted(set(analysis.duplicates))
    analysis.conflicts = sorted(set(analysis.conflicts))
    analysis.expected_resulting_count = analysis.existing_count + len(analysis._jobs)
    return analysis


def _backup_state(
    analysis: ImportAnalysis,
    database_path: Path,
    backup_root: Path | None,
) -> Path:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    directory = (backup_root or database_path.parent / "migration_backups") / stamp
    directory.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "created_at": datetime.utcnow().isoformat(),
        "database": str(database_path.resolve()),
        "database_existed": database_path.exists(),
        "files": [],
    }
    paths = [Path(item.path) for item in analysis.sources]
    if database_path.exists():
        paths.append(database_path)
        paths.extend(
            companion
            for companion in (
                Path(f"{database_path}-wal"),
                Path(f"{database_path}-shm"),
            )
            if companion.exists()
        )
    for source in paths:
        destination = directory / source.name
        shutil.copy2(source, destination)
        manifest["files"].append({
            "source": str(source.resolve()),
            "backup": str(destination.resolve()),
            "sha256": _sha256_bytes(destination.read_bytes()),
        })
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return directory


def _restore_database_backup(database_path: Path, backup_directory: Path) -> None:
    manifest = json.loads((backup_directory / "manifest.json").read_text(encoding="utf-8"))
    for companion in (database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")):
        companion.unlink(missing_ok=True)
    if not manifest.get("database_existed"):
        return
    for item in manifest.get("files") or []:
        source = Path(str(item.get("source") or ""))
        if source in {database_path.resolve(), Path(f"{database_path.resolve()}-wal"), Path(f"{database_path.resolve()}-shm")}:
            shutil.copy2(Path(item["backup"]), source)


def import_legacy_state(
    *,
    database_path: Path | str,
    sources: Sequence[tuple[Path | str, str]],
    dry_run: bool = True,
    backup_root: Path | str | None = None,
) -> ImportResult:
    """Analyze, back up, atomically import, and validate legacy state."""
    db_path = Path(database_path)
    analysis = analyze_legacy_state(database_path=db_path, sources=sources)
    result = ImportResult(analysis=analysis, dry_run=dry_run)
    if dry_run:
        return result
    if not analysis.can_import:
        raise LegacyImportError("Import rejected; resolve conflicts/invalid records first")
    if not analysis.sources:
        raise LegacyImportError("Import rejected; no readable legacy sources were discovered")
    backup = _backup_state(analysis, db_path, Path(backup_root) if backup_root else None)
    result.backup_directory = str(backup.resolve())
    try:
        with JobRepository(db_path) as repository:
            imported, duplicates = repository.import_jobs(
                analysis._jobs,
                expected_total_count=analysis.expected_resulting_count,
            )
            actual_ids = repository.identities()
            expected_ids = set(analysis.valid_identities)
            statuses = {
                job.job_id: job.status.value for job in repository.list_job_models()
            }
            validation = {
                "expected_count": analysis.expected_resulting_count,
                "actual_count": repository.count(),
                "missing_identities": sorted(expected_ids - actual_ids),
                "status_by_identity": statuses,
                "runnable_count": repository.count([JobStatus.QUEUED]),
                "terminal_count": repository.count([
                    JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED
                ]),
            }
            if validation["actual_count"] != validation["expected_count"] or validation["missing_identities"]:
                raise LegacyImportError(f"Post-import validation failed: {validation}")
            result.imported = imported
            result.idempotent_duplicates = duplicates
            result.validation = validation
    except Exception:
        _restore_database_backup(db_path, backup)
        raise
    return result


__all__ = [
    "ImportAnalysis",
    "ImportResult",
    "LegacyImportError",
    "SourceEvidence",
    "analyze_legacy_state",
    "import_legacy_state",
]
