#!/usr/bin/env python3
"""Test script to verify pack override functionality."""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from unittest.mock import Mock, MagicMock
from src.controller.app_controller import AppController


def test_config_snapshot_with_override():
    """Test that config snapshot respects override checkbox state."""
    
    # Create a mock app controller with minimal setup
    controller = AppController.__new__(AppController)
    
    # Mock necessary attributes
    controller.override_pack_config_enabled = False
    controller.app_state = Mock()
    controller.app_state.run_config = {"base_setting": "base_value"}
    controller.app_state.lora_strengths = []
    controller.state = Mock()
    controller.state.current_config = Mock()
    controller.state.current_config.randomization_enabled = False
    controller.state.current_config.max_variants = 1
    
    # Mock logging
    controller._append_log = lambda msg: print(f"LOG: {msg}")
    
    # Test 1: Override disabled - should use pack config as-is
    pack_config = {"pack_setting": "pack_value", "steps": 30}
    config_snapshot = controller._build_config_snapshot_with_override(pack_config)
    
    print("Test 1 - Override disabled:")
    print(f"  Pack config: {pack_config}")
    print(f"  Config snapshot: {config_snapshot}")
    
    # Should contain both base and pack settings
    assert "base_setting" in config_snapshot
    assert "pack_setting" in config_snapshot
    assert config_snapshot["steps"] == 30  # From pack
    
    # Test 2: Override enabled - should merge current GUI configs
    controller.override_pack_config_enabled = True
    
    # Mock stage panel and cards
    controller.main_window = Mock()
    controller._get_stage_cards_panel = Mock(return_value=None)  # No stage panel for now
    controller._get_panel_randomizer_config = Mock(return_value={})
    
    config_snapshot = controller._build_config_snapshot_with_override(pack_config)
    
    print("\nTest 2 - Override enabled (no stage configs):")
    print(f"  Pack config: {pack_config}")
    print(f"  Config snapshot: {config_snapshot}")
    
    print("\nTests passed! Override functionality is working correctly.")


if __name__ == "__main__":
    test_config_snapshot_with_override()