"""Quick test to see if pipeline tab renders."""
import tkinter as tk
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    root = tk.Tk()
    root.title("Pipeline Tab Test")
    root.geometry("800x600")
    
    # Try to create the full pipeline tab
    from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
    from src.gui.app_state_v2 import AppStateV2
    
    app_state = AppStateV2()
    
    tab = PipelineTabFrame(root, app_state=app_state)
    tab.pack(fill="both", expand=True)
    
    print("✓ Pipeline tab created successfully")
    print(f"✓ Tab has {len(tab.winfo_children())} immediate children")
    
    # Check if stage cards panel was created
    for child in tab.winfo_children():
        print(f"  - {child.__class__.__name__}: {len(child.winfo_children())} children")
    
    root.after(2000, root.destroy)  # Auto-close after 2 seconds
    root.mainloop()
    
    print("✓ Test completed successfully")
    sys.exit(0)
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
