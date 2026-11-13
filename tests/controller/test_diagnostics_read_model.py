"""Payload characterization for the diagnostics read model (ARCH-953).

The fixtures are deterministic stand-ins for every collaborator: no real
process enumeration, thread registry, GPU, Tk widget or network is used.  The
expected structures were first validated against the pre-extraction
``AppController`` implementation and must not drift.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.queue.job_model import JobStatus

# ---------------------------------------------------------------------------
# World: every input the read model may consume
# ---------------------------------------------------------------------------


@dataclass
class Probes:
    risk: Any = None
    processes: Any = field(default_factory=list)
    registry: Any = None
    threads: list[Any] = field(default_factory=list)
    frames: dict[int, Any] = field(default_factory=dict)


@dataclass
class World:
    job_service: Any = None
    app_state: Any = None
    webui_process_manager: Any = None
    pipeline_controller: Any = None
    webui_connection_controller: Any = None
    process_auto_scanner: Any = None
    optional_dependency_snapshot: Any = None
    main_window: Any = None
    runtime_status: Any = None
    last_ui_heartbeat_ts: Any = 1.0
    last_queue_activity_ts: Any = 2.0
    last_runner_activity_ts: Any = 3.0
    queue_projection_timing: Any = None
    projection_coordinator: Any = field(
        default_factory=lambda: SimpleNamespace(get_metrics_snapshot=lambda: {})
    )
    projection_sink: Any = field(
        default_factory=lambda: SimpleNamespace(get_metrics_snapshot=lambda: {})
    )
    last_bundle: Path | None = None
    last_bundle_reason: str | None = None
    probes: Probes = field(default_factory=Probes)


def _history_entry(world: World, job_id: str) -> Any:
    for entry in list(getattr(world.app_state, "history_items", []) or []):
        if getattr(entry, "job_id", None) == job_id:
            return entry
    return None


def _protected_pids(world: World) -> list[int]:
    pids: set[int] = set()
    pid = getattr(world.webui_process_manager, "pid", None)
    if pid and isinstance(pid, int):
        pids.add(pid)
    if world.job_service:
        for entry in world.job_service.get_diagnostics_snapshot().get("jobs") or []:
            for external in entry.get("external_pids", []) or []:
                if isinstance(external, int):
                    pids.add(external)
    return sorted(pids)


def _read_model_factory(world: World) -> Any:
    from src.controller.app_controller_services.diagnostics_read_model import (
        DiagnosticsProbes,
        DiagnosticsReadModel,
        DiagnosticsSources,
    )

    probes = world.probes

    def _process_risk() -> Any:
        if isinstance(probes.risk, Exception):
            raise probes.risk
        return probes.risk

    def _iter_processes() -> Any:
        if isinstance(probes.processes, Exception):
            raise probes.processes
        return list(probes.processes)

    def _registry() -> Any:
        if isinstance(probes.registry, Exception):
            raise probes.registry
        return probes.registry

    sources = DiagnosticsSources(
        job_service=lambda: world.job_service,
        spawn_tracked_thread=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected spawn")
        ),
        is_shutting_down=lambda: False,
        protected_pids=lambda: _protected_pids(world),
        latest_runtime_status=lambda: world.runtime_status,
        history_entry=lambda job_id: _history_entry(world, job_id),
        app_state=lambda: world.app_state,
        webui_process_manager=lambda: world.webui_process_manager,
        pipeline_controller=lambda: world.pipeline_controller,
        webui_connection_controller=lambda: world.webui_connection_controller,
        process_auto_scanner=lambda: world.process_auto_scanner,
        optional_dependency_snapshot=lambda: world.optional_dependency_snapshot,
        main_window=lambda: world.main_window,
        last_ui_heartbeat_ts=lambda: world.last_ui_heartbeat_ts,
        last_queue_activity_ts=lambda: world.last_queue_activity_ts,
        last_runner_activity_ts=lambda: world.last_runner_activity_ts,
        queue_projection_timing=lambda: world.queue_projection_timing,
        projection_coordinator_metrics=lambda: world.projection_coordinator.get_metrics_snapshot(),
        projection_sink_metrics=lambda: world.projection_sink.get_metrics_snapshot(),
        last_bundle=lambda: world.last_bundle,
        last_bundle_reason=lambda: world.last_bundle_reason,
    )
    return DiagnosticsReadModel(
        sources,
        probes=DiagnosticsProbes(
            collect_process_risk=_process_risk,
            iter_processes=_iter_processes,
            format_process=lambda process: f"pid={process.pid} {process.name}",
            thread_registry=_registry,
            list_threads=lambda: list(probes.threads),
            current_frames=lambda: dict(probes.frames),
        ),
    )


# Replaced by the pre-extraction harness that validated these expectations.
_FACTORY: Callable[[World], Any] = _read_model_factory


def _subject(world: World) -> Any:
    return _FACTORY(world)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _runtime_status(
    job_id: str = "job-run",
    *,
    stage: str = "txt2img",
    display: str = "txt2img 1/2",
    progress: Any = 0.5,
) -> Any:
    return SimpleNamespace(
        job_id=job_id,
        current_stage=stage,
        stage_index=0,
        total_stages=2,
        progress=progress,
        eta_seconds=12.5,
        actual_seed=99,
        current_step=10,
        total_steps=20,
        stage_detail="sampling",
        started_at=datetime(2026, 1, 2, 3, 4, 5),
        get_stage_display=lambda: display,
        get_eta_display=lambda: "00:12",
    )


def _summary(job_id: str, label: str, **extra: Any) -> Any:
    values: dict[str, Any] = {
        "job_id": job_id,
        "prompt_pack_name": "Pack A",
        "stage_chain_labels": ["txt2img", "adetailer"],
        "status": "running",
        "get_display_summary": lambda: label,
    }
    values.update(extra)
    return SimpleNamespace(**values)


NORMALIZED_RUNNING: dict[str, Any] = {
    "prompt_pack_name": "Pack A",
    "prompt_pack_id": "pack-a",
    "prompt_pack_row_index": 2,
    "variant_index": 0,
    "batch_index": 1,
    "model": "sdxl-base",
    "sampler": "Euler",
    "steps": 20,
    "cfg_scale": 7.0,
    "width": 1024,
    "height": 768,
    "seed": 42,
    "output_dir": "out/run1",
    "stage_chain": ["txt2img", "adetailer"],
    "randomization_enabled": True,
    "matrix_slot_values": {"style": "noir"},
    "config_layers": {"base": 1},
    "prompt": "a cat",
    "negative_prompt": "blurry",
    "txt2img_prompt_info": {
        "final_prompt": "a cat, detailed",
        "final_negative_prompt": "blurry, bad",
        "global_negative_terms": "lowres",
    },
    "pack_usage": [
        {"pack_name": "Pack A", "used_for_stage": "txt2img"},
        {"pack_id": "pack-b"},
        "junk",
        {"pack_name": None},
    ],
}


class _QueueSnapshotRecord:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def to_queue_snapshot(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _live_job(**values: Any) -> Any:
    defaults: dict[str, Any] = {
        "status": JobStatus.RUNNING,
        "prompt_source": "pack",
        "run_mode": "queue",
        "error_message": None,
        "result": None,
        "_normalized_record": _QueueSnapshotRecord(dict(NORMALIZED_RUNNING)),
        "snapshot": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _job_service(
    jobs: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> Any:
    registry = dict(jobs or {})

    def get_job(job_id: str) -> Any:
        value = registry.get(job_id)
        if isinstance(value, Exception):
            raise value
        return value

    return SimpleNamespace(
        job_queue=SimpleNamespace(get_job=get_job),
        get_diagnostics_snapshot=lambda: dict(snapshot or {"jobs": []}),
    )


def _app_state(**values: Any) -> Any:
    defaults: dict[str, Any] = {
        "running_job": None,
        "runtime_status": None,
        "queue_jobs": [],
        "history_items": [],
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _history(job_id: str, **values: Any) -> Any:
    defaults: dict[str, Any] = {
        "job_id": job_id,
        "status": JobStatus.COMPLETED,
        "snapshot": None,
        "prompt_source": None,
        "run_mode": None,
        "error_message": None,
        "result": None,
        "duration_ms": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# get_job_explanation_payload
# ---------------------------------------------------------------------------


def test_explanation_requires_a_job_id_and_a_known_job() -> None:
    world = World(job_service=_job_service(), app_state=_app_state())
    subject = _subject(world)

    assert subject.get_job_explanation_payload("") is None
    assert subject.get_job_explanation_payload("job-unknown") is None


def test_explanation_for_a_running_job_with_matching_runtime_status() -> None:
    world = World(
        job_service=_job_service({"job-run": _live_job()}),
        app_state=_app_state(),
        runtime_status=_runtime_status("job-run"),
    )

    payload = _subject(world).get_job_explanation_payload("job-run")

    assert payload == {
        "job_id": "job-run",
        "display_label": "Pack A | row=3 | v=1 | b=2 | job-run",
        "origin_text": (
            "Job: job-run | Packs: Pack A (txt2img), pack-b | source=pack"
            " | run_mode=queue | status=running | runtime=txt2img 1/2"
        ),
        "stage_flow": ["txt2img", "adetailer"],
        "stage_prompts": [
            {
                "stage": "txt2img",
                "prompt": "a cat, detailed",
                "negative": "blurry, bad",
                "global_terms": "lowres",
                "status": "current",
            },
            {
                "stage": "adetailer",
                "prompt": "a cat",
                "negative": "blurry",
                "global_terms": "-",
                "status": "available",
            },
        ],
        "metadata": {
            "job_id": "job-run",
            "status": "running",
            "prompt_pack_id": "pack-a",
            "prompt_pack_name": "Pack A",
            "row_index": 2,
            "variant_index": 0,
            "batch_index": 1,
            "model": "sdxl-base",
            "sampler": "Euler",
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 768,
            "seed": 42,
            "output_dir": "out/run1",
            "stage_chain": ["txt2img", "adetailer"],
            "randomization_enabled": True,
            "matrix_slot_values": {"style": "noir"},
            "config_layers": {"base": 1},
            "error_message": None,
            "runtime_status": {
                "current_stage": "txt2img",
                "stage_index": 0,
                "total_stages": 2,
                "progress": 0.5,
                "eta_seconds": 12.5,
                "actual_seed": 99,
                "current_step": 10,
                "total_steps": 20,
                "stage_detail": "sampling",
            },
        },
    }


def test_runtime_status_for_another_job_is_ignored() -> None:
    world = World(
        job_service=_job_service({"job-run": _live_job()}),
        app_state=_app_state(),
        runtime_status=_runtime_status("someone-else"),
    )

    payload = _subject(world).get_job_explanation_payload("job-run")

    assert payload is not None
    assert "runtime=" not in payload["origin_text"]
    assert "runtime_status" not in payload["metadata"]
    assert [row["status"] for row in payload["stage_prompts"]] == ["available", "available"]


def test_explanation_for_a_completed_history_only_job() -> None:
    entry = _history(
        "job-done",
        status=JobStatus.COMPLETED,
        snapshot={
            "normalized_job": {
                "prompt_pack_name": "Pack H",
                "stage_chain": ["txt2img"],
                "prompt": "history prompt",
                "model": "m1",
                "pack_usage": [],
            }
        },
        prompt_source="manual",
        run_mode="direct",
        result={"images": 2},
    )
    world = World(job_service=_job_service(), app_state=_app_state(history_items=[entry]))

    payload = _subject(world).get_job_explanation_payload("job-done")

    assert payload is not None
    assert payload["display_label"] == "Pack H | job-done"
    assert payload["origin_text"] == (
        "Job: job-done | Pack: Pack H | source=manual | run_mode=direct | status=completed"
    )
    assert payload["stage_flow"] == ["txt2img"]
    assert payload["stage_prompts"] == [
        {
            "stage": "txt2img",
            "prompt": "history prompt",
            "negative": "-",
            "global_terms": "-",
            "status": "available",
        }
    ]
    assert payload["metadata"]["status"] == "completed"
    assert payload["metadata"]["model"] == "m1"
    assert payload["metadata"]["result"] == {"images": 2}
    assert payload["metadata"]["stage_chain"] == ["txt2img"]
    assert payload["metadata"]["error_message"] is None
    assert "runtime_status" not in payload["metadata"]


def test_failed_job_prefers_live_error_and_status_over_history() -> None:
    live = _live_job(
        status=JobStatus.FAILED,
        error_message="live failure",
        result={"from": "live"},
    )
    entry = _history(
        "job-fail",
        status=JobStatus.COMPLETED,
        error_message="history failure",
        result={"from": "history"},
    )
    world = World(
        job_service=_job_service({"job-fail": live}),
        app_state=_app_state(history_items=[entry]),
    )

    payload = _subject(world).get_job_explanation_payload("job-fail")

    assert payload is not None
    assert payload["metadata"]["status"] == "failed"
    assert payload["metadata"]["error_message"] == "live failure"
    assert payload["metadata"]["result"] == {"from": "live"}
    assert "status=failed" in payload["origin_text"]


def test_status_falls_back_to_history_and_plain_values() -> None:
    plain_live = _live_job(status="queued-text")
    world = World(
        job_service=_job_service({"job-a": plain_live}),
        app_state=_app_state(history_items=[_history("job-b", status="done-text")]),
    )
    subject = _subject(world)

    assert subject.get_job_explanation_payload("job-a")["metadata"]["status"] == "queued-text"
    assert subject.get_job_explanation_payload("job-b")["metadata"]["status"] == "done-text"


def test_malformed_snapshots_fall_through_to_the_next_candidate() -> None:
    live = _live_job(
        _normalized_record=_QueueSnapshotRecord(RuntimeError("bad")),
        snapshot=_QueueSnapshotRecord(["not", "a", "dict"]),
    )
    entry = _history(
        "job-m",
        snapshot={"normalized_job": "not-a-dict"},
    )
    world = World(
        job_service=_job_service({"job-m": live}),
        app_state=_app_state(history_items=[entry]),
    )

    payload = _subject(world).get_job_explanation_payload("job-m")

    assert payload is not None
    assert payload["display_label"] == "job-m | job-m"
    assert payload["stage_flow"] == ["txt2img"]
    assert payload["stage_prompts"] == [
        {
            "stage": "txt2img",
            "prompt": "-",
            "negative": "-",
            "global_terms": "-",
            "status": "available",
        }
    ]
    assert payload["metadata"]["stage_chain"] == []
    assert payload["metadata"]["prompt_pack_id"] is None


def test_snapshot_dict_without_wrapper_is_used_directly() -> None:
    entry = _history("job-w", snapshot={"prompt_pack_name": "Bare", "stage_chain": ["upscale"]})
    world = World(job_service=_job_service(), app_state=_app_state(history_items=[entry]))

    payload = _subject(world).get_job_explanation_payload("job-w")

    assert payload is not None
    assert payload["display_label"] == "Bare | job-w"
    assert payload["stage_flow"] == ["upscale"]


def test_stage_flow_uses_runtime_stage_when_snapshot_has_no_chain() -> None:
    live = _live_job(_normalized_record=None, snapshot=None)
    world = World(
        job_service=_job_service({"job-r": live}),
        app_state=_app_state(),
        runtime_status=_runtime_status("job-r", stage="upscale", display="upscale 2/2"),
    )

    payload = _subject(world).get_job_explanation_payload("job-r")

    assert payload is not None
    assert payload["stage_flow"] == ["upscale"]
    assert payload["stage_prompts"][0]["status"] == "current"
    assert payload["origin_text"].endswith("runtime=upscale 2/2")


def test_runtime_stage_display_failure_is_ignored_in_origin_text() -> None:
    def boom() -> str:
        raise RuntimeError("display failed")

    runtime = _runtime_status("job-run")
    runtime.get_stage_display = boom
    world = World(
        job_service=_job_service({"job-run": _live_job()}),
        app_state=_app_state(),
        runtime_status=runtime,
    )

    payload = _subject(world).get_job_explanation_payload("job-run")

    assert payload is not None
    assert "runtime=" not in payload["origin_text"]


def test_live_job_lookup_failure_is_treated_as_missing() -> None:
    world = World(
        job_service=_job_service({"job-x": RuntimeError("lookup failed")}),
        app_state=_app_state(),
    )

    assert _subject(world).get_job_explanation_payload("job-x") is None


def test_explanation_without_a_job_service_uses_history_only() -> None:
    entry = _history("job-h", snapshot={"normalized_job": {"prompt_pack_name": "OnlyHistory"}})
    world = World(job_service=None, app_state=_app_state(history_items=[entry]))

    payload = _subject(world).get_job_explanation_payload("job-h")

    assert payload is not None
    assert payload["display_label"] == "OnlyHistory | job-h"


# ---------------------------------------------------------------------------
# get_diagnostics_snapshot
# ---------------------------------------------------------------------------


def _full_world(tmp_path: Path) -> World:
    done_entry = _history(
        "job-done",
        snapshot={
            "normalized_job": {
                "prompt_pack_name": "Pack H",
                "stage_chain": ["txt2img"],
            }
        },
        duration_ms=1520,
    )
    running_summary = _summary("job-run", "Pack A job-run summary")
    queued_summary = _summary("job-queued", "queued summary", status="queued")
    snapshot = {
        "queue": {"size": 1},
        "jobs": [
            {
                "job_id": "job-run",
                "status": "running",
                "external_pids": [111, "bad", 222],
                "result_summary": None,
                "retry_attempts": [],
            },
            {
                "job_id": "job-done",
                "status": "completed",
                "external_pids": [],
                "result_summary": {
                    "duration_ms": 1520.4,
                    "output_count": 3,
                    "primary_stage": "txt2img",
                },
                "retry_attempts": [{"attempt": 1}],
            },
            {
                "job_id": "job-failed",
                "external_pids": [],
                "result_summary": {"error": "oom", "duration_ms": 10},
            },
            {"job_id": "job-missing"},
        ],
    }
    return World(
        job_service=_job_service(
            {
                "job-run": _live_job(),
                "job-failed": RuntimeError("lookup failed"),
            },
            snapshot=snapshot,
        ),
        app_state=_app_state(
            running_job=running_summary,
            runtime_status=_runtime_status("job-run"),
            queue_jobs=[queued_summary],
            history_items=[done_entry],
        ),
        runtime_status=_runtime_status("ignored-by-app-state"),
        webui_process_manager=SimpleNamespace(
            pid=4321,
            get_recent_output_tail=lambda: {"stdout_tail": "ok", "stderr_tail": ""},
        ),
        pipeline_controller=SimpleNamespace(
            get_preview_build_timing_snapshot=lambda: {"elapsed_ms": 34.0},
        ),
        webui_connection_controller=SimpleNamespace(
            get_last_connection_timing_snapshot=lambda: {"total_elapsed_ms": 56.0},
            get_state=lambda: SimpleNamespace(value="ready"),
        ),
        process_auto_scanner=SimpleNamespace(
            summary=SimpleNamespace(timestamp=123.0, scanned=5, killed=[999]),
            get_status_text=lambda: "idle",
            enabled=False,
            scan_interval=30.0,
        ),
        optional_dependency_snapshot=SimpleNamespace(to_dict=lambda: {"schema": "optional.v1"}),
        main_window=SimpleNamespace(
            pipeline_tab=SimpleNamespace(get_diagnostics_snapshot=lambda: {"tab": 1}),
            log_trace_panel_v2=SimpleNamespace(get_diagnostics_snapshot=lambda: {"count": 5}),
        ),
        last_ui_heartbeat_ts=100.0,
        last_queue_activity_ts=101.5,
        last_runner_activity_ts=102.5,
        queue_projection_timing={"elapsed_ms": 12.5, "job_count": 2},
        projection_coordinator=SimpleNamespace(get_metrics_snapshot=lambda: {"flushes": 3}),
        projection_sink=SimpleNamespace(get_metrics_snapshot=lambda: {"updates": 7}),
        last_bundle=tmp_path / "bundle.zip",
        last_bundle_reason="manual_request",
        probes=Probes(
            risk={"status": "normal"},
            processes=[SimpleNamespace(pid=10, name="python.exe")],
            registry=SimpleNamespace(
                dump_status=lambda: "tracked: 1",
                get_active_threads=lambda: [
                    SimpleNamespace(thread=SimpleNamespace(ident=2), purpose="Worker purpose")
                ],
            ),
            threads=[
                SimpleNamespace(name="Worker", ident=2, daemon=True, is_alive=lambda: True),
                SimpleNamespace(name="MainThread", ident=1, daemon=False, is_alive=lambda: True),
            ],
            frames={
                1: SimpleNamespace(
                    f_code=SimpleNamespace(co_filename="main.py", co_name="run"), f_lineno=10
                )
            },
        ),
    )


def test_full_diagnostics_snapshot_structure(tmp_path: Path) -> None:
    world = _full_world(tmp_path)

    data = _subject(world).get_diagnostics_snapshot()

    assert list(data) == [
        "queue",
        "jobs",
        "webui_tail",
        "controller",
        "pipeline_controller",
        "webui_connection",
        "optional_dependencies",
        "pipeline_tab",
        "log_trace_panel",
        "app_state",
        "process_inspector",
        "threads",
        "last_bundle",
        "last_bundle_reason",
    ]
    assert data["queue"] == {"size": 1}
    assert data["webui_tail"] == {"stdout_tail": "ok", "stderr_tail": ""}
    assert data["controller"] == {
        "last_ui_heartbeat_ts": 100.0,
        "last_queue_activity_ts": 101.5,
        "last_runner_activity_ts": 102.5,
        "queue_projection_timing": {"elapsed_ms": 12.5, "job_count": 2},
        "projection_coordinator": {"flushes": 3},
        "projection_sink": {"updates": 7},
    }
    assert data["pipeline_controller"] == {"preview_build_timing": {"elapsed_ms": 34.0}}
    assert data["webui_connection"] == {"state": "ready", "timing": {"total_elapsed_ms": 56.0}}
    assert data["optional_dependencies"] == {"schema": "optional.v1"}
    assert data["pipeline_tab"] == {"tab": 1}
    assert data["log_trace_panel"] == {"count": 5}
    assert data["app_state"] == {
        "running_job": {
            "job_id": "job-run",
            "display_label": "Pack A job-run summary",
            "prompt_pack_name": "Pack A",
            "stage_chain_labels": ["txt2img", "adetailer"],
            "status": "running",
        },
        "runtime_status": {
            "job_id": "job-run",
            "stage_display": "txt2img 1/2",
            "progress_pct": 50,
            "eta_display": "00:12",
            "started_at": "2026-01-02T03:04:05",
            "stage_detail": "sampling",
        },
        "queue_job_count": 1,
        "history_count": 1,
    }
    assert data["jobs"] == [
        {
            "job_id": "job-run",
            "status": "running",
            "external_pids": [111, "bad", 222],
            "result_summary": None,
            "retry_attempts": [],
            "display_label": "Pack A job-run summary",
            "stage_display": "txt2img -> adetailer",
            "pid_display": "111, 222",
            "diagnostics_text": "no diagnostics",
        },
        {
            "job_id": "job-done",
            "status": "completed",
            "external_pids": [],
            "result_summary": {
                "duration_ms": 1520.4,
                "output_count": 3,
                "primary_stage": "txt2img",
            },
            "retry_attempts": [{"attempt": 1}],
            "display_label": "Pack H | job-done",
            "stage_display": "txt2img",
            "pid_display": "none",
            "diagnostics_text": "duration=1520ms | outputs=3 | retries=1",
        },
        {
            "job_id": "job-failed",
            "external_pids": [],
            "result_summary": {"error": "oom", "duration_ms": 10},
            "display_label": "job-failed | job-failed",
            "stage_display": "-",
            "pid_display": "none",
            "diagnostics_text": "duration=10ms | error=oom",
        },
        {
            "job_id": "job-missing",
            "display_label": "job-missing | job-missing",
            "stage_display": "-",
            "pid_display": "none",
            "diagnostics_text": "no diagnostics",
        },
    ]
    assert data["process_inspector"] == {
        "scanner_status": "idle",
        "scanner_enabled": False,
        "scan_interval": 30.0,
        "protected_pids": [111, 222, 4321],
        "summary": {"timestamp": 123.0, "scanned": 5, "killed": [999]},
        "risk": {"status": "normal"},
        "processes": ["pid=10 python.exe"],
    }
    assert data["threads"] == {
        "thread_count": 2,
        "tracked_status": "tracked: 1",
        "threads": [
            {
                "name": "MainThread",
                "ident": 1,
                "daemon": False,
                "alive": True,
                "tracked": False,
                "purpose": None,
                "top_frame": {"file": "main.py", "line": 10, "function": "run"},
            },
            {
                "name": "Worker",
                "ident": 2,
                "daemon": True,
                "alive": True,
                "tracked": True,
                "purpose": "Worker purpose",
                "top_frame": None,
            },
        ],
    }
    assert data["last_bundle"] == str(tmp_path / "bundle.zip")
    assert data["last_bundle_reason"] == "manual_request"


def test_minimal_snapshot_without_optional_services() -> None:
    world = World(
        probes=Probes(registry=RuntimeError("no registry")),
        queue_projection_timing="not-a-mapping",
    )

    data = _subject(world).get_diagnostics_snapshot()

    assert data == {
        "controller": {
            "last_ui_heartbeat_ts": 1.0,
            "last_queue_activity_ts": 2.0,
            "last_runner_activity_ts": 3.0,
            "queue_projection_timing": None,
            "projection_coordinator": {},
            "projection_sink": {},
        },
        "app_state": {
            "running_job": None,
            "runtime_status": None,
            "queue_job_count": 0,
            "history_count": 0,
        },
        "jobs": [],
        "process_inspector": {
            "scanner_status": None,
            "scanner_enabled": False,
            "scan_interval": 0.0,
            "protected_pids": [],
            "summary": None,
            "risk": None,
            "processes": [],
        },
        "threads": {"thread_count": 0, "tracked_status": None, "threads": []},
        "last_bundle": None,
        "last_bundle_reason": None,
    }
    assert list(data) == [
        "controller",
        "app_state",
        "jobs",
        "process_inspector",
        "threads",
        "last_bundle",
        "last_bundle_reason",
    ]


def _raises(message: str) -> Callable[..., Any]:
    def raiser(*_: Any, **__: Any) -> Any:
        raise RuntimeError(message)

    return raiser


def test_optional_sections_degrade_to_none_when_their_source_fails() -> None:
    world = World(
        webui_process_manager=SimpleNamespace(get_recent_output_tail=_raises("tail")),
        pipeline_controller=SimpleNamespace(get_preview_build_timing_snapshot=_raises("timing")),
        webui_connection_controller=SimpleNamespace(
            get_last_connection_timing_snapshot=_raises("conn"),
            get_state=lambda: None,
        ),
        optional_dependency_snapshot=SimpleNamespace(to_dict=_raises("deps")),
        main_window=SimpleNamespace(
            pipeline_tab=SimpleNamespace(get_diagnostics_snapshot=_raises("tab")),
            log_trace_panel_v2=SimpleNamespace(get_diagnostics_snapshot=_raises("trace")),
        ),
    )

    data = _subject(world).get_diagnostics_snapshot()

    assert data["webui_tail"] is None
    assert data["pipeline_controller"] is None
    assert data["webui_connection"] is None
    assert data["optional_dependencies"] is None
    assert data["pipeline_tab"] is None
    assert data["log_trace_panel"] is None


def test_webui_connection_falls_back_to_the_pipeline_controller_private_member() -> None:
    connection = SimpleNamespace(
        get_last_connection_timing_snapshot=lambda: {"total_elapsed_ms": 9.0},
        get_state=lambda: "plain-state",
    )
    world = World(pipeline_controller=SimpleNamespace(_webui_connection=connection))

    data = _subject(world).get_diagnostics_snapshot()

    assert data["webui_connection"] == {
        "state": "plain-state",
        "timing": {"total_elapsed_ms": 9.0},
    }
    assert "pipeline_controller" not in data


def test_webui_connection_without_state_getter_reports_no_state() -> None:
    connection = SimpleNamespace(get_last_connection_timing_snapshot=lambda: {"t": 1})
    world = World(webui_connection_controller=connection)

    data = _subject(world).get_diagnostics_snapshot()

    assert data["webui_connection"] == {"state": None, "timing": {"t": 1}}


def test_optional_dependency_snapshot_without_to_dict_is_omitted() -> None:
    world = World(optional_dependency_snapshot=object())

    assert "optional_dependencies" not in _subject(world).get_diagnostics_snapshot()


def test_app_state_falls_back_to_the_latest_runtime_status() -> None:
    latest = _runtime_status("latest", display="latest display", progress=None)
    world = World(app_state=_app_state(), runtime_status=latest)

    data = _subject(world).get_diagnostics_snapshot()

    assert data["app_state"]["runtime_status"] == {
        "job_id": "latest",
        "stage_display": "latest display",
        "progress_pct": None,
        "eta_display": "00:12",
        "started_at": "2026-01-02T03:04:05",
        "stage_detail": "sampling",
    }


def test_summary_and_runtime_serialization_tolerate_failing_getters() -> None:
    def boom() -> str:
        raise RuntimeError("no label")

    summary = _summary("job-s", "unused", get_display_summary=boom)
    runtime = _runtime_status("job-s")
    runtime.get_stage_display = boom
    runtime.get_eta_display = boom
    runtime.started_at = "not-a-datetime"
    world = World(app_state=_app_state(running_job=summary, runtime_status=runtime))

    app_state = _subject(world).get_diagnostics_snapshot()["app_state"]

    assert app_state["running_job"]["display_label"] is None
    assert app_state["runtime_status"]["stage_display"] is None
    assert app_state["runtime_status"]["eta_display"] is None
    assert app_state["runtime_status"]["started_at"] is None


def test_enriched_jobs_ignore_non_list_job_payloads() -> None:
    world = World(job_service=_job_service(snapshot={"jobs": None}))

    assert _subject(world).get_diagnostics_snapshot()["jobs"] == []


def test_enriched_job_stage_display_variants() -> None:
    summary = _summary("job-sum", "labelled", stage_chain_labels=["a", "b"])
    world = World(
        job_service=_job_service(
            snapshot={
                "jobs": [
                    {"job_id": "job-sum"},
                    {"job_id": "job-rs", "result_summary": {"primary_stage": "upscale"}},
                ]
            }
        ),
        app_state=_app_state(queue_jobs=[summary]),
        runtime_status=_runtime_status("job-rs", progress="n/a"),
    )

    jobs = _subject(world).get_diagnostics_snapshot()["jobs"]

    assert [(job["job_id"], job["display_label"], job["stage_display"]) for job in jobs] == [
        ("job-sum", "labelled", "a -> b"),
        ("job-rs", "job-rs | job-rs", "txt2img 1/2"),
    ]


def test_history_duration_is_the_diagnostics_text_fallback() -> None:
    entry = _history("job-d", duration_ms=250)
    world = World(
        job_service=_job_service(snapshot={"jobs": [{"job_id": "job-d"}]}),
        app_state=_app_state(history_items=[entry]),
    )

    jobs = _subject(world).get_diagnostics_snapshot()["jobs"]

    assert jobs[0]["diagnostics_text"] == "duration=250ms"


def test_process_inspector_tolerates_probe_failures() -> None:
    world = World(
        probes=Probes(risk=RuntimeError("risk"), processes=RuntimeError("scan")),
        process_auto_scanner=SimpleNamespace(
            summary=None,
            get_status_text=lambda: "off",
            enabled=True,
            scan_interval=None,
        ),
    )

    snapshot = _subject(world).build_process_inspector_snapshot()

    assert snapshot == {
        "scanner_status": "off",
        "scanner_enabled": True,
        "scan_interval": 0.0,
        "protected_pids": [],
        "summary": None,
        "risk": None,
        "processes": [],
    }


def test_process_inspector_includes_scanner_summary_and_protected_pids() -> None:
    world = World(
        job_service=_job_service(
            snapshot={"jobs": [{"job_id": "j", "external_pids": [7, None, "x", 5]}]}
        ),
        webui_process_manager=SimpleNamespace(pid=900),
        process_auto_scanner=SimpleNamespace(
            summary=SimpleNamespace(timestamp=None, scanned=0, killed=None),
            get_status_text=lambda: "armed",
            enabled=True,
            scan_interval=5,
        ),
        probes=Probes(
            risk={"status": "elevated"},
            processes=[
                SimpleNamespace(pid=1, name="a.exe"),
                SimpleNamespace(pid=2, name="b.exe"),
            ],
        ),
    )

    snapshot = _subject(world).build_process_inspector_snapshot()

    assert snapshot["protected_pids"] == [5, 7, 900]
    assert snapshot["summary"] == {"timestamp": None, "scanned": 0, "killed": []}
    assert snapshot["scanner_enabled"] is True
    assert snapshot["scan_interval"] == 5.0
    assert snapshot["risk"] == {"status": "elevated"}
    assert snapshot["processes"] == ["pid=1 a.exe", "pid=2 b.exe"]


def test_thread_snapshot_handles_unidentified_threads_and_bad_frames() -> None:
    broken_frame = SimpleNamespace(f_code=None, f_lineno=1)
    world = World(
        probes=Probes(
            registry=SimpleNamespace(
                dump_status=lambda: {"active": 1},
                get_active_threads=lambda: [
                    SimpleNamespace(thread=SimpleNamespace(ident=None), purpose="ghost"),
                    SimpleNamespace(thread=SimpleNamespace(ident=5), purpose="tracked five"),
                ],
            ),
            threads=[
                SimpleNamespace(name="b-thread", ident=5, daemon=False, is_alive=lambda: False),
                SimpleNamespace(name="a-thread", ident=None, daemon=True, is_alive=lambda: True),
                SimpleNamespace(name="MainThread", ident=3, daemon=False, is_alive=lambda: True),
            ],
            frames={5: broken_frame},
        )
    )

    snapshot = _subject(world).build_thread_snapshot()

    assert snapshot == {
        "thread_count": 3,
        "tracked_status": {"active": 1},
        "threads": [
            {
                "name": "MainThread",
                "ident": 3,
                "daemon": False,
                "alive": True,
                "tracked": False,
                "purpose": None,
                "top_frame": None,
            },
            {
                "name": "a-thread",
                "ident": None,
                "daemon": True,
                "alive": True,
                "tracked": False,
                "purpose": None,
                "top_frame": None,
            },
            {
                "name": "b-thread",
                "ident": 5,
                "daemon": False,
                "alive": False,
                "tracked": True,
                "purpose": "tracked five",
                "top_frame": None,
            },
        ],
    }


def test_thread_snapshot_with_the_real_thread_module_lists_the_current_thread() -> None:
    """Default probes inspect real threads only; no process enumeration runs."""
    from src.controller.app_controller_services.diagnostics_read_model import (
        DiagnosticsReadModel,
        DiagnosticsSources,
    )

    model = DiagnosticsReadModel(
        DiagnosticsSources(
            job_service=lambda: None,
            spawn_tracked_thread=lambda **kwargs: None,
            is_shutting_down=lambda: False,
            protected_pids=lambda: [],
            latest_runtime_status=lambda: None,
            history_entry=lambda job_id: None,
        )
    )

    snapshot = model.build_thread_snapshot()

    names = [thread["name"] for thread in snapshot["threads"]]
    assert threading.current_thread().name in names
    assert snapshot["thread_count"] == len(snapshot["threads"])


# ---------------------------------------------------------------------------
# Heavy-snapshot cache lifecycle (controlled clock, events and spawn fake)
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _HeavyHarness:
    """A read model whose heavy probes are counted and whose spawn is captured."""

    def __init__(self) -> None:
        from src.controller.app_controller_services.diagnostics_read_model import (
            DiagnosticsProbes,
            DiagnosticsReadModel,
            DiagnosticsSources,
        )

        self.clock = _Clock()
        self.process_calls = 0
        self.thread_calls = 0
        self.spawned: list[dict[str, Any]] = []
        self.spawn_error: Exception | None = None
        self.shutting_down = False
        self.process_error: Exception | None = None
        self.thread_error: Exception | None = None
        self.process_gate: threading.Event | None = None

        def risk() -> dict[str, int]:
            self.process_calls += 1
            if self.process_gate is not None:
                assert self.process_gate.wait(5.0)
            return {"call": self.process_calls}

        def threads() -> list[Any]:
            if self.thread_error is not None:
                raise self.thread_error
            return []

        def registry() -> Any:
            self.thread_calls += 1
            return SimpleNamespace(
                dump_status=lambda: f"tracked-{self.thread_calls}",
                get_active_threads=lambda: [],
            )

        def spawn(**kwargs: Any) -> Any:
            if self.spawn_error is not None:
                raise self.spawn_error
            self.spawned.append(kwargs)
            return object()

        def protected() -> list[int]:
            if self.process_error is not None:
                raise self.process_error
            return []

        self.model = DiagnosticsReadModel(
            DiagnosticsSources(
                job_service=lambda: None,
                spawn_tracked_thread=spawn,
                is_shutting_down=lambda: self.shutting_down,
                protected_pids=protected,
                latest_runtime_status=lambda: None,
                history_entry=lambda job_id: None,
            ),
            probes=DiagnosticsProbes(
                collect_process_risk=risk,
                iter_processes=lambda: [],
                format_process=str,
                thread_registry=registry,
                list_threads=threads,
                current_frames=lambda: {},
            ),
            clock=self.clock,
        )

    def snapshot(self) -> dict[str, Any]:
        return self.model.get_diagnostics_snapshot()

    def run_refresh(self) -> None:
        assert len(self.spawned) >= 1
        self.spawned.pop(0)["target"]()


def test_heavy_sections_are_cached_within_the_ttl() -> None:
    harness = _HeavyHarness()

    first = harness.snapshot()
    harness.clock.now += 3.9
    second = harness.snapshot()

    assert harness.process_calls == 1
    assert harness.thread_calls == 1
    assert first["process_inspector"]["risk"] == {"call": 1}
    assert second["threads"]["tracked_status"] == "tracked-1"
    assert harness.spawned == []


def test_stale_cache_is_served_while_one_tracked_refresh_is_scheduled() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    harness.clock.now += 4.0

    stale = harness.snapshot()
    again = harness.snapshot()

    assert stale["process_inspector"]["risk"] == {"call": 1}
    assert again["process_inspector"]["risk"] == {"call": 1}
    assert harness.process_calls == 1, "stale data must not rebuild on the caller thread"
    assert len(harness.spawned) == 1
    assert harness.spawned[0]["name"] == "DiagnosticsSnapshotRefresh"
    assert (
        harness.spawned[0]["purpose"] == "Refresh cached process and thread diagnostics snapshots"
    )

    harness.run_refresh()
    refreshed = harness.snapshot()

    assert refreshed["process_inspector"]["risk"] == {"call": 2}
    assert refreshed["threads"]["tracked_status"] == "tracked-2"
    assert harness.spawned == []
    harness.clock.now += 4.0
    harness.snapshot()
    assert len(harness.spawned) == 1, "a completed refresh re-opens admission"


def test_returned_snapshots_are_defensive_copies() -> None:
    harness = _HeavyHarness()
    first = harness.snapshot()
    first["process_inspector"]["risk"]["call"] = "mutated"
    first["process_inspector"]["processes"].append("injected")
    first["threads"]["threads"].append({"name": "injected"})

    second = harness.snapshot()

    assert second["process_inspector"]["risk"] == {"call": 1}
    assert second["process_inspector"]["processes"] == []
    assert second["threads"]["threads"] == []


def test_concurrent_callers_schedule_a_single_refresh() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    harness.clock.now += 10.0
    callers = 8
    barrier = threading.Barrier(callers)
    errors: list[BaseException] = []

    def call() -> None:
        try:
            barrier.wait(5.0)
            harness.snapshot()
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    workers = [threading.Thread(target=call, name=f"snapshot-caller-{i}") for i in range(callers)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10.0)

    assert errors == []
    assert not any(worker.is_alive() for worker in workers)
    assert len(harness.spawned) == 1
    assert harness.process_calls == 1


def test_spawn_failure_releases_the_refresh_admission_flag() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    harness.clock.now += 5.0
    harness.spawn_error = RuntimeError("no thread available")

    stale = harness.snapshot()
    assert stale["process_inspector"]["risk"] == {"call": 1}

    harness.spawn_error = None
    harness.snapshot()

    assert len(harness.spawned) == 1, "a failed spawn must not wedge the cache stale forever"


def test_a_failing_inspection_does_not_poison_the_cache() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    harness.clock.now += 5.0
    harness.process_error = RuntimeError("process enumeration failed")
    harness.snapshot()

    harness.run_refresh()
    after_partial_failure = harness.snapshot()

    assert after_partial_failure["process_inspector"]["risk"] == {"call": 1}, (
        "the previous process snapshot is kept when only the process build fails"
    )
    assert after_partial_failure["threads"]["tracked_status"] == "tracked-2"

    harness.process_error = None
    harness.thread_error = RuntimeError("thread enumeration failed")
    harness.clock.now += 5.0
    harness.snapshot()
    harness.run_refresh()
    after_thread_failure = harness.snapshot()

    # The failed process build still consumed one probe call (call 2).
    assert after_thread_failure["process_inspector"]["risk"] == {"call": 3}
    assert after_thread_failure["threads"]["tracked_status"] == "tracked-2"


def test_total_refresh_failure_leaves_cache_stale_but_reschedulable() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    harness.clock.now += 5.0
    harness.process_error = RuntimeError("process")
    harness.thread_error = RuntimeError("thread")
    harness.snapshot()

    harness.run_refresh()
    harness.snapshot()

    assert len(harness.spawned) == 1, "an unrefreshed cache is still stale, so it reschedules"


def test_no_refresh_is_scheduled_during_shutdown() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    harness.clock.now += 60.0
    harness.shutting_down = True

    stale = harness.snapshot()

    assert stale["process_inspector"]["risk"] == {"call": 1}
    assert harness.spawned == []


def test_refresh_builds_snapshots_without_holding_the_cache_lock() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    harness.clock.now += 5.0
    harness.snapshot()
    gate = threading.Event()
    harness.process_gate = gate
    refresh = threading.Thread(target=harness.spawned[0]["target"], name="refresh-under-test")
    refresh.start()
    try:
        # A crash bundle must be able to take the shared lock while a refresh is
        # still inspecting processes (no deadlock between bundle and cache).
        acquired = harness.model.lock.acquire(timeout=2.0)
        assert acquired
        harness.model.lock.release()
    finally:
        gate.set()
        refresh.join(5.0)
    assert not refresh.is_alive()
    assert harness.snapshot()["process_inspector"]["risk"] == {"call": 2}


def test_cache_readers_wait_for_a_bundle_holding_the_shared_lock() -> None:
    harness = _HeavyHarness()
    harness.snapshot()
    done = threading.Event()

    def reader() -> None:
        harness.snapshot()
        done.set()

    with harness.model.lock:
        worker = threading.Thread(target=reader, name="snapshot-reader")
        worker.start()
        assert not done.wait(0.2), "the cache lock is the bundle serialization lock"
    assert done.wait(5.0)
    worker.join(5.0)
