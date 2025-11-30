from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui import theme_v2
from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE, SECONDARY_BUTTON_STYLE


class PromptSection(ttk.Frame):
    def __init__(self, master: tk.Misc, *, title: str = "Prompt", height: int = 3, **kwargs) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=4, **kwargs)
        ttk.Label(self, text=title, style=BODY_LABEL_STYLE).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.text = tk.Text(
            self,
            height=height,
            wrap="word",
            bg=theme_v2.BACKGROUND_ELEVATED,
            fg=theme_v2.TEXT_PRIMARY,
            insertbackground=theme_v2.TEXT_PRIMARY,
            relief="flat",
        )
        self.text.grid(row=1, column=0, sticky="nsew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

    def get(self) -> str:
        return self.text.get("1.0", tk.END).strip()

    def set(self, value: str) -> None:
        self.text.delete("1.0", tk.END)
        if value:
            self.text.insert("1.0", value)


class SamplerSection(ttk.Frame):
    def __init__(self, master: tk.Misc, *, title: str = "Sampler / Steps / CFG", **kwargs) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=4, **kwargs)
        ttk.Label(self, text=title, style=BODY_LABEL_STYLE).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))

        self.sampler_var = tk.StringVar()
        self.steps_var = tk.StringVar(value="20")
        self.cfg_var = tk.StringVar(value="7.0")

        ttk.Label(self, text="Sampler", style=BODY_LABEL_STYLE).grid(row=1, column=0, sticky="w", padx=(0, 4))
        ttk.Entry(self, textvariable=self.sampler_var, width=18).grid(row=1, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(self, text="Steps", style=BODY_LABEL_STYLE).grid(row=1, column=2, sticky="w", padx=(0, 4))
        ttk.Entry(self, textvariable=self.steps_var, width=8).grid(row=1, column=3, sticky="ew")

        ttk.Label(self, text="CFG", style=BODY_LABEL_STYLE).grid(row=2, column=0, sticky="w", padx=(0, 4), pady=(4, 0))
        ttk.Entry(self, textvariable=self.cfg_var, width=8).grid(row=2, column=1, sticky="ew", pady=(4, 0))

        for col in range(4):
            self.columnconfigure(col, weight=1 if col in (1, 3) else 0)


class SeedSection(ttk.Frame):
    def __init__(self, master: tk.Misc, *, title: str = "Seed", **kwargs) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=4, **kwargs)
        ttk.Label(self, text=title, style=BODY_LABEL_STYLE).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.seed_var = tk.StringVar(value="0")
        ttk.Entry(self, textvariable=self.seed_var, width=14).grid(row=1, column=0, sticky="ew")
        self.randomize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Randomize", variable=self.randomize_var, style=SECONDARY_BUTTON_STYLE).grid(
            row=1, column=1, sticky="w", padx=(8, 0)
        )
        self.columnconfigure(0, weight=1)


__all__ = ["PromptSection", "SamplerSection", "SeedSection"]
