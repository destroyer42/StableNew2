"""Test PipelineTabFrame creation to find the exact error."""
import tkinter as tk
from tkinter import ttk
import traceback

print("Testing PipelineTabFrame creation...")

try:
    from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
    print("[OK] Imported PipelineTabFrame")
    
    root = tk.Tk()
    root.title("PipelineTabFrame Test")
    root.geometry("1200x800")
    
    # Try to create the pipeline tab
    print("Creating PipelineTabFrame...")
    tab = PipelineTabFrame(root)
    print("[OK] PipelineTabFrame created successfully!")
    
    tab.pack(fill="both", expand=True)
    
    print("\nPipeline tab should be visible. Close window to exit.")
    root.mainloop()
    
except Exception as e:
    print(f"\n[ERROR] creating PipelineTabFrame: {e}")
    print("\nFull traceback:")
    traceback.print_exc()
