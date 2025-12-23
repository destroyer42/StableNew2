"""Test that global prompt checkboxes are properly wired to executor flags."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

def test_global_prompt_flag_wiring():
    """Test that global prompt flags are correctly read from sidebar and applied to config."""
    
    # Mock the GUI components
    mock_sidebar = MagicMock()
    mock_main_window = MagicMock()
    mock_main_window.sidebar_panel_v2 = mock_sidebar
    
    # Test Case 1: Both checkboxes enabled
    print("\n=== Test Case 1: Both checkboxes enabled ===")
    mock_sidebar.get_global_positive_config.return_value = {"enabled": True, "text": "masterpiece, best quality"}
    mock_sidebar.get_global_negative_config.return_value = {"enabled": True, "text": "low quality, worst quality"}
    
    from src.controller.app_controller import AppController
    controller = AppController(main_window=mock_main_window, threaded=False)
    
    # Build config
    pack_config = {"pipeline": {}}
    result_config = controller._build_config_snapshot_with_override(pack_config)
    
    # Verify flags are set correctly
    assert "pipeline" in result_config, "Pipeline section missing from config"
    assert result_config["pipeline"]["apply_global_positive_txt2img"] == True, "Global positive should be enabled"
    assert result_config["pipeline"]["apply_global_negative_txt2img"] == True, "Global negative should be enabled"
    print("✅ Both flags correctly set to True")
    
    # Test Case 2: Only positive disabled
    print("\n=== Test Case 2: Positive disabled, negative enabled ===")
    mock_sidebar.get_global_positive_config.return_value = {"enabled": False, "text": "masterpiece, best quality"}
    mock_sidebar.get_global_negative_config.return_value = {"enabled": True, "text": "low quality, worst quality"}
    
    result_config = controller._build_config_snapshot_with_override(pack_config)
    
    assert result_config["pipeline"]["apply_global_positive_txt2img"] == False, "Global positive should be disabled"
    assert result_config["pipeline"]["apply_global_negative_txt2img"] == True, "Global negative should be enabled"
    print("✅ Positive disabled, negative enabled")
    
    # Test Case 3: Both disabled
    print("\n=== Test Case 3: Both checkboxes disabled ===")
    mock_sidebar.get_global_positive_config.return_value = {"enabled": False, "text": "masterpiece, best quality"}
    mock_sidebar.get_global_negative_config.return_value = {"enabled": False, "text": "low quality, worst quality"}
    
    result_config = controller._build_config_snapshot_with_override(pack_config)
    
    assert result_config["pipeline"]["apply_global_positive_txt2img"] == False, "Global positive should be disabled"
    assert result_config["pipeline"]["apply_global_negative_txt2img"] == False, "Global negative should be disabled"
    print("✅ Both flags correctly set to False")
    
    # Test Case 4: No sidebar (defensive case)
    print("\n=== Test Case 4: No sidebar (defensive) ===")
    controller_no_sidebar = AppController(main_window=None, threaded=False)
    result_config = controller_no_sidebar._build_config_snapshot_with_override(pack_config)
    # Should not crash, should use defaults
    print("✅ No crash with missing sidebar")
    
    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED - Global prompt flags correctly wired!")
    print("="*60)

if __name__ == "__main__":
    test_global_prompt_flag_wiring()
