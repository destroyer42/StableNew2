"""Test unified JSON format for prompt packs and pipeline configs."""

import json
from pathlib import Path
import tempfile
import shutil

from src.gui.models.prompt_pack_model import PromptPackModel, PromptSlot, MatrixConfig, MatrixSlot
from src.utils.config import ConfigManager

def test_unified_json_no_collision():
    """Verify that saving prompt pack and pipeline config don't overwrite each other."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        packs_dir = Path(tmpdir) / "packs"
        packs_dir.mkdir()
        
        # Step 1: Create and save a prompt pack with matrix config
        print("Step 1: Creating prompt pack with matrix...")
        pack = PromptPackModel(
            name="test_pack",
            path=str(packs_dir / "test_pack.json"),
            slots=[
                PromptSlot(index=0, text="a warrior", negative=""),
                PromptSlot(index=1, text="a mage", negative=""),
            ],
            matrix=MatrixConfig(
                enabled=True,
                mode="fanout",
                limit=8,
                slots=[
                    MatrixSlot(name="style", values=["fantasy", "scifi", "cyberpunk"]),
                    MatrixSlot(name="mood", values=["heroic", "mysterious"]),
                ]
            )
        )
        pack.save_to_file()
        
        # Verify matrix data was saved
        with open(packs_dir / "test_pack.json", encoding="utf-8") as f:
            data = json.load(f)
        print(f"\n✓ Saved pack JSON structure: {list(data.keys())}")
        assert "pack_data" in data, "Missing pack_data section"
        assert data["pack_data"]["matrix"]["enabled"] is True, "Matrix not enabled"
        assert len(data["pack_data"]["matrix"]["slots"]) == 2, "Matrix slots missing"
        print(f"  - pack_data.matrix.slots: {[s['name'] for s in data['pack_data']['matrix']['slots']]}")
        
        # Step 2: Apply pipeline config to the same pack
        print("\nStep 2: Applying pipeline config to same pack...")
        config_mgr = ConfigManager()
        pipeline_config = {
            "pipeline": {
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": True,
                "upscale_enabled": False,
            },
            "txt2img": {
                "width": 1024,
                "height": 1024,
                "steps": 30,
                "cfg_scale": 7.5,
            },
            "adetailer": {
                "ad_model": "face_yolov8n.pt",
                "ad_prompt": "beautiful face",
            }
        }
        
        # Temporarily change pack path for config manager
        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmpdir)
            success = config_mgr.save_pack_config("test_pack.txt", pipeline_config)
            assert success, "Failed to save pipeline config"
        finally:
            os.chdir(original_cwd)
        
        # Step 3: Verify BOTH matrix and pipeline data exist
        print("\nStep 3: Verifying unified JSON structure...")
        with open(packs_dir / "test_pack.json", encoding="utf-8") as f:
            data = json.load(f)
        
        print(f"✓ Unified JSON structure: {list(data.keys())}")
        
        # Verify pack_data (matrix) still exists
        assert "pack_data" in data, "pack_data section was overwritten!"
        assert data["pack_data"]["name"] == "test_pack", "Pack name missing"
        assert len(data["pack_data"]["slots"]) == 2, "Slots were lost!"
        assert data["pack_data"]["matrix"]["enabled"] is True, "Matrix config was lost!"
        assert len(data["pack_data"]["matrix"]["slots"]) == 2, "Matrix slots were lost!"
        print(f"  ✓ pack_data preserved: slots={len(data['pack_data']['slots'])}, matrix slots={len(data['pack_data']['matrix']['slots'])}")
        
        # Verify preset_data (pipeline) was added
        assert "preset_data" in data, "preset_data section missing!"
        assert "pipeline" in data["preset_data"], "Pipeline config missing"
        assert data["preset_data"]["pipeline"]["txt2img_enabled"] is True, "Pipeline flags missing"
        assert "txt2img" in data["preset_data"], "txt2img section missing"
        assert data["preset_data"]["txt2img"]["width"] == 1024, "txt2img config missing"
        print(f"  ✓ preset_data added: pipeline keys={list(data['preset_data'].keys())}")
        
        # Step 4: Load pack and verify matrix data is intact
        print("\nStep 4: Reloading pack from unified JSON...")
        loaded_pack = PromptPackModel.load_from_file(packs_dir / "test_pack.json")
        assert loaded_pack.name == "test_pack", "Pack name corrupted"
        assert len(loaded_pack.slots) >= 2, "Slots corrupted"
        assert loaded_pack.slots[0].text == "a warrior", "Slot text corrupted"
        assert loaded_pack.matrix.enabled is True, "Matrix config corrupted"
        assert len(loaded_pack.matrix.slots) == 2, "Matrix slots corrupted"
        assert loaded_pack.matrix.slots[0].name == "style", "Matrix slot names corrupted"
        assert len(loaded_pack.matrix.slots[0].values) == 3, "Matrix values corrupted"
        print(f"  ✓ Loaded pack: name={loaded_pack.name}, slots={len(loaded_pack.slots)}, matrix enabled={loaded_pack.matrix.enabled}")
        
        # Step 5: Verify config manager can still read pipeline config
        print("\nStep 5: Verifying config manager can read pipeline config...")
        import os
        os.chdir(tmpdir)
        try:
            loaded_config = config_mgr.get_pack_config("test_pack.txt")
            assert "pipeline" in loaded_config, "Pipeline section missing from loaded config"
            assert loaded_config["pipeline"]["txt2img_enabled"] is True, "Pipeline config corrupted"
            assert "txt2img" in loaded_config, "txt2img section missing from loaded config"
            print(f"  ✓ Config manager loaded: {list(loaded_config.keys())}")
        finally:
            os.chdir(original_cwd)
        
        print("\n" + "="*60)
        print("✓ ALL TESTS PASSED!")
        print("="*60)
        print("\nUnified JSON format verified:")
        print("  - prompt pack saves matrix data to pack_data section")
        print("  - config manager saves pipeline config to preset_data section")
        print("  - both sections coexist in single JSON file")
        print("  - no data loss when alternating between saves")
        print("="*60)

if __name__ == "__main__":
    test_unified_json_no_collision()
