from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from src.gui.pipeline_panel_v2 import PipelinePanelV2


@pytest.mark.gui
def test_pipeline_panel_stage_card_order():
    root = tk.Tk()
    panel = PipelinePanelV2(root)

    # Provide a dummy sidebar reporting all stages enabled
    panel.sidebar = SimpleNamespace(
        get_enabled_stages=lambda: {"txt2img", "img2img", "adetailer", "upscale"}
    )
    panel._apply_stage_visibility()

    # Ensure the card ordering matches canonical sequence
    body_children = panel.body.pack_slaves()
    order_map = {
        panel.txt2img_card: 0,
        panel.img2img_card: 1,
        panel.adetailer_card: 2,
        panel.upscale_card: 3,
    }
    positions = [order_map.get(child, -1) for child in body_children if child in order_map]
    assert positions == [0, 1, 2, 3]

    root.destroy()
