"""Trace log panel for GUI V2."""

from __future__ import annotations

import json
import tkinter as tk
from collections.abc import Callable, Iterable
from tkinter import ttk
from typing import Any

from src.utils import InMemoryLogHandler


class LogTracePanelV2(ttk.Frame):
    """Collapsible panel that shows recent log entries."""

    def __init__(
        self,
        master: tk.Misc,
        log_handler: InMemoryLogHandler,
        *args: object,
        on_generate_bundle: Callable[[], None] | None = None,
        **kwargs: object,
    ):
        super().__init__(master, *args, **kwargs)
        self._log_handler = log_handler
        self._expanded = tk.BooleanVar(value=False)
        self._level_filter = tk.StringVar(value="ALL")
        self._subsystem_filter = tk.StringVar(value="")
        self._job_filter = tk.StringVar(value="")
        self._auto_scroll = tk.BooleanVar(value=True)
        self._last_body_height = 0
        self._last_rendered_lines: tuple[str, ...] = ()

        header = ttk.Frame(self)
        header.pack(side=tk.TOP, fill=tk.X)

        self._toggle_btn = ttk.Button(
            header,
            text="Details ▼",
            width=12,
            command=self._on_toggle,
        )
        self._toggle_btn.pack(side=tk.LEFT)

        ttk.Label(header, text="Level:").pack(side=tk.LEFT, padx=(8, 2))
        self._level_combo = ttk.Combobox(
            header,
            textvariable=self._level_filter,
            values=["ALL", "DEBUG+", "INFO+", "WARN+", "ERROR"],
            state="readonly",
            width=8,
        )
        self._level_combo.pack(side=tk.LEFT)
        self._level_combo.bind("<<ComboboxSelected>>", lambda *_: self.refresh())

        ttk.Label(header, text="Subsystem:").pack(side=tk.LEFT, padx=(8, 2))
        self._subsystem_entry = ttk.Entry(
            header,
            textvariable=self._subsystem_filter,
            width=12,
        )
        self._subsystem_entry.pack(side=tk.LEFT)
        ttk.Label(header, text="Job ID:").pack(side=tk.LEFT, padx=(8, 2))
        self._job_entry = ttk.Entry(
            header,
            textvariable=self._job_filter,
            width=14,
        )
        self._job_entry.pack(side=tk.LEFT)
        self._subsystem_filter.trace_add("write", lambda *_: self.refresh())
        self._job_filter.trace_add("write", lambda *_: self.refresh())

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
        )
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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
            self._toggle_btn.config(text="Details ▲")
            self._body.update_idletasks()
            body_height = max(self._body.winfo_reqheight(), 0)
            self._last_body_height = body_height
            if not initial and body_height:
                self._adjust_window_height(body_height)
            if not initial:
                self.refresh()
        else:
            self._body.pack_forget()
            self._toggle_btn.config(text="Details ▼")
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

    def refresh(self) -> None:
        entries = list(self._log_handler.get_entries())
        filtered = self._apply_filter(entries)

        lines: list[str] = []
        for entry in filtered:
            level = str(entry.get("level", "")).upper()
            base_message = entry.get("message", "")
            payload = self._get_payload(entry)
            envelope_summary = self._format_payload_summary(payload) if payload else None
            line = f"[{level}] {base_message}"
            if envelope_summary:
                line += f" {envelope_summary}"
            elif payload:
                job_id = payload.get("job_id")
                subsystem = payload.get("subsystem")
                stage = payload.get("stage")
                extras: list[str] = []
                if job_id:
                    extras.append(f"job={job_id}")
                if subsystem:
                    extras.append(f"subsystem={subsystem}")
                if stage:
                    extras.append(f"stage={stage}")
                if extras:
                    line += " " + " ".join(extras)
            lines.append(line)

        rendered_lines = tuple(lines)
        if rendered_lines == self._last_rendered_lines:
            return
        self._last_rendered_lines = rendered_lines

        current_yview = self._log_text.yview()
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete(1.0, tk.END)
        for line in lines:
            self._log_text.insert(tk.END, f"{line}\n")
        self._log_text.config(state=tk.DISABLED)

        if self._auto_scroll.get():
            self._log_text.see(tk.END)
        else:
            self._log_text.yview_moveto(current_yview[0])

    def _get_payload(self, entry: dict[str, object]) -> dict[str, Any] | None:
        payload = entry.get("payload")
        if isinstance(payload, dict):
            return payload
        message = entry.get("message", "")
        if "|" not in message:
            return None
        _, _, payload_text = message.partition("|")
        payload_text = payload_text.strip()
        if not payload_text:
            return None
        try:
            return json.loads(payload_text)
        except json.JSONDecodeError:
            return None

    def _format_payload_summary(self, payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        envelope = payload.get("error_envelope") or payload.get("envelope")
        if not isinstance(envelope, dict):
            return None
        parts: list[str] = []
        error_type = envelope.get("error_type")
        if error_type:
            parts.append(error_type)
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
        result: list[dict[str, object]] = []
        for entry in entries:
            level = str(entry.get("level", "")).upper()
            if mode == "ALL":
                pass
            elif mode == "DEBUG+" and level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                continue
            elif mode == "INFO+" and level not in ("INFO", "WARNING", "ERROR", "CRITICAL"):
                continue
            elif mode == "WARN+" and level not in ("WARNING", "ERROR", "CRITICAL"):
                continue
            elif mode == "ERROR" and level not in ("ERROR", "CRITICAL"):
                continue
            payload = self._get_payload(entry) or {}
            subsystem = str(payload.get("subsystem", "") or "").lower()
            job_id = str(payload.get("job_id", "") or "").lower()
            if subsystem_target and subsystem_target not in subsystem:
                continue
            if job_target and job_target not in job_id:
                continue
            result.append(entry)
        return result

    def _schedule_refresh(self) -> None:
        """Schedule periodic refresh of log entries."""
        self.after(1000, self._do_refresh)

    def _do_refresh(self) -> None:
        """Perform refresh and schedule next one."""
        self.refresh()
        self._schedule_refresh()

    def show(self) -> None:
        """Ensure the log panel is expanded."""
        self._set_expanded(True)
