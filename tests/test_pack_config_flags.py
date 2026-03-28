"""Test that pack config load preserves pipeline stage flags correctly."""

import json
import os
import tempfile
from pathlib import Path

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

        print("Step 1: Creating pack config with specific flags...")
        pack_config = {
            "pack_data": {
                "name": "test_pack",
                "slots": [],
                "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
            },
            "preset_data": {
                "pipeline": {
                    "txt2img_enabled": True,
                    "img2img_enabled": False,
                    "adetailer_enabled": True,
                    "upscale_enabled": False,
                },
                "txt2img": {"steps": 30},
                "adetailer": {"adetailer_model": "face_yolov8n.pt"},
            },
        }

        pack_path = packs_dir / "test_pack.json"
        pack_path.write_text(json.dumps(pack_config, indent=2), encoding="utf-8")

        print("  Saved config:")
        print(f"    txt2img_enabled: {pack_config['preset_data']['pipeline']['txt2img_enabled']}")
        print(f"    img2img_enabled: {pack_config['preset_data']['pipeline']['img2img_enabled']}")
        print(f"    adetailer_enabled: {pack_config['preset_data']['pipeline']['adetailer_enabled']}")
        print(f"    upscale_enabled: {pack_config['preset_data']['pipeline']['upscale_enabled']}")

        print("\nStep 2: Loading config via ConfigManager.load_pack_config()...")
        previous_cwd = Path.cwd()
        try:
            os.chdir(tmpdir_path)
            config_mgr = ConfigManager(presets_dir)
            loaded_config = config_mgr.load_pack_config("test_pack.txt")
        finally:
            os.chdir(previous_cwd)

        assert loaded_config is not None, "Failed to load config"

        print("\nStep 3: Verifying loaded flags match saved flags...")
        pipeline = loaded_config.get("pipeline", {})

        print("  Loaded config:")
        print(f"    txt2img_enabled: {pipeline.get('txt2img_enabled')}")
        print(f"    img2img_enabled: {pipeline.get('img2img_enabled')}")
        print(f"    adetailer_enabled: {pipeline.get('adetailer_enabled')}")
        print(f"    upscale_enabled: {pipeline.get('upscale_enabled')}")

        assert pipeline.get("txt2img_enabled") is True
        assert pipeline.get("img2img_enabled") is False
        assert pipeline.get("adetailer_enabled") is True
        assert pipeline.get("upscale_enabled") is False


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
                },
            },
            {
                "name": "all_disabled",
                "flags": {
                    "txt2img_enabled": False,
                    "img2img_enabled": False,
                    "adetailer_enabled": False,
                    "upscale_enabled": False,
                },
            },
            {
                "name": "only_txt2img",
                "flags": {
                    "txt2img_enabled": True,
                    "img2img_enabled": False,
                    "adetailer_enabled": False,
                    "upscale_enabled": False,
                },
            },
            {
                "name": "txt2img_and_adetailer",
                "flags": {
                    "txt2img_enabled": True,
                    "img2img_enabled": False,
                    "adetailer_enabled": True,
                    "upscale_enabled": False,
                },
            },
        ]

        previous_cwd = Path.cwd()
        try:
            os.chdir(tmpdir_path)
            config_mgr = ConfigManager(presets_dir)

            print("\nTesting various flag combinations...")
            for test_case in test_cases:
                name = test_case["name"]
                flags = test_case["flags"]

                pack_config = {
                    "pack_data": {
                        "name": name,
                        "slots": [],
                        "matrix": {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                    },
                    "preset_data": {
                        "pipeline": flags,
                        "txt2img": {"steps": 30},
                    },
                }

                pack_path = packs_dir / f"{name}.json"
                pack_path.write_text(json.dumps(pack_config, indent=2), encoding="utf-8")

                loaded = config_mgr.load_pack_config(f"{name}.txt")
                loaded_flags = loaded.get("pipeline", {})

                print(f"\n  {name}:")
                for flag_name, expected_value in flags.items():
                    actual_value = loaded_flags.get(flag_name)
                    print(
                        f"    {flag_name}: expected={expected_value}, actual={actual_value}"
                    )
                    assert actual_value == expected_value, f"{name}: {flag_name} mismatch!"
        finally:
            os.chdir(previous_cwd)


if __name__ == "__main__":
    test_pack_config_preserves_stage_flags()
    test_different_flag_combinations()
