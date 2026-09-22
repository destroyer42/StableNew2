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
