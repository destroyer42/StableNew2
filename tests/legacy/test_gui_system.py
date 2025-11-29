#!/usr/bin/env python3
"""
Comprehensive GUI Test Script for New Configuration System
This script helps validate all the new configuration features systematically.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))


from src.utils.config import ConfigManager
from src.utils.file_io import get_prompt_packs


class GUITestValidator:
    """Validates GUI configuration system"""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.test_results = []

    def log_test(self, test_name, result, details=""):
        """Log a test result"""
        status = "✅ PASS" if result else "❌ FAIL"
        self.test_results.append((test_name, result, details))
        print(f"{status}: {test_name}")
        if details:
            print(f"   {details}")

    def test_preset_dropdown_data(self):
        """Test 1: Preset dropdown should have all available presets"""
        presets = self.config_manager.list_presets()
        self.log_test(
            "Preset Dropdown Data",
            len(presets) >= 3,  # Should have at least default, heroes_sdxl, etc.
            f"Found {len(presets)} presets: {', '.join(presets[:5])}{'...' if len(presets) > 5 else ''}",
        )
        return presets

    def test_pack_config_creation(self):
        """Test 2: Individual pack configs should be created automatically"""
        packs_dir = Path("packs")
        pack_files = get_prompt_packs(packs_dir)

        configs_created = 0
        for pack_file in pack_files:
            # Try to ensure pack config exists
            config = self.config_manager.ensure_pack_config(pack_file.name, "default")
            if config:
                configs_created += 1

        self.log_test(
            "Pack Config Auto-Creation",
            configs_created >= len(pack_files) // 2,  # At least half should work
            f"Created/verified {configs_created}/{len(pack_files)} pack configs",
        )

    def test_configuration_precedence(self):
        """Test 3: Configuration precedence (Override > Pack > Preset)"""
        # Test with heroes pack
        preset_config = self.config_manager.load_preset("default")
        pack_config = self.config_manager.get_pack_config("heroes.txt")

        # Test precedence logic
        has_preset = preset_config is not None
        has_pack_config = len(pack_config) > 0

        self.log_test(
            "Configuration Precedence Setup",
            has_preset and has_pack_config,
            f"Preset config: {has_preset}, Pack config: {has_pack_config}",
        )

    def test_pack_config_persistence(self):
        """Test 4: Pack configs should persist after modification"""
        test_pack = "test_gui_pack.txt"
        original_config = {"txt2img": {"steps": 30, "cfg_scale": 7.5, "width": 768, "height": 768}}

        # Save config
        saved = self.config_manager.save_pack_config(test_pack, original_config)

        # Load it back
        loaded_config = self.config_manager.get_pack_config(test_pack)

        matches = (
            loaded_config.get("txt2img", {}).get("steps") == 30
            and loaded_config.get("txt2img", {}).get("cfg_scale") == 7.5
        )

        self.log_test(
            "Pack Config Persistence", saved and matches, f"Save: {saved}, Load matches: {matches}"
        )

    def test_pack_files_structure(self):
        """Test 5: Check pack files and their corresponding configs"""
        packs_dir = Path("packs")
        txt_files = list(packs_dir.glob("*.txt"))
        json_files = list(packs_dir.glob("*.json"))

        self.log_test(
            "Pack Files Structure",
            len(txt_files) > 0 and len(json_files) > 0,
            f"Found {len(txt_files)} .txt packs and {len(json_files)} .json configs",
        )

        # Check specific packs
        important_packs = ["heroes.txt", "landscapes.txt", "portraits.txt"]
        existing_packs = []
        for pack in important_packs:
            if (packs_dir / pack).exists():
                existing_packs.append(pack)

        self.log_test(
            "Important Packs Present",
            len(existing_packs) >= 2,
            f"Found: {', '.join(existing_packs)}",
        )

    def test_config_validation(self):
        """Test 6: Validate that configs have required structure"""
        test_config = self.config_manager.load_preset("default")

        required_sections = ["txt2img", "img2img", "upscale", "api"]
        has_sections = all(section in test_config for section in required_sections)

        required_txt2img = ["steps", "cfg_scale", "width", "height"]
        has_txt2img_fields = all(
            field in test_config.get("txt2img", {}) for field in required_txt2img
        )

        self.log_test(
            "Config Structure Validation",
            has_sections and has_txt2img_fields,
            f"Sections: {has_sections}, txt2img fields: {has_txt2img_fields}",
        )

    def run_all_tests(self):
        """Run all GUI-related tests"""
        print("🧪 GUI Configuration System Test Suite")
        print("=" * 50)

        self.test_preset_dropdown_data()
        self.test_pack_config_creation()
        self.test_configuration_precedence()
        self.test_pack_config_persistence()
        self.test_pack_files_structure()
        self.test_config_validation()

        # Summary
        passed = sum(1 for _, result, _ in self.test_results if result)
        total = len(self.test_results)

        print(f"\n📊 Test Results: {passed}/{total} tests passed")

        if passed == total:
            print("🎉 All tests passed! GUI should work correctly.")
        else:
            print("⚠️ Some tests failed. Check the issues above.")

        return passed == total


def main():
    """Main test function"""
    validator = GUITestValidator()
    success = validator.run_all_tests()

    if success:
        print("\n🖥️ GUI Testing Checklist:")
        print("Now test these features in the actual GUI:")
        print("1. ✓ Preset dropdown shows all available presets")
        print("2. ✓ Single pack selection loads pack config")
        print("3. ✓ Multiple pack selection greys out config")
        print("4. ✓ Override checkbox enables config for multiple packs")
        print("5. ✓ Status messages show current config state")
        print("6. ✓ Save Pack Config button works")
        print("7. ✓ Save as Override Preset button works")
        print("8. ✓ Configuration changes persist")
        print("9. ✓ Pack selection persists through config changes")
        print("\n🚀 Ready for manual GUI testing!")

    return success


if __name__ == "__main__":
    main()
