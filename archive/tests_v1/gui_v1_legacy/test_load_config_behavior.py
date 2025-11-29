"""Tests for Load Pack Config and Load Preset functionality."""
import json
from unittest.mock import Mock

import pytest

from src.gui.main_window import StableNewGUI
from src.services.config_service import ConfigService


@pytest.fixture
def mock_config_service(tmp_path):
    """Create a mock config service with test data."""
    service = ConfigService(
        packs_dir=tmp_path / "packs",
        presets_dir=tmp_path / "presets",
        lists_dir=tmp_path / "lists",
    )

    # Create test pack config
    pack_config = {
        "txt2img": {
            "steps": 25,
            "sampler_name": "Euler",
            "cfg_scale": 7.0,
            "width": 512,
            "height": 512,
        },
        "randomization": {
            "enabled": True,
            "prompt_sr": {"enabled": True, "raw_text": "genre -> style"},
            "wildcards": {"enabled": True, "raw_text": "__artist__"},
            "matrix": {
                "enabled": True,
                "prompt_mode": "replace",
                "limit": 4,
                "base_prompt": "Base prompt",
                "slots": [{"name": "Mood", "values": ["Calm", "Energetic"]}],
                "raw_text": "Mood: Calm | Energetic",
            },
        },
    }
    pack_path = service.packs_dir / "test_pack.json"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pack_path, "w") as f:
        json.dump(pack_config, f)

    # Create test preset
    preset_config = {
        "txt2img": {
            "steps": 30,
            "sampler_name": "DPM++ 2M",
            "cfg_scale": 8.0,
            "width": 1024,
            "height": 1024,
        }
    }
    preset_path = service.presets_dir / "test_preset.json"
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    with open(preset_path, "w") as f:
        json.dump(preset_config, f)

    return service


@pytest.fixture
def minimal_app(tk_root, mock_config_service):
    """Create a minimal app instance for testing."""
    app = StableNewGUI(tk_root)
    app.config_service = mock_config_service

    # Mock the components we need
    app.config_panel = Mock()
    app.config_panel.set_config = Mock()

    # Initialize required attributes
    app.current_selected_packs = []
    app.preset_combobox = Mock()
    app.preset_combobox.get.return_value = "test_preset"

    return app


def test_pack_selection_does_not_change_editor(minimal_app):
    """Test that selecting packs does not auto-load config into editor."""
    # Initially, config_panel.set_config should not have been called
    minimal_app.config_panel.set_config.assert_not_called()

    # Simulate pack selection
    minimal_app._on_pack_selection_changed_mediator(["test_pack"])

    # config_panel.set_config should still not have been called
    minimal_app.config_panel.set_config.assert_not_called()

    # But the selected packs should be updated
    assert minimal_app.selected_packs == ["test_pack"]
    assert minimal_app.current_selected_packs == ["test_pack"]


def test_load_pack_config_updates_editor_and_banner(minimal_app):
    """Test that Load Pack Config updates the editor and banner."""
    # Set up pack selection
    minimal_app.current_selected_packs = ["test_pack"]

    # Call load pack config
    minimal_app._ui_load_pack_config()

    # Should have called config_panel.set_config with the pack config
    minimal_app.config_panel.set_config.assert_called_once()
    called_config = minimal_app.config_panel.set_config.call_args[0][0]

    # Verify the config contains expected values
    assert called_config["txt2img"]["steps"] == 25
    assert called_config["txt2img"]["sampler_name"] == "Euler"

    # Randomization state should populate UI
    rand_vars = minimal_app.randomization_vars
    assert rand_vars["enabled"].get() is True
    assert rand_vars["prompt_sr_enabled"].get() is True
    assert minimal_app._get_randomization_text("prompt_sr_text") == "genre -> style"
    assert minimal_app._get_randomization_text("wildcard_text") == "__artist__"

    # Banner should be updated
    assert minimal_app.config_source_banner.cget("text") == "Using: Pack Config (view)"


def test_load_pack_config_handles_txt_extension(minimal_app):
    """Pack configs should be discovered even when selection includes .txt suffix."""
    minimal_app.current_selected_packs = ["test_pack.txt"]
    minimal_app._ui_load_pack_config()
    minimal_app.config_panel.set_config.assert_called_once()


def test_load_preset_updates_editor_and_banner(minimal_app):
    """Test that Load Preset updates the editor and banner."""
    # Call load preset
    minimal_app._ui_load_preset()

    # Should have called config_panel.set_config with the preset config
    minimal_app.config_panel.set_config.assert_called_once()
    called_config = minimal_app.config_panel.set_config.call_args[0][0]

    # Verify the config contains expected values
    assert called_config["txt2img"]["steps"] == 30
    assert called_config["txt2img"]["sampler_name"] == "DPM++ 2M"

    # Banner should be updated
    assert minimal_app.config_source_banner.cget("text") == "Using: Preset: test_preset"


def test_load_pack_config_requires_selection(minimal_app):
    """Test that Load Pack Config does nothing when no pack is selected."""
    # No pack selected
    minimal_app.current_selected_packs = []

    # Call load pack config
    minimal_app._ui_load_pack_config()

    # Should not have called config_panel.set_config
    minimal_app.config_panel.set_config.assert_not_called()

    # Banner should remain unchanged
    assert minimal_app.config_source_banner.cget("text") == "Using: Pack Config"


def test_load_preset_requires_selection(minimal_app):
    """Test that Load Preset does nothing when no preset is selected."""
    # No preset selected
    minimal_app.preset_combobox.get.return_value = ""

    # Call load preset
    minimal_app._ui_load_preset()

    # Should not have called config_panel.set_config
    minimal_app.config_panel.set_config.assert_not_called()

    # Banner should remain unchanged
    assert minimal_app.config_source_banner.cget("text") == "Using: Pack Config"


def test_initial_banner_is_pack_config(minimal_app):
    """Test that the initial banner shows 'Using: Pack Config'."""
    # The banner should be set during initialization
    assert minimal_app.config_source_banner.cget("text") == "Using: Pack Config"


def test_load_pack_config_sets_pipeline_and_adetailer(tk_root, tmp_path):
    """Ensure stage toggles and ADetailer config load from pack files."""
    service = ConfigService(tmp_path / "packs", tmp_path / "presets", tmp_path / "lists")
    pack_cfg = {
        "txt2img": {"steps": 40},
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": False,
            "adetailer_enabled": True,
            "upscale_enabled": False,
            "loop_count": 5,
            "images_per_prompt": 3,
        },
        "adetailer": {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_confidence": 0.55,
            "adetailer_mask_feather": 6,
            "adetailer_sampler": "DPM++ 2M",
            "adetailer_steps": 12,
            "adetailer_denoise": 0.4,
            "adetailer_cfg": 6.5,
            "adetailer_prompt": "detail prompt",
            "adetailer_negative_prompt": "bad details",
        },
    }
    service.packs_dir.mkdir(parents=True, exist_ok=True)
    (service.packs_dir / "adv_pack.json").write_text(json.dumps(pack_cfg))

    gui = StableNewGUI(root=tk_root)
    gui.config_service = service
    gui.current_selected_packs = ["adv_pack"]

    gui._ui_load_pack_config()

    assert gui.pipeline_controls_panel.img2img_enabled.get() is False
    assert gui.pipeline_controls_panel.upscale_enabled.get() is False
    assert gui.pipeline_controls_panel.loop_count_var.get() == "5"
    assert gui.pipeline_controls_panel.images_per_prompt_var.get() == "3"
    assert gui.pipeline_controls_panel.adetailer_enabled.get() is True

    adetailer_panel = gui.adetailer_panel
    assert adetailer_panel is not None
    assert adetailer_panel.enabled_var.get() is True
    assert adetailer_panel.model_var.get() == "face_yolov8n.pt"
    assert adetailer_panel.steps_var.get() == 12
    assert adetailer_panel.prompt_text.get("1.0", "end-1c") == "detail prompt"


def test_apply_editor_saves_full_randomization_and_adetailer(tk_root, tmp_path, monkeypatch):
    """Applying editor config to packs should persist randomization and ADetailer settings."""

    service = ConfigService(tmp_path / "packs", tmp_path / "presets", tmp_path / "lists")

    monkeypatch.setattr("src.gui.main_window.StableNewGUI._launch_webui", lambda self: None)

    gui = StableNewGUI(tk_root)
    gui.config_service = service
    gui.current_selected_packs = ["demo_pack.txt"]

    # Enable and populate randomization panel fields
    gui.randomization_vars["enabled"].set(True)
    gui.randomization_vars["prompt_sr_enabled"].set(True)
    gui._set_randomization_text("prompt_sr_text", "hero -> villain")

    adetailer_panel = gui.adetailer_panel
    assert adetailer_panel is not None
    adetailer_panel.enabled_var.set(True)
    adetailer_panel.model_var.set("face_yolov8n.pt")
    adetailer_panel.steps_var.set(9)

    # Avoid real dialogs/threads during the test
    monkeypatch.setattr("src.gui.main_window.messagebox.askyesno", lambda *_, **__: True)
    monkeypatch.setattr("src.gui.main_window.messagebox.showinfo", lambda *_, **__: None)
    monkeypatch.setattr("src.gui.main_window.messagebox.showwarning", lambda *_, **__: None)

    captured_thread: dict[str, object] = {}

    class CaptureThread:
        def __init__(self, target=None, **kwargs):
            self._target = target

        def start(self):
            captured_thread["target"] = self._target

    monkeypatch.setattr("src.gui.main_window.threading.Thread", CaptureThread)

    def immediate_after(_delay, callback=None, *args):
        if callback:
            callback(*args)

    monkeypatch.setattr(gui.root, "after", immediate_after, raising=False)

    saved_payloads: dict[str, dict] = {}

    def fake_save(pack, cfg):
        saved_payloads[pack] = cfg

    monkeypatch.setattr(gui.config_service, "save_pack_config", fake_save, raising=False)

    gui._ui_apply_editor_to_packs()

    assert "target" in captured_thread and captured_thread["target"] is not None
    captured_thread["target"]()  # run worker synchronously

    assert "demo_pack.txt" in saved_payloads
    saved = saved_payloads["demo_pack.txt"]

    assert saved["randomization"]["prompt_sr"]["raw_text"] == "hero -> villain"
    assert saved["randomization"]["prompt_sr"]["enabled"] is True
    assert saved["adetailer"]["adetailer_model"] == "face_yolov8n.pt"
    assert saved["adetailer"]["adetailer_steps"] == 9
