"""Test to reproduce stage flag corruption on load."""

import json
import tempfile
from pathlib import Path
from src.utils.config import ConfigManager

def test_stage_flags_preserved_on_load():
    """Test that stage flags are preserved when loading pack config."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        presets_dir = tmpdir_path / "presets"
        presets_dir.mkdir()
        
        # Create a pack JSON with specific stage flags
        pack_json = {
            "pack_data": {
                "name": "test_pack",
                "slots": [],
                "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []}
            },
            "preset_data": {
                "txt2img": {
                    "model": "test_model.safetensors",
                    "steps": 20,
                    "cfg_scale": 7.5,
                },
                "pipeline": {
                    "txt2img_enabled": True,
                    "img2img_enabled": False,
                    "adetailer_enabled": True,  # ← ENABLED
                    "upscale_enabled": True,
                }
            }
        }
        
        # Save to packs/test_pack.json
        packs_dir = Path("packs")
        packs_dir.mkdir(exist_ok=True)
        pack_path = packs_dir / "test_pack.json"
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(pack_json, f, indent=2)
        
        # Create ConfigManager
        config_mgr = ConfigManager(presets_dir=presets_dir)
        
        # Load the pack config
        loaded_config = config_mgr.load_pack_config("test_pack.txt")
        
        print("\n" + "="*60)
        print("TEST: Stage Flag Preservation on Load")
        print("="*60)
        
        print("\nSaved flags:")
        print(f"  txt2img_enabled: True")
        print(f"  img2img_enabled: False")
        print(f"  adetailer_enabled: True  ← ENABLED")
        print(f"  upscale_enabled: True")
        
        print("\nLoaded flags:")
        pipeline_section = loaded_config.get("pipeline", {})
        print(f"  txt2img_enabled: {pipeline_section.get('txt2img_enabled')}")
        print(f"  img2img_enabled: {pipeline_section.get('img2img_enabled')}")
        print(f"  adetailer_enabled: {pipeline_section.get('adetailer_enabled')}")
        print(f"  upscale_enabled: {pipeline_section.get('upscale_enabled')}")
        
        # Check for corruption
        txt2img_ok = pipeline_section.get("txt2img_enabled") == True
        img2img_ok = pipeline_section.get("img2img_enabled") == False
        adetailer_ok = pipeline_section.get("adetailer_enabled") == True
        upscale_ok = pipeline_section.get("upscale_enabled") == True
        
        if txt2img_ok and img2img_ok and adetailer_ok and upscale_ok:
            print("\n✅ TEST PASSED: All flags preserved correctly!")
        else:
            print("\n❌ TEST FAILED: Flags were corrupted!")
            if not txt2img_ok:
                print(f"  - txt2img should be True, got {pipeline_section.get('txt2img_enabled')}")
            if not img2img_ok:
                print(f"  - img2img should be False, got {pipeline_section.get('img2img_enabled')}")
            if not adetailer_ok:
                print(f"  - adetailer should be True, got {pipeline_section.get('adetailer_enabled')}")
            if not upscale_ok:
                print(f"  - upscale should be True, got {pipeline_section.get('upscale_enabled')}")
        
        # Cleanup
        pack_path.unlink()

if __name__ == "__main__":
    test_stage_flags_preserved_on_load()
