"""Pipeline panel composed of modular stage cards."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as theme_mod
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
from src.gui.stage_cards_v2.validation_result import ValidationResult
from .widgets.scrollable_frame_v2 import ScrollableFrame


class PipelinePanelV2(ttk.Frame):
    """Container for pipeline stage cards."""

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
        # Default sidebar attribute to avoid attribute errors
        self.sidebar: object | None = None
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
        self.theme = theme
        self.config_manager = config_manager

        header_style = getattr(theme, "PIPELINE_HEADING_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        ttk.Label(self, text="Pipeline", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        # Prompt text widget
        self.prompt_text: tk.Text = tk.Text(self, height=4, width=60)
        self.prompt_text.pack(fill=tk.X, padx=4, pady=(0, 8))

        # Editor button
        self.open_editor_button: ttk.Button = ttk.Button(self, text="Edit Prompt", command=self._open_editor)
        self.open_editor_button.pack(anchor=tk.W, padx=4, pady=(0, 8))

        # Scrollable frame placeholder
        self._scroll: ScrollableFrame = ScrollableFrame(self)
        self.body = self._scroll.inner

        # Editor state
        self._editor: object | None = None
        self._editor_window: tk.Toplevel | None = None

        # Stage cards (parented under scrollable inner frame)
        self.txt2img_card: AdvancedTxt2ImgStageCardV2 = AdvancedTxt2ImgStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.img2img_card: AdvancedImg2ImgStageCardV2 = AdvancedImg2ImgStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.adetailer_card: ADetailerStageCardV2 = ADetailerStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.upscale_card: AdvancedUpscaleStageCardV2 = AdvancedUpscaleStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)
        self.adetailer_card: ADetailerStageCardV2 = ADetailerStageCardV2(self.body, theme=self.theme, config_manager=self.config_manager)

        self.run_button: ttk.Button | None = None
        self.stop_button: ttk.Button | None = None

        self._apply_stage_visibility()

    def get_prompt(self) -> str:
        return self.prompt_text.get("1.0", tk.END).strip()

    def set_prompt(self, text: str) -> None:
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", text)
        # If there is a config or state object, update it here as well (if needed)

    class PromptEditor:
        def __init__(self, window: tk.Toplevel, initial_text: str) -> None:
            self.prompt_text: tk.Text = tk.Text(window, height=8, width=60)
            self.prompt_text.pack(fill=tk.BOTH, padx=8, pady=8)
            self.prompt_text.insert("1.0", initial_text)
            self.apply_button: ttk.Button = ttk.Button(window, text="Apply")
            self.apply_button.pack(pady=(0, 8))

    def _open_editor(self) -> None:
        if self._editor_window and self._editor_window.winfo_exists():
            self._editor_window.lift()
            return
        self._editor_window = tk.Toplevel(self)
        self._editor_window.title("Edit Prompt")
        self._editor = self.PromptEditor(self._editor_window, self.get_prompt())
        self._editor.apply_button.config(command=self._apply_editor_prompt)

    def _apply_editor_prompt(self) -> None:
        if self._editor and hasattr(self._editor, "prompt_text"):
            new_text = self._editor.prompt_text.get("1.0", tk.END).strip()
            self.set_prompt(new_text)
        if self._editor_window and self._editor_window.winfo_exists():
            self._editor_window.destroy()

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
