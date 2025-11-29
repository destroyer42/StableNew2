"""Negative prompt editor for GUI V2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.config import app_config
from src.gui import theme_v2 as theme_mod


class NegativePromptPanelV2(ttk.Frame):
    """Multi-line editor for negative prompts with clear/reset helpers."""

    def __init__(self, master: tk.Misc, *, theme=None, **kwargs) -> None:
        style_name = theme_mod.SURFACE_FRAME_STYLE
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.theme = theme or theme_mod

        header_style = theme_mod.STATUS_STRONG_LABEL_STYLE
        ttk.Label(self, text="Negative Prompt", style=header_style).pack(anchor=tk.W, pady=(0, 4))

        self.text = tk.Text(self, height=4, wrap="word")
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.insert("1.0", app_config.negative_prompt_default())

        buttons = ttk.Frame(self, style=style_name)
        buttons.pack(fill=tk.X, pady=(theme_mod.PADDING_SM, 0))
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Reset", command=self.reset_to_default).pack(side=tk.LEFT, padx=(4, 0))

    def get_negative_prompt(self) -> str:
        return self.text.get("1.0", tk.END).strip()

    def set_negative_prompt(self, text: str) -> None:
        self.text.delete("1.0", tk.END)
        if text:
            self.text.insert("1.0", text)

    def clear(self) -> None:
        self.set_negative_prompt("")

    def reset_to_default(self) -> None:
        self.set_negative_prompt(app_config.negative_prompt_default())


__all__ = ["NegativePromptPanelV2"]
