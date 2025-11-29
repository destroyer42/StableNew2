from __future__ import annotations

import tkinter as tk

import pytest

from src.utils import InMemoryLogHandler, get_logger
from src.gui.log_trace_panel_v2 import LogTracePanelV2


def test_log_trace_panel_v2_smoke():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    handler = InMemoryLogHandler(max_entries=20)
    logger = get_logger(__name__)
    logger.addHandler(handler)

    panel = LogTracePanelV2(root, log_handler=handler)
    panel.refresh()
    assert panel._log_list.size() == 0

    logger.error("Test error")
    panel.refresh()
    assert panel._log_list.size() >= 1

    root.destroy()
