"""Test that pack config load preserves pipeline stage flags correctly."""

import json
import os
import tempfile
from pathlib import Path

from src.utils.config import ConfigManager


def test_pack_config_preserves_stage_flags() -> None:
    """Verify that loading a pack config preserves the exact stage flags saved."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        packs_dir = tmpdir_path / "packs"
        presets_dir = tmpdir_path / "presets"

        packs_dir.mkdir()
        presets_dir.mkdir()

        # Step 1: Create a pack config with specific stage flags
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
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(pack_config, f, indent=2)

        # Step 2: Load via ConfigManager (which does merge with defaults)
        original_cwd = Path.cwd()
        try:
            os.chdir(tmpdir_path)
            config_mgr = ConfigManager(presets_dir=presets_dir)
            loaded_config = config_mgr.load_pack_config("test_pack.txt")
        finally:
            os.chdir(original_cwd)

        assert loaded_config is not None, "Failed to load config"

        # Step 3: Verify the flags match what was saved
        pipeline = loaded_config.get("pipeline", {})

        # CRITICAL: These must match what was saved, NOT the defaults!
        assert pipeline.get("txt2img_enabled") is True, "txt2img_enabled was corrupted!"
        assert pipeline.get("img2img_enabled") is False, (
            f"img2img_enabled should be False, got {pipeline.get('img2img_enabled')}"
        )
        assert pipeline.get("adetailer_enabled") is True, (
            f"adetailer_enabled should be True, got {pipeline.get('adetailer_enabled')}"
        )
        assert pipeline.get("upscale_enabled") is False, (
            f"upscale_enabled should be False, got {pipeline.get('upscale_enabled')}"
        )


def test_different_flag_combinations() -> None:
    """Test various flag combinations to ensure merge doesn't corrupt any."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        packs_dir = tmpdir_path / "packs"
        presets_dir = tmpdir_path / "presets"

        packs_dir.mkdir()
        presets_dir.mkdir()

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

        original_cwd = Path.cwd()
        os.chdir(tmpdir_path)
        try:
            config_mgr = ConfigManager(presets_dir=presets_dir)

            for test_case in test_cases:
                name = test_case["name"]
                flags = test_case["flags"]

                # Save config
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
                with open(pack_path, "w", encoding="utf-8") as f:
                    json.dump(pack_config, f, indent=2)

                # Load and verify
                loaded = config_mgr.load_pack_config(f"{name}.txt")
                assert loaded is not None
                loaded_flags = loaded.get("pipeline", {})

                for flag_name, expected_value in flags.items():
                    actual_value = loaded_flags.get(flag_name)
                    assert actual_value == expected_value, f"{name}: {flag_name} mismatch!"
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    test_pack_config_preserves_stage_flags()
    test_different_flag_combinations()
