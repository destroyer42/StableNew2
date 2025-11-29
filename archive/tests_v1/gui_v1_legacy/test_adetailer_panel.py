"""Tests for ADetailer configuration panel."""

import pytest

# Skip tests if tkinter is not available
pytest.importorskip("tkinter")

from src.gui.adetailer_config_panel import ADetailerConfigPanel


class TestADetailerConfigPanel:
    """Test ADetailer configuration panel."""

    @pytest.fixture
    def root(self, tk_root):
        """Use shared Tk root that skips when Tcl/Tk is unavailable."""
        return tk_root

    def test_panel_creation(self, root):
        """Test ADetailer panel creation."""
        panel = ADetailerConfigPanel(root)

        # Check that panel was created
        assert panel.frame is not None
        assert hasattr(panel, "enabled_var")
        assert hasattr(panel, "model_var")

    def test_default_config(self, root):
        """Test default configuration values."""
        panel = ADetailerConfigPanel(root)
        config = panel.get_config()

        # Check defaults
        assert "adetailer_enabled" in config
        assert config["adetailer_enabled"] is False
        assert "adetailer_model" in config
        assert "adetailer_confidence" in config
        assert "adetailer_mask_feather" in config
        assert "adetailer_steps" in config
        assert "adetailer_denoise" in config
        assert "adetailer_cfg" in config
        assert config["adetailer_scheduler"] == "inherit"

    def test_scheduler_dropdown_defaults_to_inherit(self, root):
        """Scheduler dropdown should exist and default to inherit."""
        panel = ADetailerConfigPanel(root)
        assert hasattr(panel, "scheduler_var")
        assert hasattr(panel, "scheduler_combo")
        assert panel.scheduler_var.get() == "inherit"
        values = set(panel.scheduler_combo["values"])
        assert "inherit" in values

    def test_enable_toggle(self, root):
        """Test enabling/disabling ADetailer."""
        panel = ADetailerConfigPanel(root)

        # Initially disabled
        assert panel.enabled_var.get() is False

        # Enable
        panel.enabled_var.set(True)
        config = panel.get_config()
        assert config["adetailer_enabled"] is True

        # Disable
        panel.enabled_var.set(False)
        config = panel.get_config()
        assert config["adetailer_enabled"] is False

    def test_set_config(self, root):
        """Test setting configuration."""
        panel = ADetailerConfigPanel(root)

        test_config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_confidence": 0.35,
            "adetailer_mask_feather": 6,
            "adetailer_steps": 25,
            "adetailer_denoise": 0.45,
            "adetailer_cfg": 7.5,
            "adetailer_prompt": "detailed face",
            "adetailer_negative_prompt": "blurry",
            "adetailer_scheduler": "Karras",
        }

        panel.set_config(test_config)

        # Verify config was applied
        retrieved_config = panel.get_config()
        assert retrieved_config["adetailer_enabled"] is True
        assert retrieved_config["adetailer_model"] == "face_yolov8n.pt"
        assert retrieved_config["adetailer_confidence"] == 0.35
        assert retrieved_config["adetailer_steps"] == 25
        assert retrieved_config["adetailer_scheduler"] == "Karras"

    def test_scheduler_persisted_in_config(self, root):
        """Changing scheduler dropdown updates config."""
        panel = ADetailerConfigPanel(root)
        panel.scheduler_var.set("Automatic")
        config = panel.get_config()
        assert config["adetailer_scheduler"] == "Automatic"

    def test_validate_config(self, root):
        """Test configuration validation."""
        panel = ADetailerConfigPanel(root)

        # Valid config
        valid_config = {
            "adetailer_enabled": True,
            "adetailer_confidence": 0.3,
            "adetailer_denoise": 0.4,
            "adetailer_cfg": 7.0,
            "adetailer_steps": 20,
        }
        assert panel.validate_config(valid_config) is True

        # Invalid confidence (out of range)
        invalid_config = {
            "adetailer_enabled": True,
            "adetailer_confidence": 1.5,  # > 1.0
        }
        assert panel.validate_config(invalid_config) is False

    def test_model_selection(self, root):
        """Test model selection options."""
        panel = ADetailerConfigPanel(root)

        # Check available models
        models = panel.get_available_models()
        assert len(models) > 0
        assert "face_yolov8n.pt" in models
        assert "hand_yolov8n.pt" in models

    def test_config_persistence(self, root):
        """Test configuration save and load."""
        panel = ADetailerConfigPanel(root)

        # Set config
        test_config = {"adetailer_enabled": True, "adetailer_steps": 30, "adetailer_denoise": 0.5}
        panel.set_config(test_config)

        # Get config and verify persistence
        retrieved = panel.get_config()
        assert retrieved["adetailer_enabled"] is True
        assert retrieved["adetailer_steps"] == 30
        assert retrieved["adetailer_denoise"] == 0.5


class TestADetailerIntegration:
    """Integration tests for ADetailer with pipeline."""

    @pytest.fixture
    def root(self, tk_root):
        """Use shared Tk root that skips when Tcl/Tk is unavailable."""
        return tk_root

    def test_payload_generation(self, root):
        """Test ADetailer API payload generation."""
        panel = ADetailerConfigPanel(root)

        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_confidence": 0.3,
            "adetailer_mask_feather": 4,
            "adetailer_steps": 28,
            "adetailer_denoise": 0.4,
            "adetailer_cfg": 7.0,
            "adetailer_prompt": "high quality face",
            "adetailer_negative_prompt": "blurry, distorted",
            "adetailer_scheduler": "Karras",
        }
        panel.set_config(config)

        # Generate payload
        payload = panel.generate_api_payload()

        assert payload["adetailer_model"] == "face_yolov8n.pt"
        assert payload["adetailer_conf"] == 0.3
        assert payload["adetailer_steps"] == 28
        assert payload["adetailer_denoise"] == 0.4
        assert payload["adetailer_scheduler"] == "Karras"

    def test_cancel_during_processing(self, root):
        """Test cancellation token integration."""
        from src.gui.state import CancelToken

        panel = ADetailerConfigPanel(root)
        cancel_token = CancelToken()

        # Simulate processing with cancel
        config = panel.get_config()
        config["adetailer_enabled"] = True

        # Cancel before processing
        cancel_token.cancel()

        # Processing should respect cancel token
        assert cancel_token.is_cancelled() is True
