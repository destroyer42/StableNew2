"""Pipeline panel composed of modular stage cards and prompt pack summary."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, List

from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
from src.gui.stage_cards_v2.validation_result import ValidationResult
from .widgets.scrollable_frame_v2 import ScrollableFrame
from .widgets.config_sweep_widget_v2 import ConfigSweepWidgetV2
from src.gui.theme_v2 import STATUS_LABEL_STYLE
from . import theme as theme_mod
from src.pipeline.job_models_v2 import NormalizedJobRecord, UnifiedJobSummary


class PipelinePanelV2(ttk.Frame):
    """Container for pipeline stage cards and a prompt pack summary."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: object = None,
        app_state: object = None,
        theme: object = None,
        config_manager: object = None,
        **kwargs,
    ) -> None:
        self.sidebar: object | None = None
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self.config_manager = config_manager

        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)

        header_style = getattr(theme, "PIPELINE_HEADING_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        ttk.Label(self, text="Pipeline", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        summary_frame = ttk.Frame(self, style=style_name)
        summary_frame.pack(fill=tk.X, pady=(0, 8))
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.columnconfigure(1, weight=1)

        self.pack_label = ttk.Label(summary_frame, text="Prompt Pack: –", style=STATUS_LABEL_STYLE)
        self.pack_label.grid(row=0, column=0, sticky="w")
        self.row_label = ttk.Label(summary_frame, text="Row: –", style=STATUS_LABEL_STYLE)
        self.row_label.grid(row=0, column=1, sticky="e")

        self.positive_preview_label = ttk.Label(
            summary_frame,
            text="Positive Preview: –",
            style=STATUS_LABEL_STYLE,
            wraplength=320,
        )
        self.positive_preview_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.negative_preview_label = ttk.Label(
            summary_frame,
            text="Negative Preview: –",
            style=STATUS_LABEL_STYLE,
            wraplength=320,
        )
        self.negative_preview_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # PR-CORE-E: Config Sweep Widget
        self.config_sweep_widget = ConfigSweepWidgetV2(
            self,
            theme=self.theme,
            config_manager=self.config_manager,
            on_change=self._on_sweep_change,
        )
        self.config_sweep_widget.pack(fill=tk.X, pady=(8, 8))

        # Scrollable frame with stage cards
        self._scroll: ScrollableFrame = ScrollableFrame(self)
        self.body = self._scroll.inner
        self.txt2img_card = AdvancedTxt2ImgStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.img2img_card = AdvancedImg2ImgStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.adetailer_card = ADetailerStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.upscale_card = AdvancedUpscaleStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.adetailer_card = ADetailerStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)

        self.run_button: ttk.Button | None = None
        self.stop_button: ttk.Button | None = None

        self._apply_stage_visibility()
        self._bind_app_state()

    def _bind_app_state(self) -> None:
        if not self.app_state:
            return
        if hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe("preview_jobs", self._refresh_summary_from_app_state)
            except Exception:
                pass
            try:
                self.app_state.subscribe("current_pack", self._refresh_summary_from_app_state)
            except Exception:
                pass
            # PR-CORE-D: Subscribe to PromptPack selection for run button state
            try:
                self.app_state.subscribe("selected_prompt_pack", self._refresh_summary_from_app_state)
                self.app_state.subscribe("selected_prompt_pack", self._update_run_button_state)
            except Exception:
                pass
            try:
                self.app_state.subscribe("selected_config_snapshot", self._update_run_button_state)
            except Exception:
                pass
        self._refresh_summary_from_app_state()
        self._update_run_button_state()

    def _refresh_summary_from_app_state(self) -> None:
        records = getattr(self.app_state, "preview_jobs", None) or []
        summary = self._get_latest_summary(records)
        self.update_pack_summary(summary, len(records))

    def _get_latest_summary(self, records: list[NormalizedJobRecord] | None = None) -> UnifiedJobSummary | None:
        if not self.app_state:
            return None
        entries = records if records is not None else (getattr(self.app_state, "preview_jobs", None) or [])
        if not entries:
            return None
        first = entries[0]
        if hasattr(first, "to_unified_summary"):
            return first.to_unified_summary()
        if isinstance(first, UnifiedJobSummary):
            return first
        return None

    def update_pack_summary(self, summary: UnifiedJobSummary | None, total_records: int | None = None) -> None:
        if summary is None:
            self.pack_label.config(text="Prompt Pack: –")
            self.row_label.config(text="Row: –")
            self.positive_preview_label.config(text="Positive Preview: –")
            self.negative_preview_label.config(text="Negative Preview: –")
            return

        pack_name = summary.prompt_pack_name or "Untitled Pack"
        self.pack_label.config(text=f"Prompt Pack: {pack_name}")
        row_number = summary.prompt_pack_row_index + 1
        
        # PR-CORE-E: Show config variant count in preview
        if total_records and total_records > 1:
            # Check if we have config sweep enabled
            sweep_enabled = getattr(self.app_state, "config_sweep_enabled", False) if self.app_state else False
            variant_count = len(getattr(self.app_state, "config_sweep_variants", [])) if self.app_state else 0
            
            if sweep_enabled and variant_count > 1:
                self.row_label.config(text=f"Row: {row_number} of {total_records} ({variant_count} config variants)")
            else:
                self.row_label.config(text=f"Row: {row_number} of {total_records}")
        else:
            self.row_label.config(text=f"Row: {row_number}")
        
        self.positive_preview_label.config(
            text=f"Positive Preview: {self._truncate(summary.positive_prompt_preview)}"
        )
        negative_text = summary.negative_prompt_preview or "–"
        self.negative_preview_label.config(
            text=f"Negative Preview: {self._truncate(negative_text)}"
        )

    @staticmethod
    def _truncate(value: str, limit: int = 120) -> str:
        if not value:
            return ""
        return value if len(value) <= limit else value[:limit] + "..."

    def load_from_config(self, config: dict[str, object] | None) -> None:
        data = config or {}
        self.txt2img_card.load_from_config(data)
        self.img2img_card.load_from_config(data)
        self.upscale_card.load_from_config(data)

    def to_config_delta(self) -> dict[str, dict[str, object]]:
        delta: dict[str, dict[str, object]] = {}
        for card in (self.txt2img_card, self.img2img_card, self.upscale_card):
            section_delta = card.to_config_dict()
            for section, values in section_delta.items():
                if not values:
                    continue
                delta.setdefault(section, {}).update(values)
        return delta

    def get_txt2img_form_view(self) -> dict[str, object]:
        return self.txt2img_card.to_config_dict().get("txt2img", {})

    def validate_txt2img(self) -> ValidationResult:
        return self.txt2img_card.validate()

    def set_txt2img_change_callback(self, callback: object) -> None:
        self._txt2img_change_callback = callback

    def _handle_txt2img_change(self) -> None:
        if self._txt2img_change_callback:
            self._txt2img_change_callback()

    def validate_full_pipeline(self) -> ValidationResult:
        for card in (self.txt2img_card, self.img2img_card, self.upscale_card):
            result = card.validate()
            if not result.ok:
                return result
        return ValidationResult(True, None)

    def _apply_stage_visibility(self) -> None:
        enabled = set(self.sidebar.get_enabled_stages()) if getattr(self, "sidebar", None) else {"txt2img", "img2img", "adetailer", "upscale"}
        if "txt2img" in enabled:
            self.txt2img_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        else:
            self.txt2img_card.pack_forget()
        if "img2img" in enabled:
            self.img2img_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        else:
            self.img2img_card.pack_forget()
        if "adetailer" in enabled:
            self.adetailer_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        else:
            self.adetailer_card.pack_forget()
        if "upscale" in enabled:
            self.upscale_card.pack(fill=tk.BOTH, expand=True)
        else:
            self.upscale_card.pack_forget()

    def _handle_sidebar_change(self) -> None:
        self._apply_stage_visibility()
        try:
            if hasattr(self, "preview_panel"):
                self.preview_panel.update_from_controls(self.sidebar)
        except Exception:
            pass

    def _update_run_button_state(self) -> None:
        """PR-CORE-D: Update run button state based on PromptPack selection.
        
        Run button is enabled only when:
        1. A PromptPack is selected (selected_prompt_pack_id exists)
        2. A config snapshot is selected (selected_config_snapshot_id exists)
        """
        if not self.app_state:
            return
        
        # Check if run button exists
        if not self.run_button:
            return
        
        # PR-CORE-D: Enforce PromptPack-only - disable button if no pack selected
        has_pack = bool(getattr(self.app_state, "selected_prompt_pack_id", None))
        has_config = bool(getattr(self.app_state, "selected_config_snapshot_id", None))
        
        should_enable = has_pack and has_config
        
        try:
            if should_enable:
                self.run_button.config(state="normal")
            else:
                self.run_button.config(state="disabled")
        except Exception:
            pass

    def _on_sweep_change(self) -> None:
        """PR-CORE-E: Handle config sweep changes."""
        if not self.app_state:
            return
        
        # Update app state with sweep config
        sweep_config = self.config_sweep_widget.get_sweep_config()
        self.app_state.set_config_sweep_enabled(sweep_config["enabled"])
        self.app_state.set_config_sweep_variants(sweep_config["variants"])
        
        # Update global negative apply flags
        for stage in ["txt2img", "img2img", "upscale", "adetailer"]:
            flag_key = f"apply_global_negative_{stage}"
            if flag_key in sweep_config:
                self.app_state.set_apply_global_negative(stage, sweep_config[flag_key])

    def get_config_sweep_plan(self) -> dict[str, Any]:
        """PR-CORE-E: Get config sweep plan from widget.
        
        Returns:
            Dict with enabled, variants, and global negative flags.
        """
        return self.config_sweep_widget.get_sweep_config()


def format_queue_job_summary(job: Any) -> str:
    if job is None:
        return ""
    config = getattr(job, "config_snapshot", None) or getattr(job, "pipeline_config", None) or {}

    def _value(key: str, fallback: Any = "") -> Any:
        if isinstance(config, dict):
            return config.get(key, fallback)
        return getattr(config, key, fallback)

    model = _value("model") or _value("model_name") or "unknown"
    prompt = _value("prompt") or ""
    seed = _value("seed") or getattr(job, "seed", None)
    status = getattr(job, "status", None)
    prompt_preview = prompt.strip().splitlines()[0] if prompt.strip() else ""
    if prompt_preview and len(prompt_preview) < len(prompt.strip()):
        prompt_preview = prompt_preview[:40].rstrip() + "..."
    summary_parts: List[str] = [model]
    summary_parts.append(f"seed={seed or 'auto'}")
    if status:
        summary_parts.append(str(status))
    if prompt_preview:
        summary_parts.append(f'prompt="{prompt_preview}"')
    job_id = getattr(job, "job_id", "") or ""
    if job_id:
        summary_parts.append(job_id)
    return " | ".join(summary_parts)


__all__ = ["PipelinePanelV2", "format_queue_job_summary"]
