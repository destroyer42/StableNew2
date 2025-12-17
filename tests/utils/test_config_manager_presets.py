"""Tests for ConfigManager preset functionality."""

import json
import tempfile
from pathlib import Path

from src.utils.config import ConfigManager


class TestConfigManagerPresets:
    """Test ConfigManager preset discovery and loading."""

    def test_list_presets_empty_directory(self):
        """Test list_presets returns empty list for directory with no JSON files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_manager = ConfigManager(temp_dir)
            presets = config_manager.list_presets()
            assert presets == []

    def test_list_presets_with_files(self):
        """Test list_presets discovers JSON files and returns sorted names."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create some preset files
            (temp_path / "basic.json").write_text('{"model": "test"}')
            (temp_path / "advanced.json").write_text('{"model": "advanced"}')
            (temp_path / "simple.json").write_text('{"model": "simple"}')

            # Create a non-JSON file (should be ignored)
            (temp_path / "notes.txt").write_text("not a preset")

            config_manager = ConfigManager(temp_dir)
            presets = config_manager.list_presets()

            assert sorted(presets) == ["advanced", "basic", "simple"]

    def test_load_preset_success(self):
        """Test loading a valid preset file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            preset_data = {
                "txt2img": {"steps": 20, "cfg_scale": 7.0},
                "pipeline": {"txt2img_enabled": True},
            }
            (temp_path / "test_preset.json").write_text(json.dumps(preset_data))

            config_manager = ConfigManager(temp_dir)
            result = config_manager.load_preset("test_preset")

            # Should return merged config with defaults
            assert result is not None
            assert isinstance(result, dict)
            # Check that our overrides were applied
            assert result["txt2img"]["steps"] == 20
            assert result["txt2img"]["cfg_scale"] == 7.0
            assert result["pipeline"]["txt2img_enabled"] is True
            # Check that defaults are present
            assert "img2img" in result
            assert "upscale" in result
            assert "api" in result

    def test_load_preset_not_found(self):
        """Test loading a non-existent preset returns None."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_manager = ConfigManager(temp_dir)
            result = config_manager.load_preset("nonexistent")

            assert result is None

    def test_load_preset_invalid_json(self):
        """Test loading a preset with invalid JSON returns None."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Write invalid JSON
            (temp_path / "invalid.json").write_text("{invalid json")

            config_manager = ConfigManager(temp_dir)
            result = config_manager.load_preset("invalid")

            assert result is None
