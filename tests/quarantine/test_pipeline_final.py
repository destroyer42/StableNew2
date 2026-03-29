"""Manual final integration script for PipelineTabFrame.

Import-safe under pytest collection.
"""

from __future__ import annotations

import tkinter as tk


def main() -> None:
    print("=" * 60)
    print("FINAL INTEGRATION TEST - Pipeline Tab")
    print("=" * 60)

    try:
        print("\n1. Importing PipelineTabFrame...")
        from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

        print("   [OK] Import successful")

        print("\n2. Creating Tk root...")
        root = tk.Tk()
        root.title("Pipeline Tab - Final Test")
        root.geometry("1400x900")
        print("   [OK] Root created")

        print("\n3. Creating PipelineTabFrame...")
        tab = PipelineTabFrame(root)
        print("   [OK] PipelineTabFrame created")

        print("\n4. Checking components...")
        if hasattr(tab, "stage_cards_panel"):
            panel = tab.stage_cards_panel
            print("   [OK] stage_cards_panel exists")
            print(f"   [OK] Stage cards: {list(panel._stage_cards.keys())}")
        else:
            print("   [WARN] stage_cards_panel not found")

        if hasattr(tab, "running_job_panel"):
            print("   [OK] running_job_panel exists")
        else:
            print("   [WARN] running_job_panel not found")

        print("\n5. Packing tab...")
        tab.pack(fill="both", expand=True)
        print("   [OK] Tab packed")

        print("\n" + "=" * 60)
        print("SUCCESS! Pipeline tab should be visible.")
        print("Close window to exit test.")
        root.mainloop()
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        import traceback

        traceback.print_exc()
        print("\n" + "=" * 60)
        print("TEST FAILED")
        print("=" * 60)


if __name__ == "__main__":
    main()
