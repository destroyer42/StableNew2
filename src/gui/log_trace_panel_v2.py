"""Trace and operator log panel for GUI V2."""

from __future__ import annotations

import json
import time
import tkinter as tk
from collections.abc import Callable, Iterable
from datetime import datetime
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import BACKGROUND_ELEVATED, TEXT_PRIMARY
from src.utils import InMemoryLogHandler
from src.utils.logger import normalize_log_message


class LogTracePanelV2(ttk.Frame):
    """Collapsible panel that shows recent log entries."""

    SLOW_REFRESH_THRESHOLD_MS = 25.0

    def __init__(
        self,
        master: tk.Misc,
        log_handler: InMemoryLogHandler,
        *args: Any,
        on_generate_bundle: Callable[[], None] | None = None,
        audience: str = "trace",
        **kwargs: Any,
    ):
        super().__init__(master, *args, **kwargs)
        self._log_handler = log_handler
        self._audience = audience
        self._expanded = tk.BooleanVar(value=False)
        self._level_filter = tk.StringVar(value="INFO+" if audience == "operator" else "ALL")
        self._subsystem_filter = tk.StringVar(value="")
        self._job_filter = tk.StringVar(value="")
        self._event_filter = tk.StringVar(value="")
        self._stage_filter = tk.StringVar(value="")
        self._auto_scroll = tk.BooleanVar(value=True)
        self._last_body_height = 0
        self._last_rendered_lines: tuple[tuple[str, str], ...] = ()
        self._last_log_version = -1
        self._last_filter_signature: tuple[str, str, str, str, str] | None = None
        self._render_entry_limit = 150 if audience == "operator" else 300
        self._deferred_refresh_id: str | None = None
        self._refresh_metrics: dict[str, int | float] = {
            "count": 0,
            "total_ms": 0.0,
            "max_ms": 0.0,
            "last_ms": 0.0,
            "slow_count": 0,
            "append_only_count": 0,
            "full_rebuild_count": 0,
            "skipped_collapsed_count": 0,
            "skipped_unchanged_count": 0,
        }

        header = ttk.Frame(self)
        header.pack(side=tk.TOP, fill=tk.X)

        self._title_label = ttk.Label(
            header,
            text="Operator Log" if audience == "operator" else "Trace Log",
        )
        self._title_label.pack(side=tk.LEFT, padx=(0, 8))

        self._toggle_btn = ttk.Button(
            header,
            text="Details v",
            width=12,
            command=self._on_toggle,
        )
        self._toggle_btn.pack(side=tk.LEFT)

        ttk.Label(header, text="Level:").pack(side=tk.LEFT, padx=(8, 2))
        self._level_combo = ttk.Combobox(
            header,
            textvariable=self._level_filter,
            values=["ALL", "INFO+", "WARN+", "ERROR"],
            state="readonly",
            width=8,
        )
        self._level_combo.pack(side=tk.LEFT)
        self._level_combo.bind("<<ComboboxSelected>>", lambda *_: self.refresh(force=True))

        if audience == "trace":
            ttk.Label(header, text="Subsystem:").pack(side=tk.LEFT, padx=(8, 2))
            self._subsystem_entry = ttk.Entry(
                header,
                textvariable=self._subsystem_filter,
                width=12,
            )
            self._subsystem_entry.pack(side=tk.LEFT)
            ttk.Label(header, text="Stage:").pack(side=tk.LEFT, padx=(8, 2))
            self._stage_entry = ttk.Entry(
                header,
                textvariable=self._stage_filter,
                width=10,
            )
            self._stage_entry.pack(side=tk.LEFT)
            ttk.Label(header, text="Event:").pack(side=tk.LEFT, padx=(8, 2))
            self._event_entry = ttk.Entry(
                header,
                textvariable=self._event_filter,
                width=16,
            )
            self._event_entry.pack(side=tk.LEFT)
            ttk.Label(header, text="Job ID:").pack(side=tk.LEFT, padx=(8, 2))
            self._job_entry = ttk.Entry(
                header,
                textvariable=self._job_filter,
                width=14,
            )
            self._job_entry.pack(side=tk.LEFT)
            self._subsystem_filter.trace_add("write", lambda *_: self.refresh(force=True))
            self._stage_filter.trace_add("write", lambda *_: self.refresh(force=True))
            self._event_filter.trace_add("write", lambda *_: self.refresh(force=True))
            self._job_filter.trace_add("write", lambda *_: self.refresh(force=True))

        self._scroll_check = ttk.Checkbutton(
            header,
            text="Auto-scroll",
            variable=self._auto_scroll,
        )
        self._scroll_check.pack(side=tk.LEFT, padx=(8, 0))

        self._bundle_button: ttk.Button | None = None
        if on_generate_bundle:
            self._bundle_button = ttk.Button(
                header,
                text="Crash Bundle",
                width=12,
                command=on_generate_bundle,
            )
            self._bundle_button.pack(side=tk.RIGHT, padx=(0, 8))

        self._body = ttk.Frame(self)

        self._log_text = tk.Text(
            self._body,
            height=6,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("TkDefaultFont", 9),
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            selectbackground="#3f6fd1",
            selectforeground=TEXT_PRIMARY,
            relief=tk.FLAT,
            borderwidth=0,
        )
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("DEBUG", foreground="#6f7d8c")
        self._log_text.tag_configure("INFO", foreground="#e6e8eb")
        self._log_text.tag_configure("WARNING", foreground="#ffb84d")
        self._log_text.tag_configure("ERROR", foreground="#ff6b6b")
        self._log_text.tag_configure("CRITICAL", foreground="#ff6b6b")

        scrollbar = ttk.Scrollbar(self._body, orient=tk.VERTICAL, command=self._log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=scrollbar.set)

        self.refresh()
        self._schedule_refresh()
        self._set_expanded(True, initial=True)

    def _set_expanded(self, expanded: bool, *, initial: bool = False) -> None:
        if expanded == self._expanded.get():
            return
        if expanded:
            self._body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self._toggle_btn.config(text="Details ^")
            self._body.update_idletasks()
            body_height = max(self._body.winfo_reqheight(), 0)
            self._last_body_height = body_height
            if not initial and body_height:
                self._adjust_window_height(body_height)
            if not initial:
                self.refresh(force=True)
        else:
            self._body.pack_forget()
            self._toggle_btn.config(text="Details v")
            if not initial and self._last_body_height:
                self._adjust_window_height(-self._last_body_height)
        self._expanded.set(expanded)

    def _adjust_window_height(self, delta: int) -> None:
        if delta == 0:
            return
        toplevel = self.winfo_toplevel()
        if toplevel is None:
            return
        toplevel.update_idletasks()
        geom = toplevel.geometry()
        if not geom:
            return
        parts = geom.split("+")
        size = parts[0]
        extra = parts[1:]
        if "x" not in size:
            return
        width_str, height_str = size.split("x", 1)
        try:
            width = int(width_str)
            height = int(height_str)
        except ValueError:
            return
        new_height = max(200, height + delta)
        new_geom = f"{width}x{new_height}"
        if extra:
            new_geom += "".join(f"+{part}" for part in extra)
        toplevel.geometry(new_geom)

    def _on_toggle(self) -> None:
        self._set_expanded(not self._expanded.get())

    def _current_filter_signature(self) -> tuple[str, str, str, str, str]:
        return (
            self._level_filter.get(),
            self._subsystem_filter.get(),
            self._job_filter.get(),
            self._event_filter.get(),
            self._stage_filter.get(),
        )

    def refresh(self, *, force: bool = False) -> None:
        start = time.perf_counter()
        if not force and not self._expanded.get():
            self._record_refresh_metric((time.perf_counter() - start) * 1000.0, skipped_collapsed=True)
            return
        filter_signature = self._current_filter_signature()
        log_version = self._log_handler.get_version()
        if (
            not force
            and log_version == self._last_log_version
            and filter_signature == self._last_filter_signature
        ):
            self._record_refresh_metric((time.perf_counter() - start) * 1000.0, skipped_unchanged=True)
            return
        entries = list(self._log_handler.get_entries())
        filtered = self._apply_filter(entries)
        if self._render_entry_limit > 0 and len(filtered) > self._render_entry_limit:
            filtered = filtered[-self._render_entry_limit :]

        lines: list[tuple[str, str]] = []
        for entry in filtered:
            level = str(entry.get("level", "")).upper()
            payload = self._get_payload(entry)
            base_message = normalize_log_message(str(entry.get("message", "") or ""))
            line = self._format_line(level=level, message=base_message, payload=payload, entry=entry)
            lines.append((level, line))

        rendered_lines = tuple(lines)
        if rendered_lines == self._last_rendered_lines:
            self._last_log_version = log_version
            self._last_filter_signature = filter_signature
            self._record_refresh_metric((time.perf_counter() - start) * 1000.0, skipped_unchanged=True)
            return
        previous_lines = self._last_rendered_lines
        append_only = (
            filter_signature == self._last_filter_signature
            and len(rendered_lines) >= len(previous_lines)
            and rendered_lines[: len(previous_lines)] == previous_lines
        )
        self._last_rendered_lines = rendered_lines
        self._last_log_version = log_version
        self._last_filter_signature = filter_signature

        current_yview = self._log_text.yview()
        self._log_text.config(state=tk.NORMAL)
        if append_only:
            for level, line in rendered_lines[len(previous_lines) :]:
                tag = level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "INFO"
                self._log_text.insert(tk.END, f"{line}\n", tag)
        else:
            self._log_text.delete(1.0, tk.END)
            for level, line in lines:
                tag = level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "INFO"
                self._log_text.insert(tk.END, f"{line}\n", tag)
        self._log_text.config(state=tk.DISABLED)

        if self._auto_scroll.get():
            self._log_text.see(tk.END)
        else:
            self._log_text.yview_moveto(current_yview[0])
        self._record_refresh_metric(
            (time.perf_counter() - start) * 1000.0,
            append_only=append_only,
        )

    def _record_refresh_metric(
        self,
        elapsed_ms: float,
        *,
        append_only: bool = False,
        skipped_collapsed: bool = False,
        skipped_unchanged: bool = False,
    ) -> None:
        self._refresh_metrics["count"] = int(self._refresh_metrics.get("count", 0) or 0) + 1
        self._refresh_metrics["total_ms"] = (
            float(self._refresh_metrics.get("total_ms", 0.0) or 0.0) + float(elapsed_ms)
        )
        self._refresh_metrics["last_ms"] = float(elapsed_ms)
        self._refresh_metrics["max_ms"] = max(
            float(self._refresh_metrics.get("max_ms", 0.0) or 0.0),
            float(elapsed_ms),
        )
        if elapsed_ms >= float(self.SLOW_REFRESH_THRESHOLD_MS):
            self._refresh_metrics["slow_count"] = (
                int(self._refresh_metrics.get("slow_count", 0) or 0) + 1
            )
        if append_only:
            self._refresh_metrics["append_only_count"] = (
                int(self._refresh_metrics.get("append_only_count", 0) or 0) + 1
            )
        elif not skipped_collapsed and not skipped_unchanged:
            self._refresh_metrics["full_rebuild_count"] = (
                int(self._refresh_metrics.get("full_rebuild_count", 0) or 0) + 1
            )
        if skipped_collapsed:
            self._refresh_metrics["skipped_collapsed_count"] = (
                int(self._refresh_metrics.get("skipped_collapsed_count", 0) or 0) + 1
            )
        if skipped_unchanged:
            self._refresh_metrics["skipped_unchanged_count"] = (
                int(self._refresh_metrics.get("skipped_unchanged_count", 0) or 0) + 1
            )

    def get_diagnostics_snapshot(self) -> dict[str, float | int | bool | str]:
        count = int(self._refresh_metrics.get("count", 0) or 0)
        total_ms = float(self._refresh_metrics.get("total_ms", 0.0) or 0.0)
        return {
            "audience": self._audience,
            "expanded": bool(self._expanded.get()),
            "line_count": len(self._last_rendered_lines),
            "render_limit": int(self._render_entry_limit),
            "count": count,
            "avg_ms": round(total_ms / count, 3) if count else 0.0,
            "max_ms": round(float(self._refresh_metrics.get("max_ms", 0.0) or 0.0), 3),
            "last_ms": round(float(self._refresh_metrics.get("last_ms", 0.0) or 0.0), 3),
            "slow_count": int(self._refresh_metrics.get("slow_count", 0) or 0),
            "append_only_count": int(self._refresh_metrics.get("append_only_count", 0) or 0),
            "full_rebuild_count": int(self._refresh_metrics.get("full_rebuild_count", 0) or 0),
            "skipped_collapsed_count": int(
                self._refresh_metrics.get("skipped_collapsed_count", 0) or 0
            ),
            "skipped_unchanged_count": int(
                self._refresh_metrics.get("skipped_unchanged_count", 0) or 0
            ),
            "slow_threshold_ms": float(self.SLOW_REFRESH_THRESHOLD_MS),
        }

    def schedule_refresh_soon(self, delay_ms: int = 125) -> None:
        """Coalesce bursty refresh requests into a single near-term repaint."""
        if self._deferred_refresh_id is not None:
            return

        def _run() -> None:
            self._deferred_refresh_id = None
            self.refresh()

        self._deferred_refresh_id = self.after(max(0, int(delay_ms)), _run)

    def _get_payload(self, entry: dict[str, object]) -> dict[str, Any] | None:
        payload = entry.get("payload")
        if isinstance(payload, dict):
            return payload
        message = str(entry.get("message", "") or "")
        if "|" not in message:
            return None
        _, _, payload_text = message.partition("|")
        payload_text = payload_text.strip()
        if not payload_text:
            return None
        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _format_line(
        self,
        *,
        level: str,
        message: str,
        payload: dict[str, Any] | None,
        entry: dict[str, object],
    ) -> str:
        badges = [level]
        if payload:
            subsystem = str(payload.get("subsystem") or "").strip()
            stage = str(payload.get("stage") or "").strip()
            event = str(payload.get("event") or "").strip()
            job_id = str(payload.get("job_id") or "").strip()
            if subsystem:
                badges.append(subsystem)
            if stage:
                badges.append(stage)
            if event and self._audience == "trace":
                badges.append(event)
            if job_id and self._audience == "trace":
                badges.append(f"job={job_id}")
        created = float(entry.get("created", 0.0) or 0.0)
        timestamp = self._format_timestamp(created)
        line = f"{timestamp} [{' | '.join(badges)}] {message}"
        envelope_summary = self._format_payload_summary(payload) if payload else None
        if envelope_summary:
            line += f" {envelope_summary}"
        repeat_count = int(entry.get("repeat_count", 1) or 1)
        if repeat_count > 1:
            first_created = float(entry.get("first_created", entry.get("created", 0.0)) or 0.0)
            last_created = float(entry.get("last_created", entry.get("created", 0.0)) or 0.0)
            line += f" [repeated {repeat_count}x over {max(0.0, last_created - first_created):.1f}s]"
        return line

    def _format_timestamp(self, created: float) -> str:
        if created <= 0:
            return "--:--:--.---"
        return datetime.fromtimestamp(created).strftime("%H:%M:%S.%f")[:-3]

    def _format_payload_summary(self, payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        envelope = payload.get("error_envelope") or payload.get("envelope")
        if not isinstance(envelope, dict):
            return None
        parts: list[str] = []
        error_type = envelope.get("error_type")
        if error_type:
            parts.append(str(error_type))
        subsystem = envelope.get("subsystem")
        if subsystem:
            parts.append(f"subsystem={subsystem}")
        stage = envelope.get("stage")
        if stage:
            parts.append(f"stage={str(stage).lower()}")
        job_id = payload.get("job_id")
        if job_id:
            parts.append(f"job={job_id}")
        severity = envelope.get("severity")
        if severity:
            parts.append(f"severity={severity}")
        if not parts:
            return None
        return f"[{', '.join(parts)}]"

    def _apply_filter(self, entries: Iterable[dict[str, object]]) -> list[dict[str, object]]:
        mode = self._level_filter.get()
        subsystem_target = self._subsystem_filter.get().strip().lower()
        job_target = self._job_filter.get().strip().lower()
        event_target = self._event_filter.get().strip().lower()
        stage_target = self._stage_filter.get().strip().lower()
        result: list[dict[str, object]] = []
        for entry in entries:
            level = str(entry.get("level", "")).upper()
            if mode == "ALL":
                pass
            elif mode == "INFO+" and level not in ("INFO", "WARNING", "ERROR", "CRITICAL"):
                continue
            elif mode == "WARN+" and level not in ("WARNING", "ERROR", "CRITICAL"):
                continue
            elif mode == "ERROR" and level not in ("ERROR", "CRITICAL"):
                continue
            payload = self._get_payload(entry) or {}
            if self._audience == "operator" and not self._is_operator_entry(level, payload, entry):
                continue
            subsystem = str(payload.get("subsystem", "") or "").lower()
            job_id = str(payload.get("job_id", "") or "").lower()
            event = str(payload.get("event", "") or "").lower()
            stage = str(payload.get("stage", "") or "").lower()
            if subsystem_target and subsystem_target not in subsystem:
                continue
            if job_target and job_target not in job_id:
                continue
            if event_target and event_target not in event:
                continue
            if stage_target and stage_target not in stage:
                continue
            result.append(entry)
        return result

    def _is_operator_entry(
        self,
        level: str,
        payload: dict[str, Any],
        entry: dict[str, object],
    ) -> bool:
        if level in ("ERROR", "CRITICAL", "WARNING"):
            return True
        if level != "INFO":
            return False
        event = str(payload.get("event", "") or "").lower()
        if event:
            return event not in {
                "config_snapshot",
                "payload_built",
                "payload_sent",
                "request_retry",
                "manifest_selection",
                "batch_detail",
                "memory_detail",
                "response_summary",
            }
        message = str(entry.get("message", "") or "").lower()
        noisy_tokens = (
            "payload",
            "config",
            "manifest will use",
            "querying webui",
            "received requested_model",
            "batch_size_debug",
            "canonical_result",
        )
        return not any(token in message for token in noisy_tokens)

    def _schedule_refresh(self) -> None:
        self.after(1000, self._do_refresh)

    def _do_refresh(self) -> None:
        self.refresh()
        self._schedule_refresh()

    def show(self) -> None:
        self._set_expanded(True)
