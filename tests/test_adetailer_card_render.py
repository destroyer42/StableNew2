"""Headless-safe smoke coverage for ADetailer stage card construction."""

from __future__ import annotations

import tkinter as tk

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


def test_adetailer_card_constructs_without_entering_mainloop(tk_root: tk.Tk) -> None:
    card = ADetailerStageCardV2(tk_root, collapsible=True, collapse_key="test")
    card.pack(fill="both", expand=True, padx=20, pady=20)
    tk_root.update_idletasks()

    assert card.winfo_exists()
    assert len(list(card.watchable_vars())) > 0
    assert len(card.body_frame.winfo_children()) > 0
