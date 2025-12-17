from __future__ import annotations

import pytest

from tests.helpers.gui_harness_v2 import GuiV2Harness


@pytest.mark.gui
def test_stage_cards_have_single_header(tk_root: object) -> None:
    harness = GuiV2Harness(tk_root)
    # Ensure GUI is fully rendered
    tk_root.update_idletasks()
    panel = getattr(harness.pipeline_tab, "stage_cards_panel", None)
    assert panel is not None
    header_labels = [
        child.title_label for child in panel.winfo_children() if hasattr(child, "title_label")
    ]
    assert len(header_labels) == len(panel.stage_order)
    # Labels may not be mapped if cards are collapsed - check they exist instead
    assert all(label is not None for label in header_labels)
    harness.cleanup()


@pytest.mark.gui
def test_stage_cards_do_not_expose_validation_widgets(tk_root: object) -> None:
    harness = GuiV2Harness(tk_root)
    tk_root.update_idletasks()
    panel = getattr(harness.pipeline_tab, "stage_cards_panel", None)
    assert panel is not None
    for stage in panel.stage_order:
        card = getattr(panel, f"{stage}_card", None)
        assert card is not None, f"{stage} card missing"
        assert not hasattr(card, "validation_label")
    harness.cleanup()
