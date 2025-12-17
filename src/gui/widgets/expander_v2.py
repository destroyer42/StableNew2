"""Unified expander button used by Pipeline Tab cards."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.gui.theme_v2 import (
    EXPANDER_ICON_COLLAPSED,
    EXPANDER_ICON_EXPANDED,
)


class ExpanderV2(ttk.Button):
    """Lightweight expander widget with consistent icons."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        command: Callable[[], None],
        width: int = 4,
        **kwargs: object,
    ) -> None:
        super().__init__(
            master,
            text=EXPANDER_ICON_COLLAPSED,
            width=width,
            command=command,
            style="Dark.TButton",
            **kwargs,
        )
        self._expanded_icon = EXPANDER_ICON_EXPANDED
        self._collapsed_icon = EXPANDER_ICON_COLLAPSED
        self._is_expanded = False

    def set_expanded(self, expanded: bool) -> None:
        """Update the icon to reflect the expanded state."""
        self._is_expanded = bool(expanded)
        icon = self._expanded_icon if self._is_expanded else self._collapsed_icon
        self.configure(text=icon)
