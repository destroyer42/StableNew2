"""Read-only observers of production state (SQLite, manifests, Learning records).

These helpers never initiate work; they read what the production stack wrote,
plus one call-through submission counter installed on the existing JobService.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def read_job_rows(repository_path: Path, base: Path | None = None) -> list[dict[str, Any]]:
    """Summarize every job row through a read-only SQLite connection.

    Relative artifact references are resolved against ``base`` (the journey's
    workspace, which is also its working directory while it runs).
    """

    if not repository_path.exists():
        return []
    uri = f"file:{repository_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM jobs ORDER BY variant_index, created_at"
        ).fetchall()
    finally:
        connection.close()
    summary: list[dict[str, Any]] = []
    for row in rows:
        snapshot = json.loads(row["njr_snapshot"] or "{}")
        njr = snapshot.get("normalized_job") or {}
        workload = njr.get("workload") or {}
        provenance = njr.get("provenance") or {}
        execution = json.loads(row["execution_metadata"] or "{}")
        summary.append(
            {
                "job_id": row["job_id"],
                "status": row["status"],
                "source": row["source"],
                "variant_index": row["variant_index"],
                "variant_total": row["variant_total"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "error_message": row["error_message"],
                "retry_attempts": len(execution.get("retry_attempts") or []),
                "return_to_queue_count": execution.get("return_to_queue_count", 0),
                "artifact_references": [
                    str((base / ref) if base and not Path(ref).is_absolute() else Path(ref))
                    for ref in json.loads(row["artifact_references"] or "[]")
                ],
                "njr_positive_prompt": workload.get("positive_prompt", ""),
                "njr_seed": provenance.get("seed"),
                "njr_lora_tags": provenance.get("lora_tags") or [],
                "learning_context": provenance.get("learning_context") or {},
            }
        )
    return summary


def job_lifecycle_settled(rows: list[dict[str, Any]], expected: int) -> bool:
    return len(rows) == expected and all(r["status"] in TERMINAL_STATUSES for r in rows)


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_artifacts(rows: list[dict[str, Any]]) -> tuple[list[Path], list[Path]]:
    """Split each job's artifact references into image and manifest paths."""

    images: list[Path] = []
    manifests: list[Path] = []
    for row in rows:
        for ref in row["artifact_references"]:
            path = Path(ref)
            (manifests if path.suffix.lower() == ".json" else images).append(path)
    return images, manifests


def read_rating_records(records_path: Path) -> list[dict[str, Any]]:
    if not records_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if (record.get("metadata") or {}).get("record_kind") == "learning_experiment_rating":
            records.append(record)
    return records


class SubmissionObserver:
    """Count calls to ``JobService.submit_njrs`` without changing behavior."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._service: Any = None
        self._original: Callable[..., Any] | None = None

    def install(self, job_service: Any) -> None:
        self._service = job_service
        self._original = job_service.submit_njrs

        def counted(records: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls.append([str(getattr(r, "job_id", "")) for r in list(records)])
            assert self._original is not None
            return self._original(records, *args, **kwargs)

        job_service.submit_njrs = counted

    def uninstall(self) -> None:
        if self._service is not None:
            self._service.__dict__.pop("submit_njrs", None)
        self._service = None
        self._original = None
