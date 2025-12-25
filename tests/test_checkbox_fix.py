"""Simple verification that global prompt checkboxes are properly wired."""

import logging
from unittest.mock import MagicMock

logging.basicConfig(level=logging.WARNING)

def verify_fix():
    """Verify that controller correctly reads sidebar checkboxes and sets config flags."""
    
    print("\n" + "="*80)
    print("VERIFICATION: Global Prompt Checkbox Fix")
    print("="*80)
    
    from src.controller.app_controller import AppController
    
    # Mock GUI with sidebar
    mock_sidebar = MagicMock()
    mock_main_window = MagicMock()
    mock_main_window.sidebar_panel_v2 = mock_sidebar
    
    controller = AppController(main_window=mock_main_window, threaded=False)
    
    # Test all 4 combinations of checkbox states
    test_cases = [
        ("Both ON", True, True),
        ("Both OFF", False, False),
        ("Positive ON, Negative OFF", True, False),
        ("Positive OFF, Negative ON", False, True),
    ]
    
    print("\n📋 Testing all checkbox combinations:\n")
    
    for name, pos_enabled, neg_enabled in test_cases:
        # Set mock checkbox states
        mock_sidebar.get_global_positive_config.return_value = {
            "enabled": pos_enabled,
            "text": "masterpiece"
        }
        mock_sidebar.get_global_negative_config.return_value = {
            "enabled": neg_enabled,
            "text": "nsfw"
        }
        
        # Build config
        config = controller._build_config_snapshot_with_override({"pipeline": {}})
        
        # Verify flags
        actual_pos = config["pipeline"]["apply_global_positive_txt2img"]
        actual_neg = config["pipeline"]["apply_global_negative_txt2img"]
        
        status_pos = "✅" if actual_pos == pos_enabled else "❌"
        status_neg = "✅" if actual_neg == neg_enabled else "❌"
        
        print(f"  {name:30} → Positive: {status_pos} {actual_pos}  Negative: {status_neg} {actual_neg}")
        
        assert actual_pos == pos_enabled, f"{name}: Positive flag mismatch"
        assert actual_neg == neg_enabled, f"{name}: Negative flag mismatch"
    
    print("\n" + "="*80)
    print("✅ ALL TESTS PASSED")
    print("="*80)
    print("\n📝 What was fixed:")
    print("   BEFORE: Global prompts were ALWAYS applied (checkboxes ignored)")
    print("   AFTER:  Global prompts only applied when checkboxes are checked")
    print("\n🔧 Implementation:")
    print("   1. app_controller.py: Added _add_global_prompt_flags() method")
    print("   2. Calls sidebar.get_global_positive_config() and get_global_negative_config()")
    print("   3. Sets apply_global_positive_txt2img and apply_global_negative_txt2img flags")
    print("   4. executor.py: Already using separate flags (previously fixed)")
    print("\n✨ Result: Checkboxes now control prompt application!\n")

if __name__ == "__main__":
    verify_fix()
