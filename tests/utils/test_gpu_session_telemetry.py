from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.utils import gpu_survivor_telemetry as module
from src.utils.gpu_survivor_telemetry import GpuSurvivorTelemetry
from src.utils.process_inspector_v2 import GpuQueryResult
from src.utils.thread_registry import get_thread_registry


def _snapshot() -> dict[str, object]:
    return {
        "provider": "nvidia-smi",
        "devices": [{"index": 0, "utilization_gpu_pct": 91.0, "memory_used_mb": 8192.0}],
        "host_available_memory_mb": 12288.0,
    }


def _read_records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_default_gpu_query_records_why_a_snapshot_is_missing(tmp_path, monkeypatch) -> None:
    results = iter(
        [
            GpuQueryResult(_snapshot(), "ok"),
            GpuQueryResult(
                None, "gpu_lost", "Unable to determine the device handle for GPU0: GPU is lost."
            ),
        ]
    )
    monkeypatch.setattr(module, "query_gpu_survivor_snapshot", lambda: next(results))
    recorder = GpuSurvivorTelemetry(
        job_id="job-q",
        run_id="run-q",
        workflow=["txt2img"],
        backend_id="forge_webui",
        output_dir=tmp_path,
        presence_provider=lambda: None,
    )

    recorder.record_event("generation_dispatched")
    recorder.record_event("publication_boundary")

    first, second = _read_records(recorder.path)
    assert first["gpu"] == _snapshot() and first["gpu_query"] == {"status": "ok"}
    assert second["gpu"] is None
    assert second["gpu_query"]["status"] == "gpu_lost"  # type: ignore[index]
    assert "GPU is lost" in second["gpu_query"]["detail"]  # type: ignore[index]


def test_injected_snapshot_provider_records_no_query_status(tmp_path) -> None:
    recorder = GpuSurvivorTelemetry(
        job_id="job-i",
        run_id="run-i",
        workflow=["txt2img"],
        backend_id="forge_webui",
        output_dir=tmp_path,
        snapshot_provider=_snapshot,
        presence_provider=lambda: None,
    )

    recorder.record_event("generation_dispatched")

    assert "gpu_query" not in _read_records(recorder.path)[0]


def test_job_recorders_sample_faster_than_one_second_by_default() -> None:
    assert module.JOB_SAMPLE_INTERVAL_S <= 0.5


def test_session_lifecycle_uses_session_event_names(tmp_path) -> None:
    recorder = GpuSurvivorTelemetry(
        job_id="session-1",
        run_id="session-run",
        workflow=[],
        backend_id=None,
        output_dir=tmp_path,
        interval_s=60,
        snapshot_provider=_snapshot,
        presence_provider=lambda: None,
        lifecycle="session",
    )

    recorder.start()
    recorder.close(outcome="app_exit")

    records = _read_records(recorder.path)
    assert [record.get("event") for record in records] == ["session_started", "session_finished"]
    assert records[-1]["outcome"] == "app_exit"


def test_sample_loop_leaves_promptly_when_the_thread_registry_requests_shutdown(tmp_path) -> None:
    recorder = GpuSurvivorTelemetry(
        job_id="job-s",
        run_id="run-s",
        workflow=["txt2img"],
        backend_id=None,
        output_dir=tmp_path,
        interval_s=0.2,
        snapshot_provider=_snapshot,
        presence_provider=lambda: None,
    )
    recorder.start()
    thread = recorder._thread
    assert thread is not None
    try:
        get_thread_registry()._shutdown_requested = True
        thread.join(timeout=3.0)
        assert not thread.is_alive()
    finally:
        get_thread_registry()._shutdown_requested = False
        recorder.close(outcome="completed")


class _StubRecorder:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = 0
        self.closed: list[str] = []

    def start(self) -> None:
        self.started += 1

    def close(self, *, outcome: str) -> None:
        self.closed.append(outcome)


def test_session_telemetry_starts_once_with_slow_separate_settings_and_stops_idempotently(
    tmp_path,
) -> None:
    created: list[_StubRecorder] = []

    def _factory(**kwargs) -> _StubRecorder:
        recorder = _StubRecorder(**kwargs)
        created.append(recorder)
        return recorder

    try:
        first = module.start_gpu_session_telemetry(base_dir=tmp_path, environ={}, factory=_factory)
        second = module.start_gpu_session_telemetry(base_dir=tmp_path, environ={}, factory=_factory)
        assert first is second and len(created) == 1 and first.started == 1  # type: ignore[union-attr]
        kwargs = created[0].kwargs
        assert kwargs["output_dir"] == tmp_path / "session"
        assert kwargs["interval_s"] == module.SESSION_SAMPLE_INTERVAL_S
        assert kwargs["lifecycle"] == "session"
        assert kwargs["workflow"] == [] and str(kwargs["job_id"]).startswith("session-")

        module.stop_gpu_session_telemetry("app_exit")
        module.stop_gpu_session_telemetry("app_exit")
        assert created[0].closed == ["app_exit"]
    finally:
        module.stop_gpu_session_telemetry("test_cleanup")


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_session_telemetry_can_be_disabled_by_environment(tmp_path, value) -> None:
    created: list[_StubRecorder] = []

    def _factory(**kwargs) -> _StubRecorder:
        created.append(_StubRecorder(**kwargs))
        return created[-1]

    result = module.start_gpu_session_telemetry(
        base_dir=tmp_path, environ={module.SESSION_ENV_FLAG: value}, factory=_factory
    )

    assert result is None and created == []


def test_session_telemetry_start_failure_is_contained(tmp_path) -> None:
    def _broken(**_kwargs):
        raise RuntimeError("cannot create recorder")

    try:
        assert (
            module.start_gpu_session_telemetry(base_dir=tmp_path, environ={}, factory=_broken)
            is None
        )
    finally:
        module.stop_gpu_session_telemetry("test_cleanup")
