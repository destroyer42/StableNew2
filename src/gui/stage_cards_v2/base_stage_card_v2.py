from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional, Any

from src.gui.stage_cards_v2.validation_result import ValidationResult
from src.gui.theme_v2 import (
    CARD_FRAME_STYLE,
    HEADING_LABEL_STYLE,
    MUTED_LABEL_STYLE,
)


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
        super().__init__(master, style=CARD_FRAME_STYLE, padding=6, **filtered_kwargs)

        self.config_manager = config_manager
        self._title = title
        self._description = description
        self._show_header = show_header
        if self._show_header:
            self._build_header()
        self._build_body_container()
        self._build_validation_area()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style=CARD_FRAME_STYLE)
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
        body = ttk.Frame(self, style=CARD_FRAME_STYLE)
        body.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self.rowconfigure(1, weight=1)
        self.body_frame = body
        self._build_body(body)

    def _build_validation_area(self) -> None:
        """Build validation area but keep it hidden when empty."""
        self._validation_frame = ttk.Frame(self, style=CARD_FRAME_STYLE)
        # Don't grid it initially - only show when there's content
        self.validation_label = ttk.Label(
            self._validation_frame, text="", style=MUTED_LABEL_STYLE
        )
        self.validation_label.pack(side="left")
        # Initially hidden since no validation messages
        self._validation_visible = False

    def _show_validation_frame(self) -> None:
        """Show the validation frame if it has content."""
        if not self._validation_visible:
            self._validation_frame.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 4))
            self._validation_visible = True

    def _hide_validation_frame(self) -> None:
        """Hide the validation frame when empty."""
        if self._validation_visible:
            self._validation_frame.grid_remove()
            self._validation_visible = False

    # --- Hooks for subclasses -------------------------------------------------
    def _build_body(self, parent: ttk.Frame) -> None:
        raise NotImplementedError

    def show_validation_result(self, result: ValidationResult) -> None:
        if result.is_empty():
            self.validation_label.config(text="")
            self._hide_validation_frame()
        else:
            message = result.message or ""
            self.validation_label.config(text=message)
            self._show_validation_frame()

    def load_from_config(self, cfg: dict[str, object]) -> None:
        """Optional config loader for subclasses."""
        return None

    def to_config_dict(self) -> dict[str, object]:
        """Optional config serializer for subclasses."""
        return {}


__all__ = ["BaseStageCardV2"]
