"""Preview panel scaffold for GUI v2."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import (
    ACCENT_GOLD,
    ASWF_ERROR_RED,
    BACKGROUND_ELEVATED,
    PADDING_MD,
    SECONDARY_BUTTON_STYLE,
    STATUS_LABEL_STYLE,
    STATUS_STRONG_LABEL_STYLE,
    SURFACE_FRAME_STYLE,
    TEXT_PRIMARY,
)
from .widgets.scrollable_frame_v2 import ScrollableFrame


class PreviewPanelV2(ttk.Frame):
    """Container for preview/inspector content (structure only)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any | None = None,
        app_state: Any | None = None,
        theme: Any | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, style=SURFACE_FRAME_STYLE, padding=PADDING_MD, **kwargs)
        self.controller = controller
        self.app_state = app_state
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
        self.metadata_text = tk.Text(self.body, height=5, wrap="word", bg=BACKGROUND_ELEVATED, fg=TEXT_PRIMARY, relief="flat")
        self.metadata_text.pack(fill=tk.X)

        self.queue_header = ttk.Label(self.body, text="Queue", style=STATUS_STRONG_LABEL_STYLE)
        self.queue_header.pack(anchor="w", pady=(8, 2))
        self.queue_status_label = ttk.Label(self.body, text="Queue Status: Idle", style=STATUS_LABEL_STYLE)
        self.queue_status_label.pack(anchor="w", pady=(0, 2))
        self.queue_items_text = tk.Text(
            self.body,
            height=4,
            wrap="word",
            bg=BACKGROUND_ELEVATED,
            fg=TEXT_PRIMARY,
            relief="flat",
            padx=4,
            pady=2,
        )
        self.queue_items_text.pack(fill=tk.BOTH, pady=(0, 4))
        self.queue_items_text.config(state=tk.DISABLED)
        self.running_job_label = ttk.Label(self.body, text="Running Job: None", style=STATUS_LABEL_STYLE)
        self.running_job_label.pack(anchor="w", pady=(0, 2))
        self.running_job_status_label = ttk.Label(self.body, text="Status: Idle", style=STATUS_LABEL_STYLE)
        self.running_job_status_label.pack(anchor="w")

        self.queue_controls_frame = ttk.Frame(self.body, style=SURFACE_FRAME_STYLE)
        self.queue_controls_frame.pack(fill=tk.X, pady=(8, 0))

        self.pause_button = ttk.Button(
            self.queue_controls_frame,
            text="Pause Queue",
            style=SECONDARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_pause_queue"),
        )
        self.pause_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self.resume_button = ttk.Button(
            self.queue_controls_frame,
            text="Resume Queue",
            style=SECONDARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_resume_queue"),
        )
        self.resume_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self.cancel_button = ttk.Button(
            self.queue_controls_frame,
            text="Cancel Active",
            style=SECONDARY_BUTTON_STYLE,
            command=lambda: self._invoke_controller("on_cancel_current_job"),
        )
        self.cancel_button.pack(side=tk.LEFT, expand=True, fill=tk.X)

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

        names = ", ".join(pack_names[:3])
        if len(pack_names) > 3:
            names += f" (+{len(pack_names) - 3} more)"
        self.mode_label.config(text=f"Packs: {names}")

        randomizers = [entry for entry in packs if entry.config_snapshot.get("randomization_enabled")]
        rand_text = f"Randomizer: {len(randomizers)}/{len(packs)} enabled"
        self.scope_label.config(text=rand_text)

        self.jobs_label.config(text="")

    def update_from_controls(self, sidebar) -> None:
        """Update preview summary from sidebar controls."""
        enabled = getattr(sidebar, "get_enabled_stages", lambda: [])()
        ordered = ["txt2img", "img2img", "adetailer", "upscale"]
        enabled_set = set(enabled)
        canonical = [stage for stage in ordered if stage in enabled_set]
        stage_labels = {
            "txt2img": "txt2img",
            "img2img": "img2img",
            "adetailer": "ADetailer",
            "upscale": "upscale",
        }
        stages_text = " → ".join(stage_labels[stage] for stage in canonical) or "-"
        self.summary_label.config(text=f"Stages: {stages_text}")
        self.mode_label.config(text=f"Mode: {getattr(sidebar, 'get_run_mode', lambda: '-')()}")
        self.scope_label.config(text=f"Scope: {getattr(sidebar, 'get_run_scope', lambda: '-')()}")
        jobs, images_per_job = getattr(sidebar, "get_job_counts", lambda: (0, 0))()
        total = jobs * max(1, images_per_job)
        self.jobs_label.config(text=f"Jobs: {jobs} | Images/job: {images_per_job} | Total: {total}")

    # ------------------------------------------------------------------
    # Queue / runner helpers
    # ------------------------------------------------------------------

    def update_queue_items(self, items: list[str] | None) -> None:
        """Render pending queue summary lines."""
        contents = "\n".join(items or ["No pending jobs."])
        self.queue_items_text.config(state=tk.NORMAL)
        self.queue_items_text.delete(1.0, tk.END)
        self.queue_items_text.insert(tk.END, contents)
        self.queue_items_text.config(state=tk.DISABLED)

    def update_running_job(self, job: dict[str, Any] | None) -> None:
        """Display the currently running job."""
        if not job:
            self.running_job_label.config(text="Running Job: None")
            self.running_job_status_label.config(text="Status: Idle")
            return

        job_id = job.get("job_id") or "Unknown"
        payload = job.get("payload") or {}
        packs = payload.get("packs") or []
        pack_count = len(packs) if isinstance(packs, list) else 0
        status = job.get("status") or "running"
        self.running_job_label.config(text=f"Running Job: {job_id} ({pack_count} packs)")
        self.running_job_status_label.config(text=f"Status: {status.title()}")

    def update_queue_status(self, status: str | None) -> None:
        """Update the queue status badge."""
        normalized = (status or "idle").lower()
        text = normalized.title()
        self.queue_status_label.config(text=f"Queue Status: {text}")
        color = TEXT_PRIMARY
        if normalized == "running":
            color = ACCENT_GOLD
        elif normalized == "paused":
            color = ASWF_ERROR_RED
        self.queue_status_label.config(foreground=color)

    def _invoke_controller(self, method_name: str) -> None:
        """Call a controller hook if available."""
        controller = self.controller
        if not controller:
            return
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass
