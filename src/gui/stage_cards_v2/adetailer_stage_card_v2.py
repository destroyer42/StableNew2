from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Iterable
from tkinter import ttk
from typing import Any

from src.gui.help_text.stage_setting_help_v2 import ADETAILER_STAGE_HELP
from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import (
    BODY_LABEL_STYLE,
    DARK_CHECKBUTTON_STYLE,
    DARK_COMBOBOX_STYLE,
    DARK_ENTRY_STYLE,
    DARK_SPINBOX_STYLE,
    SURFACE_FRAME_STYLE,
)


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
    MASK_FILTER_OPTIONS = ["Area", "largest", "all"]
    MASK_MERGE_OPTIONS = ["None", "Merge", "Merge and Invert"]
    STAGE_MODEL_INHERIT = "Inherit Base Generation"

    def __init__(self, master: tk.Misc, *, theme: Any | None = None, **kwargs: Any) -> None:
        self.stage_model_override_var = tk.StringVar(value="")

        self.enable_face_pass_var = tk.BooleanVar(value=True)
        self.model_var = tk.StringVar(value=self.MODEL_OPTIONS[0])
        self.face_model_var = self.model_var
        self.confidence_var = tk.DoubleVar(value=0.35)
        self.face_confidence_var = self.confidence_var
        self.max_detections_var = tk.IntVar(value=8)
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
        self.mask_feather_var = tk.IntVar(value=4)
        self.face_mask_feather_var = self.mask_feather_var

        self.enable_hands_pass_var = tk.BooleanVar(value=False)
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
        self.hands_mask_feather_var = tk.IntVar(value=4)
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
        self._face_prompt_widgets: list[tk.Widget] = []
        self._hand_prompt_widgets: list[tk.Widget] = []

        self.detector_var = self.model_var

        super().__init__(
            master,
            title="ADetailer Stage",
            description="Face and hand refinement with explicit pass-level controls.",
            theme=theme,
            **kwargs,
        )

    def _build_body(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        helper = ttk.Label(
            parent,
            text="Use face and hand pass tabs for pass-local settings. Stage model override is optional and inherits Base Generation by default.",
            style=BODY_LABEL_STYLE,
            wraplength=460,
            justify="left",
        )
        helper.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        overall = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        overall.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in range(4):
            overall.columnconfigure(column, weight=1 if column % 2 == 1 else 0)

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
        self._attach_setting_help(
            "hand_pass_enabled",
            ADETAILER_STAGE_HELP["hand_pass_enabled"],
            hand_pass_label,
            hand_pass_check,
        )

        notebook = ttk.Notebook(parent)
        notebook.grid(row=2, column=0, sticky="nsew")

        face_tab = ttk.Frame(notebook, style=SURFACE_FRAME_STYLE)
        hand_tab = ttk.Frame(notebook, style=SURFACE_FRAME_STYLE)
        prompt_tab = ttk.Frame(notebook, style=SURFACE_FRAME_STYLE)
        for tab in (face_tab, hand_tab, prompt_tab):
            tab.columnconfigure(1, weight=1)

        notebook.add(face_tab, text="Face Pass")
        notebook.add(hand_tab, text="Hand Pass")
        notebook.add(prompt_tab, text="Prompts")

        self._build_face_tab(face_tab)
        self._build_hand_tab(hand_tab)
        self._build_prompt_tab(prompt_tab)
        self._sync_pass_states()

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
            ("CFG", self.face_cfg_var, 1.0, 30.0, 0.1, "cfg"),
            ("Denoising", self.face_denoise_var, 0.0, 1.0, 0.01, "denoising"),
            ("Padding", self.face_padding_var, 0, 256, 1, "padding"),
            ("Mask Blur", self.face_mask_blur_var, 0, 64, 1, "mask_blur"),
            ("Mask Feather", self.face_mask_feather_var, 0, 64, 1, "mask_feather"),
            ("Dilate / Erode", self.face_dilate_erode_var, -64, 64, 1, "dilate_erode"),
            ("Max Detections", self.max_detections_var, 1, 32, 1, "max_detections"),
            ("Mask Max-K", self.face_mask_k_largest_var, 1, 16, 1, "mask_max_k"),
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
        self._attach_setting_help("use_inpaint_wh", ADETAILER_STAGE_HELP["use_inpaint_wh"], inpaint_wh)
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
            ("CFG", self.hands_cfg_var, 1.0, 30.0, 0.1, "cfg"),
            ("Denoising", self.hands_denoise_var, 0.0, 1.0, 0.01, "denoising"),
            ("Padding", self.hands_padding_var, 0, 256, 1, "padding"),
            ("Mask Blur", self.hands_mask_blur_var, 0, 64, 1, "mask_blur"),
            ("Mask Feather", self.hands_mask_feather_var, 0, 64, 1, "mask_feather"),
            ("Dilate / Erode", self.hands_dilate_erode_var, -64, 64, 1, "dilate_erode"),
            ("Mask Max-K", self.hands_mask_k_largest_var, 1, 16, 1, "mask_max_k"),
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
        self._attach_setting_help("use_inpaint_wh", ADETAILER_STAGE_HELP["use_inpaint_wh"], inpaint_wh)
        self._hand_widgets.extend([hand_masked, inpaint_wh])

    def _build_prompt_tab(self, parent: ttk.Frame) -> None:
        face_frame = ttk.LabelFrame(parent, text="Face Pass Prompts", style="Dark.TLabelframe")
        face_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        face_frame.columnconfigure(1, weight=1)

        face_prompt_label = ttk.Label(face_frame, text="Prompt", style=BODY_LABEL_STYLE)
        face_prompt_label.grid(row=0, column=0, sticky="w", pady=2)
        face_prompt = ttk.Entry(face_frame, textvariable=self.face_prompt_var, style=DARK_ENTRY_STYLE)
        face_prompt.grid(row=0, column=1, sticky="ew", pady=2, padx=(8, 0))
        self._attach_setting_help("prompt", ADETAILER_STAGE_HELP["prompt"], face_prompt_label, face_prompt)
        face_negative_label = ttk.Label(face_frame, text="Negative", style=BODY_LABEL_STYLE)
        face_negative_label.grid(row=1, column=0, sticky="w", pady=2)
        face_negative = ttk.Entry(
            face_frame, textvariable=self.face_negative_var, style=DARK_ENTRY_STYLE
        )
        face_negative.grid(row=1, column=1, sticky="ew", pady=2, padx=(8, 0))
        self._attach_setting_help(
            "negative",
            ADETAILER_STAGE_HELP["negative"],
            face_negative_label,
            face_negative,
        )
        self._face_prompt_widgets.extend([face_prompt, face_negative])

        hand_frame = ttk.LabelFrame(parent, text="Hand Pass Prompts", style="Dark.TLabelframe")
        hand_frame.grid(row=1, column=0, sticky="ew")
        hand_frame.columnconfigure(1, weight=1)

        hand_prompt_label = ttk.Label(hand_frame, text="Prompt", style=BODY_LABEL_STYLE)
        hand_prompt_label.grid(row=0, column=0, sticky="w", pady=2)
        hand_prompt = ttk.Entry(hand_frame, textvariable=self.hands_prompt_var, style=DARK_ENTRY_STYLE)
        hand_prompt.grid(row=0, column=1, sticky="ew", pady=2, padx=(8, 0))
        self._attach_setting_help("prompt", ADETAILER_STAGE_HELP["prompt"], hand_prompt_label, hand_prompt)
        hand_negative_label = ttk.Label(hand_frame, text="Negative", style=BODY_LABEL_STYLE)
        hand_negative_label.grid(row=1, column=0, sticky="w", pady=2)
        hand_negative = ttk.Entry(
            hand_frame, textvariable=self.hands_negative_var, style=DARK_ENTRY_STYLE
        )
        hand_negative.grid(row=1, column=1, sticky="ew", pady=2, padx=(8, 0))
        self._attach_setting_help(
            "negative",
            ADETAILER_STAGE_HELP["negative"],
            hand_negative_label,
            hand_negative,
        )
        self._hand_prompt_widgets.extend([hand_prompt, hand_negative])

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
        spin.grid(row=row, column=1, sticky="w", pady=2, padx=(8, 0))
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
        self._set_widgets_enabled(
            self._face_prompt_widgets, bool(self.enable_face_pass_var.get())
        )
        self._set_widgets_enabled(self._hand_widgets, bool(self.enable_hands_pass_var.get()))
        self._set_widgets_enabled(
            self._hand_prompt_widgets, bool(self.enable_hands_pass_var.get())
        )

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
        self.max_detections_var.set(int(cfg.get("max_detections", 8)))
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
        self.face_prompt_var.set(str(cfg.get("adetailer_prompt") or cfg.get("ad_prompt") or ""))
        self.face_negative_var.set(
            str(cfg.get("adetailer_negative_prompt") or cfg.get("ad_negative_prompt") or "")
        )
        self.face_inpaint_masked_var.set(bool(cfg.get("ad_inpaint_only_masked", True)))
        self.face_padding_var.set(
            int(cfg.get("ad_inpaint_only_masked_padding", cfg.get("adetailer_padding", 32)))
        )
        self.face_use_inpaint_wh_var.set(bool(cfg.get("ad_use_inpaint_width_height", False)))
        self.face_inpaint_width_var.set(int(cfg.get("ad_inpaint_width", 1024)))
        self.face_inpaint_height_var.set(int(cfg.get("ad_inpaint_height", 1024)))
        self.face_mask_filter_method_var.set(
            str(cfg.get("ad_mask_filter_method") or cfg.get("mask_filter_method") or "Area")
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
        self.face_mask_feather_var.set(
            int(cfg.get("ad_mask_feather", cfg.get("adetailer_mask_feather", cfg.get("mask_feather", 4))))
        )

        self.enable_hands_pass_var.set(
            bool(cfg.get("enable_hands_pass", cfg.get("ad_hands_enabled", False)))
        )
        self.hands_model_var.set(
            str(cfg.get("adetailer_hands_model") or cfg.get("hands_model") or self.HAND_MODEL_OPTIONS[0])
        )
        self.hands_confidence_var.set(float(cfg.get("adetailer_hands_confidence", 0.30)))
        self.hands_steps_var.set(int(cfg.get("adetailer_hands_steps", 12)))
        self.hands_cfg_var.set(float(cfg.get("adetailer_hands_cfg", 5.0)))
        self.hands_sampler_var.set(str(cfg.get("adetailer_hands_sampler") or "DPM++ 2M Karras"))
        self.hands_scheduler_var.set(
            self._normalize_scheduler_value(cfg.get("adetailer_hands_scheduler"))
        )
        self.hands_denoise_var.set(float(cfg.get("adetailer_hands_denoise", 0.25)))
        self.hands_prompt_var.set(str(cfg.get("adetailer_hands_prompt", self.hands_prompt_var.get())))
        self.hands_negative_var.set(
            str(cfg.get("adetailer_hands_negative_prompt", self.hands_negative_var.get()))
        )
        self.hands_inpaint_masked_var.set(bool(cfg.get("ad_hands_inpaint_only_masked", True)))
        self.hands_padding_var.set(int(cfg.get("ad_hands_padding", cfg.get("hands_padding", 16))))
        self.hands_use_inpaint_wh_var.set(bool(cfg.get("ad_hands_use_inpaint_width_height", False)))
        self.hands_inpaint_width_var.set(int(cfg.get("ad_hands_inpaint_width", 1024)))
        self.hands_inpaint_height_var.set(int(cfg.get("ad_hands_inpaint_height", 1024)))
        self.hands_mask_filter_method_var.set(str(cfg.get("ad_hands_mask_filter_method", "Area")))
        self.hands_mask_k_largest_var.set(int(cfg.get("ad_hands_mask_k", 6)))
        self.hands_mask_min_ratio_var.set(float(cfg.get("ad_hands_mask_min_ratio", 0.003)))
        self.hands_mask_max_ratio_var.set(float(cfg.get("ad_hands_mask_max_ratio", 1.0)))
        self.hands_dilate_erode_var.set(int(cfg.get("ad_hands_dilate_erode", 6)))
        self.hands_mask_blur_var.set(int(cfg.get("ad_hands_mask_blur", 4)))
        self.hands_mask_feather_var.set(int(cfg.get("ad_hands_mask_feather", 4)))
        self.hands_merge_var.set(str(cfg.get("ad_hands_mask_merge_invert", "None")))
        self._sync_pass_states()

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "adetailer_checkpoint_model": self._normalize_stage_model_override(
                self.stage_model_override_var.get()
            ),
            "adetailer_model": self.face_model_var.get(),
            "adetailer_confidence": self.face_confidence_var.get(),
            "ad_confidence": self.face_confidence_var.get(),
            "max_detections": self.max_detections_var.get(),
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
            "mask_feather": self.face_mask_feather_var.get(),
            "ad_mask_feather": self.face_mask_feather_var.get(),
            "adetailer_mask_feather": self.face_mask_feather_var.get(),
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
            "ad_hands_mask_feather": self.hands_mask_feather_var.get(),
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

    def watchable_vars(self) -> Iterable[tk.Variable]:
        return [
            self.stage_model_override_var,
            self.enable_face_pass_var,
            self.model_var,
            self.confidence_var,
            self.max_detections_var,
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
            self.mask_feather_var,
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
            self.hands_mask_feather_var,
            self.hands_merge_var,
        ]

    def apply_webui_resources(self, resources: dict[str, Any] | None) -> None:
        if resources is None:
            resources = {}
        detector_models = [str(v) for v in (resources.get("adetailer_models") or []) if str(v).strip()]
        checkpoint_models = []
        for item in resources.get("models") or []:
            name = getattr(item, "display_name", None) or getattr(item, "name", None) or str(item)
            if str(name).strip():
                checkpoint_models.append(str(name))
        samplers = [str(v) for v in (resources.get("samplers") or []) if str(v).strip()]

        self._configure_combo(self._face_model_combo, detector_models, self.face_model_var)
        self._configure_combo(
            self._hands_model_combo,
            detector_models or self.HAND_MODEL_OPTIONS,
            self.hands_model_var,
        )
        self._configure_combo(self._sampler_combo, samplers, self.face_sampler_var)
        self._configure_combo(self._hand_sampler_combo, samplers, self.hands_sampler_var)

        if self._stage_model_combo is not None:
            stage_values = [self.STAGE_MODEL_INHERIT] + checkpoint_models if checkpoint_models else [self.STAGE_MODEL_INHERIT]
            current = self.stage_model_override_var.get().strip() or self.STAGE_MODEL_INHERIT
            self._stage_model_combo.configure(values=tuple(stage_values), state="readonly")
            self.stage_model_override_var.set(current if current in stage_values else self.STAGE_MODEL_INHERIT)

    def _configure_combo(
        self, combo: ttk.Combobox | None, values: Iterable[str], variable: tk.StringVar
    ) -> None:
        if combo is None:
            return
        cleaned = [str(value) for value in values if str(value).strip()]
        existing = list(combo.cget("values"))
        final_values = cleaned or existing
        combo.configure(values=tuple(final_values), state="readonly", style=DARK_COMBOBOX_STYLE)
        if final_values:
            current = variable.get()
            if current not in final_values:
                variable.set(final_values[0])

    def apply_resource_update(self, resources: dict[str, Any] | None) -> None:
        self.apply_webui_resources(resources)
