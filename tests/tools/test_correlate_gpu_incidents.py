from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_tool():
    path = Path("tools/diagnostics/correlate_gpu_incidents.py")
    spec = importlib.util.spec_from_file_location("correlate_gpu_incidents", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_correlation_marks_missing_sources_as_explicitly_unavailable() -> None:
    tool = _load_tool()

    result = tool.correlate(
        [{"timestamp_utc": "2026-09-16T06:20:25Z", "source": "kernel_power"}],
        jobs=None,
        telemetry=None,
        webui_log_files=None,
    )

    assert result[0]["classification"] == "evidence_unavailable"
    assert result[0]["active_sqlite_jobs"] == []


def test_correlation_uses_read_only_sqlite_lifecycle_and_survivor_records(tmp_path) -> None:
    tool = _load_tool()
    database = tmp_path / "jobs.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE jobs (job_id TEXT, status TEXT, started_at TEXT, completed_at TEXT, updated_at TEXT, source TEXT)"
    )
    connection.execute(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
        ("job-1", "running", "2026-09-16T06:20:00+00:00", None, "2026-09-16T06:20:00+00:00", "queue"),
    )
    connection.commit()
    connection.close()
    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir()
    (telemetry_dir / "survivor.jsonl").write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-09-16T06:20:24+00:00",
                "kind": "sample",
                "job_id": "job-1",
                "run_id": "run-1",
                "backend_id": "a1111_webui",
                "stage": "txt2img",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = tool.correlate(
        [{"timestamp_utc": "2026-09-16T06:20:25Z", "source": "kernel_power"}],
        jobs=tool.read_sqlite_jobs(database),
        telemetry=tool.read_jsonl(list(telemetry_dir.glob("*.jsonl"))),
        webui_log_files=[],
    )

    assert result[0]["classification"] == "proven_active_stablenew_gpu_work"
    assert result[0]["active_sqlite_jobs"][0]["job_id"] == "job-1"
    assert result[0]["nearby_survivor_telemetry"][0]["stage"] == "txt2img"


def test_correlation_distinguishes_nearby_terminal_jobs_from_active_jobs() -> None:
    tool = _load_tool()
    incident = "2026-09-16T06:20:25Z"
    result = tool.correlate(
        [{"timestamp_utc": incident}],
        jobs=[
            {
                "job_id": "completed-before",
                "status": "completed",
                "started_at": "2026-09-16T06:18:00Z",
                "completed_at": "2026-09-16T06:19:55Z",
                "updated_at": "2026-09-16T06:19:55Z",
                "source": "queue",
            },
            {
                "job_id": "failed-before",
                "status": "failed",
                "started_at": "2026-09-16T06:17:00Z",
                "completed_at": "2026-09-16T06:19:00Z",
                "updated_at": "2026-09-16T06:19:00Z",
                "source": "queue",
            },
            {
                "job_id": "outside-window",
                "status": "completed",
                "started_at": "2026-09-16T05:00:00Z",
                "completed_at": "2026-09-16T05:01:00Z",
                "updated_at": "2026-09-16T05:01:00Z",
                "source": "queue",
            },
        ],
        telemetry=[],
        webui_log_files=[],
    )

    nearby = {job["job_id"]: job for job in result[0]["nearby_sqlite_jobs"]}
    assert result[0]["active_sqlite_jobs"] == []
    assert result[0]["classification"] == "nearby_stablenew_lifecycle_no_proven_active_generation"
    assert nearby["completed-before"]["relation"] == "completed_before_incident"
    assert nearby["failed-before"]["relation"] == "failed_before_incident"
    assert nearby["completed-before"]["delta_seconds"] < 0
    assert "outside-window" not in nearby


def test_correlation_normalizes_naive_local_and_aware_timestamps() -> None:
    tool = _load_tool()
    result = tool.correlate(
        [{"timestamp_utc": "2026-09-16T06:20:25Z"}],
        jobs=[
            {
                "job_id": "active-aware",
                "status": "running",
                "started_at": "2026-09-16T02:20:00-04:00",
                "completed_at": None,
                "updated_at": "2026-09-16T06:20:00+00:00",
                "source": "queue",
            }
        ],
        telemetry=None,
        webui_log_files=None,
    )
    assert result[0]["active_sqlite_jobs"][0]["job_id"] == "active-aware"
    assert result[0]["nearby_sqlite_jobs"][0]["relation"] == "active_at_incident"
