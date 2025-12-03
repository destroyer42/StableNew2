from __future__ import annotations

import pytest

from tests.helpers.gui_harness_v2 import GuiV2Harness


@pytest.mark.gui
def test_stage_cards_have_single_header(tk_root: object) -> None:
    harness = GuiV2Harness(tk_root)
    panel = getattr(harness.pipeline_tab, "stage_cards_panel", None)
    assert panel is not None
    header_labels = [
        child.title_label
        for child in panel.winfo_children()
        if hasattr(child, "title_label")
    ]
    assert len(header_labels) == len(panel.stage_order)
    assert all(label.winfo_ismapped() for label in header_labels)
    harness.cleanup()
