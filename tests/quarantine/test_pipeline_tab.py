"""Manual PipelineTabFrame creation script.

Import-safe under pytest collection.
"""

from __future__ import annotations

import tkinter as tk
import traceback


def main() -> None:
    print("Testing PipelineTabFrame creation...")

    try:
        from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

        print("[OK] Imported PipelineTabFrame")

        root = tk.Tk()
        root.title("PipelineTabFrame Test")
        root.geometry("1200x800")

        print("Creating PipelineTabFrame...")
        tab = PipelineTabFrame(root)
        print("[OK] PipelineTabFrame created successfully")

        tab.pack(fill="both", expand=True)

        print("\nPipeline tab should be visible. Close window to exit.")
        root.mainloop()
    except Exception as exc:
        print(f"\n[ERROR] creating PipelineTabFrame: {exc}")
        print("\nFull traceback:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
