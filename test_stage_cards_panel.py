"""Test StageCardsPanel creation and visibility."""
import tkinter as tk
from tkinter import ttk

print("Testing StageCardsPanel...")

try:
    from src.gui.views.stage_cards_panel_v2 import StageCardsPanel
    print("✓ Imported StageCardsPanel")
    
    root = tk.Tk()
    root.title("StageCardsPanel Test")
    root.geometry("800x600")
    
    # Create container frame
    container = ttk.Frame(root, padding=10)
    container.pack(fill="both", expand=True)
    
    # Create panel
    panel = StageCardsPanel(container)
    panel.pack(fill="both", expand=True)
    
    print(f"✓ StageCardsPanel created")
    print(f"  Stage cards: {list(panel._stage_cards.keys())}")
    print(f"  Stage order: {panel.stage_order}")
    
    # Check if cards are visible
    for stage_name, card in panel._stage_cards.items():
        grid_info = card.grid_info()
        print(f"  {stage_name} grid: {grid_info}")
    
    print("\nWindow should be visible with stage cards. Close window to exit.")
    root.mainloop()
    
except Exception as e:
    print(f"✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
