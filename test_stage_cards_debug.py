"""Debug script to test stage cards creation."""
import sys
import traceback
import tkinter as tk

print("Starting stage cards test...")

try:
    from src.gui.views.stage_cards_panel_v2 import StageCardsPanel
    print("✓ Imported StageCardsPanel")
    
    root = tk.Tk()
    print("✓ Created Tk root")
    
    panel = StageCardsPanel(root)
    print(f"✓ Created StageCardsPanel")
    print(f"  Stage cards: {list(panel._stage_cards.keys())}")
    print(f"  Stage order: {panel.stage_order}")
    
    # Check if cards exist
    for stage_name in ["txt2img", "img2img", "adetailer", "upscale"]:
        card = getattr(panel, f"{stage_name}_card", None)
        if card:
            print(f"  ✓ {stage_name}_card exists")
        else:
            print(f"  ✗ {stage_name}_card missing")
    
except Exception as e:
    print(f"✗ ERROR: {e}")
    traceback.print_exc()

print("\nTest complete.")
