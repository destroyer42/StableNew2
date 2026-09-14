"""Compact job history renderer for the Pipeline tab."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.gui import theme_v2 as theme_mod
from src.gui.view_contracts.movie_clips_contract import extract_source_paths_from_bundle
from src.pipeline.artifact_contract import extract_artifact_paths
from src.queue.job_history_store import (
    INTERRUPTED_RESTART_ACTION_REQUIRED,
    JobHistoryEntry,
)
from src.video.video_artifact_helpers import extract_source_image_for_handoff

_IMAGE_OUTPUT_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
}
_MOVIE_CLIPS_SOURCE_SUFFIXES = _IMAGE_OUTPUT_SUFFIXES | {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
}


@dataclass(frozen=True)
class HistoryActionState:
    """The currently legal, callable actions for one history entry."""

    open_folder: bool
    replay: bool
    svd: bool
    video_workflow: bool
    movie_clips: bool
    explain: bool


class JobHistoryPanelV2(ttk.Frame):
    """Show recent job history entries (completion timestamps, packs, duration, output)."""

    SLOW_REFRESH_THRESHOLD_MS = 20.0

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        folder_opener: Callable[[str], None] | None = None,
        manage_app_state_subscriptions: bool = True,
        **kwargs,
    ) -> None:
        style_name = theme_mod.SURFACE_FRAME_STYLE
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self._manage_app_state_subscriptions = bool(manage_app_state_subscriptions)
        self._folder_opener = folder_opener or self._default_open_folder
        self._entries: dict[str, JobHistoryEntry] = {}
        self._item_to_job: dict[str, str] = {}
        self._selected_job_id: str | None = None
        self._tooltip: tk.Toplevel | None = None
        self._last_history_signature: tuple[tuple[str, tuple[str, ...]], ...] = ()
        self._refresh_metrics: dict[str, dict[str, float | int]] = {}

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
        self.svd_btn = ttk.Button(
            action_bar,
            text="Animate with SVD",
            command=self._on_send_to_svd,
            state=tk.DISABLED,
        )
        self.svd_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.video_workflow_btn = ttk.Button(
            action_bar,
            text="Video Workflow",
            command=self._on_send_to_video_workflow,
            state=tk.DISABLED,
        )
        self.video_workflow_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.movie_clips_btn = ttk.Button(
            action_bar,
            text="Movie Clips",
            command=self._on_send_to_movie_clips,
            state=tk.DISABLED,
        )
        self.movie_clips_btn.pack(side=tk.LEFT, padx=(4, 0))
        self.explain_btn = ttk.Button(
            action_bar,
            text="Explain Job",
            command=self._on_explain_job,
            state=tk.DISABLED,
        )
        self.explain_btn.pack(side=tk.LEFT, padx=(4, 0))

        # D-GUI-003: Enhanced columns with row/variant/batch info
        columns = (
            "time",
            "status",
            "model",
            "pack",
            "row",
            "v",
            "b",
            "duration",
            "seed",
            "images",
            "output",
        )
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
            tree_frame, columns=columns, show="headings", height=6, yscrollcommand=scrollbar.set
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
        self._history_menu.add_command(label="Animate with SVD", command=self._on_send_to_svd)
        self._history_menu.add_command(
            label="Send to Video Workflow", command=self._on_send_to_video_workflow
        )
        self._history_menu.add_command(
            label="Send to Movie Clips", command=self._on_send_to_movie_clips
        )
        self._history_menu.add_command(label="Explain This Job", command=self._on_explain_job)
        self.history_tree.bind("<Button-3>", self._on_context_menu)
        self.empty_state_var = tk.StringVar(
            value="No recent jobs yet. Queue an image or video job to populate history."
        )
        ttk.Label(self, textvariable=self.empty_state_var, style=theme_mod.MUTED_LABEL_STYLE).pack(
            anchor=tk.W, pady=(4, 0)
        )

        if self._manage_app_state_subscriptions and app_state and hasattr(app_state, "subscribe"):
            app_state.subscribe("history_items", self._on_history_items_changed)
            try:
                self._on_history_items_changed()
            except Exception:
                pass

    def _on_refresh(self) -> None:
        ctrl = self.controller
        refresh = getattr(ctrl, "refresh_job_history", None)
        if callable(refresh):
            try:
                refresh()
                return
            except Exception:
                pass
        self._on_history_items_changed()

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        if app_state is not None:
            self.app_state = app_state
        self._on_history_items_changed()

    def _on_history_items_changed(self) -> None:
        start = time.perf_counter()
        items = []
        if self.app_state:
            items = list(self.app_state.history_items or [])
        self._populate_history(items)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._record_refresh_metric("_on_history_items_changed", elapsed_ms)

    def _populate_history(self, entries: list[JobHistoryEntry]) -> None:
        start = time.perf_counter()
        selected_job_id = self._selected_job_id
        rows = [(entry, self._entry_values(entry)) for entry in entries]
        signature = tuple((entry.job_id, values) for entry, values in rows)
        if signature == self._last_history_signature:
            self.empty_state_var.set(
                "No recent jobs yet. Queue an image or video job to populate history."
                if not entries
                else ""
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_populate_history", elapsed_ms)
            return

        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        self._entries.clear()
        self._item_to_job.clear()
        restored_item_id: str | None = None
        for entry, values in rows:
            item_id = self.history_tree.insert("", "end", values=values)
            self._entries[entry.job_id] = entry
            self._item_to_job[item_id] = entry.job_id
            if selected_job_id and entry.job_id == selected_job_id:
                restored_item_id = item_id
        self._last_history_signature = signature
        self.empty_state_var.set(
            "No recent jobs yet. Queue an image or video job to populate history."
            if not entries
            else ""
        )
        if restored_item_id and selected_job_id in self._entries:
            self.history_tree.selection_set(restored_item_id)
            self._selected_job_id = selected_job_id
            self._update_action_buttons(self._entries[selected_job_id])
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_populate_history", elapsed_ms)
            return
        self._selected_job_id = None
        self._update_action_buttons(None)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._record_refresh_metric("_populate_history", elapsed_ms)

    def _record_refresh_metric(self, name: str, elapsed_ms: float) -> None:
        metrics = self._refresh_metrics.setdefault(
            name,
            {
                "count": 0,
                "total_ms": 0.0,
                "max_ms": 0.0,
                "last_ms": 0.0,
                "slow_count": 0,
            },
        )
        metrics["count"] = int(metrics["count"]) + 1
        metrics["total_ms"] = float(metrics["total_ms"]) + float(elapsed_ms)
        metrics["last_ms"] = float(elapsed_ms)
        metrics["max_ms"] = max(float(metrics["max_ms"]), float(elapsed_ms))
        if elapsed_ms >= float(self.SLOW_REFRESH_THRESHOLD_MS):
            metrics["slow_count"] = int(metrics["slow_count"]) + 1

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        refresh_metrics: dict[str, dict[str, float | int]] = {}
        for name, metrics in sorted(self._refresh_metrics.items()):
            count = int(metrics.get("count", 0) or 0)
            total_ms = float(metrics.get("total_ms", 0.0) or 0.0)
            refresh_metrics[name] = {
                "count": count,
                "avg_ms": round(total_ms / count, 3) if count else 0.0,
                "max_ms": round(float(metrics.get("max_ms", 0.0) or 0.0), 3),
                "last_ms": round(float(metrics.get("last_ms", 0.0) or 0.0), 3),
                "slow_count": int(metrics.get("slow_count", 0) or 0),
            }
        return {
            "slow_threshold_ms": float(self.SLOW_REFRESH_THRESHOLD_MS),
            "refresh_metrics": refresh_metrics,
        }

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

        return (
            time_text,
            status,
            model,
            pack_name,
            row_idx,
            variant_idx,
            batch_idx,
            duration,
            seed,
            images,
            output,
        )

    def _on_select(self, event=None) -> None:
        selection = self.history_tree.selection()
        if not selection:
            self._selected_job_id = None
            self._update_action_buttons(None)
            return
        item_id = selection[0]
        job_id = self._item_to_job.get(item_id)
        self._selected_job_id = job_id
        entry = self._entries.get(job_id) if job_id else None
        if not entry:
            self._selected_job_id = None
            self._update_action_buttons(None)
            return
        self._update_action_buttons(entry)

    def _on_open_folder(self) -> None:
        entry = self._selected_entry()
        if not entry or not self._history_action_state(entry).open_folder:
            return
        folder = self._usable_output_folder(entry)
        if not folder:
            return
        try:
            self._folder_opener(folder)
        except Exception:
            pass

    def _on_replay_job(self) -> None:
        entry = self._selected_entry()
        if not entry or not self._history_action_state(entry).replay:
            return
        handler = getattr(self.controller, "on_replay_history_job_v2", None)
        if not callable(handler):
            return
        try:
            handler(self._selected_job_id)
        except Exception:
            pass

    def _on_explain_job(self) -> None:
        entry = self._selected_entry()
        if not entry or not self._history_action_state(entry).explain:
            return
        handler = getattr(self.controller, "explain_job", None)
        if callable(handler):
            try:
                handler(self._selected_job_id)
            except Exception:
                pass

    def _on_send_to_svd(self) -> None:
        entry = self._selected_entry()
        if not entry or not self._history_action_state(entry).svd:
            return
        handler = getattr(self.controller, "send_history_job_image_to_svd", None)
        if callable(handler):
            try:
                handler(self._selected_job_id)
            except Exception:
                pass

    def _on_send_to_video_workflow(self) -> None:
        entry = self._selected_entry()
        if not entry or not self._history_action_state(entry).video_workflow:
            return
        handler = getattr(self.controller, "send_history_job_image_to_video_workflow", None)
        if callable(handler):
            try:
                handler(self._selected_job_id)
            except Exception:
                pass

    def _on_send_to_movie_clips(self) -> None:
        entry = self._selected_entry()
        if not entry or not self._history_action_state(entry).movie_clips:
            return
        handler = getattr(self.controller, "send_history_job_to_movie_clips", None)
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
        entry = self._entries.get(job_id)
        if entry:
            self._update_action_buttons(entry)
        self._history_menu.tk_popup(event.x_root, event.y_root)

    def _update_action_buttons(self, entry: JobHistoryEntry | None) -> None:
        actions = self._history_action_state(entry)
        self.open_btn.configure(state=tk.NORMAL if actions.open_folder else tk.DISABLED)
        self.replay_btn.configure(state=tk.NORMAL if actions.replay else tk.DISABLED)
        self.svd_btn.configure(state=tk.NORMAL if actions.svd else tk.DISABLED)
        self.video_workflow_btn.configure(
            state=tk.NORMAL if actions.video_workflow else tk.DISABLED
        )
        self.movie_clips_btn.configure(state=tk.NORMAL if actions.movie_clips else tk.DISABLED)
        self.explain_btn.configure(state=tk.NORMAL if actions.explain else tk.DISABLED)
        self._history_menu.entryconfigure(
            "Animate with SVD", state=tk.NORMAL if actions.svd else tk.DISABLED
        )
        self._history_menu.entryconfigure(
            "Send to Video Workflow",
            state=tk.NORMAL if actions.video_workflow else tk.DISABLED,
        )
        self._history_menu.entryconfigure(
            "Send to Movie Clips", state=tk.NORMAL if actions.movie_clips else tk.DISABLED
        )
        self._history_menu.entryconfigure(
            "Explain This Job", state=tk.NORMAL if actions.explain else tk.DISABLED
        )

    def _selected_entry(self) -> JobHistoryEntry | None:
        if not self._selected_job_id:
            return None
        return self._entries.get(self._selected_job_id)

    def _controller_supports(self, name: str) -> bool:
        return callable(getattr(self.controller, name, None))

    @staticmethod
    def _is_existing_file(path_value: object, suffixes: set[str]) -> bool:
        try:
            path = Path(str(path_value or "")).expanduser()
            return path.is_file() and path.suffix.lower() in suffixes
        except (OSError, ValueError):
            return False

    def _usable_image_artifact_path(self, entry: JobHistoryEntry) -> str | None:
        artifact = self._extract_primary_artifact(entry)
        if str(artifact.get("artifact_type") or "").strip().lower() != "image":
            return None
        for path in extract_artifact_paths({"artifact": artifact}):
            if self._is_existing_file(path, _IMAGE_OUTPUT_SUFFIXES):
                return str(path)
        return None

    def _usable_video_workflow_source(self, entry: JobHistoryEntry) -> str | None:
        result = entry.result if isinstance(entry.result, dict) else {}
        bundles = [result.get("video_bundle")]
        bundles.extend(self._iter_video_artifact_aggregates(self._extract_result_metadata(entry)))
        for bundle in bundles:
            if not isinstance(bundle, dict):
                continue
            source_path = extract_source_image_for_handoff(bundle)
            if self._is_existing_file(source_path, _IMAGE_OUTPUT_SUFFIXES):
                return str(source_path)
        return self._usable_image_artifact_path(entry)

    def _usable_movie_clips_source(self, entry: JobHistoryEntry) -> str | None:
        result = entry.result if isinstance(entry.result, dict) else {}
        bundles = [result.get("video_bundle")]
        bundles.extend(self._iter_video_artifact_aggregates(self._extract_result_metadata(entry)))
        for bundle in bundles:
            if not isinstance(bundle, dict):
                continue
            for path in extract_source_paths_from_bundle(bundle):
                if self._is_existing_file(path, _MOVIE_CLIPS_SOURCE_SUFFIXES):
                    return str(path)
        return self._usable_image_artifact_path(entry)

    def _entry_has_reconstructable_njr(self, entry: JobHistoryEntry) -> bool:
        snapshot = entry.snapshot if isinstance(entry.snapshot, dict) else None
        try:
            return HistoryHandoffService().hydrate_njr_from_snapshot(snapshot) is not None
        except Exception:
            return False

    def _usable_output_folder(self, entry: JobHistoryEntry) -> str | None:
        artifact = self._extract_primary_artifact(entry)
        for path_value in extract_artifact_paths({"artifact": artifact}) if artifact else []:
            try:
                path = Path(path_value).expanduser()
                folder = path if path.is_dir() else path.parent
                if path.exists() and folder.is_dir():
                    return str(folder)
            except (OSError, ValueError):
                continue
        result = entry.result if isinstance(entry.result, dict) else {}
        output_dir = result.get("output_dir") or result.get("output_folder")
        try:
            path = Path(str(output_dir or "")).expanduser()
            return str(path) if output_dir and path.is_dir() else None
        except (OSError, ValueError):
            return None

    def _history_action_state(self, entry: JobHistoryEntry | None) -> HistoryActionState:
        if entry is None:
            return HistoryActionState(False, False, False, False, False, False)
        return HistoryActionState(
            open_folder=(
                self._usable_output_folder(entry) is not None
                and callable(getattr(self, "_folder_opener", None))
            ),
            replay=(
                self._controller_supports("on_replay_history_job_v2")
                and self._entry_has_reconstructable_njr(entry)
            ),
            svd=(
                self._controller_supports("send_history_job_image_to_svd")
                and self._usable_image_artifact_path(entry) is not None
            ),
            video_workflow=(
                self._controller_supports("send_history_job_image_to_video_workflow")
                and self._usable_video_workflow_source(entry) is not None
            ),
            movie_clips=(
                self._controller_supports("send_history_job_to_movie_clips")
                and self._usable_movie_clips_source(entry) is not None
            ),
            explain=self._controller_supports("explain_job"),
        )

    def _entry_supports_image_handoff(self, entry: JobHistoryEntry) -> bool:
        """Returns True if the entry has a still-image primary output suitable for SVD."""
        return self._usable_image_artifact_path(entry) is not None

    def _entry_supports_video_workflow_handoff(self, entry: JobHistoryEntry) -> bool:
        """Return True only when the entry has a usable still-image handoff source."""
        return self._usable_video_workflow_source(entry) is not None

    def _entry_supports_movie_clips_handoff(self, entry: JobHistoryEntry) -> bool:
        return self._usable_movie_clips_source(entry) is not None

    def _get_display_status(self, entry: JobHistoryEntry) -> str:
        """D-GUI-003: Determine status: Success, Failed, or Cancelled."""
        if (
            entry.error_envelope is not None
            and entry.error_envelope.error_type == INTERRUPTED_RESTART_ACTION_REQUIRED
        ):
            return "Interrupted"

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
                pack_name = (
                    njr.get("prompt_pack_name") or njr.get("pack_name") or njr.get("prompt_pack_id")
                )
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
        if not model and entry.result and isinstance(entry.result, dict):
            model = entry.result.get("model") or entry.result.get("sd_model_checkpoint")
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
        if seed == -1:
            return "Random"
        if entry.result and isinstance(entry.result, dict):
            seed = entry.result.get("actual_seed") or entry.result.get("final_seed")
            if seed is not None and seed != -1:
                return str(seed)
            if seed == -1:
                return "Random"

        # Try NJR snapshot
        if entry.snapshot:
            njr = entry.snapshot.get("normalized_job", {})
            seed = njr.get("actual_seed") or njr.get("resolved_seed")
            if seed is not None and seed != -1:
                return str(seed)
            # Last resort: show requested seed even if -1
            seed = njr.get("seed")
            if seed == -1:
                return "Random"
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
                    start = datetime.fromisoformat(start.replace("Z", "+00:00"))
                if isinstance(end, str):
                    end = datetime.fromisoformat(end.replace("Z", "+00:00"))

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

    @staticmethod
    def _iter_video_artifact_aggregates(metadata: dict[str, Any]) -> list[dict[str, Any]]:
        aggregates: list[dict[str, Any]] = []

        primary_artifact = metadata.get("video_primary_artifact")
        if isinstance(primary_artifact, dict):
            aggregates.append(dict(primary_artifact))

        video_artifacts = metadata.get("video_artifacts")
        if isinstance(video_artifacts, dict):
            for aggregate in video_artifacts.values():
                if isinstance(aggregate, dict):
                    aggregates.append(dict(aggregate))

        video_backend_results = metadata.get("video_backend_results")
        if isinstance(video_backend_results, dict):
            for aggregate in video_backend_results.values():
                if isinstance(aggregate, dict):
                    aggregates.append(dict(aggregate))

        for key in ("video_workflow_artifact", "svd_native_artifact", "animatediff_artifact"):
            aggregate = metadata.get(key)
            if isinstance(aggregate, dict):
                aggregates.append(dict(aggregate))

        return aggregates

    def _extract_primary_artifact(self, entry: JobHistoryEntry) -> dict[str, Any]:
        """Extract the best available canonical artifact record from a history result."""
        if not entry.result or not isinstance(entry.result, dict):
            return {}

        direct_artifact = entry.result.get("artifact")
        if isinstance(direct_artifact, dict):
            return dict(direct_artifact)

        metadata = self._extract_result_metadata(entry)
        for aggregate in self._iter_video_artifact_aggregates(metadata):
            artifacts = aggregate.get("artifacts")
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if isinstance(artifact, dict):
                        return dict(artifact)
            primary_path = aggregate.get("primary_path")
            output_paths = aggregate.get("output_paths") or aggregate.get("video_paths")
            manifest_paths = aggregate.get("manifest_paths")
            manifest_path = (
                manifest_paths[0] if isinstance(manifest_paths, list) and manifest_paths else None
            )
            if primary_path or output_paths:
                return {
                    "artifact_type": "video",
                    "primary_path": primary_path,
                    "output_paths": list(output_paths or []),
                    "manifest_path": manifest_path,
                }

        variants = entry.result.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                artifact = variant.get("artifact")
                if isinstance(artifact, dict):
                    return dict(artifact)

        return {}

    def _extract_image_count(self, entry: JobHistoryEntry) -> str:
        """Extract image count from result or NJR snapshot."""
        artifact = self._extract_primary_artifact(entry)
        if artifact:
            output_paths = extract_artifact_paths({"artifact": artifact})
            if output_paths:
                return str(len(output_paths))
        metadata = self._extract_result_metadata(entry)
        for aggregate in self._iter_video_artifact_aggregates(metadata):
            if aggregate.get("count") is not None:
                return str(aggregate["count"])

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
        artifact = self._extract_primary_artifact(entry)
        primary_paths = extract_artifact_paths({"artifact": artifact}) if artifact else []
        if primary_paths:
            return Path(primary_paths[0]).parent.name or "-"

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
        """Return only a current folder proven by canonical result/artifact evidence."""
        return self._usable_output_folder(entry) or ""

    def _on_tree_motion(self, event: tk.Event) -> None:
        """Show tooltip with full model name and efficiency metrics on hover."""
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

        efficiency_text = self._extract_efficiency_summary(entry)
        tooltip_text = full_model if not efficiency_text else f"{full_model}\n{efficiency_text}"
        self._show_tooltip(event.x_root, event.y_root, tooltip_text)

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

    def _extract_efficiency_summary(self, entry: JobHistoryEntry) -> str:
        """Return compact efficiency metrics summary from run result metadata."""
        if not entry.result or not isinstance(entry.result, dict):
            return ""
        metrics = None
        metadata = entry.result.get("metadata")
        if isinstance(metadata, dict):
            candidate = metadata.get("efficiency_metrics")
            if isinstance(candidate, dict):
                metrics = candidate
        if metrics is None:
            candidate = entry.result.get("efficiency_metrics")
            if isinstance(candidate, dict):
                metrics = candidate
        if not metrics:
            return ""

        elapsed = metrics.get("elapsed_seconds")
        ipm = metrics.get("images_per_minute")
        model_switches = metrics.get("model_switches")
        vae_switches = metrics.get("vae_switches")
        parts: list[str] = []
        if elapsed is not None:
            parts.append(f"elapsed={elapsed}s")
        if ipm is not None:
            parts.append(f"img/min={ipm}")
        if model_switches is not None:
            parts.append(f"model_sw={model_switches}")
        if vae_switches is not None:
            parts.append(f"vae_sw={vae_switches}")
        return " | ".join(parts)

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
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                dt = value
            # Convert to local time if it's a datetime
            if hasattr(dt, "astimezone"):
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
