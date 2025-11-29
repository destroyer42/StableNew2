# Renamed from run_control_bar.py to run_control_bar_v2.py


from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from src.gui.state import PipelineState
from src.gui.views.stage_cards_panel import StageCardsPanel
from src.pipeline.randomizer_v2 import build_prompt_variants
from src.pipeline.run_plan import PlannedJob, RunPlan


class RunControlBar(ttk.Frame):
    """Top-of-pipeline run controls (UI-only scaffold)."""

    def __init__(
        self,
        master: tk.Misc,
        pipeline_state: PipelineState,
        stage_cards_panel: StageCardsPanel,
        prompt_workspace_state=None,
        on_run_now: Callable[[], None] | None = None,
        on_add_queue: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.state = pipeline_state
        self.stage_cards_panel = stage_cards_panel
        self.prompt_workspace_state = prompt_workspace_state
        self.on_run_now = on_run_now
        self.on_add_queue = on_add_queue

        # Stage toggles
        toggle_frame = ttk.Frame(self)
        toggle_frame.pack(fill="x", pady=(0, 4))
        ttk.Label(toggle_frame, text="Stages:").pack(side="left", padx=(0, 6))
        self.txt2img_var = tk.BooleanVar(value=self.state.stage_txt2img_enabled)
        self.img2img_var = tk.BooleanVar(value=self.state.stage_img2img_enabled)
        self.upscale_var = tk.BooleanVar(value=self.state.stage_upscale_enabled)
        ttk.Checkbutton(
            toggle_frame, text="txt2img", variable=self.txt2img_var, command=self._on_stage_toggle
        ).pack(side="left", padx=2)
        ttk.Checkbutton(
            toggle_frame, text="img2img/adetailer", variable=self.img2img_var, command=self._on_stage_toggle
        ).pack(side="left", padx=2)
        ttk.Checkbutton(
            toggle_frame, text="upscale", variable=self.upscale_var, command=self._on_stage_toggle
        ).pack(side="left", padx=2)

        # Run scope
        scope_frame = ttk.Frame(self)
        scope_frame.pack(fill="x", pady=(0, 4))
        ttk.Label(scope_frame, text="Run Scope:").pack(side="left", padx=(0, 6))
        self.scope_var = tk.StringVar(value=getattr(self.state, "run_scope", "full"))
        scope_options = [("Selected only", "selected"), ("From selected", "from_selected"), ("Full pipeline", "full")]
        for text, val in scope_options:
            ttk.Radiobutton(scope_frame, text=text, value=val, variable=self.scope_var, command=self._on_scope_change).pack(
                side="left", padx=2
            )

        # Run buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", pady=(0, 4))
        self.run_now_button = ttk.Button(btn_frame, text="Run Now", command=self._on_run_clicked)
        self.run_now_button.pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="Add to Queue", command=self._on_queue_clicked).pack(side="left")

    def set_run_enabled(self, enabled: bool) -> None:
        if enabled:
            self.run_now_button.state(["!disabled"])
        else:
            self.run_now_button.state(["disabled"])

        # Summary label
        self.summary_var = tk.StringVar()
        ttk.Label(self, textvariable=self.summary_var).pack(anchor="w")
        self._refresh_summary()

    def _on_stage_toggle(self) -> None:
        self.state.stage_txt2img_enabled = bool(self.txt2img_var.get())
        self.state.stage_img2img_enabled = bool(self.img2img_var.get())
        self.state.stage_upscale_enabled = bool(self.upscale_var.get())
        try:
            self.stage_cards_panel.set_stage_enabled("txt2img", self.state.stage_txt2img_enabled)
            self.stage_cards_panel.set_stage_enabled("img2img", self.state.stage_img2img_enabled)
            self.stage_cards_panel.set_stage_enabled("upscale", self.state.stage_upscale_enabled)
        except Exception:
            pass
        self._refresh_summary()

    def _on_scope_change(self) -> None:
        self.state.run_scope = self.scope_var.get()
        self._refresh_summary()

    def _on_run_clicked(self) -> None:
        if callable(self.on_run_now):
            try:
                self.on_run_now()
            except Exception:
                pass

    def _on_queue_clicked(self) -> None:
        if callable(self.on_add_queue):
            try:
                self.on_add_queue()
            except Exception:
                pass

    def _refresh_summary(self) -> None:
        enabled = []
        if self.state.stage_txt2img_enabled:
            enabled.append("txt2img")
        if self.state.stage_img2img_enabled:
            enabled.append("img2img/adetailer")
        if self.state.stage_upscale_enabled:
            enabled.append("upscale")
        stages_text = ", ".join(enabled) if enabled else "none"
        scope_text = getattr(self.state, "run_scope", "full")
        mode_text = self.state.run_mode
        plan = self._build_run_plan()
        self.summary_var.set(
            f"Stages: {stages_text} | Scope: {scope_text} | Mode: {mode_text} | Jobs: {plan.total_jobs} | Images: {plan.total_images}"
        )

    def _build_run_plan(self) -> RunPlan:
        """Build a lightweight run plan for summary purposes (no execution)."""
        enabled_stages: list[str] = []
        if self.state.stage_txt2img_enabled:
            enabled_stages.append("txt2img")
        if self.state.stage_img2img_enabled:
            enabled_stages.append("img2img")
        if self.state.stage_upscale_enabled:
            enabled_stages.append("upscale")

        prompt_text = ""
        metadata = None
        try:
            if self.prompt_workspace_state is not None:
                prompt_text = self.prompt_workspace_state.get_current_prompt_text()
                metadata = self.prompt_workspace_state.get_current_prompt_metadata()
        except Exception:
            prompt_text = ""
            metadata = None

        variants = build_prompt_variants(
            prompt_text=prompt_text,
            metadata=metadata,
            mode=getattr(self.state, "randomizer_mode", "off"),
            max_variants=getattr(self.state, "max_variants", 1),
        )
        jobs: list[PlannedJob] = []
        batch_runs = max(1, getattr(self.state, "batch_runs", 1))
        for batch_idx in range(batch_runs):
            for variant_id, variant_prompt in enumerate(variants):
                for stage in enabled_stages:
                    jobs.append(
                        PlannedJob(
                            stage_name=stage,
                            prompt_text=variant_prompt,
                            variant_id=variant_id,
                            batch_index=batch_idx,
                        )
                    )

        total_jobs = len(jobs)
        total_images = total_jobs  # placeholder assumption
        return RunPlan(
            jobs=jobs,
            total_jobs=total_jobs,
            total_images=total_images,
            enabled_stages=enabled_stages,
        )


RunControlBar = RunControlBar
