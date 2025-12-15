"""Shim module exporting PipelineConfigPanel for backward-compatible imports.

If the heavier implementation exists under `src.gui.views.pipeline_config_panel_v2`, import
and re-export it. Otherwise provide a minimal no-op fallback compatible with tests.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

try:
    from src.gui.views.pipeline_config_panel_v2 import PipelineConfigPanel as _RealPanel  # type: ignore
except Exception:  # pragma: no cover - fallback for environments lacking the full panel
    _RealPanel = None  # type: ignore


if _RealPanel is not None:
    PipelineConfigPanel = _RealPanel  # type: ignore
else:
    class PipelineConfigPanel(ttk.Frame):
        def __init__(self, master: tk.Misc, pipeline_state: object | None = None, app_state: object | None = None, on_change: Any = None, *args: Any, **kwargs: Any) -> None:
            style = kwargs.pop("style", None)
            super().__init__(master, **kwargs)
            self._on_change = on_change
            self.pipeline_state = pipeline_state
            self.app_state = app_state

        def set_validation_message(self, *args: Any, **kwargs: Any) -> None:
            # no-op for tests that expect this method
            return None
