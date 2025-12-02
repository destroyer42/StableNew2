from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.state import PipelineState
from src.gui.views.pipeline_config_panel import PipelineConfigPanel


@pytest.mark.gui
def test_pipeline_config_stage_checkbox_order(monkeypatch) -> None:
    root = tk.Tk()
    state = PipelineState()
    panel = PipelineConfigPanel(root, pipeline_state=state)
    panel.pack()
    root.update_idletasks()

    # Extract labels of the stage checkbuttons in creation order
    stage_labels = [child.cget("text") for child in panel.winfo_children() if isinstance(child, tk.Checkbutton)]
    assert stage_labels == [
        "Enable txt2img",
        "Enable img2img",
        "Enable ADetailer",
        "Enable upscale",
    ]

    root.destroy()
