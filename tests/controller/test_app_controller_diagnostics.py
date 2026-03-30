"""Tests covering AppController diagnostics helpers."""

from __future__ import annotations

from pathlib import Path
import time

from src.app.optional_dependency_probes import (
    OPTIONAL_DEPENDENCY_SCHEMA_V1,
    OptionalDependencyCapability,
    OptionalDependencySnapshot,
)
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


def test_open_debug_hub_uses_app_controller_as_controller(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    def fake_open(**kwargs: object) -> object:
        recorded.update(kwargs)
        return object()

    monkeypatch.setattr("src.controller.app_controller.DebugHubPanelV2.open", fake_open)

    controller = AppController(
        None,
        pipeline_runner=DummyPipelineRunner(),
        job_service=DummyJobService(),
    )
    controller.pipeline_controller = object()
    controller.app_state = object()
    controller.gui_log_handler = object()

    controller.open_debug_hub()

    assert recorded["controller"] is controller


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


def test_diagnostics_snapshot_includes_pipeline_tab_metrics() -> None:
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    controller.main_window = type(
        "Window",
        (),
        {
            "pipeline_tab": type(
                "PipelineTab",
                (),
                {
                    "get_diagnostics_snapshot": lambda self: {
                        "callback_metrics": {
                            "_on_runtime_status_changed": {"count": 3, "avg_ms": 1.5}
                        },
                        "hot_surface_scheduler": {"count": 2, "avg_ms": 4.0},
                        "running_job_panel": {"count": 4, "avg_ms": 2.0},
                    }
                },
            )()
            ,
            "log_trace_panel_v2": type(
                "LogTracePanel",
                (),
                {"get_diagnostics_snapshot": lambda self: {"count": 5, "avg_ms": 1.0}},
            )()
        },
    )()

    snapshot = controller.get_diagnostics_snapshot()

    assert snapshot["pipeline_tab"]["callback_metrics"]["_on_runtime_status_changed"]["count"] == 3
    assert snapshot["pipeline_tab"]["hot_surface_scheduler"]["count"] == 2
    assert snapshot["pipeline_tab"]["running_job_panel"]["count"] == 4
    assert snapshot["log_trace_panel"]["count"] == 5
    assert isinstance(snapshot["process_inspector"].get("processes"), list)
    assert isinstance(snapshot["threads"], dict)


def test_diagnostics_snapshot_reuses_cached_heavy_sections(monkeypatch) -> None:
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    process_calls = 0
    thread_calls = 0

    def fake_process_snapshot() -> dict[str, object]:
        nonlocal process_calls
        process_calls += 1
        return {
            "scanner_status": "ready",
            "risk": {"status": "normal"},
            "processes": ["pid=111 python.exe | main"],
        }

    def fake_thread_snapshot() -> dict[str, object]:
        nonlocal thread_calls
        thread_calls += 1
        return {"thread_count": 1, "threads": []}

    monkeypatch.setattr(controller, "_build_process_inspector_snapshot", fake_process_snapshot)
    monkeypatch.setattr(controller, "_build_thread_snapshot", fake_thread_snapshot)

    first = controller.get_diagnostics_snapshot()
    second = controller.get_diagnostics_snapshot()

    assert process_calls == 1
    assert thread_calls == 1
    assert first["process_inspector"]["processes"] == ["pid=111 python.exe | main"]
    assert second["threads"]["thread_count"] == 1


def test_protected_process_pids_include_host_managed_runtime_pids() -> None:
    class ManagedRuntimeJobService(DummyJobService):
        def get_diagnostics_snapshot(self) -> dict[str, object]:
            return {
                "jobs": [{"external_pids": [111]}],
                "managed_runtimes": {
                    "webui": {"pid": 222},
                    "comfy": {"pid": 333},
                },
            }

    controller = AppController(
        None,
        pipeline_runner=DummyPipelineRunner(),
        job_service=ManagedRuntimeJobService(),
    )

    assert set(controller._get_protected_process_pids()) == {111, 222, 333}


def test_diagnostics_snapshot_normalizes_runtime_host_state() -> None:
    class RemoteRuntimeJobService(DummyJobService):
        def describe_protocol(self) -> dict[str, object]:
            return {
                "transport": "local-child",
                "protocol": "stablenew.runtime_host",
                "version": 1,
            }

        def get_diagnostics_snapshot(self) -> dict[str, object]:
            return {
                "jobs": [],
                "host_pid": 777,
                "runtime_host_client": {
                    "connected": True,
                    "startup_error": None,
                    "host_pid": 777,
                    "transport": "local-child",
                    "protocol": "stablenew.runtime_host",
                    "version": 1,
                },
                "managed_runtimes": {
                    "webui": {
                        "managed": True,
                        "state": "ready",
                        "pid": 456,
                        "autostart_enabled": True,
                        "startup_error": None,
                    }
                },
            }

    controller = AppController(
        None,
        pipeline_runner=DummyPipelineRunner(),
        job_service=RemoteRuntimeJobService(),
    )

    snapshot = controller.get_diagnostics_snapshot()

    assert snapshot["runtime_host"] == {
        "transport": "local-child",
        "protocol": "stablenew.runtime_host",
        "version": 1,
        "connected": True,
        "host_pid": 777,
        "startup_error": None,
        "managed_runtimes": {
            "webui": {
                "managed": True,
                "state": "ready",
                "pid": 456,
                "autostart_enabled": True,
                "startup_error": None,
            }
        },
    }


def test_diagnostics_snapshot_refreshes_stale_cache_async(monkeypatch) -> None:
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    controller._diagnostics_process_snapshot_cache = {
        "scanner_status": "cached",
        "risk": {"status": "normal"},
        "processes": ["pid=222 cached"],
    }
    controller._diagnostics_thread_snapshot_cache = {"thread_count": 2, "threads": []}
    controller._diagnostics_heavy_snapshot_ts = time.monotonic() - 10.0

    scheduled: list[str] = []

    def fake_spawn_tracked_thread(
        target,
        args=(),
        kwargs=None,
        name=None,
        daemon=False,
        purpose=None,
    ):
        scheduled.append(str(name))
        return object()

    def fail_if_called() -> dict[str, object]:
        raise AssertionError("stale cached diagnostics should not rebuild on the caller thread")

    monkeypatch.setattr(controller, "_spawn_tracked_thread", fake_spawn_tracked_thread)
    monkeypatch.setattr(controller, "_build_process_inspector_snapshot", fail_if_called)
    monkeypatch.setattr(controller, "_build_thread_snapshot", fail_if_called)

    snapshot = controller.get_diagnostics_snapshot()

    assert snapshot["process_inspector"]["processes"] == ["pid=222 cached"]
    assert snapshot["threads"]["thread_count"] == 2
    assert scheduled == ["DiagnosticsSnapshotRefresh"]


def test_diagnostics_snapshot_includes_optional_dependency_snapshot() -> None:
    controller = AppController(
        None,
        pipeline_runner=DummyPipelineRunner(),
        job_service=DummyJobService(),
        optional_dependency_snapshot=OptionalDependencySnapshot(
            capabilities={
                "workflow:demo@1.0.0": OptionalDependencyCapability(
                    capability_id="workflow:demo@1.0.0",
                    available=True,
                    status="ready",
                    detail="ok",
                    source="comfy",
                )
            }
        ),
    )

    snapshot = controller.get_diagnostics_snapshot()

    assert snapshot["optional_dependencies"]["schema"] == OPTIONAL_DEPENDENCY_SCHEMA_V1
    assert snapshot["optional_dependencies"]["capabilities"]["workflow:demo@1.0.0"]["status"] == "ready"
