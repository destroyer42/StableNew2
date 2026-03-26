"""Read-only artifact metadata inspector dialog."""

from __future__ import annotations

import json
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import apply_toplevel_theme, style_text_widget


class ArtifactMetadataInspectorDialog(tk.Toplevel):
    """Modal dialog for inspecting normalized and raw metadata payloads."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        inspection_payload: dict[str, Any],
        on_refresh: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Artifact Metadata Inspector")
        self.transient(parent)
        self.grab_set()
        self.geometry("860x720")
        self.minsize(720, 560)
        apply_toplevel_theme(self)

        self._payload = dict(inspection_payload or {})
        self._on_refresh = on_refresh
        self._normalized_text: tk.Text | None = None
        self._generation_text: tk.Text | None = None
        self._review_text: tk.Text | None = None
        self._diagnostics_text: tk.Text | None = None
        self._raw_text: tk.Text | None = None

        self._build_ui()
        self._render_payload()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self._artifact_var = tk.StringVar(value="Artifact: n/a")
        ttk.Label(header, textvariable=self._artifact_var, style="Dark.TLabel").grid(row=0, column=0, sticky="w")

        actions = ttk.Frame(header)
        actions.grid(row=0, column=1, sticky="e")
        ttk.Button(actions, text="Copy Normalized Summary", command=self._copy_normalized_summary).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Copy Raw Metadata JSON", command=self._copy_raw_json).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Refresh", command=self._refresh_payload).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="left")

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self._normalized_text = self._add_tab(notebook, "Normalized Summary")
        self._generation_text = self._add_tab(notebook, "Generation Metadata")
        self._review_text = self._add_tab(notebook, "Portable Review Metadata")
        self._diagnostics_text = self._add_tab(notebook, "Source Diagnostics")
        self._raw_text = self._add_tab(notebook, "Raw Payload")

    def _add_tab(self, notebook: ttk.Notebook, title: str) -> tk.Text:
        frame = ttk.Frame(notebook, padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, wrap="word", state="disabled")
        style_text_widget(text, elevated=True)
        text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        notebook.add(frame, text=title)
        return text

    def _render_payload(self) -> None:
        artifact_path = str(self._payload.get("artifact_path") or "n/a")
        self._artifact_var.set(f"Artifact: {artifact_path}")

        normalized_generation = self._payload.get("normalized_generation_summary") or {}
        normalized_review = self._payload.get("normalized_review_summary") or {}
        diagnostics = self._payload.get("source_diagnostics") or {}

        normalized_text = self._format_json(
            {
                "artifact_path": artifact_path,
                "normalized_generation_summary": normalized_generation,
                "normalized_review_summary": normalized_review,
                "source_diagnostics": diagnostics,
            }
        )
        self._set_text(self._normalized_text, normalized_text)
        self._set_text(self._generation_text, self._format_json(normalized_generation))
        self._set_text(self._review_text, self._format_json(normalized_review))
        self._set_text(self._diagnostics_text, self._format_json(diagnostics))
        self._set_text(
            self._raw_text,
            self._format_json(
                {
                    "raw_embedded_payload": self._payload.get("raw_embedded_payload"),
                    "raw_embedded_review_payload": self._payload.get("raw_embedded_review_payload"),
                    "raw_sidecar_review_payload": self._payload.get("raw_sidecar_review_payload"),
                    "raw_internal_review_summary": self._payload.get("raw_internal_review_summary"),
                }
            ),
        )

    @staticmethod
    def _format_json(payload: Any) -> str:
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _set_text(widget: tk.Text | None, value: str) -> None:
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _copy_normalized_summary(self) -> None:
        normalized = {
            "artifact_path": self._payload.get("artifact_path"),
            "normalized_generation_summary": self._payload.get("normalized_generation_summary"),
            "normalized_review_summary": self._payload.get("normalized_review_summary"),
            "source_diagnostics": self._payload.get("source_diagnostics"),
        }
        self.clipboard_clear()
        self.clipboard_append(self._format_json(normalized))

    def _copy_raw_json(self) -> None:
        raw_payload = {
            "raw_embedded_payload": self._payload.get("raw_embedded_payload"),
            "raw_embedded_review_payload": self._payload.get("raw_embedded_review_payload"),
            "raw_sidecar_review_payload": self._payload.get("raw_sidecar_review_payload"),
            "raw_internal_review_summary": self._payload.get("raw_internal_review_summary"),
        }
        self.clipboard_clear()
        self.clipboard_append(self._format_json(raw_payload))

    def _refresh_payload(self) -> None:
        if self._on_refresh is None:
            return
        refreshed = self._on_refresh()
        if not isinstance(refreshed, dict):
            return
        self._payload = dict(refreshed)
        self._render_payload()