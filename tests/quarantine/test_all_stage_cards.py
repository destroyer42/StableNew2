"""Manual debug script for stage card creation.

Import-safe under pytest collection.
"""

from __future__ import annotations

import tkinter as tk
import traceback


def main() -> None:
    print("Testing all stage cards...")

    try:
        from src.gui.stage_cards_v2.advanced_adetailer_stage_card_v2 import (
            AdvancedADetailerStageCardV2,
        )
        from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import (
            AdvancedImg2ImgStageCardV2,
        )
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import (
            AdvancedTxt2ImgStageCardV2,
        )
        from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import (
            AdvancedUpscaleStageCardV2,
        )

        print("[OK] All imports successful")

        root = tk.Tk()
        root.withdraw()

        cards = {}

        try:
            cards["txt2img"] = AdvancedTxt2ImgStageCardV2(root)
            print("[OK] Txt2Img card created")
        except Exception as exc:
            print(f"[ERR] Txt2Img card failed: {exc}")
            traceback.print_exc()

        try:
            cards["adetailer"] = AdvancedADetailerStageCardV2(root)
            print("[OK] ADetailer card created")
        except Exception as exc:
            print(f"[ERR] ADetailer card failed: {exc}")
            traceback.print_exc()

        try:
            cards["img2img"] = AdvancedImg2ImgStageCardV2(root)
            print("[OK] Img2Img card created")
        except Exception as exc:
            print(f"[ERR] Img2Img card failed: {exc}")
            traceback.print_exc()

        try:
            cards["upscale"] = AdvancedUpscaleStageCardV2(root)
            print("[OK] Upscale card created")
        except Exception as exc:
            print(f"[ERR] Upscale card failed: {exc}")
            traceback.print_exc()

        print(f"\n[OK] Successfully created {len(cards)}/4 cards")
        root.destroy()
    except Exception as exc:
        print(f"[ERR] Fatal error: {exc}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
