"""Diagnostics dashboard for StableNew V2."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.utils.process_inspector_v2 import format_process_brief, iter_stablenew_like_processes
from src.utils.system_info_v2 import collect_system_snapshot


class DiagnosticsDashboardV2(ttk.Frame):
    """Read-only diagnostics surface for jobs, containers, and watchdog activity."""

    REFRESH_INTERVAL_MS = 5000

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._refresh_after_id: str | None = None

        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 4))

        self._memory_var = tk.StringVar(value="Memory: --")
        self._bundle_var = tk.StringVar(value="Last Bundle: none")
        self._runtime_var = tk.StringVar(value="Running Job: idle")
        self._queue_state_var = tk.StringVar(value="Queue: --")
        self._activity_var = tk.StringVar(value="Activity: --")
        self._preview_timing_var = tk.StringVar(value="Preview Build: not captured")
        self._readiness_timing_var = tk.StringVar(value="WebUI Readiness: not captured")
        self._queue_timing_var = tk.StringVar(value="Queue Projection: not captured")

        ttk.Label(header, textvariable=self._memory_var).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self._bundle_var).pack(side=tk.RIGHT)

        runtime_frame = ttk.LabelFrame(self, text="Live Runtime")
        runtime_frame.pack(fill=tk.X, pady=(0, 4))
        runtime_frame.columnconfigure(0, weight=1)
        ttk.Label(runtime_frame, textvariable=self._runtime_var, anchor="w").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=8,
            pady=(4, 2),
        )
        ttk.Label(runtime_frame, textvariable=self._queue_state_var, anchor="w").grid(
            row=1,
            column=0,
            sticky="ew",
            padx=8,
            pady=2,
        )
        ttk.Label(runtime_frame, textvariable=self._activity_var, anchor="w").grid(
            row=2,
            column=0,
            sticky="ew",
            padx=8,
            pady=(2, 4),
        )

        timing_frame = ttk.LabelFrame(self, text="Timing Snapshots")
        timing_frame.pack(fill=tk.X, pady=(0, 4))
        timing_frame.columnconfigure(0, weight=1)
        ttk.Label(timing_frame, textvariable=self._preview_timing_var, anchor="w").grid(
            row=0,
            column=0,
            sticky="ew",
            padx=8,
            pady=(4, 2),
        )
        ttk.Label(timing_frame, textvariable=self._readiness_timing_var, anchor="w").grid(
            row=1,
            column=0,
            sticky="ew",
            padx=8,
            pady=2,
        )
        ttk.Label(timing_frame, textvariable=self._queue_timing_var, anchor="w").grid(
            row=2,
            column=0,
            sticky="ew",
            padx=8,
            pady=(2, 4),
        )

        job_frame = ttk.LabelFrame(self, text="Jobs & Metadata")
        job_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        job_frame.rowconfigure(0, weight=1)
        job_frame.columnconfigure(0, weight=1)

        self._job_tree = ttk.Treeview(
            job_frame,
            columns=("job", "status", "stage", "processes", "diagnostics"),
            show="headings",
            height=5,
        )
        for column, label in [
            ("job", "Job"),
            ("status", "Status"),
            ("stage", "Stage"),
            ("processes", "Processes"),
            ("diagnostics", "Diagnostics"),
        ]:
            self._job_tree.heading(column, text=label)
            self._job_tree.column(column, width=80, stretch=False)
        self._job_tree.column("job", width=260, stretch=True)
        self._job_tree.column("status", width=100)
        self._job_tree.column("stage", width=220, stretch=True)
        self._job_tree.column("processes", width=110)
        self._job_tree.column("diagnostics", width=240, stretch=True)
        self._job_tree.grid(row=0, column=0, sticky="nsew")

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)

        self._watchdog_text = self._build_text_widget(body, "Watchdog Events", row=0, column=0)
        self._cleanup_text = self._build_text_widget(body, "Cleanup History", row=0, column=1)
        self._containers_text = self._build_text_widget(body, "Containers", row=0, column=2)
        self._process_text = self._build_text_widget(body, "Processes", row=1, column=0)
        self._thread_text = self._build_text_widget(body, "Threads", row=1, column=1)
        self._ui_metrics_text = self._build_text_widget(body, "UI Pressure", row=1, column=2)

        import os

        self._is_test_mode = (
            bool(os.environ.get("PYTEST_CURRENT_TEST"))
            or os.environ.get("STABLENEW_TEST_MODE") == "1"
        )
        self._refresh_snapshot()

    def _build_text_widget(self, parent: ttk.Frame, title: str, *, row: int, column: int) -> tk.Text:
        frame = ttk.LabelFrame(parent, text=title)
        frame.grid(row=row, column=column, padx=4, pady=4, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        widget = tk.Text(frame, height=5, wrap=tk.WORD, state=tk.DISABLED)
        widget.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=widget.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        widget.configure(yscrollcommand=scrollbar.set)
        return widget

    def _refresh_snapshot(self) -> None:
        snapshot = self._get_snapshot()
        self._update_memory_label()
        self._update_runtime_snapshot(snapshot)
        self._update_timing_snapshots(snapshot)
        self._update_job_table(snapshot.get("jobs", []))
        self._update_watchdog(snapshot.get("watchdog_events", []))
        self._update_cleanup(snapshot.get("cleanup_history", []))
        self._update_containers(snapshot.get("containers", {}))
        self._update_processes(snapshot)
        self._update_threads(snapshot)
        self._update_ui_metrics(snapshot)
        last_bundle = snapshot.get("last_bundle")
        reason = snapshot.get("last_bundle_reason")
        if last_bundle:
            self._bundle_var.set(f"Last Bundle: {Path(last_bundle).name} ({reason or 'unknown'})")
        else:
            self._bundle_var.set("Last Bundle: none")
        if not getattr(self, "_is_test_mode", False):
            self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if getattr(self, "_is_test_mode", False):
            return
        self._cancel_refresh()
        self._refresh_after_id = self.after(self.REFRESH_INTERVAL_MS, self._refresh_snapshot)

    def _cancel_refresh(self) -> None:
        if self._refresh_after_id:
            try:
                self.after_cancel(self._refresh_after_id)
            except Exception:
                pass
        self._refresh_after_id = None

    def destroy(self) -> None:
        self._cancel_refresh()
        super().destroy()

    def _get_snapshot(self) -> dict[str, Any]:
        controller = self.controller
        getter = getattr(controller, "get_diagnostics_snapshot", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass
        return {}

    def _update_memory_label(self) -> None:
        info = collect_system_snapshot().get("memory")
        if info and info.get("total_mb"):
            used = info.get("used_mb", 0.0)
            total = info.get("total_mb", 0.0)
            percent = info.get("percent", 0.0)
            self._memory_var.set(f"Memory: {used:.1f}MB / {total:.1f}MB ({percent:.0f}%)")
        else:
            self._memory_var.set("Memory: unknown")

    def _update_job_table(self, jobs: list[dict[str, Any]]) -> None:
        for row in self._job_tree.get_children():
            self._job_tree.delete(row)
        for job in jobs:
            self._job_tree.insert(
                "",
                "end",
                values=(
                    job.get("display_label", job.get("job_id", "")),
                    job.get("status", ""),
                    job.get("stage_display", "-"),
                    job.get("pid_display", "none"),
                    job.get("diagnostics_text", "no diagnostics"),
                ),
            )

    def _update_runtime_snapshot(self, snapshot: dict[str, Any]) -> None:
        app_state = snapshot.get("app_state")
        app_state = app_state if isinstance(app_state, dict) else {}
        queue = snapshot.get("queue")
        queue = queue if isinstance(queue, dict) else {}
        controller = snapshot.get("controller")
        controller = controller if isinstance(controller, dict) else {}

        running_job = app_state.get("running_job") if isinstance(app_state.get("running_job"), dict) else {}
        runtime_status = (
            app_state.get("runtime_status") if isinstance(app_state.get("runtime_status"), dict) else {}
        )
        display_label = running_job.get("display_label") or "idle"
        if runtime_status:
            stage = runtime_status.get("stage_display") or "stage unknown"
            progress = runtime_status.get("progress_pct")
            eta = runtime_status.get("eta_display") or "ETA unknown"
            progress_text = f" | {progress}%" if isinstance(progress, int) else ""
            self._runtime_var.set(f"Running Job: {display_label} | {stage}{progress_text} | {eta}")
        else:
            self._runtime_var.set(f"Running Job: {display_label}")

        runner_running = "on" if queue.get("runner_running") else "off"
        paused = "yes" if queue.get("paused") else "no"
        queued_count = len(queue.get("queued_job_ids") or []) if isinstance(queue.get("queued_job_ids"), list) else 0
        total_count = int(queue.get("job_count", 0) or 0)
        current_job = queue.get("current_job_id") or "none"
        self._queue_state_var.set(
            f"Queue: runner={runner_running} | paused={paused} | queued={queued_count} | total={total_count} | current={current_job}"
        )
        self._activity_var.set(
            "Activity: "
            + " | ".join(
                [
                    f"ui={self._format_age(controller.get('last_ui_heartbeat_ts'))}",
                    f"queue={self._format_age(controller.get('last_queue_activity_ts'))}",
                    f"runner={self._format_age(controller.get('last_runner_activity_ts'))}",
                ]
            )
        )

    def _update_timing_snapshots(self, snapshot: dict[str, Any]) -> None:
        controller = snapshot.get("controller")
        controller = controller if isinstance(controller, dict) else {}
        pipeline_controller = snapshot.get("pipeline_controller")
        pipeline_controller = pipeline_controller if isinstance(pipeline_controller, dict) else {}
        webui_connection = snapshot.get("webui_connection")
        webui_connection = webui_connection if isinstance(webui_connection, dict) else {}

        self._preview_timing_var.set(
            self._format_preview_timing(pipeline_controller.get("preview_build_timing"))
        )
        self._readiness_timing_var.set(
            self._format_readiness_timing(
                webui_connection.get("state"),
                webui_connection.get("timing"),
            )
        )
        self._queue_timing_var.set(
            self._format_queue_timing(controller.get("queue_projection_timing"))
        )

    def _update_watchdog(self, events: list[dict[str, Any]]) -> None:
        lines = self._format_event_lines(events)
        self._replace_text(self._watchdog_text, lines)

    def _update_cleanup(self, events: list[dict[str, Any]]) -> None:
        lines = self._format_event_lines(events, label="cleanup")
        self._replace_text(self._cleanup_text, lines)

    def _update_containers(self, containers: dict[str, dict[str, Any]]) -> None:
        lines = []
        for job_id, info in containers.items():
            lines.append(f"job={job_id}: {info.get('container_type') or 'container'}")
            lines.append(f"  config={info.get('config')}")
        self._replace_text(self._containers_text, lines)

    def _update_processes(self, snapshot: dict[str, Any]) -> None:
        lines = []
        process_snapshot = snapshot.get("process_inspector")
        process_snapshot = process_snapshot if isinstance(process_snapshot, dict) else {}
        risk = process_snapshot.get("risk") if isinstance(process_snapshot.get("risk"), dict) else {}
        if risk:
            lines.append(
                "risk="
                + str(risk.get("status") or "unknown")
                + f" | processes={int(risk.get('stablenew_like_count', 0) or 0)}"
                + f" | main={int(risk.get('main_process_count', 0) or 0)}"
                + f" | webui={int(risk.get('webui_process_count', 0) or 0)}"
            )
            suspicious = risk.get("suspicious_processes")
            if isinstance(suspicious, list):
                for proc in suspicious[:5]:
                    if not isinstance(proc, dict):
                        continue
                    lines.append(
                        "suspicious pid="
                        + str(proc.get("pid"))
                        + f" rss={proc.get('rss_mb')}MB"
                        + f" reasons={','.join(str(reason) for reason in proc.get('reasons', []))}"
                    )
        scanner_status = process_snapshot.get("scanner_status")
        if scanner_status:
            lines.append(f"scanner={scanner_status}")
        protected_pids = process_snapshot.get("protected_pids")
        if isinstance(protected_pids, list) and protected_pids:
            lines.append("protected_pids=" + ", ".join(str(pid) for pid in protected_pids[:10]))
        for proc in iter_stablenew_like_processes():
            lines.append(format_process_brief(proc))
        self._replace_text(self._process_text, lines)

    def _update_threads(self, snapshot: dict[str, Any]) -> None:
        thread_snapshot = snapshot.get("threads")
        thread_snapshot = thread_snapshot if isinstance(thread_snapshot, dict) else {}
        lines: list[str] = []
        thread_count = thread_snapshot.get("thread_count")
        if isinstance(thread_count, int):
            lines.append(f"threads={thread_count}")
        tracked_status = thread_snapshot.get("tracked_status")
        if tracked_status:
            lines.extend(str(tracked_status).splitlines()[:8])
        threads = thread_snapshot.get("threads")
        if isinstance(threads, list):
            for thread in threads[:12]:
                if not isinstance(thread, dict):
                    continue
                top_frame = thread.get("top_frame") if isinstance(thread.get("top_frame"), dict) else {}
                location = ""
                if top_frame:
                    file_name = Path(str(top_frame.get("file") or "")).name
                    line = top_frame.get("line")
                    function = top_frame.get("function") or "?"
                    location = f" | {file_name}:{line} {function}"
                tracked = "tracked" if thread.get("tracked") else "untracked"
                daemon = "daemon" if thread.get("daemon") else "normal"
                lines.append(
                    f"{thread.get('name') or 'thread'} | id={thread.get('ident')} | {tracked} | {daemon}{location}"
                )
        self._replace_text(self._thread_text, lines)

    def _update_ui_metrics(self, snapshot: dict[str, Any]) -> None:
        lines: list[str] = []
        pipeline_tab = snapshot.get("pipeline_tab")
        pipeline_tab = pipeline_tab if isinstance(pipeline_tab, dict) else {}
        hot_surface = pipeline_tab.get("hot_surface_scheduler")
        if isinstance(hot_surface, dict):
            pending = hot_surface.get("dirty_pending") if isinstance(hot_surface.get("dirty_pending"), list) else []
            lines.append(
                "hot-surface"
                + f" | avg={hot_surface.get('avg_ms', 0.0)}ms"
                + f" | max={hot_surface.get('max_ms', 0.0)}ms"
                + f" | slow={hot_surface.get('slow_count', 0)}"
                + (f" | pending={','.join(str(item) for item in pending)}" if pending else "")
            )
        callback_metrics = pipeline_tab.get("callback_metrics")
        if isinstance(callback_metrics, dict):
            sorted_callbacks = sorted(
                (
                    (name, metrics)
                    for name, metrics in callback_metrics.items()
                    if isinstance(metrics, dict)
                ),
                key=lambda item: float(item[1].get("max_ms", 0.0) or 0.0),
                reverse=True,
            )
            for name, metrics in sorted_callbacks[:4]:
                lines.append(
                    f"callback {name} | avg={metrics.get('avg_ms', 0.0)}ms | max={metrics.get('max_ms', 0.0)}ms | slow={metrics.get('slow_count', 0)}"
                )
        for panel_name in ("queue_panel", "history_panel", "preview_panel"):
            panel_snapshot = pipeline_tab.get(panel_name)
            if not isinstance(panel_snapshot, dict):
                continue
            refresh_metrics = panel_snapshot.get("refresh_metrics")
            if not isinstance(refresh_metrics, dict) or not refresh_metrics:
                continue
            slowest = max(
                (
                    (metric_name, metric_payload)
                    for metric_name, metric_payload in refresh_metrics.items()
                    if isinstance(metric_payload, dict)
                ),
                key=lambda item: float(item[1].get("max_ms", 0.0) or 0.0),
                default=None,
            )
            if slowest is None:
                continue
            metric_name, metric_payload = slowest
            lines.append(
                f"{panel_name} {metric_name} | avg={metric_payload.get('avg_ms', 0.0)}ms | max={metric_payload.get('max_ms', 0.0)}ms | slow={metric_payload.get('slow_count', 0)}"
            )
        running_panel = pipeline_tab.get("running_job_panel")
        if isinstance(running_panel, dict):
            lines.append(
                "running panel"
                + f" | avg={running_panel.get('avg_ms', 0.0)}ms"
                + f" | max={running_panel.get('max_ms', 0.0)}ms"
                + f" | skips={running_panel.get('skipped_count', 0)}"
                + f" | timeline_clears={running_panel.get('timeline_clear_count', 0)}"
            )
        log_trace_panel = snapshot.get("log_trace_panel")
        if isinstance(log_trace_panel, dict):
            lines.append(
                f"log {log_trace_panel.get('audience', 'trace')}"
                + f" | avg={log_trace_panel.get('avg_ms', 0.0)}ms"
                + f" | max={log_trace_panel.get('max_ms', 0.0)}ms"
                + f" | append={log_trace_panel.get('append_only_count', 0)}"
                + f" | rebuild={log_trace_panel.get('full_rebuild_count', 0)}"
            )
        self._replace_text(self._ui_metrics_text, lines)

    def _replace_text(self, widget: tk.Text, lines: list[str]) -> None:
        widget.config(state=tk.NORMAL)
        widget.delete(1.0, tk.END)
        rendered = lines[-20:] if lines else ["No diagnostics recorded."]
        widget.insert(tk.END, "\n".join(rendered) + "\n")
        widget.config(state=tk.DISABLED)

    def _format_preview_timing(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return "Preview Build: not captured"
        parts = [self._format_ms(payload.get("elapsed_ms"))]
        source = payload.get("source")
        if source:
            parts.append(f"source={source}")
        parts.append(f"jobs={int(payload.get('job_count', 0) or 0)}")
        parts.append(f"packs={int(payload.get('pack_entry_count', 0) or 0)}")
        error = payload.get("error")
        if error:
            parts.append(f"error={error}")
        return "Preview Build: " + " | ".join(parts)

    def _format_readiness_timing(self, state: Any, payload: Any) -> str:
        if not isinstance(payload, dict):
            return "WebUI Readiness: not captured"
        parts: list[str] = []
        if state:
            parts.append(str(state))
        parts.append(self._format_ms(payload.get("total_elapsed_ms")))
        parts.append(f"retries={int(payload.get('retry_attempts_used', 0) or 0)}")
        parts.append(
            f"autostart={'yes' if payload.get('autostart_invoked') else 'no'}"
        )
        error = payload.get("error")
        if error:
            parts.append(f"error={error}")
        return "WebUI Readiness: " + " | ".join(parts)

    def _format_queue_timing(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return "Queue Projection: not captured"
        parts = [self._format_ms(payload.get("elapsed_ms"))]
        parts.append(f"jobs={int(payload.get('job_count', 0) or 0)}")
        parts.append(f"summaries={int(payload.get('summary_count', 0) or 0)}")
        parts.append(f"fallback={int(payload.get('fallback_count', 0) or 0)}")
        return "Queue Projection: " + " | ".join(parts)

    @staticmethod
    def _format_ms(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{float(value):.1f}ms"
        return "--"

    def _format_event_lines(
        self, events: list[dict[str, Any]], *, label: str = "watchdog"
    ) -> list[str]:
        result: list[str] = []
        for event in events[-5:]:
            ts = event.get("timestamp")
            ts_text = (
                datetime.utcfromtimestamp(ts).isoformat() + "Z"
                if isinstance(ts, (int, float))
                else "n/a"
            )
            job_id = event.get("job_id") or "unknown"
            reason = event.get("reason") or label
            info = event.get("info") or {}
            result.append(f"{ts_text} | job={job_id} reason={reason} info={info}")
        return result

    @staticmethod
    def _format_age(timestamp: Any) -> str:
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            age = max(0.0, datetime.utcnow().timestamp() - float(timestamp))
            return f"{age:.1f}s ago"
        return "n/a"
