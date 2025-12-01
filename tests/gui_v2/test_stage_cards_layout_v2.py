from __future__ import annotations

import pytest

from src.gui.views.stage_cards_panel_v2 import StageCardsPanel


@pytest.mark.gui
def test_stage_cards_have_single_header(tk_root: object) -> None:
    panel = StageCardsPanel(tk_root)
    header_labels = [
        child.title_label
        for child in panel.winfo_children()
        if hasattr(child, "title_label")
    ]
    assert len(header_labels) == len(panel.stage_order)
    assert all(label.winfo_ismapped() for label in header_labels)
