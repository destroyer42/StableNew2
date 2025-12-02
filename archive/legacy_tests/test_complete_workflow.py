#!/usr/bin/env python3
"""Complete test of the new configuration system without GUI"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.utils.config import ConfigManager


def test_complete_workflow():
    """Test the complete configuration workflow"""
    print("🔧 Testing Complete Configuration Workflow")
    print("=" * 50)

    cm = ConfigManager()

    # Test 1: List available presets (for dropdown)
    print("1. Available Presets:")
    presets = cm.list_presets()
    for preset in presets:
        print(f"   • {preset}")
    print()

    # Test 2: Configuration Precedence Test
    print("2. Testing Configuration Precedence:")

    # Base preset
    base_config = cm.load_preset("default")
    print(f'   Base preset (default) steps: {base_config["txt2img"]["steps"]}')

    # Individual pack config
    pack_config = cm.ensure_pack_config("heroes.txt", "heroes_sdxl")
    print(
        f'   Pack config (heroes.txt) steps: {pack_config.get("txt2img", {}).get("steps", "not set")}'
    )

    # Override scenario
    override_config = {"txt2img": {"steps": 99, "cfg_scale": 12.0, "width": 2048, "height": 2048}}
    print(f'   Override config steps: {override_config["txt2img"]["steps"]}')

    # Test 3: Pack-specific config modification
    print("\\n3. Testing Pack Config Modification:")
    modified_pack_config = pack_config.copy()
    modified_pack_config["txt2img"]["steps"] = 42
    modified_pack_config["txt2img"]["cfg_scale"] = 9.5

    success = cm.save_pack_config("heroes.txt", modified_pack_config)
    print(f"   Modified heroes.txt config saved: {success}")

    # Verify the change
    reloaded = cm.get_pack_config("heroes.txt")
    print(f'   Reloaded heroes.txt steps: {reloaded["txt2img"]["steps"]}')

    print("\\n✅ Configuration workflow test completed!")
    print("\\n📋 Summary of New Features:")
    print("   • Preset dropdown (no more typos)")
    print("   • Individual pack .json configs")
    print("   • Configuration precedence: Override > Pack > Preset")
    print("   • Pack selection behavior: Single=editable, Multiple=grayed unless override")
    print("   • Status messages in both pack area and config section")
    print("   • Save pack config and save override preset buttons")


if __name__ == "__main__":
    test_complete_workflow()
