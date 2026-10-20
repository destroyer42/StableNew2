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


# --- app-session telemetry is observation of the app, not proof of generation ----------------------

_INCIDENT = "2026-10-17T16:49:25Z"


def _session_sample(**overrides):
    record = {
        "timestamp_utc": "2026-10-17T16:49:20+00:00",
        "kind": "sample",
        "scope": "session",
        "job_id": "session-4242",
        "run_id": "session-20261017T160000Z",
        "backend_id": None,
        "stage": None,
    }
    record.update(overrides)
    return record


def test_idle_session_sample_without_a_job_is_not_proof_of_active_generation() -> None:
    tool = _load_tool()

    result = tool.correlate(
        [{"timestamp_utc": _INCIDENT}],
        jobs=[],
        telemetry=[_session_sample()],
        webui_log_files=[],
    )

    assert result[0]["classification"] == "stablenew_open_no_proven_active_generation"
    assert result[0]["active_sqlite_jobs"] == []
    assert [item["scope"] for item in result[0]["nearby_survivor_telemetry"]] == ["session"]
    assert result[0]["source_availability"]["survivor_telemetry_covers_incident"] is True


def test_session_marker_is_recognized_from_the_job_id_when_a_record_has_no_scope() -> None:
    tool = _load_tool()
    record = _session_sample()
    del record["scope"]

    result = tool.correlate([{"timestamp_utc": _INCIDENT}], jobs=[], telemetry=[record], webui_log_files=[])

    assert result[0]["classification"] == "stablenew_open_no_proven_active_generation"
    assert result[0]["nearby_survivor_telemetry"][0]["scope"] == "session"


def test_job_scoped_telemetry_still_proves_active_work_beside_session_samples() -> None:
    tool = _load_tool()
    job_record = {
        "timestamp_utc": "2026-10-17T16:49:20+00:00",
        "kind": "sample",
        "scope": "job",
        "job_id": "81f4fdc58e1c43f199e42d30b3183e84",
        "stage": "txt2img",
    }

    result = tool.correlate(
        [{"timestamp_utc": _INCIDENT}],
        jobs=[],
        telemetry=[_session_sample(), job_record],
        webui_log_files=[],
    )

    assert result[0]["classification"] == "proven_active_stablenew_gpu_work"
    assert sorted(item["scope"] for item in result[0]["nearby_survivor_telemetry"]) == ["job", "session"]


def test_records_from_before_the_scope_field_are_job_telemetry() -> None:
    tool = _load_tool()
    legacy = {
        "timestamp_utc": "2026-10-17T16:49:20+00:00",
        "kind": "sample",
        "job_id": "81f4fdc58e1c43f199e42d30b3183e84",
        "stage": "txt2img",
    }

    result = tool.correlate([{"timestamp_utc": _INCIDENT}], jobs=[], telemetry=[legacy], webui_log_files=[])

    assert result[0]["classification"] == "proven_active_stablenew_gpu_work"
    assert result[0]["nearby_survivor_telemetry"][0]["scope"] == "job"


def test_an_active_sqlite_job_still_proves_active_work_beside_a_session_sample() -> None:
    tool = _load_tool()
    running = {
        "job_id": "job-running",
        "status": "running",
        "started_at": "2026-10-17T16:49:00Z",
        "completed_at": None,
        "updated_at": "2026-10-17T16:49:00Z",
        "source": "queue",
    }

    result = tool.correlate(
        [{"timestamp_utc": _INCIDENT}], jobs=[running], telemetry=[_session_sample()], webui_log_files=[]
    )

    assert result[0]["classification"] == "proven_active_stablenew_gpu_work"


def test_command_line_reads_session_telemetry_from_a_subdirectory(tmp_path, monkeypatch) -> None:
    import sys

    tool = _load_tool()
    telemetry_dir = tmp_path / "gpu_survivor"
    (telemetry_dir / "session").mkdir(parents=True)
    (telemetry_dir / "session" / "survivor.jsonl").write_text(
        json.dumps(_session_sample()) + "\n", encoding="utf-8"
    )
    out = tmp_path / "timeline.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "correlate_gpu_incidents.py",
            "--incident",
            _INCIDENT,
            "--telemetry-dir",
            str(telemetry_dir),
            "--out",
            str(out),
        ],
    )

    assert tool.main() == 0

    timeline = json.loads(out.read_text(encoding="utf-8"))["timeline"]
    assert timeline[0]["classification"] == "stablenew_open_no_proven_active_generation"
    assert timeline[0]["nearby_survivor_telemetry"][0]["scope"] == "session"


def test_naive_repository_timestamps_are_utc_not_local_time(monkeypatch) -> None:
    """The job repository writes naive ``datetime.utcnow()`` values; reading them as local
    time shifted the job by the machine's UTC offset and hid it (2026-10-20 incident)."""

    from datetime import datetime, timedelta, timezone

    tool = _load_tool()

    class _EasternLocalTime(datetime):
        """A machine at UTC-4, so the test also fails the old behaviour on a UTC CI runner."""

        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime(2026, 10, 20, 18, 57, tzinfo=timezone(timedelta(hours=-4)))

    monkeypatch.setattr(tool, "datetime", _EasternLocalTime)
    result = tool.correlate(
        [{"timestamp_utc": "2026-10-20T22:57:28Z"}],
        jobs=[
            {
                "job_id": "forge-txt2img",
                "status": "failed",
                "started_at": "2026-10-20T22:57:10.794010",
                "completed_at": "2026-10-20T22:57:28.567300",
                "updated_at": "2026-10-20T22:57:28.567300",
                "source": "queue",
            }
        ],
        telemetry=None,
        webui_log_files=None,
    )
    assert [job["job_id"] for job in result[0]["active_sqlite_jobs"]] == ["forge-txt2img"]
