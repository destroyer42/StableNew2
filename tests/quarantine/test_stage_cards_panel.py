"""Manual visibility script for StageCardsPanel.

Import-safe under pytest collection.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def main() -> None:
    print("Testing StageCardsPanel...")

    try:
        from src.gui.views.stage_cards_panel_v2 import StageCardsPanel

        print("[OK] Imported StageCardsPanel")

        root = tk.Tk()
        root.title("StageCardsPanel Test")
        root.geometry("800x600")

        container = ttk.Frame(root, padding=10)
        container.pack(fill="both", expand=True)

        panel = StageCardsPanel(container)
        panel.pack(fill="both", expand=True)

        print("[OK] StageCardsPanel created")
        print(f"  Stage cards: {list(panel._stage_cards.keys())}")
        print(f"  Stage order: {panel.stage_order}")

        for stage_name, card in panel._stage_cards.items():
            print(f"  {stage_name} grid: {card.grid_info()}")

        print("\nWindow should be visible with stage cards. Close window to exit.")
        root.mainloop()
    except Exception as exc:
        print(f"[ERR] ERROR: {exc}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
