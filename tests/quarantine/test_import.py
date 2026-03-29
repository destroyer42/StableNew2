#!/usr/bin/env python
"""Manual import smoke script.

Import-safe under pytest collection.
"""

from __future__ import annotations


def main() -> None:
    try:
        print("Testing theme_v2 import...")
        from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE

        print(f"[OK] SURFACE_FRAME_STYLE = {SURFACE_FRAME_STYLE}")
        print(f"[OK] BODY_LABEL_STYLE = {BODY_LABEL_STYLE}")

        print("\nTesting advanced_upscale_stage_card_v2 import...")
        from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import (
            AdvancedUpscaleStageCardV2,
        )

        print(f"[OK] {AdvancedUpscaleStageCardV2.__name__} imported successfully")
        print("\n[OK] All imports successful")
    except Exception as exc:
        print(f"\n[ERR] Import failed: {exc}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
