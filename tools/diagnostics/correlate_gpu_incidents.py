"""Read-only correlation of Windows incidents with StableNew survivor evidence.

This operational tool intentionally has no access to queue mutation, runtime
ownership, or GPU control.  It turns supplied timestamps and durable local
records into a machine-readable timeline without inferring absent evidence.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone(UTC)


def _safe_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return _parse_timestamp(str(value))
    except ValueError:
        return None


def read_sqlite_jobs(path: Path) -> list[dict[str, Any]]:
    """Read only lifecycle columns needed for correlation, never NJR payloads."""

    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """
            SELECT job_id, status, started_at, completed_at, updated_at, source
            FROM jobs
            """
        ).fetchall()
    return [
        {
            "job_id": str(job_id),
            "status": str(status),
            "started_at": started_at,
            "completed_at": completed_at,
            "updated_at": updated_at,
            "source": source,
        }
        for job_id, status, started_at, completed_at, updated_at, source in rows
    ]


def read_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return records


def _active_jobs(incident: datetime, jobs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for job in jobs:
        started_at = _safe_time(job.get("started_at"))
        completed_at = _safe_time(job.get("completed_at"))
        if started_at is None or started_at > incident:
            continue
        if completed_at is not None and completed_at < incident:
            continue
        active.append(
            {
                "job_id": job.get("job_id"),
                "status": job.get("status"),
                "source": job.get("source"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
            }
        )
    return active


def _telemetry_near(
    incident: datetime,
    records: Iterable[Mapping[str, Any]],
    *,
    window: timedelta,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        timestamp = _safe_time(record.get("timestamp_utc"))
        if timestamp is None or abs(timestamp - incident) > window:
            continue
        selected.append(
            {
                "timestamp_utc": record.get("timestamp_utc"),
                "kind": record.get("kind"),
                "event": record.get("event"),
                "job_id": record.get("job_id"),
                "run_id": record.get("run_id"),
                "backend_id": record.get("backend_id"),
                "stage": record.get("stage"),
            }
        )
    return selected


def correlate(
    incidents: Iterable[Mapping[str, Any]],
    *,
    jobs: Iterable[Mapping[str, Any]] | None,
    telemetry: Iterable[Mapping[str, Any]] | None,
    webui_log_files: Iterable[Path] | None,
    window: timedelta = timedelta(minutes=10),
) -> list[dict[str, Any]]:
    """Classify only what supplied evidence proves; unavailable remains unknown."""

    jobs_list = list(jobs or [])
    telemetry_list = list(telemetry or [])
    webui_files = list(webui_log_files or [])
    sqlite_available = jobs is not None
    telemetry_available = telemetry is not None
    webui_available = webui_log_files is not None
    timeline: list[dict[str, Any]] = []
    for raw_incident in incidents:
        timestamp = _parse_timestamp(str(raw_incident["timestamp_utc"]))
        active_jobs = _active_jobs(timestamp, jobs_list)
        nearby_telemetry = _telemetry_near(timestamp, telemetry_list, window=window)
        telemetry_times = [
            sample_time
            for record in telemetry_list
            if (sample_time := _safe_time(record.get("timestamp_utc"))) is not None
        ]
        telemetry_covers_incident = bool(
            telemetry_times
            and min(telemetry_times) - window <= timestamp <= max(telemetry_times) + window
        )
        nearby_webui = [
            {"path": str(path), "last_write_utc": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()}
            for path in webui_files
            if abs(datetime.fromtimestamp(path.stat().st_mtime, UTC) - timestamp) <= window
        ]
        if active_jobs or nearby_telemetry:
            classification = "proven_active_stablenew_gpu_work"
        elif nearby_webui:
            classification = "stablenew_open_no_proven_active_generation"
        elif sqlite_available and telemetry_covers_incident and webui_available:
            classification = "no_stablenew_evidence"
        else:
            classification = "evidence_unavailable"
        timeline.append(
            {
                "timestamp_utc": timestamp.isoformat(),
                "incident": dict(raw_incident),
                "classification": classification,
                "active_sqlite_jobs": active_jobs,
                "nearby_survivor_telemetry": nearby_telemetry,
                "nearby_webui_log_files": nearby_webui,
                "source_availability": {
                    "sqlite": sqlite_available,
                    "survivor_telemetry": telemetry_available,
                    "survivor_telemetry_covers_incident": telemetry_covers_incident,
                    "webui_log_inventory": webui_available,
                },
            }
        )
    return timeline


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", action="append", required=True, help="UTC ISO-8601 timestamp")
    parser.add_argument("--sqlite", type=Path)
    parser.add_argument("--telemetry-dir", type=Path)
    parser.add_argument("--webui-log-dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    jobs = read_sqlite_jobs(args.sqlite) if args.sqlite and args.sqlite.exists() else None
    telemetry_paths = (
        sorted(args.telemetry_dir.glob("*.jsonl*"))
        if args.telemetry_dir and args.telemetry_dir.exists()
        else None
    )
    telemetry = read_jsonl(telemetry_paths or []) if telemetry_paths is not None else None
    webui_files = (
        list(args.webui_log_dir.glob("*.log"))
        if args.webui_log_dir and args.webui_log_dir.exists()
        else None
    )
    incidents = [{"timestamp_utc": timestamp, "source": "operator_supplied"} for timestamp in args.incident]
    output = {
        "schema": "stablenew.gpu-incident-timeline.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "timeline": correlate(
            incidents,
            jobs=jobs,
            telemetry=telemetry,
            webui_log_files=webui_files,
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
