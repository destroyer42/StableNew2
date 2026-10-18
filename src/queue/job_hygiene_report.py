"""Read-only hygiene report for the job repository: where the space is and what a prune could remove.

It writes nothing and deletes nothing: the database is opened read-only and the module has no delete code. It exists
to put numbers in front of the owner before any decision to externalize snapshots, backfill, or prune.

A job is a *prune candidate* only when every one of these holds: it is terminal (completed, failed or cancelled), it is
older than the age threshold, it has recorded output paths and every one of them is confirmed missing, no other job
was compiled from it (replay lineage), and no Learning file mentions its id. Queued and running jobs, jobs with no
recorded outputs, unresolvable relative paths and paths that could not be checked are never candidates. Not checked:
staged-curation groups and run folders (a candidate list is a starting point for review, not a delete list).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

TERMINAL_STATUSES = ("completed", "failed", "cancelled")
_COLUMNS = (
    "njr_snapshot",
    "result_json",
    "execution_metadata",
    "randomizer_metadata",
    "error_envelope",
    "artifact_references",
    "payload_summary",
)
_JOB_ID_PATTERN = re.compile(r'"job_id"\s*:\s*"([^"]+)"')
_FROZEN_MARKER = '"frozen_experiment"'
_TOP = 10


@dataclass(frozen=True)
class ReportOptions:
    older_than_days: int = 30
    output_root: Path | None = None
    learning_root: Path | None = None
    now: datetime | None = None


def open_read_only(path: str | Path) -> sqlite3.Connection:
    """A connection that cannot write, even by accident."""

    connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _database_section(connection: sqlite3.Connection, path: Path | None) -> dict[str, Any]:
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    pages = int(connection.execute("PRAGMA page_count").fetchone()[0])
    free = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    return {
        "file_bytes": path.stat().st_size
        if path is not None and path.exists()
        else page_size * pages,
        "page_size": page_size,
        "page_count": pages,
        "free_pages": free,
        "reclaimable_by_vacuum_bytes": free * page_size,
    }


def _jobs_section(connection: sqlite3.Connection) -> dict[str, Any]:
    by_status = {
        str(row["status"]): int(row["n"])
        for row in connection.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    }
    return {"total": sum(by_status.values()), "by_status": by_status}


def _column_bytes(connection: sqlite3.Connection) -> dict[str, int]:
    sums = ", ".join(f"COALESCE(SUM(LENGTH({column})), 0) AS {column}" for column in _COLUMNS)
    row = connection.execute(f"SELECT {sums} FROM jobs").fetchone()
    return {column: int(row[column]) for column in _COLUMNS}


def _frozen_snapshots(value: Any) -> Iterator[tuple[str, str, int]]:
    """Every ``frozen_experiment`` block in a parsed NJR as ``(snapshot_sha256, experiment_id, snapshot_bytes)``."""

    if isinstance(value, dict):
        frozen = value.get("frozen_experiment")
        if isinstance(frozen, dict) and frozen.get("snapshot_sha256"):
            snapshot = frozen.get("snapshot") or {}
            size = len(json.dumps(snapshot, sort_keys=True, separators=(",", ":")))
            yield str(frozen["snapshot_sha256"]), str(frozen.get("experiment_id") or ""), size
        for child in value.values():
            yield from _frozen_snapshots(child)
    elif isinstance(value, list):
        for child in value:
            yield from _frozen_snapshots(child)


def _duplicated_snapshots(connection: sqlite3.Connection) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    jobs_with = 0
    for row in connection.execute(
        "SELECT job_id, njr_snapshot FROM jobs WHERE instr(njr_snapshot, ?) > 0", (_FROZEN_MARKER,)
    ):
        try:
            parsed = json.loads(row["njr_snapshot"])
        except (TypeError, ValueError):
            continue
        found = list(_frozen_snapshots(parsed))
        if not found:
            continue
        jobs_with += 1
        for digest, experiment_id, size in found:
            group = groups.setdefault(
                digest,
                {
                    "experiment_id": experiment_id,
                    "snapshot_bytes": size,
                    "jobs": set(),
                    "copies": 0,
                },
            )
            group["jobs"].add(str(row["job_id"]))
            group["copies"] += 1
    copies = sum(group["copies"] for group in groups.values())
    all_bytes = sum(group["copies"] * group["snapshot_bytes"] for group in groups.values())
    once_bytes = sum(group["snapshot_bytes"] for group in groups.values())
    top = sorted(
        groups.items(), key=lambda item: item[1]["copies"] * item[1]["snapshot_bytes"], reverse=True
    )[:_TOP]
    return {
        "jobs_with_frozen_snapshot": jobs_with,
        "distinct_snapshots": len(groups),
        "copies": copies,
        "bytes_all_copies": all_bytes,
        "bytes_if_stored_once": once_bytes,
        "estimated_saving_bytes": all_bytes - once_bytes,
        "largest": [
            {
                "snapshot_sha256": digest[:12],
                "experiment_id": group["experiment_id"],
                "jobs": len(group["jobs"]),
                "copies": group["copies"],
                "snapshot_bytes": group["snapshot_bytes"],
                "bytes_all_copies": group["copies"] * group["snapshot_bytes"],
            }
            for digest, group in top
        ],
    }


def _learning_job_ids(root: Path | None) -> set[str]:
    """Job ids that any Learning record or saved session mentions (a textual scan; no schema assumptions)."""

    ids: set[str] = set()
    if root is None or not root.exists():
        return ids
    files = [root / "learning_records.jsonl", *sorted(root.glob("experiments/*/session.json"))]
    for file in files:
        if not file.is_file():
            continue
        with file.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                ids.update(_JOB_ID_PATTERN.findall(line))
    return ids


def _classify_paths(references: list[str], output_root: Path | None) -> str:
    """``no_outputs``, ``unresolvable``, ``unchecked``, ``all_present``, ``partly_missing`` or ``all_missing``."""

    if not references:
        return "no_outputs"
    present = missing = 0
    for reference in references:
        path = Path(reference)
        if not path.is_absolute():
            if output_root is None:
                return "unresolvable"
            path = output_root / path
        try:
            exists = path.exists()
        except (OSError, ValueError):
            return "unchecked"
        present += exists
        missing += not exists
    if missing == 0:
        return "all_present"
    return "all_missing" if present == 0 else "partly_missing"


def _prune_section(connection: sqlite3.Connection, options: ReportOptions) -> dict[str, Any]:
    now = options.now or datetime.now()
    cutoff = (now - timedelta(days=options.older_than_days)).isoformat()
    parents = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT parent_job_id FROM jobs WHERE parent_job_id IS NOT NULL"
        )
    }
    learning_ids = _learning_job_ids(options.learning_root)
    marks = ",".join("?" for _ in TERMINAL_STATUSES)
    counts: Counter[str] = Counter()
    bytes_by_class: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    considered = 0
    for row in connection.execute(
        f"SELECT job_id, status, created_at, artifact_references, "
        f"LENGTH(njr_snapshot) + COALESCE(LENGTH(result_json), 0) + LENGTH(execution_metadata) AS size "
        f"FROM jobs WHERE status IN ({marks}) AND created_at < ?",
        (*TERMINAL_STATUSES, cutoff),
    ):
        considered += 1
        job_id = str(row["job_id"])
        try:
            references = [str(item) for item in json.loads(row["artifact_references"] or "[]")]
        except (TypeError, ValueError):
            references = []
        outcome = _classify_paths(references, options.output_root)
        size = int(row["size"] or 0)
        if outcome == "all_missing":
            if job_id in parents:
                outcome = "protected_has_replay_children"
            elif job_id in learning_ids:
                outcome = "protected_in_learning_files"
            else:
                outcome = "candidate"
        counts[outcome] += 1
        bytes_by_class[outcome] += size
        if outcome == "candidate":
            candidate_ids.append(job_id)
            candidates.append(
                {
                    "job_id": job_id,
                    "status": str(row["status"]),
                    "created_at": str(row["created_at"]),
                    "bytes": size,
                }
            )
    candidates.sort(key=lambda item: item["bytes"], reverse=True)
    created = sorted(item["created_at"] for item in candidates)
    return {
        "criteria": {
            "older_than_days": options.older_than_days,
            "cutoff": cutoff,
            "output_root": str(options.output_root) if options.output_root else None,
            "learning_root": str(options.learning_root) if options.learning_root else None,
            "relative_paths_resolvable": options.output_root is not None,
        },
        "terminal_jobs_older_than_cutoff": considered,
        "classes": {
            name: {"jobs": counts[name], "bytes": bytes_by_class[name]} for name in sorted(counts)
        },
        "candidates": {
            "jobs": len(candidates),
            "bytes": sum(item["bytes"] for item in candidates),
            "oldest": created[0] if created else None,
            "newest": created[-1] if created else None,
            "largest": candidates[:_TOP],
        },
        "candidate_job_ids": candidate_ids,
    }


def build_report(
    connection: sqlite3.Connection,
    options: ReportOptions | None = None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    options = options or ReportOptions()
    return {
        "database": _database_section(connection, path),
        "jobs": _jobs_section(connection),
        "column_bytes": _column_bytes(connection),
        "duplicated_snapshots": _duplicated_snapshots(connection),
        "prune": _prune_section(connection, options),
    }


def _mb(value: int | float) -> str:
    return f"{value / 1_000_000:,.1f} MB"


def format_report(report: dict[str, Any]) -> str:
    db, jobs, columns = report["database"], report["jobs"], report["column_bytes"]
    dup, prune = report["duplicated_snapshots"], report["prune"]
    lines = [
        "Job repository hygiene report (read-only; nothing was changed)",
        "",
        f"Database: {_mb(db['file_bytes'])}; {_mb(db['reclaimable_by_vacuum_bytes'])} free inside it (VACUUM would reclaim that)",
        f"Jobs: {jobs['total']:,} ("
        + ", ".join(f"{name} {count:,}" for name, count in sorted(jobs["by_status"].items()))
        + ")",
        "",
        "Bytes by column:",
        *(
            f"  {name:<20} {_mb(size):>12}"
            for name, size in sorted(columns.items(), key=lambda kv: -kv[1])
        ),
        "",
        "Duplicated Learning snapshots (what externalizing by hash would save):",
        f"  jobs carrying a frozen snapshot: {dup['jobs_with_frozen_snapshot']:,}; distinct snapshots: {dup['distinct_snapshots']:,}; copies stored: {dup['copies']:,}",
        f"  stored today {_mb(dup['bytes_all_copies'])}; stored once {_mb(dup['bytes_if_stored_once'])}; estimated saving {_mb(dup['estimated_saving_bytes'])}",
    ]
    for item in dup["largest"][:5]:
        lines.append(
            f"    {item['snapshot_sha256']}  {item['jobs']:,} jobs x {item['copies'] // max(1, item['jobs'])} copies  "
            f"{_mb(item['bytes_all_copies'])}  ({item['experiment_id']})"
        )
    criteria = prune["criteria"]
    lines += [
        "",
        f"Prune dry run: terminal jobs older than {criteria['older_than_days']} days: {prune['terminal_jobs_older_than_cutoff']:,}",
    ]
    if not criteria["relative_paths_resolvable"]:
        lines.append(
            "  (no --output-root given: jobs with relative output paths are 'unresolvable' and never candidates)"
        )
    for name, info in prune["classes"].items():
        lines.append(f"  {name:<32} {info['jobs']:>8,} jobs  {_mb(info['bytes']):>12}")
    cand = prune["candidates"]
    lines.append(
        f"  => candidates: {cand['jobs']:,} jobs, {_mb(cand['bytes'])} of snapshot/result/metadata text"
    )
    if cand["jobs"]:
        lines.append(f"     created between {cand['oldest']} and {cand['newest']}")
    lines += [
        "",
        "Not checked: staged-curation groups and run folders. Nothing here deletes anything;",
        "use --candidates-csv to keep the list for the delete decision.",
    ]
    return "\n".join(lines)


def candidates_csv(report: dict[str, Any]) -> str:
    return "job_id\n" + "\n".join(report["prune"]["candidate_job_ids"]) + "\n"


__all__ = [
    "ReportOptions",
    "build_report",
    "candidates_csv",
    "format_report",
    "open_read_only",
]
