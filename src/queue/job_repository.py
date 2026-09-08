"""Transactional SQLite authority for StableNew job lifecycle state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_history_store import JobHistoryEntry, JobHistoryStore
from src.queue.job_model import (
    Job,
    JobExecutionMetadata,
    JobPriority,
    JobStatus,
    RetryAttempt,
    StageCheckpoint,
)
from src.utils.error_envelope_v2 import deserialize_envelope, serialize_envelope

REPOSITORY_SCHEMA_VERSION = 1
_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
_ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.QUEUED,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


class JobRepositoryError(RuntimeError):
    """Base error for durable repository operations."""


class JobConflictError(JobRepositoryError):
    """Raised when a job identity already represents different work."""


class InvalidLifecycleTransition(JobRepositoryError):
    """Raised when a lifecycle transition violates the canonical state machine."""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _canonical_snapshot(job: Job) -> tuple[dict[str, Any], NormalizedJobRecord]:
    from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

    snapshot = getattr(job, "snapshot", None)
    record = getattr(job, "_normalized_record", None)
    if not isinstance(record, NormalizedJobRecord):
        record = normalized_job_from_snapshot(snapshot or {})
    if not isinstance(record, NormalizedJobRecord):
        raise ValueError(f"Job {job.job_id!r} has no canonical NormalizedJobRecord snapshot")
    serialized_record = record.to_dict()
    if str(serialized_record.get("job_id") or "") != job.job_id:
        raise ValueError("Job identity does not match its immutable NJR snapshot")
    # Store the NJR in the established snapshot envelope so replay can use the
    # same strict reader after a process restart. Runtime state lives in columns.
    canonical = {
        "schema_version": "2.6",
        "job_id": job.job_id,
        "normalized_job": serialized_record,
    }
    return canonical, record


def _execution_metadata_to_dict(metadata: JobExecutionMetadata) -> dict[str, Any]:
    return {
        "external_pids": list(metadata.external_pids),
        "retry_attempts": [asdict(item) for item in metadata.retry_attempts],
        "stage_checkpoints": [asdict(item) for item in metadata.stage_checkpoints],
        "last_control_action": metadata.last_control_action,
        "return_to_queue_count": metadata.return_to_queue_count,
    }


def _execution_metadata_from_dict(raw: Mapping[str, Any] | None) -> JobExecutionMetadata:
    data = dict(raw or {})
    retries = []
    for item in data.get("retry_attempts") or []:
        if not isinstance(item, Mapping):
            continue
        retries.append(
            RetryAttempt(
                stage=str(item.get("stage") or "pipeline"),
                attempt_index=int(item.get("attempt_index") or 0),
                max_attempts=int(item.get("max_attempts") or 0),
                reason=str(item.get("reason") or ""),
                timestamp=float(item.get("timestamp") or 0.0),
            )
        )
    checkpoints = []
    for item in data.get("stage_checkpoints") or []:
        if not isinstance(item, Mapping):
            continue
        checkpoints.append(
            StageCheckpoint(
                stage_name=str(item.get("stage_name") or ""),
                completed_at=float(item.get("completed_at") or 0.0),
                output_paths=[str(path) for path in item.get("output_paths") or [] if path],
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return JobExecutionMetadata(
        external_pids=[int(pid) for pid in data.get("external_pids") or []],
        retry_attempts=retries,
        stage_checkpoints=checkpoints,
        last_control_action=(
            str(data["last_control_action"]) if data.get("last_control_action") else None
        ),
        return_to_queue_count=int(data.get("return_to_queue_count") or 0),
    )


def _artifact_references(result: Mapping[str, Any] | None) -> list[str]:
    references: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                visit(child, str(child_key).lower())
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                visit(child, key)
            return
        if isinstance(value, str) and value and ("path" in key or key.endswith("artifact")):
            references.add(value)

    visit(dict(result or {}))
    return sorted(references)


def _lineage(snapshot: Mapping[str, Any]) -> tuple[str | None, str | None]:
    normalized = snapshot.get("normalized_job")
    source = normalized.get("source") if isinstance(normalized, Mapping) else snapshot.get("source")
    if not isinstance(source, Mapping):
        return None, None
    parent_job = source.get("parent_job_id")
    parent_artifact = source.get("parent_artifact_id")
    return (
        str(parent_job) if parent_job else None,
        str(parent_artifact) if parent_artifact else None,
    )


class JobRepository(JobHistoryStore):
    """SQLite-backed job authority and queue/history projection source."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = Path(path) if str(path) != ":memory:" else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._callbacks: list[Any] = []
        self._connection = sqlite3.connect(
            str(self.path) if self.path is not None else ":memory:",
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._configure()
        self._initialize_schema()

    def _configure(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 10000")
            if self.path is not None:
                self._connection.execute("PRAGMA journal_mode = WAL")
                self._connection.execute("PRAGMA synchronous = FULL")

    def _initialize_schema(self) -> None:
        with self.transaction() as connection:
            statements = (
                """
                CREATE TABLE IF NOT EXISTS repository_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    njr_snapshot TEXT NOT NULL,
                    njr_fingerprint TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    queue_order INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'running', 'completed', 'failed', 'cancelled')
                    ),
                    created_at TEXT NOT NULL,
                    queued_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0.0,
                    eta_seconds REAL,
                    worker_id TEXT,
                    run_mode TEXT NOT NULL,
                    source TEXT NOT NULL,
                    prompt_source TEXT NOT NULL,
                    prompt_pack_id TEXT,
                    randomizer_metadata TEXT NOT NULL,
                    variant_index INTEGER,
                    variant_total INTEGER,
                    execution_metadata TEXT NOT NULL,
                    error_message TEXT,
                    error_envelope TEXT,
                    result_json TEXT,
                    artifact_references TEXT NOT NULL,
                    parent_job_id TEXT,
                    parent_artifact_id TEXT,
                    payload_summary TEXT NOT NULL
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_runnable
                    ON jobs(status, priority DESC, queue_order ASC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_terminal
                    ON jobs(status, completed_at DESC)
                """,
                """
                CREATE TABLE IF NOT EXISTS legacy_imports (
                    source_fingerprint TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    record_fingerprint TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY(source_fingerprint, job_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                )
                """,
            )
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT OR IGNORE INTO repository_metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(REPOSITORY_SCHEMA_VERSION)),
            )
            version = connection.execute(
                "SELECT value FROM repository_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version is None or int(version["value"]) != REPOSITORY_SCHEMA_VERSION:
                raise JobRepositoryError(
                    f"Unsupported job repository schema: {version['value'] if version else 'missing'}"
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> JobRepository:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return REPOSITORY_SCHEMA_VERSION

    @staticmethod
    def read_diagnostics_projection(path: str | Path) -> list[dict[str, Any]]:
        """Read a bounded, non-mutating diagnostics projection from an existing repository."""
        repository_path = Path(path)
        uri = f"file:{repository_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT job_id, status, priority, created_at, started_at, updated_at,
                       progress, run_mode, source, prompt_source, prompt_pack_id,
                       error_message
                FROM jobs ORDER BY queue_order ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def record_job_submission(self, job: Job) -> None:
        snapshot, record = _canonical_snapshot(job)
        serialized_snapshot = _json_dumps(snapshot)
        fingerprint = hashlib.sha256(serialized_snapshot.encode("utf-8")).hexdigest()
        parent_job_id, parent_artifact_id = _lineage(snapshot)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT njr_fingerprint FROM jobs WHERE job_id = ?", (job.job_id,)
            ).fetchone()
            if existing is not None:
                if existing["njr_fingerprint"] == fingerprint:
                    raise JobConflictError(f"Job {job.job_id!r} has already been submitted")
                raise JobConflictError(f"Job identity conflict for {job.job_id!r}")
            next_order = connection.execute(
                "SELECT COALESCE(MAX(queue_order), 0) + 1 AS value FROM jobs"
            ).fetchone()["value"]
            created = _iso(job.created_at) or datetime.utcnow().isoformat()
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, njr_snapshot, njr_fingerprint, priority, queue_order, status,
                    created_at, queued_at, started_at, completed_at, updated_at,
                    progress, eta_seconds, worker_id, run_mode, source, prompt_source,
                    prompt_pack_id, randomizer_metadata, variant_index, variant_total,
                    execution_metadata, error_message, error_envelope, result_json,
                    artifact_references, parent_job_id, parent_artifact_id, payload_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    serialized_snapshot,
                    fingerprint,
                    int(job.priority),
                    int(next_order),
                    job.status.value,
                    created,
                    created,
                    _iso(job.started_at),
                    _iso(job.completed_at),
                    _iso(job.updated_at) or created,
                    float(job.progress),
                    job.eta_seconds,
                    str(job.worker_id) if job.worker_id is not None else None,
                    job.run_mode,
                    job.source,
                    job.prompt_source,
                    job.prompt_pack_id,
                    _json_dumps(job.randomizer_metadata or {}),
                    job.variant_index,
                    job.variant_total,
                    _json_dumps(_execution_metadata_to_dict(job.execution_metadata)),
                    job.error_message,
                    _json_dumps(serialize_envelope(job.error_envelope))
                    if job.error_envelope is not None
                    else None,
                    _json_dumps(job.result) if job.result is not None else None,
                    _json_dumps(_artifact_references(job.result)),
                    parent_job_id,
                    parent_artifact_id,
                    f"{record.positive_prompt[:64]} | {record.base_model}",
                ),
            )
        self._emit(self.get_job(job.job_id))

    def transition_job(
        self,
        job: Job,
        status: JobStatus,
        *,
        error_message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Job:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job.job_id,)).fetchone()
            if row is None:
                raise JobRepositoryError(f"Unknown job identity {job.job_id!r}")
            current = JobStatus(row["status"])
            if status != current and status not in _ALLOWED_TRANSITIONS[current]:
                raise InvalidLifecycleTransition(f"Cannot transition {job.job_id} from {current.value} to {status.value}")
            now = datetime.utcnow()
            started_at = row["started_at"]
            completed_at = row["completed_at"]
            if status == JobStatus.RUNNING and not started_at:
                started_at = _iso(job.started_at) or now.isoformat()
            if status == JobStatus.QUEUED:
                started_at = None
                completed_at = None
            elif status in _TERMINAL_STATUSES:
                completed_at = _iso(job.completed_at) or now.isoformat()
                job.progress = 0.0
                job.eta_seconds = None
            effective_result = result if result is not None else job.result
            effective_error = error_message or job.error_message
            connection.execute(
                """
                UPDATE jobs SET status = ?, started_at = ?, completed_at = ?, updated_at = ?,
                    progress = ?, eta_seconds = ?, worker_id = ?, execution_metadata = ?,
                    error_message = ?, error_envelope = ?, result_json = ?,
                    artifact_references = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    status.value,
                    started_at,
                    completed_at,
                    now.isoformat(),
                    float(job.progress),
                    job.eta_seconds,
                    str(job.worker_id) if job.worker_id is not None else None,
                    _json_dumps(_execution_metadata_to_dict(job.execution_metadata)),
                    effective_error,
                    _json_dumps(serialize_envelope(job.error_envelope))
                    if job.error_envelope is not None
                    else None,
                    _json_dumps(effective_result) if effective_result is not None else None,
                    _json_dumps(_artifact_references(effective_result)),
                    job.job_id,
                    current.value,
                ),
            )
        persisted = self.get_job_model(job.job_id)
        if persisted is None:
            raise JobRepositoryError(f"Failed to reload transitioned job {job.job_id!r}")
        self._emit(self.get_job(job.job_id))
        return persisted

    def persist_runtime_state(self, job: Job) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET progress = ?, eta_seconds = ?, worker_id = ?,
                    execution_metadata = ?, error_envelope = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    float(job.progress),
                    job.eta_seconds,
                    str(job.worker_id) if job.worker_id is not None else None,
                    _json_dumps(_execution_metadata_to_dict(job.execution_metadata)),
                    _json_dumps(serialize_envelope(job.error_envelope))
                    if job.error_envelope is not None
                    else None,
                    datetime.utcnow().isoformat(),
                    job.job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise JobRepositoryError(f"Unknown job identity {job.job_id!r}")

    def update_queue_order(self, ordered_job_ids: Sequence[str]) -> None:
        with self.transaction() as connection:
            stored = {
                row["job_id"]
                for row in connection.execute("SELECT job_id FROM jobs WHERE status = 'queued'")
            }
            requested = set(ordered_job_ids)
            if requested != stored or len(requested) != len(ordered_job_ids):
                raise JobRepositoryError("Queue order update must contain every queued identity exactly once")
            for position, job_id in enumerate(ordered_job_ids, start=1):
                connection.execute(
                    "UPDATE jobs SET queue_order = ?, updated_at = ? WHERE job_id = ?",
                    (position, datetime.utcnow().isoformat(), job_id),
                )

    def recover_interrupted_jobs(self) -> int:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT job_id, execution_metadata FROM jobs WHERE status = 'running'"
            ).fetchall()
            now = datetime.utcnow().isoformat()
            for row in rows:
                metadata = _execution_metadata_from_dict(_json_loads(row["execution_metadata"], {}))
                metadata.last_control_action = "restart_requeue"
                metadata.return_to_queue_count += 1
                connection.execute(
                    """
                    UPDATE jobs SET status = 'queued', started_at = NULL, completed_at = NULL,
                        updated_at = ?, execution_metadata = ?, error_message = NULL,
                        result_json = NULL, artifact_references = '[]'
                    WHERE job_id = ?
                    """,
                    (now, _json_dumps(_execution_metadata_to_dict(metadata)), row["job_id"]),
                )
            return len(rows)

    def load_runnable_jobs(self, *, recover_interrupted: bool = True) -> list[Job]:
        if recover_interrupted:
            self.recover_interrupted_jobs()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM jobs WHERE status = 'queued'
                ORDER BY priority DESC, queue_order ASC
                """
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def get_job_model(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row is not None else None

    def list_job_models(self, statuses: Iterable[JobStatus] | None = None) -> list[Job]:
        values = tuple(status.value for status in statuses or ())
        sql = "SELECT * FROM jobs"
        parameters: tuple[Any, ...] = ()
        if values:
            sql += f" WHERE status IN ({','.join('?' for _ in values)})"
            parameters = values
        sql += " ORDER BY queue_order ASC"
        with self._lock:
            rows = self._connection.execute(sql, parameters).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 50, offset: int = 0
    ) -> list[JobHistoryEntry]:
        parameters: list[Any] = []
        sql = "SELECT * FROM jobs"
        if status is not None:
            sql += " WHERE status = ?"
            parameters.append(status.value)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        parameters.extend([max(0, int(limit)), max(0, int(offset))])
        with self._lock:
            rows = self._connection.execute(sql, tuple(parameters)).fetchall()
        return [self._row_to_history(row) for row in rows]

    def list_recent_jobs(
        self, *, statuses: set[JobStatus] | None = None, limit: int = 50
    ) -> list[JobHistoryEntry]:
        wanted = tuple(status.value for status in statuses or ())
        parameters: list[Any] = []
        sql = "SELECT * FROM jobs"
        if wanted:
            sql += f" WHERE status IN ({','.join('?' for _ in wanted)})"
            parameters.extend(wanted)
        sql += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(max(0, int(limit)))
        with self._lock:
            rows = self._connection.execute(sql, tuple(parameters)).fetchall()
        return [self._row_to_history(row) for row in rows]

    def get_job(self, job_id: str) -> JobHistoryEntry | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_history(row) if row is not None else None

    def record_status_change(
        self,
        job_id: str,
        status: JobStatus,
        ts: datetime,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        job = self.get_job_model(job_id)
        if job is None:
            raise JobRepositoryError(f"Unknown job identity {job_id!r}")
        if status == JobStatus.RUNNING:
            job.started_at = ts
        if status in _TERMINAL_STATUSES:
            job.completed_at = ts
        self.transition_job(job, status, error_message=error, result=result)

    def save_entry(self, entry: JobHistoryEntry) -> None:
        job = self.get_job_model(entry.job_id)
        if job is None:
            raise JobRepositoryError("History is a projection; submit the NJR before recording history")
        job.started_at = entry.started_at
        job.completed_at = entry.completed_at
        self.transition_job(job, entry.status, error_message=entry.error_message, result=entry.result)

    def register_callback(self, callback: Any) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM repository_metadata WHERE key = ?", (key,)
            ).fetchone()
        return _json_loads(row["value"], default) if row is not None else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO repository_metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, _json_dumps(value)),
            )

    def count(self, statuses: Iterable[JobStatus] | None = None) -> int:
        values = tuple(status.value for status in statuses or ())
        sql = "SELECT COUNT(*) AS count FROM jobs"
        parameters: tuple[Any, ...] = ()
        if values:
            sql += f" WHERE status IN ({','.join('?' for _ in values)})"
            parameters = values
        with self._lock:
            return int(self._connection.execute(sql, parameters).fetchone()["count"])

    def identities(self) -> set[str]:
        with self._lock:
            rows = self._connection.execute("SELECT job_id FROM jobs").fetchall()
        return {str(row["job_id"]) for row in rows}

    def get_artifact_references(self, job_id: str) -> list[str]:
        with self._lock:
            row = self._connection.execute(
                "SELECT artifact_references FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return list(_json_loads(row["artifact_references"], [])) if row is not None else []

    def get_lineage(self, job_id: str) -> tuple[str | None, str | None]:
        with self._lock:
            row = self._connection.execute(
                "SELECT parent_job_id, parent_artifact_id FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None, None
        return row["parent_job_id"], row["parent_artifact_id"]

    def import_jobs(
        self,
        jobs: Sequence[tuple[Job, str, str]],
        *,
        expected_total_count: int | None = None,
    ) -> tuple[list[str], list[str]]:
        """Atomically import ``(job, source fingerprint, record fingerprint)`` tuples."""
        imported: list[str] = []
        duplicates: list[str] = []
        with self.transaction() as connection:
            for job, source_fingerprint, record_fingerprint in jobs:
                prior_import = connection.execute(
                    "SELECT record_fingerprint FROM legacy_imports WHERE source_fingerprint = ? AND job_id = ?",
                    (source_fingerprint, job.job_id),
                ).fetchone()
                if prior_import is not None:
                    if prior_import["record_fingerprint"] != record_fingerprint:
                        raise JobConflictError(f"Changed legacy source record for {job.job_id!r}")
                    duplicates.append(job.job_id)
                    continue
                if connection.execute(
                    "SELECT 1 FROM jobs WHERE job_id = ?", (job.job_id,)
                ).fetchone():
                    raise JobConflictError(f"Canonical job identity already exists: {job.job_id!r}")
                self._insert_imported_job(connection, job)
                connection.execute(
                    "INSERT INTO legacy_imports VALUES (?, ?, ?, ?)",
                    (
                        source_fingerprint,
                        job.job_id,
                        record_fingerprint,
                        datetime.utcnow().isoformat(),
                    ),
                )
                imported.append(job.job_id)
            if expected_total_count is not None:
                actual_count = int(
                    connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"]
                )
                if actual_count != expected_total_count:
                    raise JobRepositoryError(
                        "Atomic import validation failed: "
                        f"expected {expected_total_count} jobs, found {actual_count}"
                    )
            for job, _source_fingerprint, _record_fingerprint in jobs:
                stored = connection.execute(
                    "SELECT status FROM jobs WHERE job_id = ?", (job.job_id,)
                ).fetchone()
                if stored is None or stored["status"] != job.status.value:
                    raise JobRepositoryError(
                        f"Atomic import validation failed for {job.job_id!r}"
                    )
        return imported, duplicates

    def _insert_imported_job(self, connection: sqlite3.Connection, job: Job) -> None:
        snapshot, _record = _canonical_snapshot(job)
        serialized_snapshot = _json_dumps(snapshot)
        fingerprint = hashlib.sha256(serialized_snapshot.encode("utf-8")).hexdigest()
        parent_job_id, parent_artifact_id = _lineage(snapshot)
        next_order = connection.execute(
            "SELECT COALESCE(MAX(queue_order), 0) + 1 AS value FROM jobs"
        ).fetchone()["value"]
        created = _iso(job.created_at) or datetime.utcnow().isoformat()
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, njr_snapshot, njr_fingerprint, priority, queue_order, status,
                created_at, queued_at, started_at, completed_at, updated_at,
                progress, eta_seconds, worker_id, run_mode, source, prompt_source,
                prompt_pack_id, randomizer_metadata, variant_index, variant_total,
                execution_metadata, error_message, error_envelope, result_json,
                artifact_references, parent_job_id, parent_artifact_id, payload_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id, serialized_snapshot, fingerprint, int(job.priority), int(next_order),
                job.status.value, created, created, _iso(job.started_at), _iso(job.completed_at),
                _iso(job.updated_at) or created, float(job.progress), job.eta_seconds,
                str(job.worker_id) if job.worker_id is not None else None, job.run_mode,
                job.source, job.prompt_source, job.prompt_pack_id,
                _json_dumps(job.randomizer_metadata or {}), job.variant_index, job.variant_total,
                _json_dumps(_execution_metadata_to_dict(job.execution_metadata)), job.error_message,
                _json_dumps(serialize_envelope(job.error_envelope)) if job.error_envelope else None,
                _json_dumps(job.result) if job.result is not None else None,
                _json_dumps(_artifact_references(job.result)), parent_job_id, parent_artifact_id,
                job.summary(),
            ),
        )

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

        snapshot = _json_loads(row["njr_snapshot"], {})
        record = normalized_job_from_snapshot(snapshot)
        if record is None:
            raise JobRepositoryError(f"Stored NJR for {row['job_id']!r} cannot be reconstructed")
        job = Job(
            job_id=str(row["job_id"]),
            priority=JobPriority(int(row["priority"])),
            status=JobStatus(row["status"]),
            created_at=_parse_datetime(row["created_at"]) or datetime.utcnow(),
            updated_at=_parse_datetime(row["updated_at"]) or datetime.utcnow(),
            started_at=_parse_datetime(row["started_at"]),
            completed_at=_parse_datetime(row["completed_at"]),
            randomizer_metadata=_json_loads(row["randomizer_metadata"], {}),
            error_message=row["error_message"],
            result=_json_loads(row["result_json"], None),
            worker_id=row["worker_id"],
            run_mode=str(row["run_mode"]),
            source=str(row["source"]),
            prompt_source=str(row["prompt_source"]),
            prompt_pack_id=row["prompt_pack_id"],
            variant_index=row["variant_index"],
            variant_total=row["variant_total"],
            snapshot=snapshot,
            execution_metadata=_execution_metadata_from_dict(
                _json_loads(row["execution_metadata"], {})
            ),
            progress=float(row["progress"] or 0.0),
            eta_seconds=row["eta_seconds"],
        )
        job.error_envelope = deserialize_envelope(_json_loads(row["error_envelope"], None))
        job._normalized_record = record
        return job

    def _row_to_history(self, row: sqlite3.Row) -> JobHistoryEntry:
        started = _parse_datetime(row["started_at"])
        completed = _parse_datetime(row["completed_at"])
        duration_ms = None
        if started is not None and completed is not None:
            duration_ms = int((completed - started).total_seconds() * 1000)
        return JobHistoryEntry(
            job_id=str(row["job_id"]),
            created_at=_parse_datetime(row["created_at"]) or datetime.utcnow(),
            status=JobStatus(row["status"]),
            payload_summary=str(row["payload_summary"]),
            started_at=started,
            completed_at=completed,
            error_message=row["error_message"],
            worker_id=row["worker_id"],
            run_mode=str(row["run_mode"]),
            result=_json_loads(row["result_json"], None),
            prompt_source=str(row["prompt_source"]),
            prompt_pack_id=row["prompt_pack_id"],
            snapshot=_json_loads(row["njr_snapshot"], {}),
            duration_ms=duration_ms,
        )

    def _emit(self, entry: JobHistoryEntry | None) -> None:
        if entry is None:
            return
        for callback in list(self._callbacks):
            try:
                callback(entry)
            except Exception:
                continue


__all__ = [
    "InvalidLifecycleTransition",
    "JobConflictError",
    "JobRepository",
    "JobRepositoryError",
    "REPOSITORY_SCHEMA_VERSION",
]
