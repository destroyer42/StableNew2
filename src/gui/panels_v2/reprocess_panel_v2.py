"""Minimal sidebar launcher for the canonical Review-tab reprocess workflow."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import BODY_LABEL_STYLE, CARD_FRAME_STYLE, MUTED_LABEL_STYLE


class ReprocessPanelV2(ttk.Frame):
    """Compact launcher that redirects users to the Review tab.

    The Review tab is the only advanced reprocess surface. This sidebar panel
    exists purely as a discoverability bridge from Pipeline.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        controller: Any = None,
        app_state: Any = None,
        embed_mode: bool = False,
        **kwargs: Any,
    ) -> None:
        style = CARD_FRAME_STYLE if not embed_mode else None
        if style and "style" not in kwargs:
            kwargs["style"] = style
        super().__init__(master, **kwargs)
        self.controller = controller
        self.app_state = app_state

        self.columnconfigure(0, weight=1)

        description = ttk.Label(
            self,
            text="Advanced reprocess now lives in Review. Use it to select images, "
            "inspect embedded metadata, edit prompts, and submit queue-backed reprocess jobs.",
            style=BODY_LABEL_STYLE,
            wraplength=560,
            justify="left",
        )
        description.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 8))

        details = ttk.Label(
            self,
            text="Review owns image selection, prompt delta modes, and batch-aware reprocess submission.",
            style=MUTED_LABEL_STYLE,
            wraplength=560,
            justify="left",
        )
        details.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 8))

        self.open_review_button = ttk.Button(
            self,
            text="Open Review Workspace",
            command=self._on_open_review,
            style="Primary.TButton",
        )
        self.open_review_button.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 4))

        self.helper_label = ttk.Label(
            self,
            text="Tip: Review supports both selected-image and folder-based reprocess flows.",
            style=MUTED_LABEL_STYLE,
            wraplength=560,
            justify="left",
        )
        self.helper_label.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 0))

    def _find_notebook(self) -> ttk.Notebook | None:
        root = self.winfo_toplevel()
        stack = [root]
        while stack:
            widget = stack.pop()
            if isinstance(widget, ttk.Notebook):
                return widget
            try:
                stack.extend(widget.winfo_children())
            except Exception:
                continue
        return None

    def _activate_review_tab(self) -> bool:
        main_window = getattr(self.controller, "main_window", None)
        review_tab = getattr(main_window, "review_tab", None)
        notebook = getattr(main_window, "center_notebook", None)
        if notebook is not None and review_tab is not None:
            try:
                notebook.select(review_tab)
                return True
            except Exception:
                pass

        notebook = self._find_notebook()
        if notebook is None:
            return False

        try:
            for tab_id in notebook.tabs():
                if notebook.tab(tab_id, "text") == "Review":
                    notebook.select(tab_id)
                    return True
        except Exception:
            return False
        return False

    def _on_open_review(self) -> None:
        opened = self._activate_review_tab()
        if not opened and self.controller is not None:
            logger = getattr(self.controller, "_append_log", None)
            if callable(logger):
                try:
                    logger("[reprocess] Review tab could not be activated.")
                except Exception:
                    pass
