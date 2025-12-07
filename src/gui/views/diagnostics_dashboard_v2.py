"""Diagnostics dashboard for StableNew V2."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
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

        ttk.Label(header, textvariable=self._memory_var).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self._bundle_var).pack(side=tk.RIGHT)

        job_frame = ttk.LabelFrame(self, text="Jobs & Metadata")
        job_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        job_frame.rowconfigure(0, weight=1)
        job_frame.columnconfigure(0, weight=1)

        self._job_tree = ttk.Treeview(
            job_frame,
            columns=("job_id", "status", "pids", "run_mode", "priority"),
            show="headings",
            height=5,
        )
        for column, label in [
            ("job_id", "Job ID"),
            ("status", "Status"),
            ("pids", "PIDs"),
            ("run_mode", "Run Mode"),
            ("priority", "Priority"),
        ]:
            self._job_tree.heading(column, text=label)
            self._job_tree.column(column, width=80, stretch=False)
        self._job_tree.column("job_id", width=200)
        self._job_tree.column("status", width=100)
        self._job_tree.column("pids", width=60)
        self._job_tree.column("run_mode", width=80)
        self._job_tree.column("priority", width=70)
        self._job_tree.grid(row=0, column=0, sticky="nsew")

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self._watchdog_text = self._build_text_widget(body, "Watchdog Events")
        self._cleanup_text = self._build_text_widget(body, "Cleanup History")
        self._containers_text = self._build_text_widget(body, "Containers")
        self._process_text = self._build_text_widget(body, "Processes")

        self._refresh_snapshot()

    def _build_text_widget(self, parent: ttk.Frame, title: str) -> tk.Text:
        frame = ttk.LabelFrame(parent, text=title)
        row = 0 if "Watchdog" in title or "Containers" in title else 1
        column = 0 if title in {"Watchdog Events", "Cleanup History"} else 1
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
        self._update_job_table(snapshot.get("jobs", []))
        self._update_watchdog(snapshot.get("watchdog_events", []))
        self._update_cleanup(snapshot.get("cleanup_history", []))
        self._update_containers(snapshot.get("containers", {}))
        self._update_processes()
        last_bundle = snapshot.get("last_bundle")
        reason = snapshot.get("last_bundle_reason")
        if last_bundle:
            self._bundle_var.set(f"Last Bundle: {Path(last_bundle).name} ({reason or 'unknown'})")
        else:
            self._bundle_var.set("Last Bundle: none")
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
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
            self._memory_var.set(
                f"Memory: {used:.1f}MB / {total:.1f}MB ({percent:.0f}%)"
            )
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
                    job.get("job_id", ""),
                    job.get("status", ""),
                    len(job.get("external_pids", [])),
                    job.get("run_mode", ""),
                    job.get("priority", ""),
                ),
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

    def _update_processes(self) -> None:
        lines = []
        for proc in iter_stablenew_like_processes():
            lines.append(format_process_brief(proc))
        self._replace_text(self._process_text, lines)

    def _replace_text(self, widget: tk.Text, lines: list[str]) -> None:
        widget.config(state=tk.NORMAL)
        widget.delete(1.0, tk.END)
        widget.insert(tk.END, "\n".join(lines[-20:]) + ("\n" if lines else ""))
        widget.config(state=tk.DISABLED)

    def _format_event_lines(self, events: list[dict[str, Any]], *, label: str = "watchdog") -> list[str]:
        result: list[str] = []
        for event in events[-5:]:
            ts = event.get("timestamp")
            ts_text = (
                datetime.utcfromtimestamp(ts).isoformat() + "Z" if isinstance(ts, (int, float)) else "n/a"
            )
            job_id = event.get("job_id") or "unknown"
            reason = event.get("reason") or label
            info = event.get("info") or {}
            result.append(f"{ts_text} | job={job_id} reason={reason} info={info}")
        return result
