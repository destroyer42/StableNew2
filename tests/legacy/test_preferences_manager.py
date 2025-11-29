"""Tests for the PreferencesManager helper."""
from __future__ import annotations

from pathlib import Path

from src.utils.config import ConfigManager
from src.utils.preferences import PreferencesManager


def _make_config_manager(tmp_path: Path) -> ConfigManager:
    presets_dir = tmp_path / "presets"
    return ConfigManager(presets_dir=str(presets_dir))


def test_preferences_roundtrip(tmp_path):
    """Saving and loading preferences should preserve values and merge defaults."""

    config_manager = _make_config_manager(tmp_path)
    default_config = config_manager.get_default_config()
    manager = PreferencesManager(tmp_path / "prefs.json")

    preferences = {
        "preset": "cyberpunk",
        "selected_packs": ["heroes.txt", "villains.txt"],
        "override_pack": True,
        "pipeline_controls": {
            "txt2img_enabled": False,
            "img2img_enabled": True,
            "loop_type": "pipeline",
            "loop_count": 5,
            "pack_mode": "all",
            "images_per_prompt": 3,
        },
        "config": {
            "txt2img": {"steps": 42},
            "api": {"timeout": 123},
        },
    }

    assert manager.save_preferences(preferences)

    loaded = manager.load_preferences(default_config)

    assert loaded["preset"] == "cyberpunk"
    assert loaded["selected_packs"] == ["heroes.txt", "villains.txt"]
    assert loaded["override_pack"] is True
    assert loaded["pipeline_controls"]["loop_type"] == "pipeline"
    assert loaded["pipeline_controls"]["loop_count"] == 5
    assert loaded["pipeline_controls"]["txt2img_enabled"] is False
    assert loaded["config"]["txt2img"]["steps"] == 42
    # Unspecified fields should fall back to defaults
    assert loaded["config"]["txt2img"]["width"] == default_config["txt2img"]["width"]
    assert loaded["config"]["api"]["timeout"] == 123
    assert loaded["config"]["api"]["base_url"] == default_config["api"]["base_url"]


def test_preferences_defaulting(tmp_path):
    """When no file exists preferences should resolve to defaults."""

    config_manager = _make_config_manager(tmp_path)
    default_config = config_manager.get_default_config()
    manager = PreferencesManager(tmp_path / "prefs.json")

    loaded = manager.load_preferences(default_config)

    assert loaded["preset"] == "default"
    assert loaded["selected_packs"] == []
    assert loaded["override_pack"] is False
    assert loaded["pipeline_controls"]["loop_type"] == "single"
    assert loaded["pipeline_controls"]["loop_count"] == 1
    assert loaded["config"] == default_config
