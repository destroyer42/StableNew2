"""Test all stage cards creation to find which one fails."""
import sys
import traceback
import tkinter as tk

print("Testing all stage cards...")

try:
    # Test each card individually
    from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
    from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
    from src.gui.stage_cards_v2.advanced_img2img_stage_card_v2 import AdvancedImg2ImgStageCardV2
    from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
    
    print("✓ All imports successful")
    
    root = tk.Tk()
    root.withdraw()  # Hide the window
    
    cards = {}
    
    # Test Txt2Img
    try:
        cards['txt2img'] = AdvancedTxt2ImgStageCardV2(root)
        print("✓ Txt2Img card created")
    except Exception as e:
        print(f"✗ Txt2Img card failed: {e}")
        traceback.print_exc()
    
    # Test ADetailer
    try:
        cards['adetailer'] = ADetailerStageCardV2(root)
        print("✓ ADetailer card created")
    except Exception as e:
        print(f"✗ ADetailer card failed: {e}")
        traceback.print_exc()
    
    # Test Img2Img
    try:
        cards['img2img'] = AdvancedImg2ImgStageCardV2(root)
        print("✓ Img2Img card created")
    except Exception as e:
        print(f"✗ Img2Img card failed: {e}")
        traceback.print_exc()
    
    # Test Upscale
    try:
        cards['upscale'] = AdvancedUpscaleStageCardV2(root)
        print("✓ Upscale card created")
    except Exception as e:
        print(f"✗ Upscale card failed: {e}")
        traceback.print_exc()
    
    print(f"\n✓ Successfully created {len(cards)}/4 cards")
    
except Exception as e:
    print(f"✗ Fatal error: {e}")
    traceback.print_exc()
