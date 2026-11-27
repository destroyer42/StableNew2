"""Present workflow video settings, source selection, previews, and queue admission controls."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from src.gui.help_text.stage_setting_help_v2 import VIDEO_WORKFLOW_SETTING_HELP
from src.gui.layout_v2 import configure_grid_columns
from src.gui.theme_v2 import style_text_widget
from src.gui.tooltip import attach_tooltip
from src.gui.view_contracts.motion_library_contract import MotionLibraryPorts
from src.gui.view_contracts.pipeline_layout_contract import build_form_column_specs
from src.gui.view_contracts.video_batch_contract import VideoBatchSession
from src.gui.view_contracts.video_experiment_contract import VideoExperimentSession
from src.gui.view_contracts.video_motion_alignment_contract import (
    BLOCKED_FIELD as ALIGN_BLOCKED_FIELD,
)
from src.gui.view_contracts.video_motion_alignment_contract import (
    PREPARED_FIELD as ALIGN_PREPARED_FIELD,
)
from src.gui.view_contracts.video_motion_alignment_contract import AlignInputs
from src.gui.view_contracts.video_motion_prep_contract import (
    BLOCKED_FIELD as PREP_BLOCKED_FIELD,
)
from src.gui.view_contracts.video_motion_prep_contract import (
    PREPARED_FIELD,
    MotionPreparationSession,
)
from src.gui.view_contracts.video_motion_readiness_contract import MotionReadinessSession
from src.gui.view_contracts.video_runtime_readiness_contract import RuntimeReadinessSession
from src.gui.view_contracts.video_sequence_contract import SequenceSession
from src.gui.view_contracts.video_workspace_contract import (
    format_workflow_capability_label,
    summarize_video_workflow_source,
)
from src.gui.view_contracts.workspace_density_contract import changed_value_count
from src.gui.views.motion_batch_dialog import MotionBatchDialog
from src.gui.views.motion_conversion_dialog import (
    ConditioningPreviewWindow,
    MotionConversionDialog,
)
from src.gui.views.video_eval_panel_v2 import VideoEvalPanel
from src.gui.views.video_workflow_alignment_host import AlignmentHost, AlignmentRow
from src.gui.views.video_workflow_batch_panel_v2 import WorkflowBatchPanel
from src.gui.views.video_workflow_controls_panel_v2 import WorkflowControlsPanel
from src.gui.views.video_workflow_driver_host_v2 import DriverClipHost, DriverInputs
from src.gui.views.video_workflow_evaluate_view_v2 import VideoWorkflowEvaluateView
from src.gui.views.video_workflow_experiment_panel_v2 import WorkflowExperimentPanel
from src.gui.views.video_workflow_harvest_host import HarvestHost
from src.gui.views.video_workflow_layout_v2 import (
    PANE_FORM,
    PANE_MEDIA,
    VIEW_CREATE,
    VIEW_EVALUATE,
    TwoPaneLayout,
    ViewSwitch,
    media_allowed,
)
from src.gui.views.video_workflow_media_pane_v2 import (
    VideoWorkflowMediaPane,
    readiness_chip_text,
    readiness_is_relevant,
)
from src.gui.views.video_workflow_motion_ai_host import MotionAiHost
from src.gui.views.video_workflow_motion_intent_v2 import MotionIntentPanel
from src.gui.views.video_workflow_motion_library_panel_v2 import WorkflowMotionLibraryPanel
from src.gui.views.video_workflow_motion_prep_panel_v2 import WorkflowMotionPreparationPanel
from src.gui.views.video_workflow_rate_review_v2 import (
    OPEN_OPERATOR_SITE_EVENT,
    RateReviewSection,
)
from src.gui.views.video_workflow_rerun_host import RerunHost
from src.gui.views.video_workflow_runtime_strip_v2 import WorkflowRuntimeReadinessStrip
from src.gui.views.video_workflow_sections_v2 import (
    build_details_section,
    build_keyframes_section,
    build_settings_section,
)
from src.gui.views.video_workflow_sequence_panel_v2 import WorkflowSequencePanel
from src.gui.views.video_workflow_task_panel_v2 import (
    PinTracker,
    SuggestedSettingsLine,
    WorkflowTaskSelector,
)
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui.widgets.submission_notice_v2 import SubmissionNotice
from src.pipeline.policy_warnings import PolicyWarning
from src.state.output_routing import (
    OUTPUT_ROUTE_REPROCESS,
)
from src.video.conditioning_inspection import build_inspection_context
from src.video.driver_intent import (
    DEFAULT_BETWEEN_PROMPT,
    DEFAULT_DRIVER_PROMPT,
    WHOLE_MOVEMENT_LABEL,
)
from src.video.motion_intent import (
    LONGEST_SUFFIX,
    MOTION_INTENT_FIELD,
    LengthPolicy,
    choice_for_frames,
    compose_prompt,
    duration_label,
    duration_options,
    frames_for_duration,
    length_policy,
    motion_intent_record,
    parse_seconds,
)
from src.video.motion_library.handoff import (
    FIELD_LIBRARY_BINDING,
    HandoffPlan,
    binding_for_submission,
)
from src.video.motion_library.harvest_service import HarvestSourceRef
from src.video.motion_presets import (
    CONTROL_FIELD_PREFIX,
    FIELD_MOTION_PHRASE,
    INTENT_FOLLOW_DRIVER,
    INTENT_PROMPT_ONLY,
    MOTION_PROMPT_CONTROL,
    NO_PRESET_ID,
    NO_PRESET_LABEL,
    intent_suggestions,
    preset_by_id,
    preset_by_label,
    preset_duration_seconds,
    preset_is_modified,
)
from src.video.motion_rerun import (
    DRIVER_REPREPARE,
    DRIVER_REUSE,
    RERUN_LINEAGE_FIELD,
    RerunOpening,
    rerun_edits,
    rerun_lineage,
)
from src.video.recent_video_outputs import RecentVideoOutput
from src.video.workflow_frame_count import frame_count_advisory
from src.video.workflow_picker import offered_workflow_ids, workflow_choices
from src.video.workflow_tasks import (
    FIELD_ENGINE,
    FIELD_LENGTH,
    FIELD_MOTION,
    FIELD_NEGATIVE,
    FIELD_SEED,
    FIELD_SMOOTH,
    NO_ENGINE_MESSAGE,
    TASK_ANIMATE,
    TASK_BATCH,
    TASK_BETWEEN,
    TASK_FOLLOW_CLIP,
    TASK_SEQUENCE,
    TASKS,
    choose_workflow,
    eligible_workflows,
    infer_task,
    reconcile,
    smoothing_warning,
    suggest_settings,
)
from src.video.workflow_warnings import (
    end_frame_crop_warning_for_paths,
    source_crop_warning_for_path,
)

_IMAGE_FILETYPES = [
    ("PNG files", "*.png"),
    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif"),
    ("All files", "*.*"),
]
_VIDEO_FILETYPES = [
    ("Video files", "*.mp4 *.webm *.mov *.mkv"),
    ("All files", "*.*"),
]
# PR-VID-UX-360: the fields the Settings editor holds, and how a suggestion's reason is titled.
_SETTINGS_FIELD_TITLES = {
    FIELD_LENGTH: "Length",
    FIELD_MOTION: "Motion",
    FIELD_SMOOTH: "Smoothing",
    FIELD_SEED: "Seed",
    FIELD_NEGATIVE: "Negative",
    FIELD_MOTION_PHRASE: "Motion phrase",
}
_SETTINGS_FIELDS = frozenset({FIELD_ENGINE, *_SETTINGS_FIELD_TITLES})
# V1-3: the declared controls a driving-video preset sets (pinned once the operator edits one).
_PRESET_CONTROLS = (MOTION_PROMPT_CONTROL, "pose_strength", "reference_image_strength")


def _control_text(value: Any) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value if value is not None else "")


def _settings_title(field: str) -> str:
    return (
        _SETTINGS_FIELD_TITLES.get(field)
        or field.removeprefix(CONTROL_FIELD_PREFIX).replace("_", " ").capitalize()
    )


def _frame_count_label(choice: dict[str, Any]) -> str:
    """Operator-facing label for one legal length, so nobody has to compute the duration."""

    return f"{int(choice['frames'])} frames (~{float(choice['seconds']):.1f} s)"


class VideoWorkflowTabFrameV2(ttk.Frame):
    """Dedicated queue-backed UI for workflow-driven video generation."""

    # Widgets built by ``video_workflow_sections_v2``; declared here so type checking sees them.
    negative_prompt_text: tk.Text
    advanced_section: DisclosureSection
    workflow_combo: ttk.Combobox
    workflow_controls_panel: WorkflowControlsPanel
    end_anchor_entry: ttk.Entry
    end_anchor_browse: ttk.Button
    mid_anchors_entry: ttk.Entry
    mid_anchors_browse: ttk.Button
    motion_label: ttk.Label
    motion_combo: ttk.Combobox
    seed_label: ttk.Label
    seed_entry: ttk.Entry
    conditioning_frame: ttk.Frame
    conditioning_section: DisclosureSection
    keyframes_section: DisclosureSection
    frame_count_combo: ttk.Combobox
    frame_count_frame: ttk.Frame
    effective_settings_section: DisclosureSection
    suggestion_reasons_var: tk.StringVar
    reasons_label: ttk.Label
    depth_path_entry: ttk.Entry
    depth_browse_button: ttk.Button
    motion_intent_panel: MotionIntentPanel
    follow_clip_frame: ttk.Frame
    end_image_frame: ttk.Frame
    pose_video_frame: ttk.Frame
    pose_video_entry: ttk.Entry

    def __init__(
        self,
        master: tk.Misc,
        *,
        app_controller: Any = None,
        app_state: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.app_controller = app_controller
        self.app_state = app_state
        self._workflow_map: dict[str, dict[str, Any]] = {}
        # Identity of the Motion Library clip last handed to the driving-video field
        # (PR-VID-MOTION-LIB-353); frozen with a job only while the field still names that file.
        self._library_binding: dict[str, Any] | None = None
        self._library_bound_path = ""
        self._last_folder = ""
        self._source_bundle: dict[str, Any] | None = None
        self._setting_tooltips: dict[str, Any] = {}
        self._pending_visibility_refresh = False
        # PR-VID-UX-360: what the operator is making (a GUI intent only, never submitted), the fields
        # they edited (suggestions leave those alone) and what the last suggestion pass had to say.
        self._task = TASK_ANIMATE
        self._pins = PinTracker()
        self._suggestion_notes: list[str] = []
        self._engine_by_task: dict[str, str] = {}
        self._rife_found = False
        # V1-1: the chosen motion preset (a suggestion source, like the engine's own), why each value was chosen
        # (provenance only, D5) and the seconds the operator last typed with the length they resolved to.
        self._preset_id = NO_PRESET_ID
        self._suggestion_basis: dict[str, str] = {}
        self._requested_seconds: tuple[float, int] | None = None
        # V1-3: the driver clip of "Follow a driving video" (built once the body exists).
        self._driver_host: DriverClipHost | None = None
        self._duration_shown = ""
        self._driver_typed = False
        # V1-2: the finished job a Re-run with tweaks opened (its lineage applies while the source is unchanged).
        self._rerun: RerunOpening | None = None
        # VID-UX-384: which half of the tab is showing (a GUI preference, saved with the form, never
        # submitted), the one Show media preference shared by every media render in the tab, and whether
        # the operator opened the motion-readiness details from the header chip.
        self._view = VIEW_CREATE
        self.show_media_var = tk.BooleanVar(master=self, value=True)
        # N13: unrated speed arms and superseded arms are offered only when this is on (saved with the form).
        self.show_experimental_var = tk.BooleanVar(master=self, value=False)
        self._readiness_opened = False

        defaults = self._load_defaults()
        camera_intent_defaults = dict(defaults.get("camera_intent") or {})
        controlnet_defaults = dict(defaults.get("controlnet") or {})
        depth_input_defaults = dict(defaults.get("depth_input") or {})
        # ``workflow_var`` holds the workflow ID (what is submitted and persisted); the picker shows the
        # friendly label held in ``workflow_label_var`` and the two are kept in step.
        self.workflow_var = tk.StringVar(value=str(defaults.get("workflow_id") or ""))
        self.workflow_label_var = tk.StringVar(value="")
        self._workflow_label_to_id: dict[str, str] = {}
        self._workflow_id_to_label: dict[str, str] = {}
        # Trusted parent ids from a Make Video handoff, valid only for the source path they were given for.
        self._source_lineage: dict[str, str] = {}
        self._source_lineage_path = ""
        self._recent_controller: Any = None
        self.source_image_var = tk.StringVar(value=str(defaults.get("source_image_path") or ""))
        self.end_anchor_var = tk.StringVar(value=str(defaults.get("end_anchor_path") or ""))
        self.mid_anchors_var = tk.StringVar(value="; ".join(defaults.get("mid_anchor_paths") or []))
        self.motion_profile_var = tk.StringVar(
            value=str(defaults.get("motion_profile") or "gentle")
        )
        self.seed_var = tk.StringVar(value=str(defaults.get("seed") or ""))
        # Label of the selected legal length; the map turns it back into a frame count.  Empty
        # when the selected workflow declares no frame-count policy.
        self.frame_count_var = tk.StringVar(value="")
        self._frame_count_labels: dict[str, int] = {}
        # Inline advisory for a length above the workflow's declared advisory_above (VID-A14B-SPEED-374).
        self.frame_count_advisory_var = tk.StringVar(value="")
        # Driving video for workflows that transfer a clip's motion (shown only for those).
        self.pose_video_var = tk.StringVar(value="")
        self.camera_preset_var = tk.StringVar(
            value=str(camera_intent_defaults.get("preset") or "none")
        )
        self.camera_strength_var = tk.StringVar(
            value=str(camera_intent_defaults.get("strength") or 0.35)
        )
        self.depth_mode_var = tk.StringVar(value=str(depth_input_defaults.get("mode") or "none"))
        self.depth_path_var = tk.StringVar(value=str(depth_input_defaults.get("path") or ""))
        self.controlnet_model_var = tk.StringVar(
            value=str(controlnet_defaults.get("model") or "depth")
        )
        self.controlnet_weight_var = tk.StringVar(
            value=str(controlnet_defaults.get("weight") or 1.0)
        )
        self.controlnet_guidance_start_var = tk.StringVar(
            value=str(controlnet_defaults.get("guidance_start") or 0.0)
        )
        self.controlnet_guidance_end_var = tk.StringVar(
            value=str(controlnet_defaults.get("guidance_end") or 1.0)
        )
        # Baseline for the collapsed Advanced Conditioning header: operator edits are compared to these.
        self._conditioning_defaults = {
            "camera_preset": self.camera_preset_var.get(),
            "camera_strength": self.camera_strength_var.get(),
            "depth_mode": self.depth_mode_var.get(),
            "depth_path": self.depth_path_var.get(),
            "controlnet_model": self.controlnet_model_var.get(),
            "controlnet_weight": self.controlnet_weight_var.get(),
            "controlnet_guidance_start": self.controlnet_guidance_start_var.get(),
            "controlnet_guidance_end": self.controlnet_guidance_end_var.get(),
        }
        self.output_route_var = tk.StringVar(
            value=str(defaults.get("output_route") or OUTPUT_ROUTE_REPROCESS)
        )
        self.status_var = tk.StringVar(value="Ready to queue a workflow-driven video job.")
        self.workflow_detail_var = tk.StringVar(value="No workflow selected.")
        # Optional RIFE smoothing of the finished clip (a saved preference, unlike the per-job opt-in).
        self.smooth_var = tk.BooleanVar(value=False)
        # Why Queue is disabled for the selected workflow, or (N1) the warning Queue will accept for it; empty
        # when there is neither. Batch mode also disables the single-image Queue, but says so through its own panel.
        self.queue_block_reason_var = tk.StringVar(value="")
        self._queue_blocked_by_batch = False
        self.source_summary_var = tk.StringVar(value="Source: none selected")
        self.effective_settings_var = tk.StringVar(value="Effective settings: defaults loaded")
        self._submitted_effective_settings: dict[str, Any] = {}
        self._defaults = dict(defaults)
        # Transient, unsaved "Compare one control" state; previewing/queueing is delegated to the
        # Video Workflow controller, which owns the NJR build and the single admission.
        self._experiment_session = VideoExperimentSession(
            resolve_baseline=lambda form,
            name: self._experiment_controller().resolve_experiment_baseline(form, name),
            build_preview=lambda **kw: self._experiment_controller().preview_experiment(**kw),
            submit_plan=lambda plan: self._experiment_controller().submit_experiment(plan),
        )
        # Transient multi-source batch state (PR-VID-BATCH-200); never saved with the form.
        self._batch_session = VideoBatchSession(
            build_preview=lambda **kw: self._experiment_controller().preview_batch(**kw),
            submit_plan=lambda plan: self._experiment_controller().submit_batch(plan),
            select_sources=lambda paths, lineage=None, review_origin=False: (
                self._experiment_controller().select_batch_sources(
                    paths, lineage, review_origin=review_origin
                )
            ),
            scan_folder=lambda folder, recursive=True: (
                self._experiment_controller().scan_batch_folder(folder, recursive=recursive)
            ),
        )

        # Read-only source/driving-video readiness (PR-VID-196): display state only, never saved
        # with the form and never part of what is submitted.
        self._motion_readiness_session = MotionReadinessSession(
            preview_source=lambda path, policy: self._experiment_controller().preview_motion_source(
                path, policy
            ),
            inspect_video=lambda path, cancel: self._experiment_controller().inspect_driving_video(
                path, cancel
            ),
        )
        # Optional "Prepare Motion Source" (PR-VID-MOTION-210): transient, never saved with the
        # form; the controller prepares, the job builder re-verifies what it produced.
        self._motion_prep_session = MotionPreparationSession(
            prepare=lambda form, request, cancel: (
                self._experiment_controller().prepare_motion_source(form, request, cancel)
            )
        )

        # Read-only runtime readiness gates (PR-VID-UX-311): transient display state; a blocked gate keeps
        # Queue disabled with its reason, an unknown one never does.
        self._runtime_readiness_session = RuntimeReadinessSession(
            evaluate=lambda workflow_id, version: (
                self._experiment_controller().workflow_preflight(workflow_id, version)
            )
        )

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=0)
        self.rowconfigure(2, weight=1)

        self._build_header()
        self._build_body()
        self._driver_host = DriverClipHost(
            self,
            read_inputs=self._read_driver_inputs,
            inspect=lambda path: self._experiment_controller().inspect_driving_video(path),
            prep_panel=self.motion_prep_panel,
            apply_frames=self._apply_driver_frames,
            on_change=self._refresh_driver_view,
        )
        self.workflow_controls_panel.on_edit = lambda name: self._pins.pin(
            CONTROL_FIELD_PREFIX + name
        )
        self.show_media_var.trace_add("write", lambda *_args: self._apply_show_media())
        self._apply_show_media()
        self.show_experimental_var.trace_add("write", lambda *_args: self._sync_engine_choices())
        self.bind("<Map>", self._on_map, add="+")
        self._refresh_workflow_choices()
        self._set_text_value(self.prompt_text, str(defaults.get("prompt") or ""))
        self._set_text_value(self.negative_prompt_text, str(defaults.get("negative_prompt") or ""))
        if self.app_state is not None and hasattr(self.app_state, "subscribe"):
            try:
                self.app_state.subscribe(
                    "content_visibility_mode",
                    self._on_content_visibility_mode_changed,
                )
            except Exception:
                pass
        self.workflow_label_var.trace_add("write", lambda *_args: self._on_workflow_label_changed())
        self.workflow_var.trace_add("write", lambda *_args: self._on_workflow_id_changed())
        for variable in (
            self.workflow_var,
            self.source_image_var,
            self.end_anchor_var,
            self.mid_anchors_var,
            self.motion_profile_var,
            self.seed_var,
            self.frame_count_var,
            self.pose_video_var,
            self.depth_mode_var,
            self.depth_path_var,
            self.camera_preset_var,
            self.camera_strength_var,
            self.controlnet_model_var,
            self.controlnet_weight_var,
            self.controlnet_guidance_start_var,
            self.controlnet_guidance_end_var,
            self.output_route_var,
        ):
            variable.trace_add("write", lambda *_args: self._refresh_workspace_summary())
        self.source_image_var.trace_add("write", lambda *_args: self._refresh_queue_gate())
        self.frame_count_var.trace_add("write", lambda *_args: self._refresh_frame_count_advisory())
        self.frame_count_var.trace_add("write", lambda *_args: self._sync_duration())
        self.motion_intent_panel.phrase_var.trace_add(
            "write", lambda *_args: self._refresh_suggested_line()
        )
        for sequence in ("<KeyRelease>", "<<Paste>>", "<<Cut>>"):
            self.prompt_text.bind(sequence, lambda _e: self._refresh_composed(), add="+")
        self.smooth_var.trace_add("write", lambda *_args: self._refresh_advanced_status())
        self.smooth_var.trace_add("write", lambda *_args: self._refresh_suggested_line())
        self.negative_prompt_text.bind(
            "<KeyRelease>", lambda _e: self._refresh_advanced_status(), add="+"
        )
        for prompt_widget in (self.prompt_text, self.negative_prompt_text):
            for sequence in ("<KeyRelease>", "<<Paste>>", "<<Cut>>"):
                prompt_widget.bind(
                    sequence, lambda _e: self._invalidate_experiment_preview(), add="+"
                )
        self.depth_mode_var.trace_add(
            "write", lambda *_args: self._refresh_conditioning_controls_state()
        )
        self._refresh_conditioning_controls_state()
        self._refresh_workspace_summary()
        self.on_content_visibility_mode_changed()
        # From here on a write to one of these is the operator's (or a restore's) own choice.
        watched: tuple[tuple[str, tk.Variable], ...] = (
            (FIELD_ENGINE, self.workflow_var),
            (FIELD_LENGTH, self.frame_count_var),
            (FIELD_MOTION, self.motion_profile_var),
            (FIELD_SMOOTH, self.smooth_var),
            (FIELD_SEED, self.seed_var),
            (FIELD_MOTION_PHRASE, self.motion_intent_panel.phrase_var),
        )
        for field, watched_variable in watched:
            self._pins.watch(field, watched_variable)
        for sequence in ("<KeyRelease>", "<<Paste>>", "<<Cut>>"):
            self.negative_prompt_text.bind(
                sequence, lambda _e: self._pins.pin(FIELD_NEGATIVE), add="+"
            )
        self._adopt_task(infer_task(self._workflow_map.get(self.workflow_var.get().strip())))
        self._apply_suggestions()

    def _load_defaults(self) -> dict[str, Any]:
        controller = getattr(self, "app_controller", None)
        builder = getattr(controller, "build_video_workflow_defaults", None)
        if callable(builder):
            try:
                return dict(builder() or {})
            except Exception:
                pass
        return {
            "workflow_id": "",
            "workflow_version": "",
            "source_image_path": "",
            "end_anchor_path": "",
            "mid_anchor_paths": [],
            "prompt": "",
            "negative_prompt": "",
            "motion_profile": "gentle",
            "seed": "",
            "camera_intent": {"preset": "none", "strength": 0.35},
            "controlnet": {
                "model": "depth",
                "weight": 1.0,
                "guidance_start": 0.0,
                "guidance_end": 1.0,
            },
            "depth_input": {"mode": "none", "path": ""},
            "output_route": OUTPUT_ROUTE_REPROCESS,
        }

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame", padding=8)
        header.grid(row=1, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Source Image", style="Dark.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Entry(header, textvariable=self.source_image_var, style="Dark.TEntry").grid(
            row=0, column=1, sticky="ew", padx=(0, 6)
        )
        ttk.Button(
            header, text="Browse...", style="Dark.TButton", command=self._on_browse_source
        ).grid(row=0, column=2, sticky="ew", padx=(0, 6))
        self.use_latest_output_button = ttk.Button(
            header,
            text="Use Latest Output",
            style="Dark.TButton",
            command=self._on_use_latest_output,
        )
        self.use_latest_output_button.grid(row=0, column=3, sticky="ew")
        self.use_latest_output_tooltip = attach_tooltip(
            self.use_latest_output_button,
            "Load the newest compatible image output into this workflow tab. This prepares the source input only; it does not queue the workflow yet.",
        )
        # PR-VID-UX-360: the first choice is what to make, not which workflow to run.  Choosing a task picks
        # its engine, fills the settings and shows only the inputs that task needs.
        self.task_selector = WorkflowTaskSelector(header, on_select=self._on_task_selected)
        self.task_selector.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        # VID-UX-384: Create | Evaluate shares the task row; the readiness chip sits at the action bar's right edge.
        view_controls = ttk.Frame(header, style="Panel.TFrame")
        view_controls.grid(row=1, column=3, sticky="e", pady=(6, 0))
        self.view_switch = ViewSwitch(view_controls, on_change=self.select_view)
        self.view_switch.grid(row=0, column=0, sticky="e")
        # Shown only while the panes are stacked (a narrow window): one pane at a time, each at full height.
        self.pane_switch = ViewSwitch(
            view_controls,
            on_change=self._on_pane_chosen,
            choices=((PANE_FORM, "Form"), (PANE_MEDIA, "Media")),
            initial=PANE_FORM,
        )
        # Keep the primary action and its status visible above the scrolling form.
        action_bar = ttk.Frame(header, style="Panel.TFrame")
        action_bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self._action_bar = action_bar
        self.queue_workflow_button = ttk.Button(
            action_bar,
            text="Queue Video Workflow",
            style="Primary.TButton",
            command=self._on_submit,
        )
        self.queue_workflow_button.pack(side="left")
        self.frozen_plan_button = ttk.Button(
            action_bar,
            text="Preview Frozen Plan",
            command=self._preview_frozen_plan,
            style="Dark.TButton",
        )
        self.queue_workflow_tooltip = attach_tooltip(
            self.queue_workflow_button,
            "Queue a workflow-driven video job using the selected workflow, anchors, prompts, and route shown in this tab.",
        )
        self.status_label = ttk.Label(
            action_bar, textvariable=self.status_var, style="Dark.TLabel", justify="left"
        )
        self.status_label.pack(side="left", fill="x", expand=True, padx=(12, 0))
        bind_wraplength(self.status_label)
        self.readiness_chip = ttk.Button(
            action_bar,
            text="Source: none selected",
            style="Dark.TButton",
            command=self._on_readiness_chip,
        )
        # Packed before the expanding status label so a narrow window shortens the status text, never the chip.
        self.readiness_chip.pack(side="right", padx=(8, 0), before=self.status_label)
        self.readiness_chip_tooltip = attach_tooltip(
            self.readiness_chip,
            "Source and motion readiness at a glance. Click to open the details beside the form.",
        )
        self.queue_block_label = ttk.Label(
            action_bar, textvariable=self.queue_block_reason_var, style="Muted.TLabel"
        )
        self.queue_block_tooltip = attach_tooltip(self.queue_block_label, "")
        self.visibility_banner = ttk.Label(header, text="", style="Dark.TLabel")
        # Inline, non-modal feedback for Queue: a failure stays visible until dismissed or the next attempt;
        # an accepted job is acknowledged with a "View in queue" action instead of a blocking dialog.
        self.submission_notice = SubmissionNotice(header)
        self.submission_notice.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        # PR-GUI-110: what the job will read stays in view; row 4 is the batch source strip.
        self.source_summary_label = ttk.Label(
            header, textvariable=self.source_summary_var, style="Muted.TLabel", justify="left"
        )
        self.source_summary_label.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        bind_wraplength(self.source_summary_label)
        self._header_frame = header

    def _build_body(self) -> None:
        # VID-UX-384: below the fixed header sit two views.  Create is a two-pane layout (the form on the
        # left, media and status on the right); Evaluate is the full-width eval kit.
        self._create_view = TwoPaneLayout(self, on_mode_change=self._sync_pane_switch)
        self._create_view.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.evaluate_view = VideoWorkflowEvaluateView(self)
        self.evaluate_view.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.evaluate_view.grid_remove()
        right = self._create_view.right
        # PR-GUI-100: the workflow body keeps growing with workflow controls; it scrolls instead of growing the window.
        self._body_scroll = ScrollableFrame(self._create_view.left, style="Panel.TFrame")
        self._body_scroll.grid(row=0, column=0, sticky="nsew")
        self._body_scroll.inner.columnconfigure(0, weight=1)
        # No padding under the lowest panel: scrolled to the end, the last section sits flush with the viewport.
        body = ttk.Frame(self._body_scroll.inner, style="Panel.TFrame", padding=(8, 8, 8, 0))
        body.grid(row=1, column=0, sticky="nsew")
        # Multi-source batch: a one-row source strip in the fixed header (shown for the batch task), its
        # Preview/Queue buttons in the header's action bar, and the (taller) source table at the top of the
        # scrolled body.
        self.batch_panel = WorkflowBatchPanel(
            self._header_frame,
            details_parent=self._body_scroll.inner,
            session=self._batch_session,
            read_form=self._read_batch_form,
            action_parent=self._action_bar,
            action_before=self.status_label,
            on_queued=self._on_batch_queued,
            on_mode_change=self._on_batch_mode_change,
            on_status=self.status_var.set,
        )
        self.batch_panel.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self.batch_panel.grid_remove()
        self.batch_panel.place_details(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        self._form_columns = build_form_column_specs(
            label_columns=(0,),
            primary_columns=(1,),
            secondary_columns=(2, 3),
            secondary_min_width=140,
            secondary_weight=1,
        )
        configure_grid_columns(body, self._form_columns)
        body.rowconfigure(0, weight=1)
        self._body_frame = body

        # Left pane, top to bottom: the prompt, the task's settings, the summary line, Advanced, the task's own
        # inputs, then named disclosures for everything else.
        self._build_task_inputs(body)
        self._build_settings_section(body)
        self.suggested_line = SuggestedSettingsLine(
            body,
            on_change=self._toggle_settings,
            on_reset=self._reset_to_suggested,
            title="",
            change_label="Change",
            hide_label="Hide advanced",
        )
        self.suggested_line.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self.advanced_section.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self._build_sequence_panel(body)
        # PR-VID-UX-311: runtime readiness stays outside the disclosures, because it is what keeps Queue disabled.
        self.runtime_readiness_strip = WorkflowRuntimeReadinessStrip(
            body,
            session=self._runtime_readiness_session,
            read_selection=self._read_runtime_readiness_selection,
            on_change=self._refresh_queue_gate,
            on_fix_setup=self._open_comfy_setup,
        )
        self.runtime_readiness_strip.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self.runtime_readiness_strip.grid_remove()
        self.bind("<Map>", self._on_tab_shown, add="+")
        self._build_keyframes_section(body)
        self._build_details_section(body)

        # Right pane: one Show media switch, the source preview, readiness details (only when relevant) and
        # the newest finished clips.
        self._build_media_pane(right)
        self._build_compare_section(self.evaluate_view)

    @property
    def _media_scroll(self) -> ScrollableFrame:
        return self._create_view.media_scroller

    def reveal_media_pane(self) -> None:
        """Make the media pane visible: always in two-pane mode, by switching panes when stacked."""

        self._create_view.show_pane(PANE_MEDIA)
        self._sync_pane_switch()

    def _on_pane_chosen(self, pane: str) -> None:
        self._create_view.show_pane(pane)

    def _sync_pane_switch(self) -> None:
        """The Form | Media toggle exists only while the panes are stacked in the Create view."""

        switch = getattr(self, "pane_switch", None)
        if switch is None:
            return
        pane_view = getattr(self, "_create_view", None)
        if pane_view is not None and pane_view.stacked and self._view == VIEW_CREATE:
            switch.set_view(pane_view.active_pane)
            switch.grid(row=0, column=1, sticky="e", padx=(8, 0))
        else:
            switch.grid_remove()

    def _build_media_pane(self, right: ttk.Frame) -> None:
        # The readiness panel and Recent outputs are built by the pane module; the tab keeps its attribute names.
        self._media_pane = VideoWorkflowMediaPane(
            right,
            show_media_var=self.show_media_var,
            readiness_kwargs={
                "session": self._motion_readiness_session,
                "read_inputs": self._read_motion_readiness_inputs,
                "media_allowed": self._readiness_media_allowed,
                "on_render": self._on_readiness_rendered,
            },
            recent_kwargs={
                "list_outputs": self._list_recent_outputs,
                "send_to_movie": self._send_output_to_movie,
                "add_to_library": self._add_output_to_library,
                "on_library_changed": self._refresh_motion_library,
                "harvest_motion": self._harvest_recent_output,
                "continue_in_storyboard": self._continue_output_in_storyboard,
                "rerun_with_tweaks": lambda output: self.open_rerun(output.job_id),
            },
        )
        self.show_media_check = self._media_pane.check
        self.source_preview = self._media_pane.source_preview
        self.motion_readiness_panel = self._media_pane.readiness_panel
        self.recent_outputs_panel = self._media_pane.recent_panel

    def _build_task_inputs(self, body: ttk.Frame) -> None:
        """Row 0: the prompt (every task); row 4: the driving-clip tools (their own task)."""

        prompt_label = ttk.Label(body, text="Prompt", style="Dark.TLabel")
        self.prompt_label = prompt_label  # relabelled from the workflow's operator projection
        prompt_label.grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=(8, 6))
        self.prompt_text = tk.Text(
            body,
            height=5,
            wrap="word",
        )
        style_text_widget(self.prompt_text, elevated=True)
        self.prompt_text.grid(row=0, column=1, columnspan=3, sticky="nsew", pady=(8, 6))
        self._attach_setting_help(
            "prompt",
            VIDEO_WORKFLOW_SETTING_HELP["prompt"],
            prompt_label,
            self.prompt_text,
        )

        # Row 4 stacks the driving clip and the clip tools; both belong to "Follow a driving clip".  The source
        # and motion readiness live in the right pane (VID-UX-384 supersedes the VID-UX-360 "every task" rule).
        inputs = ttk.Frame(body, style="Panel.TFrame")
        inputs.grid(row=4, column=0, columnspan=4, sticky="ew")
        inputs.columnconfigure(0, weight=1)
        # A permanent empty row keeps the stack shrinking when everything else in it is hidden.
        ttk.Frame(inputs, style="Panel.TFrame", height=0).grid(row=3, column=0, sticky="ew")
        tools = ttk.Frame(inputs, style="Panel.TFrame")
        tools.grid(row=2, column=0, sticky="ew")
        tools.columnconfigure(0, weight=1)
        tools.grid_remove()
        self.follow_clip_tools = tools
        # V1-3: preparation happens by itself; the window and alignment editors are folded away.
        self.driver_tools_section = DisclosureSection(tools, title="Adjust window and alignment")
        self.driver_tools_section.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        adjust = self.driver_tools_section.body
        adjust.columnconfigure(0, weight=1)
        # PR-VID-MOTION-210: exact preparation of the driving clip for this workflow.
        self.motion_prep_panel = WorkflowMotionPreparationPanel(
            adjust,
            session=self._motion_prep_session,
            read_form=self._read_motion_prep_form,
            on_change=self._on_motion_prep_changed,
        )
        self.motion_prep_panel.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.motion_prep_panel.grid_remove()
        # PR-VID-MOTION-420: optional explicit spatial alignment of the driving motion to this source image.
        self.alignment_host = AlignmentHost(
            self,
            controller=self._experiment_controller,
            read_inputs=self._read_alignment_inputs,
            media_allowed=self._alignment_media_allowed,
            on_change=self._invalidate_experiment_preview,
        )
        self.alignment_row = AlignmentRow(adjust, host=self.alignment_host)
        self.alignment_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        # PR-VID-MOTION-LIB-353: local motion-reference catalog; Use as Driving Video fills the
        # driving-video field above and nothing else.
        self._recent_controller = self._experiment_controller()
        self.motion_library_button = ttk.Button(
            tools,
            text="Show Motion Library",
            style="Dark.TButton",
            command=self._toggle_motion_library,
        )
        self.motion_library_button.grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.motion_library_panel = WorkflowMotionLibraryPanel(
            tools,
            ports=self._motion_library_ports(),
            mode_provider=lambda: str(
                getattr(self.app_state, "content_visibility_mode", "nsfw") or "nsfw"
            ),
            selected_workflow=self._selected_workflow_identity,
            on_handoff=self._apply_library_handoff,
            on_convert=self._open_motion_conversion,
            on_batch_convert=self._open_motion_batch,
            on_preview_conditioning=self._open_conditioning_preview,
            on_harvest=self.open_motion_harvest,
        )
        self.motion_library_panel.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.motion_library_panel.grid_remove()

    def _build_sequence_panel(self, body: ttk.Frame) -> None:
        """Row 5, built after the Settings block because the panel reads the form as it is created."""

        # PR-VID-SEQ-331A: an ordered list of shots becomes one multi-segment job ("Multi-shot sequence" only).
        self.sequence_panel = WorkflowSequencePanel(
            body,
            session=SequenceSession(get_controller=self._experiment_controller),
            read_form=lambda: (
                self.source_image_var.get().strip(),
                self.get_video_workflow_state(for_submission=True),
            ),
            frame_counts=lambda: dict(self._frame_count_labels),
            block_reason=self._queue_block_reason,
            on_queued=self._on_sequence_queued,
            restore_form=self._restore_form_for_storyboard,
        )
        self.sequence_panel.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self.sequence_panel.grid_remove()
        self.sequence_panel.refresh_lengths()

    def _build_settings_section(self, body: ttk.Frame) -> None:
        """Row 1: the task's settings (motion phrase, preset, duration); row 3: Advanced (engine and raw settings)."""

        build_settings_section(self, body)

    def _build_keyframes_section(self, body: ttk.Frame) -> None:
        """Row 7: anchors and camera/depth conditioning; hidden when the engine declares none of them."""

        build_keyframes_section(self, body)

    def _build_compare_section(self, view: VideoWorkflowEvaluateView) -> None:
        """The Evaluate view: the eval kit, then one-control comparisons (VID-UX-384)."""

        # Kept as an attribute for the VID-UX-360 contract; it is the Evaluate container now.
        self.compare_section = view
        self.experiment_panel = WorkflowExperimentPanel(
            view.experiment_host,
            session=self._experiment_session,
            read_form=lambda: (
                self.source_image_var.get().strip(),
                self.get_video_workflow_state(for_submission=True),
            ),
            on_queued=self._on_experiment_queued,
            on_review=self._on_open_experiment_review,
        )
        self.experiment_panel.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.experiment_panel.grid_remove()
        view.adopt_experiment_panel(self.experiment_panel)

        self.eval_panel = VideoEvalPanel(
            view.eval_host,
            get_controller=self._experiment_controller,
            output_dir=lambda: str(getattr(self.app_controller, "output_dir", "") or "output"),
            eval_plans_dir=self._configured_eval_plans_dir,
            show_prompts=lambda: (
                str(getattr(self.app_state, "content_visibility_mode", "nsfw") or "nsfw") != "sfw"
            ),
            on_queued=self._on_batch_queued_refresh_only,
            on_run_changed=lambda run: self.rate_review.set_run(run),
        )
        self.eval_panel.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.rate_review = RateReviewSection(
            view.rate_host,
            open_report=self.eval_panel.open_selected_report,
            open_motion_review=self.eval_panel.open_selected_motion_review,
            open_site=lambda: self.winfo_toplevel().event_generate(
                OPEN_OPERATOR_SITE_EVENT, when="tail"
            ),
        )
        self.rate_review.grid(row=0, column=0, sticky="ew")

    def _configured_eval_plans_dir(self) -> str:
        manager = getattr(self.app_controller, "_config_manager", None)
        getter = getattr(manager, "get_setting", None)
        value = getter("eval_plans_dir", "") if callable(getter) else ""
        return value if isinstance(value, str) else ""

    def _build_details_section(self, body: ttk.Frame) -> None:
        """Row 8: what the job will use, where its output goes, and the reference text for the tab."""

        build_details_section(self, body)

    def _add_labeled_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        *,
        variable: tk.Variable,
        combo: bool = False,
        values: tuple[str, ...] | list[str] = (),
        width: int = 40,
        helper: str = "",
        help_key: str | None = None,
    ) -> ttk.Combobox | ttk.Entry:
        label_widget = ttk.Label(parent, text=label, style="Dark.TLabel")
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        widget: ttk.Combobox | ttk.Entry
        if combo:
            widget = ttk.Combobox(
                parent,
                textvariable=variable,
                values=list(values),
                state="readonly",
                style="Dark.TCombobox",
                width=width,
            )
        else:
            widget = ttk.Entry(parent, textvariable=variable, style="Dark.TEntry", width=width)
        widget.grid(row=row, column=1, sticky="ew", pady=(0, 6))
        if help_key:
            self._attach_setting_help(
                help_key, VIDEO_WORKFLOW_SETTING_HELP[help_key], label_widget, widget
            )
        if helper:
            ttk.Label(parent, text=helper, style="Muted.TLabel").grid(
                row=row, column=3, sticky="w", padx=(8, 0), pady=(0, 6)
            )
        return widget

    def _attach_setting_help(self, key: str, text: str, *widgets: tk.Widget | None) -> None:
        live_widgets = [widget for widget in widgets if widget is not None]
        if not live_widgets:
            return
        primary = live_widgets[0]
        self._setting_tooltips[key] = attach_tooltip(primary, text)
        for widget in live_widgets[1:]:
            attach_tooltip(widget, text)

    def _refresh_workflow_choices(self) -> None:
        controller = getattr(self, "app_controller", None)
        loader = getattr(controller, "get_video_workflow_specs", None)
        specs = []
        if callable(loader):
            try:
                specs = list(loader() or [])
            except Exception:
                specs = []
        self._workflow_map = {
            str(item.get("workflow_id") or ""): dict(item)
            for item in specs
            if item.get("workflow_id")
        }
        choices = workflow_choices(specs)
        self._workflow_label_to_id = {choice.label: choice.workflow_id for choice in choices}
        self._workflow_id_to_label = {choice.workflow_id: choice.label for choice in choices}
        self.workflow_combo["values"] = list(self._workflow_label_to_id)
        if not self.workflow_var.get() and choices:
            with self._pins.applying():
                self.workflow_var.set(choices[0].workflow_id)
        self._sync_workflow_label()
        self._sync_engine_choices()
        self._refresh_workspace_summary()

    def _sync_workflow_label(self) -> None:
        """Show the friendly label of the selected workflow id (the id itself when it is unknown)."""

        workflow_id = self.workflow_var.get().strip()
        label = self._workflow_id_to_label.get(workflow_id) or workflow_id
        if label != self.workflow_label_var.get():
            self.workflow_label_var.set(label)

    def _on_workflow_label_changed(self) -> None:
        workflow_id = self._workflow_label_to_id.get(self.workflow_label_var.get())
        if workflow_id and workflow_id != self.workflow_var.get():
            self.workflow_var.set(workflow_id)

    def _on_workflow_id_changed(self) -> None:
        self._sync_workflow_label()
        self._sync_engine_choices()  # a hidden engine left behind drops out of the picker
        self._invalidate_experiment_preview()
        self._refresh_queue_gate()

    def _on_workflow_selected(self, _event: tk.Event) -> None:
        self._invalidate_experiment_preview()
        self._refresh_queue_gate()

    def _experimental_warning_text(self) -> tuple[str, str]:
        """N1: the selected experimental workflow's warning beside Queue (short line, full text for the tooltip).

        Queue on this header records the job's opt-in; the full why-and-fix text is the same data the phone shows."""

        meta = self._workflow_map.get(self.workflow_var.get(), {})
        # VID-FRAME: a source this workflow would crop is warned about, approved or not.
        crop = source_crop_warning_for_path(
            (meta.get("motion_readiness") or {}).get("source_preparation"),
            f"{meta.get('workflow_id')}@{meta.get('workflow_version')}",
            self.source_image_var.get().strip(),
        )
        if self._task == TASK_BETWEEN:
            end_crop = end_frame_crop_warning_for_paths(
                (meta.get("motion_readiness") or {}).get("source_preparation"),
                f"{meta.get('workflow_id')}@{meta.get('workflow_version')}",
                self.source_image_var.get().strip(),
                self.end_anchor_var.get().strip(),
            )
            if end_crop is not None:
                crop = (
                    end_crop
                    if crop is None
                    else replace(
                        crop,
                        title=f"{crop.title} {end_crop.title}",
                        why=f"{crop.why} {end_crop.why}",
                    )
                )
        if not meta.get("experimental"):
            if crop is None:
                return "", ""
            return f"Warning: {crop.title} Queue runs it anyway (hover for why).", crop.text()
        warnings = [PolicyWarning.from_dict(item) for item in meta.get("policy_warnings") or ()]
        title = " ".join(warning.title for warning in warnings) or (
            f"{meta.get('display_name') or 'This workflow'} is experimental."
        )
        full = " ".join(warning.text() for warning in warnings) or title
        if crop is not None:
            title, full = f"{title} {crop.title}", f"{full} {crop.text()}"
        return (
            f"Warning: {title} Queue runs it anyway and records your opt-in (hover for why).",
            full,
        )

    def apply_make_video_defaults(self) -> str:
        """Preselect the recommended approved workflow for a Make Video handoff.

        An approved workflow the user already chose is kept; an experimental or missing selection is
        replaced by the recommended one. Nothing is queued, and the per-job experimental opt-in is never
        carried over (a changed selection resets it). Returns the selected workflow id."""

        controller = self._experiment_controller()
        getter = getattr(controller, "recommended_workflow_id", None)
        recommended = str(getter() or "") if callable(getter) else ""
        current = self._workflow_map.get(self.workflow_var.get().strip(), {})
        keeps_choice = current.get("governance_state") == "approved" and not current.get(
            "experimental"
        )
        if self._task in (TASK_FOLLOW_CLIP, TASK_SEQUENCE, TASK_BETWEEN):
            self.select_task(TASK_ANIMATE)  # one image handed over: the plain image-to-video task
            current = self._workflow_map.get(self.workflow_var.get().strip(), {})
            keeps_choice = current.get("governance_state") == "approved" and not current.get(
                "experimental"
            )
        if recommended and recommended in self._workflow_map and not keeps_choice:
            with self._pins.applying():
                self.workflow_var.set(recommended)
        elif current.get("experimental"):
            self._invalidate_experiment_preview()
            self._refresh_queue_gate()
        self.submission_notice.clear()
        return self.workflow_var.get().strip()

    def _leave_batch_mode(self) -> bool:
        """A single-image choice makes single-image mode authoritative again.

        Returns False (and says why) while a batch step is still running: the batch is then left
        untouched and the single-image choice is not applied, so the form never claims one mode
        while the other is in force."""

        session = getattr(self, "_batch_session", None)
        panel = getattr(self, "batch_panel", None)
        if session is None or not session.active:
            return True
        if session.busy:
            self.status_var.set(
                "A batch step is still running; wait for it to finish before choosing a single image."
            )
            return False
        session.clear()
        if panel is not None:
            panel.refresh()
        return True

    def _leave_batch_task(self) -> None:
        """A single image was chosen: the batch task gives way to the plain image-to-video task."""

        if self._task == TASK_BATCH:
            self.select_task(TASK_ANIMATE)

    def set_source_image_path(
        self,
        image_path: str,
        *,
        status_message: str | None = None,
        lineage: dict[str, str] | None = None,
    ) -> None:
        if not self._leave_batch_mode():
            return
        self._leave_batch_task()
        self.source_image_var.set(str(image_path))
        self._source_bundle = None
        # Trusted parent ids from the entry point (History job, Review metadata); valid only for this exact path.
        self._source_lineage = {key: str(value) for key, value in (lineage or {}).items() if value}
        self._source_lineage_path = str(image_path) if self._source_lineage else ""
        self.submission_notice.clear()
        if status_message:
            self.status_var.set(status_message)
        self._refresh_workspace_summary()

    def set_source_bundle(
        self,
        bundle: dict[str, Any],
        *,
        status_message: str | None = None,
    ) -> None:
        """Accept a generic video-artifact handoff bundle (PR-VIDEO-215).

        Extracts the best source image for this workflow tab:
        thumbnail_path > source_image_path > first frame path.
        """
        from src.video.video_artifact_helpers import extract_source_image_for_handoff

        best_path = extract_source_image_for_handoff(bundle) if isinstance(bundle, dict) else None
        if best_path:
            if not self._leave_batch_mode():
                return
            self._leave_batch_task()
            self._source_bundle = dict(bundle)
            self.source_image_var.set(str(best_path))
            self.status_var.set(
                status_message
                or f"Loaded from video output: {best_path.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}"
            )
            self._refresh_workspace_summary()

    def get_video_workflow_state(self, *, for_submission: bool = False) -> dict[str, Any]:
        workflow_meta = self._workflow_map.get(self.workflow_var.get(), {})
        visible = dict(workflow_meta.get("form_visibility") or {})
        supported = (lambda key: bool(visible.get(key, True))) if visible else (lambda key: True)
        state: dict[str, Any] = {
            "workflow_id": self.workflow_var.get().strip(),
            "workflow_version": str(workflow_meta.get("workflow_version") or "").strip(),
            "source_image_path": self.source_image_var.get().strip(),
            # Inputs the selected workflow does not accept are never submitted.
            "end_anchor_path": self.end_anchor_var.get().strip() if supported("end_anchor") else "",
            "mid_anchor_paths": [
                item.strip() for item in self.mid_anchors_var.get().split(";") if item.strip()
            ]
            if supported("mid_anchors")
            else [],
            "prompt": self.prompt_text.get("1.0", "end").strip(),
            "negative_prompt": self.negative_prompt_text.get("1.0", "end").strip(),
            "camera_intent": {
                "preset": self.camera_preset_var.get().strip()
                if supported("camera_intent")
                else "none",
                "strength": self.camera_strength_var.get().strip(),
            },
            "controlnet": {
                "model": self.controlnet_model_var.get().strip(),
                "weight": self.controlnet_weight_var.get().strip(),
                "guidance_start": self.controlnet_guidance_start_var.get().strip(),
                "guidance_end": self.controlnet_guidance_end_var.get().strip(),
            },
            "depth_input": {
                "mode": self.depth_mode_var.get().strip()
                if supported("depth_conditioning")
                else "none",
                "path": self.depth_path_var.get().strip()
                if supported("depth_conditioning")
                else "",
            },
            "output_route": self.output_route_var.get().strip(),
        }
        if supported("motion_profile"):
            state["motion_profile"] = self.motion_profile_var.get().strip()
        if supported("seed"):
            state["seed"] = self.seed_var.get().strip()
        if self._frame_count_labels:
            state["frame_count"] = self._frame_count_labels.get(self.frame_count_var.get())
        if self.smooth_var.get():
            state["interpolation"] = {"enabled": True}
        if bool(visible.get("pose_video", False)):
            state["pose_video_path"] = self.pose_video_var.get().strip()
            if for_submission:
                # The prepared record, or a blocker while a preparation is running/failed/stale.
                state.update(self.motion_prep_panel.submission_fields())
                self.alignment_host.refresh()
                aligned = self.alignment_host.submission_fields()
                if (
                    aligned
                ):  # an applied alignment supersedes the unaligned preparation, never mixes with it
                    state.pop(ALIGN_PREPARED_FIELD, None)
                    state.pop(ALIGN_BLOCKED_FIELD, None)
                    state.update(aligned)
                binding = binding_for_submission(
                    self._library_binding,
                    current_path=str(state["pose_video_path"]),
                    bound_path=self._library_bound_path,
                )
                if binding is not None:
                    state[FIELD_LIBRARY_BINDING] = binding
        if self.workflow_controls_panel.control_names:
            state["operator_controls"] = self.workflow_controls_panel.get_values()
        if for_submission and self._task == TASK_FOLLOW_CLIP:
            waiting = self._driver_block_reason()
            if waiting:  # never queue the unprepared clip while the panel is still preparing it
                state[PREP_BLOCKED_FIELD] = waiting
            state[MOTION_INTENT_FIELD] = self._motion_intent_record("")
            if not state["prompt"]:
                state["prompt"] = DEFAULT_DRIVER_PROMPT  # shown under the prompt before Queue
                state[MOTION_INTENT_FIELD]["basis"]["prompt"] = (
                    "The prompt box was empty: the default was sent."
                )
        if for_submission and self._task == TASK_BETWEEN:
            state[MOTION_INTENT_FIELD] = self._motion_intent_record("")
            if not state["prompt"]:
                state["prompt"] = DEFAULT_BETWEEN_PROMPT  # shown under the prompt before Queue
                state[MOTION_INTENT_FIELD]["basis"]["prompt"] = (
                    "The prompt box was empty: the default was sent."
                )
        phrase = self.motion_intent_panel.phrase_var.get().strip()
        if for_submission and self._task == TASK_ANIMATE:
            # V1-1 (D3, D5): the visible motion phrase is part of the submitted prompt; the preset and the basis of
            # each choice travel as provenance only.
            state["prompt"] = compose_prompt(state["prompt"], phrase)
            state[MOTION_INTENT_FIELD] = self._motion_intent_record(phrase)
        elif not for_submission:
            state["motion_phrase"] = phrase
            state["motion_preset"] = self._preset_id
        if for_submission:
            state.update(self._rerun_submission_fields(state))
            # N1: Queue on a header that shows the experimental warning is the job's opt-in; it is only ever part of
            # a submission, never saved state.
            state["experimental_opt_in"] = bool(workflow_meta.get("experimental"))
        else:
            # PR-VID-UX-360: a GUI intent, saved with the form and never part of a job.
            state["task"] = self._task
            # VID-UX-384: layout preferences, saved with the form and never part of a job.
            state["view"] = self._view
            state["show_media"] = bool(self.show_media_var.get())
            state["show_experimental"] = bool(self.show_experimental_var.get())  # N13
        return state

    def restore_video_workflow_state(self, state: dict[str, Any] | None) -> None:
        if not isinstance(state, dict):
            return
        self._refresh_workflow_choices()
        if self._driver_host is not None:
            self._driver_host.release()  # a restored form is shown as saved, never re-prepared by itself
        self.select_view(VIEW_EVALUATE if state.get("view") == VIEW_EVALUATE else VIEW_CREATE)
        if "show_media" in state:
            self.show_media_var.set(bool(state.get("show_media")))
        preset = preset_by_id(state.get("motion_preset"))
        self._preset_id = NO_PRESET_ID if preset is None else preset.preset_id
        if "show_experimental" in state:
            self.show_experimental_var.set(bool(state.get("show_experimental")))
        self._restore_task_and_engine(state)
        self._invalidate_experiment_preview()
        self._refresh_queue_gate()
        self.source_image_var.set(str(state.get("source_image_path") or ""))
        self.end_anchor_var.set(str(state.get("end_anchor_path") or ""))
        mid_anchors = state.get("mid_anchor_paths") or []
        if isinstance(mid_anchors, str):
            text = mid_anchors
        else:
            text = "; ".join(str(item) for item in mid_anchors if item)
        self.mid_anchors_var.set(text)
        self.motion_profile_var.set(
            str(state.get("motion_profile") or self.motion_profile_var.get())
        )
        self.seed_var.set(str(state.get("seed") or ""))
        camera_intent = dict(state.get("camera_intent") or {})
        controlnet = dict(state.get("controlnet") or {})
        depth_input = dict(state.get("depth_input") or {})
        self.camera_preset_var.set(str(camera_intent.get("preset") or "none"))
        self.camera_strength_var.set(str(camera_intent.get("strength") or 0.35))
        self.controlnet_model_var.set(str(controlnet.get("model") or "depth"))
        self.controlnet_weight_var.set(str(controlnet.get("weight") or 1.0))
        self.controlnet_guidance_start_var.set(str(controlnet.get("guidance_start") or 0.0))
        self.controlnet_guidance_end_var.set(str(controlnet.get("guidance_end") or 1.0))
        self.depth_mode_var.set(str(depth_input.get("mode") or "none"))
        self.depth_path_var.set(str(depth_input.get("path") or ""))
        self.output_route_var.set(str(state.get("output_route") or self.output_route_var.get()))
        self._set_text_value(self.prompt_text, str(state.get("prompt") or ""))
        self._set_text_value(self.negative_prompt_text, str(state.get("negative_prompt") or ""))
        self._source_bundle = None
        self._refresh_workspace_summary()
        self._select_frame_count(state.get("frame_count"))
        interpolation = state.get("interpolation")
        self.smooth_var.set(isinstance(interpolation, dict) and bool(interpolation.get("enabled")))
        if self.pose_video_frame.winfo_manager():
            self.pose_video_var.set(str(state.get("pose_video_path") or ""))
        controls = state.get("operator_controls")
        self.workflow_controls_panel.set_values(controls)
        if isinstance(controls, Mapping):
            self._pins.pin_all(CONTROL_FIELD_PREFIX + str(name) for name in controls)
        self.motion_intent_panel.phrase_var.set(str(state.get("motion_phrase") or ""))
        # Restored values are the operator's own: suggestions never replace them (PR-VID-UX-360).
        self._pins.pin_all(_SETTINGS_FIELDS)
        self._apply_suggestions()
        self._refresh_advanced_status()

    def _restore_form_for_storyboard(self, state: dict[str, Any]) -> None:
        """A Storyboard restores the form from any task (Job History opens one), so its task comes too."""

        self.restore_video_workflow_state({**state, "task": TASK_SEQUENCE})

    def _restore_task_and_engine(self, state: Mapping[str, Any]) -> None:
        """Select the saved engine and its task.  A snapshot without a task keeps the current task when
        the engine can serve it.  A workflow that is no longer installed is shown as saved under the
        plain image-to-video task: it is never swapped for another engine behind the operator's back."""

        saved_id = str(state.get("workflow_id") or "").strip()
        record = self._workflow_map.get(saved_id)
        if not saved_id:
            return
        if record is None:
            if self._task != TASK_BATCH or self._leave_batch_mode():
                self._adopt_task(TASK_ANIMATE)
            self.workflow_var.set(saved_id)
            return
        task = infer_task(record, state.get("task") or self._task)
        self.select_task(task, pinned_workflow_id=str(record["workflow_id"]))

    def _apply_workflow_capabilities(self, workflow_meta: dict[str, Any]) -> None:
        """Show and enable the inputs declared by the selected workflow."""

        visible = dict(workflow_meta.get("form_visibility") or {})

        def enabled(key: str) -> bool:
            return bool(visible.get(key, True)) if visible else True

        def set_state(widget: Any, on: bool) -> None:
            try:
                widget.configure(state="normal" if on else "disabled")
            except Exception:
                pass

        for widget in (self.end_anchor_entry, self.end_anchor_browse):
            set_state(widget, enabled("end_anchor"))
        for widget in (self.mid_anchors_entry, self.mid_anchors_browse):
            set_state(widget, enabled("mid_anchors"))
        # A Motion selector the workflow does not honor is hidden, not shown disabled: nothing on
        # this form may imply a setting affects generation when it does not (PR-VID-192).
        if enabled("motion_profile"):
            self.motion_label.grid()
            self.motion_combo.grid()
            set_state(self.motion_combo, True)
        else:
            self.motion_label.grid_remove()
            self.motion_combo.grid_remove()
        projection = dict(workflow_meta.get("operator_projection") or {})
        self.prompt_label.configure(text=str(projection.get("prompt_label") or "Prompt"))
        self.workflow_controls_panel.apply(workflow_meta.get("operator_controls"))
        # Comparison is offered only for controls the selected workflow declares.
        self.experiment_panel.apply_controls(
            workflow_meta.get("operator_controls")
            if self._experiment_controller() is not None
            else None
        )
        self.evaluate_view.sync()
        if enabled("seed"):
            self.seed_label.grid()
            self.seed_entry.grid()
            set_state(self.seed_entry, True)
        else:
            self.seed_label.grid_remove()
            self.seed_entry.grid_remove()
            self.seed_var.set("")
        self._apply_frame_count_choices(workflow_meta, enabled("frame_count"))
        plan_button = getattr(self, "frozen_plan_button", None)
        if plan_button is not None:
            if visible.get("frozen_preview"):
                plan_button.pack(side="left", padx=(8, 0), before=self.status_label)
            else:
                plan_button.pack_forget()
        if bool(visible.get("pose_video", False)):
            self.pose_video_frame.grid()
        else:
            self.pose_video_frame.grid_remove()
            self.pose_video_var.set("")
        conditioning_on = enabled("camera_intent") or enabled("depth_conditioning")
        for child in self.conditioning_frame.winfo_children():
            set_state(child, conditioning_on)
        if conditioning_on:
            self.conditioning_section.grid()
            self._refresh_conditioning_controls_state()
        else:
            # Camera, depth and ControlNet fields a workflow does not declare are not shown at all.
            self.conditioning_section.grid_remove()
        if self._task != TASK_BETWEEN and (
            conditioning_on or enabled("end_anchor") or enabled("mid_anchors")
        ):
            self.keyframes_section.grid()
        else:
            self.keyframes_section.grid_remove()  # nothing in it applies to this engine
        required_control = any(
            control.get("kind") == "text" and control.get("required")
            for control in workflow_meta.get("operator_controls") or ()
        )
        # Required inputs, and the picker where an experimental engine is authorised, must not hide behind a header.
        # V1-3: following a driver, Queue on the visible warning is the opt-in; the picker stays under Advanced.
        if required_control or (
            workflow_meta.get("experimental") and self._task not in (TASK_FOLLOW_CLIP, TASK_BETWEEN)
        ):
            self.advanced_section.set_expanded(True)
            self._sync_settings_editor_label()
        self._refresh_queue_gate()

    def _queue_block_reason(self) -> str:
        """Why the selected workflow cannot be queued yet, or an empty string."""

        workflow_meta = self._workflow_map.get(self.workflow_var.get(), {})
        policy_reason = (workflow_meta.get("operator_projection") or {}).get(
            "admission_block_reason"
        )
        if policy_reason:
            return str(policy_reason)
        driver_reason = self._driver_block_reason()
        if driver_reason:
            return driver_reason
        runtime_reason = self._runtime_readiness_session.block_reason()
        if runtime_reason:
            # The full reason, and what to do about it, is in the Runtime readiness strip below.
            return (
                runtime_reason
                if len(runtime_reason) <= 120
                else runtime_reason[:117].rstrip() + "... (see Runtime readiness)"
            )
        return ""

    def _refresh_queue_gate(self) -> None:
        if not hasattr(self, "queue_block_label"):
            return  # the header is still being built
        reason = self._queue_block_reason()
        blocked = bool(reason) or self._queue_blocked_by_batch
        warning, warning_detail = ("", "") if reason else self._experimental_warning_text()
        self.queue_block_reason_var.set(reason or warning)
        self.queue_block_tooltip.text = warning_detail or reason
        self.queue_workflow_button.configure(state="disabled" if blocked else "normal")
        self.queue_block_label.pack_forget()
        if self.queue_block_reason_var.get():
            self.queue_block_label.pack(side="left", padx=(12, 0), before=self.status_label)

    def _apply_frame_count_choices(self, workflow_meta: dict[str, Any], enabled: bool) -> None:
        """Offer exactly the legal lengths the selected workflow declares (default selected)."""

        projection = workflow_meta.get("frame_count")
        choices = projection.get("choices") if isinstance(projection, dict) else None
        if not enabled or not choices:
            self._frame_count_labels = {}
            self.frame_count_combo["values"] = []
            self.frame_count_var.set("")
            self.frame_count_frame.grid_remove()
            self.motion_intent_panel.show_duration(False)
            self._refresh_sequence_lengths()
            return
        self._frame_count_labels = {
            _frame_count_label(choice): int(choice["frames"]) for choice in choices
        }
        self.frame_count_combo["values"] = list(self._frame_count_labels)
        self._sync_length_row()
        self.motion_intent_panel.show_duration(True)
        self._select_frame_count(projection.get("default"))
        self._sync_duration()
        self._refresh_sequence_lengths()

    def _refresh_sequence_lengths(self) -> None:
        panel = getattr(self, "sequence_panel", None)
        if panel is not None:
            panel.refresh_lengths()

    def _refresh_frame_count_advisory(self) -> None:
        """Show the selected workflow's advisory when the chosen length is above its advisory threshold."""

        workflow_meta = self._workflow_map.get(self.workflow_var.get().strip(), {})
        selected = self._frame_count_labels.get(self.frame_count_var.get())
        self.frame_count_advisory_var.set(
            frame_count_advisory(workflow_meta.get("frame_count"), selected)
        )

    def _select_frame_count(self, frame_count: Any) -> None:
        for label, count in self._frame_count_labels.items():
            if str(count) == str(frame_count or "").strip():
                self.frame_count_var.set(label)
                return

    def _refresh_workspace_summary(self) -> None:
        workflow_meta = self._workflow_map.get(self.workflow_var.get(), {})
        identity = self._selected_workflow_identity()
        if identity != getattr(self, "_capability_workflow_identity", None):
            self._capability_workflow_identity = identity
            self._follow_engine(workflow_meta)
            kept_length = self._frame_count_labels.get(self.frame_count_var.get())
            with self._pins.applying():  # the form adapting itself is not an operator edit
                self._apply_workflow_capabilities(workflow_meta)
            self._apply_suggestions(kept_length)
            strip = getattr(self, "runtime_readiness_strip", None)
            if strip is not None and self.winfo_ismapped():
                strip.request_refresh()  # a hidden tab probes nothing; showing it does (_on_tab_shown)
        self._sync_source_preview()
        detail = format_workflow_capability_label(workflow_meta)
        if workflow_meta.get("experimental"):
            detail += " Choosing this workflow and selecting Queue authorizes experimental execution for the job."
        self.workflow_detail_var.set(detail)
        summary = summarize_video_workflow_source(
            source_image_path=self.source_image_var.get().strip(),
            workflow_spec=workflow_meta,
            end_anchor_path=self.end_anchor_var.get().strip(),
            mid_anchor_paths=self.mid_anchors_var.get(),
            bundle=self._source_bundle,
        )
        detail = summary.detail.strip()
        headline = summary.headline
        batch_session = getattr(self, "_batch_session", None)
        if batch_session is not None and batch_session.active:
            headline = f"Source: batch of {batch_session.count} image(s)"
        if detail:
            self.source_summary_var.set(f"{headline} | {detail}")
        else:
            self.source_summary_var.set(headline or summary.empty_state)
        workflow_value = self.workflow_var.get().strip() or "none"
        workflow_source = (
            "default"
            if workflow_value == str(self._defaults.get("workflow_id") or "").strip()
            else "selected here"
        )
        output_value = self.output_route_var.get().strip() or OUTPUT_ROUTE_REPROCESS
        output_source = (
            "default"
            if output_value
            == str(self._defaults.get("output_route") or OUTPUT_ROUTE_REPROCESS).strip()
            else "selected here"
        )
        anchor_state = (
            "explicit anchors"
            if (self.end_anchor_var.get().strip() or self.mid_anchors_var.get().strip())
            else "source-only"
        )
        depth_mode = self.depth_mode_var.get().strip() or "none"
        depth_path = (
            Path(self.depth_path_var.get().strip()).name
            if self.depth_path_var.get().strip()
            else ""
        )
        if depth_mode == "upload" and depth_path:
            conditioning_depth = f"depth=upload[{depth_path}]"
        elif depth_mode == "auto":
            conditioning_depth = "depth=auto"
        else:
            conditioning_depth = "depth=off"
        camera_preset = self.camera_preset_var.get().strip() or "none"
        camera_strength = self.camera_strength_var.get().strip() or "0.35"
        camera_summary = (
            "camera=off" if camera_preset == "none" else f"camera={camera_preset}@{camera_strength}"
        )
        control_model = self.controlnet_model_var.get().strip() or "depth"
        control_weight = self.controlnet_weight_var.get().strip() or "1.0"
        guide_start = self.controlnet_guidance_start_var.get().strip() or "0.0"
        guide_end = self.controlnet_guidance_end_var.get().strip() or "1.0"
        control_summary = (
            "controlnet=off"
            if depth_mode == "none"
            else f"controlnet={control_model}@{control_weight}[{guide_start}-{guide_end}]"
        )
        effective_parts = [
            f"workflow={workflow_value} [{workflow_source}]",
            f"output={output_value} [{output_source}]",
            f"anchor plan={anchor_state}",
        ]
        visible = dict(workflow_meta.get("form_visibility") or {})
        if not visible or visible.get("motion_profile", False):
            motion_value = self.motion_profile_var.get().strip() or "gentle"
            motion_source = (
                "default"
                if motion_value == str(self._defaults.get("motion_profile") or "gentle").strip()
                else "selected here"
            )
            effective_parts.append(f"motion={motion_value} [{motion_source}]")
        if not visible or visible.get("seed", False):
            seed_value = self.seed_var.get().strip() or "Random (frozen at admission)"
            effective_parts.append(f"seed={seed_value}")
        if self._frame_count_labels and self.frame_count_var.get():
            policy, frames = self._length_policy(), self._current_frames()
            shown = self.frame_count_var.get()
            if self._task == TASK_FOLLOW_CLIP and policy is not None and frames is not None:
                shown = duration_label(frames, policy)  # V1-3: this task never shows frame counts
            effective_parts.append(f"length={shown}")
        effective_parts.extend(self.workflow_controls_panel.summary_parts())
        if (
            not visible
            or visible.get("camera_intent", False)
            or visible.get("depth_conditioning", False)
        ):
            effective_parts.extend((conditioning_depth, camera_summary, control_summary))
        fixed_settings = dict(workflow_meta.get("operator_projection") or {}).get("fixed_settings")
        if isinstance(fixed_settings, dict):
            fixed_text = ", ".join(
                f"{key}={value}" for key, value in fixed_settings.items() if value not in (None, "")
            )
            if fixed_text:
                effective_parts.append(f"fixed: {fixed_text}")
        submitted_seed = self._submitted_effective_settings.get("seed")
        submitted_source = self._submitted_effective_settings.get("source_preparation")
        if submitted_seed is not None:
            effective_parts.append(f"submitted seed={submitted_seed}")
        if isinstance(submitted_source, dict):
            target = dict(submitted_source.get("target_dimensions") or {})
            if target.get("width") and target.get("height"):
                effective_parts.append(f"submitted target={target['width']}x{target['height']}")
        self.effective_settings_var.set("Effective settings: " + " | ".join(effective_parts))
        self.effective_settings_section.set_status(" | ".join(effective_parts[:2])[:72])
        self._refresh_conditioning_status(workflow_meta)
        self._invalidate_experiment_preview()
        readiness_panel = getattr(self, "motion_readiness_panel", None)
        if readiness_panel is not None:
            readiness_panel.request_refresh()  # debounced; the session de-duplicates unchanged inputs
        prep_panel = getattr(self, "motion_prep_panel", None)
        if prep_panel is not None:
            prep_panel.refresh()
        alignment_row = getattr(self, "alignment_row", None)
        if alignment_row is not None:
            alignment_row.refresh()
        self._refresh_advanced_status()
        self._refresh_suggested_line()
        host = getattr(self, "_driver_host", None)
        if host is not None:
            host.replan()  # cheap unless the driver, source or engine changed

    def _refresh_advanced_status(self) -> None:
        """Collapsed-header hints: say so when a closed section holds something the operator set."""

        section = getattr(self, "advanced_section", None)
        if section is None or not hasattr(self, "details_section"):
            return
        modified = bool(self._pins.pinned & _SETTINGS_FIELDS)
        section.set_status("modified" if modified else "", active=modified)
        keyframes: list[str] = []
        if self.end_anchor_var.get().strip():
            keyframes.append("end anchor")
        if self.mid_anchors_var.get().strip():
            keyframes.append("mid anchors")
        self.keyframes_section.set_status(
            ("set: " + ", ".join(keyframes)) if keyframes else "", active=bool(keyframes)
        )
        route_changed = self.output_route_var.get().strip() != str(
            self._defaults.get("output_route") or OUTPUT_ROUTE_REPROCESS
        )
        self.details_section.set_status(
            "output route changed" if route_changed else "", active=route_changed
        )

    # ------------------------------------------------------------------ task (PR-VID-UX-360)

    def current_task(self) -> str:
        return self._task

    def select_task(self, task_id: str, *, pinned_workflow_id: str = "") -> bool:
        """Switch to ``task_id``: pick its engine, fill unpinned settings, show only its inputs.

        Returns False, changing nothing, when no installed workflow can serve the task or a batch step is
        still running.  It never records experimental consent: only the picker's own selection does."""

        if task_id not in {task.task_id for task in TASKS}:
            return False
        if self._task == TASK_BATCH and task_id != TASK_BATCH and not self._leave_batch_mode():
            self.task_selector.set_task(self._task)
            return False
        current = self.workflow_var.get().strip()
        if FIELD_ENGINE in self._pins.pinned and current:
            self._engine_by_task[self._task] = (
                current  # the operator's pick for the task being left
            )
        pinned = pinned_workflow_id or self._engine_by_task.get(task_id, "")
        if not pinned and FIELD_ENGINE in self._pins.pinned:
            pinned = current
        choice = choose_workflow(task_id, self._offered_records(pinned), pinned)
        if choice is None:
            self.task_selector.set_task(self._task)
            self.status_var.set(NO_ENGINE_MESSAGE)
            return False
        self._adopt_task(task_id)
        # The engine counts as the operator's own only when it is the one they picked for this task.
        if pinned and choice.workflow_id == pinned:
            self._pins.pinned.add(FIELD_ENGINE)
        else:
            self._pins.pinned.discard(FIELD_ENGINE)
        if choice.workflow_id != self.workflow_var.get().strip():
            with self._pins.applying():
                self.workflow_var.set(choice.workflow_id)  # capabilities and suggestions follow
        else:
            self._apply_suggestions()
        self._refresh_advanced_status()
        return True

    def _on_task_selected(self, task_id: str) -> bool:
        return self.select_task(task_id)

    def _follow_engine(self, workflow_meta: Mapping[str, Any]) -> None:
        """An engine chosen some other way (a restore, a handoff) brings its task with it."""

        if self._pins.is_applying or not workflow_meta.get("workflow_id"):
            return
        if not eligible_workflows(self._task, [workflow_meta]):
            self._adopt_task(infer_task(workflow_meta))

    def _adopt_task(self, task_id: str) -> None:
        previous, self._task = self._task, task_id
        self.task_selector.set_task(task_id)
        if previous == TASK_FOLLOW_CLIP and task_id != TASK_FOLLOW_CLIP:
            # Nothing tied to a driving clip may travel with an engine that does not take one.
            with self._pins.applying():
                self.pose_video_var.set("")
            self._library_binding = None
            self._library_bound_path = ""
            self._motion_prep_session.clear()
            self.motion_prep_panel.refresh()
            self.alignment_host.discard()
            if self._driver_host is not None:
                self._driver_host.release()
        if task_id == TASK_FOLLOW_CLIP:
            if previous != TASK_FOLLOW_CLIP and self._driver_host is not None:
                self._driver_host.requested_seconds = preset_duration_seconds(
                    preset_by_id(self._preset_id)
                )
            self.follow_clip_frame.grid()
            self.follow_clip_tools.grid()
        else:
            self.follow_clip_frame.grid_remove()
            self.follow_clip_tools.grid_remove()
        if task_id == TASK_SEQUENCE:
            self.sequence_panel.grid()
        else:
            self.sequence_panel.grid_remove()
        self.motion_intent_panel.show_mode(
            phrase=task_id == TASK_ANIMATE,
            preset=task_id in (TASK_ANIMATE, TASK_FOLLOW_CLIP),
            sends=task_id == TASK_BETWEEN,
        )
        if task_id == TASK_BETWEEN:
            self.end_image_frame.grid()
            self.keyframes_section.grid_remove()
        else:
            self.end_image_frame.grid_remove()
        self._sync_length_row()
        self._sync_duration()
        self._sync_batch_strip()
        self._sync_engine_choices()
        readiness = getattr(self, "motion_readiness_panel", None)
        if readiness is not None:
            readiness.render()

    def _sync_batch_strip(self) -> None:
        """The batch source strip shows for the batch task, for the driving-clip task (many images can
        share one clip), and whenever a batch is in force."""

        panel = getattr(self, "batch_panel", None)
        if panel is None:
            return
        if self._task in (TASK_BATCH, TASK_FOLLOW_CLIP) or self._batch_session.active:
            panel.grid()
        else:
            panel.grid_remove()

    def _sync_engine_choices(self) -> None:
        """Offer only the engines that can serve the task; disable a task no engine can serve."""

        if not hasattr(self, "task_selector"):
            return
        # N13: only offered engines (Show experimental decides the unrated arms), plus the selected one.
        records = self._offered_records(self.workflow_var.get().strip())
        eligible = {record["workflow_id"] for record in eligible_workflows(self._task, records)}
        self.workflow_combo["values"] = [
            label
            for label, workflow_id in self._workflow_label_to_id.items()
            if workflow_id in eligible
        ]
        self.task_selector.set_availability(
            {
                task.task_id: "" if choose_workflow(task.task_id, records) else NO_ENGINE_MESSAGE
                for task in TASKS
            }
        )

    def _offered_records(self, *keep: str) -> list[dict[str, Any]]:
        """N13: the records the picker offers now, plus ``keep`` (a selected or pinned engine stays offered)."""

        records = list(self._workflow_map.values())
        show = bool(self.show_experimental_var.get())
        offered = offered_workflow_ids(records, show_experimental=show, keep=keep)
        return [record for record in records if record["workflow_id"] in offered]

    def _rife_available(self) -> bool:
        getter = getattr(self._experiment_controller(), "rife_available", None)
        return bool(getter()) if callable(getter) else False  # the controller's check never raises

    def _apply_suggestions(self, kept_length: int | None = None) -> None:
        """Fill every setting the operator has not edited from what the engine declares, with reasons."""

        workflow_meta = self._workflow_map.get(self.workflow_var.get().strip(), {})
        self._suggestion_notes = []
        reasons: list[str] = []
        if workflow_meta.get("workflow_id"):
            self._rife_found = self._rife_available()
            suggestions = suggest_settings(
                self._task, workflow_meta, rife_available=self._rife_found
            )
            # V1-1: the motion preset is one more suggestion source, through the same pins.
            overlay, intent_notes = intent_suggestions(self._task, self._preset_id, workflow_meta)
            suggestions.update(overlay)
            if (
                self._task == TASK_FOLLOW_CLIP
                and self._driver_host is not None
                and self._driver_host.engaged
            ):
                suggestions.pop(FIELD_LENGTH, None)  # V1-3: the length follows the driver
            if kept_length is None:
                kept_length = self._frame_count_labels.get(self.frame_count_var.get())
            values, notes = reconcile(
                {FIELD_LENGTH: kept_length}, self._pins.pinned, suggestions, workflow_meta
            )
            with self._pins.applying():
                if FIELD_LENGTH in self._pins.pinned and FIELD_LENGTH not in values:
                    self._select_frame_count(
                        kept_length
                    )  # an engine change reset it to the default
                for field, value in values.items():
                    self._write_suggested(field, value)
            self._suggestion_notes = notes + intent_notes
            self._suggestion_basis = {
                field: suggestion.reason for field, suggestion in suggestions.items()
            }
            records = list(self._workflow_map.values())
            automatic = choose_workflow(self._task, records)
            if automatic is not None and automatic.workflow_id == workflow_meta["workflow_id"]:
                reasons.append(f"Engine: {automatic.reason}")
                self._suggestion_basis[FIELD_ENGINE] = automatic.reason
            else:
                reasons.append("Engine: Your choice.")
            reasons.extend(
                f"{_settings_title(field)}: "
                + ("Your choice." if field in self._pins.pinned else suggestion.reason)
                for field, suggestion in suggestions.items()
            )
        self.suggestion_reasons_var.set("\n".join(reasons))
        self._refresh_suggested_line()
        if self._driver_host is not None:
            self._driver_host.replan()

    def _write_suggested(self, field: str, value: Any) -> None:
        if field == FIELD_LENGTH:
            self._select_frame_count(value)
        elif field == FIELD_MOTION:
            self.motion_profile_var.set(str(value))
        elif field == FIELD_SMOOTH:
            self.smooth_var.set(bool(value))
        elif field == FIELD_SEED:
            self.seed_var.set(str(value))
        elif field == FIELD_NEGATIVE:
            self._set_text_value(self.negative_prompt_text, str(value))
        elif field == FIELD_MOTION_PHRASE:
            self.motion_intent_panel.phrase_var.set(str(value))
        elif field.startswith(CONTROL_FIELD_PREFIX):
            name = field.removeprefix(CONTROL_FIELD_PREFIX)
            self.workflow_controls_panel.set_values({name: _control_text(value)})

    def _refresh_suggested_line(self) -> None:
        line = getattr(self, "suggested_line", None)
        if line is None:
            return
        workflow_id = self.workflow_var.get().strip()
        workflow_meta = self._workflow_map.get(workflow_id, {})
        visible = dict(workflow_meta.get("form_visibility") or {})

        def shows(key: str) -> bool:
            return bool(visible.get(key, False)) if visible else True

        seed = self.seed_var.get().strip()
        smooth = bool(self.smooth_var.get())
        policy, frames = self._length_policy(), self._current_frames()
        preset = (
            preset_by_id(self._preset_id)
            if self._task in (TASK_ANIMATE, TASK_FOLLOW_CLIP)
            else None
        )
        self._refresh_composed()
        self._refresh_preset_status()
        line.set_summary(
            [
                self._workflow_id_to_label.get(workflow_id) or workflow_id or "No engine",
                duration_label(frames, policy).removesuffix(LONGEST_SUFFIX)
                if policy is not None and frames is not None
                else "",
                ""
                if preset is None
                else preset.label + (" (modified)" if self._preset_modified() else ""),
                f"{self.motion_profile_var.get().strip()} motion"
                if shows("motion_profile")
                else "",
                "smoothed" if smooth else "not smoothed",
                (f"seed {seed}" if seed else "random seed") if shows("seed") else "",
            ]
        )
        line.set_notes(
            [
                *self._suggestion_notes,
                smoothing_warning(self._task, smooth, rife_available=self._rife_found),
            ]
        )

    # ------------------------------------------------------------------ motion intent (V1-1)

    def _length_policy(self) -> LengthPolicy | None:
        if not self._frame_count_labels:
            return None
        meta = self._workflow_map.get(self.workflow_var.get().strip(), {})
        return length_policy(meta.get("frame_count"))

    def _current_frames(self) -> int | None:
        return self._frame_count_labels.get(self.frame_count_var.get())

    def _sync_duration(self) -> None:
        """Show the selected legal length as seconds (and its frames); writing the display is never an edit."""

        policy, frames = self._length_policy(), self._current_frames()
        if policy is None or frames is None:
            self._duration_shown = ""
            self.motion_intent_panel.set_duration("", "", "", ())
            return
        if self._task == TASK_FOLLOW_CLIP:
            self._sync_driver_duration(policy, frames)
            return
        choice = choice_for_frames(frames, policy)
        options = [option.label for option in duration_options(policy)]
        self._duration_shown = duration_label(frames, policy)
        self.motion_intent_panel.set_duration(
            self._duration_shown, choice.line(), choice.advisory, options
        )

    def _sync_driver_duration(self, policy: LengthPolicy, frames: int) -> None:
        """V1-3: the duration of a driven clip, in seconds only; what the driver allows is said beside it."""

        host = self._driver_host
        requested = None if host is None else host.requested_seconds
        clip = self.pose_video_var.get().strip()
        whole = requested is None and (not clip or (host is not None and host.engaged))
        self._duration_shown = WHOLE_MOVEMENT_LABEL if whole else duration_label(frames, policy)
        status = host.status() if host is not None else ""
        if not clip:
            status = "Choose a driving video: the clip follows its movement."
        options = [WHOLE_MOVEMENT_LABEL, *(option.label for option in duration_options(policy))]
        self.motion_intent_panel.set_duration(self._duration_shown, "", status, options)

    def _on_duration_entered(self, text: str) -> None:
        """The operator chose or typed a duration: the nearest legal length becomes their (pinned) length."""

        policy = self._length_policy()
        if policy is None:
            return
        if self._task == TASK_FOLLOW_CLIP:
            self._on_driver_duration(text, policy)
            return
        try:
            seconds = parse_seconds(text)
            choice = frames_for_duration(seconds, policy)
        except ValueError as exc:
            self.status_var.set(str(exc))
            self._sync_duration()
            return
        if choice.frames == self._current_frames():
            self._sync_duration()  # the same length again is not an edit
            return
        self._requested_seconds = (seconds, choice.frames)
        self._select_frame_count(choice.frames)

    def _on_driver_duration(self, text: str, policy: LengthPolicy) -> None:
        """ "Whole movement" or seconds; the driver then decides how much of it fits."""

        host = self._driver_host
        if host is None or text == self._duration_shown:
            return  # leaving the box unchanged is not a choice
        seconds: float | None = None
        if text.strip().lower() != WHOLE_MOVEMENT_LABEL.lower():
            try:
                seconds = parse_seconds(text)
                chosen = frames_for_duration(seconds, policy).frames
            except ValueError as exc:
                self.status_var.set(str(exc))
                self._sync_duration()
                return
        else:
            chosen = policy.default
        with self._pins.applying():
            self._select_frame_count(
                chosen
            )  # without a driver this is the length; with one it is re-fitted
        host.set_duration(seconds)
        self._sync_duration()

    def _on_preset_chosen(self, label: str) -> None:
        preset = preset_by_label(label)
        self._preset_id = NO_PRESET_ID if preset is None else preset.preset_id
        if self._task == TASK_FOLLOW_CLIP:
            self._apply_driver_preset(preset)
            return
        self._apply_suggestions()

    def _apply_driver_preset(self, preset: Any) -> None:
        """V1-3: a preset sets the motion controls and how long the clip should be; edited controls are kept."""

        if preset is None:
            meta = self._workflow_map.get(self.workflow_var.get().strip(), {})
            defaults = {
                control["name"]: ""
                if control.get("kind") == "text"
                else _control_text(control.get("default"))
                for control in meta.get("operator_controls") or ()
                if control["name"] in _PRESET_CONTROLS
                and CONTROL_FIELD_PREFIX + control["name"] not in self._pins.pinned
            }
            self.workflow_controls_panel.set_values(defaults)
        host = self._driver_host
        if host is not None:
            host.requested_seconds = preset_duration_seconds(preset)
        self._apply_suggestions()
        if host is not None:
            host.engage()
        self._sync_duration()

    def _on_reset_preset(self) -> None:
        """Forget the edits to what the preset sets (its duration and phrase) and take the preset's values again."""

        self._pins.pinned.difference_update({FIELD_LENGTH, FIELD_MOTION_PHRASE})
        if self._task == TASK_FOLLOW_CLIP:
            self._pins.pinned.difference_update(
                CONTROL_FIELD_PREFIX + name for name in _PRESET_CONTROLS
            )
            self._apply_driver_preset(preset_by_id(self._preset_id))
            return
        self._apply_suggestions()

    def _preset_modified(self) -> bool:
        meta = self._workflow_map.get(self.workflow_var.get().strip(), {})
        preset = preset_by_id(self._preset_id)
        if self._task == TASK_FOLLOW_CLIP:
            host = self._driver_host
            if (
                preset is not None
                and host is not None
                and host.requested_seconds != preset_duration_seconds(preset)
            ):
                return True
            values = self.workflow_controls_panel.get_values()
            current_controls = {
                CONTROL_FIELD_PREFIX + name: value for name, value in values.items()
            }
            return preset_is_modified(preset, INTENT_FOLLOW_DRIVER, meta, current_controls)
        current = {
            FIELD_LENGTH: self._current_frames(),
            FIELD_MOTION_PHRASE: self.motion_intent_panel.phrase_var.get(),
        }
        return preset_is_modified(preset_by_id(self._preset_id), INTENT_PROMPT_ONLY, meta, current)

    def _refresh_preset_status(self) -> None:
        preset = preset_by_id(self._preset_id)
        if preset is None:
            self.motion_intent_panel.set_preset(NO_PRESET_LABEL, "", modified=False)
            return
        modified = self._preset_modified()
        side = preset.follow_driver if self._task == TASK_FOLLOW_CLIP else preset.prompt_only
        status = " ".join(
            part for part in ("Modified." if modified else "", side.basis, side.warning) if part
        )
        self.motion_intent_panel.set_preset(preset.label, status, modified=modified)

    def _refresh_composed(self) -> None:
        """Preview of the prompt that is sent, whenever a motion phrase is added to it (D3)."""

        phrase = self.motion_intent_panel.phrase_var.get().strip()
        prompt = self.prompt_text.get("1.0", "end").strip()
        default = {
            TASK_FOLLOW_CLIP: DEFAULT_DRIVER_PROMPT,
            TASK_BETWEEN: DEFAULT_BETWEEN_PROMPT,
        }.get(self._task)
        if default:
            self.motion_intent_panel.set_composed("" if prompt else default)
            return
        shown = phrase and self._task == TASK_ANIMATE
        self.motion_intent_panel.set_composed(compose_prompt(prompt, phrase) if shown else "")

    def _motion_intent_record(self, phrase: str) -> dict[str, Any]:
        policy, frames = self._length_policy(), self._current_frames()
        duration = None
        if policy is not None and frames is not None:
            typed = self._requested_seconds
            requested = typed[0] if typed is not None and typed[1] == frames else None
            if self._task == TASK_FOLLOW_CLIP:
                requested = (
                    None if self._driver_host is None else self._driver_host.requested_seconds
                )
            duration = choice_for_frames(frames, policy, requested)
        basis = {
            field: "Your choice." if field in self._pins.pinned else reason
            for field, reason in self._suggestion_basis.items()
        }
        if FIELD_ENGINE in self._pins.pinned or FIELD_ENGINE not in basis:
            basis[FIELD_ENGINE] = "Your choice."
        return motion_intent_record(
            intent=self._task,
            preset=preset_by_id(self._preset_id),
            preset_modified=self._preset_modified(),
            motion_phrase=phrase,
            duration=duration,
            basis=basis,
        )

    @property
    def motion_ai_host(self) -> MotionAiHost:
        host = getattr(self, "_motion_ai_host", None)
        if host is None:
            panel = self.motion_intent_panel
            host = self._motion_ai_host = MotionAiHost(
                self,
                ai=lambda: getattr(self.app_controller, "ai_assist", None),
                source=self.source_image_var.get,
                prompt=lambda: self.prompt_text.get("1.0", "end"),
                phrase_var=panel.phrase_var,
                pins=self._pins,
                on_status=self.status_var.set,
                on_busy=panel.set_suggest_busy,
                on_undo_available=panel.show_undo,
            )
        return host

    # ------------------------------------------------------------------ follow a driving video (V1-3)

    def _read_driver_inputs(self) -> DriverInputs:
        session = getattr(self, "_batch_session", None)
        return DriverInputs(
            active=self._task == TASK_FOLLOW_CLIP,
            clip_path=self.pose_video_var.get().strip(),
            source_path=self.source_image_var.get().strip(),
            record=self._workflow_map.get(self.workflow_var.get().strip(), {}),
            batch=bool(session is not None and session.active),
        )

    def _apply_driver_frames(self, frames: int) -> None:
        with (
            self._pins.applying()
        ):  # the driver's length is the form adapting, not an operator edit
            self._select_frame_count(frames)

    def _driver_block_reason(self) -> str:
        host = getattr(self, "_driver_host", None)
        return "" if host is None else host.block_reason()

    def _refresh_driver_view(self) -> None:
        self._sync_duration()
        self._refresh_queue_gate()
        self._refresh_suggested_line()

    def _sync_length_row(self) -> None:
        """The raw length list (frame counts) is for the other tasks; a driven clip is chosen in seconds."""

        if self._frame_count_labels and self._task != TASK_FOLLOW_CLIP:
            self.frame_count_frame.grid()
        else:
            self.frame_count_frame.grid_remove()

    def _toggle_motion_library(self) -> None:
        if self.motion_library_panel.winfo_manager():
            self.motion_library_panel.grid_remove()
            self.motion_library_button.configure(text="Show Motion Library")
        else:
            self.motion_library_panel.grid()
            self.motion_library_button.configure(text="Hide Motion Library")

    def _on_driver_typed(self, _event: Any = None) -> None:
        self._driver_typed = True

    def _on_driver_entered(self, _event: Any = None) -> None:
        """A path typed or pasted into the driver field was committed (Return or leaving the field)."""

        if self._driver_typed and self._driver_host is not None:
            self._driver_typed = False
            self._driver_host.choose(self.pose_video_var.get())
            self._sync_duration()

    # ------------------------------------------------------------------ re-run with tweaks (V1-2)

    @property
    def rerun_host(self) -> RerunHost:
        host = getattr(self, "_rerun_host", None)
        if host is None:
            host = self._rerun_host = RerunHost(
                self,
                repository=lambda: getattr(
                    getattr(self.app_controller, "job_service", None), "history_store", None
                ),
                on_opened=self.apply_rerun,
                on_refused=self._fail,
                on_status=self.status_var.set,
            )
        return host

    def open_rerun(self, job_id: str) -> None:
        """Re-run with tweaks: read the finished job on a worker, then fill the form from it (nothing is queued)."""

        self.rerun_host.open(job_id)

    def apply_rerun(self, opening: RerunOpening) -> None:
        """Fill the form from a finished job (every value pinned, a new random seed); Queue builds a new NJR with
        lineage to it through the normal builder."""

        if not self._leave_batch_mode():
            return
        self.select_view(VIEW_CREATE)
        self.submission_notice.clear()
        self.restore_video_workflow_state(dict(opening.form))
        self._rerun = opening
        message = (
            f"Re-run with tweaks of job {opening.snapshot.job_id}: change what you like, then Queue "
            "(a new random seed is used)."
        )
        binding, driver = opening.snapshot.driver, opening.driver
        if binding is not None and driver is not None:
            settings = binding.settings
            requested = settings.get("requested") if isinstance(settings, Mapping) else None
            start = (requested or {}).get("start") if isinstance(requested, Mapping) else None
            end = (requested or {}).get("end") if isinstance(requested, Mapping) else None
            self.motion_prep_panel.set_window(
                start=float(start) if isinstance(start, int | float) else 0.0,
                end=float(end) if isinstance(end, int | float) else None,
                convert=settings.get("fps_conversion") == "workflow_rate",
            )
            if driver.action == DRIVER_REPREPARE:
                self.motion_prep_panel.prepare()
                message += f" {driver.reason}"
            elif driver.prepared is not None and not binding.aligned:
                self.motion_prep_panel.adopt_record(driver.prepared, driver.reason)
            elif driver.prepared is not None:
                message += " The aligned driving clip is reused while the length stays the same."
        self.status_var.set(message)

    def _rerun_submission_fields(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """The lineage (and an aligned clip the re-run reuses) while the form still starts from that job's source."""

        opening = self._rerun
        if opening is None or self.source_image_var.get().strip() != str(
            opening.form.get("source_image_path") or ""
        ):
            return {}
        fields: dict[str, Any] = {}
        binding, driver = opening.snapshot.driver, opening.driver
        if (
            binding is not None
            and binding.aligned
            and driver is not None
            and driver.action == DRIVER_REUSE
            and driver.prepared is not None
            and ALIGN_PREPARED_FIELD not in state
            and state.get("pose_video_path") == binding.path
        ):
            if state.get("frame_count") == opening.snapshot.frame_count:
                fields[ALIGN_PREPARED_FIELD] = dict(driver.prepared)
            else:
                fields[ALIGN_BLOCKED_FIELD] = (
                    f"The aligned driving clip was made for {opening.snapshot.frame_count} frames. "
                    "Apply Align Motion again for the new length, or keep the original length."
                )
        edits = rerun_edits(opening.snapshot, self.get_video_workflow_state())
        fields[RERUN_LINEAGE_FIELD] = rerun_lineage(opening.snapshot, edits)
        return fields

    def _toggle_settings(self) -> None:
        self.advanced_section.toggle()
        self._sync_settings_editor_label()

    def _toggle_reasons(self) -> None:
        """Show or hide why the suggested settings were chosen (the reasons are text, not controls)."""

        if self.reasons_label.winfo_manager():
            self.reasons_label.grid_remove()
        else:
            self.reasons_label.grid()

    # ------------------------------------------------------------------ views and media (VID-UX-384)

    def current_view(self) -> str:
        return self._view

    def select_view(self, view_id: str) -> None:
        """Switch between Create and Evaluate.  Both views stay built, so no form state is lost."""

        if view_id not in (VIEW_CREATE, VIEW_EVALUATE):
            return
        self._view = view_id
        self.view_switch.set_view(view_id)
        if view_id == VIEW_EVALUATE:
            self._create_view.grid_remove()
            self.evaluate_view.grid()
            self.evaluate_view.sync()
        else:
            self.evaluate_view.grid_remove()
            self._create_view.grid()
        self._sync_pane_switch()
        # One Primary per visible surface: Queue video is Create's; the eval panel's own Queue is Evaluate's.
        self.queue_workflow_button.configure(
            style="Primary.TButton" if view_id == VIEW_CREATE else "Dark.TButton"
        )

    def _content_mode(self) -> str:
        return str(getattr(self.app_state, "content_visibility_mode", "nsfw") or "nsfw")

    def _readiness_media_allowed(self) -> bool:
        """Show media is on AND the application content-visibility policy lets the source render."""

        path = self.source_image_var.get().strip()
        return bool(self.show_media_var.get()) and media_allowed(self._content_mode(), path)

    def _apply_show_media(self) -> None:
        pane = getattr(self, "_media_pane", None)
        if pane is not None:
            pane.apply_show_media()

    def _sync_source_preview(self) -> None:
        pane = getattr(self, "_media_pane", None)
        if pane is not None:
            pane.sync_source(self.source_image_var.get().strip())

    def _on_readiness_rendered(self, view: Any) -> None:
        """Decide whether the readiness details earn a place on screen, and say the gist in the header chip."""

        panel = getattr(
            self, "motion_readiness_panel", None
        )  # absent while the panel is being built
        if panel is not None:
            panel.set_relevant(
                readiness_is_relevant(
                    view,
                    follow_clip_task=self._task == TASK_FOLLOW_CLIP,
                    opened=self._readiness_opened,
                )
            )
        chip = getattr(self, "readiness_chip", None)
        if chip is not None:
            chip.configure(
                text=readiness_chip_text(view, has_source=bool(self.source_image_var.get().strip()))
            )

    def _on_readiness_chip(self) -> None:
        """Open the readiness details in the right pane (and make sure the Create view is showing)."""

        self._readiness_opened = True
        self.select_view(VIEW_CREATE)
        self.reveal_media_pane()
        panel = self.motion_readiness_panel
        panel.set_relevant(True)
        panel.render()
        panel.request_refresh(force=True)

    def _sync_settings_editor_label(self) -> None:
        line = getattr(self, "suggested_line", None)
        if line is not None:
            line.set_editing(self.advanced_section.is_expanded())

    def _reset_to_suggested(self) -> None:
        """Forget every operator edit to the settings and take the suggestions again."""

        self._pins.clear()
        self._engine_by_task.clear()
        self.select_task(self._task)

    def _refresh_conditioning_status(self, workflow_meta: dict[str, Any]) -> None:
        """Collapsed-header hint: say so when hidden conditioning is active or edited from its default."""

        visible = dict(workflow_meta.get("form_visibility") or {})
        if visible and not (visible.get("camera_intent") or visible.get("depth_conditioning")):
            self.conditioning_section.set_status("not used by this workflow")
            return
        current = {
            "camera_preset": self.camera_preset_var.get(),
            "camera_strength": self.camera_strength_var.get(),
            "depth_mode": self.depth_mode_var.get(),
            "depth_path": self.depth_path_var.get(),
            "controlnet_model": self.controlnet_model_var.get(),
            "controlnet_weight": self.controlnet_weight_var.get(),
            "controlnet_guidance_start": self.controlnet_guidance_start_var.get(),
            "controlnet_guidance_end": self.controlnet_guidance_end_var.get(),
        }
        active: list[str] = []
        camera = self.camera_preset_var.get().strip() or "none"
        depth = self.depth_mode_var.get().strip() or "none"
        if camera != "none":
            active.append(f"camera={camera}")
        if depth != "none":
            active.append(f"depth={depth}")
        changed = changed_value_count(current, self._conditioning_defaults)
        if active:
            self.conditioning_section.set_status("active: " + ", ".join(active), active=True)
        elif changed:
            self.conditioning_section.set_status(f"{changed} edited (inactive)", active=True)
        else:
            self.conditioning_section.set_status("")

    def _experiment_controller(self) -> Any:
        getter = getattr(self.app_controller, "get_video_workflow_controller", None)
        return getter() if callable(getter) else None

    def _on_tab_shown(self, _event: Any = None) -> None:
        """Re-check the runtime when the tab is shown, so a hidden tab never probes the host at start-up."""

        strip = getattr(self, "runtime_readiness_strip", None)
        if strip is not None:
            strip.request_refresh(force=True)
        recent = getattr(self, "recent_outputs_panel", None)
        if recent is not None:
            # Resolved on the Tk thread; the worker only calls the already-built controller.
            self._recent_controller = self._experiment_controller()
            recent.request_refresh()
        self._refresh_motion_library()

    def _open_comfy_setup(self) -> None:
        """Open the existing Engine Settings > Video runtime (ComfyUI) section; nothing is edited or started here."""

        opener = getattr(self.app_controller, "on_open_settings", None)
        if not callable(opener):
            return
        strip = self.runtime_readiness_strip
        view = strip.last_view
        opener(
            focus_video_runtime=True,
            comfy_repair_reason=view.repair_reason if view else "",
            on_closed=lambda: strip.request_refresh(
                force=True
            ),  # shows a restart-pending save at once
        )

    # ------------------------------------------------------------------ Motion Library

    def _library_controller(self) -> Any:
        controller = getattr(self, "_recent_controller", None)
        if controller is None:
            raise RuntimeError("The Video Workflow controller is not available.")
        return controller

    def _motion_library_ports(self) -> MotionLibraryPorts:
        def lib() -> Any:
            return self._library_controller()

        return MotionLibraryPorts(
            snapshot=lambda: lib().motion_library_snapshot(),
            inspect=lambda asset_id, cancel: lib().inspect_motion_asset(asset_id, cancel),
            import_file=lambda path, mode, notes, cancel: lib().import_motion_video(
                path, mode=mode, annotations=notes, cancel=cancel
            ),
            import_folder=lambda folder, mode, notes, cancel: lib().import_motion_folder(
                folder, mode=mode, annotations=notes, cancel=cancel
            ),
            annotate=lambda asset_id, changes: lib().annotate_motion_asset(asset_id, changes),
            relink=lambda asset_id, path, cancel: lib().relink_motion_asset(asset_id, path, cancel),
            configure=lambda root: lib().configure_motion_library(root),
            plan_handoff=lambda asset_id, workflow_id, version, cancel: (
                lib().plan_motion_library_handoff(asset_id, workflow_id, version, cancel)
            ),
        )

    def _open_motion_conversion(self) -> None:
        """PR-VID-MOTION-354: the non-modal Convert Motion dialog (Blender, CPU only); queues nothing."""

        existing = getattr(self, "_motion_conversion_dialog", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                return
        except tk.TclError:
            pass
        self._motion_conversion_dialog = MotionConversionDialog(
            self,
            ports=self._library_controller().motion_conversion_ports(
                self._selected_workflow_identity
            ),
            on_accepted=lambda asset_id: self.motion_library_panel.focus_asset(asset_id),
        )

    def _open_motion_batch(self) -> None:
        """PR-VID-MOTION-356: the non-modal Batch Convert Motion dialog (offline, Blender CPU); queues nothing."""

        existing = getattr(self, "_motion_batch_dialog", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                return
        except tk.TclError:
            pass
        self._motion_batch_dialog = MotionBatchDialog(
            self,
            ports=self._library_controller().motion_batch_ports(self._selected_workflow_identity),
            on_finished=self._refresh_motion_library,
        )

    def _conditioning_context(self, detail: Any) -> Any:
        """The effective-driver inspection context for the selected engine, or ``None`` when it takes no driving clip."""

        resolve = getattr(self._library_controller(), "motion_conversion_workflow", None)
        if resolve is None:
            return None
        choice = resolve(*self._selected_workflow_identity())
        if getattr(choice, "spec", None) is None:
            return None
        prepared = self._motion_prep_session.submission_fields().get(PREPARED_FIELD)
        return build_inspection_context(
            choice.spec,
            detail.asset,
            detail.media_path,
            prepared if isinstance(prepared, Mapping) else None,
            frame_count=self._read_motion_prep_form().get("frame_count"),
        )

    def _run_conditioning_preview(
        self, path: str, sha: str, size: tuple[int, int], cancel: Any
    ) -> Any:
        context = getattr(self, "_conditioning_inspection", None)
        controller = self._library_controller()
        if context is not None:
            return controller.motion_conditioning_inspection(context, cancel)
        return controller.motion_conditioning_preview(path, sha, size, cancel)

    def _open_conditioning_preview(self, detail: Any) -> None:
        """Approximate Canny preview of the effective driving clip for the selected engine (no queue, Comfy or GPU).

        The effective clip is the verified prepared or aligned derivative when one exists for this engine and length; a
        preparation made for another engine is never used and is reported as stale (PR-VID-MOTION-430)."""

        window = getattr(self, "_conditioning_preview_window", None)
        try:
            if window is None or not window.winfo_exists():
                window = ConditioningPreviewWindow(self, preview=self._run_conditioning_preview)
                self._conditioning_preview_window = window
            else:
                window.lift()
        except tk.TclError:
            return
        asset = detail.asset
        context = self._conditioning_context(detail)
        self._conditioning_inspection = context
        if context is not None:
            window.show_clip(
                context.driver.path, context.driver.sha256, context.target_size, context.heading
            )
            return
        portrait = not asset.width or not asset.height or asset.height >= asset.width
        size = (480, 832) if portrait else (832, 480)
        window.show_clip(
            detail.media_path, asset.sha256, size, f"{asset.display_name} - {size[0]}x{size[1]}"
        )

    def open_motion_harvest(self, ref: HarvestSourceRef) -> None:
        """PR-VID-MOTION-400: the one non-modal Harvest Motion workspace (offline; queues nothing, edits no field)."""

        host = getattr(self, "_harvest_host", None)
        if host is None:
            host = self._harvest_host = HarvestHost(
                self,
                controller=self._library_controller,
                read_form=self._read_motion_prep_form,
                mode_provider=lambda: str(
                    getattr(self.app_state, "content_visibility_mode", "nsfw") or "nsfw"
                ),
                source_image=lambda: self.source_image_var.get().strip(),
                on_saved=lambda record: self._refresh_motion_library(),
            )
        host.open(ref)

    def _harvest_recent_output(self, output: RecentVideoOutput) -> None:
        self.open_motion_harvest(
            HarvestSourceRef(
                path=output.video_path,
                label=output.file_name,
                job_id=output.job_id,
                surface="recent_outputs",
                subject=output.visibility_subject or {"name": output.file_name},
            )
        )

    def _selected_workflow_identity(self) -> tuple[str, str]:
        meta = self._workflow_map.get(self.workflow_var.get().strip(), {})
        return (str(meta.get("workflow_id") or ""), str(meta.get("workflow_version") or ""))

    def _refresh_motion_library(self) -> None:
        panel = getattr(self, "motion_library_panel", None)
        if panel is not None:
            panel.request_refresh()

    def _add_output_to_library(self, output: RecentVideoOutput, details: Mapping[str, Any]) -> Any:
        """Worker-side: keep a finished clip as a motion reference (explicit operator action)."""

        return self._library_controller().add_job_to_motion_library(
            output.job_id,
            mode=str(details.get("mode") or "linked"),
            motion_label=str(details.get("motion_label") or ""),
            motion_achieved=details.get("motion_achieved"),
            good_for_motion=details.get("good_for_motion"),
            known_artifacts=str(details.get("known_artifacts") or ""),
            reuse_conditions=str(details.get("reuse_conditions") or ""),
        )

    def _apply_library_handoff(self, plan: HandoffPlan) -> None:
        """Fill only the driving-video field with the verified clip (nothing is previewed or queued)."""

        fields = plan.form_fields
        if not fields:
            return
        if self._task != TASK_FOLLOW_CLIP:
            self.select_task(TASK_FOLLOW_CLIP, pinned_workflow_id=plan.workflow_id)
        self.pose_video_var.set(fields["pose_video_path"])
        self._library_binding = plan.binding
        self._library_bound_path = plan.path
        self._invalidate_experiment_preview()
        if self._driver_host is not None:
            self._driver_host.choose(self.pose_video_var.get())
            self._sync_duration()
        self.status_var.set(
            "Driving video set from the Motion Library. Preview the job to confirm it. "
            + " ".join(plan.advisories[:2])
        )

    def _list_recent_outputs(self) -> list[Any]:
        getter = getattr(self._recent_controller, "list_recent_video_outputs", None)
        return list(getter()) if callable(getter) else []

    def _send_output_to_movie(self, output: Any) -> None:
        """Hand a recent clip's recorded bundle to Movie Clips (intent only; nothing is queued)."""

        from src.gui.controllers.video_workspace_handoff import route_bundle_to_movie_clips

        main_window = getattr(self.app_controller, "main_window", None)
        if main_window is None:
            raise RuntimeError("The main window is not available.")
        route_bundle_to_movie_clips(
            main_window=main_window,
            bundle=dict(output.bundle),
            status_message=f"Loaded {output.file_name} into Movie Clips.",
        )

    def _continue_output_in_storyboard(self, output: Any) -> None:
        """Open a recent clip's job in the Storyboard tab as a new root (intent only; nothing is queued)."""

        from src.gui.controllers.video_workspace_handoff import route_job_to_storyboard

        main_window = getattr(self.app_controller, "main_window", None)
        if main_window is None:
            raise RuntimeError("The main window is not available.")
        route_job_to_storyboard(main_window=main_window, job_id=output.job_id)

    def _read_runtime_readiness_selection(self) -> tuple[str, str]:
        """The selected workflow for the runtime strip; empty (strip hidden) when there is no controller."""

        if self._experiment_controller() is None:
            return ("", "")
        meta = self._workflow_map.get(self.workflow_var.get(), {})
        return (str(meta.get("workflow_id") or ""), str(meta.get("workflow_version") or ""))

    def _read_motion_readiness_inputs(self) -> dict[str, Any]:
        """Plain snapshot of what the readiness panel shows (Tk reads happen here, never on a worker)."""

        meta = self._workflow_map.get(self.workflow_var.get(), {})
        readiness = meta.get("motion_readiness")
        selected = self._frame_count_labels.get(self.frame_count_var.get())
        return {
            "source_path": self.source_image_var.get().strip(),
            "video_path": self.pose_video_var.get().strip(),
            "readiness": readiness if isinstance(readiness, dict) else None,
            "frame_count": meta.get("frame_count"),
            "selected_frames": selected,
        }

    def _on_motion_prep_changed(self) -> None:
        self._invalidate_experiment_preview()
        row = getattr(self, "alignment_row", None)
        if row is not None:
            row.refresh()  # the window or rate conversion changed: an applied alignment may be stale
        if getattr(self, "_driver_host", None) is not None:
            self._refresh_driver_view()

    def _alignment_media_allowed(self) -> bool:
        clip = self.pose_video_var.get().strip()
        return self._readiness_media_allowed() and media_allowed(self._content_mode(), clip)

    def _read_alignment_inputs(self) -> AlignInputs:
        """What the Align Motion workspace needs from the form (Tk reads happen here, on the UI thread)."""

        form = self._read_motion_prep_form()
        available, reason = bool(form["available"]), str(form["unavailable_reason"])
        controller = self._experiment_controller()
        if available and controller is not None:
            support = controller.motion_alignment_support(
                {"workflow_id": form["workflow_id"], "workflow_version": form["workflow_version"]}
            )
            available, reason = support.supported, "" if support.supported else support.reason
        panel = self.motion_prep_panel
        binding = binding_for_submission(
            self._library_binding,
            current_path=str(form["clip_path"]),
            bound_path=self._library_bound_path,
        )
        source = self.source_image_var.get().strip()

        def stat(path: str) -> tuple[int, int] | None:
            try:
                info = Path(path).expanduser().stat()
            except (OSError, ValueError):
                return None
            return (info.st_size, info.st_mtime_ns)

        return AlignInputs(
            available=available,
            unavailable_reason=reason,
            workflow_id=str(form["workflow_id"]),
            workflow_version=str(form["workflow_version"]),
            frame_count=form["frame_count"],
            output_fps=form["output_fps"],
            clip_path=str(form["clip_path"]),
            source_path=source,
            start_text=panel.start_var.get(),
            end_text=panel.end_var.get(),
            convert=bool(panel.convert_var.get()),
            clip_stat=stat(str(form["clip_path"])) if form["clip_path"] else None,
            source_stat=stat(source) if source else None,
            library_asset_id=str((binding or {}).get("asset_id") or ""),
        )

    def _read_motion_prep_form(self) -> dict[str, Any]:
        """What the Prepare Motion Source panel needs from the form (Tk reads happen here)."""

        meta = self._workflow_map.get(self.workflow_var.get(), {})
        readiness = dict(meta.get("motion_readiness") or {})
        accepts = bool(readiness.get("accepts_driving_video"))
        consumption = dict(readiness.get("driving_frame_consumption") or {})
        frame_meta = dict(meta.get("frame_count") or {})
        available = accepts and bool(consumption.get("verified")) and bool(frame_meta)
        reason = ""
        if accepts and not available:
            detail = str(consumption.get("reason") or "") or "it declares no generation length."
            reason = f"Preparation is not offered for this workflow: {detail}"
        return {
            "available": available,
            "unavailable_reason": reason,
            "workflow_id": str(meta.get("workflow_id") or self.workflow_var.get()),
            "workflow_version": str(meta.get("workflow_version") or ""),
            "frame_count": self._frame_count_labels.get(self.frame_count_var.get()),
            "output_fps": frame_meta.get("fps"),
            "clip_path": self.pose_video_var.get().strip(),
        }

    def _invalidate_experiment_preview(self) -> None:
        panel = getattr(self, "experiment_panel", None)
        if panel is not None:
            panel.invalidate_if_changed()
        batch_panel = getattr(self, "batch_panel", None)
        if batch_panel is not None:
            batch_panel.invalidate_if_changed()

    def _read_batch_form(self) -> dict[str, Any]:
        # The batch owns its sources; the single-image field is not part of the batch inputs.
        form = self.get_video_workflow_state(for_submission=True)
        form.pop("source_image_path", None)
        if getattr(self, "_single_frozen_plan", False):
            form["_preview_reference_path"] = self.source_image_var.get().strip()
        return form

    def _preview_frozen_plan(self) -> None:
        """Use the existing one-source batch compiler/worker and its edit-invalidated preview."""
        source = self.source_image_var.get().strip()
        if not source:
            self.status_var.set("Choose a reference image before Preview Frozen Plan.")
            return
        self._single_frozen_plan = True
        self.batch_panel.preview_single_source(source)

    def _on_batch_mode_change(self, active: bool) -> None:
        # One authoritative source mode at a time: batch mode disables the single-image queue.
        self._queue_blocked_by_batch = bool(active)
        self._sync_batch_strip()
        self._refresh_queue_gate()
        if hasattr(self, "workflow_controls_panel"):  # the body is built after the header
            self._refresh_workspace_summary()

    def _on_batch_queued_refresh_only(self, _job_ids: list[str]) -> None:
        # Eval admission ran on a worker; GUI-visible queue state is refreshed here, on Tk.
        sync = getattr(self.app_controller, "sync_queue_state_after_direct_submission", None)
        if callable(sync):
            sync()

    def _on_batch_queued(self, job_ids: list[str]) -> None:
        # Admission ran on a worker; refreshing GUI-visible queue state happens here, on Tk.
        sync = getattr(self.app_controller, "sync_queue_state_after_direct_submission", None)
        if callable(sync):
            sync()
        if not job_ids:
            return  # a refusal: the session message (already shown) is the status
        result = self._batch_session.last_result
        batch_id = getattr(result, "batch_id", "")
        self.status_var.set(
            f"Queued {len(job_ids)} video jobs as batch {batch_id}. See Queue / History."
        )

    def set_source_batch(
        self,
        paths: list[str],
        *,
        lineage_by_path: dict[str, dict[str, str]] | None = None,
        status_message: str | None = None,
    ) -> bool:
        """Accept an ordered Review selection as batch sources (intent only; nothing is queued)."""

        accepted = self.batch_panel.set_review_selection(list(paths), dict(lineage_by_path or {}))
        if accepted and self._task not in (TASK_BATCH, TASK_FOLLOW_CLIP):
            self.select_task(TASK_BATCH)  # a driving-clip batch keeps its task, engine and clip
        if accepted and status_message:
            self.status_var.set(status_message)
        return accepted

    def _on_sequence_queued(self, job_id: str) -> None:
        sync = getattr(self.app_controller, "sync_queue_state_after_direct_submission", None)
        if callable(sync):
            sync()
        message = f"Queued multi-shot sequence job {job_id}"
        self.status_var.set(message)
        self.submission_notice.show_queued(message + ".", on_view_queue=self._on_view_queue)

    def _on_experiment_queued(self, job_ids: list[str]) -> None:
        # Admission ran on a worker; refreshing GUI-visible queue state happens here, on Tk.
        sync = getattr(self.app_controller, "sync_queue_state_after_direct_submission", None)
        if callable(sync):
            sync()
        self.status_var.set(f"Queued {len(job_ids)} experiment jobs: " + ", ".join(job_ids))

    def _on_open_experiment_review(self, job_id: str) -> None:
        # Entry point to the compare-and-rate window; it reads canonical history, never the form.
        from src.gui.views.video_experiment_review_window import open_video_experiment_review

        if open_video_experiment_review(self, self.app_controller, job_id) is None:
            self.status_var.set("Experiment review is unavailable: no job repository.")

    def _set_text_value(self, widget: tk.Text, value: str) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        self._refresh_advanced_status()

    def on_content_visibility_mode_changed(self, mode: str | None = None) -> None:
        self._pending_visibility_refresh = False
        self.visibility_banner.configure(text="")
        library = getattr(self, "motion_library_panel", None)
        if library is not None:
            library.on_content_visibility_mode_changed(mode)
        readiness = getattr(self, "motion_readiness_panel", None)
        if readiness is not None:
            readiness.render()  # an application "hidden" mode wins over the Show media checkbox

    def _on_content_visibility_mode_changed(self) -> None:
        if not bool(self.winfo_ismapped()):
            self._pending_visibility_refresh = True
            return
        self.on_content_visibility_mode_changed()

    def _on_map(self, _event=None) -> None:
        if not self._pending_visibility_refresh:
            return
        self.after_idle(self.on_content_visibility_mode_changed)

    def _on_browse_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose source image",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if path:
            self._last_folder = str(Path(path).parent)
            if not self._leave_batch_mode():
                return
            self._leave_batch_task()
            self.source_image_var.set(path)

    def _on_browse_pose_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Driving Video",
            filetypes=_VIDEO_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if path:
            self._last_folder = str(Path(path).parent)
            self.pose_video_var.set(path)
            if self._driver_host is not None:
                self._driver_host.choose(path)
                self._sync_duration()

    def _on_browse_end_anchor(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose end anchor image",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if path:
            self._last_folder = str(Path(path).parent)
            self.end_anchor_var.set(path)

    def _on_browse_mid_anchors(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Choose mid anchor images",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if paths:
            self._last_folder = str(Path(paths[0]).parent)
            self.mid_anchors_var.set("; ".join(str(path) for path in paths))

    def _on_browse_depth_map(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose depth map image",
            filetypes=_IMAGE_FILETYPES,
            initialdir=self._last_folder or None,
        )
        if path:
            self._last_folder = str(Path(path).parent)
            self.depth_path_var.set(path)

    def _refresh_conditioning_controls_state(self) -> None:
        upload_enabled = self.depth_mode_var.get().strip().lower() == "upload"
        entry_state = "normal" if upload_enabled else "disabled"
        button_state = "normal" if upload_enabled else "disabled"
        self.depth_path_entry.configure(state=entry_state)
        self.depth_browse_button.configure(state=button_state)

    def _on_use_latest_output(self) -> None:
        controller = getattr(self, "app_controller", None)
        getter = getattr(controller, "get_latest_output_image_path", None)
        latest = getter() if callable(getter) else None
        if latest:
            if not self._leave_batch_mode():
                return
            self._leave_batch_task()
            self._source_bundle = None
            self.source_image_var.set(str(latest))
            self.status_var.set(f"Loaded latest output: {Path(str(latest)).name}")
            self._refresh_workspace_summary()
        else:
            self.status_var.set("No recent image output available to route into Video Workflow.")

    def _fail(self, message: str) -> None:
        """Show a failure beside the form (and in the status line); it stays until dismissed or retried."""

        self.status_var.set(message)
        self.submission_notice.show_error(message)

    def _current_lineage(self) -> dict[str, str]:
        if (
            self._source_lineage
            and self.source_image_var.get().strip() == self._source_lineage_path
        ):
            return dict(self._source_lineage)
        return {}

    def _on_view_queue(self) -> None:
        from src.gui.controllers.video_workspace_handoff import show_queue_view

        if not show_queue_view(getattr(self.app_controller, "main_window", None)):
            self.status_var.set("The queue view is not available from here; open the Pipeline tab.")

    def _on_use_svd(self) -> None:
        source = self.source_image_var.get().strip()
        sender = getattr(self.app_controller, "send_image_to_svd", None)
        if not source:
            self._fail("Choose a source image first.")
        elif not callable(sender):
            self._fail("The native SVD tab is not available.")
        else:
            try:
                sender(source)
            except (OSError, RuntimeError, ValueError) as exc:
                self._fail(f"Could not open the SVD tab: {exc}")

    def _on_submit(self) -> None:
        self.submission_notice.clear()
        controller = getattr(self, "app_controller", None)
        handler = getattr(controller, "submit_video_workflow_job", None)
        if not callable(handler):
            self._fail("Video workflow submission is not available.")
            return
        source_image_path = self.source_image_var.get().strip()
        if not source_image_path:
            self._fail(
                "Choose a source image first: Browse..., Use Latest Output, or Make Video from "
                "Review, History or the Pipeline preview."
            )
            return
        form_data = self.get_video_workflow_state(for_submission=True)
        lineage = self._current_lineage()
        if lineage:
            form_data["source_lineage"] = lineage
        try:
            job_id = handler(source_image_path=source_image_path, form_data=form_data)
        except Exception as exc:
            self._fail(f"Not queued: {exc}")
            return
        self._submitted_effective_settings = dict(
            form_data.get("_stable_new_submission_projection") or {}
        )
        submitted_seed = self._submitted_effective_settings.get("seed")
        status_suffix = f" (seed {submitted_seed})" if submitted_seed is not None else ""
        message = f"Queued video workflow job {job_id}{status_suffix}"
        self.status_var.set(message)
        self._refresh_workspace_summary()
        self.submission_notice.show_queued(message + ".", on_view_queue=self._on_view_queue)
