"""V2 History Panel (PR-CORE1-A3: NJR-only display).

Displays completed job history using NJR-derived DTOs.
History updates must run on the Tk main thread via AppController's dispatcher (e.g., `_run_in_gui_thread`).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import (
    SECONDARY_BUTTON_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
)
from src.pipeline.job_models_v2 import JobHistoryItemDTO


class HistoryPanelV2(ttk.Frame):
    """History panel displaying completed jobs (NJR-driven).

    Receives completed jobs from JobService callbacks.
    All display data derived from NJR snapshots via JobHistoryItemDTO.

    Features:
    - Display list of completed jobs
    - Show completion time and image count
    - Clear history button
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=(8, 8, 8, 8), **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._history_items: list[JobHistoryItemDTO] = []

        # Title row
        title_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        title_frame.pack(fill="x", pady=(0, 4))

        title = ttk.Label(title_frame, text="History", style=STATUS_STRONG_LABEL_STYLE)
        title.pack(side="left")

        self.count_label = ttk.Label(
            title_frame, text="(0 completed)", style=STATUS_STRONG_LABEL_STYLE
        )
        self.count_label.pack(side="left", padx=(8, 0))

        # History listbox
        list_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        list_frame.pack(fill="both", expand=True, pady=(4, 8))

        self.history_listbox = tk.Listbox(
            list_frame,
            height=6,
            selectmode=tk.SINGLE,
            exportselection=False,
            bg="#2a2a2a",
            fg="#e0e0e0",
            selectbackground="#4a90d9",
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#3a3a3a",
            highlightcolor="#4a90d9",
            relief="flat",
            font=("Segoe UI", 9),
        )
        self.history_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.history_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.history_listbox.configure(yscrollcommand=scrollbar.set)

        # Clear button
        button_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        button_frame.pack(fill="x")

        self.clear_button = ttk.Button(
            button_frame,
            text="Clear History",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_clear,
        )
        self.clear_button.pack(side="right")

    def append_history_item(self, dto: JobHistoryItemDTO) -> None:
        """Add a completed job to the history.

        PR-D: Core method for history panel updates via JobService callbacks.

        Args:
            dto: JobHistoryItemDTO with completed job info
        """
        self._history_items.append(dto)

        # PR-CORE-D: Format display text with PromptPack metadata
        timestamp = dto.completed_at.strftime("%H:%M:%S") if dto.completed_at else "??:??:??"

        # Calculate duration if both started_at and completed_at are available
        duration_text = ""
        if hasattr(dto, "started_at") and dto.started_at and dto.completed_at:
            try:
                duration_seconds = (dto.completed_at - dto.started_at).total_seconds()
                if duration_seconds < 60:
                    duration_text = f" ({int(duration_seconds)}s)"
                elif duration_seconds < 3600:
                    mins = int(duration_seconds // 60)
                    secs = int(duration_seconds % 60)
                    duration_text = f" ({mins}m{secs}s)"
                else:
                    hours = int(duration_seconds // 3600)
                    mins = int((duration_seconds % 3600) // 60)
                    duration_text = f" ({hours}h{mins}m)"
            except Exception:
                duration_text = ""

        # Extract metadata for richer display
        pack_name = getattr(dto, "prompt_pack_name", None)
        row_idx = getattr(dto, "prompt_pack_row_index", None)
        variant_idx = getattr(dto, "variant_index", None)
        batch_idx = getattr(dto, "batch_index", None)

        # PR-CORE-E: Extract config variant metadata
        config_variant_label = getattr(dto, "config_variant_label", None)
        config_variant_index = getattr(dto, "config_variant_index", None)

        # Build display text with metadata (Row number first)
        parts = [f"[{timestamp}{duration_text}]"]

        if pack_name:
            pack_text = ""
            # Row/prompt number FIRST
            if row_idx is not None:
                pack_text = f"R{row_idx + 1}: "
            
            pack_text += pack_name

            # PR-CORE-E: Add config variant label if present
            if config_variant_label and config_variant_label != "base":
                pack_text += f" [{config_variant_label}]"
            elif config_variant_index is not None and config_variant_index > 0:
                pack_text += f" [cfg_v{config_variant_index}]"

            if variant_idx is not None or batch_idx is not None:
                v_text = f"v{variant_idx + 1}" if variant_idx is not None else "v?"
                b_text = f"b{batch_idx + 1}" if batch_idx is not None else "b?"
                pack_text += f" [{v_text}/{b_text}]"
            parts.append(pack_text)
        else:
            parts.append(dto.label)

        parts.append(f"({dto.total_images} img{'s' if dto.total_images != 1 else ''})")

        display_text = " ".join(parts)

        self.history_listbox.insert(tk.END, display_text)

        # Update count
        count = len(self._history_items)
        self.count_label.configure(text=f"({count} completed)")

        # Auto-scroll to bottom
        self.history_listbox.see(tk.END)

    def clear_history(self) -> None:
        """Clear all history items."""
        self._history_items.clear()
        self.history_listbox.delete(0, tk.END)
        self.count_label.configure(text="(0 completed)")

    def _on_clear(self) -> None:
        """Handle clear button click."""
        if self.controller:
            method = getattr(self.controller, "on_history_clear_v2", None)
            if callable(method):
                method()
        else:
            self.clear_history()

    def get_history_items(self) -> list[JobHistoryItemDTO]:
        """Get all history items."""
        return list(self._history_items)


__all__ = ["HistoryPanelV2"]
