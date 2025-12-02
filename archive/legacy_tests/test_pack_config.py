#!/usr/bin/env python3
"""Test the new pack configuration system"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.utils.config import ConfigManager


def test_pack_config_system():
    """Test pack config functionality"""
    cm = ConfigManager()

    # Test 1: Ensure pack config exists
    config = cm.ensure_pack_config("heroes.txt", "default")
    assert len(config) > 0

    # Test 2: Save pack config
    test_config = {"txt2img": {"steps": 25, "cfg_scale": 8.0, "width": 1024, "height": 1024}}
    success = cm.save_pack_config("test_pack.txt", test_config)
    assert success

    # Test 3: Load pack config
    loaded = cm.get_pack_config("test_pack.txt")
    steps_match = loaded.get("txt2img", {}).get("steps") == 25
    assert steps_match

    # Test 4: Check file was created
    config_file = Path("packs/test_pack.json")
    assert config_file.exists()
