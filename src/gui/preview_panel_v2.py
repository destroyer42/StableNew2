"""Preview panel scaffold for GUI v2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.pipeline.job_models_v2 import JobUiSummary, NormalizedJobRecord
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

    def set_jobs(self, jobs: list[Any]) -> None:
        """Update preview from a list of NormalizedJobRecord objects."""
        summaries: list[JobUiSummary] = []
        for job in jobs:
            if hasattr(job, "to_ui_summary"):
                summaries.append(job.to_ui_summary())
        self.set_job_summaries(summaries)

    def set_job_summaries(self, summaries: list[JobUiSummary]) -> None:
        """Render one or more JobUiSummary entries."""
        self._job_summaries = list(summaries)
        first_summary = summaries[0] if summaries else None
        self._render_summary(first_summary, len(summaries))

    def update_from_job_draft(self, job_draft: Any) -> None:
        """Update preview summary from job draft."""
        packs = getattr(job_draft, "packs", [])
        if not packs:
            self._render_summary(None, 0)
            self._update_action_states(job_draft)
            return

        entry = packs[0]
        summary = self._summary_from_pack_entry(entry)
        self._render_summary(summary, len(packs))
        self._update_action_states(job_draft)

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

    def _summary_from_pack_entry(self, entry: Any) -> JobUiSummary:
        config = entry.config_snapshot or {}
        prompt_text = entry.prompt_text or str(config.get("prompt") or "")
        negative = entry.negative_prompt_text or str(config.get("negative_prompt", "") or "")
        sampler = str(config.get("sampler") or config.get("sampler_name") or "")
        steps = self._coerce_int(config.get("steps"))
        cfg_scale = self._coerce_float(config.get("cfg_scale"))

        model = str(config.get("model") or config.get("model_name") or entry.pack_name or "unknown") or "unknown"
        seed = config.get("seed")
        seed_display = str(seed) if seed is not None else "?"
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
        stages_summary = " + ".join(stages)

        randomizer_summary = NormalizedJobRecord._format_randomizer_summary(entry.randomizer_metadata)

        has_refiner = bool(stage_flags.get("refiner") or config.get("refiner_enabled"))
        has_hires = bool(stage_flags.get("hires") or config.get("hires_enabled"))
        has_upscale = bool(stage_flags.get("upscale") or config.get("upscale_enabled"))
        output_dir = str(config.get("output_dir") or config.get("path_output_dir") or "output")

        return JobUiSummary(
            job_id=entry.pack_id,
            model=model,
            prompt_short=self._truncate_text(prompt_text, limit=120),
            negative_prompt_short=self._truncate_text(negative, limit=120) if negative else None,
            sampler=sampler,
            steps=steps,
            cfg_scale=cfg_scale,
            seed_display=seed_display,
            variant_label="",
            batch_label="",
            stages_summary=stages_summary,
            randomizer_summary=randomizer_summary,
            has_refiner=has_refiner,
            has_hires=has_hires,
            has_upscale=has_upscale,
            output_dir=output_dir,
            total_summary=f"{model} | seed={seed_display}",
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
    def update_from_app_state(self, app_state: Any | None = None) -> None:
        """Update action button availability based on app_state."""
        if app_state is None:
            app_state = self.app_state
        job_draft = getattr(app_state, "job_draft", None)
        self._update_action_states(job_draft)

    def _render_summary(self, summary: JobUiSummary | None, total: int) -> None:
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

        job_text = "Jobs: " + str(total) if total > 1 else "Job: 1"
        self.job_count_label.config(text=job_text)
        self._set_text_widget(self.prompt_text, summary.prompt_short)
        self._set_text_widget(self.negative_prompt_text, summary.negative_prompt_short or "")
        self.model_label.config(text=f"Model: {summary.model}")
        self.sampler_label.config(text=f"Sampler: {summary.sampler or '-'}")
        self.steps_label.config(
            text=f"Steps: {summary.steps if summary.steps is not None else '-'}"
        )
        cfg_value = summary.cfg_scale if summary.cfg_scale is not None else "-"
        self.cfg_label.config(text=f"CFG: {cfg_value}")
        self.seed_label.config(text=f"Seed: {summary.seed_display}")
        self.stage_summary_label.config(text=f"Stages: {summary.stages_summary}")

        flag_text = self._format_flags(
            refiner=summary.has_refiner,
            hires=summary.has_hires,
            upscale=summary.has_upscale,
        )
        self.stage_flags_label.config(text=flag_text)

        randomizer_text = summary.randomizer_summary or "OFF"
        self.randomizer_label.config(text=f"Randomizer: {randomizer_text}")
        self.learning_metadata_label.config(text="Learning metadata: N/A")

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
        self._invoke_controller("on_add_job_to_queue_v2")

    def _on_clear_draft(self) -> None:
        """Clear the current draft job metadata."""
        self._invoke_controller("on_clear_job_draft")

    def _on_details_clicked(self) -> None:
        """Show the logging view via controller helper."""
        self._invoke_controller("show_log_trace_panel")

    def _update_action_states(self, job_draft: Any | None) -> None:
        """Enable/disable action buttons based on draft content."""
        has_draft = False
        if job_draft is not None:
            packs = getattr(job_draft, "packs", [])
            has_draft = bool(packs)
        state = ["!disabled"] if has_draft else ["disabled"]
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
