from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional, Any

from src.gui.stage_cards_v2.validation_result import ValidationResult
from src.gui.theme_v2 import HEADING_LABEL_STYLE, MUTED_LABEL_STYLE


class BaseStageCardV2(ttk.Frame):
    """Base class for V2 stage cards with shared header and validation area."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        description: Optional[str] = None,
        *,
        config_manager: Any = None,
        show_header: bool = True,
        **kwargs: Any,
    ) -> None:
        # Remove config_manager from kwargs if present
        filtered_kwargs = {k: v for k, v in kwargs.items() if k != "config_manager"}
        super().__init__(master, style="Card.TFrame", padding=6, **filtered_kwargs)

        self.config_manager = config_manager
        self._title = title
        self._description = description
        self._show_header = show_header
        if self._show_header:
            self._build_header()
        self._build_body_container()
        self._build_validation_area()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 4))
        self.columnconfigure(0, weight=1)

        self.title_label = ttk.Label(header, text=self._title, style=HEADING_LABEL_STYLE)
        self.title_label.pack(side="left")

        if self._description:
            self.description_label = ttk.Label(
                header,
                text=self._description,
                style=MUTED_LABEL_STYLE,
                wraplength=420,
                justify="left",
            )
            self.description_label.pack(side="left", padx=(8, 0))

    def _build_body_container(self) -> None:
        body = ttk.Frame(self, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self.rowconfigure(1, weight=1)
        self.body_frame = body
        self._build_body(body)

    def _build_validation_area(self) -> None:
        val_frame = ttk.Frame(self, style="Card.TFrame")
        val_frame.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 4))
        self.validation_label = ttk.Label(val_frame, text="", style=MUTED_LABEL_STYLE)
        self.validation_label.pack(side="left")

    # --- Hooks for subclasses -------------------------------------------------
    def _build_body(self, parent: ttk.Frame) -> None:
        raise NotImplementedError

    def show_validation_result(self, result: ValidationResult) -> None:
        message = result.message or ""
        self.validation_label.config(text=message)

    def load_from_config(self, cfg: dict[str, object]) -> None:
        """Optional config loader for subclasses."""
        return None

    def to_config_dict(self) -> dict[str, object]:
        """Optional config serializer for subclasses."""
        return {}


__all__ = ["BaseStageCardV2"]
