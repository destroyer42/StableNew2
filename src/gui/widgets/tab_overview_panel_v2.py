from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import BODY_LABEL_STYLE, HEADING_LABEL_STYLE, MUTED_LABEL_STYLE


@dataclass(frozen=True, slots=True)
class TabOverviewContent:
    tab_id: str
    tab_name: str
    compact_summary: str
    purpose: str
    inputs: tuple[str, ...]
    actions: tuple[str, ...]
    connections: tuple[str, ...]

    def to_detail_text(self) -> str:
        sections = [
            f"Purpose: {self.purpose}",
            "Inputs:\n- " + "\n- ".join(self.inputs),
            "Actions:\n- " + "\n- ".join(self.actions),
            "Connections:\n- " + "\n- ".join(self.connections),
        ]
        return "\n\n".join(section for section in sections if section.strip())


TAB_OVERVIEW_CONTENTS: dict[str, TabOverviewContent] = {
    "pipeline": TabOverviewContent(
        tab_id="pipeline",
        tab_name="Pipeline",
        compact_summary="Use Pipeline to prepare new image jobs, choose stage chains, preview outputs, and queue work without leaving the main generation workspace.",
        purpose="Pipeline is the queue-first workspace for fresh image generation and controlled stage execution.",
        inputs=(
            "Prompt packs, saved recipes, and base generation settings.",
            "Optional downstream stage settings for img2img, ADetailer, and upscale.",
            "Queue and history context from recent runs.",
        ),
        actions=(
            "Queue new generation jobs.",
            "Adjust effective stage settings before submission.",
            "Inspect previews, running jobs, and recent history in one place.",
        ),
        connections=(
            "Outputs can be opened later in Review for advanced reprocess work.",
            "Still-image outputs can feed SVD or Video Workflow tabs.",
            "Learning can consume completed runs after generation finishes.",
        ),
    ),
    "review": TabOverviewContent(
        tab_id="review",
        tab_name="Review",
        compact_summary="Use Review when you already have images and want to compare metadata, inspect effective settings, edit prompts, or submit deliberate queue-backed reprocess jobs.",
        purpose="Review is the canonical advanced reprocess workspace for existing images and lineage-aware edits.",
        inputs=(
            "Existing images from disk or recent job history.",
            "Embedded metadata, resolved prompts, and derived settings.",
            "Operator edits for prompts, stages, and ratings.",
        ),
        actions=(
            "Compare source and derived outputs.",
            "Inspect metadata and effective settings before queue-backed reprocessing.",
            "Import selected items into Learning when they should become curation evidence.",
        ),
        connections=(
            "Review receives outputs from Pipeline and history imports.",
            "Selected items can move into Learning for feedback and staged curation work.",
            "Reprocess actions eventually route back through the queue-backed pipeline.",
        ),
    ),
    "learning": TabOverviewContent(
        tab_id="learning",
        tab_name="Learning",
        compact_summary="Use Learning to design experiments, review discovered candidates, capture ratings, and manage post-execution evidence without changing the live runtime path.",
        purpose="Learning is the evidence-and-experiment workspace for ratings, review intake, and bounded learning plans.",
        inputs=(
            "Learning records from completed runs and discovered review items.",
            "Experiment plans, variable sweeps, and operator feedback.",
            "Optional post-execution learning metadata such as refinement or prompt-optimizer evidence.",
        ),
        actions=(
            "Design and save experiments.",
            "Review run outcomes and attach ratings or tags.",
            "Stage bounded learning plans without creating an alternate execution path.",
        ),
        connections=(
            "Learning consumes post-execution results from Pipeline and Review handoffs.",
            "The Discovered Review Inbox supports staged curation work inside this tab.",
            "Queued validation work still runs through the normal pipeline and queue services.",
        ),
    ),
    "svd": TabOverviewContent(
        tab_id="svd",
        tab_name="SVD Img2Vid",
        compact_summary="Use SVD Img2Vid to turn one still image into a short native SVD clip with explicit inference and postprocess controls.",
        purpose="SVD Img2Vid is the dedicated single-image native video generation surface.",
        inputs=(
            "One source image, either chosen manually or pulled from the latest output.",
            "Preset-driven SVD inference settings and optional postprocess controls.",
            "An output route for where generated clips should land.",
        ),
        actions=(
            "Queue a native SVD video job.",
            "Apply runtime defaults and inspect capability status.",
            "Review recent SVD runs from the same workspace.",
        ),
        connections=(
            "Often starts from a still image produced in Pipeline or Review.",
            "Generated clips can be routed into video-focused output areas or follow-on workflows.",
            "Movie Clips can assemble compatible outputs later if needed.",
        ),
    ),
    "video_workflow": TabOverviewContent(
        tab_id="video_workflow",
        tab_name="Video Workflow",
        compact_summary="Use Video Workflow for pinned workflow-driven video jobs that need a source image, optional anchors, and a workflow-specific prompt bundle.",
        purpose="Video Workflow is the queue-backed surface for workflow-authored video generation such as anchored multi-frame runs.",
        inputs=(
            "A source image and optional end or mid anchors.",
            "Workflow selection, motion profile, prompts, and output route.",
            "Optional source bundles handed off from history or other tabs.",
        ),
        actions=(
            "Queue a workflow-driven video generation job.",
            "Inspect workflow capabilities and source summaries before submission.",
            "Prepare anchored or chained video inputs without editing runtime internals.",
        ),
        connections=(
            "Can start from recent image outputs or explicit handoff bundles.",
            "Outputs can continue into Movie Clips for assembly work.",
            "The queue and history surfaces remain the system of record for execution.",
        ),
    ),
    "movie_clips": TabOverviewContent(
        tab_id="movie_clips",
        tab_name="Movie Clips",
        compact_summary="Use Movie Clips to assemble an ordered list of images or compatible outputs into a rendered clip with explicit format and quality settings.",
        purpose="Movie Clips is the assembly surface for ordered image sequences and compatible video-derived assets.",
        inputs=(
            "A folder of source images, a manual ordered list, or compatible handoff bundles.",
            "Clip settings such as FPS, codec, quality, and output mode.",
            "Optional latest-output shortcuts from other video surfaces.",
        ),
        actions=(
            "Load, reorder, and prune image sequences.",
            "Build clips with explicit assembly settings.",
            "Inspect source summaries before export.",
        ),
        connections=(
            "Receives outputs from Video Workflow and other video-producing tabs.",
            "Can also work from manually curated folders outside StableNew.",
            "Resulting clips remain part of the normal artifact and output-routing flow.",
        ),
    ),
}


def get_tab_overview_content(tab_id: str) -> TabOverviewContent:
    return TAB_OVERVIEW_CONTENTS[tab_id]


class TabOverviewPanel(ttk.Frame):
    """Compact, collapsible overview panel for major workspaces."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        content: TabOverviewContent,
        app_state: Any | None = None,
        expanded: bool = False,
        wraplength: int = 920,
        **kwargs: object,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=8, **kwargs)
        self.content = content
        self._app_state = app_state
        self._manual_expanded = bool(expanded)
        self._help_mode_enabled = bool(getattr(app_state, "help_mode_enabled", False))
        self._wraplength = wraplength

        self.columnconfigure(0, weight=1)

        header = ttk.Frame(self, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(
            header,
            text=f"About This Tab: {content.tab_name}",
            style=HEADING_LABEL_STYLE,
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.toggle_button = ttk.Button(
            header,
            text="",
            style="Dark.TButton",
            command=self.toggle_details,
            width=14,
        )
        self.toggle_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.summary_label = ttk.Label(
            self,
            text=content.compact_summary,
            style=BODY_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.summary_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        self.details_frame = ttk.Frame(self, style="Panel.TFrame")
        self.details_label = ttk.Label(
            self.details_frame,
            text=content.to_detail_text(),
            style=MUTED_LABEL_STYLE,
            justify="left",
            wraplength=wraplength,
        )
        self.details_label.grid(row=0, column=0, sticky="ew")

        if self._app_state is not None and hasattr(self._app_state, "subscribe"):
            try:
                self._app_state.subscribe("help_mode", self._on_help_mode_changed)
            except Exception:
                pass
        self._sync_details()

    def toggle_details(self) -> None:
        if self._help_mode_enabled:
            return
        self._manual_expanded = not self._manual_expanded
        self._sync_details()

    def is_expanded(self) -> bool:
        return bool(self._help_mode_enabled or self._manual_expanded)

    def destroy(self) -> None:
        if self._app_state is not None and hasattr(self._app_state, "unsubscribe"):
            try:
                self._app_state.unsubscribe("help_mode", self._on_help_mode_changed)
            except Exception:
                pass
        super().destroy()

    def _on_help_mode_changed(self) -> None:
        self._help_mode_enabled = bool(getattr(self._app_state, "help_mode_enabled", False))
        self._sync_details()

    def _sync_details(self) -> None:
        if self.is_expanded():
            self.details_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
            if self._help_mode_enabled:
                self.toggle_button.configure(text="Help Mode On", state="disabled")
            else:
                self.toggle_button.configure(text="Hide Guidance", state="normal")
        else:
            self.details_frame.grid_remove()
            self.toggle_button.configure(text="Show Guidance", state="normal")
