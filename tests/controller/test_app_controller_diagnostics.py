"""Tests covering AppController diagnostics helpers."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.app.optional_dependency_probes import (
    OPTIONAL_DEPENDENCY_SCHEMA_V1,
    OptionalDependencyCapability,
    OptionalDependencySnapshot,
)
from src.controller.app_controller import AppController
from src.controller.ports.presentation_actions import PresentationActions
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.utils.error_envelope_v2 import wrap_exception
from src.utils.exceptions_v2 import WatchdogViolationError


class DummyPipelineRunner:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class DummyJobService:
    def __init__(self) -> None:
        # JobRepository is the sole live history authority.
        self.history_store = JobRepository(":memory:")
        self._callbacks: dict[str, list[callable]] = {}

    def register_callback(self, event: str, callback: callable) -> None:
        self._callbacks.setdefault(event, []).append(callback)

    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return {"jobs": []}


class DummyWebUIProcessManager:
    def get_recent_output_tail(self) -> dict[str, object]:
        return {"stdout_tail": "boot ok", "stderr_tail": ""}


def test_load_history_entries_prefers_recent_jobs_api() -> None:
    class RecentHistoryStore:
        def __init__(self) -> None:
            self.recent_called = False
            self.invalidated = False

        def list_recent_jobs(self, *, statuses, limit: int = 20):
            self.recent_called = True
            assert statuses == {JobStatus.COMPLETED, JobStatus.FAILED}
            return [
                JobHistoryEntry(
                    job_id="job-recent",
                    created_at=time_now(),
                    status=JobStatus.COMPLETED,
                )
            ]

        def invalidate_cache(self) -> None:
            self.invalidated = True

        def list_jobs(self, limit: int | None = None) -> list[object]:
            raise AssertionError("full history scan should not be used")

    def time_now():
        from datetime import datetime

        return datetime.utcnow()

    controller = AppController.__new__(AppController)
    store = RecentHistoryStore()
    controller.job_service = SimpleNamespace(history_store=store)

    entries = AppController._load_history_entries(controller, limit=10)

    assert store.recent_called is True
    assert store.invalidated is False
    assert len(entries) == 1
    assert entries[0].job_id == "job-recent"


def test_open_debug_hub_delegates_to_presentation_port() -> None:
    actions = Mock(spec=PresentationActions)
    controller = AppController(
        None,
        pipeline_runner=DummyPipelineRunner(),
        job_service=DummyJobService(),
        presentation_actions=actions,
    )
    controller.pipeline_controller = object()
    controller.app_state = object()
    controller.gui_log_handler = object()

    controller.open_debug_hub()

    actions.open_debug_hub.assert_called_once_with()


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
            )(),
            "log_trace_panel_v2": type(
                "LogTracePanel",
                (),
                {"get_diagnostics_snapshot": lambda self: {"count": 5, "avg_ms": 1.0}},
            )(),
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
    """Cache-reuse behavior now lives in test_diagnostics_read_model.py (the
    read model owns the heavy cache). This keeps the controller-level
    integration check: the adapter actually serves cached heavy sections."""
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    model = controller._diagnostics_read_model
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

    monkeypatch.setattr(model, "build_process_inspector_snapshot", fake_process_snapshot)
    monkeypatch.setattr(model, "build_thread_snapshot", fake_thread_snapshot)

    first = controller.get_diagnostics_snapshot()
    second = controller.get_diagnostics_snapshot()

    assert process_calls == 1
    assert thread_calls == 1
    assert first["process_inspector"]["processes"] == ["pid=111 python.exe | main"]
    assert second["threads"]["thread_count"] == 1


def test_diagnostics_snapshot_refreshes_stale_cache_async(monkeypatch) -> None:
    """Stale-refresh scheduling detail now lives in test_diagnostics_read_model.py.
    This keeps the controller-level integration check: the adapter surfaces a
    stale cache and the controller's own tracked-thread authority is used."""
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    model = controller._diagnostics_read_model
    model._process_snapshot_cache = {
        "scanner_status": "cached",
        "risk": {"status": "normal"},
        "processes": ["pid=222 cached"],
    }
    model._thread_snapshot_cache = {"thread_count": 2, "threads": []}
    model._heavy_snapshot_ts = time.monotonic() - 10.0

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
    monkeypatch.setattr(model, "build_process_inspector_snapshot", fail_if_called)
    monkeypatch.setattr(model, "build_thread_snapshot", fail_if_called)

    snapshot = controller.get_diagnostics_snapshot()

    assert snapshot["process_inspector"]["processes"] == ["pid=222 cached"]
    assert snapshot["threads"]["thread_count"] == 2
    assert scheduled == ["DiagnosticsSnapshotRefresh"]


def test_snapshot_and_explanation_adapters_delegate_to_the_read_model(monkeypatch) -> None:
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    model = controller._diagnostics_read_model
    monkeypatch.setattr(model, "get_diagnostics_snapshot", lambda: {"sentinel": "snapshot"})
    monkeypatch.setattr(model, "get_job_explanation_payload", lambda job_id: {"sentinel": job_id})

    assert controller.get_diagnostics_snapshot() == {"sentinel": "snapshot"}
    assert controller.get_job_explanation_payload("job-9") == {"sentinel": "job-9"}


def test_bundle_generation_holds_the_read_model_lock(monkeypatch, tmp_path: Path) -> None:
    held: list[bool] = []

    def fake_build(**kwargs: object) -> Path:
        held.append(controller._diagnostics_read_model.lock.locked())
        return tmp_path / "locked.zip"

    monkeypatch.setattr("src.controller.app_controller.build_crash_bundle", fake_build)
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )

    controller.generate_diagnostics_bundle_manual()

    assert held == [True]
    assert controller._diagnostics_read_model.lock.locked() is False
    snapshot = controller.get_diagnostics_snapshot()
    assert snapshot["last_bundle"] == str(tmp_path / "locked.zip")
    assert snapshot["last_bundle_reason"] == "manual_request"


def test_controller_keeps_no_diagnostics_projection_state_or_forwarders() -> None:
    controller = AppController(
        None, pipeline_runner=DummyPipelineRunner(), job_service=DummyJobService()
    )
    extracted = [
        "_find_live_job",
        "_extract_normalized_snapshot",
        "_resolve_job_status_value",
        "_resolve_stage_flow",
        "_build_debug_job_label",
        "_build_job_origin_text",
        "_build_job_stage_prompt_rows",
        "_build_job_metadata_payload",
        "_build_diagnostics_app_state_snapshot",
        "_build_enriched_diagnostics_jobs",
        "_format_job_stage_display",
        "_format_job_diagnostics_text",
        "_build_process_inspector_snapshot",
        "_build_thread_snapshot",
        "_serialize_job_summary",
        "_serialize_runtime_status",
        "_get_cached_heavy_diagnostics_snapshots",
        "_schedule_heavy_diagnostics_refresh",
        "_refresh_heavy_diagnostics_snapshots_async",
        "_store_heavy_diagnostics_snapshots",
    ]
    assert [name for name in extracted if hasattr(AppController, name)] == []
    cache_state = [
        "_diagnostics_lock",
        "_diagnostics_process_snapshot_cache",
        "_diagnostics_thread_snapshot_cache",
        "_diagnostics_heavy_snapshot_ts",
        "_diagnostics_heavy_snapshot_refresh_in_progress",
    ]
    assert [name for name in cache_state if hasattr(controller, name)] == []
    hook_fields = [
        "_original_excepthook",
        "_original_threading_excepthook",
        "_original_tk_report_callback_exception",
    ]
    assert [name for name in hook_fields if hasattr(controller, name)] == []
    # Protected PIDs stay on the controller for ProcessAutoScannerService.
    assert callable(controller._get_protected_process_pids)


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
    assert (
        snapshot["optional_dependencies"]["capabilities"]["workflow:demo@1.0.0"]["status"]
        == "ready"
    )
