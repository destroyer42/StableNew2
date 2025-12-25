"""Minimal test to check if ADetailer card renders."""

import tkinter as tk
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


def test_card_render():
    root = tk.Tk()
    root.title("ADetailer Card Test")
    root.geometry("600x800")
    
    try:
        card = ADetailerStageCardV2(root, collapsible=True, collapse_key="test")
        card.pack(fill="both", expand=True, padx=20, pady=20)
        
        print("✓ Card created successfully")
        print(f"✓ Card has {len(list(card.watchable_vars()))} watchable variables")
        print(f"✓ Body frame children: {len(card.body_frame.winfo_children())}")
        
        # Keep window open for visual inspection
        root.mainloop()
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(test_card_render())
