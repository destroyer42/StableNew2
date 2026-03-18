"""Smoke test: ADetailer card renders without error.

Uses the shared tk_root fixture so no window is left open.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


@pytest.mark.gui
def test_card_render(tk_root: tk.Tk) -> None:
    card = ADetailerStageCardV2(tk_root, collapsible=True, collapse_key="test")
    card.pack(fill="both", expand=True, padx=20, pady=20)
    assert isinstance(card, ADetailerStageCardV2)
    assert len(list(card.watchable_vars())) >= 0
    assert card.body_frame is not None
    card.destroy()
