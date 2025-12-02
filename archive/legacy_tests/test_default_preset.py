"""Tests for default preset functionality.

Tests ConfigManager default preset methods and startup behavior.
"""

import tempfile
from pathlib import Path

import pytest

from src.utils.config import ConfigManager


@pytest.fixture
def temp_preset_dir():
    """Create a temporary presets directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def config_manager(temp_preset_dir):
    """Create a ConfigManager with temporary directory"""
    return ConfigManager(presets_dir=temp_preset_dir)


def test_set_default_preset_success(config_manager):
    """Test setting a preset as default"""
    # Create a preset first
    config = {"txt2img": {"steps": 30}, "api": {"base_url": "http://localhost:7860"}}
    assert config_manager.save_preset("test_preset", config)

    # Set it as default
    assert config_manager.set_default_preset("test_preset")

    # Verify it's set
    assert config_manager.get_default_preset() == "test_preset"


def test_set_default_preset_nonexistent(config_manager):
    """Test setting a nonexistent preset as default fails"""
    assert not config_manager.set_default_preset("nonexistent_preset")
    assert config_manager.get_default_preset() is None


def test_set_default_preset_empty_name(config_manager):
    """Test setting empty preset name as default fails"""
    assert not config_manager.set_default_preset("")
    assert config_manager.get_default_preset() is None


def test_get_default_preset_when_none_set(config_manager):
    """Test getting default preset when none is set"""
    assert config_manager.get_default_preset() is None


def test_get_default_preset_when_file_missing(config_manager):
    """Test getting default preset when the referenced preset file is deleted"""
    # Create and set default
    config = {"txt2img": {"steps": 25}}
    config_manager.save_preset("temp_preset", config)
    config_manager.set_default_preset("temp_preset")
    assert config_manager.get_default_preset() == "temp_preset"

    # Delete the preset file
    preset_path = Path(config_manager.presets_dir) / "temp_preset.json"
    preset_path.unlink()

    # Should return None and clean up stale reference
    assert config_manager.get_default_preset() is None
    default_file = Path(config_manager.presets_dir) / ".default_preset"
    assert not default_file.exists()


def test_clear_default_preset(config_manager):
    """Test clearing the default preset"""
    # Set a default
    config = {"txt2img": {"steps": 20}}
    config_manager.save_preset("my_preset", config)
    config_manager.set_default_preset("my_preset")
    assert config_manager.get_default_preset() == "my_preset"

    # Clear it
    assert config_manager.clear_default_preset()
    assert config_manager.get_default_preset() is None


def test_clear_default_preset_when_none_set(config_manager):
    """Test clearing default preset when none is set"""
    assert config_manager.clear_default_preset()
    assert config_manager.get_default_preset() is None


def test_overwrite_default_preset(config_manager):
    """Test changing which preset is the default"""
    # Create two presets
    config1 = {"txt2img": {"steps": 10}}
    config2 = {"txt2img": {"steps": 50}}
    config_manager.save_preset("preset1", config1)
    config_manager.save_preset("preset2", config2)

    # Set first as default
    config_manager.set_default_preset("preset1")
    assert config_manager.get_default_preset() == "preset1"

    # Change to second
    config_manager.set_default_preset("preset2")
    assert config_manager.get_default_preset() == "preset2"


def test_default_preset_persists_across_instances(temp_preset_dir):
    """Test that default preset persists across ConfigManager instances"""
    # Create first instance and set default
    cm1 = ConfigManager(presets_dir=temp_preset_dir)
    config = {"txt2img": {"steps": 35}}
    cm1.save_preset("persistent_preset", config)
    cm1.set_default_preset("persistent_preset")

    # Create second instance and verify default is loaded
    cm2 = ConfigManager(presets_dir=temp_preset_dir)
    assert cm2.get_default_preset() == "persistent_preset"


def test_default_preset_file_format(config_manager):
    """Test that default preset is stored in correct format"""
    config = {"txt2img": {"steps": 15}}
    config_manager.save_preset("format_test", config)
    config_manager.set_default_preset("format_test")

    # Check file contains just the preset name
    default_file = Path(config_manager.presets_dir) / ".default_preset"
    assert default_file.exists()
    assert default_file.read_text(encoding="utf-8").strip() == "format_test"


def test_default_preset_with_special_characters(config_manager):
    """Test default preset with special characters in name"""
    # Create preset with spaces and dashes
    config = {"txt2img": {"steps": 22}}
    preset_name = "my-special preset_123"
    config_manager.save_preset(preset_name, config)
    config_manager.set_default_preset(preset_name)

    assert config_manager.get_default_preset() == preset_name
