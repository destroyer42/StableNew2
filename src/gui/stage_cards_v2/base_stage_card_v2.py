from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional, Any

from src.gui.app_state_v2 import AppStateV2
from src.gui.theme_v2 import (
    CARD_FRAME_STYLE,
    HEADING_LABEL_STYLE,
    MUTED_LABEL_STYLE,
)
from src.gui.widgets.expander_v2 import ExpanderV2


class BaseStageCardV2(ttk.Frame):
    """Base class for V2 stage cards with shared header, body, and optional collapse."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        description: Optional[str] = None,
        *,
        config_manager: Any = None,
        show_header: bool = True,
        collapsible: bool = False,
        collapse_key: str | None = None,
        app_state: AppStateV2 | None = None,
        default_open: bool = True,
        **kwargs: Any,
    ) -> None:
        filtered_kwargs = {k: v for k, v in kwargs.items() if k != "config_manager"}
        super().__init__(master, style=CARD_FRAME_STYLE, padding=6, **filtered_kwargs)

        self.config_manager = config_manager
        self._title = title
        self._description = description
        self._show_header = show_header
        self._collapsible = collapsible
        self._collapse_key = collapse_key
        self._app_state = app_state
        self._default_open = default_open
        self._body_visible = True
        self._expander: ExpanderV2 | None = None

        if self._show_header:
            self._build_header()
        self._build_body_container()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style=CARD_FRAME_STYLE)
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 4))
        self.columnconfigure(0, weight=1)
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        text_container = ttk.Frame(header, style=CARD_FRAME_STYLE)
        text_container.grid(row=0, column=0, sticky="w")
        self.title_label = ttk.Label(text_container, text=self._title, style=HEADING_LABEL_STYLE)
        self.title_label.pack(side="left")

        if self._description:
            self.description_label = ttk.Label(
                text_container,
                text=self._description,
                style=MUTED_LABEL_STYLE,
                wraplength=420,
                justify="left",
            )
            self.description_label.pack(side="left", padx=(8, 0))

        if self._collapsible:
            self._expander = ExpanderV2(header, command=self._toggle_body)
            self._expander.grid(row=0, column=1, sticky="e", padx=(8, 0))

    def _build_body_container(self) -> None:
        body = ttk.Frame(self, style=CARD_FRAME_STYLE)
        body.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self.rowconfigure(1, weight=1)
        self.body_frame = body
        self._build_body(body)
        if self._collapsible:
            initial_open = self._determine_initial_collapse_state()
            self._apply_collapse_state(initial_open, persist=False)

    # --- Hooks for subclasses -------------------------------------------------
    def _build_body(self, parent: ttk.Frame) -> None:
        raise NotImplementedError

    def load_from_config(self, cfg: dict[str, object]) -> None:
        """Optional config loader for subclasses."""  # pragma: no cover
        return None

    def to_config_dict(self) -> dict[str, object]:
        """Optional config serializer for subclasses."""  # pragma: no cover
        return {}

    # --- Collapsible helpers --------------------------------------------------
    def _toggle_body(self) -> None:
        if not self._collapsible:
            return
        self._apply_collapse_state(not self._body_visible, persist=True)

    def _determine_initial_collapse_state(self) -> bool:
        if not self._collapsible:
            return True
        if self._collapse_key and self._app_state:
            stored = self._app_state.get_collapse_state(self._collapse_key)
            if stored is not None:
                return stored
        return self._default_open

    def _apply_collapse_state(self, is_open: bool, *, persist: bool = True) -> None:
        if not self._collapsible or not hasattr(self, "body_frame"):
            return
        self._body_visible = bool(is_open)
        if self._body_visible:
            self.body_frame.grid()
        else:
            self.body_frame.grid_remove()
        if self._expander:
            self._expander.set_expanded(self._body_visible)
        if persist and self._app_state and self._collapse_key:
            self._app_state.set_collapse_state(self._collapse_key, self._body_visible)


__all__ = ["BaseStageCardV2"]
