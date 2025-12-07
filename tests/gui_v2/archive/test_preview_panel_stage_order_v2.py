#ARCHIVE
# Legacy preview panel stage order test archived after Phase 6 changes.
from __future__ import annotations

import tkinter as tk

from src.gui.preview_panel_v2 import PreviewPanelV2


def test_preview_panel_stage_order() -> None:
    root = tk.Tk()
    panel = PreviewPanelV2(root)
    class FakeSidebar:
        def get_enabled_stages(self):
            return ["adetailer", "txt2img", "upscale", "img2img"]

    panel.update_from_controls(FakeSidebar())
    assert panel.summary_label.cget("text") == "Stages: txt2img → img2img → ADetailer → upscale"
    root.destroy()
