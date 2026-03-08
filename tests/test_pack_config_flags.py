"""Test that pack config load preserves pipeline stage flags correctly."""

import json
from pathlib import Path
import tempfile

from src.utils.config import ConfigManager

def test_pack_config_preserves_stage_flags():
    """Verify that loading a pack config preserves the exact stage flags saved."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        packs_dir = tmpdir_path / "packs"
        presets_dir = tmpdir_path / "presets"
        lists_dir = tmpdir_path / "lists"
        
        packs_dir.mkdir()
        presets_dir.mkdir()
        lists_dir.mkdir()
        
        # Step 1: Create a pack config with specific stage flags
        print("Step 1: Creating pack config with specific flags...")
        pack_config = {
            "pack_data": {
                "name": "test_pack",
                "slots": [],
                "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []}
            },
            "preset_data": {
                "pipeline": {
                    "txt2img_enabled": True,
                    "img2img_enabled": False,  # DISABLED
                    "adetailer_enabled": True,  # ENABLED
                    "upscale_enabled": False,  # DISABLED
                },
                "txt2img": {"steps": 30},
                "adetailer": {"adetailer_model": "face_yolov8n.pt"}
            }
        }
        
        pack_path = packs_dir / "test_pack.json"
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(pack_config, f, indent=2)
        
        print("  Saved config:")
        print(f"    txt2img_enabled: {pack_config['preset_data']['pipeline']['txt2img_enabled']}")
        print(f"    img2img_enabled: {pack_config['preset_data']['pipeline']['img2img_enabled']}")
        print(f"    adetailer_enabled: {pack_config['preset_data']['pipeline']['adetailer_enabled']}")
        print(f"    upscale_enabled: {pack_config['preset_data']['pipeline']['upscale_enabled']}")
        
        # Step 2: Load via ConfigManager (which does merge with defaults)
        print("\nStep 2: Loading config via ConfigManager.load_pack_config()...")
        config_mgr = ConfigManager(packs_dir, presets_dir, lists_dir)
        loaded_config = config_mgr.load_pack_config("test_pack.txt")
        
        assert loaded_config is not None, "Failed to load config"
        
        # Step 3: Verify the flags match what was saved
        print("\nStep 3: Verifying loaded flags match saved flags...")
        pipeline = loaded_config.get("pipeline", {})
        
        print("  Loaded config:")
        print(f"    txt2img_enabled: {pipeline.get('txt2img_enabled')}")
        print(f"    img2img_enabled: {pipeline.get('img2img_enabled')}")
        print(f"    adetailer_enabled: {pipeline.get('adetailer_enabled')}")
        print(f"    upscale_enabled: {pipeline.get('upscale_enabled')}")
        
        # CRITICAL: These must match what was saved, NOT the defaults!
        assert pipeline.get("txt2img_enabled") is True, "txt2img_enabled was corrupted!"
        assert pipeline.get("img2img_enabled") is False, f"img2img_enabled should be False, got {pipeline.get('img2img_enabled')}"
        assert pipeline.get("adetailer_enabled") is True, f"adetailer_enabled should be True, got {pipeline.get('adetailer_enabled')}"
        assert pipeline.get("upscale_enabled") is False, f"upscale_enabled should be False, got {pipeline.get('upscale_enabled')}"
        
        print("\n" + "="*60)
        print("✓ TEST PASSED!")
        print("="*60)
        print("\nConfig merge correctly preserves saved stage flags:")
        print("  - txt2img: enabled (saved as True)")
        print("  - img2img: disabled (saved as False, not overridden by defaults)")
        print("  - adetailer: enabled (saved as True, not overridden by defaults)")
        print("  - upscale: disabled (saved as False, not overridden by defaults)")
        print("="*60)

def test_different_flag_combinations():
    """Test various flag combinations to ensure merge doesn't corrupt any."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        packs_dir = tmpdir_path / "packs"
        presets_dir = tmpdir_path / "presets"
        lists_dir = tmpdir_path / "lists"
        
        packs_dir.mkdir()
        presets_dir.mkdir()
        lists_dir.mkdir()
        
        test_cases = [
            {
                "name": "all_enabled",
                "flags": {
                    "txt2img_enabled": True,
                    "img2img_enabled": True,
                    "adetailer_enabled": True,
                    "upscale_enabled": True,
                }
            },
            {
                "name": "all_disabled",
                "flags": {
                    "txt2img_enabled": False,
                    "img2img_enabled": False,
                    "adetailer_enabled": False,
                    "upscale_enabled": False,
                }
            },
            {
                "name": "only_txt2img",
                "flags": {
                    "txt2img_enabled": True,
                    "img2img_enabled": False,
                    "adetailer_enabled": False,
                    "upscale_enabled": False,
                }
            },
            {
                "name": "txt2img_and_adetailer",
                "flags": {
                    "txt2img_enabled": True,
                    "img2img_enabled": False,
                    "adetailer_enabled": True,
                    "upscale_enabled": False,
                }
            },
        ]
        
        config_mgr = ConfigManager(packs_dir, presets_dir, lists_dir)
        
        print("\nTesting various flag combinations...")
        for test_case in test_cases:
            name = test_case["name"]
            flags = test_case["flags"]
            
            # Save config
            pack_config = {
                "pack_data": {
                    "name": name,
                    "slots": [],
                    "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []}
                },
                "preset_data": {
                    "pipeline": flags,
                    "txt2img": {"steps": 30},
                }
            }
            
            pack_path = packs_dir / f"{name}.json"
            with open(pack_path, "w", encoding="utf-8") as f:
                json.dump(pack_config, f, indent=2)
            
            # Load and verify
            loaded = config_mgr.load_pack_config(f"{name}.txt")
            loaded_flags = loaded.get("pipeline", {})
            
            print(f"\n  {name}:")
            for flag_name, expected_value in flags.items():
                actual_value = loaded_flags.get(flag_name)
                status = "✓" if actual_value == expected_value else "✗"
                print(f"    {status} {flag_name}: expected={expected_value}, actual={actual_value}")
                assert actual_value == expected_value, f"{name}: {flag_name} mismatch!"
        
        print("\n✓ All flag combinations preserved correctly!")

if __name__ == "__main__":
    test_pack_config_preserves_stage_flags()
    test_different_flag_combinations()
