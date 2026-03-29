"""Manual render smoke script for the pipeline tab.

Import-safe under pytest collection.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        root = tk.Tk()
        root.title("Pipeline Tab Test")
        root.geometry("800x600")

        from src.gui.app_state_v2 import AppStateV2
        from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

        app_state = AppStateV2()
        tab = PipelineTabFrame(root, app_state=app_state)
        tab.pack(fill="both", expand=True)

        print("[OK] Pipeline tab created successfully")
        print(f"[OK] Tab has {len(tab.winfo_children())} immediate children")

        for child in tab.winfo_children():
            print(f"  - {child.__class__.__name__}: {len(child.winfo_children())} children")

        root.after(2000, root.destroy)
        root.mainloop()

        print("[OK] Test completed successfully")
        sys.exit(0)
    except Exception as exc:
        print(f"[ERR] Error: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
