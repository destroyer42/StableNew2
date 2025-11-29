from __future__ import annotations

import pytest


def test_base_stage_card_v2_smoke():
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - Tk may be unavailable
        pytest.skip(f"Tk not available: {exc}")

    from src.gui.stage_cards_v2.base_stage_card_v2 import BaseStageCardV2

    class DummyCard(BaseStageCardV2):
        def _build_body(self, parent):
            pass

    root = tk.Tk()
    try:
        card = DummyCard(root, title="Dummy")
        assert card._title == "Dummy"
    finally:
        try:
            card.destroy()
        except Exception:
            pass
        root.destroy()
