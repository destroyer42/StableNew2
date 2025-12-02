"""
Test script for advanced GUI enhancements in StableNew
Tests all new features including advanced prompt editor and enhanced sliders
"""

import sys
import tkinter as tk
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def test_advanced_features():
    """Test all advanced GUI features"""
    print("🧪 TESTING ADVANCED GUI ENHANCEMENTS")
    print("=" * 50)

    # Test 1: Enhanced slider import
    print("1. Testing Enhanced Slider Import...")
    try:
        from src.gui.enhanced_slider import EnhancedSlider

        print("   ✅ EnhancedSlider imported successfully")
    except ImportError as e:
        print(f"   ❌ EnhancedSlider import failed: {e}")
        return False

    # Test 2: Advanced prompt editor import
    print("2. Testing Advanced Prompt Editor Import...")
    try:
        from src.gui.advanced_prompt_editor import AdvancedPromptEditor

        print("   ✅ AdvancedPromptEditor imported successfully")
    except ImportError as e:
        print(f"   ❌ AdvancedPromptEditor import failed: {e}")
        return False

    # Test 3: Main window modifications
    print("3. Testing Main Window Integration...")
    try:
        from src.gui.main_window import StableNewGUI

        print("   ✅ Main window with advanced features imported")
    except ImportError as e:
        print(f"   ❌ Main window import failed: {e}")
        return False

    # Test 4: Configuration manager compatibility
    print("4. Testing Configuration Manager...")
    try:
        from src.utils.config import ConfigManager

        config_manager = ConfigManager()
        config = config_manager.get_default_config()
        print("   ✅ ConfigManager works correctly")
    except Exception as e:
        print(f"   ❌ ConfigManager error: {e}")
        return False

    # Test 5: Enhanced slider widget test
    print("5. Testing Enhanced Slider Widget...")
    try:
        root = tk.Tk()
        root.withdraw()  # Hide main window

        # Create test frame
        frame = tk.Frame(root)
        var = tk.DoubleVar(value=5.0)

        # Test slider creation
        slider = EnhancedSlider(frame, from_=1.0, to=10.0, variable=var, resolution=0.5)

        # Test value setting
        slider.set(7.5)
        assert abs(slider.get() - 7.5) < 0.1, "Slider value setting failed"

        # Test arrow functionality (simulate)
        slider._increase_value()
        assert abs(slider.get() - 8.0) < 0.1, "Slider increment failed"

        slider._decrease_value()
        assert abs(slider.get() - 7.5) < 0.1, "Slider decrement failed"

        root.destroy()
        print("   ✅ Enhanced slider widget works correctly")
    except Exception as e:
        print(f"   ❌ Enhanced slider test failed: {e}")
        return False

    # Test 6: Advanced editor widget test
    print("6. Testing Advanced Prompt Editor Widget...")
    try:
        root = tk.Tk()
        root.withdraw()

        # Create editor instance
        editor = AdvancedPromptEditor(
            parent_window=root, config_manager=config_manager, on_packs_changed=None
        )

        # Test that the editor can be created and has required attributes
        assert hasattr(editor, "embeddings_cache"), "Editor missing embeddings cache"
        assert hasattr(editor, "loras_cache"), "Editor missing LoRAs cache"
        assert hasattr(editor, "open_editor"), "Editor missing open_editor method"

        root.destroy()
        print("   ✅ Advanced prompt editor works correctly")
    except Exception as e:
        print(f"   ❌ Advanced prompt editor test failed: {e}")
        return False

    # Test 7: File structure verification
    print("7. Testing File Structure...")
    required_files = [
        "src/gui/enhanced_slider.py",
        "src/gui/advanced_prompt_editor.py",
        "src/gui/main_window.py",
        "presets/default.json",
    ]

    for file_path in required_files:
        if not Path(file_path).exists():
            print(f"   ❌ Required file missing: {file_path}")
            return False

    print("   ✅ All required files present")

    # Test 8: Integration test - simulate GUI creation
    print("8. Testing Full GUI Integration...")
    try:
        root = tk.Tk()
        root.withdraw()

        # Create GUI instance (don't start mainloop)
        gui = StableNewGUI()

        # Test that advanced editor can be created
        assert hasattr(gui, "_open_prompt_editor"), "Advanced editor method missing"

        # Test enhanced sliders are in place
        enhanced_slider_count = 0
        for widget_dict in [gui.txt2img_widgets, gui.img2img_widgets, gui.upscale_widgets]:
            for widget in widget_dict.values():
                if isinstance(widget, EnhancedSlider):
                    enhanced_slider_count += 1

        assert (
            enhanced_slider_count >= 5
        ), f"Expected at least 5 enhanced sliders, found {enhanced_slider_count}"

        root.destroy()
        print(f"   ✅ GUI integration successful - {enhanced_slider_count} enhanced sliders found")
    except Exception as e:
        print(f"   ❌ GUI integration test failed: {e}")
        return False

    return True


def print_feature_summary():
    """Print summary of implemented features"""
    print("\n🎉 ADVANCED FEATURES IMPLEMENTED")
    print("=" * 50)

    features = [
        "Enhanced Sliders with Arrow Controls",
        "  • CFG Scale sliders (txt2img, img2img)",
        "  • Denoising Strength sliders (all tabs)",
        "  • GFPGAN visibility slider",
        "  • CodeFormer sliders (visibility & weight)",
        "  • HR Denoising slider",
        "",
        "Advanced Prompt Pack Editor",
        "  • Multi-tab interface (Prompts, Global Negative, Validation, Models, Help)",
        "  • Real-time validation with error/warning highlighting",
        "  • Embedding & LoRA auto-discovery and validation",
        "  • Format support (TXT block-based, TSV tab-separated)",
        "  • Quick insert templates and model browser",
        "  • Clone, delete, and pack management features",
        "  • Auto-fix common issues (typos, syntax errors)",
        "  • Global negative prompt editor",
        "",
        "Validation Engine",
        "  • Missing model detection",
        "  • Syntax error checking",
        "  • Weight range validation",
        "  • Common typo detection and correction",
        "  • Prompt statistics and analytics",
        "",
        "User Interface Improvements",
        "  • Dark theme consistency across all components",
        "  • Improved button layouts and icons",
        "  • Enhanced tooltips and help system",
        "  • Real-time status updates and progress indicators",
    ]

    for feature in features:
        if feature.startswith("  •"):
            print(f"    {feature[3:]}")
        elif feature.startswith("  "):
            print(f"  {feature[2:]}")
        elif feature == "":
            print()
        else:
            print(f"📋 {feature}")


if __name__ == "__main__":
    success = test_advanced_features()

    if success:
        print("\n✅ ALL TESTS PASSED!")
        print_feature_summary()
        print("\n🚀 Advanced GUI enhancements are ready for use!")
        print("\nTo use:")
        print("  python -m src.main")
        print("  Click 'Advanced Editor' to access the new prompt editor")
        print("  Use arrow buttons on sliders for precise control")
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("Please check the errors above and fix any issues.")
        sys.exit(1)
