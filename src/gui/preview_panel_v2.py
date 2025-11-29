"""Preview panel scaffold for GUI v2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme as theme_mod
from .widgets.scrollable_frame_v2 import ScrollableFrame


class PreviewPanelV2(ttk.Frame):
    """Container for preview/inspector content (structure only)."""

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs) -> None:
        style_name = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        super().__init__(master, style=style_name, padding=theme_mod.PADDING_MD, **kwargs)
        self.controller = controller
        self.theme = theme

        header_style = getattr(theme, "STATUS_STRONG_LABEL_STYLE", theme_mod.STATUS_STRONG_LABEL_STYLE)
        self.header_label = ttk.Label(self, text="Preview", style=header_style)
        self.header_label.pack(anchor=tk.W, pady=(0, 4))

        body_style = getattr(theme, "SURFACE_FRAME_STYLE", theme_mod.SURFACE_FRAME_STYLE)
        self._scroll = ScrollableFrame(self, style=body_style)
        self._scroll.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.body = ttk.Frame(self._scroll.inner, style=body_style)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.summary_label = ttk.Label(self.body, text="Stages: -", style=theme_mod.STATUS_LABEL_STYLE)
        self.summary_label.pack(anchor="w", pady=(0, 4))
        self.mode_label = ttk.Label(self.body, text="Mode: -", style=theme_mod.STATUS_LABEL_STYLE)
        self.mode_label.pack(anchor="w", pady=(0, 4))
        self.scope_label = ttk.Label(self.body, text="Scope: -", style=theme_mod.STATUS_LABEL_STYLE)
        self.scope_label.pack(anchor="w", pady=(0, 4))
        self.jobs_label = ttk.Label(self.body, text="Jobs: -", style=theme_mod.STATUS_LABEL_STYLE)
        self.jobs_label.pack(anchor="w", pady=(0, 4))
        self.current_image_label = ttk.Label(self.body, text="No image", style=theme_mod.STATUS_LABEL_STYLE)
        self.current_image_label.pack(anchor="w", pady=(4, 2))
        self.metadata_text = tk.Text(self.body, height=5, wrap="word")
        self.metadata_text.pack(fill=tk.X)

    def set_current_image(self, image_path: str, metadata: dict) -> None:
        """Set the current image and metadata."""
        self.current_image_label.config(text=f"Image: {image_path}")
        self.metadata_text.delete(1.0, tk.END)
        self.metadata_text.insert(tk.END, str(metadata))

    def clear(self) -> None:
        """Clear the current image and metadata."""
        self.current_image_label.config(text="No image")
        self.metadata_text.delete(1.0, tk.END)

    def update_from_controls(self, sidebar) -> None:
        """Update preview summary from sidebar controls."""
        enabled = getattr(sidebar, "get_enabled_stages", lambda: [])()
        stages_text = ", ".join([s.title() for s in enabled]) or "-"
        self.summary_label.config(text=f"Stages: {stages_text}")
        self.mode_label.config(text=f"Mode: {getattr(sidebar, 'get_run_mode', lambda: '-')()}")
        self.scope_label.config(text=f"Scope: {getattr(sidebar, 'get_run_scope', lambda: '-')()}")
        jobs, images_per_job = getattr(sidebar, "get_job_counts", lambda: (0, 0))()
        total = jobs * max(1, images_per_job)
        self.jobs_label.config(text=f"Jobs: {jobs} | Images/job: {images_per_job} | Total: {total}")
