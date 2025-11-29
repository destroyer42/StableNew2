"""Tests for configuration manager"""

from src.utils import ConfigManager


class TestConfigManager:
    """Test cases for ConfigManager"""

    def test_init(self, tmp_path):
        """Test initialization"""
        config_manager = ConfigManager(presets_dir=str(tmp_path / "presets"))
        assert config_manager.presets_dir.exists()

    def test_save_and_load_preset(self, tmp_path):
        """Test saving and loading presets"""
        config_manager = ConfigManager(presets_dir=str(tmp_path / "presets"))

        test_config = {"txt2img": {"steps": 20}, "img2img": {"steps": 15}}

        # Save preset
        assert config_manager.save_preset("test", test_config) is True

        # Load preset
        loaded_config = config_manager.load_preset("test")
        assert loaded_config is not None
        assert loaded_config["txt2img"]["steps"] == 20
        assert loaded_config["img2img"]["steps"] == 15

    def test_load_nonexistent_preset(self, tmp_path):
        """Test loading non-existent preset"""
        config_manager = ConfigManager(presets_dir=str(tmp_path / "presets"))

        result = config_manager.load_preset("nonexistent")
        assert result is None

    def test_list_presets(self, tmp_path):
        """Test listing presets"""
        config_manager = ConfigManager(presets_dir=str(tmp_path / "presets"))

        # Create some presets
        config_manager.save_preset("preset1", {"key": "value1"})
        config_manager.save_preset("preset2", {"key": "value2"})

        presets = config_manager.list_presets()
        assert len(presets) == 2
        assert "preset1" in presets
        assert "preset2" in presets

    def test_get_default_config(self):
        """Test getting default configuration"""
        config_manager = ConfigManager()

        default_config = config_manager.get_default_config()

        assert "txt2img" in default_config
        assert "img2img" in default_config
        assert "upscale" in default_config
        assert "video" in default_config
        assert "api" in default_config

        # Check some specific values
        assert default_config["txt2img"]["steps"] == 20
        assert default_config["api"]["base_url"] == "http://127.0.0.1:7860"

    def test_utf8_support(self, tmp_path):
        """Test UTF-8 encoding support"""
        config_manager = ConfigManager(presets_dir=str(tmp_path / "presets"))

        test_config = {"txt2img": {"prompt": "美しい風景, schöne Landschaft, 漂亮的风景"}}

        # Save with UTF-8 characters
        assert config_manager.save_preset("utf8test", test_config) is True

        # Load and verify
        loaded_config = config_manager.load_preset("utf8test")
        assert loaded_config is not None
        assert loaded_config["txt2img"]["prompt"] == test_config["txt2img"]["prompt"]
