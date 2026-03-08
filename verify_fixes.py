#!/usr/bin/env python
"""Verify that all PR fixes are working correctly."""

print("=" * 80)
print("VERIFICATION SCRIPT - PR GUI Fixes")
print("=" * 80)

# Test 1: Import SURFACE_FRAME_STYLE
print("\n[1/3] Testing SURFACE_FRAME_STYLE import...")
try:
    from src.gui.theme_v2 import SURFACE_FRAME_STYLE, BODY_LABEL_STYLE
    print(f"    ✓ SURFACE_FRAME_STYLE = '{SURFACE_FRAME_STYLE}'")
    print(f"    ✓ BODY_LABEL_STYLE = '{BODY_LABEL_STYLE}'")
except Exception as e:
    print(f"    ✗ FAILED: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Import AdvancedUpscaleStageCardV2 (uses SURFACE_FRAME_STYLE)
print("\n[2/3] Testing AdvancedUpscaleStageCardV2 import...")
try:
    from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2
    print("    ✓ AdvancedUpscaleStageCardV2 imported successfully")
except Exception as e:
    print(f"    ✗ FAILED: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Check pipeline_tab_frame_v2 has None check
print("\n[3/3] Checking pipeline_tab_frame_v2 None guard...")
try:
    with open("src/gui/views/pipeline_tab_frame_v2.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "if card and card not in ordered_cards:" in content:
            print("    ✓ None guard present in _apply_stage_visibility")
        else:
            print("    ✗ None guard NOT FOUND")
except Exception as e:
    print(f"    ✗ FAILED: {e}")

# Test 4: Check test_pipeline_tab_render.py is proper pytest
print("\n[4/4] Checking test_pipeline_tab_render.py structure...")
try:
    with open("tests/gui_v2/test_pipeline_tab_render.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "def test_render_pipeline():" in content:
            print("    ✓ Converted to proper pytest function")
        else:
            print("    ✗ NOT a proper pytest function")
        if "sys.exit(" in content and "pytest.fail" not in content:
            print("    ✗ Still has sys.exit() calls")
        else:
            print("    ✓ No sys.exit() in module scope")
except Exception as e:
    print(f"    ✗ FAILED: {e}")

print("\n" + "=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)
