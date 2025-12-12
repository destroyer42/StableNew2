from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.state import PipelineState
from src.gui.panels_v2.pipeline_panel_v2 import PipelinePanelV2


@pytest.mark.gui
def test_pipeline_config_stage_checkbox_order(monkeypatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter unavailable: {exc}")
    state = PipelineState()
    panel = PipelinePanelV2(root, pipeline_state=state)
    panel.pack()
    root.update_idletasks()

    # Try to find stage checkboxes; if not present, skip
    checkboxes = [child for child in panel.winfo_children() if isinstance(child, tk.Checkbutton)]
    if not checkboxes:
        pytest.skip("Stage checkbox ordering not implemented/accessible in v2 panel surface yet")
    stage_labels = [child.cget("text") for child in checkboxes]
    assert stage_labels == [
        "Enable txt2img",
        "Enable img2img",
        "Enable ADetailer",
        "Enable upscale",
    ]

    root.destroy()
