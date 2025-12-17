from __future__ import annotations

from src.gui.views.stage_cards_panel_v2 import StageCardsPanel
from src.gui.zone_map_v2 import get_pipeline_stage_order


def test_stage_cards_panel_follows_zone_map_order(tk_root) -> None:
    panel = StageCardsPanel(tk_root, controller=None, theme=None)
    expected_order = [
        stage for stage in get_pipeline_stage_order() if hasattr(panel, f"{stage}_card")
    ]
    assert panel.stage_order == expected_order
    for idx, stage_name in enumerate(panel.stage_order):
        card = getattr(panel, f"{stage_name}_card")
        assert card.grid_info().get("row") == idx
