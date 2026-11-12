from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from tkinter import messagebox, ttk
from typing import Any

from src.gui.help_text.stage_setting_help_v2 import ADETAILER_STAGE_HELP
from src.gui.layout_v2 import configure_grid_columns
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import (
    BODY_LABEL_STYLE,
    DARK_CHECKBUTTON_STYLE,
    DARK_COMBOBOX_STYLE,
    DARK_SPINBOX_STYLE,
    SURFACE_FRAME_STYLE,
)
from src.gui.ui_tokens import TOKENS
from src.gui.view_contracts.pipeline_layout_contract import (
    get_single_pair_form_column_specs,
    get_stage_card_min_width,
    get_two_pair_form_column_specs,
)
from src.image_backends.backend_capabilities import configured_adetailer_detector_fallbacks
from src.pipeline.adetailer_contract import (
    FRESH_PASS_DEFAULTS,
    MASK_FILTER_METHODS,
    MASK_MERGE_MODES,
    UNSUPPORTED_CONFIG_KEYS,
    detector_status,
    schema_issues,
    split_detectors,
)
from src.pipeline.adetailer_profiles import (
    FACE_MASK_LIMITS,
    FACE_MODES,
    PROFILES_KEY,
    apply_profile,
    profile_values,
    suggested_profile,
)
from src.services.ui_state_store import UIStateStore

_MODE_LABELS = {
    "single": "Single Face",
    "multiple": "Multiple Faces",
    "auto": "Auto (Prompt-Aware)",
    "legacy": "Inherited settings",
}
_DRAFT_KEY = "adetailer_working_draft"
_DRAFT_DELAY_MS = 450


class ADetailerStageCardV2(BaseStageCardV2):
    """Tabbed ADetailer surface with explicit face and hand pass controls."""

    logger = logging.getLogger(__name__)

    MODEL_OPTIONS = ["face_yolov8n.pt", "face_yolov8s.pt", "mediapipe_face_full"]
    HAND_MODEL_OPTIONS = ["hand_yolov8n.pt", "hand_yolov8s.pt"]
    SAMPLER_OPTIONS = ["DPM++ 2M", "Euler a", "DDIM", "DPM++ SDE"]
    SCHEDULER_OPTIONS = [
        "inherit",
        "Automatic",
        "Karras",
        "Exponential",
        "Polyexponential",
        "SGM Uniform",
    ]
    MASK_FILTER_OPTIONS = list(MASK_FILTER_METHODS)
    MASK_MERGE_OPTIONS = list(MASK_MERGE_MODES)
    STAGE_MODEL_INHERIT = "Inherit Base Generation"

    def __init__(self, master: tk.Misc, *, theme: Any | None = None, **kwargs: Any) -> None:
        # Under Forge the generic detector lists are not installed: offer only the managed runtime's accepted set.
        forge_fallbacks = configured_adetailer_detector_fallbacks()
        self._forge_detectors = forge_fallbacks is not None
        self._available_face_detectors: list[str] | None = None
        self._available_hand_detectors: list[str] | None = None
        if forge_fallbacks is not None:
            self.MODEL_OPTIONS, self.HAND_MODEL_OPTIONS = (
                list(forge_fallbacks[0]),
                list(forge_fallbacks[1]),
            )
        self.stage_model_override_var = tk.StringVar(value="")
        self._mode = "single"
        self._editing_profile = "single"
        self._profiles: dict[str, dict[str, Any]] = {}
        self._mode_var = tk.StringVar(master, _MODE_LABELS[self._mode])
        self._profile_var = tk.StringVar(master, _MODE_LABELS[self._editing_profile])
        self._config_revision = tk.IntVar(master)
        self.loading_config = False
        self._resource_refreshing = False
        self._draft_store: UIStateStore | None = None
        self._draft_after: str | None = None
        self._draft_worker: ThreadPoolExecutor | None = None
        self._draft_write: tuple[Future[bool], dict[str, Any]] | None = None
        self._draft_pending: dict[str, Any] | None = None
        self._draft_saved: dict[str, Any] | None = None
        self._draft_read_error = ""
        self._expanded_prompts = tk.BooleanVar(master, False)

        # Fresh-configuration defaults. Loading a saved dict never applies them to a flag the dict omits.
        self.enable_face_pass_var = tk.BooleanVar(value=FRESH_PASS_DEFAULTS["enable_face_pass"])
        self._legacy_unsupported: dict[str, Any] = {}
        self._legacy_notes: list[str] = []
        self._detector_options_known = False
        self.model_var = tk.StringVar(value=self.MODEL_OPTIONS[0])
        self.face_model_var = self.model_var
        self.confidence_var = tk.DoubleVar(value=0.35)
        self.face_confidence_var = self.confidence_var
        self.mask_blur_var = tk.IntVar(value=6)
        self.face_mask_blur_var = self.mask_blur_var
        self.merge_var = tk.StringVar(value="None")
        self.face_merge_var = self.merge_var
        self.steps_var = tk.IntVar(value=14)
        self.face_steps_var = self.steps_var
        self.cfg_var = tk.DoubleVar(value=5.5)
        self.face_cfg_var = self.cfg_var
        self.sampler_var = tk.StringVar(value="DPM++ 2M Karras")
        self.face_sampler_var = self.sampler_var
        self.scheduler_var = tk.StringVar(value="inherit")
        self.face_scheduler_var = self.scheduler_var
        self.denoise_var = tk.DoubleVar(value=0.32)
        self.face_denoise_var = self.denoise_var
        self.prompt_var = tk.StringVar(value="")
        self.face_prompt_var = self.prompt_var
        self.negative_var = tk.StringVar(value="")
        self.face_negative_var = self.negative_var
        self.inpaint_masked_var = tk.BooleanVar(value=True)
        self.face_inpaint_masked_var = self.inpaint_masked_var
        self.inpaint_padding_var = tk.IntVar(value=32)
        self.face_padding_var = self.inpaint_padding_var
        self.use_inpaint_wh_var = tk.BooleanVar(value=False)
        self.face_use_inpaint_wh_var = self.use_inpaint_wh_var
        self.face_inpaint_width_var = tk.IntVar(value=1024)
        self.face_inpaint_height_var = tk.IntVar(value=1024)
        self.mask_filter_method_var = tk.StringVar(value="Area")
        self.face_mask_filter_method_var = self.mask_filter_method_var
        self.mask_k_largest_var = tk.IntVar(value=3)
        self.face_mask_k_largest_var = self.mask_k_largest_var
        self.mask_min_ratio_var = tk.DoubleVar(value=0.01)
        self.face_mask_min_ratio_var = self.mask_min_ratio_var
        self.mask_max_ratio_var = tk.DoubleVar(value=1.0)
        self.face_mask_max_ratio_var = self.mask_max_ratio_var
        self.dilate_erode_var = tk.IntVar(value=4)
        self.face_dilate_erode_var = self.dilate_erode_var

        self.enable_hands_pass_var = tk.BooleanVar(value=FRESH_PASS_DEFAULTS["enable_hands_pass"])
        self.hands_model_var = tk.StringVar(value=self.HAND_MODEL_OPTIONS[0])
        self.hands_confidence_var = tk.DoubleVar(value=0.30)
        self.hands_steps_var = tk.IntVar(value=12)
        self.hands_cfg_var = tk.DoubleVar(value=5.0)
        self.hands_sampler_var = tk.StringVar(value="DPM++ 2M Karras")
        self.hands_scheduler_var = tk.StringVar(value="inherit")
        self.hands_denoise_var = tk.DoubleVar(value=0.25)
        self.hands_prompt_var = tk.StringVar(
            value="well-formed fingers, natural knuckles, correct hand anatomy, sharp details"
        )
        self.hands_negative_var = tk.StringVar(
            value="extra fingers, fused fingers, broken fingers, deformed hands, missing fingers"
        )
        self.hands_inpaint_masked_var = tk.BooleanVar(value=True)
        self.hands_padding_var = tk.IntVar(value=16)
        self.hands_use_inpaint_wh_var = tk.BooleanVar(value=False)
        self.hands_inpaint_width_var = tk.IntVar(value=1024)
        self.hands_inpaint_height_var = tk.IntVar(value=1024)
        self.hands_mask_filter_method_var = tk.StringVar(value="Area")
        self.hands_mask_k_largest_var = tk.IntVar(value=6)
        self.hands_mask_min_ratio_var = tk.DoubleVar(value=0.003)
        self.hands_mask_max_ratio_var = tk.DoubleVar(value=1.0)
        self.hands_dilate_erode_var = tk.IntVar(value=6)
        self.hands_mask_blur_var = tk.IntVar(value=4)
        self.hands_merge_var = tk.StringVar(value="None")

        self._model_combo: ttk.Combobox | None = None
        self._detector_combo: ttk.Combobox | None = None
        self._sampler_combo: ttk.Combobox | None = None
        self._scheduler_combo: ttk.Combobox | None = None
        self._face_model_combo: ttk.Combobox | None = None
        self._hands_model_combo: ttk.Combobox | None = None
        self._stage_model_combo: ttk.Combobox | None = None
        self._face_sampler_combo: ttk.Combobox | None = None
        self._hand_sampler_combo: ttk.Combobox | None = None
        self._face_widgets: list[tk.Widget] = []
        self._hand_widgets: list[tk.Widget] = []
        self._face_prompt_widgets: list[tk.Text] = []
        self._hand_prompt_widgets: list[tk.Text] = []

        self.detector_var = self.model_var

        super().__init__(
            master,
            title="ADetailer Stage",
            description="Face and hand refinement with explicit pass-level controls.",
            theme=theme,
            **kwargs,
        )

        self.bind("<Destroy>", self._dispose_draft_worker, add="+")
        fresh = self._raw_config()
        fresh.update(
            face_mode="single",
            **{PROFILES_KEY: {mode: suggested_profile(mode) for mode in FACE_MASK_LIMITS}},
        )
        self.load_from_dict(fresh)
        for variable in self.watchable_vars():
            if variable is not self._config_revision:
                variable.trace_add("write", self._on_working_edit)

    def _build_body(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1, minsize=get_stage_card_min_width())

        helper = ttk.Label(
            parent,
            text="Edits are restored as your working draft. Use Apply to PromptPack to save pack settings. Queued jobs keep their compiled settings.",
            style=BODY_LABEL_STYLE,
            wraplength=460,
            justify="left",
        )
        helper.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        overall = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        overall.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        configure_grid_columns(overall, get_two_pair_form_column_specs())
        self._overall_frame = overall

        stage_model_label = ttk.Label(overall, text="Stage Model Override", style=BODY_LABEL_STYLE)
        stage_model_label.grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
        self._stage_model_combo = self._build_combo(
            overall,
            self.stage_model_override_var,
            [self.STAGE_MODEL_INHERIT],
        )
        self._stage_model_combo.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=2)
        self._attach_setting_help(
            "stage_model_override",
            ADETAILER_STAGE_HELP["stage_model_override"],
            stage_model_label,
            self._stage_model_combo,
        )

        face_pass_label = ttk.Label(overall, text="Face Pass", style=BODY_LABEL_STYLE)
        face_pass_label.grid(row=1, column=0, sticky="w", padx=(0, 4), pady=2)
        face_pass_check = ttk.Checkbutton(
            overall,
            text="Enabled",
            variable=self.enable_face_pass_var,
            style=DARK_CHECKBUTTON_STYLE,
            command=self._sync_pass_states,
        )
        face_pass_check.grid(row=1, column=1, sticky="w", pady=2)
        self._attach_setting_help(
            "face_pass_enabled",
            ADETAILER_STAGE_HELP["face_pass_enabled"],
            face_pass_label,
            face_pass_check,
        )

        hand_pass_label = ttk.Label(overall, text="Hand Pass", style=BODY_LABEL_STYLE)
        hand_pass_label.grid(row=1, column=2, sticky="w", padx=(0, 4), pady=2)
        hand_pass_check = ttk.Checkbutton(
            overall,
            text="Enabled",
            variable=self.enable_hands_pass_var,
            style=DARK_CHECKBUTTON_STYLE,
            command=self._sync_pass_states,
        )
        hand_pass_check.grid(row=1, column=3, sticky="w", pady=2)
        self._hand_pass_label = hand_pass_label
        self._hand_pass_check = hand_pass_check
        self._attach_setting_help(
            "hand_pass_enabled",
            ADETAILER_STAGE_HELP["hand_pass_enabled"],
            hand_pass_label,
            hand_pass_check,
        )

        summary = ttk.Label(
            overall, text="", style=BODY_LABEL_STYLE, wraplength=460, justify="left"
        )
        summary.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self._effective_summary_label = summary

        mode_label = ttk.Label(overall, text="Face Handling", style=BODY_LABEL_STYLE)
        mode_label.grid(row=3, column=0, sticky="w", pady=2)
        self._mode_combo = self._build_combo(overall, self._mode_var, ())
        self._mode_combo.grid(row=3, column=1, columnspan=3, sticky="ew", pady=2)
        self._mode_combo.bind("<<ComboboxSelected>>", self._select_mode)
        self._attach_setting_help(
            "face_mode",
            "Single Face retains one eligible region without identifying the intended subject. "
            "Multiple Faces keeps eligible regions separate and may still introduce identity drift. "
            "Auto selects a profile for each compiled prompt and falls back to Single Face when uncertain.",
            mode_label,
            self._mode_combo,
        )
        self._profile_label = ttk.Label(overall, text="Edit Profile", style=BODY_LABEL_STYLE)
        self._profile_label.grid(row=4, column=0, sticky="w", pady=2)
        self._profile_combo = self._build_combo(
            overall, self._profile_var, (_MODE_LABELS[mode] for mode in FACE_MASK_LIMITS)
        )
        self._profile_combo.grid(row=4, column=1, columnspan=3, sticky="ew", pady=2)
        self._profile_combo.bind("<<ComboboxSelected>>", self._select_profile)

        actions = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        actions.grid(row=2, column=0, sticky="ew", pady=4)
        self._reset_profile_button = ttk.Button(
            actions, text="Reset to suggested", command=self._reset_profile
        )
        self._reset_profile_button.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._save_default_button = ttk.Button(
            actions, text="Save ADetailer as App Default", state="disabled"
        )
        self._save_default_button.grid(row=1, column=0, sticky="w", pady=2)
        self._draft_status = ttk.Label(
            actions, style=BODY_LABEL_STYLE, wraplength=325, justify="left"
        )
        self._draft_status.grid(row=2, column=0, sticky="w")
        self._default_status = ttk.Label(
            actions, style=BODY_LABEL_STYLE, wraplength=325, justify="left"
        )
        self._default_status.grid(row=3, column=0, sticky="w")

        notebook = ttk.Notebook(parent)
        notebook.grid(row=3, column=0, sticky="nsew")
        self._notebook = notebook

        face_tab = ttk.Frame(notebook, style=SURFACE_FRAME_STYLE)
        hand_tab = ttk.Frame(notebook, style=SURFACE_FRAME_STYLE)
        prompt_tab = ttk.Frame(notebook, style=SURFACE_FRAME_STYLE)
        for tab in (face_tab, hand_tab, prompt_tab):
            configure_grid_columns(tab, get_single_pair_form_column_specs())
        self._face_tab = face_tab
        self._hand_tab = hand_tab
        self._prompt_tab = prompt_tab

        notebook.add(face_tab, text="Face Pass")
        notebook.add(hand_tab, text="Hand Pass")
        notebook.add(prompt_tab, text="Prompts")

        self._build_face_tab(face_tab)
        self._build_hand_tab(hand_tab)
        self._build_prompt_tab(prompt_tab)
        for variable in (
            self.face_model_var,
            self.hands_model_var,
            self.face_mask_filter_method_var,
            self.hands_mask_filter_method_var,
            self.face_merge_var,
            self.hands_merge_var,
        ):
            variable.trace_add("write", lambda *_: self._refresh_effective_summary())
        self._sync_pass_states()

    def set_compact_layout(self, compact: bool) -> None:
        """Stack the Hand Pass toggle under the Face Pass one while the Pipeline is compact (PR-GUI-100).

        The Face/Hand pair side by side has an irreducible natural width; reflowing it keeps both toggles unclipped.
        Same widgets and variables, only their grid cells change, and normal mode restores the original cells.
        """
        if compact:
            self._hand_pass_label.grid_configure(row=2, column=0)
            self._hand_pass_check.grid_configure(row=2, column=1)
        else:
            self._hand_pass_label.grid_configure(row=1, column=2)
            self._hand_pass_check.grid_configure(row=1, column=3)

    def _build_face_tab(self, parent: ttk.Frame) -> None:
        row = 0
        self._face_model_combo = self._add_combo_row(
            parent,
            row,
            "Detector Model",
            self.face_model_var,
            self.MODEL_OPTIONS,
            help_key="detector_model",
        )
        self._model_combo = self._face_model_combo
        self._detector_combo = self._face_model_combo
        self._face_widgets.append(self._face_model_combo)
        row += 1
        self._face_sampler_combo = self._add_combo_row(
            parent,
            row,
            "Sampler",
            self.face_sampler_var,
            self.SAMPLER_OPTIONS,
            help_key="sampler",
        )
        self._sampler_combo = self._face_sampler_combo
        self._face_widgets.append(self._face_sampler_combo)
        row += 1
        self._scheduler_combo = self._add_combo_row(
            parent,
            row,
            "Scheduler",
            self.face_scheduler_var,
            self.SCHEDULER_OPTIONS,
            help_key="scheduler",
        )
        self._face_widgets.append(self._scheduler_combo)
        row += 1

        for label, variable, start, end, increment, help_key in (
            ("Confidence", self.face_confidence_var, 0.0, 1.0, 0.01, "confidence"),
            ("Steps", self.face_steps_var, 1, 150, 1, "steps"),
            ("CFG", self.face_cfg_var, 1.0, 24.0, 0.1, "cfg"),
            ("Denoising", self.face_denoise_var, 0.0, 1.0, 0.01, "denoising"),
            ("Padding", self.face_padding_var, 0, 256, 1, "padding"),
            ("Mask Blur", self.face_mask_blur_var, 0, 64, 1, "mask_blur"),
            ("Dilate / Erode", self.face_dilate_erode_var, -64, 64, 1, "dilate_erode"),
            ("Retained Masks (Top-K)", self.face_mask_k_largest_var, 0, 16, 1, "mask_max_k"),
            ("Mask Min Ratio", self.face_mask_min_ratio_var, 0.0, 1.0, 0.001, "mask_min_ratio"),
            ("Mask Max Ratio", self.face_mask_max_ratio_var, 0.0, 1.0, 0.001, "mask_max_ratio"),
            ("Inpaint Width", self.face_inpaint_width_var, 64, 4096, 64, "inpaint_width"),
            ("Inpaint Height", self.face_inpaint_height_var, 64, 4096, 64, "inpaint_height"),
        ):
            widget = self._add_spin_row(
                parent,
                row,
                label,
                variable,
                start,
                end,
                increment,
                help_key=help_key,
            )
            if variable is self.face_mask_k_largest_var:
                self._face_mask_spin = widget
            self._face_widgets.append(widget)
            row += 1

        filter_combo = self._add_combo_row(
            parent,
            row,
            "Mask Filter",
            self.face_mask_filter_method_var,
            self.MASK_FILTER_OPTIONS,
            help_key="mask_filter",
        )
        self._face_widgets.append(filter_combo)
        row += 1
        merge_combo = self._add_combo_row(
            parent,
            row,
            "Mask Merge",
            self.face_merge_var,
            self.MASK_MERGE_OPTIONS,
            help_key="mask_merge",
        )
        self._face_merge_combo = merge_combo
        self._face_widgets.append(merge_combo)
        row += 1

        inpaint_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        inpaint_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        masked = ttk.Checkbutton(
            inpaint_frame,
            text="Only masked",
            variable=self.face_inpaint_masked_var,
            style=DARK_CHECKBUTTON_STYLE,
        )
        masked.pack(side="left", padx=(0, 8))
        self._attach_setting_help("only_masked", ADETAILER_STAGE_HELP["only_masked"], masked)
        inpaint_wh = ttk.Checkbutton(
            inpaint_frame,
            text="Use inpaint width/height",
            variable=self.face_use_inpaint_wh_var,
            style=DARK_CHECKBUTTON_STYLE,
            command=self._sync_pass_states,
        )
        inpaint_wh.pack(side="left")
        self._attach_setting_help(
            "use_inpaint_wh", ADETAILER_STAGE_HELP["use_inpaint_wh"], inpaint_wh
        )
        self._face_widgets.extend([masked, inpaint_wh])

    def _build_hand_tab(self, parent: ttk.Frame) -> None:
        row = 0
        self._hands_model_combo = self._add_combo_row(
            parent,
            row,
            "Detector Model",
            self.hands_model_var,
            self.HAND_MODEL_OPTIONS,
            help_key="detector_model",
        )
        self._hand_widgets.append(self._hands_model_combo)
        row += 1
        self._hand_sampler_combo = self._add_combo_row(
            parent,
            row,
            "Sampler",
            self.hands_sampler_var,
            self.SAMPLER_OPTIONS,
            help_key="sampler",
        )
        self._hand_widgets.append(self._hand_sampler_combo)
        row += 1
        hand_scheduler = self._add_combo_row(
            parent,
            row,
            "Scheduler",
            self.hands_scheduler_var,
            self.SCHEDULER_OPTIONS,
            help_key="scheduler",
        )
        self._hand_widgets.append(hand_scheduler)
        row += 1

        for label, variable, start, end, increment, help_key in (
            ("Confidence", self.hands_confidence_var, 0.0, 1.0, 0.01, "confidence"),
            ("Steps", self.hands_steps_var, 1, 150, 1, "steps"),
            ("CFG", self.hands_cfg_var, 1.0, 24.0, 0.1, "cfg"),
            ("Denoising", self.hands_denoise_var, 0.0, 1.0, 0.01, "denoising"),
            ("Padding", self.hands_padding_var, 0, 256, 1, "padding"),
            ("Mask Blur", self.hands_mask_blur_var, 0, 64, 1, "mask_blur"),
            ("Dilate / Erode", self.hands_dilate_erode_var, -64, 64, 1, "dilate_erode"),
            ("Retained Masks (Top-K)", self.hands_mask_k_largest_var, 0, 16, 1, "mask_max_k"),
            ("Mask Min Ratio", self.hands_mask_min_ratio_var, 0.0, 1.0, 0.001, "mask_min_ratio"),
            ("Mask Max Ratio", self.hands_mask_max_ratio_var, 0.0, 1.0, 0.001, "mask_max_ratio"),
            ("Inpaint Width", self.hands_inpaint_width_var, 64, 4096, 64, "inpaint_width"),
            ("Inpaint Height", self.hands_inpaint_height_var, 64, 4096, 64, "inpaint_height"),
        ):
            widget = self._add_spin_row(
                parent,
                row,
                label,
                variable,
                start,
                end,
                increment,
                help_key=help_key,
            )
            self._hand_widgets.append(widget)
            row += 1

        filter_combo = self._add_combo_row(
            parent,
            row,
            "Mask Filter",
            self.hands_mask_filter_method_var,
            self.MASK_FILTER_OPTIONS,
            help_key="mask_filter",
        )
        self._hand_widgets.append(filter_combo)
        row += 1
        merge_combo = self._add_combo_row(
            parent,
            row,
            "Mask Merge",
            self.hands_merge_var,
            self.MASK_MERGE_OPTIONS,
            help_key="mask_merge",
        )
        self._hand_widgets.append(merge_combo)
        row += 1

        inpaint_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        inpaint_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        hand_masked = ttk.Checkbutton(
            inpaint_frame,
            text="Only masked",
            variable=self.hands_inpaint_masked_var,
            style=DARK_CHECKBUTTON_STYLE,
        )
        hand_masked.pack(side="left", padx=(0, 8))
        self._attach_setting_help("only_masked", ADETAILER_STAGE_HELP["only_masked"], hand_masked)
        inpaint_wh = ttk.Checkbutton(
            inpaint_frame,
            text="Use inpaint width/height",
            variable=self.hands_use_inpaint_wh_var,
            style=DARK_CHECKBUTTON_STYLE,
            command=self._sync_pass_states,
        )
        inpaint_wh.pack(side="left")
        self._attach_setting_help(
            "use_inpaint_wh", ADETAILER_STAGE_HELP["use_inpaint_wh"], inpaint_wh
        )
        self._hand_widgets.extend([hand_masked, inpaint_wh])

    def _build_prompt_tab(self, parent: ttk.Frame) -> None:
        expand = ttk.Checkbutton(
            parent,
            text="Expand prompt editors",
            variable=self._expanded_prompts,
            command=self._resize_prompt_editors,
            style=DARK_CHECKBUTTON_STYLE,
        )
        expand.grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        for row, title, variables, widgets in (
            (
                1,
                "Face Pass Prompts",
                (self.face_prompt_var, self.face_negative_var),
                self._face_prompt_widgets,
            ),
            (
                2,
                "Hand Pass Prompts",
                (self.hands_prompt_var, self.hands_negative_var),
                self._hand_prompt_widgets,
            ),
        ):
            frame = ttk.LabelFrame(parent, text=title, style="Dark.TLabelframe")
            frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
            frame.columnconfigure(0, weight=1)
            for index, (label, help_key, variable) in enumerate(
                zip(
                    ("Positive prompt", "Negative prompt"),
                    ("prompt", "negative"),
                    variables,
                    strict=True,
                )
            ):
                editor_label = ttk.Label(frame, text=label, style=BODY_LABEL_STYLE)
                editor_label.grid(row=2 * index, column=0, sticky="w", pady=(4, 0))
                editor = self._build_prompt_editor(frame, 2 * index + 1, variable)
                editor_label.bind("<Button-1>", partial(self._focus_prompt_editor, editor))
                self._attach_setting_help(
                    help_key, ADETAILER_STAGE_HELP[help_key], editor_label, editor
                )
                widgets.append(editor)
            if row == 1:
                self._face_prompt_frame = frame
            else:
                self._hand_prompt_frame = frame

    @staticmethod
    def _focus_prompt_editor(editor: tk.Text, _event: tk.Event) -> None:
        editor.focus_set()

    def _build_prompt_editor(
        self, frame: ttk.LabelFrame, row: int, variable: tk.StringVar
    ) -> tk.Text:
        colors = TOKENS.colors
        editor = tk.Text(
            frame,
            width=1,
            height=4,
            wrap="word",
            undo=True,
            takefocus=True,
            bg=colors.surface_secondary,
            fg=colors.text_primary,
            insertbackground=colors.accent_primary,
            selectbackground=colors.accent_primary,
            selectforeground=colors.surface_primary,
            highlightbackground=colors.surface_secondary,
            highlightcolor=colors.accent_primary,
            highlightthickness=1,
            borderwidth=0,
            padx=4,
            pady=3,
        )
        editor.grid(row=row, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=editor.yview)
        scrollbar.grid(row=row, column=1, sticky="ns")
        editor.configure(yscrollcommand=scrollbar.set)

        def load_text(*_args: Any) -> None:
            value = variable.get()
            if value == editor.get("1.0", "end-1c"):
                return
            state = editor.cget("state")
            editor.configure(state="normal")
            editor.replace("1.0", "end-1c", value)
            editor.edit_reset()
            editor.edit_modified(False)
            editor.configure(state=state)

        def edited(_event: tk.Event) -> None:
            if editor.edit_modified():
                editor.edit_modified(False)
                value = editor.get("1.0", "end-1c")
                if variable.get() != value:
                    variable.set(value)

        def traverse(forward: bool) -> str:
            target = editor.tk_focusNext() if forward else editor.tk_focusPrev()
            if target is not None:
                target.focus_set()
            return "break"

        trace_id = variable.trace_add("write", load_text)
        editor.bind("<Destroy>", lambda _event: variable.trace_remove("write", trace_id))
        editor.bind("<<Modified>>", edited)
        editor.bind("<Tab>", lambda _event: traverse(True))
        editor.bind("<Shift-Tab>", lambda _event: traverse(False))
        load_text()
        return editor

    def _resize_prompt_editors(self) -> None:
        height = 10 if self._expanded_prompts.get() else 4
        for editor in (*self._face_prompt_widgets, *self._hand_prompt_widgets):
            editor.configure(height=height)

    def _add_combo_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        options: Iterable[str],
        *,
        help_key: str | None = None,
    ) -> ttk.Combobox:
        label_widget = ttk.Label(parent, text=label, style=BODY_LABEL_STYLE)
        label_widget.grid(row=row, column=0, sticky="w", pady=2)
        combo = self._build_combo(parent, variable, options)
        combo.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        if help_key:
            self._attach_setting_help(help_key, ADETAILER_STAGE_HELP[help_key], label_widget, combo)
        return combo

    def _add_spin_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.Variable,
        minimum: float,
        maximum: float,
        increment: float,
        *,
        help_key: str | None = None,
    ) -> ttk.Spinbox:
        label_widget = ttk.Label(parent, text=label, style=BODY_LABEL_STYLE)
        label_widget.grid(row=row, column=0, sticky="w", pady=2)
        spin = ttk.Spinbox(
            parent,
            from_=minimum,
            to=maximum,
            increment=increment,
            textvariable=variable,
            width=10,
            style=DARK_SPINBOX_STYLE,
        )
        spin.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        if help_key:
            self._attach_setting_help(help_key, ADETAILER_STAGE_HELP[help_key], label_widget, spin)
        return spin

    def _build_combo(
        self, parent: ttk.Frame, variable: tk.StringVar, values: Iterable[str]
    ) -> ttk.Combobox:
        return ttk.Combobox(
            parent,
            textvariable=variable,
            values=tuple(values),
            state="readonly",
            style=DARK_COMBOBOX_STYLE,
        )

    def _sync_pass_states(self) -> None:
        self._set_widgets_enabled(self._face_widgets, bool(self.enable_face_pass_var.get()))
        self._set_widgets_enabled(self._face_prompt_widgets, bool(self.enable_face_pass_var.get()))
        self._set_widgets_enabled(self._hand_widgets, bool(self.enable_hands_pass_var.get()))
        self._set_widgets_enabled(self._hand_prompt_widgets, bool(self.enable_hands_pass_var.get()))
        if self.enable_face_pass_var.get() and self._mode in FACE_MODES:
            self._face_mask_spin.configure(state="disabled")
            self._face_merge_combo.configure(state="disabled")
        self._refresh_effective_summary()

    def _pass_argument_view(self, hands: bool) -> dict[str, Any]:
        """The few displayed values the pinned schema can reject (for the projection only; not a second authority)."""
        prefix = "hands" if hands else "face"
        try:
            return {
                "ad_mask_filter_method": getattr(self, f"{prefix}_mask_filter_method_var").get(),
                "ad_mask_merge_invert": getattr(self, f"{prefix}_merge_var").get(),
                "ad_cfg_scale": getattr(self, f"{prefix}_cfg_var").get(),
                "ad_steps": getattr(self, f"{prefix}_steps_var").get(),
                "ad_confidence": getattr(self, f"{prefix}_confidence_var").get(),
            }
        except (tk.TclError, ValueError):
            return {}

    def effective_summary(self) -> str:
        """Which passes will run and with which detector, as projected from the card's own variables."""
        lines: list[str] = []
        if self._mode == "auto":
            lines.append(
                f"Auto resolves each prompt at compile time. Editing {_MODE_LABELS[self._editing_profile]}."
            )
        try:
            face_k = self.face_mask_k_largest_var.get()
            hand_k = self.hands_mask_k_largest_var.get()
            face_limit = str(face_k) if face_k else "all eligible"
            hand_limit = str(hand_k) if hand_k else "all eligible"
            lines.append(
                f"Retained masks for displayed settings: face {face_limit}, hand {hand_limit}."
            )
        except tk.TclError:
            pass
        if not (self.enable_face_pass_var.get() or self.enable_hands_pass_var.get()):
            lines.append(
                "No correction will run: both passes are off, so ADetailer sends no request."
            )
        for label, enabled_var, model_var, role, available, hands in (
            (
                "Face",
                self.enable_face_pass_var,
                self.face_model_var,
                "face",
                self._available_face_detectors,
                False,
            ),
            (
                "Hand",
                self.enable_hands_pass_var,
                self.hands_model_var,
                "hand",
                self._available_hand_detectors,
                True,
            ),
        ):
            if not enabled_var.get():
                lines.append(f"{label} pass: off")
                continue
            name = str(model_var.get() or "")
            status = detector_status(name, available, role)
            note = {
                "unavailable": " - not installed; it is kept, not substituted",
                "wrong_role": f" - not a {role} detector",
            }.get(status, "")
            lines.append(f"{label} pass: on, detector {name or '(none)'}{note}")
            for issue in schema_issues(self._pass_argument_view(hands)):
                lines.append(f"  ! {label} pass setting the extension would reject: {issue}")
        lines.extend(f"Note: {note}" for note in self._legacy_notes)
        return "\n".join(lines)

    def _refresh_effective_summary(self) -> None:
        label = getattr(self, "_effective_summary_label", None)
        if label is None:
            return
        try:
            label.configure(text=self.effective_summary())
        except tk.TclError:
            pass

    def _set_widgets_enabled(self, widgets: Iterable[tk.Widget], enabled: bool) -> None:
        for widget in widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="readonly" if enabled else "disabled")
                elif isinstance(widget, ttk.Entry):
                    widget.configure(state="normal" if enabled else "disabled")
                else:
                    widget.configure(state="normal" if enabled else "disabled")
            except Exception:
                pass

    def _supported_filter(self, value: object, label: str) -> str:
        """Legacy GUI values (largest/all) were never accepted by the extension, which dropped the pass silently.

        Loading one shows the schema's ``Area`` instead and says so in the projection; nothing else is reinterpreted.
        """
        text = str(value or "Area")
        if text in MASK_FILTER_METHODS:
            return text
        self._legacy_notes.append(
            f"{label} mask filter {text!r} was never supported by the extension; shown as 'Area'"
        )
        return "Area"

    @classmethod
    def _normalize_scheduler_value(cls, value: object) -> str:
        raw = str(value or "").strip()
        if not raw or raw in {"Use same scheduler", "Use sampler default"}:
            return "inherit"
        for option in cls.SCHEDULER_OPTIONS:
            if raw.lower() == option.lower():
                return option
        return "inherit"

    @classmethod
    def _normalize_stage_model_override(cls, value: object) -> str:
        raw = str(value or "").strip()
        if not raw or raw == cls.STAGE_MODEL_INHERIT:
            return ""
        return raw

    def load_from_dict(self, cfg: dict[str, Any] | None) -> None:
        if not cfg:
            return
        mode = cfg.get("face_mode")
        self._mode = mode if mode in FACE_MODES else "legacy"
        self._editing_profile = mode if mode in FACE_MASK_LIMITS else "single"
        profiles = cfg.get(PROFILES_KEY)
        self._profiles = (
            {
                name: profile_values(values)
                for name, values in profiles.items()
                if name in FACE_MASK_LIMITS and isinstance(values, dict)
            }
            if isinstance(profiles, dict)
            else {}
        )
        if self._mode in FACE_MODES:
            for name in FACE_MASK_LIMITS:
                initial = profile_values(cfg) if name == self._editing_profile else {}
                self._profiles[name] = {
                    **suggested_profile(name),
                    **initial,
                    **self._profiles.get(name, {}),
                }
            cfg = apply_profile(cfg, self._editing_profile, self._profiles[self._editing_profile])
        self._load_controls(cfg)

    def _sync_mode_controls(self) -> None:
        modes = (*FACE_MODES, "legacy") if self._mode == "legacy" else FACE_MODES
        self._mode_combo.configure(values=tuple(_MODE_LABELS[mode] for mode in modes))
        self._mode_var.set(_MODE_LABELS[self._mode])
        self._profile_var.set(_MODE_LABELS[self._editing_profile])
        for widget in (self._profile_label, self._profile_combo):
            if self._mode == "auto":
                widget.grid()
            else:
                widget.grid_remove()
        self._reset_profile_button.configure(
            state="disabled" if self._mode == "legacy" else "normal"
        )
        self._sync_pass_states()

    def _select_mode(self, _event: tk.Event) -> None:
        target = next(mode for mode, label in _MODE_LABELS.items() if label == self._mode_var.get())
        if target != self._mode:
            self._switch_profile(target, target if target in FACE_MASK_LIMITS else "single")

    def _select_profile(self, _event: tk.Event) -> None:
        target = next(
            mode for mode in FACE_MASK_LIMITS if _MODE_LABELS[mode] == self._profile_var.get()
        )
        if target != self._editing_profile:
            self._switch_profile("auto", target)

    def _switch_profile(self, mode: str, profile: str, *, reset: bool = False) -> None:
        try:
            config = self._raw_config()
        except tk.TclError:
            self._sync_mode_controls()
            self._draft_status.configure(
                text="Finish editing the current numeric settings before switching profiles."
            )
            return
        current = self._editing_profile if self._mode != "legacy" else profile
        self._profiles[current] = profile_values(config)
        for name in FACE_MASK_LIMITS:
            if name not in self._profiles:
                self._profiles[name] = suggested_profile(name)
        if reset:
            self._profiles[profile] = suggested_profile(profile)
        self._mode, self._editing_profile = mode, profile
        self._load_controls(apply_profile(config, profile, self._profiles[profile]))
        self._on_working_edit()

    def _reset_profile(self) -> None:
        if messagebox.askokcancel(
            "Reset ADetailer profile",
            f"Replace the prompts and refinement settings for {_MODE_LABELS[self._editing_profile]} "
            "with the suggested values?",
            parent=self,
        ):
            self._switch_profile(self._mode, self._editing_profile, reset=True)

    def set_default_saver(self, save: Callable[[dict[str, Any]], bool]) -> None:
        def save_default() -> None:
            try:
                saved = save(self.to_config_dict())
            except (OSError, ValueError, tk.TclError):
                saved = False
            self._default_status.configure(
                text=(
                    "Application default saved for new configurations."
                    if saved
                    else "Could not save the application default. Check settings.json and file permissions."
                )
            )

        self._save_default_button.configure(command=save_default, state="normal")

    def restore_working_draft(self, store: UIStateStore) -> None:
        self._draft_store = store
        original = self.to_config_dict()
        try:
            state = store.load_state(strict=True) or {}
            if _DRAFT_KEY in state:
                draft = state[_DRAFT_KEY]
                if not isinstance(draft, dict) or not draft:
                    raise ValueError("invalid ADetailer working draft")
                self.load_from_dict(draft)
                self._draft_status.configure(text="Working draft restored.")
            self._draft_saved = self.to_config_dict()
        except (OSError, ValueError, TypeError, tk.TclError):
            self.load_from_dict(original)
            self._draft_read_error = (
                "Could not read the saved ADetailer draft. Check ui_state.json before replacing it."
            )
            self._draft_status.configure(text=self._draft_read_error)

    def _on_working_edit(self, *_args: Any) -> None:
        self._refresh_effective_summary()
        if self.loading_config or self._resource_refreshing or self._draft_store is None:
            return
        try:
            snapshot = self.to_config_dict()
        except (ValueError, tk.TclError):
            return  # Keep the most recent valid settings while a numeric control is being edited.
        if snapshot == self._draft_saved and self._draft_pending is None:
            return
        self._draft_pending = snapshot
        self._draft_status.configure(text=self._draft_read_error or "Working draft modified.")
        if self._draft_after is None and self._draft_write is None and not self._draft_read_error:
            self._draft_after = self.after(_DRAFT_DELAY_MS, self._start_draft_write)

    def _start_draft_write(self) -> None:
        self._draft_after = None
        store, snapshot = self._draft_store, self._draft_pending
        if store is None or snapshot is None:
            return
        if self._draft_worker is None:
            self._draft_worker = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="adetailer-draft"
            )
        future = self._draft_worker.submit(store.update_state, {_DRAFT_KEY: snapshot})
        self._draft_write = (future, snapshot)
        self._draft_after = self.after(50, self._poll_draft_write)

    def _poll_draft_write(self) -> None:
        self._draft_after = None
        if self._draft_write is None:
            return
        future, snapshot = self._draft_write
        if not future.done():
            self._draft_after = self.after(50, self._poll_draft_write)
            return
        self._finish_draft_write(future.result(), snapshot)
        if self._draft_pending is not None and self._draft_pending != snapshot:
            self._draft_after = self.after(_DRAFT_DELAY_MS, self._start_draft_write)

    def _finish_draft_write(self, saved: bool, snapshot: dict[str, Any]) -> None:
        self._draft_write = None
        if saved:
            self._draft_saved = snapshot
            if self._draft_pending == snapshot:
                self._draft_pending = None
        self._draft_status.configure(
            text=(
                ("Working draft modified." if self._draft_pending else "Working draft saved.")
                if saved
                else "Could not save the working draft. Check ui_state.json and file permissions."
            )
        )

    def _dispose_draft_worker(self, _event: tk.Event) -> None:
        if self._draft_after is not None:
            self.after_cancel(self._draft_after)
            self._draft_after = None
        if self._draft_worker is not None:
            self._draft_worker.shutdown(wait=False)

    def flush_working_draft(self) -> bool:
        if self._draft_after is not None:
            self.after_cancel(self._draft_after)
            self._draft_after = None
        if self._draft_write is not None:
            future, in_flight = self._draft_write
            self._finish_draft_write(future.result(), in_flight)
        store, snapshot = self._draft_store, self._draft_pending
        if snapshot is None or store is None:
            return True
        if self._draft_read_error:
            return False
        saved = store.update_state({_DRAFT_KEY: snapshot})
        self._finish_draft_write(saved, snapshot)
        return saved

    def _load_controls(self, cfg: dict[str, Any]) -> None:
        self.loading_config = True
        try:
            self._load_fields(cfg)
            self._sync_mode_controls()
        finally:
            self.loading_config = False
        self._config_revision.set(self._config_revision.get() + 1)

    def _load_fields(self, cfg: dict[str, Any]) -> None:
        self._legacy_notes = []
        self.stage_model_override_var.set(
            self._normalize_stage_model_override(
                cfg.get("adetailer_checkpoint_model") or cfg.get("sd_model_checkpoint")
            )
            or self.STAGE_MODEL_INHERIT
        )
        self.enable_face_pass_var.set(bool(cfg.get("enable_face_pass", True)))
        self.face_model_var.set(
            str(cfg.get("adetailer_model") or cfg.get("face_model") or self.MODEL_OPTIONS[0])
        )
        self.face_confidence_var.set(
            float(cfg.get("adetailer_confidence", cfg.get("ad_confidence", 0.35)))
        )
        self._legacy_unsupported = {
            key: cfg[key] for key in sorted(UNSUPPORTED_CONFIG_KEYS) if key in cfg
        }  # kept so saved data round-trips; never shown as effective, never transmitted by the executor
        self.face_mask_blur_var.set(int(cfg.get("mask_blur", cfg.get("ad_mask_blur", 6))))
        self.face_merge_var.set(
            str(cfg.get("ad_mask_merge_invert") or cfg.get("mask_merge_mode") or "None")
        )
        self.face_steps_var.set(int(cfg.get("adetailer_steps", cfg.get("ad_steps", 14))))
        self.face_cfg_var.set(float(cfg.get("adetailer_cfg", cfg.get("ad_cfg_scale", 5.5))))
        self.face_sampler_var.set(
            str(cfg.get("adetailer_sampler") or cfg.get("ad_sampler") or "DPM++ 2M Karras")
        )
        self.face_scheduler_var.set(
            self._normalize_scheduler_value(cfg.get("adetailer_scheduler") or cfg.get("scheduler"))
        )
        self.face_denoise_var.set(
            float(cfg.get("adetailer_denoise", cfg.get("ad_denoising_strength", 0.32)))
        )
        self.face_prompt_var.set(str(cfg.get("adetailer_prompt", cfg.get("ad_prompt", "")) or ""))
        self.face_negative_var.set(
            str(cfg.get("adetailer_negative_prompt", cfg.get("ad_negative_prompt", "")) or "")
        )
        self.face_inpaint_masked_var.set(bool(cfg.get("ad_inpaint_only_masked", True)))
        self.face_padding_var.set(
            int(cfg.get("ad_inpaint_only_masked_padding", cfg.get("adetailer_padding", 32)))
        )
        self.face_use_inpaint_wh_var.set(bool(cfg.get("ad_use_inpaint_width_height", False)))
        self.face_inpaint_width_var.set(int(cfg.get("ad_inpaint_width", 1024)))
        self.face_inpaint_height_var.set(int(cfg.get("ad_inpaint_height", 1024)))
        self.face_mask_filter_method_var.set(
            self._supported_filter(
                cfg.get("ad_mask_filter_method") or cfg.get("mask_filter_method") or "Area", "Face"
            )
        )
        self.face_mask_k_largest_var.set(
            int(cfg.get("ad_mask_k_largest", cfg.get("mask_k_largest", 3)))
        )
        self.face_mask_min_ratio_var.set(
            float(cfg.get("ad_mask_min_ratio", cfg.get("mask_min_ratio", 0.01)))
        )
        self.face_mask_max_ratio_var.set(
            float(cfg.get("ad_mask_max_ratio", cfg.get("mask_max_ratio", 1.0)))
        )
        self.face_dilate_erode_var.set(
            int(cfg.get("ad_dilate_erode", cfg.get("mask_dilate_erode", 4)))
        )

        # A saved configuration that omits the flag keeps its historical meaning (hand pass off); only an
        # explicit value is honored. The fresh-configuration default lives in the variable's initial value.
        self.enable_hands_pass_var.set(
            bool(cfg.get("enable_hands_pass", cfg.get("ad_hands_enabled", False)))
        )
        self.hands_model_var.set(
            str(
                cfg.get("adetailer_hands_model")
                or cfg.get("hands_model")
                or self.HAND_MODEL_OPTIONS[0]
            )
        )
        self.hands_confidence_var.set(float(cfg.get("adetailer_hands_confidence", 0.30)))
        self.hands_steps_var.set(int(cfg.get("adetailer_hands_steps", 12)))
        self.hands_cfg_var.set(float(cfg.get("adetailer_hands_cfg", 5.0)))
        self.hands_sampler_var.set(str(cfg.get("adetailer_hands_sampler") or "DPM++ 2M Karras"))
        self.hands_scheduler_var.set(
            self._normalize_scheduler_value(cfg.get("adetailer_hands_scheduler"))
        )
        self.hands_denoise_var.set(float(cfg.get("adetailer_hands_denoise", 0.25)))
        self.hands_prompt_var.set(
            str(
                cfg.get(
                    "adetailer_hands_prompt",
                    "well-formed fingers, natural knuckles, correct hand anatomy, sharp details",
                )
            )
        )
        self.hands_negative_var.set(
            str(
                cfg.get(
                    "adetailer_hands_negative_prompt",
                    "extra fingers, fused fingers, broken fingers, deformed hands, missing fingers",
                )
            )
        )
        self.hands_inpaint_masked_var.set(bool(cfg.get("ad_hands_inpaint_only_masked", True)))
        self.hands_padding_var.set(int(cfg.get("ad_hands_padding", cfg.get("hands_padding", 16))))
        self.hands_use_inpaint_wh_var.set(bool(cfg.get("ad_hands_use_inpaint_width_height", False)))
        self.hands_inpaint_width_var.set(int(cfg.get("ad_hands_inpaint_width", 1024)))
        self.hands_inpaint_height_var.set(int(cfg.get("ad_hands_inpaint_height", 1024)))
        self.hands_mask_filter_method_var.set(
            self._supported_filter(cfg.get("ad_hands_mask_filter_method", "Area"), "Hand")
        )
        self.hands_mask_k_largest_var.set(int(cfg.get("ad_hands_mask_k", 6)))
        self.hands_mask_min_ratio_var.set(float(cfg.get("ad_hands_mask_min_ratio", 0.003)))
        self.hands_mask_max_ratio_var.set(float(cfg.get("ad_hands_mask_max_ratio", 1.0)))
        self.hands_dilate_erode_var.set(int(cfg.get("ad_hands_dilate_erode", 6)))
        self.hands_mask_blur_var.set(int(cfg.get("ad_hands_mask_blur", 4)))
        self.hands_merge_var.set(str(cfg.get("ad_hands_mask_merge_invert", "None")))

    def to_config_dict(self) -> dict[str, Any]:
        config = self._raw_config()
        if self._mode in FACE_MODES:
            profiles = {**self._profiles, self._editing_profile: profile_values(config)}
            # Auto displays either profile for editing, but the flat authoring aliases mirror Single Face.
            flat_mode = "single" if self._mode == "auto" else self._mode
            config = apply_profile(config, flat_mode, profiles[flat_mode])
            config.update(face_mode=self._mode, **{PROFILES_KEY: profiles})
        return config

    def _raw_config(self) -> dict[str, Any]:
        config = {
            "adetailer_checkpoint_model": self._normalize_stage_model_override(
                self.stage_model_override_var.get()
            ),
            "adetailer_model": self.face_model_var.get(),
            "adetailer_confidence": self.face_confidence_var.get(),
            "ad_confidence": self.face_confidence_var.get(),
            "mask_blur": self.face_mask_blur_var.get(),
            "ad_mask_blur": self.face_mask_blur_var.get(),
            "mask_merge_mode": self.face_merge_var.get(),
            "ad_mask_merge_invert": self.face_merge_var.get(),
            "adetailer_steps": self.face_steps_var.get(),
            "ad_steps": self.face_steps_var.get(),
            "adetailer_cfg": self.face_cfg_var.get(),
            "ad_cfg_scale": self.face_cfg_var.get(),
            "adetailer_sampler": self.face_sampler_var.get(),
            "ad_sampler": self.face_sampler_var.get(),
            "adetailer_scheduler": self._normalize_scheduler_value(self.face_scheduler_var.get()),
            "scheduler": self._normalize_scheduler_value(self.face_scheduler_var.get()),
            "adetailer_denoise": self.face_denoise_var.get(),
            "ad_denoising_strength": self.face_denoise_var.get(),
            "adetailer_prompt": self.face_prompt_var.get(),
            "ad_prompt": self.face_prompt_var.get(),
            "adetailer_negative_prompt": self.face_negative_var.get(),
            "ad_negative_prompt": self.face_negative_var.get(),
            "ad_inpaint_only_masked": self.face_inpaint_masked_var.get(),
            "ad_inpaint_only_masked_padding": self.face_padding_var.get(),
            "adetailer_padding": self.face_padding_var.get(),
            "ad_use_inpaint_width_height": self.face_use_inpaint_wh_var.get(),
            "ad_inpaint_width": self.face_inpaint_width_var.get(),
            "ad_inpaint_height": self.face_inpaint_height_var.get(),
            "mask_filter_method": self.face_mask_filter_method_var.get(),
            "ad_mask_filter_method": self.face_mask_filter_method_var.get(),
            "mask_k_largest": self.face_mask_k_largest_var.get(),
            "ad_mask_k_largest": self.face_mask_k_largest_var.get(),
            "mask_min_ratio": self.face_mask_min_ratio_var.get(),
            "ad_mask_min_ratio": self.face_mask_min_ratio_var.get(),
            "mask_max_ratio": self.face_mask_max_ratio_var.get(),
            "ad_mask_max_ratio": self.face_mask_max_ratio_var.get(),
            "mask_dilate_erode": self.face_dilate_erode_var.get(),
            "ad_dilate_erode": self.face_dilate_erode_var.get(),
            "enable_face_pass": self.enable_face_pass_var.get(),
            "adetailer_hands_model": self.hands_model_var.get(),
            "hands_model": self.hands_model_var.get(),
            "enable_hands_pass": self.enable_hands_pass_var.get(),
            "ad_hands_enabled": self.enable_hands_pass_var.get(),
            "adetailer_hands_confidence": self.hands_confidence_var.get(),
            "ad_hands_mask_filter_method": self.hands_mask_filter_method_var.get(),
            "ad_hands_mask_k": self.hands_mask_k_largest_var.get(),
            "ad_hands_mask_min_ratio": self.hands_mask_min_ratio_var.get(),
            "ad_hands_mask_max_ratio": self.hands_mask_max_ratio_var.get(),
            "ad_hands_dilate_erode": self.hands_dilate_erode_var.get(),
            "ad_hands_mask_blur": self.hands_mask_blur_var.get(),
            "ad_hands_mask_merge_invert": self.hands_merge_var.get(),
            "ad_hands_padding": self.hands_padding_var.get(),
            "ad_hands_inpaint_only_masked": self.hands_inpaint_masked_var.get(),
            "ad_hands_use_inpaint_width_height": self.hands_use_inpaint_wh_var.get(),
            "ad_hands_inpaint_width": self.hands_inpaint_width_var.get(),
            "ad_hands_inpaint_height": self.hands_inpaint_height_var.get(),
            "adetailer_hands_steps": self.hands_steps_var.get(),
            "adetailer_hands_cfg": self.hands_cfg_var.get(),
            "adetailer_hands_denoise": self.hands_denoise_var.get(),
            "adetailer_hands_sampler": self.hands_sampler_var.get(),
            "adetailer_hands_scheduler": self._normalize_scheduler_value(
                self.hands_scheduler_var.get()
            ),
            "adetailer_hands_prompt": self.hands_prompt_var.get(),
            "adetailer_hands_negative_prompt": self.hands_negative_var.get(),
        }
        config.update(self._legacy_unsupported)
        return config

    def watchable_vars(self) -> Iterable[tk.Variable]:
        return [
            self._config_revision,
            self.stage_model_override_var,
            self.enable_face_pass_var,
            self.model_var,
            self.confidence_var,
            self.mask_blur_var,
            self.merge_var,
            self.steps_var,
            self.cfg_var,
            self.sampler_var,
            self.scheduler_var,
            self.denoise_var,
            self.prompt_var,
            self.negative_var,
            self.inpaint_masked_var,
            self.inpaint_padding_var,
            self.use_inpaint_wh_var,
            self.face_inpaint_width_var,
            self.face_inpaint_height_var,
            self.mask_filter_method_var,
            self.mask_k_largest_var,
            self.mask_min_ratio_var,
            self.mask_max_ratio_var,
            self.dilate_erode_var,
            self.enable_hands_pass_var,
            self.hands_model_var,
            self.hands_confidence_var,
            self.hands_steps_var,
            self.hands_cfg_var,
            self.hands_sampler_var,
            self.hands_scheduler_var,
            self.hands_denoise_var,
            self.hands_prompt_var,
            self.hands_negative_var,
            self.hands_inpaint_masked_var,
            self.hands_padding_var,
            self.hands_use_inpaint_wh_var,
            self.hands_inpaint_width_var,
            self.hands_inpaint_height_var,
            self.hands_mask_filter_method_var,
            self.hands_mask_k_largest_var,
            self.hands_mask_min_ratio_var,
            self.hands_mask_max_ratio_var,
            self.hands_dilate_erode_var,
            self.hands_mask_blur_var,
            self.hands_merge_var,
        ]

    def apply_webui_resources(self, resources: dict[str, Any] | None) -> None:
        self._resource_refreshing = True
        try:
            self._update_webui_resources(resources)
        finally:
            self._resource_refreshing = False

    def _update_webui_resources(self, resources: dict[str, Any] | None) -> None:
        if resources is None:
            resources = {}
        detector_models = [
            str(v) for v in (resources.get("adetailer_models") or []) if str(v).strip()
        ]
        checkpoint_models = []
        for item in resources.get("models") or []:
            name = getattr(item, "display_name", None) or getattr(item, "name", None) or str(item)
            if str(name).strip():
                checkpoint_models.append(str(name))
        samplers = [str(v) for v in (resources.get("samplers") or []) if str(v).strip()]

        usable = [
            name
            for name in detector_models
            # ADetailer-Neo's MediaPipe detectors are not part of the managed Forge runtime, so they are never offered there.
            if not (self._forge_detectors and name.lower().startswith("mediapipe"))
        ]
        face_options, hand_options = split_detectors(usable)
        known = bool(usable)
        face_options = face_options or list(self.MODEL_OPTIONS)
        hand_options = hand_options or list(self.HAND_MODEL_OPTIONS)
        known = known or self._forge_detectors  # the runtime's accepted set is itself a known list
        self._available_face_detectors = face_options if known else None
        self._available_hand_detectors = hand_options if known else None
        self._configure_combo(
            self._face_model_combo, face_options, self.face_model_var, keep_current=True
        )
        self._configure_combo(
            self._hands_model_combo, hand_options, self.hands_model_var, keep_current=True
        )
        self._configure_combo(self._sampler_combo, samplers, self.face_sampler_var)
        self._configure_combo(self._hand_sampler_combo, samplers, self.hands_sampler_var)

        if self._stage_model_combo is not None:
            stage_values = (
                [self.STAGE_MODEL_INHERIT] + checkpoint_models
                if checkpoint_models
                else [self.STAGE_MODEL_INHERIT]
            )
            current = self.stage_model_override_var.get().strip() or self.STAGE_MODEL_INHERIT
            self._stage_model_combo.configure(values=tuple(stage_values), state="readonly")
            self.stage_model_override_var.set(
                current if current in stage_values else self.STAGE_MODEL_INHERIT
            )

    def _configure_combo(
        self,
        combo: ttk.Combobox | None,
        values: Iterable[str],
        variable: tk.StringVar,
        *,
        keep_current: bool = False,
    ) -> None:
        if combo is None:
            return
        cleaned = [str(value) for value in values if str(value).strip()]
        existing = list(combo.cget("values"))
        final_values = cleaned or existing
        current_value = variable.get()
        if keep_current and current_value and current_value not in final_values:
            # An unavailable saved selection stays visible and unchanged; the projection reports it, nothing replaces it.
            final_values = [*final_values, current_value]
        combo.configure(values=tuple(final_values), state="readonly", style=DARK_COMBOBOX_STYLE)
        if final_values and not keep_current:
            current = variable.get()
            if current not in final_values:
                variable.set(final_values[0])
        self._refresh_effective_summary()

    def apply_resource_update(self, resources: dict[str, Any] | None) -> None:
        self.apply_webui_resources(resources)
