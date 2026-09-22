from __future__ import annotations

import json
from pathlib import Path

from src.utils.gpu_survivor_telemetry import SCHEMA, GpuSurvivorTelemetry


def _snapshot() -> dict[str, object]:
    return {
        "provider": "nvidia-smi",
        "devices": [{"index": 0, "utilization_gpu_pct": 91.0, "memory_used_mb": 8192.0}],
        "host_available_memory_mb": 12288.0,
    }


def _read_records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_survivor_telemetry_records_canonical_job_and_stage_events(tmp_path) -> None:
    recorder = GpuSurvivorTelemetry(
        job_id="job-123",
        run_id="run-456",
        workflow=["txt2img", "upscale"],
        backend_id="a1111_webui",
        output_dir=tmp_path,
        interval_s=60,
        snapshot_provider=_snapshot,
        presence_provider=lambda: {"status": "normal", "webui_process_count": 1},
    )

    recorder.start()
    recorder.enter_stage("txt2img")
    recorder.leave_stage("txt2img")
    recorder.close(outcome="completed")

    records = _read_records(recorder.path)
    assert [record["kind"] for record in records] == [
        "job_event",
        "job_event",
        "job_event",
        "job_event",
    ]
    assert [record.get("event") for record in records] == [
        "job_started",
        "stage_started",
        "stage_finished",
        "job_finished",
    ]
    for record in records:
        assert record["schema"] == SCHEMA
        assert record["job_id"] == "job-123"
        assert record["run_id"] == "run-456"
        assert record["backend_id"] == "a1111_webui"
        assert record["workflow"] == ["txt2img", "upscale"]
        assert "timestamp_utc" in record
        assert "monotonic_ns" in record
        assert record["gpu"] == _snapshot()


def test_survivor_telemetry_flushes_a_record_without_clean_close(tmp_path) -> None:
    recorder = GpuSurvivorTelemetry(
        job_id="abrupt-job",
        run_id="abrupt-run",
        workflow=["txt2img"],
        backend_id="a1111_webui",
        output_dir=tmp_path,
        snapshot_provider=_snapshot,
        presence_provider=lambda: None,
    )

    recorder.enter_stage("txt2img")

    records = _read_records(recorder.path)
    assert records[-1]["event"] == "stage_started"
    assert records[-1]["stage"] == "txt2img"


def test_survivor_telemetry_records_resolved_video_identity_and_boundaries(tmp_path) -> None:
    recorder = GpuSurvivorTelemetry(
        job_id="video-job",
        run_id="video-run",
        workflow=["video_workflow"],
        backend_id="a1111_webui",
        output_dir=tmp_path,
        interval_s=60,
        snapshot_provider=_snapshot,
        presence_provider=lambda: None,
    )

    recorder.start()
    recorder.enter_stage("video_workflow")
    recorder.update_execution_context(
        backend_id="comfy",
        workflow_id="wan22_ti2v_5b_i2v_v1",
        workflow_version="1.0.0",
    )
    recorder.record_event("generation_dispatched")
    recorder.record_event("publication_boundary")
    recorder.close(outcome="completed")

    records = _read_records(recorder.path)
    assert [record.get("event") for record in records] == [
        "job_started",
        "stage_started",
        "backend_resolved",
        "generation_dispatched",
        "publication_boundary",
        "job_finished",
    ]
    for record in records[2:]:
        assert record["backend_id"] == "comfy"
        assert record["workflow_id"] == "wan22_ti2v_5b_i2v_v1"
        assert record["workflow_version"] == "1.0.0"


def test_survivor_telemetry_is_best_effort_when_snapshot_or_output_fails(tmp_path) -> None:
    def _broken_snapshot() -> None:
        raise RuntimeError("nvidia-smi unavailable")

    blocked_path = tmp_path / "not-a-directory"
    blocked_path.write_text("file", encoding="utf-8")
    recorder = GpuSurvivorTelemetry(
        job_id="failure-job",
        run_id="failure-run",
        workflow=["txt2img"],
        backend_id=None,
        output_dir=blocked_path / "child",
        snapshot_provider=_broken_snapshot,
        presence_provider=_broken_snapshot,
    )

    recorder.start()
    recorder.enter_stage("txt2img")
    recorder.close(outcome="failed")


def test_survivor_telemetry_rotates_without_discarding_the_previous_segment(tmp_path) -> None:
    recorder = GpuSurvivorTelemetry(
        job_id="rotation-job",
        run_id="rotation-run",
        workflow=["txt2img"],
        backend_id=None,
        output_dir=tmp_path,
        max_bytes=1024,
        backup_count=2,
        snapshot_provider=lambda: {"devices": [{"padding": "x" * 750}]},
        presence_provider=lambda: None,
    )

    for index in range(4):
        recorder.enter_stage(f"stage-{index}")

    assert recorder.path.exists()
    assert recorder.path.with_suffix(".jsonl.1").exists()
    assert _read_records(recorder.path.with_suffix(".jsonl.1"))


def test_survivor_telemetry_has_no_queue_or_runtime_lifecycle_authority() -> None:
    source = Path("src/utils/gpu_survivor_telemetry.py").read_text(encoding="utf-8")

    assert "src.queue" not in source
    assert "webui_process_manager" not in source
    assert "comfy_process_manager" not in source
    assert "free_vram" not in source
    assert "cancel_token" not in source
