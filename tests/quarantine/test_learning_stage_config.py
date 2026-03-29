"""Test that learning controller retrieves stage card configuration properly."""

from __future__ import annotations

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState


class MockStageCard:
    """Mock stage card with configuration."""

    def to_config_dict(self):
        return {
            "txt2img": {
                "model": "test_model.safetensors",
                "vae": "test_vae.safetensors",
                "sampler_name": "Euler a",
                "scheduler": "normal",
                "steps": 25,
                "cfg_scale": 7.5,
                "width": 512,
                "height": 768,
                "seed": 42,
                "clip_skip": 2,
            },
            "pipeline": {
                "batch_size": 1,
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": False,
                "upscale_enabled": False,
            },
        }


class MockStagePanel:
    """Mock stage cards panel."""

    def __init__(self):
        self.txt2img_card = MockStageCard()


class MockAppController:
    """Mock app controller with stage card access."""

    def _get_stage_cards_panel(self):
        return MockStagePanel()


def test_baseline_config_with_app_controller():
    learning_state = LearningState()
    controller = LearningController(
        learning_state=learning_state,
        app_controller=MockAppController(),
    )

    baseline = controller._get_baseline_config()
    txt2img = baseline.get("txt2img", {})

    assert txt2img.get("model") == "test_model.safetensors"
    assert txt2img.get("vae") == "test_vae.safetensors"
    assert txt2img.get("sampler_name") == "Euler a"
    assert txt2img.get("scheduler") == "normal"
    assert txt2img.get("seed") == 42
    assert txt2img.get("subseed") == -1
    assert txt2img.get("subseed_strength") == 0.0
    assert txt2img.get("seed_resize_from_h") == 0
    assert txt2img.get("seed_resize_from_w") == 0
    assert "pipeline" in baseline
    assert baseline["pipeline"].get("txt2img_enabled") is True


def test_baseline_config_without_app_controller():
    learning_state = LearningState()
    controller = LearningController(learning_state=learning_state)

    baseline = controller._get_baseline_config()

    if "txt2img" not in baseline:
        return

    txt2img = baseline["txt2img"]
    assert txt2img.get("subseed") == -1
    assert txt2img.get("subseed_strength") == 0.0
