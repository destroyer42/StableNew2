"""Tests covering AppController diagnostics helpers."""

from __future__ import annotations

from pathlib import Path

from src.controller.app_controller import AppController
from src.utils.error_envelope_v2 import wrap_exception
from src.utils.exceptions_v2 import WatchdogViolationError


class DummyPipelineRunner:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class DummyHistoryStore:
    def list_jobs(self, limit: int | None = None) -> list[object]:
        return []


class DummyJobService:
    def __init__(self) -> None:
        self.history_store = DummyHistoryStore()
        self._callbacks: dict[str, list[callable]] = {}

    def register_callback(self, event: str, callback: callable) -> None:
        self._callbacks.setdefault(event, []).append(callback)

    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return {"jobs": []}


class DummyWebUIProcessManager:
    def get_recent_output_tail(self) -> dict[str, object]:
        return {"stdout_tail": "boot ok", "stderr_tail": ""}


def test_manual_diagnostics_bundle_triggers_builder(monkeypatch, tmp_path: Path) -> None:
    recorded: list[dict[str, object]] = []

    def fake_build(**kwargs: object) -> Path:
        recorded.append(kwargs)
        return tmp_path / "manual.zip"

    monkeypatch.setattr("src.utils.diagnostics_bundle_v2.build_crash_bundle", fake_build)
    monkeypatch.setattr("src.controller.app_controller.build_crash_bundle", fake_build)

    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    controller.webui_process_manager = DummyWebUIProcessManager()
    controller.generate_diagnostics_bundle_manual()

    assert recorded
    assert recorded[0]["reason"] == "manual_request"
    assert recorded[0]["include_process_state"] is True
    assert recorded[0]["include_queue_state"] is True
    assert recorded[0]["webui_tail"]["stdout_tail"] == "boot ok"


def test_watchdog_violation_generates_bundle(monkeypatch, tmp_path: Path) -> None:
    recorded: list[dict[str, object]] = []

    def fake_build(**kwargs: object) -> Path:
        recorded.append(kwargs)
        return tmp_path / "watchdog.zip"

    monkeypatch.setattr("src.utils.diagnostics_bundle_v2.build_crash_bundle", fake_build)
    monkeypatch.setattr("src.controller.app_controller.build_crash_bundle", fake_build)

    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    controller.webui_process_manager = DummyWebUIProcessManager()
    exc = WatchdogViolationError("Watchdog MEMORY")
    envelope = wrap_exception(
        exc,
        subsystem="watchdog",
        job_id="job-1",
        context={"watchdog_reason": "MEMORY", "pid": 1},
    )
    controller._on_watchdog_violation_event("job-1", envelope)

    assert recorded
    assert recorded[0]["reason"].startswith("watchdog_")
