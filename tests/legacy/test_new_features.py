"""Tests for new PR1-8 features to prevent regression."""

import pytest

from src.services.config_service import ConfigService


class TestConfigService:
    """Test the ConfigService added in PR2."""

    @pytest.fixture
    def temp_dirs(self, tmp_path):
        """Create temporary directories for testing."""
        packs_dir = tmp_path / "packs"
        presets_dir = tmp_path / "presets"
        lists_dir = tmp_path / "lists"
        packs_dir.mkdir()
        presets_dir.mkdir()
        lists_dir.mkdir()
        return packs_dir, presets_dir, lists_dir

    @pytest.fixture
    def config_service(self, temp_dirs):
        """Create ConfigService instance."""
        packs_dir, presets_dir, lists_dir = temp_dirs
        return ConfigService(packs_dir, presets_dir, lists_dir)

    def test_pack_operations(self, config_service):
        """Test pack save/load operations."""
        test_config = {"txt2img": {"steps": 20}, "img2img": {"steps": 15}}

        # Save pack
        config_service.save_pack_config("test_pack", test_config)

        # Load pack
        loaded = config_service.load_pack_config("test_pack")
        assert loaded == test_config

        # Test non-existent pack
        assert config_service.load_pack_config("nonexistent") == {}

    def test_preset_operations(self, config_service):
        """Test preset CRUD operations."""
        test_config = {"txt2img": {"steps": 25}}

        # Save preset
        config_service.save_preset("test_preset", test_config)

        # Load preset
        loaded = config_service.load_preset("test_preset")
        assert loaded == test_config

        # List presets
        presets = config_service.list_presets()
        assert "test_preset" in presets

        # Delete preset
        config_service.delete_preset("test_preset")
        assert config_service.list_presets() == []

        # Test non-existent preset
        assert config_service.load_preset("nonexistent") == {}

    def test_list_operations(self, config_service):
        """Test list CRUD operations."""
        test_packs = ["pack1", "pack2", "pack3"]

        # Save list
        config_service.save_list("test_list", test_packs)

        # Load list
        loaded = config_service.load_list("test_list")
        assert loaded == test_packs

        # List lists
        lists = config_service.list_lists()
        assert "test_list" in lists

        # Delete list
        config_service.delete_list("test_list")
        assert config_service.list_lists() == []

        # Test non-existent list
        assert config_service.load_list("nonexistent") == []


class TestConfigContext:
    """Test the ConfigContext added in PR1."""

    def test_config_context_initialization(self):
        """Test ConfigContext initializes correctly."""
        from src.gui.main_window import ConfigContext, ConfigSource

        ctx = ConfigContext()
        assert ctx.source == ConfigSource.PACK
        assert ctx.editor_cfg == {}
        assert ctx.locked_cfg is None
        assert ctx.active_preset is None
        assert ctx.active_list is None

    def test_config_context_with_params(self):
        """Test ConfigContext with custom parameters."""
        from src.gui.main_window import ConfigContext, ConfigSource

        ctx = ConfigContext(
            source=ConfigSource.PRESET,
            editor_cfg={"test": "value"},
            active_preset="test_preset"
        )
        assert ctx.source == ConfigSource.PRESET
        assert ctx.editor_cfg == {"test": "value"}
        assert ctx.active_preset == "test_preset"


if __name__ == "__main__":
    pytest.main([__file__])
