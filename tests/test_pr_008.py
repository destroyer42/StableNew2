"""Test PR-008: ADetailer Two-Pass Controls & Advanced Settings."""

import sys
from pathlib import Path
import tkinter as tk

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2


def test_pr_008_new_variables():
    """Test that all PR-008 variables exist and have correct defaults."""
    print("\n=== Testing PR-008: New Variables ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        card = ADetailerStageCardV2(root)
        
        # Test two-pass controls
        assert hasattr(card, 'enable_face_pass_var'), "Missing enable_face_pass_var"
        assert card.enable_face_pass_var.get() == True, "Face pass should be enabled by default"
        
        assert hasattr(card, 'face_model_var'), "Missing face_model_var"
        assert card.face_model_var.get() == "face_yolov8n.pt", "Wrong face model default"
        
        assert hasattr(card, 'face_padding_var'), "Missing face_padding_var"
        assert card.face_padding_var.get() == 32, "Wrong face padding default"
        
        assert hasattr(card, 'enable_hands_pass_var'), "Missing enable_hands_pass_var"
        assert card.enable_hands_pass_var.get() == False, "Hands pass should be disabled by default"
        
        assert hasattr(card, 'hands_model_var'), "Missing hands_model_var"
        assert card.hands_model_var.get() == "hand_yolov8n.pt", "Wrong hands model default"
        
        assert hasattr(card, 'hands_padding_var'), "Missing hands_padding_var"
        assert card.hands_padding_var.get() == 32, "Wrong hands padding default"
        
        print("✓ Two-pass control variables exist with correct defaults")
        
        # Test mask filter controls
        assert hasattr(card, 'mask_filter_method_var'), "Missing mask_filter_method_var"
        assert card.mask_filter_method_var.get() == "largest", "Wrong filter method default"
        
        assert hasattr(card, 'mask_k_largest_var'), "Missing mask_k_largest_var"
        assert card.mask_k_largest_var.get() == 3, "Wrong mask k default"
        
        assert hasattr(card, 'mask_min_ratio_var'), "Missing mask_min_ratio_var"
        assert card.mask_min_ratio_var.get() == 0.01, "Wrong min ratio default"
        
        assert hasattr(card, 'mask_max_ratio_var'), "Missing mask_max_ratio_var"
        assert card.mask_max_ratio_var.get() == 1.0, "Wrong max ratio default"
        
        print("✓ Mask filter control variables exist with correct defaults")
        
        # Test mask processing controls
        assert hasattr(card, 'dilate_erode_var'), "Missing dilate_erode_var"
        assert card.dilate_erode_var.get() == 4, "Wrong dilate/erode default"
        
        assert hasattr(card, 'mask_feather_var'), "Missing mask_feather_var"
        assert card.mask_feather_var.get() == 5, "Wrong feather default"
        
        print("✓ Mask processing control variables exist with correct defaults")
        
        # Test scheduler control
        assert hasattr(card, 'scheduler_var'), "Missing scheduler_var"
        assert card.scheduler_var.get() == "Use sampler default", "Wrong scheduler default"
        
        print("✓ Scheduler control variable exists with correct default")
        
    finally:
        root.destroy()


def test_pr_008_gui_widgets():
    """Test that all PR-008 GUI widgets were created."""
    print("\n=== Testing PR-008: GUI Widgets ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        card = ADetailerStageCardV2(root)
        
        # Check comboboxes
        assert card._face_model_combo is not None, "Face model combo not created"
        assert card._hands_model_combo is not None, "Hands model combo not created"
        assert card._scheduler_combo is not None, "Scheduler combo not created"
        
        print("✓ All new comboboxes created")
        
        # Verify combobox values
        face_values = card._face_model_combo.cget("values")
        assert "face_yolov8n.pt" in face_values, "Missing face model option"
        assert "face_yolov8s.pt" in face_values, "Missing face model option"
        
        hands_values = card._hands_model_combo.cget("values")
        assert "hand_yolov8n.pt" in hands_values, "Missing hands model option"
        assert "hand_yolov8s.pt" in hands_values, "Missing hands model option"
        
        scheduler_values = card._scheduler_combo.cget("values")
        assert "Use sampler default" in scheduler_values, "Missing scheduler option"
        assert "Karras" in scheduler_values, "Missing scheduler option"
        
        print("✓ All combobox values configured correctly")
        
    finally:
        root.destroy()


def test_pr_008_config_export():
    """Test that to_config_dict exports all new PR-008 fields."""
    print("\n=== Testing PR-008: Config Export ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        card = ADetailerStageCardV2(root)
        
        # Set some test values
        card.enable_face_pass_var.set(True)
        card.face_model_var.set("face_yolov8s.pt")
        card.face_padding_var.set(48)
        card.enable_hands_pass_var.set(True)
        card.hands_model_var.set("hand_yolov8s.pt")
        card.hands_padding_var.set(64)
        card.mask_filter_method_var.set("all")
        card.mask_k_largest_var.set(5)
        card.mask_min_ratio_var.set(0.02)
        card.mask_max_ratio_var.set(0.9)
        card.dilate_erode_var.set(8)
        card.mask_feather_var.set(10)
        card.scheduler_var.set("Karras")
        
        # Export config
        config = card.to_config_dict()
        
        # Check two-pass fields
        assert config["enable_face_pass"] == True, "Face pass not exported"
        assert config["face_model"] == "face_yolov8s.pt", "Face model not exported correctly"
        assert config["face_padding"] == 48, "Face padding not exported correctly"
        assert config["enable_hands_pass"] == True, "Hands pass not exported"
        assert config["hands_model"] == "hand_yolov8s.pt", "Hands model not exported correctly"
        assert config["hands_padding"] == 64, "Hands padding not exported correctly"
        
        print("✓ Two-pass fields exported correctly")
        
        # Check mask filter fields
        assert config["mask_filter_method"] == "all", "Filter method not exported"
        assert config["mask_k_largest"] == 5, "Mask k not exported correctly"
        assert config["ad_mask_k_largest"] == 5, "Mask k (dual key) not exported"
        assert config["mask_min_ratio"] == 0.02, "Min ratio not exported correctly"
        assert config["ad_mask_min_ratio"] == 0.02, "Min ratio (dual key) not exported"
        assert config["mask_max_ratio"] == 0.9, "Max ratio not exported correctly"
        assert config["ad_mask_max_ratio"] == 0.9, "Max ratio (dual key) not exported"
        
        print("✓ Mask filter fields exported correctly with dual keys")
        
        # Check mask processing fields
        assert config["mask_dilate_erode"] == 8, "Dilate/erode not exported"
        assert config["ad_dilate_erode"] == 8, "Dilate/erode (dual key) not exported"
        assert config["mask_feather"] == 10, "Feather not exported"
        assert config["ad_mask_feather"] == 10, "Feather (dual key) not exported"
        
        print("✓ Mask processing fields exported correctly with dual keys")
        
        # Check scheduler field
        assert config["scheduler"] == "Karras", "Scheduler not exported"
        assert config["ad_scheduler"] == "Karras", "Scheduler (dual key) not exported"
        
        print("✓ Scheduler field exported correctly with dual key")
        
    finally:
        root.destroy()


def test_pr_008_config_load():
    """Test that load_from_dict loads all new PR-008 fields."""
    print("\n=== Testing PR-008: Config Load ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        card = ADetailerStageCardV2(root)
        
        # Test config
        test_config = {
            "enable_face_pass": False,
            "face_model": "mediapipe_face_full",
            "face_padding": 16,
            "enable_hands_pass": True,
            "hands_model": "hand_yolov8s.pt",
            "hands_padding": 48,
            "mask_filter_method": "all",
            "mask_k_largest": 7,
            "mask_min_ratio": 0.05,
            "mask_max_ratio": 0.8,
            "mask_dilate_erode": -4,
            "mask_feather": 15,
            "scheduler": "Exponential",
        }
        
        # Load config
        card.load_from_dict(test_config)
        
        # Verify values loaded
        assert card.enable_face_pass_var.get() == False, "Face pass not loaded"
        assert card.face_model_var.get() == "mediapipe_face_full", "Face model not loaded"
        assert card.face_padding_var.get() == 16, "Face padding not loaded"
        assert card.enable_hands_pass_var.get() == True, "Hands pass not loaded"
        assert card.hands_model_var.get() == "hand_yolov8s.pt", "Hands model not loaded"
        assert card.hands_padding_var.get() == 48, "Hands padding not loaded"
        assert card.mask_filter_method_var.get() == "all", "Filter method not loaded"
        assert card.mask_k_largest_var.get() == 7, "Mask k not loaded"
        assert card.mask_min_ratio_var.get() == 0.05, "Min ratio not loaded"
        assert card.mask_max_ratio_var.get() == 0.8, "Max ratio not loaded"
        assert card.dilate_erode_var.get() == -4, "Dilate/erode not loaded"
        assert card.mask_feather_var.get() == 15, "Feather not loaded"
        assert card.scheduler_var.get() == "Exponential", "Scheduler not loaded"
        
        print("✓ All fields loaded correctly from config")
        
    finally:
        root.destroy()


def test_pr_008_watchable_vars():
    """Test that all new variables are in watchable_vars."""
    print("\n=== Testing PR-008: Watchable Variables ===")
    
    root = tk.Tk()
    root.withdraw()
    
    try:
        card = ADetailerStageCardV2(root)
        
        watchable = list(card.watchable_vars())
        
        # Check all new variables are watchable
        assert card.enable_face_pass_var in watchable, "Face pass toggle not watchable"
        assert card.face_model_var in watchable, "Face model not watchable"
        assert card.face_padding_var in watchable, "Face padding not watchable"
        assert card.enable_hands_pass_var in watchable, "Hands pass toggle not watchable"
        assert card.hands_model_var in watchable, "Hands model not watchable"
        assert card.hands_padding_var in watchable, "Hands padding not watchable"
        assert card.mask_filter_method_var in watchable, "Filter method not watchable"
        assert card.mask_k_largest_var in watchable, "Mask k not watchable"
        assert card.mask_min_ratio_var in watchable, "Min ratio not watchable"
        assert card.mask_max_ratio_var in watchable, "Max ratio not watchable"
        assert card.dilate_erode_var in watchable, "Dilate/erode not watchable"
        assert card.mask_feather_var in watchable, "Feather not watchable"
        assert card.scheduler_var in watchable, "Scheduler not watchable"
        
        print(f"✓ All {len(watchable)} variables are watchable")
        print(f"✓ PR-008 added 13 new watchable variables")
        
    finally:
        root.destroy()


def main():
    """Run all tests for PR-008."""
    print("=" * 60)
    print("Testing PR-008: ADetailer Two-Pass & Advanced Controls")
    print("=" * 60)
    
    try:
        test_pr_008_new_variables()
        test_pr_008_gui_widgets()
        test_pr_008_config_export()
        test_pr_008_config_load()
        test_pr_008_watchable_vars()
        
        print("\n" + "=" * 60)
        print("✓ ALL PR-008 TESTS PASSED")
        print("=" * 60)
        print("\nPR-008 Summary:")
        print("  • Two-pass controls: Face/Hands toggles + models + padding")
        print("  • Mask filter: Method, K, min/max ratio (4 controls)")
        print("  • Mask processing: Dilate/erode, feather (2 controls)")
        print("  • Scheduler: Override dropdown (1 control)")
        print("  • Total new controls: 13 variables, 30+ widgets")
        print("  • Config save/load: ✓ All fields working")
        print("  • Watchable vars: ✓ All registered")
        return 0
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
