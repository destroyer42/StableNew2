"""Unified Debug Hub panel for StableNew V2."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.gui.log_trace_panel_v2 import LogTracePanelV2
from src.gui.panels_v2.api_failure_visualizer_v2 import ApiFailureVisualizerV2
from src.gui.views.diagnostics_dashboard_v2 import DiagnosticsDashboardV2
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.utils import InMemoryLogHandler
from src.utils.diagnostics_bundle_v2 import DEFAULT_BUNDLE_DIR
from src.utils.process_inspector_v2 import format_process_brief, iter_stablenew_like_processes
from src.utils.system_info_v2 import collect_system_snapshot

logger = logging.getLogger(__name__)


class DebugHubPanelV2(tk.Toplevel):
    """A central, tabbed debugging hub that surfaces diagnostics from across StableNew."""

    MIN_WIDTH = 960
    MIN_HEIGHT = 640
    _active_instance: DebugHubPanelV2 | None = None

    @classmethod
    def open(
        cls,
        *,
        master: tk.Misc | None = None,
        controller: Any | None = None,
        app_state: Any | None = None,
        log_handler: InMemoryLogHandler | None = None,
    ) -> DebugHubPanelV2:
        """Create or focus the singleton debug hub."""
        if cls._active_instance and cls._active_instance.winfo_exists():
            cls._active_instance.lift()
            return cls._active_instance
        instance = cls(
            master=master, controller=controller, app_state=app_state, log_handler=log_handler
        )
        cls._active_instance = instance
        return instance

    def __init__(
        self,
        *,
        master: tk.Misc | None = None,
        controller: Any | None = None,
        app_state: Any | None = None,
        log_handler: InMemoryLogHandler | None = None,
    ) -> None:
        self._controller = controller
        self._app_state = app_state
        self._log_handler = log_handler
        super().__init__(master or self._resolve_master())

        self.title("Unified Debug Hub")
        self.geometry(f"{self.MIN_WIDTH}x{self.MIN_HEIGHT}")
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.protocol("WM_DELETE_WINDOW", self.close)

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.notebook = notebook

        self.pipeline_tab = _PipelineTab(notebook, controller=controller, app_state=app_state)
        notebook.add(self.pipeline_tab, text="Pipeline")

        self.prompt_tab = _PromptTab(notebook, controller=controller, app_state=app_state)
        notebook.add(self.prompt_tab, text="Prompts")

        self.api_tab = _ApiTab(notebook, log_handler=log_handler, controller=controller)
        notebook.add(self.api_tab, text="API")

        auto_scanner = getattr(controller, "process_auto_scanner", None)
        self.process_tab = _ProcessTab(notebook, auto_scanner=auto_scanner)
        notebook.add(self.process_tab, text="Processes")

        self.crash_tab = _CrashTab(notebook)
        notebook.add(self.crash_tab, text="Crash Reports")

        self.system_tab = _SystemTab(notebook)
        notebook.add(self.system_tab, text="System")

        self.bind("<Destroy>", self._on_destroy, add="+")

    def _resolve_master(self) -> tk.Misc:
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
        return root

    def _on_destroy(self, event: tk.Event | None = None) -> None:
        if DebugHubPanelV2._active_instance is self:
            DebugHubPanelV2._active_instance = None

    def close(self) -> None:
        """Close the debug hub."""
        self.destroy()
        DebugHubPanelV2._active_instance = None


class _PipelineTab(ttk.Frame):
    def __init__(
        self, master: tk.Misc, controller: Any | None = None, app_state: Any | None = None
    ) -> None:
        super().__init__(master)
        self.controller = controller
        self.app_state = app_state
        self._selected_job_id: str | None = None
        self._history_listener_registered = False
        self._pending_history_refresh = False
        self._job_value_map: dict[str, str] = {}
        self.bind("<Map>", self._on_map, add="+")

        action_bar = ttk.Frame(self)
        action_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(action_bar, text="Explain a job").pack(side=tk.LEFT)
        self._job_var = tk.StringVar(value="")
        self._job_combo = ttk.Combobox(
            action_bar, textvariable=self._job_var, state="readonly", width=30
        )
        self._job_combo.pack(side=tk.LEFT, padx=(4, 4))
        self._job_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_job_selected())
        self._explain_btn = ttk.Button(
            action_bar,
            text="Explain This Job",
            command=self._on_explain_job,
            state=tk.DISABLED,
        )
        self._explain_btn.pack(side=tk.LEFT)

        dashboard = DiagnosticsDashboardV2(self, controller=controller, app_state=app_state)
        dashboard.pack(fill=tk.BOTH, expand=True)

        if app_state and hasattr(app_state, "subscribe"):
            app_state.subscribe("history_items", self._on_history_updated)
            app_state.subscribe("queue_jobs", self._on_history_updated)
            app_state.subscribe("running_job", self._on_history_updated)
            self._history_listener_registered = True
            self._on_history_updated()

    def _on_history_updated(self, *_) -> None:
        if not self.winfo_exists():
            return
        self._pending_history_refresh = False
        combo = getattr(self, "_job_combo", None)
        explain_btn = getattr(self, "_explain_btn", None)
        job_var = getattr(self, "_job_var", None)
        if combo is None or explain_btn is None or job_var is None:
            return
        if not combo.winfo_exists():
            return
        values = self._build_job_choices()
        combo["values"] = values
        if not values:
            explain_btn.configure(state=tk.DISABLED)
            job_var.set("")
            self._selected_job_id = None
            return
        if self._selected_job_id is not None:
            for label, mapped_job_id in self._job_value_map.items():
                if mapped_job_id == self._selected_job_id:
                    job_var.set(label)
                    explain_btn.configure(state=tk.NORMAL)
                    return
        job_var.set(values[0])
        self._selected_job_id = self._job_value_map.get(values[0])
        explain_btn.configure(state=tk.NORMAL)

    def _build_job_choices(self) -> list[str]:
        choices: list[tuple[str, str]] = []
        seen: set[str] = set()

        def _add(job_id: str, label: str) -> None:
            if not job_id or job_id in seen:
                return
            seen.add(job_id)
            choices.append((label, job_id))

        running_job = getattr(self.app_state, "running_job", None)
        if running_job is not None and getattr(running_job, "job_id", None):
            _add(
                str(running_job.job_id),
                self._format_summary_label("RUNNING", running_job, str(running_job.job_id)),
            )

        for summary in list(getattr(self.app_state, "queue_jobs", []) or []):
            job_id = getattr(summary, "job_id", None)
            if not job_id:
                continue
            status = getattr(summary, "status", "QUEUED") or "QUEUED"
            _add(str(job_id), self._format_summary_label(str(status).upper(), summary, str(job_id)))

        history_items = list(getattr(self.app_state, "history_items", []) or [])
        for entry in history_items[:25]:
            job_id = getattr(entry, "job_id", None)
            if not job_id:
                continue
            status = getattr(getattr(entry, "status", None), "value", None) or getattr(entry, "status", "history")
            _add(str(job_id), self._format_history_label(str(status).upper(), entry, str(job_id)))

        self._job_value_map = {label: job_id for label, job_id in choices}
        return [label for label, _ in choices]

    @staticmethod
    def _format_summary_label(prefix: str, summary: Any, job_id: str) -> str:
        display = None
        getter = getattr(summary, "get_display_summary", None)
        if callable(getter):
            try:
                display = getter()
            except Exception:
                display = None
        if not display:
            pack_name = getattr(summary, "prompt_pack_name", None) or getattr(summary, "base_model", None)
            display = str(pack_name or job_id)
        return f"{prefix} | {display} | {job_id}"

    @staticmethod
    def _format_history_label(prefix: str, entry: Any, job_id: str) -> str:
        snapshot = getattr(entry, "snapshot", None)
        normalized = snapshot.get("normalized_job") if isinstance(snapshot, dict) else None
        pack_name = None
        if isinstance(normalized, dict):
            pack_name = normalized.get("prompt_pack_name") or normalized.get("pack_name")
            stages = normalized.get("stage_chain")
            stage_text = " -> ".join(str(stage) for stage in stages) if isinstance(stages, list) and stages else ""
        else:
            stage_text = ""
        payload_summary = getattr(entry, "payload_summary", None) or job_id
        display = str(pack_name or payload_summary)
        if stage_text:
            display = f"{display} | {stage_text}"
        return f"{prefix} | {display} | {job_id}"

    def _on_map(self, _event: tk.Event | None = None) -> None:
        if not self._pending_history_refresh:
            return
        self.after_idle(self._on_history_updated)

    def _on_job_selected(self) -> None:
        value = self._job_var.get()
        job_id = self._job_value_map.get(value)
        if job_id:
            self._selected_job_id = job_id
            self._explain_btn.configure(state=tk.NORMAL)
        else:
            self._selected_job_id = None
            self._explain_btn.configure(state=tk.DISABLED)

    def _on_explain_job(self) -> None:
        if not self._selected_job_id or not self.controller:
            return
        handler = getattr(self.controller, "explain_job", None)
        if callable(handler):
            try:
                handler(self._selected_job_id)
            except Exception:
                pass

    def destroy(self) -> None:
        if (
            self._history_listener_registered
            and self.app_state is not None
            and hasattr(self.app_state, "unsubscribe")
        ):
            try:
                self.app_state.unsubscribe("history_items", self._on_history_updated)
            except Exception:
                pass
            try:
                self.app_state.unsubscribe("queue_jobs", self._on_history_updated)
            except Exception:
                pass
            try:
                self.app_state.unsubscribe("running_job", self._on_history_updated)
            except Exception:
                pass
            self._history_listener_registered = False
        super().destroy()


class _PromptTab(ttk.Frame):
    REFRESH_INTERVAL_MS = 3000

    def __init__(
        self, master: tk.Misc, controller: Any | None = None, app_state: Any | None = None
    ) -> None:
        super().__init__(master)
        self._controller = controller
        self._app_state = app_state
        self._refresh_id: str | None = None

        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(header, text="Normalized job prompts").pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        columns = ("job_id", "prompt", "negative", "packs")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=8)
        for col, label in [
            ("job_id", "Job ID"),
            ("prompt", "Prompt"),
            ("negative", "Negative"),
            ("packs", "Packs"),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, anchor=tk.W, width=200)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.refresh()

    def refresh(self) -> None:
        jobs = self._get_jobs()
        self.tree.delete(*self.tree.get_children())
        for job in jobs:
            prompt, negative = self._extract_prompts(job)
            packs = self._format_packs(job)
            self.tree.insert("", "end", values=(job.job_id, prompt, negative, packs))
        self._schedule_refresh()

    def _refresh_on_timer(self) -> None:
        if not self.winfo_exists():
            return
        if not self.winfo_ismapped():
            self._schedule_refresh()
            return
        self.refresh()

    def _schedule_refresh(self) -> None:
        if self._refresh_id:
            try:
                self.after_cancel(self._refresh_id)
            except Exception:
                pass
        self._refresh_id = self.after(self.REFRESH_INTERVAL_MS, self._refresh_on_timer)

    def _get_jobs(self) -> list[NormalizedJobRecord]:
        getter = getattr(self._controller, "get_preview_jobs", None)
        if callable(getter):
            try:
                return list(getter())
            except Exception:
                pass
        if self._app_state is not None:
            return list(getattr(self._app_state, "preview_jobs", []))
        return []

    @staticmethod
    def _shorten(value: str | None, limit: int = 120) -> str:
        if not value:
            return ""
        text = value.strip()
        return text if len(text) <= limit else text[: limit - 3] + "..."

    def _extract_prompts(self, job: NormalizedJobRecord) -> tuple[str, str]:
        prompt_info = job.txt2img_prompt_info or job.img2img_prompt_info
        if prompt_info:
            return self._shorten(prompt_info.final_prompt), self._shorten(
                prompt_info.final_negative_prompt
            )
        config = job.config or {}
        if isinstance(config, dict):
            prompt = config.get("prompt", "")
            negative = config.get("negative_prompt", "")
        else:
            prompt = getattr(config, "prompt", "")
            negative = getattr(config, "negative_prompt", "")
        return self._shorten(prompt), self._shorten(negative)

    @staticmethod
    def _format_packs(job: NormalizedJobRecord) -> str:
        names = [usage.pack_name for usage in getattr(job, "pack_usage", []) if usage.pack_name]
        return ", ".join(names) if names else ""

    def destroy(self) -> None:
        if self._refresh_id:
            try:
                self.after_cancel(self._refresh_id)
            except Exception:
                pass
        super().destroy()


class _ApiTab(ttk.Frame):
    def __init__(
        self, master: tk.Misc, log_handler: InMemoryLogHandler | None, controller: Any | None
    ) -> None:
        super().__init__(master)
        if log_handler is None:
            ttk.Label(
                self,
                text="Log handler unavailable",
            ).pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
            return

        self.visualizer = ApiFailureVisualizerV2(self)
        self.visualizer.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        bundle_cmd = getattr(controller, "generate_diagnostics_bundle_manual", None)
        log_frame = ttk.Frame(self)
        log_frame.pack(fill=tk.BOTH, expand=True)
        panel = LogTracePanelV2(
            log_frame,
            log_handler=log_handler,
            on_generate_bundle=bundle_cmd,
            audience="trace",
        )
        panel.pack(fill=tk.BOTH, expand=True)


class _ProcessTab(ttk.Frame):
    REFRESH_INTERVAL_MS = 3000

    def __init__(self, master: tk.Misc, *, auto_scanner: Any | None = None) -> None:
        super().__init__(master)
        self._auto_scanner = auto_scanner
        self._status_refresh_id: str | None = None
        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(header, text="StableNew-like processes").pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)
        self._scanner_enabled_var = tk.BooleanVar(
            value=bool(getattr(auto_scanner, "enabled", False))
        )
        ttk.Checkbutton(
            header,
            text="Auto-scan strays",
            variable=self._scanner_enabled_var,
            command=self._toggle_scanner,
        ).pack(side=tk.RIGHT, padx=(4, 0))
        self._scanner_status_var = tk.StringVar(value="Auto-scanner unavailable")
        ttk.Label(header, textvariable=self._scanner_status_var).pack(side=tk.RIGHT, padx=(4, 0))
        self._interval_var = tk.DoubleVar(value=getattr(auto_scanner, "scan_interval", 30.0))
        tk.Spinbox(
            header,
            from_=5,
            to=300,
            increment=5,
            textvariable=self._interval_var,
            width=5,
            command=self._update_interval,
            justify=tk.CENTER,
        ).pack(side=tk.RIGHT, padx=(4, 0))

        self._text = tk.Text(self, wrap=tk.NONE, height=10)
        self._text.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._text.config(yscrollcommand=scrollbar.set, state=tk.DISABLED)

        self.refresh()
        self._update_scanner_status()

    def refresh(self) -> None:
        lines = [format_process_brief(proc) for proc in iter_stablenew_like_processes()]
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, "\n".join(lines))
        self._text.config(state=tk.DISABLED)

    def _toggle_scanner(self) -> None:
        if not self._auto_scanner:
            return
        self._auto_scanner.set_enabled(bool(self._scanner_enabled_var.get()))
        self._update_scanner_status()

    def _update_interval(self) -> None:
        if not self._auto_scanner:
            return
        self._auto_scanner.set_scan_interval(self._interval_var.get())
        self._update_scanner_status()

    def _update_scanner_status(self) -> None:
        if not self.winfo_exists():
            return
        if not self._auto_scanner:
            self._scanner_status_var.set("Auto-scanner unavailable")
        else:
            self._scanner_status_var.set(self._auto_scanner.get_status_text())
        self._status_refresh_id = self.after(self.REFRESH_INTERVAL_MS, self._update_scanner_status)

    def destroy(self) -> None:
        if self._status_refresh_id:
            try:
                self.after_cancel(self._status_refresh_id)
            except Exception:
                pass
            self._status_refresh_id = None
        super().destroy()


class _CrashTab(ttk.Frame):
    def __init__(self, master: tk.Misc, bundle_dir: Path | None = None) -> None:
        super().__init__(master)
        self._bundle_dir = bundle_dir or DEFAULT_BUNDLE_DIR
        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(header, text="Diagnostics bundles").pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        columns = ("name", "modified")
        self._tree = ttk.Treeview(self, columns=columns, show="headings", height=8)
        for key, label in [("name", "Name"), ("modified", "Modified")]:
            self._tree.heading(key, text=label)
            self._tree.column(key, anchor=tk.W, width=320)
        self._tree.pack(fill=tk.BOTH, expand=True)

        footer = ttk.Frame(self)
        footer.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(footer, text="Open folder", command=self._open_folder).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(footer, text="Open selected", command=self._open_selected).pack(side=tk.LEFT)

        self._paths: dict[str, Path] = {}
        self.refresh()

    def refresh(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._paths.clear()
        if not self._bundle_dir.exists():
            return
        entries = sorted(
            self._bundle_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for bundle in entries:
            modified = bundle.stat().st_mtime
            label = bundle.name
            node = self._tree.insert("", "end", values=(label, self._format_ts(modified)))
            self._paths[node] = bundle

    def _open_folder(self) -> None:
        _open_path(self._bundle_dir)

    def _open_selected(self) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        path = self._paths.get(selection[0])
        if path:
            _open_path(path)

    @staticmethod
    def _format_ts(timestamp: float) -> str:
        from datetime import datetime

        try:
            return datetime.fromtimestamp(timestamp).isoformat()
        except Exception:
            return str(timestamp)


class _SystemTab(ttk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(header, text="System snapshot").pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        self._text = tk.Text(self, wrap=tk.NONE, state=tk.DISABLED)
        self._text.pack(fill=tk.BOTH, expand=True)
        self.refresh()

    def refresh(self) -> None:
        snapshot = collect_system_snapshot()
        payload = json.dumps(snapshot, indent=2)
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, payload)
        self._text.config(state=tk.DISABLED)


def _open_path(path: Path) -> None:
    try:
        if path.is_dir():
            target = path
        elif path.exists():
            target = path
        else:
            return
        if sys.platform == "win32":
            os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as exc:
        logger.debug("Failed to open path %s: %s", path, exc)
