"""Preview panel scaffold for GUI v2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

from src.pipeline.job_models_v2 import JobUiSummary, NormalizedJobRecord, UnifiedJobSummary
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

        self.job_count_label = ttk.Label(self.body, text="No job selected", style=STATUS_LABEL_STYLE)
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

        self.negative_prompt_label = ttk.Label(self.body, text="Prompt (–)", style=STATUS_LABEL_STYLE)
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

        self.randomizer_label = ttk.Label(self.body, text="Randomizer: OFF", style=STATUS_LABEL_STYLE)
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

    def set_jobs(self, jobs: list[Any]) -> None:
        """Update preview from a list of NormalizedJobRecord objects."""
        self.set_preview_jobs(jobs)

    def set_preview_jobs(self, jobs: list[NormalizedJobRecord] | None) -> None:
        """Render previews from NormalizedJobRecord objects."""
        summary_entries: list[Any] = []
        for job in jobs or []:
            summary_entries.append(self._summary_from_normalized_job(job))
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
        self._job_summaries = list(summaries)
        first_summary = summaries[0] if summaries else None
        self._render_summary(first_summary, len(summaries))

    def update_from_summary(self, dto: Any | None) -> None:
        """Update preview from JobBundleSummaryDTO (PR-D method)."""
        from src.pipeline.job_models_v2 import JobBundleSummaryDTO
        
        if dto is None or not isinstance(dto, JobBundleSummaryDTO):
            self._render_summary(None, 0)
            self._update_action_states(None)
            return
        
        # Convert DTO to display data using SimpleNamespace to avoid type issues
        job_id_display = f"{dto.num_parts} part(s)"
        label_display = dto.label or "Draft Bundle"
        positive_text = dto.positive_preview or ""
        negative_text = dto.negative_preview if dto.negative_preview else ""
        stages_text = dto.stage_summary or "-"
        
        summary = SimpleNamespace(
            job_id=job_id_display,
            label=label_display,
            positive_preview=positive_text,
            negative_preview=negative_text,
            stages_display=stages_text,
            estimated_images=dto.estimated_images,
            created_at=None,
        )
        
        self._render_summary(summary, dto.num_parts)  # type: ignore[arg-type]
        # Enable buttons when draft has content
        has_draft = dto.num_parts > 0
        state = ["!disabled"] if has_draft else ["disabled"]
        self.add_to_queue_button.state(state)
        self.clear_draft_button.state(state)

    def update_from_job_draft(self, job_draft: Any) -> None:
        """Update preview summary from job draft."""
        if job_draft is None:
            self._render_summary(None, 0)
            self._update_action_states(None)
            return

        packs = getattr(job_draft, "packs", [])
        total = 0
        summary = None
        if packs:
            entry = packs[0]
            summary = self._summary_from_pack_entry(entry)
            total = len(packs)
        else:
            draft_summary = getattr(job_draft, "summary", None)
            if draft_summary and getattr(draft_summary, "part_count", 0) > 0:
                summary = self._summary_from_draft_summary(draft_summary)
                total = draft_summary.part_count

        self._render_summary(summary, total)
        self._update_action_states(job_draft, getattr(self.app_state, "preview_jobs", None))

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

    def _summary_from_pack_entry(self, entry: Any) -> JobUiSummary:
        config = entry.config_snapshot or {}
        prompt_text = entry.prompt_text or str(config.get("prompt") or "")
        negative = entry.negative_prompt_text or str(config.get("negative_prompt", "") or "")
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

        model = str(config.get("model") or config.get("model_name") or entry.pack_name or "unknown") or "unknown"
        label = f"{model} | seed={config.get('seed', '?')}"

        return JobUiSummary(
            job_id=entry.pack_id,
            label=label,
            positive_preview=self._truncate_text(prompt_text, limit=120),
            negative_preview=self._truncate_text(negative, limit=120) if negative else "",
            stages_display=stages_display,
            estimated_images=1,  # Default for pack entry
            created_at=None,
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
        if not self.app_state or not hasattr(self.app_state, "subscribe"):
            return
        try:
            self.app_state.subscribe("preview_jobs", self._on_preview_jobs_changed)
        except Exception:
            pass
        self._on_preview_jobs_changed()

    def _on_preview_jobs_changed(self) -> None:
        if not self.app_state:
            return
        records = getattr(self.app_state, "preview_jobs", None)
        self.set_preview_jobs(records)

    def _render_summary(self, summary: Any | None, total: int) -> None:
        if summary is None:
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
            return

        summary_obj = self._normalize_summary(summary)
        if summary_obj is None:
            self.job_count_label.config(text="No job selected")
            return

        job_text = f"Job: {total}" if total == 1 else f"Jobs: {total}"
        self.job_count_label.config(text=job_text)

        positive = getattr(summary_obj, "positive_preview", "")
        negative = getattr(summary_obj, "negative_preview", "")
        self._set_text_widget(self.prompt_text, positive or "")
        self._set_text_widget(self.negative_prompt_text, negative or "")

        model_text = getattr(summary_obj, "label", None) or getattr(summary_obj, "base_model", "-")
        self.model_label.config(text=f"Model: {model_text}")
        sampler_text = getattr(summary_obj, "sampler_name", getattr(summary_obj, "sampler", "-"))
        self.sampler_label.config(text=f"Sampler: {sampler_text}")
        steps_value = self._coerce_int(getattr(summary_obj, "steps", None))
        self.steps_label.config(text=f"Steps: {steps_value if steps_value is not None else '-'}")
        cfg_value = self._coerce_float(getattr(summary_obj, "cfg_scale", None))
        cfg_text = f"{cfg_value:.1f}" if cfg_value is not None else "-"
        self.cfg_label.config(text=f"CFG: {cfg_text}")
        seed_value = getattr(summary_obj, "seed", None)
        seed_text = str(seed_value) if seed_value is not None else "-"
        self.seed_label.config(text=f"Seed: {seed_text}")

        stages_text = getattr(summary_obj, "stages_display", "-")
        self.stage_summary_label.config(text=f"Stages: {stages_text}")
        self.stage_flags_label.config(text=self._format_flags(refiner=False, hires=False, upscale=False))
        
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
        self._invoke_controller("enqueue_draft_bundle")

    def _on_clear_draft(self) -> None:
        """Clear the current draft job metadata."""
        self._invoke_controller("clear_draft_job_bundle")

    def _on_details_clicked(self) -> None:
        """Show the logging view via controller helper."""
        self._invoke_controller("show_log_trace_panel")

    def _update_action_states(
        self,
        job_draft: Any | None,
        preview_jobs: list["NormalizedJobRecord"] | None = None,
    ) -> None:
        """Enable/disable action buttons based on draft content."""
        has_draft = False
        if job_draft is not None:
            packs = getattr(job_draft, "packs", [])
            part_summary = getattr(job_draft, "summary", None)
            has_parts = bool(getattr(part_summary, "part_count", 0))
            has_draft = bool(packs) or has_parts
        has_preview = bool(preview_jobs)
        state = ["!disabled"] if has_draft or has_preview else ["disabled"]
        self.add_to_queue_button.state(state)
        self.clear_draft_button.state(state)

    def _invoke_controller(self, method_name: str, *args: Any) -> Any:
        """Call a controller hook if available."""
        controller = self.controller
        if not controller:
            return None
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                return method(*args)
            except Exception:
                pass
        return None
