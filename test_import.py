#!/usr/bin/env python
"""Quick test to verify imports work."""

try:
    print("Testing theme_v2 import...")
    from src.gui.theme_v2 import SURFACE_FRAME_STYLE, BODY_LABEL_STYLE
    print(f"✓ SURFACE_FRAME_STYLE = {SURFACE_FRAME_STYLE}")
    print(f"✓ BODY_LABEL_STYLE = {BODY_LABEL_STYLE}")
    
    print("\nTesting advanced_upscale_stage_card_v2 import...")
    from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
    print("✓ AdvancedUpscaleStageCardV2 imported successfully")
    
    print("\n✅ All imports successful!")
except Exception as e:
    print(f"\n❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
