"""Compact job history renderer for the Pipeline tab."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.gui import theme_v2 as theme_mod
from src.queue.job_history_store import JobHistoryEntry


class JobHistoryPanelV2(ttk.Frame):
    """Show recent job history entries (completion timestamps, packs, duration, output)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        folder_opener: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        style_name = theme_mod.SURFACE_FRAME_STYLE
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._folder_opener = folder_opener or self._default_open_folder
        self._entries: dict[str, JobHistoryEntry] = {}
        self._item_to_job: dict[str, str] = {}
        self._selected_job_id: str | None = None
        self._tooltip: tk.Toplevel | None = None

        header_style = theme_mod.STATUS_STRONG_LABEL_STYLE
        ttk.Label(self, text="Job History", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        action_bar = ttk.Frame(self, style=style_name)
        action_bar.pack(fill=tk.X, pady=(0, 4))
        self.refresh_btn = ttk.Button(action_bar, text="Refresh History", command=self._on_refresh)
        self.refresh_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self.open_btn = ttk.Button(
            action_bar,
            text="Open Output Folder",
            command=self._on_open_folder,
            state=tk.DISABLED,
        )
        self.open_btn.pack(side=tk.LEFT)
        self.replay_btn = ttk.Button(
            action_bar,
            text="Replay Job",
            command=self._on_replay_job,
            state=tk.DISABLED,
        )
        self.replay_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.explain_btn = ttk.Button(
            action_bar,
            text="Explain Job",
            command=self._on_explain_job,
            state=tk.DISABLED,
        )
        self.explain_btn.pack(side=tk.LEFT, padx=(4, 0))

        # D-GUI-003: Enhanced columns with row/variant/batch info
        columns = ("time", "status", "model", "pack", "row", "v", "b", "duration", "seed", "images", "output")
        headings = {
            "time": "Completed",
            "status": "Status",
            "model": "Model",
            "pack": "Pack Name",
            "row": "Row",
            "v": "V",
            "b": "B",
            "duration": "Duration",
            "seed": "Seed",
            "images": "Images",
            "output": "Output Folder",
        }
        
        # D-GUI-003: Add container frame with scrollbar
        tree_frame = ttk.Frame(self, style=style_name)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create scrollbar
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical")
        
        # Create treeview with scrollbar
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            height=6,
            yscrollcommand=scrollbar.set
        )
        scrollbar.configure(command=self.history_tree.yview)
        
        for col in columns:
            self.history_tree.heading(col, text=headings[col])
            width = {
                "time": 100,
                "status": 70,
                "model": 120,
                "pack": 150,
                "row": 40,
                "v": 30,
                "b": 30,
                "duration": 70,
                "seed": 95,
                "images": 55,
                "output": 150,
            }.get(col, 100)
            self.history_tree.column(col, anchor=tk.W, width=width, stretch=True)
        
        # Layout treeview and scrollbar
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.history_tree.bind("<<TreeviewSelect>>", self._on_select)
        self.history_tree.bind("<Motion>", self._on_tree_motion)
        self.history_tree.bind("<Leave>", self._hide_tooltip)
        self._history_menu = tk.Menu(self, tearoff=0)
        self._history_menu.add_command(label="Explain This Job", command=self._on_explain_job)
        self.history_tree.bind("<Button-3>", self._on_context_menu)

        if app_state and hasattr(app_state, "subscribe"):
            app_state.subscribe("history_items", self._on_history_items_changed)
            try:
                self._on_history_items_changed()
            except Exception:
                pass

    def _on_refresh(self) -> None:
        ctrl = self.controller
        if ctrl and hasattr(ctrl, "refresh_job_history"):
            try:
                ctrl.refresh_job_history()
                return
            except Exception:
                pass
        self._on_history_items_changed()

    def _on_history_items_changed(self) -> None:
        items = []
        if self.app_state:
            items = list(self.app_state.history_items or [])
        self._populate_history(items)

    def _populate_history(self, entries: list[JobHistoryEntry]) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        self._entries.clear()
        self._item_to_job.clear()
        for entry in entries:
            values = self._entry_values(entry)
            item_id = self.history_tree.insert("", "end", values=values)
            self._entries[entry.job_id] = entry
            self._item_to_job[item_id] = entry.job_id
        self._selected_job_id = None
        self.open_btn.configure(state=tk.DISABLED)

    def _entry_values(self, entry: JobHistoryEntry) -> tuple[str, ...]:
        time_text = self._format_time(entry.completed_at or entry.started_at or entry.created_at)
        status = self._get_display_status(entry)  # D-GUI-003: Success/Failed instead of Completed
        
        # Extract model
        model = self._extract_model(entry)
        
        # D-GUI-003: Extract pack name (never show full prompt or hash)
        pack_name = self._extract_pack_name(entry)
        
        # D-GUI-003: Extract row, variant, batch indices
        row_idx, variant_idx, batch_idx = self._extract_indices(entry)
        
        # Calculate duration more robustly
        duration = self._ensure_duration(entry)
        
        # D-GUI-003: Extract seed (use final_seed from seeds object)
        seed = self._extract_seed(entry)
        
        # Extract image count from result or NJR snapshot
        images = self._extract_image_count(entry)
        
        # D-GUI-003: Get actual output folder name (20251226_HHMMSS_PackName format)
        output = self._extract_output_folder(entry)
        
        return (time_text, status, model, pack_name, row_idx, variant_idx, batch_idx, duration, seed, images, output)

    def _on_select(self, event=None) -> None:
        selection = self.history_tree.selection()
        if not selection:
            self._selected_job_id = None
            self.open_btn.configure(state=tk.DISABLED)
            self.replay_btn.configure(state=tk.DISABLED)
            return
        item_id = selection[0]
        job_id = self._item_to_job.get(item_id)
        self._selected_job_id = job_id
        entry = self._entries.get(job_id) if job_id else None
        if not entry:
            self._selected_job_id = None
            self.open_btn.configure(state=tk.DISABLED)
            self.replay_btn.configure(state=tk.DISABLED)
            self.explain_btn.configure(state=tk.DISABLED)
            return
        self.open_btn.configure(state=tk.NORMAL)
        self.replay_btn.configure(state=tk.NORMAL)
        self.explain_btn.configure(state=tk.NORMAL)

    def _on_open_folder(self) -> None:
        if not self._selected_job_id:
            return
        entry = self._entries.get(self._selected_job_id)
        if not entry:
            return
        folder = self._derive_output_folder(entry)
        if not folder:
            return
        try:
            self._folder_opener(folder)
        except Exception:
            pass

    def _on_replay_job(self) -> None:
        if not self._selected_job_id or not self.controller:
            return
        handler = getattr(self.controller, "on_replay_history_job_v2", None)
        if not callable(handler):
            return
        try:
            handler(self._selected_job_id)
        except Exception:
            pass

    def _on_explain_job(self) -> None:
        if not self._selected_job_id or not self.controller:
            return
        handler = getattr(self.controller, "explain_job", None)
        if callable(handler):
            try:
                handler(self._selected_job_id)
            except Exception:
                pass

    def _on_context_menu(self, event: tk.Event) -> None:
        item = self.history_tree.identify_row(event.y)
        if not item:
            return
        self.history_tree.selection_set(item)
        self.history_tree.focus(item)
        job_id = self._item_to_job.get(item)
        if not job_id:
            return
        self._selected_job_id = job_id
        self.explain_btn.configure(state=tk.NORMAL)
        self._history_menu.tk_popup(event.x_root, event.y_root)

    def _get_display_status(self, entry: JobHistoryEntry) -> str:
        """D-GUI-003: Determine status: Success, Failed, or Cancelled."""
        # Check for explicit error
        if entry.result and isinstance(entry.result, dict):
            error = entry.result.get("error")
            if error:
                return "Failed"
        
        # Check snapshot for error
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            if njr.get("error"):
                return "Failed"
        
        # Check for cancellation
        if entry.status.value.lower() in ("cancelled", "canceled"):
            return "Cancelled"
        
        # Default: Success if completed without error
        if entry.status.value.lower() == "completed":
            return "Success"
        
        return entry.status.value.title()
    
    def _extract_pack_name(self, entry: JobHistoryEntry) -> str:
        """D-GUI-003: Extract pack name, never show full prompt or hash."""
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            if njr:
                # Priority: pack name > job_id
                pack_name = njr.get("prompt_pack_name") or njr.get("pack_name") or njr.get("prompt_pack_id")
                if pack_name:
                    return str(pack_name)
        
        # Fall back to truncated job_id
        job_id = entry.job_id or "unknown"
        return job_id[:12] if len(job_id) > 12 else job_id
    
    def _extract_indices(self, entry: JobHistoryEntry) -> tuple[str, str, str]:
        """D-GUI-003: Extract row, variant, batch indices (1-based for display)."""
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            if njr:
                row = njr.get("prompt_pack_row_index")
                variant = njr.get("variant_index")
                batch = njr.get("batch_index")
                
                # Convert to 1-based display
                row_str = str(row + 1) if row is not None else "-"
                variant_str = str(variant + 1) if variant is not None else "-"
                batch_str = str(batch + 1) if batch is not None else "-"
                
                return (row_str, variant_str, batch_str)
        
        return ("-", "-", "-")
    
    def _extract_summary(self, entry: JobHistoryEntry) -> str:
        """Extract pack name + prompt preview when available."""
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            if njr:
                pack_name = None
                if njr.get("source") == "pack":
                    pack_name = njr.get("pack_name") or njr.get("prompt_pack_id")
                prompt = njr.get("positive_prompt", "")
                if pack_name:
                    prompt_preview = self._shorten(prompt, width=40)
                    return f"{pack_name}: {prompt_preview}"
                if prompt:
                    return self._shorten(prompt, width=60)
        if entry.payload_summary:
            return self._shorten(entry.payload_summary, width=60)
        job_id = entry.job_id or "unknown"
        return f"Job {job_id[:8]}"
    
    def _extract_model(self, entry: JobHistoryEntry) -> str:
        """Extract model name from NJR snapshot or result."""
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            model = njr.get("base_model") or njr.get("model")
            if model:
                return Path(str(model)).stem
        metadata = self._extract_result_metadata(entry)
        model = metadata.get("model") or metadata.get("sd_model_checkpoint")
        if model:
            return Path(str(model)).stem
        return "-"
    
    def _extract_seed(self, entry: JobHistoryEntry) -> str:
        """D-GUI-003: Extract actual seed from seeds.final_seed, never show 'Random'."""
        # Try manifest seeds structure first (D-MANIFEST-001)
        metadata = self._extract_result_metadata(entry)
        seeds = metadata.get("seeds")
        if isinstance(seeds, dict):
            final_seed = seeds.get("final_seed")
            if final_seed is not None and final_seed != -1:
                return str(final_seed)
        
        # Fall back to legacy fields
        seed = metadata.get("actual_seed") or metadata.get("final_seed")
        if seed is not None and seed != -1:
            return str(seed)
        
        # Try NJR snapshot
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            seed = njr.get("actual_seed") or njr.get("resolved_seed")
            if seed is not None and seed != -1:
                return str(seed)
            # Last resort: show requested seed even if -1
            seed = njr.get("seed")
            if seed is not None and seed != -1:
                return str(seed)
        
        return "-"
    
    def _ensure_duration(self, entry: JobHistoryEntry) -> str:
        """Ensure duration is calculated and formatted."""
        # Prefer pre-calculated duration_ms
        if entry.duration_ms is not None and entry.duration_ms > 0:
            return self._format_duration_ms(entry.duration_ms)
        
        # Calculate from timestamps if available
        if (entry.started_at or entry.created_at) and entry.completed_at:
            try:
                start = entry.started_at or entry.created_at
                end = entry.completed_at
                
                # Handle string timestamps
                if isinstance(start, str):
                    start = datetime.fromisoformat(start.replace('Z', '+00:00'))
                if isinstance(end, str):
                    end = datetime.fromisoformat(end.replace('Z', '+00:00'))
                
                delta = end - start
                duration_ms = int(delta.total_seconds() * 1000)
                if duration_ms > 0:
                    return self._format_duration_ms(duration_ms)
            except Exception:
                pass
        
        return "-"

    def _extract_result_metadata(self, entry: JobHistoryEntry) -> dict[str, Any]:
        """Extract metadata dict from result payload if present."""
        if not entry.result or not isinstance(entry.result, dict):
            return {}
        metadata = entry.result.get("metadata")
        if isinstance(metadata, dict):
            return metadata
        if isinstance(metadata, list) and metadata:
            for item in reversed(metadata):
                if isinstance(item, dict):
                    return item
        return {}
    
    def _extract_image_count(self, entry: JobHistoryEntry) -> str:
        """Extract image count from result or NJR snapshot."""
        # Try result first
        if entry.result and isinstance(entry.result, dict):
            count = entry.result.get("image_count") or entry.result.get("images_generated")
            if count is not None:
                return str(count)
        
        # Try NJR snapshot
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            if njr:
                variant_total = njr.get("variant_total", 1)
                batch_total = njr.get("batch_total", 1)
                if variant_total and batch_total:
                    return str(variant_total * batch_total)
        
        return "-"
    
    def _extract_output_folder(self, entry: JobHistoryEntry) -> str:
        """D-GUI-003: Extract actual output folder name (20251226_HHMMSS_PackName)."""
        # Try result first for actual output path
        if entry.result and isinstance(entry.result, dict):
            output_dir = entry.result.get("output_dir") or entry.result.get("output_folder")
            if output_dir:
                folder_name = Path(output_dir).name
                return folder_name if folder_name else "-"
        
        # Try to derive from NJR snapshot run_id
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            run_id = njr.get("run_id")
            if run_id:
                return str(run_id)
        
        # Fall back to job_id (truncated)
        job_id = entry.job_id or "unknown"
        return job_id[:20] if len(job_id) > 20 else job_id
    
    def _derive_output_folder(self, entry: JobHistoryEntry) -> str:
        """PR-GUI-FUNC-003: Derive actual output folder path from job entry."""
        # Try to get output_dir from result first (most accurate)
        if entry.result and isinstance(entry.result, dict):
            output_dir = entry.result.get("output_dir") or entry.result.get("output_folder")
            if output_dir:
                output_path = Path(output_dir)
                if output_path.exists():
                    return str(output_path)
        
        # Try to get path_output_dir from snapshot
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            path_output_dir = njr.get("path_output_dir")
            if path_output_dir:
                output_path = Path(path_output_dir)
                if output_path.exists():
                    return str(output_path)
        
        # Fall back to checking runs/{job_id}
        runs_candidate = Path("runs") / entry.job_id
        if runs_candidate.exists():
            return str(runs_candidate)
        
        # Last resort: return base runs directory
        runs_base = Path("runs")
        if runs_base.exists():
            return str(runs_base)
        
        # If nothing exists, return the expected location
        return str(runs_base)

    def _on_tree_motion(self, event: tk.Event) -> None:
        """Show tooltip with full model name on hover."""
        item = self.history_tree.identify_row(event.y)
        column = self.history_tree.identify_column(event.x)
        
        if not item or column != "#3":  # Model column (0-indexed: #1=time, #2=status, #3=model)
            self._hide_tooltip()
            return
        
        job_id = self._item_to_job.get(item)
        if not job_id:
            self._hide_tooltip()
            return
        
        entry = self._entries.get(job_id)
        if not entry:
            self._hide_tooltip()
            return
        
        # Get full model name
        full_model = self._extract_full_model(entry)
        if not full_model or full_model == "-":
            self._hide_tooltip()
            return
        
        self._show_tooltip(event.x_root, event.y_root, full_model)
    
    def _extract_full_model(self, entry: JobHistoryEntry) -> str:
        """Extract full model name without truncation."""
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            model = njr.get("base_model") or njr.get("model")
            if model:
                return str(model)
        
        if entry.result and isinstance(entry.result, dict):
            model = entry.result.get("model") or entry.result.get("sd_model_checkpoint")
            if model:
                return str(model)
        
        return "-"
    
    def _show_tooltip(self, x: int, y: int, text: str) -> None:
        """Display tooltip near cursor."""
        self._hide_tooltip()
        
        self._tooltip = tk.Toplevel(self)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.wm_geometry(f"+{x + 10}+{y + 10}")
        
        label = tk.Label(
            self._tooltip,
            text=text,
            background="#ffffe0",
            foreground="#000000",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=4,
            pady=2,
        )
        label.pack()
    
    def _hide_tooltip(self, event: tk.Event | None = None) -> None:
        """Hide the tooltip."""
        if self._tooltip:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None

    @staticmethod
    def _format_time(value: str | None) -> str:
        if not value:
            return "-"
        try:
            # Parse as UTC datetime, convert to local
            if isinstance(value, str):
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                dt = value
            # Convert to local time if it's a datetime
            if hasattr(dt, 'astimezone'):
                dt = dt.astimezone()
            return dt.strftime("%m-%d-%Y %H:%M:%S")
        except Exception:
            return str(value) if value else "-"

    @staticmethod
    def _format_duration(start: str | None, end: str | None) -> str:
        if not start or not end:
            return "-"
        try:
            delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
            return f"{delta.total_seconds():.1f}s"
        except Exception:
            return "-"

    @staticmethod
    def _format_duration_ms(duration_ms: int) -> str:
        """Format duration in milliseconds to readable format."""
        total_seconds = duration_ms / 1000
        if total_seconds < 60:
            return f"{total_seconds:.0f}s"
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}h {minutes}m"

    @staticmethod
    def _shorten(text: str, *, width: int = 16) -> str:
        if len(text) <= width:
            return text
        return text[: width - 3] + "..."

    @staticmethod
    def _default_open_folder(path: str) -> None:
        candidate = Path(path)
        if not candidate.exists():
            candidate = candidate.parent
        try:
            if os.name == "nt":
                os.startfile(str(candidate))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(candidate)], check=False)
            else:
                subprocess.run(["xdg-open", str(candidate)], check=False)
        except Exception:
            pass
