"""Preview panel for GUI v2 (PR-CORE1-A3: NJR-only display).

This panel displays job previews using NormalizedJobRecord and UnifiedJobSummary.
All display data comes from NJR snapshots, never from pipeline_config.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.design_system_v2 import DANGER_BUTTON
from src.gui.theme_v2 import (
    BACKGROUND_ELEVATED,
    PADDING_MD,
    PRIMARY_BUTTON_STYLE,
    SECONDARY_BUTTON_STYLE,
    STATUS_LABEL_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
    TEXT_PRIMARY,
)
from src.gui.utils.display_helpers import extract_seed_from_job, format_seed_display
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget
from src.pipeline.job_models_v2 import JobUiSummary, NormalizedJobRecord, UnifiedJobSummary
from src.controller.ports.runtime_ports import NJRSummaryPort, NJRUISummaryPort
from src.state.output_routing import get_output_root, iter_output_run_dirs
from src.state.workspace_paths import workspace_paths

logger = logging.getLogger(__name__)

# PR-PERSIST-001: Preview panel state persistence
PREVIEW_STATE_PATH = workspace_paths.preview_panel_state()
_THUMBNAIL_CACHE_MISS = object()


class PreviewPanelV2(ttk.Frame):
    """Container for preview/inspector content (structure only)."""
    NEGATIVE_THUMBNAIL_CACHE_TTL_S = 1.0
    POSITIVE_THUMBNAIL_CACHE_TTL_S = 15.0
    SLOW_REFRESH_THRESHOLD_MS = 20.0

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        manage_app_state_subscriptions: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self._manage_app_state_subscriptions = bool(manage_app_state_subscriptions)
        self._job_summaries: list[JobUiSummary] = []
        self._content_visibility_mode = str(
            getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        self._refresh_metrics: dict[str, dict[str, float | int]] = {}
        self._last_render_signature: tuple[Any, ...] | None = None
        self._thumbnail_lookup_cache: dict[tuple[str, ...], tuple[float, str | None]] = {}
        self._thumbnail_lookup_pending: set[tuple[str, ...]] = set()
        self._prompt_text_value = ""
        self._negative_prompt_text_value = ""

        header_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        header_frame.pack(fill="x", pady=(0, 4))

        self.header_label = ttk.Label(header_frame, text="Preview", style=STATUS_STRONG_LABEL_STYLE)
        self.header_label.pack(side=tk.LEFT)

        self.details_button = ttk.Button(
            header_frame,
            text="Details",
            style=SECONDARY_BUTTON_STYLE,
            command=self._on_details_clicked,
        )
        self.details_button.pack(side=tk.RIGHT)

        # PR-GUI-LAYOUT-002: Two-column layout with thumbnail on right
        self.body = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        self.body.pack(fill=tk.BOTH, expand=True)
        self.body.columnconfigure(0, weight=1)  # Left column expands
        self.body.columnconfigure(1, weight=0)  # Right column fixed

        # Right column: Thumbnail + checkbox
        right_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        right_frame.grid(row=0, column=1, sticky="ne", padx=(8, 0))
        self.thumbnail_frame = right_frame

        self.thumbnail = ThumbnailWidget(
            right_frame,
            width=300,
            height=300,
            placeholder_text="No Preview",
        )
        self.thumbnail.pack(anchor="ne")

        # Checkbox to enable/disable preview thumbnails
        # PR-PREVIEW-001: Default to False
        self._show_preview_var = tk.BooleanVar(value=False)
        self.preview_checkbox = ttk.Checkbutton(
            right_frame,
            text="Show preview thumbnails",
            variable=self._show_preview_var,
            command=self._on_preview_checkbox_changed,
            style="Dark.TCheckbutton",
        )
        self.preview_checkbox.pack(anchor="ne", pady=(4, 0))

        # Left column: Job info + prompts + settings
        left_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        left_frame.grid(row=0, column=0, sticky="nsew")

        self.job_count_label = ttk.Label(
            left_frame, text="No job selected", style=STATUS_LABEL_STYLE
        )
        self.job_count_label.pack(anchor=tk.W, pady=(0, 4))
        self.visibility_banner = ttk.Label(
            left_frame,
            text="",
            style=STATUS_LABEL_STYLE,
            foreground="#7aa2d6",
        )

        self.prompt_label = ttk.Label(left_frame, text="Prompt (+)", style=STATUS_LABEL_STYLE)
        self.prompt_label.pack(anchor=tk.W)
        # PR-GUI-LAYOUT-002: Increased height from 3 to 4
        self.prompt_text = tk.Text(
            left_frame,
            height=4,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="flat",
            state="disabled",
        )
        self.prompt_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.negative_prompt_label = ttk.Label(
            left_frame, text="Prompt (–)", style=STATUS_LABEL_STYLE
        )
        self.negative_prompt_label.pack(anchor=tk.W)
        # PR-GUI-LAYOUT-002: Increased height from 2 to 3
        self.negative_prompt_text = tk.Text(
            left_frame,
            height=3,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="flat",
            state="disabled",
        )
        self.negative_prompt_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        settings_frame = ttk.Frame(left_frame, style=SURFACE_FRAME_STYLE)
        settings_frame.pack(fill=tk.X, pady=(0, 4))
        settings_frame.columnconfigure(0, weight=1)
        settings_frame.columnconfigure(1, weight=1)

        self.model_label = ttk.Label(settings_frame, text="Model: -", style=STATUS_LABEL_STYLE)
        self.model_label.grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.sampler_label = ttk.Label(settings_frame, text="Sampler: -", style=STATUS_LABEL_STYLE)
        self.sampler_label.grid(row=0, column=1, sticky="w")
        self.steps_label = ttk.Label(settings_frame, text="Steps: -", style=STATUS_LABEL_STYLE)
        self.steps_label.grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(4, 0))
        self.cfg_label = ttk.Label(settings_frame, text="CFG: -", style=STATUS_LABEL_STYLE)
        self.cfg_label.grid(row=1, column=1, sticky="w", pady=(4, 0))
        self.seed_label = ttk.Label(settings_frame, text="Seed: -", style=STATUS_LABEL_STYLE)
        self.seed_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.stage_summary_label = ttk.Label(left_frame, text="Stages: -", style=STATUS_LABEL_STYLE)
        self.stage_summary_label.pack(anchor=tk.W, pady=(4, 0))

        self.stage_flags_label = ttk.Label(
            left_frame,  # PR-GUI-FIX: pack into left_frame, not body (grid/pack conflict)
            text=self._format_flags(refiner=False, hires=False, upscale=False),
            style=STATUS_LABEL_STYLE,
        )
        self.stage_flags_label.pack(anchor=tk.W, pady=(0, 4))

        self.randomizer_label = ttk.Label(
            left_frame,  # PR-GUI-FIX: pack into left_frame, not body
            text="Randomizer: OFF", style=STATUS_LABEL_STYLE
        )
        self.randomizer_label.pack(anchor=tk.W, pady=(0, 4))

        self.learning_metadata_label = ttk.Label(
            left_frame,  # PR-GUI-FIX: pack into left_frame, not body
            text="Learning metadata: N/A",
            style=STATUS_LABEL_STYLE,
        )
        self.learning_metadata_label.pack(anchor=tk.W)

        self.actions_frame = ttk.Frame(left_frame, style=SURFACE_FRAME_STYLE)  # PR-GUI-FIX: parent is left_frame
        self.actions_frame.pack(fill=tk.X, pady=(12, 0))
        self.actions_frame.columnconfigure((0, 1), weight=1)

        self.add_to_queue_button = ttk.Button(
            self.actions_frame,
            text="Add to Queue",
            style=PRIMARY_BUTTON_STYLE,
            command=self._on_add_to_queue,
        )
        self.add_to_queue_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.clear_draft_button = ttk.Button(
            self.actions_frame,
            text="Clear Draft",
            style=DANGER_BUTTON,
            command=self._on_clear_draft,
        )
        self.clear_draft_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self._update_action_states(None)
        self._bind_app_state_previews()
        
        # PR-PERSIST-001: Restore saved state
        self.restore_state()

    def _dispatch_to_ui(self, fn: Callable[[], None]) -> bool:
        """Run panel updates on the Tk main thread when invoked off-thread."""
        if threading.current_thread().name != "MainThread" and hasattr(self, "after"):
            try:
                self.after(0, fn)
                return True
            except Exception:
                return False
        return False

    def set_jobs(self, jobs: list[Any]) -> None:
        """Update preview from a list of NormalizedJobRecord objects."""
        self.set_preview_jobs(jobs)

    def set_preview_jobs(self, jobs: list[NormalizedJobRecord] | None) -> None:
        """Render previews from NormalizedJobRecord objects."""
        logger.debug(f"[PreviewPanel] set_preview_jobs called with {len(jobs) if jobs else 0} jobs")
        if self._dispatch_to_ui(lambda: self.set_preview_jobs(jobs)):
            logger.debug("[PreviewPanel] Dispatched to UI thread, returning")
            return
        logger.debug(f"[PreviewPanel] Building summary entries from {len(jobs) if jobs else 0} jobs")
        summary_entries: list[Any] = []
        for job in jobs or []:
            summary_entries.append(self._summary_from_normalized_job(job))
        logger.debug(f"[PreviewPanel] Created {len(summary_entries)} summary entries, calling set_job_summaries")
        self.set_job_summaries(summary_entries)

    def _summary_from_normalized_job(self, job: NormalizedJobRecord) -> Any:
        unified = job.to_unified_summary() if isinstance(job, NJRSummaryPort) else None
        ui_summary = job.to_ui_summary() if isinstance(job, NJRUISummaryPort) else None

        positive_preview = ""
        negative_preview = ""
        if ui_summary:
            positive_preview = ui_summary.positive_preview or ""
            negative_preview = ui_summary.negative_preview or ""
        if not positive_preview and unified:
            positive_preview = unified.positive_prompt_preview or ""
        if not negative_preview and unified:
            negative_preview = unified.negative_prompt_preview or ""

        stage_display = "-"
        if unified and unified.stage_chain_labels:
            stage_display = " + ".join(unified.stage_chain_labels)
        elif ui_summary:
            stage_display = ui_summary.stages_display

        return SimpleNamespace(
            job_id=(unified.job_id if unified else getattr(ui_summary, "job_id", "")),
            label=(unified.base_model if unified else getattr(ui_summary, "label", "")),
            positive_preview=positive_preview,
            negative_preview=negative_preview,
            stages_display=stage_display,
            sampler_name=(unified.sampler_name if unified else ""),
            steps=(unified.steps if unified else None),
            cfg_scale=(unified.cfg_scale if unified else None),
            seed=getattr(job, "seed", None),
            base_model=(unified.base_model if unified else getattr(ui_summary, "label", "")),
            prompt_pack_name=getattr(job, "prompt_pack_name", ""),
            thumbnail_path=getattr(job, "thumbnail_path", None),
            output_paths=list(getattr(job, "output_paths", []) or []),
            source_job=job,
        )

    def set_job_summaries(self, summaries: list[Any]) -> None:
        """Render one or more JobUiSummary entries."""
        if self._dispatch_to_ui(lambda: self.set_job_summaries(summaries)):
            return
        start = time.perf_counter()
        self._job_summaries = list(summaries)
        last_summary = summaries[-1] if summaries else None
        render_signature = self._build_render_signature(last_summary, len(summaries))
        if last_summary is not None and render_signature == self._last_render_signature:
            self._current_preview_job = last_summary
            self._current_pack_name = self._resolve_pack_name(last_summary)
            self._current_show_preview = self._show_preview_var.get()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("set_job_summaries", elapsed_ms)
            return
        self._render_summary(last_summary, len(summaries))
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._record_refresh_metric("set_job_summaries", elapsed_ms)

    def update_from_job_draft(self, job_draft: Any | None) -> None:
        """Render preview directly from a JobDraft pack list."""
        if self._dispatch_to_ui(lambda: self.update_from_job_draft(job_draft)):
            return
        if job_draft is None:
            self.set_job_summaries([])
            self._update_action_states(None, None)
            return

        packs = getattr(job_draft, "packs", []) or []
        summaries: list[Any] = []
        for idx, pack in enumerate(packs):
            config = getattr(pack, "config_snapshot", {}) or {}
            stage_flags = getattr(pack, "stage_flags", {}) or {}
            stage_names = [name for name, enabled in stage_flags.items() if enabled]
            stages_display = " + ".join(stage_names) if stage_names else "txt2img"
            summaries.append(
                SimpleNamespace(
                    job_id=f"draft-{idx + 1}",
                    label=config.get("model") or getattr(pack, "pack_name", "-"),
                    positive_preview=getattr(pack, "prompt_text", "") or "",
                    negative_preview=getattr(pack, "negative_prompt_text", "") or "",
                    stages_display=stages_display,
                    sampler=config.get("sampler") or config.get("sampler_name") or "-",
                    steps=config.get("steps"),
                    cfg_scale=config.get("cfg_scale"),
                    seed=config.get("seed"),
                )
            )

        self.set_job_summaries(summaries)
        self._update_action_states(job_draft, summaries)

    def update_from_controls(self, sidebar: Any) -> None:
        """Update preview summary from sidebar controls."""
        enabled: list[str] = getattr(sidebar, "get_enabled_stages", lambda: [])()
        ordered = ["txt2img", "img2img", "adetailer", "upscale"]
        canonical = [stage for stage in ordered if stage in set(enabled)]
        stage_labels = {
            "txt2img": "txt2img",
            "img2img": "img2img",
            "adetailer": "ADetailer",
            "upscale": "upscale",
        }
        stages_text = " + ".join(stage_labels[stage] for stage in canonical) or "-"
        self.stage_summary_label.config(text=f"Stages: {stages_text}")

    def _summary_from_draft_summary(self, summary: Any) -> Any:
        return SimpleNamespace(
            prompt_short=summary.last_positive_prompt,
            negative_prompt_short=summary.last_negative_prompt,
            model="Manual",
            sampler="Manual",
            steps=None,
            cfg_scale=None,
            seed_display="?",
            variant_label="",
            batch_label="",
            stages_summary="-",
            randomizer_summary=None,
            has_refiner=False,
            has_hires=False,
            has_upscale=False,
            output_dir="",
            total_summary="Manual",
        )

    def _summary_from_pack_entry(self, entry: Any) -> Any:
        """PR-CORE-D/E: Convert PackJobEntry to display summary with all metadata.

        Returns SimpleNamespace with all fields needed for _render_summary.
        """
        config = entry.config_snapshot or {}
        prompt_text = entry.prompt_text or str(config.get("prompt") or "")
        negative = entry.negative_prompt_text or str(config.get("negative_prompt", "") or "")

        logger.debug(f"[PreviewPanel] _summary_from_pack_entry: prompt_text length={len(prompt_text)}")

        stage_flags = entry.stage_flags or {}
        stages = []
        stage_labels = {
            "txt2img": "txt2img",
            "img2img": "img2img",
            "adetailer": "ADetailer",
            "upscale": "upscale",
        }
        for stage, label in stage_labels.items():
            if stage_flags.get(stage):
                stages.append(label)
        if not stages:
            stages.append("txt2img")
        stages_display = " + ".join(stages)

        # Extract settings from txt2img config if available
        txt2img_config = config.get("txt2img", {})

        model = (
            txt2img_config.get("model")
            or config.get("model")
            or config.get("model_name")
            or entry.pack_name
            or "unknown"
        )
        sampler = txt2img_config.get("sampler_name") or config.get("sampler") or "DPM++ 2M"
        steps = txt2img_config.get("steps") or config.get("steps") or 20
        cfg_scale = txt2img_config.get("cfg_scale") or config.get("cfg_scale") or 7.0
        seed = txt2img_config.get("seed") or config.get("seed") or -1

        label = f"{model}"

        logger.debug(
            f"[PreviewPanel] Created summary: label={label}, sampler={sampler}, steps={steps}, cfg={cfg_scale}, stages={stages_display}"
        )

        # Return SimpleNamespace so _render_summary can access all fields
        return SimpleNamespace(
            job_id=entry.pack_id,
            label=label,
            positive_preview=self._truncate_text(prompt_text, limit=120),
            negative_preview=self._truncate_text(negative, limit=120) if negative else "",
            stages_display=stages_display,
            sampler_name=sampler,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            base_model=model,
        )

    @staticmethod
    def _truncate_text(value: str, limit: int) -> str:
        if not value:
            return ""
        return value if len(value) <= limit else value[:limit] + "..."

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_stage_chain(summary: UnifiedJobSummary | None) -> str:
        """PR-CORE-D: Format stage chain as human-friendly labels.

        Args:
            summary: UnifiedJobSummary with stage_chain_labels

        Returns:
            Formatted string like "txt2img → img2img → adetailer → upscale"
        """
        if not summary or not hasattr(summary, "stage_chain_labels"):
            return "-"

        labels = getattr(summary, "stage_chain_labels", None)
        if not labels:
            return "-"

        return " → ".join(labels)

    @staticmethod
    def _format_matrix_slots(summary: UnifiedJobSummary | None) -> str:
        """PR-CORE-D: Format matrix slot values for display.

        Args:
            summary: UnifiedJobSummary with matrix_slot_values

        Returns:
            Formatted string like "env: volcanic lair, lighting: hellish"
        """
        if not summary or not hasattr(summary, "matrix_slot_values"):
            return ""

        slots = getattr(summary, "matrix_slot_values", None)
        if not slots or not isinstance(slots, dict):
            return ""

        # Format as "key: value" pairs
        pairs = [f"{key}: {value}" for key, value in slots.items()]
        return ", ".join(pairs) if pairs else ""

    @staticmethod
    def _format_pack_provenance(summary: UnifiedJobSummary | None) -> str:
        """PR-CORE-D: Format PromptPack provenance for display.

        Args:
            summary: UnifiedJobSummary with prompt_pack_name and row_index

        Returns:
            Formatted string like "Pack: Angelic Warriors (Row 3)"
        """
        if not summary:
            return "Pack: -"

        pack_name = getattr(summary, "prompt_pack_name", None) or "Unknown"
        row_index = getattr(summary, "prompt_pack_row_index", None)

        if row_index is not None:
            return f"Pack: {pack_name} (Row {row_index + 1})"
        else:
            return f"Pack: {pack_name}"

    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update action button availability based on app_state."""
        start = time.perf_counter()
        if app_state is None:
            app_state = self.app_state
        job_draft = getattr(app_state, "job_draft", None)
        preview_jobs = getattr(app_state, "preview_jobs", None)
        self._update_action_states(job_draft, preview_jobs)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._record_refresh_metric("update_from_app_state", elapsed_ms)

    def _bind_app_state_previews(self) -> None:
        logger.debug(f"[PreviewPanel] _bind_app_state_previews called, app_state={self.app_state}")
        if not self.app_state or not hasattr(self.app_state, "subscribe"):
            logger.debug(f"[PreviewPanel] Cannot subscribe - app_state={self.app_state}, has_subscribe={hasattr(self.app_state, 'subscribe') if self.app_state else False}")
            return
        if self._manage_app_state_subscriptions:
            try:
                logger.debug("[PreviewPanel] Subscribing to preview_jobs changes")
                self.app_state.subscribe("preview_jobs", self._on_preview_jobs_changed)
                logger.debug("[PreviewPanel] Successfully subscribed to preview_jobs")
            except Exception as e:
                logger.debug(f"[PreviewPanel] Failed to subscribe: {e}")
                pass
        try:
            self.app_state.subscribe("content_visibility_mode", self._on_content_visibility_mode_changed)
        except Exception:
            pass
        if self._manage_app_state_subscriptions:
            self._on_preview_jobs_changed()

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._content_visibility_mode = str(
            mode or getattr(getattr(self, "app_state", None), "content_visibility_mode", "nsfw") or "nsfw"
        )
        last_summary = self._job_summaries[-1] if self._job_summaries else None
        self._render_summary(last_summary, len(self._job_summaries))

    def _on_content_visibility_mode_changed(self) -> None:
        self.on_content_visibility_mode_changed()

    def _on_preview_jobs_changed(self) -> None:
        logger.debug("[PreviewPanel] _on_preview_jobs_changed called")
        if not self.app_state:
            logger.debug("[PreviewPanel] No app_state, returning")
            return
        records = getattr(self.app_state, "preview_jobs", None)
        logger.debug(f"[PreviewPanel] Got {len(records) if records else 0} preview jobs from app_state")
        self.set_preview_jobs(records)

    def _build_render_signature(self, summary: Any | None, total: int) -> tuple[Any, ...]:
        summary_obj = self._normalize_summary(summary)
        if summary_obj is None:
            return (
                "empty",
                int(total),
                self._content_visibility_mode,
                bool(self._show_preview_var.get()),
            )
        pack_name = self._resolve_pack_name(summary_obj, summary)
        return (
            "summary",
            int(total),
            self._content_visibility_mode,
            bool(self._show_preview_var.get()),
            str(getattr(summary_obj, "job_id", "") or ""),
            str(getattr(summary_obj, "label", None) or getattr(summary_obj, "base_model", "-") or "-"),
            str(getattr(summary_obj, "positive_preview", "") or ""),
            str(getattr(summary_obj, "negative_preview", "") or ""),
            str(getattr(summary_obj, "stages_display", "-") or "-"),
            str(getattr(summary_obj, "sampler_name", getattr(summary_obj, "sampler", "-")) or "-"),
            self._coerce_int(getattr(summary_obj, "steps", None)),
            self._coerce_float(getattr(summary_obj, "cfg_scale", None)),
            getattr(summary_obj, "seed", None),
            getattr(summary_obj, "actual_seed", None),
            getattr(summary_obj, "resolved_seed", None),
            str(pack_name or ""),
            self._make_thumbnail_lookup_key(summary, pack_name),
        )

    @staticmethod
    def _set_label_text(widget: ttk.Label, value: str) -> None:
        if str(widget.cget("text") or "") == value:
            return
        widget.config(text=value)

    def _resolve_pack_name(self, summary_obj: Any | None, raw_summary: Any | None = None) -> str | None:
        candidate = getattr(summary_obj, "pack_name", None) or getattr(summary_obj, "prompt_pack_name", None)
        if candidate:
            return str(candidate)
        candidate = getattr(raw_summary, "pack_name", None) or getattr(raw_summary, "prompt_pack_name", None)
        if candidate:
            return str(candidate)
        candidate = getattr(summary_obj, "label", None) or getattr(raw_summary, "label", None)
        return str(candidate) if candidate else None

    def _render_summary(self, summary: Any | None, total: int) -> None:
        start = time.perf_counter()
        logger.debug(f"[PreviewPanel] _render_summary called: summary={bool(summary)}, total={total}")
        render_signature = self._build_render_signature(summary, total)

        if summary is None:
            logger.debug("[PreviewPanel] Rendering empty state")
            self._set_label_text(self.job_count_label, "No job selected")
            self._set_label_text(self.visibility_banner, "")
            self._set_text_widget(self.prompt_text, "", cache_attr_name="_prompt_text_value")
            self._set_text_widget(
                self.negative_prompt_text,
                "",
                cache_attr_name="_negative_prompt_text_value",
            )
            self._set_label_text(self.model_label, "Model: -")
            self._set_label_text(self.sampler_label, "Sampler: -")
            self._set_label_text(self.steps_label, "Steps: -")
            self._set_label_text(self.cfg_label, "CFG: -")
            self._set_label_text(self.seed_label, "Seed: -")
            self._set_label_text(self.stage_summary_label, "Stages: -")
            self._set_label_text(
                self.stage_flags_label,
                self._format_flags(refiner=False, hires=False, upscale=False),
            )
            self._set_label_text(self.randomizer_label, "Randomizer: OFF")
            self._set_label_text(self.learning_metadata_label, "Learning metadata: N/A")
            # Clear thumbnail when no job
            self._current_preview_job = None
            self._current_pack_name = None
            # PR-PREVIEW-001: Preserve checkbox state, don't reset to True
            self._current_show_preview = self._show_preview_var.get()
            self._update_thumbnail()
            self._last_render_signature = render_signature
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_render_summary", elapsed_ms)
            return

        summary_obj = self._normalize_summary(summary)
        if summary_obj is None:
            logger.debug("[PreviewPanel] _normalize_summary returned None")
            self._set_label_text(self.job_count_label, "No job selected")
            self._set_label_text(self.visibility_banner, "")
            self._update_thumbnail()
            self._last_render_signature = render_signature
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_render_summary", elapsed_ms)
            return

        job_text = f"Job: {total}" if total == 1 else f"Jobs: {total}"
        logger.debug(f"[PreviewPanel] Setting job_count_label to: {job_text}")
        self._set_label_text(self.job_count_label, job_text)

        positive = getattr(summary_obj, "positive_preview", "") or ""
        negative = getattr(summary_obj, "negative_preview", "") or ""
        resolver = ContentVisibilityResolver(self._content_visibility_mode)
        positive = resolver.redact_text(
            positive,
            item={
                "positive_preview": positive,
                "negative_preview": negative,
                "name": getattr(summary_obj, "prompt_pack_name", ""),
            },
        )
        negative = resolver.redact_text(
            negative,
            item={
                "positive_preview": getattr(summary_obj, "positive_preview", "") or "",
                "negative_preview": getattr(summary_obj, "negative_preview", "") or "",
                "name": getattr(summary_obj, "prompt_pack_name", ""),
            },
        )
        self._set_label_text(self.visibility_banner, "")
        logger.debug(f"[PreviewPanel] Positive preview length: {len(positive)}, Negative: {len(negative)}")
        self._set_text_widget(self.prompt_text, positive, cache_attr_name="_prompt_text_value")
        self._set_text_widget(
            self.negative_prompt_text,
            negative,
            cache_attr_name="_negative_prompt_text_value",
        )

        model_text = getattr(summary_obj, "label", None) or getattr(summary_obj, "base_model", "-")
        logger.debug(f"[PreviewPanel] Model: {model_text}")
        self._set_label_text(self.model_label, f"Model: {model_text}")
        sampler_text = getattr(summary_obj, "sampler_name", getattr(summary_obj, "sampler", "-"))
        logger.debug(f"[PreviewPanel] Sampler: {sampler_text}")
        self._set_label_text(self.sampler_label, f"Sampler: {sampler_text}")
        steps_value = self._coerce_int(getattr(summary_obj, "steps", None))
        logger.debug(f"[PreviewPanel] Steps: {steps_value}")
        self._set_label_text(
            self.steps_label,
            f"Steps: {steps_value if steps_value is not None else '-'}",
        )
        cfg_value = self._coerce_float(getattr(summary_obj, "cfg_scale", None))
        cfg_text = f"{cfg_value:.1f}" if cfg_value is not None else "-"
        logger.debug(f"[PreviewPanel] CFG: {cfg_text}")
        self._set_label_text(self.cfg_label, f"CFG: {cfg_text}")
        # PR-PIPE-007: Show resolved seed when available
        requested_seed = getattr(summary_obj, "seed", None)
        actual_seed = getattr(summary_obj, "actual_seed", None) or getattr(summary_obj, "resolved_seed", None)
        seed_text = format_seed_display(requested_seed, actual_seed)
        self._set_label_text(self.seed_label, f"Seed: {seed_text}")

        stages_text = getattr(summary_obj, "stages_display", "-")
        self._set_label_text(self.stage_summary_label, f"Stages: {stages_text}")
        self._set_label_text(
            self.stage_flags_label,
            self._format_flags(refiner=False, hires=False, upscale=False),
        )

        # PR-CORE-D: Display randomization/matrix metadata if available
        randomizer_text = "Randomizer: OFF"
        if isinstance(summary, UnifiedJobSummary):
            matrix_slots = self._format_matrix_slots(summary)
            if matrix_slots:
                randomizer_text = f"Randomizer: ON ({matrix_slots})"
            variant_idx = getattr(summary, "variant_index", None)
            batch_idx = getattr(summary, "batch_index", None)
            if variant_idx is not None or batch_idx is not None:
                variant_text = f"v{variant_idx}" if variant_idx is not None else "-"
                batch_text = f"b{batch_idx}" if batch_idx is not None else "-"
                randomizer_text += f" [{variant_text}/{batch_text}]"

        self._set_label_text(self.randomizer_label, randomizer_text)
        self._set_label_text(self.learning_metadata_label, "Learning metadata: N/A")

        # Update thumbnail with pack info from summary
        pack_name = self._resolve_pack_name(summary_obj, summary)
        
        # PR-PREVIEW-001: Don't override user's checkbox preference from pack config
        # The checkbox state is the authoritative source, not the pack
        # Store current state for checkbox handler
        self._current_preview_job = summary
        self._current_pack_name = pack_name
        self._current_show_preview = self._show_preview_var.get()

        # Load thumbnail
        self._update_thumbnail(summary, pack_name, self._show_preview_var.get())
        self._last_render_signature = render_signature
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._record_refresh_metric("_render_summary", elapsed_ms)

    def _normalize_summary(self, summary: Any) -> Any | None:
        if summary is None:
            return None
        if isinstance(summary, UnifiedJobSummary):
            return SimpleNamespace(
                job_id=summary.job_id,
                label=summary.base_model,
                positive_preview=summary.positive_prompt_preview or "",
                negative_preview=summary.negative_prompt_preview or "",
                stages_display=" + ".join(summary.stage_chain_labels or ["txt2img"]),
                sampler_name=summary.sampler_name,
                steps=summary.steps,
                cfg_scale=summary.cfg_scale,
                seed=getattr(summary, "seed", None),
                actual_seed=getattr(summary, "actual_seed", None),
                resolved_seed=getattr(summary, "resolved_seed", None),
                base_model=summary.base_model,
                pack_name=getattr(summary, "prompt_pack_name", None),
                prompt_pack_name=getattr(summary, "prompt_pack_name", None),
            )
        return summary

    @staticmethod
    def _format_flags(*, refiner: bool, hires: bool, upscale: bool) -> str:
        parts = [
            f"Refiner: {'ON' if refiner else 'OFF'}",
            f"HiRes: {'ON' if hires else 'OFF'}",
            f"Upscale: {'ON' if upscale else 'OFF'}",
        ]
        return " · ".join(parts)

    def _set_text_widget(
        self,
        widget: tk.Text,
        value: str,
        *,
        cache_attr_name: str | None = None,
    ) -> None:
        if cache_attr_name and getattr(self, cache_attr_name, None) == value:
            return
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        if value:
            widget.insert(tk.END, value)
        widget.config(state=tk.DISABLED)
        if cache_attr_name:
            setattr(self, cache_attr_name, value)

    def _on_add_to_queue(self) -> None:
        """Move the draft job into the queue."""
        if not self.controller:
            return
        try:
            add_to_queue_v2 = getattr(self.controller, "on_add_job_to_queue_v2", None)
            if callable(add_to_queue_v2):
                add_to_queue_v2()
            else:
                self.controller.on_add_to_queue()
        except ValueError as exc:
            logger.debug(f"[PreviewPanel] _on_add_to_queue validation error: {exc}")
        except Exception as exc:
            logger.debug(f"[PreviewPanel] _on_add_to_queue unexpected error: {exc}")

    def _on_clear_draft(self) -> None:
        """Clear the current draft job metadata."""
        if not self.controller:
            return
        self.controller.on_clear_draft()

    def _on_details_clicked(self) -> None:
        """Show detailed information about the preview jobs."""
        if not self._job_summaries and self.app_state is None:
            show_log_trace_panel = getattr(self.controller, "show_log_trace_panel", None)
            if callable(show_log_trace_panel):
                show_log_trace_panel()
                return
        self._show_preview_details()

    def _update_action_states(
        self,
        job_draft: Any | None,
        preview_jobs: list[NormalizedJobRecord] | None = None,
    ) -> None:
        """Enable/disable action buttons based on draft content."""
        has_draft = False
        packs = []
        packs: list[Any] = []
        has_parts = False
        if job_draft is not None:
            packs = getattr(job_draft, "packs", [])
            part_summary = getattr(job_draft, "summary", None)
            has_parts = bool(getattr(part_summary, "part_count", 0))
            has_draft = bool(packs) or has_parts
        has_preview = bool(preview_jobs) and has_draft
        logger.debug(
            f"[PreviewPanel] _update_action_states: packs={len(packs)}, has_parts={has_parts}, has_draft={has_draft}"
        )
        can_queue = has_draft and has_preview
        state = ["!disabled"] if can_queue else ["disabled"]
        logger.debug(f"[PreviewPanel] Setting button state to: {state}")
        self.add_to_queue_button.state(state)
        self.clear_draft_button.state(state)
    def _show_preview_details(self) -> None:
        """Display a detailed breakdown of what will be queued."""
        if not self._job_summaries and not self.app_state:
            self._show_info_dialog("No Preview Available", "No jobs are currently in the preview.")
            return

        # Get job draft and preview jobs
        job_draft = getattr(self.app_state, "job_draft", None) if self.app_state else None
        preview_jobs = getattr(self.app_state, "preview_jobs", None) if self.app_state else None

        if not job_draft and not preview_jobs:
            self._show_info_dialog("No Preview Available", "No jobs are currently in the preview.")
            return

        # Build detailed information
        details_lines = []
        
        # Summary header
        packs = getattr(job_draft, "packs", []) if job_draft else []
        total_jobs = len(preview_jobs) if preview_jobs else len(packs)
        details_lines.append(f"PREVIEW SUMMARY")
        details_lines.append(f"{'=' * 60}")
        details_lines.append(f"Total Jobs to Queue: {total_jobs}")
        details_lines.append("")

        # Calculate total images
        total_images = 0
        if preview_jobs:
            for job in preview_jobs:
                config = getattr(job, "config", {}) or {}
                batch_size = config.get("batch_size", 1)
                n_iter = config.get("n_iter", 1)
                total_images += batch_size * n_iter
        elif packs:
            for pack in packs:
                config = getattr(pack, "config_snapshot", {}) or {}
                txt2img_config = config.get("txt2img", config)
                batch_size = txt2img_config.get("batch_size", 1)
                n_iter = txt2img_config.get("n_iter", 1)
                total_images += batch_size * n_iter

        details_lines.append(f"Total Images: {total_images}")
        details_lines.append("")

        # Per-job breakdown
        details_lines.append("JOB BREAKDOWN")
        details_lines.append(f"{'-' * 60}")

        if preview_jobs:
            for idx, job in enumerate(preview_jobs, 1):
                details_lines.extend(self._format_job_details(job, idx))
        elif packs:
            for idx, pack in enumerate(packs, 1):
                details_lines.extend(self._format_pack_details(pack, idx))

        # Show in dialog
        details_text = "\n".join(details_lines)
        self._show_info_dialog("Preview Details", details_text, width=700, height=500)

    def _format_job_details(self, job: NormalizedJobRecord, index: int) -> list[str]:
        """Format details for a single NormalizedJobRecord."""
        lines = []
        lines.append(f"\nJob #{index}: {job.job_id}")
        
        config = getattr(job, "config", {}) or {}
        
        # Model and settings
        model = config.get("model", "unknown")
        sampler = config.get("sampler_name", config.get("sampler", "unknown"))
        scheduler = config.get("scheduler", "unknown")
        steps = config.get("steps", "?")
        cfg = config.get("cfg_scale", "?")
        batch_size = config.get("batch_size", 1)
        n_iter = config.get("n_iter", 1)
        images_per_job = batch_size * n_iter
        
        lines.append(f"  Model: {model}")
        lines.append(f"  Sampler: {sampler} / Scheduler: {scheduler}")
        lines.append(f"  Steps: {steps}, CFG: {cfg}")
        lines.append(f"  Batch Size: {batch_size}, Iterations: {n_iter} ({images_per_job} images)")
        
        # Stages
        stages = []
        if getattr(job, "stage_chain", None):
            stage_names = [s.get("name", "?") for s in job.stage_chain]
            stages = stage_names
        else:
            stages = ["txt2img"]  # default
            
        lines.append(f"  Stages: {' → '.join(stages)}")
        
        # Special features
        features = []
        if config.get("enable_hr"):
            hr_upscaler = config.get("hr_upscaler", "?")
            hr_scale = config.get("hr_scale", "?")
            features.append(f"Hires Fix ({hr_upscaler} @ {hr_scale}x)")
        if config.get("refiner_checkpoint"):
            features.append(f"Refiner ({config.get('refiner_checkpoint')})")
        if features:
            lines.append(f"  Features: {', '.join(features)}")
        
        # Prompts (truncated)
        prompt = getattr(job, "prompt", "") or config.get("prompt", "")
        negative = getattr(job, "negative_prompt", "") or config.get("negative_prompt", "")
        lines.append(f"  Prompt: {self._truncate_text(prompt, 80)}")
        if negative:
            lines.append(f"  Negative: {self._truncate_text(negative, 80)}")
        
        return lines

    def _format_pack_details(self, pack: Any, index: int) -> list[str]:
        """Format details for a single pack."""
        lines = []
        pack_name = getattr(pack, "pack_name", f"Pack {index}")
        lines.append(f"\nPack #{index}: {pack_name}")
        
        config = getattr(pack, "config_snapshot", {}) or {}
        txt2img_config = config.get("txt2img", config)
        
        # Model and settings
        model = txt2img_config.get("model", config.get("model", "unknown"))
        sampler = txt2img_config.get("sampler_name", config.get("sampler", "unknown"))
        scheduler = txt2img_config.get("scheduler", config.get("scheduler", "unknown"))
        steps = txt2img_config.get("steps", config.get("steps", "?"))
        cfg = txt2img_config.get("cfg_scale", config.get("cfg_scale", "?"))
        batch_size = txt2img_config.get("batch_size", config.get("batch_size", 1))
        n_iter = txt2img_config.get("n_iter", config.get("n_iter", 1))
        images_per_pack = batch_size * n_iter
        
        lines.append(f"  Model: {model}")
        lines.append(f"  Sampler: {sampler} / Scheduler: {scheduler}")
        lines.append(f"  Steps: {steps}, CFG: {cfg}")
        lines.append(f"  Batch Size: {batch_size}, Iterations: {n_iter} ({images_per_pack} images)")
        
        # Stages
        stage_flags = getattr(pack, "stage_flags", {}) or {}
        stages = []
        stage_order = ["txt2img", "img2img", "adetailer", "upscale"]
        for stage in stage_order:
            if stage_flags.get(stage):
                stages.append(stage)
        if not stages:
            stages = ["txt2img"]
        lines.append(f"  Stages: {' → '.join(stages)}")
        
        # Special features
        features = []
        if txt2img_config.get("enable_hr", config.get("enable_hr")):
            hr_upscaler = txt2img_config.get("hr_upscaler", config.get("hr_upscaler", "?"))
            hr_scale = txt2img_config.get("hr_scale", config.get("hr_scale", "?"))
            features.append(f"Hires Fix ({hr_upscaler} @ {hr_scale}x)")
        if txt2img_config.get("refiner_checkpoint", config.get("refiner_checkpoint")):
            refiner = txt2img_config.get("refiner_checkpoint", config.get("refiner_checkpoint"))
            features.append(f"Refiner ({refiner})")
        if features:
            lines.append(f"  Features: {', '.join(features)}")
        
        # Prompts (truncated)
        prompt = getattr(pack, "prompt_text", "") or txt2img_config.get("prompt", "")
        negative = getattr(pack, "negative_prompt_text", "") or txt2img_config.get("negative_prompt", "")
        lines.append(f"  Prompt: {self._truncate_text(prompt, 80)}")
        if negative:
            lines.append(f"  Negative: {self._truncate_text(negative, 80)}")
        
        return lines

    def _show_info_dialog(self, title: str, message: str, width: int = 500, height: int = 300) -> None:
        """Show a dialog with detailed information."""
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry(f"{width}x{height}")
        dialog.transient(self.winfo_toplevel())
        
        # Text widget with scrollbar
        text_frame = ttk.Frame(dialog)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        text_widget = tk.Text(
            text_frame,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="solid",
            borderwidth=1,
        )
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        text_widget.insert("1.0", message)
        text_widget.configure(state="disabled")
        
        # Close button
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        close_button = ttk.Button(
            button_frame,
            text="Close",
            command=dialog.destroy,
        )
        close_button.pack(side=tk.RIGHT)
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _find_recent_thumbnail(self, job: Any, pack_name: str | None = None) -> Any:
        """Find a recent image that matches this job's config for preview."""
        from pathlib import Path

        # Try to get output directory from job config
        output_dir = get_output_root("output", create=False)
        if not output_dir.exists():
            return None

        # Get pack name or model for matching
        model_name = None

        if pack_name is None and hasattr(job, "prompt_pack_name"):
            pack_name = job.prompt_pack_name

        if hasattr(job, "to_unified_summary"):
            try:
                summary = job.to_unified_summary()
                pack_name = pack_name or getattr(summary, "prompt_pack_name", None)
                model_name = getattr(summary, "model_name", None) or getattr(summary, "base_model", None)
            except Exception:
                pass

        # Look for recent outputs with matching pack/model
        try:
            # List recent run directories
            run_dirs = iter_output_run_dirs(output_dir)[:10]

            for run_dir in run_dirs:
                matches_pack = bool(pack_name and pack_name.lower() in run_dir.name.lower())
                matches_model = bool(model_name and model_name.lower() in run_dir.name.lower())

                if matches_pack or matches_model:
                    # Find first image in directory
                    for img_path in sorted(run_dir.glob("*.png"))[:1]:
                        return img_path

                    # Check txt2img subdirectory
                    txt2img_dir = run_dir / "txt2img"
                    if txt2img_dir.exists():
                        for img_path in sorted(txt2img_dir.glob("*.png"))[:1]:
                            return img_path

                # Fallback: return the most recent image if no pack/model match
                all_pngs = sorted(run_dir.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
                if all_pngs:
                    return all_pngs[0]

        except Exception:
            pass

        return None

    def _find_immediate_output_image(
        self,
        summary: UnifiedJobSummary | Any | None,
        *,
        _depth: int = 0,
    ) -> Path | None:
        """Return explicit output paths without scanning output directories."""
        if summary is None:
            return None
        if _depth >= 8:
            return None

        source_job = getattr(summary, "source_job", None)
        if source_job is not None and source_job is not summary:
            source_image = self._find_immediate_output_image(source_job, _depth=_depth + 1)
            if source_image and source_image.exists():
                return source_image

        thumbnail_path = getattr(summary, "thumbnail_path", None)
        if isinstance(thumbnail_path, (str, os.PathLike)):
            thumbnail = Path(thumbnail_path)
            if thumbnail.exists():
                return thumbnail

        output_paths = getattr(summary, "output_paths", None)
        if isinstance(output_paths, list):
            for candidate in reversed(output_paths):
                if isinstance(candidate, (str, os.PathLike)):
                    image_path = Path(candidate)
                    if image_path.exists():
                        return image_path

        result = getattr(summary, "result", None)
        if isinstance(result, dict):
            metadata = result.get("metadata")
            if isinstance(metadata, dict):
                candidate = metadata.get("path") or metadata.get("output_path")
                if isinstance(candidate, (str, os.PathLike)) and Path(candidate).exists():
                    return Path(candidate)
            if isinstance(metadata, list):
                for entry in reversed(metadata):
                    if isinstance(entry, dict):
                        candidate = entry.get("path") or entry.get("output_path")
                        if isinstance(candidate, (str, os.PathLike)) and Path(candidate).exists():
                            return Path(candidate)

        return None

    def _find_latest_output_image(self, summary: UnifiedJobSummary | Any | None) -> Path | None:
        """Inspect a summary/result object to find the latest output image."""
        immediate = self._find_immediate_output_image(summary)
        if immediate is not None:
            return immediate

        # If the summary has a job_id, look for a run folder named with it
        job_id = getattr(summary, "job_id", None)
        output_dir = get_output_root("output", create=False)
        if job_id and output_dir.exists():
            job_dirs = sorted(
                [p for p in iter_output_run_dirs(output_dir) if job_id in p.name],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for run_dir in job_dirs:
                candidates = sorted(run_dir.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    return candidates[0]

        return None

    def _make_thumbnail_lookup_key(self, job: Any | None, pack_name: str | None) -> tuple[str, ...]:
        summary = job
        output_paths = getattr(summary, "output_paths", None)
        output_values: tuple[str, ...] = ()
        if isinstance(output_paths, (list, tuple)):
            output_values = tuple(str(path) for path in output_paths if path)
        thumbnail_path = str(getattr(summary, "thumbnail_path", "") or "")
        result = getattr(summary, "result", None)
        metadata_paths: list[str] = []
        if isinstance(result, dict):
            metadata = result.get("metadata")
            if isinstance(metadata, dict):
                candidate = metadata.get("path") or metadata.get("output_path")
                if candidate:
                    metadata_paths.append(str(candidate))
            elif isinstance(metadata, list):
                for entry in metadata:
                    if isinstance(entry, dict):
                        candidate = entry.get("path") or entry.get("output_path")
                        if candidate:
                            metadata_paths.append(str(candidate))
        return (
            str(getattr(summary, "job_id", "") or ""),
            str(pack_name or getattr(summary, "prompt_pack_name", "") or ""),
            str(getattr(summary, "label", "") or getattr(summary, "base_model", "") or ""),
            thumbnail_path,
            *output_values,
            *metadata_paths,
        )

    def _get_cached_thumbnail_lookup(self, request_key: tuple[str, ...]) -> Path | None | object:
        cached = self._thumbnail_lookup_cache.get(request_key)
        if cached is None:
            return _THUMBNAIL_CACHE_MISS
        cached_at, cached_path = cached
        ttl = (
            self.POSITIVE_THUMBNAIL_CACHE_TTL_S
            if cached_path
            else self.NEGATIVE_THUMBNAIL_CACHE_TTL_S
        )
        if (time.monotonic() - cached_at) > ttl:
            self._thumbnail_lookup_cache.pop(request_key, None)
            return _THUMBNAIL_CACHE_MISS
        if not cached_path:
            return None
        candidate = Path(cached_path)
        if not candidate.exists():
            self._thumbnail_lookup_cache.pop(request_key, None)
            return _THUMBNAIL_CACHE_MISS
        return candidate

    def _schedule_thumbnail_lookup(
        self,
        job: Any,
        pack_name: str | None,
        request_key: tuple[str, ...],
    ) -> None:
        if request_key in self._thumbnail_lookup_pending:
            return
        self._thumbnail_lookup_pending.add(request_key)

        def _lookup() -> None:
            resolved: Path | None = None
            try:
                resolved = self._find_latest_output_image(job)
                if resolved is None:
                    recent = self._find_recent_thumbnail(job, pack_name)
                    resolved = Path(recent) if recent else None
            except Exception:
                resolved = None

            def _apply() -> None:
                self._apply_thumbnail_lookup_result(request_key, resolved)

            try:
                self.after(0, _apply)
            except Exception:
                self._thumbnail_lookup_pending.discard(request_key)

        from src.utils.thread_registry import get_thread_registry

        registry = get_thread_registry()
        registry.spawn(
            target=_lookup,
            name=f"Preview-ThumbLookup-{id(self)}",
            daemon=False,
            purpose="Resolve preview thumbnail candidates without blocking Tk",
        )

    def _apply_thumbnail_lookup_result(
        self,
        request_key: tuple[str, ...],
        resolved_path: Path | None,
    ) -> None:
        self._thumbnail_lookup_pending.discard(request_key)
        self._thumbnail_lookup_cache[request_key] = (
            time.monotonic(),
            str(resolved_path) if resolved_path else None,
        )

        current_key = self._make_thumbnail_lookup_key(
            getattr(self, "_current_preview_job", None),
            getattr(self, "_current_pack_name", None),
        )
        if request_key != current_key or not self._show_preview_var.get():
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            pass

        if resolved_path and resolved_path.exists():
            self.thumbnail.set_image_from_path(resolved_path)
        else:
            self.thumbnail.clear()

    def _update_thumbnail(self, job: Any | None = None, pack_name: str | None = None, show_preview: bool = True) -> None:
        """Update the thumbnail display for the current preview job."""
        start = time.perf_counter()
        # Check if preview is disabled
        if not show_preview or not self._show_preview_var.get():
            self.thumbnail.clear()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_update_thumbnail", elapsed_ms)
            return

        if job is None:
            self.thumbnail.clear()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_update_thumbnail", elapsed_ms)
            return

        # Prefer explicit output path from summary/result if available.
        explicit_path = self._find_immediate_output_image(job)
        if explicit_path:
            self.thumbnail.set_image_from_path(explicit_path)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_update_thumbnail", elapsed_ms)
            return

        request_key = self._make_thumbnail_lookup_key(job, pack_name)
        cached_path = self._get_cached_thumbnail_lookup(request_key)
        if cached_path is not _THUMBNAIL_CACHE_MISS:
            if cached_path is None:
                self.thumbnail.clear()
            else:
                self.thumbnail.set_image_from_path(cached_path)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._record_refresh_metric("_update_thumbnail", elapsed_ms)
            return

        self.thumbnail.set_loading()
        self._schedule_thumbnail_lookup(job, pack_name, request_key)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._record_refresh_metric("_update_thumbnail", elapsed_ms)

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

    def _on_preview_checkbox_changed(self) -> None:
        """Handle preview checkbox state change."""
        enabled = self._show_preview_var.get()

        # Update thumbnail visibility
        if enabled and self._job_summaries:
            # Reload thumbnail for current job
            first_job = getattr(self, "_current_preview_job", None)
            pack_name = getattr(self, "_current_pack_name", None)
            # PR-PREVIEW-001: Use current checkbox state, not stored value
            show_preview = self._show_preview_var.get()
            self._update_thumbnail(first_job, pack_name, show_preview)
        else:
            self.thumbnail.clear()

        # Save preference to pack config if available
        if self.app_state:
            job_draft = getattr(self.app_state, "job_draft", None)
            if job_draft:
                packs = getattr(job_draft, "packs", [])
                if packs:
                    # Update show_preview for the current pack
                    # This would require storing it in the pack model
                    pass
        
        # PR-PERSIST-001: Save state on checkbox change
        self.save_state()

    def update_with_summary(self, summary: UnifiedJobSummary | None) -> None:
        """Update the preview thumbnail based on a UnifiedJobSummary.
        
        PR-GUI-DATA-005: Load and display latest output image as thumbnail.
        """
        if self._dispatch_to_ui(lambda: self.update_with_summary(summary)):
            return
        self._current_preview_job = summary
        self._current_pack_name = getattr(summary, "prompt_pack_name", None) if summary else None
        # PR-PREVIEW-001: Preserve checkbox state, don't hardcode True
        self._current_show_preview = self._show_preview_var.get()
        self._update_thumbnail(summary, self._current_pack_name, self._show_preview_var.get())

    # PR-PERSIST-001: State persistence methods
    def save_state(self) -> None:
        """Save preview panel state to disk."""
        try:
            state = {
                "show_preview": self._show_preview_var.get(),
                "schema_version": "2.6"
            }
            PREVIEW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PREVIEW_STATE_PATH.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save preview panel state: {e}")

    def restore_state(self) -> None:
        """Restore preview panel state from disk."""
        if not PREVIEW_STATE_PATH.exists():
            return
        
        try:
            state = json.loads(PREVIEW_STATE_PATH.read_text())
            
            # Validate schema version
            if state.get("schema_version") != "2.6":
                logger.warning("Unsupported preview state schema, ignoring")
                return
            
            show_preview = bool(state.get("show_preview", False))
            self._show_preview_var.set(show_preview)
            logger.debug("Restored preview panel state")
        except Exception as e:
            logger.warning(f"Failed to restore preview panel state: {e}")

    def destroy(self) -> None:
        """Override destroy to save state before cleanup."""
        try:
            self.save_state()
        except Exception:
            pass
        super().destroy()
