"""Preview panel scaffold for GUI v2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from src.gui.theme_v2 import SURFACE_FRAME_STYLE, STATUS_STRONG_LABEL_STYLE, STATUS_LABEL_STYLE, PADDING_MD
from .widgets.scrollable_frame_v2 import ScrollableFrame


class PreviewPanelV2(ttk.Frame):
    """Container for preview/inspector content (structure only)."""

    def __init__(self, master: tk.Misc, *, controller=None, theme=None, **kwargs) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=PADDING_MD, **kwargs)
        self.controller = controller
        self.theme = theme

        self.header_label = ttk.Label(self, text="Preview", style=STATUS_STRONG_LABEL_STYLE)
        self.header_label.pack(anchor=tk.W, pady=(0, 4))

        self._scroll = ScrollableFrame(self, style=SURFACE_FRAME_STYLE)
        self._scroll.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.body = ttk.Frame(self._scroll.inner, style=SURFACE_FRAME_STYLE)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.summary_label = ttk.Label(self.body, text="Stages: -", style=STATUS_LABEL_STYLE)
        self.summary_label.pack(anchor="w", pady=(0, 4))
        self.mode_label = ttk.Label(self.body, text="Mode: -", style=STATUS_LABEL_STYLE)
        self.mode_label.pack(anchor="w", pady=(0, 4))
        self.scope_label = ttk.Label(self.body, text="Scope: -", style=STATUS_LABEL_STYLE)
        self.scope_label.pack(anchor="w", pady=(0, 4))
        self.jobs_label = ttk.Label(self.body, text="Jobs: -", style=STATUS_LABEL_STYLE)
        self.jobs_label.pack(anchor="w", pady=(0, 4))
        self.current_image_label = ttk.Label(self.body, text="No image", style=STATUS_LABEL_STYLE)
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

    def update_from_job_draft(self, job_draft) -> None:
        """Update preview summary from job draft."""
        packs = getattr(job_draft, "packs", [])
        if not packs:
            self.summary_label.config(text="Job Draft: Empty")
            self.mode_label.config(text="")
            self.scope_label.config(text="")
            self.jobs_label.config(text="")
            return
        
        pack_names = [entry.pack_name for entry in packs]
        summary_text = f"Job Draft: {len(packs)} pack(s)"
        self.summary_label.config(text=summary_text)
        
        # Show pack names
        names_text = ", ".join(pack_names[:3])  # Show first 3
        if len(pack_names) > 3:
            names_text += f" (+{len(pack_names) - 3} more)"
        self.mode_label.config(text=f"Packs: {names_text}")
        
        # Check randomization
        randomizers = [entry for entry in packs if entry.config_snapshot.get("randomization_enabled")]
        rand_text = f"Randomizer: {len(randomizers)}/{len(packs)} enabled"
        self.scope_label.config(text=rand_text)
        
        self.jobs_label.config(text="")

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
