"""Manual debug script for StageCardsPanel creation.

Import-safe under pytest collection.
"""

from __future__ import annotations

import tkinter as tk
import traceback


def main() -> None:
    print("Starting stage cards test...")

    try:
        from src.gui.views.stage_cards_panel_v2 import StageCardsPanel

        print("[OK] Imported StageCardsPanel")

        root = tk.Tk()
        print("[OK] Created Tk root")

        panel = StageCardsPanel(root)
        print("[OK] Created StageCardsPanel")
        print(f"  Stage cards: {list(panel._stage_cards.keys())}")
        print(f"  Stage order: {panel.stage_order}")

        for stage_name in ["txt2img", "img2img", "adetailer", "upscale"]:
            card = getattr(panel, f"{stage_name}_card", None)
            print(f"  {'[OK]' if card else '[ERR]'} {stage_name}_card")
        root.destroy()
    except Exception as exc:
        print(f"[ERR] ERROR: {exc}")
        traceback.print_exc()

    print("\nTest complete.")


if __name__ == "__main__":
    main()
