from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable

from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2
from src.gui.theme_v2 import BODY_LABEL_STYLE, CARD_FRAME_STYLE, SURFACE_FRAME_STYLE, TEXT_PRIMARY


class ADetailerStageCardV2(BaseStageCardV2):
    """Minimal ADetailer stage card exposing controls via BaseStageCardV2."""

    MODEL_OPTIONS = ["face_yolov8n.pt", "adetailer_v1.pt"]
    DETECTOR_OPTIONS = ["face", "hand", "body"]
    MERGE_MODES = ["keep", "replace", "merge"]

    def __init__(self, master: tk.Misc, *, theme: Any | None = None, **kwargs: Any) -> None:
        self.model_var = tk.StringVar(value=self.MODEL_OPTIONS[0])
        self.detector_var = tk.StringVar(value=self.DETECTOR_OPTIONS[0])
        self.confidence_var = tk.DoubleVar(value=0.35)
        self.max_detections_var = tk.IntVar(value=8)
        self.mask_blur_var = tk.IntVar(value=4)
        self.merge_var = tk.StringVar(value=self.MERGE_MODES[0])
        self.only_faces_var = tk.BooleanVar(value=True)
        self.only_hands_var = tk.BooleanVar(value=False)
        self._model_combo: ttk.Combobox | None = None
        self._detector_combo: ttk.Combobox | None = None

        super().__init__(
            master,
            title="ADetailer Stage",
            description="Fine-tune face/hand/model outputs after txt2img.",
            theme=theme,
            **kwargs,
        )

    def _build_body(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        row = 0

        self._model_combo = self._add_labeled_combo(
            parent,
            "ADetailer model:",
            self.model_var,
            self.MODEL_OPTIONS,
            row,
        )
        row += 1
        self._detector_combo = self._add_labeled_combo(
            parent,
            "Detector:",
            self.detector_var,
            self.DETECTOR_OPTIONS,
            row,
        )
        row += 1

        row = self._add_spin_section(
            parent,
            row,
            "Confidence:",
            self.confidence_var,
            0.1,
            1.0,
            0.05,
            format_str="%.2f",
        )

        row = self._add_spin_section(
            parent,
            row,
            "Max detections:",
            self.max_detections_var,
            1,
            32,
            1,
        )

        row = self._add_spin_section(
            parent, row, "Mask blur:", self.mask_blur_var, 0, 16, 1
        )

        self._add_labeled_combo(
            parent,
            "Mask merge mode:",
            self.merge_var,
            self.MERGE_MODES,
            row,
        )
        row += 1

        toggle_frame = ttk.Frame(parent, style=SURFACE_FRAME_STYLE)
        toggle_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(
            toggle_frame,
            text="Only faces",
            variable=self.only_faces_var,
            style="Dark.TCheckbutton",
        ).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(
            toggle_frame,
            text="Only hands",
            variable=self.only_hands_var,
            style="Dark.TCheckbutton",
        ).pack(side="left")

    def _add_labeled_combo(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        options: Iterable[str],
        row: int,
    ) -> None:
        ttk.Label(parent, text=label, style=BODY_LABEL_STYLE).grid(
            row=row, column=0, sticky="w", pady=2
        )
        combo = ttk.Combobox(
            parent,
            values=list(options),
            textvariable=variable,
            state="readonly",
            style="Dark.TCombobox",
        )
        combo.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        return combo

    def _add_spin_section(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.Variable,
        minimum: float,
        maximum: float,
        increment: float,
        format_str: str = "%.1f",
    ) -> int:
        ttk.Label(parent, text=label, style=BODY_LABEL_STYLE).grid(
            row=row, column=0, sticky="w", pady=2
        )
        spin = ttk.Spinbox(
            parent,
            from_=minimum,
            to=maximum,
            increment=increment,
            textvariable=variable,
            width=8,
            format=format_str if isinstance(variable, tk.DoubleVar) else None,
        )
        spin.grid(row=row, column=1, sticky="w", pady=2, padx=(8, 0))
        return row + 1

    def load_from_dict(self, cfg: dict[str, Any] | None) -> None:
        if not cfg:
            return
        self.model_var.set(cfg.get("adetailer_model") or self.MODEL_OPTIONS[0])
        self.detector_var.set(cfg.get("detector") or self.DETECTOR_OPTIONS[0])
        self.confidence_var.set(float(cfg.get("adetailer_confidence", 0.35)))
        self.max_detections_var.set(int(cfg.get("max_detections", 8)))
        self.mask_blur_var.set(int(cfg.get("mask_blur", 4)))
        self.merge_var.set(cfg.get("mask_merge_mode") or self.MERGE_MODES[0])
        self.only_faces_var.set(bool(cfg.get("only_faces", True)))
        self.only_hands_var.set(bool(cfg.get("only_hands", False)))

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "adetailer_model": self.model_var.get(),
            "detector": self.detector_var.get(),
            "adetailer_confidence": self.confidence_var.get(),
            "max_detections": self.max_detections_var.get(),
            "mask_blur": self.mask_blur_var.get(),
            "mask_merge_mode": self.merge_var.get(),
            "only_faces": self.only_faces_var.get(),
            "only_hands": self.only_hands_var.get(),
        }

    def watchable_vars(self) -> Iterable[tk.Variable]:
        return [
            self.model_var,
            self.detector_var,
            self.confidence_var,
            self.max_detections_var,
            self.mask_blur_var,
            self.merge_var,
            self.only_faces_var,
            self.only_hands_var,
        ]

    def apply_webui_resources(self, resources: dict[str, Any] | None) -> None:
        if resources is None:
            resources = {}
        models = [str(v) for v in (resources.get("adetailer_models") or []) if str(v).strip()]
        detectors = [str(v) for v in (resources.get("adetailer_detectors") or []) if str(v).strip()]

        self._configure_combo(self._model_combo, models, self.model_var)
        self._configure_combo(self._detector_combo, detectors, self.detector_var)

    def _configure_combo(self, combo: ttk.Combobox | None, values: list[str], variable: tk.StringVar) -> None:
        if not combo:
            return
        combo.configure(values=values, state="readonly" if values else "disabled", style="Dark.TCombobox")
        if values:
            current = variable.get()
            if not current or current not in values:
                variable.set(values[0])
