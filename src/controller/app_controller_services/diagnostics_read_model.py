"""Diagnostics read model: job explanations, diagnostics snapshots and the heavy cache.

``DiagnosticsReadModel`` builds the dictionaries the Debug Hub, the diagnostics
dashboard and the job-explanation panel consume.  It receives *narrow, explicit*
dependencies (``DiagnosticsSources``) as zero-argument getters; it never receives
the controller or the main window.  The getters are evaluated at call time, so
collaborators that the host replaces after construction (``job_service``,
``main_window`` ...) are always read fresh.

Ownership and threading:

* The heavy process/thread snapshots are expensive, so the read model owns a
  bounded cache of them (TTL ``DIAGNOSTICS_HEAVY_SNAPSHOT_TTL_SEC``).  A stale
  entry is refreshed by *one* tracked thread spawned through the host-provided
  ``spawn_tracked_thread``; the read model creates no thread of its own.
* ``lock`` guards the cache.  The host also uses it to serialize crash-bundle
  generation against cache stores, so there is a single synchronization object.
* ``get_diagnostics_snapshot`` reads the Tk-panel metric sections through the
  ``main_window`` getter on the calling thread.  Callers (the diagnostics
  dashboard) invoke it on the GUI thread; the background refresh only builds the
  process/thread sections and never touches a widget.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.utils.process_inspector_v2 import (
    collect_process_risk_snapshot,
    format_process_brief,
    iter_stablenew_like_processes,
)
from src.utils.thread_registry import get_thread_registry

DIAGNOSTICS_HEAVY_SNAPSHOT_TTL_SEC = 4.0


def _none() -> Any:
    return None


@dataclass(frozen=True)
class DiagnosticsSources:
    """Read-only getters the read model evaluates on every call."""

    job_service: Callable[[], Any]
    spawn_tracked_thread: Callable[..., Any]
    is_shutting_down: Callable[[], bool]
    protected_pids: Callable[[], Iterable[int]]
    latest_runtime_status: Callable[[], Any]
    history_entry: Callable[[str], Any]
    app_state: Callable[[], Any] = _none
    webui_process_manager: Callable[[], Any] = _none
    pipeline_controller: Callable[[], Any] = _none
    webui_connection_controller: Callable[[], Any] = _none
    process_auto_scanner: Callable[[], Any] = _none
    optional_dependency_snapshot: Callable[[], Any] = _none
    main_window: Callable[[], Any] = _none
    last_ui_heartbeat_ts: Callable[[], Any] = _none
    last_queue_activity_ts: Callable[[], Any] = _none
    last_runner_activity_ts: Callable[[], Any] = _none
    queue_projection_timing: Callable[[], Any] = _none
    projection_coordinator_metrics: Callable[[], Any] = _none
    projection_sink_metrics: Callable[[], Any] = _none
    last_bundle: Callable[[], Any] = _none
    last_bundle_reason: Callable[[], Any] = _none


def _enumerate_threads() -> list[threading.Thread]:
    return threading.enumerate()


def _current_frames() -> dict[int, Any]:
    return sys._current_frames()


@dataclass(frozen=True)
class DiagnosticsProbes:
    """Process and thread inspection seams (replaced by fakes in tests)."""

    collect_process_risk: Callable[[], Any] = collect_process_risk_snapshot
    iter_processes: Callable[[], Iterable[Any]] = iter_stablenew_like_processes
    format_process: Callable[[Any], str] = format_process_brief
    thread_registry: Callable[[], Any] = get_thread_registry
    list_threads: Callable[[], Iterable[Any]] = _enumerate_threads
    current_frames: Callable[[], Mapping[int, Any]] = _current_frames


class DiagnosticsReadModel:
    """Build diagnostics payloads from explicit sources; own the heavy-snapshot cache."""

    def __init__(
        self,
        sources: DiagnosticsSources,
        *,
        probes: DiagnosticsProbes | None = None,
        clock: Callable[[], float] = time.monotonic,
        heavy_ttl_sec: float = DIAGNOSTICS_HEAVY_SNAPSHOT_TTL_SEC,
    ) -> None:
        self._sources = sources
        self._probes = probes or DiagnosticsProbes()
        self._clock = clock
        self._heavy_ttl_sec = heavy_ttl_sec
        self._lock = threading.Lock()
        self._process_snapshot_cache: dict[str, Any] | None = None
        self._thread_snapshot_cache: dict[str, Any] | None = None
        self._heavy_snapshot_ts = 0.0
        self._heavy_refresh_in_progress = False

    @property
    def lock(self) -> threading.Lock:
        """Lock guarding the heavy-snapshot cache; also serializes crash bundles."""
        return self._lock

    # ------------------------------------------------------------------
    # Job explanation
    # ------------------------------------------------------------------

    def get_job_explanation_payload(self, job_id: str) -> dict[str, Any] | None:
        if not job_id:
            return None
        live_job = self._find_live_job(job_id)
        history_entry = self._sources.history_entry(job_id)
        normalized = _extract_normalized_snapshot(live_job=live_job, history_entry=history_entry)
        runtime_status = self._sources.latest_runtime_status()
        if getattr(runtime_status, "job_id", None) != job_id:
            runtime_status = None
        if not normalized and history_entry is None and live_job is None:
            return None

        status_value = _resolve_job_status_value(live_job=live_job, history_entry=history_entry)
        stage_flow = _resolve_stage_flow(normalized, runtime_status)
        return {
            "job_id": job_id,
            "display_label": _build_debug_job_label(job_id, normalized),
            "origin_text": _build_job_origin_text(
                job_id=job_id,
                normalized=normalized,
                live_job=live_job,
                history_entry=history_entry,
                runtime_status=runtime_status,
            ),
            "stage_flow": stage_flow,
            "stage_prompts": _build_job_stage_prompt_rows(
                normalized=normalized,
                stage_flow=stage_flow,
                runtime_status=runtime_status,
            ),
            "metadata": _build_job_metadata_payload(
                job_id=job_id,
                normalized=normalized,
                live_job=live_job,
                history_entry=history_entry,
                runtime_status=runtime_status,
                status_value=status_value,
            ),
        }

    def _find_live_job(self, job_id: str) -> Any | None:
        job_service = self._sources.job_service()
        job_queue = getattr(job_service, "job_queue", None)
        getter = getattr(job_queue, "get_job", None)
        if callable(getter):
            try:
                return getter(job_id)
            except Exception:  # noqa: BLE001 - a job-queue lookup failure means no live job, not a crash
                return None
        return None

    # ------------------------------------------------------------------
    # Diagnostics snapshot
    # ------------------------------------------------------------------

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        sources = self._sources
        job_service = sources.job_service()
        snapshot = job_service.get_diagnostics_snapshot() if job_service else {}
        data = dict(snapshot)
        manager = sources.webui_process_manager()
        if manager and hasattr(manager, "get_recent_output_tail"):
            try:
                data["webui_tail"] = manager.get_recent_output_tail()
            except Exception:  # noqa: BLE001 - best-effort WebUI tail; a collector failure must not break the snapshot
                data["webui_tail"] = None
        queue_timing = sources.queue_projection_timing()
        data["controller"] = {
            "last_ui_heartbeat_ts": sources.last_ui_heartbeat_ts(),
            "last_queue_activity_ts": sources.last_queue_activity_ts(),
            "last_runner_activity_ts": sources.last_runner_activity_ts(),
            "queue_projection_timing": (
                dict(queue_timing) if isinstance(queue_timing, Mapping) else None
            ),
            "projection_coordinator": sources.projection_coordinator_metrics(),
            "projection_sink": sources.projection_sink_metrics(),
        }
        pipeline_controller = sources.pipeline_controller()
        preview_timing_getter = getattr(
            pipeline_controller,
            "get_preview_build_timing_snapshot",
            None,
        )
        if callable(preview_timing_getter):
            try:
                data["pipeline_controller"] = {
                    "preview_build_timing": preview_timing_getter(),
                }
            except Exception:  # noqa: BLE001 - best-effort preview timing section; a collector failure must not break the snapshot
                data["pipeline_controller"] = None
        webui_connection = sources.webui_connection_controller()
        if webui_connection is None and pipeline_controller is not None:
            webui_connection = getattr(pipeline_controller, "_webui_connection", None)
        readiness_timing_getter = getattr(
            webui_connection,
            "get_last_connection_timing_snapshot",
            None,
        )
        readiness_state_getter = getattr(webui_connection, "get_state", None)
        if callable(readiness_timing_getter):
            try:
                readiness_state = None
                if callable(readiness_state_getter):
                    state = readiness_state_getter()
                    readiness_state = getattr(
                        state, "value", str(state) if state is not None else None
                    )
                data["webui_connection"] = {
                    "state": readiness_state,
                    "timing": readiness_timing_getter(),
                }
            except Exception:  # noqa: BLE001 - best-effort connection timing section; a collector failure must not break the snapshot
                data["webui_connection"] = None
        optional_dependencies = sources.optional_dependency_snapshot()
        if optional_dependencies is not None and hasattr(optional_dependencies, "to_dict"):
            try:
                data["optional_dependencies"] = optional_dependencies.to_dict()
            except Exception:  # noqa: BLE001 - best-effort optional-dependency section; a collector failure must not break the snapshot
                data["optional_dependencies"] = None
        self._collect_gui_panel_sections(data)
        data["app_state"] = self._build_app_state_snapshot()
        data["jobs"] = self._build_enriched_jobs(data.get("jobs"))
        process_snapshot, thread_snapshot = self._get_cached_heavy_snapshots()
        data["process_inspector"] = process_snapshot
        data["threads"] = thread_snapshot
        last_bundle = sources.last_bundle()
        data["last_bundle"] = str(last_bundle) if last_bundle else None
        data["last_bundle_reason"] = sources.last_bundle_reason()
        return data

    def _collect_gui_panel_sections(self, data: dict[str, Any]) -> None:
        """Read Tk panel metrics. Runs on the caller's (GUI) thread by design."""
        main_window = self._sources.main_window()
        pipeline_tab = getattr(main_window, "pipeline_tab", None)
        getter = getattr(pipeline_tab, "get_diagnostics_snapshot", None)
        if callable(getter):
            try:
                data["pipeline_tab"] = getter()
            except Exception:  # noqa: BLE001 - best-effort pipeline-tab panel section; a collector failure must not break the snapshot
                data["pipeline_tab"] = None
        log_trace_panel = getattr(main_window, "log_trace_panel_v2", None)
        log_trace_getter = getattr(log_trace_panel, "get_diagnostics_snapshot", None)
        if callable(log_trace_getter):
            try:
                data["log_trace_panel"] = log_trace_getter()
            except Exception:  # noqa: BLE001 - best-effort log-trace panel section; a collector failure must not break the snapshot
                data["log_trace_panel"] = None

    def _build_app_state_snapshot(self) -> dict[str, Any]:
        app_state = self._sources.app_state()
        running_job = getattr(app_state, "running_job", None)
        runtime_status = (
            getattr(app_state, "runtime_status", None) or self._sources.latest_runtime_status()
        )
        queue_jobs = list(getattr(app_state, "queue_jobs", []) or [])
        history_items = list(getattr(app_state, "history_items", []) or [])
        return {
            "running_job": _serialize_job_summary(running_job),
            "runtime_status": _serialize_runtime_status(runtime_status),
            "queue_job_count": len(queue_jobs),
            "history_count": len(history_items),
        }

    def _build_enriched_jobs(self, jobs: Any) -> list[dict[str, Any]]:
        if not isinstance(jobs, list):
            return []
        app_state = self._sources.app_state()
        queue_jobs = list(getattr(app_state, "queue_jobs", []) or [])
        running_job = getattr(app_state, "running_job", None)
        history_items = list(getattr(app_state, "history_items", []) or [])
        summary_index = {
            summary.job_id: summary
            for summary in ([running_job] if running_job is not None else []) + queue_jobs
            if getattr(summary, "job_id", None)
        }
        history_index = {
            getattr(entry, "job_id", None): entry
            for entry in history_items
            if getattr(entry, "job_id", None)
        }
        runtime_status = self._sources.latest_runtime_status()

        enriched: list[dict[str, Any]] = []
        for entry in jobs:
            if not isinstance(entry, dict):
                continue
            job_id = str(entry.get("job_id") or "")
            live_job = self._find_live_job(job_id)
            history_entry = history_index.get(job_id)
            normalized = _extract_normalized_snapshot(
                live_job=live_job,
                history_entry=history_entry,
            )
            summary = summary_index.get(job_id)
            display_label = (
                summary.get_display_summary()
                if summary is not None and hasattr(summary, "get_display_summary")
                else _build_debug_job_label(job_id, normalized)
            )
            stage_display = _format_job_stage_display(
                job_id=job_id,
                summary=summary,
                normalized=normalized,
                runtime_status=runtime_status,
                result_summary=entry.get("result_summary"),
            )
            diagnostics_text = _format_job_diagnostics_text(entry, history_entry)
            pids = [int(pid) for pid in entry.get("external_pids", []) if isinstance(pid, int)]
            enriched_entry = dict(entry)
            enriched_entry["display_label"] = display_label
            enriched_entry["stage_display"] = stage_display
            enriched_entry["pid_display"] = ", ".join(str(pid) for pid in pids) if pids else "none"
            enriched_entry["diagnostics_text"] = diagnostics_text
            enriched.append(enriched_entry)
        return enriched

    # ------------------------------------------------------------------
    # Process / thread inspection
    # ------------------------------------------------------------------

    def build_process_inspector_snapshot(self) -> dict[str, Any]:
        scanner = self._sources.process_auto_scanner()
        scanner_summary = getattr(scanner, "summary", None)
        summary_payload = None
        if scanner_summary is not None:
            summary_payload = {
                "timestamp": getattr(scanner_summary, "timestamp", None),
                "scanned": getattr(scanner_summary, "scanned", None),
                "killed": list(getattr(scanner_summary, "killed", []) or []),
            }
        try:
            risk = self._probes.collect_process_risk()
        except Exception:  # noqa: BLE001 - process-risk probe is best effort; absent data degrades to None
            risk = None
        try:
            process_lines = [
                self._probes.format_process(process) for process in self._probes.iter_processes()
            ]
        except Exception:  # noqa: BLE001 - process enumeration is best effort; absent data degrades to an empty list
            process_lines = []
        return {
            "scanner_status": scanner.get_status_text() if scanner is not None else None,
            "scanner_enabled": bool(getattr(scanner, "enabled", False))
            if scanner is not None
            else False,
            "scan_interval": float(getattr(scanner, "scan_interval", 0.0) or 0.0)
            if scanner is not None
            else 0.0,
            "protected_pids": sorted(int(pid) for pid in self._sources.protected_pids()),
            "summary": summary_payload,
            "risk": risk,
            "processes": process_lines,
        }

    def build_thread_snapshot(self) -> dict[str, Any]:
        tracked_status = None
        tracked_threads: dict[int, Any] = {}
        try:
            registry = self._probes.thread_registry()
            tracked_status = registry.dump_status()
            tracked_threads = {
                thread.thread.ident: thread
                for thread in registry.get_active_threads()
                if getattr(thread.thread, "ident", None) is not None
            }
        except Exception:  # noqa: BLE001 - thread-registry inspection is best effort; absent data degrades to None
            tracked_status = None
        try:
            frames = self._probes.current_frames()
        except Exception:  # noqa: BLE001 - frame inspection is best effort; absent data degrades to an empty mapping
            frames = {}
        threads: list[dict[str, Any]] = []
        for thread in self._probes.list_threads():
            ident = getattr(thread, "ident", None)
            frame = frames.get(ident) if ident is not None else None
            top_frame = None
            if frame is not None:
                try:
                    top_frame = {
                        "file": str(frame.f_code.co_filename),
                        "line": int(frame.f_lineno),
                        "function": str(frame.f_code.co_name),
                    }
                except Exception:  # noqa: BLE001 - per-thread frame formatting is best effort; a bad frame degrades to None
                    top_frame = None
            tracked = tracked_threads.get(ident) if ident is not None else None
            threads.append(
                {
                    "name": thread.name,
                    "ident": ident,
                    "daemon": bool(thread.daemon),
                    "alive": bool(thread.is_alive()),
                    "tracked": tracked is not None,
                    "purpose": getattr(tracked, "purpose", None) if tracked is not None else None,
                    "top_frame": top_frame,
                }
            )
        threads.sort(
            key=lambda item: (
                0 if item.get("name") == "MainThread" else 1,
                str(item.get("name") or ""),
            )
        )
        return {
            "thread_count": len(threads),
            "tracked_status": tracked_status,
            "threads": threads,
        }

    # ------------------------------------------------------------------
    # Heavy snapshot cache
    # ------------------------------------------------------------------

    def _get_cached_heavy_snapshots(self) -> tuple[dict[str, Any], dict[str, Any]]:
        process_snapshot: dict[str, Any] | None = None
        thread_snapshot: dict[str, Any] | None = None
        refresh_needed = False
        now = self._clock()
        with self._lock:
            if isinstance(self._process_snapshot_cache, dict):
                process_snapshot = deepcopy(self._process_snapshot_cache)
            if isinstance(self._thread_snapshot_cache, dict):
                thread_snapshot = deepcopy(self._thread_snapshot_cache)
            cache_ready = process_snapshot is not None and thread_snapshot is not None
            cache_stale = (
                cache_ready
                and self._heavy_snapshot_ts > 0.0
                and (now - self._heavy_snapshot_ts) >= self._heavy_ttl_sec
            )
            if (
                cache_stale
                and not self._heavy_refresh_in_progress
                and not self._sources.is_shutting_down()
            ):
                self._heavy_refresh_in_progress = True
                refresh_needed = True
        if process_snapshot is None or thread_snapshot is None:
            process_snapshot = self.build_process_inspector_snapshot()
            thread_snapshot = self.build_thread_snapshot()
            self._store_heavy_snapshots(process_snapshot, thread_snapshot)
            return process_snapshot, thread_snapshot
        if refresh_needed:
            self._schedule_heavy_refresh()
        return process_snapshot, thread_snapshot

    def _schedule_heavy_refresh(self) -> None:
        try:
            self._sources.spawn_tracked_thread(
                target=self._refresh_heavy_snapshots_async,
                name="DiagnosticsSnapshotRefresh",
                purpose="Refresh cached process and thread diagnostics snapshots",
            )
        except Exception:  # noqa: BLE001 - a failed refresh spawn must still release the admission flag
            with self._lock:
                self._heavy_refresh_in_progress = False

    def _refresh_heavy_snapshots_async(self) -> None:
        process_snapshot: dict[str, Any] | None = None
        thread_snapshot: dict[str, Any] | None = None
        try:
            process_snapshot = self.build_process_inspector_snapshot()
        except Exception:  # noqa: BLE001 - the async refresh keeps whatever half of the heavy snapshot it could build
            process_snapshot = None
        try:
            thread_snapshot = self.build_thread_snapshot()
        except Exception:  # noqa: BLE001 - the async refresh keeps whatever half of the heavy snapshot it could build
            thread_snapshot = None
        with self._lock:
            if process_snapshot is not None:
                self._process_snapshot_cache = deepcopy(process_snapshot)
            if thread_snapshot is not None:
                self._thread_snapshot_cache = deepcopy(thread_snapshot)
            if process_snapshot is not None or thread_snapshot is not None:
                self._heavy_snapshot_ts = self._clock()
            self._heavy_refresh_in_progress = False

    def _store_heavy_snapshots(
        self,
        process_snapshot: dict[str, Any],
        thread_snapshot: dict[str, Any],
    ) -> None:
        with self._lock:
            self._process_snapshot_cache = deepcopy(process_snapshot)
            self._thread_snapshot_cache = deepcopy(thread_snapshot)
            self._heavy_snapshot_ts = self._clock()
            self._heavy_refresh_in_progress = False


# ----------------------------------------------------------------------
# Pure projections
# ----------------------------------------------------------------------


def _extract_normalized_snapshot(
    *,
    live_job: Any | None,
    history_entry: Any | None,
) -> dict[str, Any]:
    candidates: list[Any] = []
    if live_job is not None:
        candidates.append(getattr(live_job, "_normalized_record", None))
        candidates.append(getattr(live_job, "snapshot", None))
    if history_entry is not None:
        candidates.append(getattr(history_entry, "snapshot", None))
    for candidate in candidates:
        if candidate is None:
            continue
        if hasattr(candidate, "to_queue_snapshot") and callable(candidate.to_queue_snapshot):
            try:
                snapshot = candidate.to_queue_snapshot()
                if isinstance(snapshot, dict):
                    return dict(snapshot)
            except Exception:  # noqa: BLE001, S112 - a malformed normalized-snapshot candidate is skipped, not fatal
                continue
        if isinstance(candidate, dict):
            normalized = (
                candidate.get("normalized_job") if "normalized_job" in candidate else candidate
            )
            if isinstance(normalized, dict):
                return dict(normalized)
    return {}


def _resolve_job_status_value(*, live_job: Any | None, history_entry: Any | None) -> str:
    status: Any = getattr(live_job, "status", None)
    if hasattr(status, "value"):
        return str(status.value)
    if status is not None:
        return str(status)
    history_status: Any = getattr(history_entry, "status", None)
    if hasattr(history_status, "value"):
        return str(history_status.value)
    if history_status is not None:
        return str(history_status)
    return ""


def _resolve_stage_flow(
    normalized: Mapping[str, Any],
    runtime_status: Any | None,
) -> list[str]:
    stage_chain = normalized.get("stage_chain") if isinstance(normalized, Mapping) else None
    if isinstance(stage_chain, list) and stage_chain:
        return [str(stage) for stage in stage_chain if stage]
    runtime_stage = getattr(runtime_status, "current_stage", None)
    if runtime_stage:
        return [str(runtime_stage)]
    return ["txt2img"]


def _build_debug_job_label(job_id: str, normalized: Mapping[str, Any]) -> str:
    pack_name = str(
        normalized.get("prompt_pack_name")
        or normalized.get("pack_name")
        or normalized.get("prompt_pack_id")
        or normalized.get("model")
        or job_id
    )
    row_index = normalized.get("prompt_pack_row_index")
    variant_index = normalized.get("variant_index")
    batch_index = normalized.get("batch_index")
    parts = [pack_name]
    if isinstance(row_index, int):
        parts.append(f"row={row_index + 1}")
    if isinstance(variant_index, int):
        parts.append(f"v={variant_index + 1}")
    if isinstance(batch_index, int):
        parts.append(f"b={batch_index + 1}")
    return " | ".join(parts + [job_id])


def _build_job_origin_text(
    *,
    job_id: str,
    normalized: Mapping[str, Any],
    live_job: Any | None,
    history_entry: Any | None,
    runtime_status: Any | None,
) -> str:
    parts: list[str] = [f"Job: {job_id}"]
    pack_usage = normalized.get("pack_usage") if isinstance(normalized, Mapping) else None
    if isinstance(pack_usage, list) and pack_usage:
        pack_labels = []
        for item in pack_usage:
            if isinstance(item, dict):
                name = item.get("pack_name") or item.get("pack_id")
                stage = item.get("used_for_stage")
                if name and stage:
                    pack_labels.append(f"{name} ({stage})")
                elif name:
                    pack_labels.append(str(name))
        if pack_labels:
            parts.append("Packs: " + ", ".join(pack_labels))
    elif normalized.get("prompt_pack_name"):
        parts.append(f"Pack: {normalized.get('prompt_pack_name')}")

    prompt_source = getattr(live_job, "prompt_source", None) or getattr(
        history_entry, "prompt_source", None
    )
    if prompt_source:
        parts.append(f"source={prompt_source}")
    run_mode = getattr(live_job, "run_mode", None) or getattr(history_entry, "run_mode", None)
    if run_mode:
        parts.append(f"run_mode={run_mode}")
    status_value = _resolve_job_status_value(live_job=live_job, history_entry=history_entry)
    if status_value:
        parts.append(f"status={status_value}")
    if runtime_status is not None and hasattr(runtime_status, "get_stage_display"):
        try:
            parts.append(f"runtime={runtime_status.get_stage_display()}")
        except Exception:  # noqa: BLE001, S110 - the runtime-stage suffix is optional enrichment of the origin text
            pass
    return " | ".join(parts)


def _build_job_stage_prompt_rows(
    *,
    normalized: Mapping[str, Any],
    stage_flow: list[str],
    runtime_status: Any | None,
) -> list[dict[str, str]]:
    def _prompt_info_for(stage_name: str) -> Mapping[str, Any]:
        key = f"{stage_name}_prompt_info"
        value = normalized.get(key)
        return value if isinstance(value, Mapping) else {}

    rows: list[dict[str, str]] = []
    runtime_stage = str(getattr(runtime_status, "current_stage", "") or "")
    for stage_name in stage_flow:
        info = _prompt_info_for(str(stage_name))
        prompt = str(info.get("final_prompt") or normalized.get("prompt") or "-")
        negative = str(
            info.get("final_negative_prompt") or normalized.get("negative_prompt") or "-"
        )
        global_terms = str(info.get("global_negative_terms") or "-")
        status = "current" if runtime_stage and runtime_stage == str(stage_name) else "available"
        rows.append(
            {
                "stage": str(stage_name),
                "prompt": prompt,
                "negative": negative,
                "global_terms": global_terms,
                "status": status,
            }
        )
    return rows


def _build_job_metadata_payload(
    *,
    job_id: str,
    normalized: Mapping[str, Any],
    live_job: Any | None,
    history_entry: Any | None,
    runtime_status: Any | None,
    status_value: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "job_id": job_id,
        "status": status_value,
        "prompt_pack_id": normalized.get("prompt_pack_id"),
        "prompt_pack_name": normalized.get("prompt_pack_name"),
        "row_index": normalized.get("prompt_pack_row_index"),
        "variant_index": normalized.get("variant_index"),
        "batch_index": normalized.get("batch_index"),
        "model": normalized.get("model"),
        "sampler": normalized.get("sampler"),
        "steps": normalized.get("steps"),
        "cfg_scale": normalized.get("cfg_scale"),
        "width": normalized.get("width"),
        "height": normalized.get("height"),
        "seed": normalized.get("seed"),
        "output_dir": normalized.get("output_dir"),
        "stage_chain": list(normalized.get("stage_chain") or []),
        "randomization_enabled": normalized.get("randomization_enabled"),
        "matrix_slot_values": normalized.get("matrix_slot_values"),
        "config_layers": normalized.get("config_layers"),
        "error_message": getattr(live_job, "error_message", None)
        or getattr(history_entry, "error_message", None),
    }
    result = getattr(live_job, "result", None) or getattr(history_entry, "result", None)
    if isinstance(result, dict):
        metadata["result"] = dict(result)
    if runtime_status is not None:
        metadata["runtime_status"] = {
            "current_stage": getattr(runtime_status, "current_stage", None),
            "stage_index": getattr(runtime_status, "stage_index", None),
            "total_stages": getattr(runtime_status, "total_stages", None),
            "progress": getattr(runtime_status, "progress", None),
            "eta_seconds": getattr(runtime_status, "eta_seconds", None),
            "actual_seed": getattr(runtime_status, "actual_seed", None),
            "current_step": getattr(runtime_status, "current_step", None),
            "total_steps": getattr(runtime_status, "total_steps", None),
            "stage_detail": getattr(runtime_status, "stage_detail", None),
        }
    return metadata


def _format_job_stage_display(
    *,
    job_id: str,
    summary: Any | None,
    normalized: Mapping[str, Any],
    runtime_status: Any | None,
    result_summary: Any,
) -> str:
    if (
        runtime_status is not None
        and getattr(runtime_status, "job_id", None) == job_id
        and hasattr(runtime_status, "get_stage_display")
    ):
        try:
            stage_text = str(runtime_status.get_stage_display())
            progress = getattr(runtime_status, "progress", None)
            if isinstance(progress, (int, float)):
                return f"{stage_text} ({int(float(progress) * 100)}%)"
            return stage_text
        except Exception:  # noqa: BLE001, S110 - a failing stage-display call falls back to the stage-chain projection below
            pass
    stage_chain = normalized.get("stage_chain") if isinstance(normalized, Mapping) else None
    if isinstance(stage_chain, list) and stage_chain:
        return " -> ".join(str(stage) for stage in stage_chain if stage)
    if summary is not None:
        stage_labels = getattr(summary, "stage_chain_labels", None)
        if isinstance(stage_labels, list) and stage_labels:
            return " -> ".join(str(stage) for stage in stage_labels if stage)
    if isinstance(result_summary, Mapping):
        primary_stage = result_summary.get("primary_stage")
        if primary_stage:
            return str(primary_stage)
    return "-"


def _format_job_diagnostics_text(entry: Mapping[str, Any], history_entry: Any | None) -> str:
    parts: list[str] = []
    result_summary = entry.get("result_summary")
    if isinstance(result_summary, Mapping):
        duration_ms = result_summary.get("duration_ms")
        if isinstance(duration_ms, (int, float)):
            parts.append(f"duration={float(duration_ms):.0f}ms")
        output_count = result_summary.get("output_count")
        if isinstance(output_count, int):
            parts.append(f"outputs={output_count}")
        error = result_summary.get("error")
        if error:
            parts.append(f"error={error}")
    retries = entry.get("retry_attempts")
    if isinstance(retries, list) and retries:
        parts.append(f"retries={len(retries)}")
    duration_ms = getattr(history_entry, "duration_ms", None)
    if not parts and isinstance(duration_ms, int):
        parts.append(f"duration={duration_ms}ms")
    return " | ".join(parts) if parts else "no diagnostics"


def _serialize_job_summary(summary: Any | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    display_label = None
    getter = getattr(summary, "get_display_summary", None)
    if callable(getter):
        try:
            display_label = getter()
        except Exception:  # noqa: BLE001 - a failing display-summary getter degrades to no label
            display_label = None
    return {
        "job_id": getattr(summary, "job_id", None),
        "display_label": display_label,
        "prompt_pack_name": getattr(summary, "prompt_pack_name", None),
        "stage_chain_labels": list(getattr(summary, "stage_chain_labels", []) or []),
        "status": getattr(summary, "status", None),
    }


def _serialize_runtime_status(status: Any | None) -> dict[str, Any] | None:
    if status is None:
        return None
    stage_display = None
    stage_label = getattr(status, "get_stage_display", None)
    if callable(stage_label):
        try:
            stage_display = stage_label()
        except Exception:  # noqa: BLE001 - a failing stage-display getter degrades to no label
            stage_display = None
    eta_display = None
    eta_getter = getattr(status, "get_eta_display", None)
    if callable(eta_getter):
        try:
            eta_display = eta_getter()
        except Exception:  # noqa: BLE001 - a failing eta-display getter degrades to no label
            eta_display = None
    progress = getattr(status, "progress", None)
    progress_pct = int(float(progress) * 100) if isinstance(progress, (int, float)) else None
    started_at = getattr(status, "started_at", None)
    return {
        "job_id": getattr(status, "job_id", None),
        "stage_display": stage_display,
        "progress_pct": progress_pct,
        "eta_display": eta_display,
        "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
        "stage_detail": getattr(status, "stage_detail", None),
    }
