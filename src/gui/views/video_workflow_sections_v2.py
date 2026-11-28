"""Section builders for the Video Workflow tab's left pane (VID-UX-384).

Mechanical extraction from the tab so the tab file shrinks: each function builds one section into ``body`` and
attaches the same attributes to ``tab`` that the tab always had.  Presentation only; no controller access.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, cast

from src.gui.help_text.stage_setting_help_v2 import VIDEO_WORKFLOW_SETTING_HELP
from src.gui.help_text.workflow_guidance_v2 import build_video_workflow_guidance
from src.gui.layout_v2 import configure_grid_columns
from src.gui.theme_v2 import style_text_widget
from src.gui.tooltip import attach_tooltip
from src.gui.views.video_workflow_continue_v2 import ContinueClipPanel
from src.gui.views.video_workflow_controls_panel_v2 import WorkflowControlsPanel
from src.gui.views.video_workflow_motion_intent_v2 import MotionIntentPanel
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerPanel
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content
from src.state.output_routing import (
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_REPROCESS,
    OUTPUT_ROUTE_TESTING,
)

_MOTION_PROFILES = ("gentle", "balanced", "dynamic")
_OUTPUT_ROUTES = (OUTPUT_ROUTE_REPROCESS, OUTPUT_ROUTE_MOVIE_CLIPS, OUTPUT_ROUTE_TESTING)
_CAMERA_PRESETS = (
    "none",
    "dolly_in",
    "dolly_out",
    "truck_left",
    "truck_right",
    "orbit_left",
    "orbit_right",
    "tilt_up",
    "tilt_down",
)
_DEPTH_INPUT_MODES = ("none", "auto", "upload")


def build_settings_section(tab: Any, body: ttk.Frame) -> None:
    """Row 1: the task's own settings (motion phrase, preset, duration); row 3: Advanced (engine, raw length, seed,
    smoothing, negative prompt, declared controls).  V1-1 (section 5.2): the summary line names the engine."""

    visible = ttk.Frame(body, style="Panel.TFrame")
    visible.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    tab.settings_block = visible
    tab._settings_frame = visible
    configure_grid_columns(visible, tab._form_columns)
    tab.suggestion_reasons_var = tk.StringVar(value="")
    tab.why_button = ttk.Button(
        visible, text="Why these settings?", style="Dark.TButton", command=tab._toggle_reasons
    )
    tab.why_button.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
    reasons_label = ttk.Label(
        visible, textvariable=tab.suggestion_reasons_var, style="Muted.TLabel", justify="left"
    )
    reasons_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    bind_wraplength(reasons_label)
    reasons_label.grid_remove()
    tab.reasons_label = reasons_label
    _build_driver_row(tab, visible, row=2)
    _build_continue_rows(tab, visible, row=2)  # never shown with the driver row: one task at a time
    _build_end_image_row(tab, visible, row=4)
    tab.motion_intent_panel = MotionIntentPanel(
        visible,
        on_preset=tab._on_preset_chosen,
        on_reset_preset=tab._on_reset_preset,
        on_duration=tab._on_duration_entered,
        on_suggest=lambda: tab.motion_ai_host.suggest(),
        on_undo_suggestion=lambda: tab.motion_ai_host.undo(),
    )
    tab.motion_intent_panel.grid(row=3, column=0, columnspan=4, sticky="ew")
    # Advanced (today's More settings): the section keeps its ``advanced_section`` name; it opens by itself for a
    # required control or an experimental engine (see _apply_workflow_visibility).
    tab.advanced_section = DisclosureSection(body, title="Advanced")
    tab.advanced_section.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    tab.advanced_section.toggle_button.configure(command=tab._toggle_settings)
    adv = tab.advanced_section.body
    tab._advanced_frame = adv
    configure_grid_columns(adv, tab._form_columns)
    # N13 (beside the engine picker, under Advanced since V1-1): unrated speed arms and superseded arms are listed only when this is on.
    tab.show_experimental_check = ttk.Checkbutton(
        adv,
        text="Show experimental",
        variable=tab.show_experimental_var,
        style="Dark.TCheckbutton",
    )
    tab.show_experimental_check.grid(row=0, column=3, sticky="w", padx=(8, 0), pady=(0, 6))
    attach_tooltip(
        tab.show_experimental_check,
        "Also list unrated speed arms and superseded engine arms (A14B CK attention and SVI, "
        "HunyuanVideo 1.5). They stay experimental: Queue warns and records your opt-in.",
    )
    tab.workflow_combo = cast(
        ttk.Combobox,
        tab._add_labeled_entry(
            adv,
            0,
            "Engine",
            combo=True,
            variable=tab.workflow_label_var,
            help_key="workflow",
        ),
    )
    # Only the picker's selection event is evidence that the operator chose this engine (consent for an
    # experimental one); task choices and restores write the variable without it.
    tab.workflow_combo.bind("<<ComboboxSelected>>", tab._on_workflow_selected, add="+")
    ttk.Label(
        adv,
        textvariable=tab.workflow_detail_var,
        style="Muted.TLabel",
        wraplength=640,
        justify="left",
    ).grid(row=0, column=3, sticky="w", padx=(8, 0), pady=(0, 6))
    tab.motion_combo = tab._add_labeled_entry(
        adv,
        1,
        "Motion profile",
        combo=True,
        variable=tab.motion_profile_var,
        values=_MOTION_PROFILES,
        help_key="motion",
    )
    tab.motion_label = tab.motion_combo.master.grid_slaves(row=1, column=0)[0]
    # The raw generation length (the Duration above resolves to one of these), only for a declared frame-count policy.
    tab.frame_count_frame = ttk.Frame(adv, style="Panel.TFrame")
    tab.frame_count_frame.grid(row=1, column=2, columnspan=2, sticky="w", padx=(6, 0))
    frame_count_label = ttk.Label(tab.frame_count_frame, text="Length", style="Dark.TLabel")
    frame_count_label.pack(side="left", padx=(0, 6))
    tab.frame_count_combo = ttk.Combobox(
        tab.frame_count_frame,
        textvariable=tab.frame_count_var,
        values=[],
        state="readonly",
        style="Dark.TCombobox",
        width=22,
    )
    tab.frame_count_combo.pack(side="left")
    tab.frame_count_advisory_label = ttk.Label(
        tab.frame_count_frame,
        textvariable=tab.frame_count_advisory_var,
        style="Dark.TLabel",
        wraplength=320,
        justify="left",
    )
    tab.frame_count_advisory_label.pack(side="left", padx=(8, 0))
    tab._attach_setting_help(
        "frame_count",
        VIDEO_WORKFLOW_SETTING_HELP["frame_count"],
        frame_count_label,
        tab.frame_count_combo,
    )
    tab.seed_label = ttk.Label(adv, text="Seed", style="Dark.TLabel")
    tab.seed_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
    tab.seed_entry = ttk.Entry(adv, textvariable=tab.seed_var, style="Dark.TEntry", width=40)
    tab.seed_entry.grid(row=2, column=1, sticky="ew", pady=(0, 6))
    tab._attach_setting_help(
        "seed", VIDEO_WORKFLOW_SETTING_HELP["seed"], tab.seed_label, tab.seed_entry
    )
    tab.smooth_check = ttk.Checkbutton(
        adv,
        text="Smooth with RIFE",
        variable=tab.smooth_var,
        style="Dark.TCheckbutton",
    )
    tab.smooth_check.grid(row=2, column=2, columnspan=2, sticky="w", padx=(6, 0), pady=(0, 6))
    tab._attach_setting_help(
        "rife_smooth", VIDEO_WORKFLOW_SETTING_HELP["rife_smooth"], tab.smooth_check
    )
    negative_label = ttk.Label(adv, text="Negative", style="Dark.TLabel")
    negative_label.grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=(0, 6))
    tab.negative_prompt_text = tk.Text(
        adv,
        height=4,
        wrap="word",
    )
    style_text_widget(tab.negative_prompt_text, elevated=True)
    tab.negative_prompt_text.grid(row=3, column=1, columnspan=3, sticky="nsew", pady=(0, 6))
    tab._attach_setting_help(
        "negative",
        VIDEO_WORKFLOW_SETTING_HELP["negative"],
        negative_label,
        tab.negative_prompt_text,
    )
    # Controls the selected workflow declares (e.g. Animate-2 motion prompt / pose strength).
    tab.workflow_controls_panel = WorkflowControlsPanel(
        adv, on_change=tab._refresh_workspace_summary
    )
    tab.workflow_controls_panel.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    tab.workflow_controls_panel.grid_remove()
    svd_row = ttk.Frame(adv, style="Panel.TFrame")
    svd_row.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    tab.use_svd_button = ttk.Button(
        svd_row, text="Use native SVD instead", style="Dark.TButton", command=tab._on_use_svd
    )
    tab.use_svd_button.pack(side="left")
    ttk.Label(
        svd_row,
        text="Opens the Stable Video Diffusion tab with this source image.",
        style="Muted.TLabel",
    ).pack(side="left", padx=(8, 0))


def _build_driver_row(tab: Any, parent: ttk.Frame, *, row: int) -> None:
    """V1-3: the driving video, above the preset and duration; shown for the follow-a-driver task only."""

    clip = ttk.Frame(parent, style="Panel.TFrame")
    clip.grid(row=row, column=0, columnspan=4, sticky="ew")
    clip.columnconfigure(0, weight=1)
    clip.grid_remove()
    tab.follow_clip_frame = clip
    tab.pose_video_frame = ttk.Frame(clip, style="Panel.TFrame")
    tab.pose_video_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    label = ttk.Label(tab.pose_video_frame, text="Driving video", style="Dark.TLabel")
    label.pack(side="left", padx=(0, 6))
    tab.pose_video_entry = ttk.Entry(
        tab.pose_video_frame, textvariable=tab.pose_video_var, style="Dark.TEntry", width=34
    )
    tab.pose_video_entry.pack(side="left", fill="x", expand=True)
    tab.pose_video_entry.bind("<KeyRelease>", tab._on_driver_typed, add="+")
    tab.pose_video_entry.bind("<<Paste>>", tab._on_driver_typed, add="+")
    for sequence in ("<Return>", "<FocusOut>"):
        tab.pose_video_entry.bind(sequence, tab._on_driver_entered, add="+")
    ttk.Button(
        tab.pose_video_frame,
        text="Browse...",
        style="Dark.TButton",
        command=tab._on_browse_pose_video,
    ).pack(side="left", padx=(6, 0))
    tab._attach_setting_help(
        "pose_video", VIDEO_WORKFLOW_SETTING_HELP["pose_video"], label, tab.pose_video_entry
    )


def _build_continue_rows(tab: Any, parent: ttk.Frame, *, row: int) -> None:
    """V1-6: the clip, the frame to continue from and the fallbacks, for the "Continue a clip" task only."""

    panel = ContinueClipPanel(
        parent,
        on_frame=tab._on_continue_frame,
        on_prompt_only=tab._continue_as_prompt_only,
        on_end_picture=tab._continue_to_picture,
    )
    panel.grid(row=row, column=0, columnspan=4, sticky="ew")
    panel.grid_remove()
    tab.continue_panel = panel


def _build_end_image_row(tab: Any, parent: ttk.Frame, *, row: int) -> None:
    """V1 end frame: the end image, for the "Start and end image" task only (the start image is the header's)."""

    frame = ttk.Frame(parent, style="Panel.TFrame")
    frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    frame.grid_remove()
    tab.end_image_frame = frame
    label = ttk.Label(frame, text="End image", style="Dark.TLabel")
    label.pack(side="left", padx=(0, 6))
    entry = ttk.Entry(frame, textvariable=tab.end_anchor_var, style="Dark.TEntry", width=34)
    entry.pack(side="left", fill="x", expand=True)
    ttk.Button(
        frame, text="Browse...", style="Dark.TButton", command=tab._on_browse_end_anchor
    ).pack(side="left", padx=(6, 0))
    tab._attach_setting_help("end_anchor", VIDEO_WORKFLOW_SETTING_HELP["end_anchor"], label, entry)


def build_keyframes_section(tab: Any, body: ttk.Frame) -> None:
    """Row 7: anchors and camera/depth conditioning; hidden when the engine declares none of them."""

    tab.keyframes_section = DisclosureSection(body, title="Keyframes and conditioning")
    tab.keyframes_section.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    keyframes = tab.keyframes_section.body
    configure_grid_columns(keyframes, tab._form_columns)
    tab.end_anchor_entry = tab._add_labeled_entry(
        keyframes,
        0,
        "End Anchor",
        variable=tab.end_anchor_var,
        help_key="end_anchor",
    )
    tab.end_anchor_browse = ttk.Button(
        keyframes, text="Browse...", style="Dark.TButton", command=tab._on_browse_end_anchor
    )
    tab.end_anchor_browse.grid(row=0, column=2, sticky="ew", padx=(6, 0))

    tab.mid_anchors_entry = tab._add_labeled_entry(
        keyframes,
        1,
        "Mid Anchors",
        variable=tab.mid_anchors_var,
        width=60,
        helper="Optional, separated by ';'",
        help_key="mid_anchors",
    )
    tab.mid_anchors_browse = ttk.Button(
        keyframes, text="Browse...", style="Dark.TButton", command=tab._on_browse_mid_anchors
    )
    tab.mid_anchors_browse.grid(row=1, column=2, sticky="ew", padx=(6, 0))
    # PR-GUI-110: collapsible; every control and value stays alive while collapsed, and a collapsed header
    # that hides non-default values says so (see _refresh_conditioning_status).  PR-VID-UX-313: the whole
    # section is hidden for a workflow that declares neither camera nor depth conditioning.
    tab.conditioning_section = DisclosureSection(keyframes, title="Advanced Conditioning")
    tab.conditioning_section.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 6))
    conditioning_frame = tab.conditioning_section.body
    tab.conditioning_frame = conditioning_frame
    configure_grid_columns(conditioning_frame, tab._form_columns)
    tab._add_labeled_entry(
        conditioning_frame,
        0,
        "Camera Preset",
        combo=True,
        variable=tab.camera_preset_var,
        values=_CAMERA_PRESETS,
        help_key="camera_preset",
    )
    tab._add_labeled_entry(
        conditioning_frame,
        1,
        "Camera Strength",
        variable=tab.camera_strength_var,
        help_key="camera_strength",
    )
    tab._add_labeled_entry(
        conditioning_frame,
        2,
        "Depth Source",
        combo=True,
        variable=tab.depth_mode_var,
        values=_DEPTH_INPUT_MODES,
        help_key="depth_mode",
    )
    tab.depth_path_entry = cast(
        ttk.Entry,
        tab._add_labeled_entry(
            conditioning_frame,
            3,
            "Depth Map",
            variable=tab.depth_path_var,
            help_key="depth_path",
        ),
    )
    tab.depth_browse_button = ttk.Button(
        conditioning_frame,
        text="Browse...",
        style="Dark.TButton",
        command=tab._on_browse_depth_map,
    )
    tab.depth_browse_button.grid(row=3, column=2, sticky="ew", padx=(6, 0), pady=(0, 6))
    tab._add_labeled_entry(
        conditioning_frame,
        4,
        "ControlNet Model",
        variable=tab.controlnet_model_var,
        help_key="controlnet_model",
    )
    tab._add_labeled_entry(
        conditioning_frame,
        5,
        "Control Weight",
        variable=tab.controlnet_weight_var,
        help_key="controlnet_weight",
    )
    tab._add_labeled_entry(
        conditioning_frame,
        6,
        "Guidance Start",
        variable=tab.controlnet_guidance_start_var,
        help_key="controlnet_guidance_start",
    )
    tab._add_labeled_entry(
        conditioning_frame,
        7,
        "Guidance End",
        variable=tab.controlnet_guidance_end_var,
        help_key="controlnet_guidance_end",
    )


def build_details_section(tab: Any, body: ttk.Frame) -> None:
    """Row 8: what the job will use, where its output goes, and the reference text for the tab."""

    tab.details_section = DisclosureSection(body, title="Details")
    tab.details_section.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    details = tab.details_section.body
    configure_grid_columns(details, tab._form_columns)
    # The effective-settings string repeats what the form shows, so it is disclosed on demand.
    tab.effective_settings_section = DisclosureSection(details, title="Effective settings")
    tab.effective_settings_section.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 6))
    tab.effective_settings_section.body.columnconfigure(0, weight=1)
    tab.effective_settings_label = ttk.Label(
        tab.effective_settings_section.body,
        textvariable=tab.effective_settings_var,
        style="Muted.TLabel",
        justify="left",
    )
    tab.effective_settings_label.grid(row=0, column=0, sticky="ew")
    bind_wraplength(tab.effective_settings_label)
    tab._add_labeled_entry(
        details,
        2,
        "Output Route",
        combo=True,
        variable=tab.output_route_var,
        values=_OUTPUT_ROUTES,
        help_key="output_route",
    )
    tab.workflow_help_panel = ActionExplainerPanel(
        details,
        content=build_video_workflow_guidance(),
        app_state=tab.app_state,
        wraplength=900,
    )
    tab.workflow_help_panel.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 6))
    tab.overview_panel = TabOverviewPanel(
        details,
        content=get_tab_overview_content("video_workflow"),
        app_state=tab.app_state,
    )
    tab.overview_panel.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 6))
