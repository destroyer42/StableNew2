"""Preview panel for GUI v2 (PR-CORE1-A3: NJR-only display).

This panel displays job previews using NormalizedJobRecord and UnifiedJobSummary.
All display data comes from NJR snapshots, never from pipeline_config.
"""

from __future__ import annotations

import json
import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

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

logger = logging.getLogger(__name__)

# PR-PERSIST-001: Preview panel state persistence
PREVIEW_STATE_PATH = Path("state") / "preview_panel_state.json"


class PreviewPanelV2(ttk.Frame):
    """Container for preview/inspector content (structure only)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self._job_summaries: list[JobUiSummary] = []

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

        self.body = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
        self.body.pack(fill=tk.BOTH, expand=True)

        # Add thumbnail widget and preview checkbox
        self.thumbnail_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        self.thumbnail_frame.pack(fill="x", pady=(0, 8))

        self.thumbnail = ThumbnailWidget(
            self.thumbnail_frame,
            width=150,
            height=150,
            placeholder_text="No Preview",
        )
        self.thumbnail.pack(anchor="center")

        # Checkbox to enable/disable preview thumbnails
        self._show_preview_var = tk.BooleanVar(value=True)
        self.preview_checkbox = ttk.Checkbutton(
            self.thumbnail_frame,
            text="Show preview thumbnails",
            variable=self._show_preview_var,
            command=self._on_preview_checkbox_changed,
        )
        self.preview_checkbox.pack(anchor="center", pady=(4, 0))

        self.job_count_label = ttk.Label(
            self.body, text="No job selected", style=STATUS_LABEL_STYLE
        )
        self.job_count_label.pack(anchor=tk.W, pady=(0, 4))

        self.prompt_label = ttk.Label(self.body, text="Prompt (+)", style=STATUS_LABEL_STYLE)
        self.prompt_label.pack(anchor=tk.W)
        self.prompt_text = tk.Text(
            self.body,
            height=3,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="flat",
            state="disabled",
        )
        self.prompt_text.pack(fill=tk.X, pady=(0, 4))

        self.negative_prompt_label = ttk.Label(
            self.body, text="Prompt (–)", style=STATUS_LABEL_STYLE
        )
        self.negative_prompt_label.pack(anchor=tk.W)
        self.negative_prompt_text = tk.Text(
            self.body,
            height=2,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="flat",
            state="disabled",
        )
        self.negative_prompt_text.pack(fill=tk.X, pady=(0, 8))

        settings_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
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

        self.stage_summary_label = ttk.Label(self.body, text="Stages: -", style=STATUS_LABEL_STYLE)
        self.stage_summary_label.pack(anchor=tk.W, pady=(4, 0))

        self.stage_flags_label = ttk.Label(
            self.body,
            text=self._format_flags(refiner=False, hires=False, upscale=False),
            style=STATUS_LABEL_STYLE,
        )
        self.stage_flags_label.pack(anchor=tk.W, pady=(0, 4))

        self.randomizer_label = ttk.Label(
            self.body, text="Randomizer: OFF", style=STATUS_LABEL_STYLE
        )
        self.randomizer_label.pack(anchor=tk.W, pady=(0, 4))

        self.learning_metadata_label = ttk.Label(
            self.body,
            text="Learning metadata: N/A",
            style=STATUS_LABEL_STYLE,
        )
        self.learning_metadata_label.pack(anchor=tk.W)

        self.actions_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
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
        unified = job.to_unified_summary() if hasattr(job, "to_unified_summary") else None
        ui_summary = job.to_ui_summary() if hasattr(job, "to_ui_summary") else None

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
        )

    def set_job_summaries(self, summaries: list[Any]) -> None:
        """Render one or more JobUiSummary entries."""
        if self._dispatch_to_ui(lambda: self.set_job_summaries(summaries)):
            return
        self._job_summaries = list(summaries)
        first_summary = summaries[0] if summaries else None
        self._render_summary(first_summary, len(summaries))

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
        if app_state is None:
            app_state = self.app_state
        job_draft = getattr(app_state, "job_draft", None)
        preview_jobs = getattr(app_state, "preview_jobs", None)
        self._update_action_states(job_draft, preview_jobs)

    def _bind_app_state_previews(self) -> None:
        logger.debug(f"[PreviewPanel] _bind_app_state_previews called, app_state={self.app_state}")
        if not self.app_state or not hasattr(self.app_state, "subscribe"):
            logger.debug(f"[PreviewPanel] Cannot subscribe - app_state={self.app_state}, has_subscribe={hasattr(self.app_state, 'subscribe') if self.app_state else False}")
            return
        try:
            logger.debug("[PreviewPanel] Subscribing to preview_jobs changes")
            self.app_state.subscribe("preview_jobs", self._on_preview_jobs_changed)
            logger.debug("[PreviewPanel] Successfully subscribed to preview_jobs")
        except Exception as e:
            logger.debug(f"[PreviewPanel] Failed to subscribe: {e}")
            pass
        self._on_preview_jobs_changed()

    def _on_preview_jobs_changed(self) -> None:
        logger.debug("[PreviewPanel] _on_preview_jobs_changed called")
        if not self.app_state:
            logger.debug("[PreviewPanel] No app_state, returning")
            return
        records = getattr(self.app_state, "preview_jobs", None)
        logger.debug(f"[PreviewPanel] Got {len(records) if records else 0} preview jobs from app_state")
        self.set_preview_jobs(records)

    def _render_summary(self, summary: Any | None, total: int) -> None:
        logger.debug(f"[PreviewPanel] _render_summary called: summary={bool(summary)}, total={total}")

        if summary is None:
            logger.debug("[PreviewPanel] Rendering empty state")
            self.job_count_label.config(text="No job selected")
            self._set_text_widget(self.prompt_text, "")
            self._set_text_widget(self.negative_prompt_text, "")
            self.model_label.config(text="Model: -")
            self.sampler_label.config(text="Sampler: -")
            self.steps_label.config(text="Steps: -")
            self.cfg_label.config(text="CFG: -")
            self.seed_label.config(text="Seed: -")
            self.stage_summary_label.config(text="Stages: -")
            self.stage_flags_label.config(
                text=self._format_flags(refiner=False, hires=False, upscale=False)
            )
            self.randomizer_label.config(text="Randomizer: OFF")
            self.learning_metadata_label.config(text="Learning metadata: N/A")
            # Clear thumbnail when no job
            self._current_preview_job = None
            self._current_pack_name = None
            self._current_show_preview = True
            self._update_thumbnail()
            return

        summary_obj = self._normalize_summary(summary)
        if summary_obj is None:
            logger.debug("[PreviewPanel] _normalize_summary returned None")
            self.job_count_label.config(text="No job selected")
            self._update_thumbnail()
            return

        job_text = f"Job: {total}" if total == 1 else f"Jobs: {total}"
        logger.debug(f"[PreviewPanel] Setting job_count_label to: {job_text}")
        self.job_count_label.config(text=job_text)

        positive = getattr(summary_obj, "positive_preview", "") or ""
        negative = getattr(summary_obj, "negative_preview", "") or ""
        logger.debug(f"[PreviewPanel] Positive preview length: {len(positive)}, Negative: {len(negative)}")
        self._set_text_widget(self.prompt_text, positive)
        self._set_text_widget(self.negative_prompt_text, negative)

        # Force Tkinter to update the display immediately
        self.update_idletasks()

        model_text = getattr(summary_obj, "label", None) or getattr(summary_obj, "base_model", "-")
        logger.debug(f"[PreviewPanel] Model: {model_text}")
        self.model_label.config(text=f"Model: {model_text}")
        sampler_text = getattr(summary_obj, "sampler_name", getattr(summary_obj, "sampler", "-"))
        logger.debug(f"[PreviewPanel] Sampler: {sampler_text}")
        self.sampler_label.config(text=f"Sampler: {sampler_text}")
        steps_value = self._coerce_int(getattr(summary_obj, "steps", None))
        logger.debug(f"[PreviewPanel] Steps: {steps_value}")
        self.steps_label.config(text=f"Steps: {steps_value if steps_value is not None else '-'}")
        cfg_value = self._coerce_float(getattr(summary_obj, "cfg_scale", None))
        cfg_text = f"{cfg_value:.1f}" if cfg_value is not None else "-"
        logger.debug(f"[PreviewPanel] CFG: {cfg_text}")
        self.cfg_label.config(text=f"CFG: {cfg_text}")
        # PR-PIPE-007: Show resolved seed when available
        requested_seed = getattr(summary_obj, "seed", None)
        actual_seed = getattr(summary_obj, "actual_seed", None) or getattr(summary_obj, "resolved_seed", None)
        seed_text = format_seed_display(requested_seed, actual_seed)
        self.seed_label.config(text=f"Seed: {seed_text}")

        stages_text = getattr(summary_obj, "stages_display", "-")
        self.stage_summary_label.config(text=f"Stages: {stages_text}")
        self.stage_flags_label.config(
            text=self._format_flags(refiner=False, hires=False, upscale=False)
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

        self.randomizer_label.config(text=randomizer_text)
        self.learning_metadata_label.config(text="Learning metadata: N/A")

        # Update thumbnail with pack info from summary
        pack_name = getattr(summary_obj, "pack_name", None) or getattr(summary_obj, "label", None)
        show_preview = getattr(summary_obj, "show_preview", True)

        # Store current state for checkbox handler
        self._current_preview_job = summary
        self._current_pack_name = pack_name
        self._current_show_preview = show_preview

        # Update checkbox state based on pack config
        if show_preview != self._show_preview_var.get():
            self._show_preview_var.set(show_preview)

        # Load thumbnail
        self._update_thumbnail(summary, pack_name, show_preview)

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
                base_model=summary.base_model,
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

    @staticmethod
    def _set_text_widget(widget: tk.Text, value: str) -> None:
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, value)
        widget.config(state=tk.DISABLED)

    def _on_add_to_queue(self) -> None:
        """Move the draft job into the queue."""
        if not self.controller:
            return
        try:
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
        output_dir = Path("output")
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
            run_dirs = sorted(
                [p for p in output_dir.iterdir() if p.is_dir()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:10]  # Check last 10 runs

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

    def _find_latest_output_image(self, summary: UnifiedJobSummary | Any | None) -> Path | None:
        """Inspect a summary/result object to find the latest output image."""
        if summary is None:
            return None

        # If summary carries a result dict with metadata paths, use that first
        result = getattr(summary, "result", None)
        if isinstance(result, dict):
            metadata = result.get("metadata")
            if isinstance(metadata, dict):
                candidate = metadata.get("path") or metadata.get("output_path")
                if candidate and Path(candidate).exists():
                    return Path(candidate)
            if isinstance(metadata, list):
                for entry in reversed(metadata):
                    if isinstance(entry, dict):
                        candidate = entry.get("path") or entry.get("output_path")
                        if candidate and Path(candidate).exists():
                            return Path(candidate)

        # If the summary has a job_id, look for a run folder named with it
        job_id = getattr(summary, "job_id", None)
        output_dir = Path("output")
        if job_id and output_dir.exists():
            job_dirs = sorted(
                [p for p in output_dir.iterdir() if job_id in p.name],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for run_dir in job_dirs:
                candidates = sorted(run_dir.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    return candidates[0]

        return None

    def _update_thumbnail(self, job: Any | None = None, pack_name: str | None = None, show_preview: bool = True) -> None:
        """Update the thumbnail display for the current preview job."""
        # Check if preview is disabled
        if not show_preview or not self._show_preview_var.get():
            self.thumbnail.clear()
            return

        if job is None:
            self.thumbnail.clear()
            return

        # Prefer explicit output path from summary/result if available
        explicit_path = self._find_latest_output_image(job)
        if explicit_path:
            self.thumbnail.set_image_from_path(explicit_path)
            return

        # Try to find a matching image
        thumb_path = self._find_recent_thumbnail(job, pack_name)

        if thumb_path:
            self.thumbnail.set_image_from_path(thumb_path)
        else:
            self.thumbnail.clear()

    def _on_preview_checkbox_changed(self) -> None:
        """Handle preview checkbox state change."""
        enabled = self._show_preview_var.get()

        # Update thumbnail visibility
        if enabled and self._job_summaries:
            # Reload thumbnail for current job
            first_job = getattr(self, "_current_preview_job", None)
            pack_name = getattr(self, "_current_pack_name", None)
            show_preview = getattr(self, "_current_show_preview", True)
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
        self._current_show_preview = True
        self._update_thumbnail(summary, self._current_pack_name, True)
        
        # PR-GUI-DATA-005: Load latest output image if preview enabled
        if self._show_preview_var.get() and summary:
            latest_image = self._find_latest_output_image(summary)
            if latest_image and latest_image.exists():
                try:
                    self.thumbnail.load_image(str(latest_image))
                except Exception as e:
                    logger.debug(f"Failed to load thumbnail: {e}")
                    self.thumbnail.clear()
            else:
                self.thumbnail.clear()
        else:
            self.thumbnail.clear()
    
    def _find_latest_output_image(self, summary: UnifiedJobSummary) -> Path | None:
        """Find the most recently generated image for this job.
        
        PR-GUI-DATA-005: Search job output folder for latest image.
        
        Args:
            summary: UnifiedJobSummary containing job_id and result metadata
            
        Returns:
            Path to most recent image or None
        """
        # Try to get output folder from result metadata
        if hasattr(summary, 'result') and isinstance(summary.result, dict):
            metadata = summary.result.get('metadata', {})
            if isinstance(metadata, dict):
                output_path = metadata.get('path')
                if output_path:
                    image_path = Path(output_path)
                    if image_path.exists():
                        return image_path
        
        # Fallback: scan output folder for this job_id
        job_id = getattr(summary, 'job_id', None)
        if job_id:
            output_folder = Path("output") / job_id
            if output_folder.exists():
                # Find most recent image file
                image_extensions = ('.png', '.jpg', '.jpeg', '.webp')
                images = [
                    f for f in output_folder.rglob("*")
                    if f.is_file() and f.suffix.lower() in image_extensions
                ]
                if images:
                    # Sort by modification time, return most recent
                    images.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    return images[0]
        
        # Try output/<timestamp> pattern fallback
        output_root = Path("output")
        if output_root.exists():
            # Find folders that might contain this job's outputs
            # Look for recent folders (within last hour)
            import time
            now = time.time()
            recent_threshold = now - 3600  # 1 hour ago
            
            recent_folders = [
                f for f in output_root.iterdir()
                if f.is_dir() and f.stat().st_mtime > recent_threshold
            ]
            
            for folder in sorted(recent_folders, key=lambda p: p.stat().st_mtime, reverse=True):
                image_extensions = ('.png', '.jpg', '.jpeg', '.webp')
                images = [
                    f for f in folder.rglob("*")
                    if f.is_file() and f.suffix.lower() in image_extensions
                ]
                if images:
                    images.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    return images[0]
        
        return None

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
            
            # Restore show_preview flag
            show_preview = state.get("show_preview", True)
            self._show_preview_var.set(show_preview)
            
            logger.debug(f"Restored preview panel state: show_preview={show_preview}")
        except Exception as e:
            logger.warning(f"Failed to restore preview panel state: {e}")

    def destroy(self) -> None:
        """Override destroy to save state before cleanup."""
        try:
            self.save_state()
        except Exception:
            pass
        super().destroy()
