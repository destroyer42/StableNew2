"""Modal that presents structured error envelopes to the user."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from src.utils.diagnostics_bundle_v2 import DEFAULT_BUNDLE_DIR
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope

logger = logging.getLogger(__name__)


class ErrorModalV2(tk.Toplevel):
    """Show a structured error report with remediation hints."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        envelope: UnifiedErrorEnvelope,
        bundle_dir: Path | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.envelope = envelope
        self._bundle_dir = Path(bundle_dir or DEFAULT_BUNDLE_DIR)
        self._on_close = on_close
        self.title("Run Failed (Structured Error Report)")
        self.resizable(False, False)
        self.configure(padx=16, pady=12)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

        header = ttk.Label(
            self,
            text="Structured Error Report",
            font=("TkDefaultFont", 12, "bold"),
        )
        header.grid(row=0, column=0, columnspan=2, pady=(0, 12))

        fields = [
            ("Error Type", envelope.error_type),
            ("Subsystem", envelope.subsystem),
            ("Stage", envelope.stage or "n/a"),
            ("Severity", envelope.severity),
            ("Message", envelope.message),
            ("Remediation", envelope.remediation or "n/a"),
        ]

        for idx, (label, value) in enumerate(fields, start=1):
            ttk.Label(self, text=f"{label}:", anchor="w").grid(
                row=idx, column=0, sticky="w", padx=(0, 4), pady=2
            )
            ttk.Label(self, text=str(value), anchor="w", wraplength=420).grid(
                row=idx, column=1, sticky="w", pady=2
            )

        context_frame = ttk.LabelFrame(self, text="Context", padding=8)
        context_frame.grid(
            row=len(fields) + 1,
            column=0,
            columnspan=2,
            pady=(12, 6),
            sticky="nsew",
        )
        context_widget = tk.Text(
            context_frame,
            height=4,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("TkDefaultFont", 9),
        )
        context_widget.pack(fill="both", expand=True)
        context_payload = self._format_context()
        if context_payload:
            context_widget.config(state=tk.NORMAL)
            context_widget.insert(tk.END, context_payload)
            context_widget.config(state=tk.DISABLED)

        stack_frame = ttk.LabelFrame(self, text="Stack Trace", padding=8)
        stack_frame.grid(
            row=len(fields) + 2,
            column=0,
            columnspan=2,
            pady=(0, 8),
            sticky="nsew",
        )
        stack_widget = tk.Text(
            stack_frame,
            height=10,
            wrap=tk.NONE,
            state=tk.NORMAL,
            font=("TkFixedFont", 9),
        )
        stack_widget.insert(tk.END, envelope.stack)
        stack_widget.config(state=tk.DISABLED)
        stack_widget.pack(fill="both", expand=True)

        button_frame = ttk.Frame(self)
        button_frame.grid(
            row=len(fields) + 3,
            column=0,
            columnspan=2,
            pady=(0, 4),
        )
        open_button = ttk.Button(
            button_frame,
            text="Open Crash Bundle Folder",
            command=self._open_bundle_folder,
        )
        open_button.pack(side="left", padx=(0, 8))
        close_button = ttk.Button(button_frame, text="Close", command=self._handle_close)
        close_button.pack(side="right")

        self.update_idletasks()
        self.lift()

    def _format_context(self) -> str:
        context = getattr(self.envelope, "context", None) or {}
        if not context:
            return "(No additional context)"
        parts = []
        for key, value in context.items():
            parts.append(f"{key}: {value}")
        return "\n".join(parts)

    def _open_bundle_folder(self) -> None:
        try:
            self._bundle_dir.mkdir(parents=True, exist_ok=True)
            path_str = str(self._bundle_dir)
            if sys.platform.startswith("win"):
                os.startfile(path_str)
            elif sys.platform == "darwin":
                subprocess.run(["open", path_str], check=False)
            else:
                subprocess.run(["xdg-open", path_str], check=False)
        except Exception as exc:
            logger.warning(
                "Unable to open diagnostics folder %s: %s",
                self._bundle_dir,
                exc,
            )

    def _handle_close(self) -> None:
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                logger.exception("Error running error modal close hook")
        self.destroy()
