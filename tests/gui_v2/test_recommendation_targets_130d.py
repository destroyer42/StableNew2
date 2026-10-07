from types import SimpleNamespace

import pytest

from src.gui_v2.recommendation_targets import checkpoint_for_stage, recommendation_target
from src.learning.stage_capabilities import get_variables_for_stage
from src.learning.variable_metadata import get_variable_metadata
from tests.learning_v2.test_model_capabilities_130d import make_controller, sdxl


class Variable:
    def __init__(self, value):
        self.value = value
        self.writes = []

    def get(self):
        return self.value

    def set(self, value):
        self.writes.append(value)
        self.value = value


@pytest.fixture
def cards():
    def card(**values):
        return SimpleNamespace(**{name: Variable(value) for name, value in values.items()})

    return SimpleNamespace(
        txt2img_card=card(
            cfg_var=7,
            steps_var=20,
            sampler_var="Euler a",
            scheduler_var="normal",
            model_var="ordinary",
            vae_var="base-vae",
        ),
        img2img_card=card(
            cfg_var=6,
            steps_var=15,
            sampler_var="Euler a",
            denoise_var=0.3,
            model_var="hidden-model",
            vae_var="hidden-vae",
        ),
        adetailer_card=card(
            cfg_var=5,
            steps_var=14,
            sampler_var="Euler a",
            scheduler_var="inherit",
            denoise_var=0.32,
            model_var="face_yolov8n.pt",
            stage_model_override_var="",
        ),
        upscale_card=card(factor_var=2),
    )


def controller_for(cards):
    controller = make_controller({"txt2img": {"model": "ordinary"}})
    controller._learning_policy_resolver = sdxl
    controller.pipeline_controller = SimpleNamespace(stage_cards_panel=cards)
    controller.set_automation_mode("apply_with_confirm")
    return controller


@pytest.mark.parametrize("stage", ["txt2img", "img2img", "adetailer", "upscale"])
def test_every_stage_scalar_has_a_faithful_target(stage, cards):
    for display in get_variables_for_stage(stage):
        name = get_variable_metadata(display).name
        if name == "lora_strength":
            # Composite LoRA editing has no scalar operator target; reject atomically.
            assert recommendation_target(stage, name) is None
            continue
        target = recommendation_target(stage, name)
        assert target is not None
        value = "alternate" if name in {"model", "vae", "sampler", "scheduler"} else 0.8
        recs = SimpleNamespace(stage=stage, recommendations=[{"parameter": name, "value": value}])
        assert controller_for(cards).apply_recommendations_to_pipeline(recs)
        assert getattr(getattr(cards, target[0]), target[1]).get() == value


def test_adetailer_model_never_overwrites_detector_and_can_rollback(cards):
    controller = controller_for(cards)
    recs = SimpleNamespace(
        stage="adetailer", recommendations=[{"parameter": "model", "value": "alternate"}]
    )
    assert controller.apply_recommendations_to_pipeline(recs)
    assert cards.adetailer_card.stage_model_override_var.get() == "alternate"
    assert cards.adetailer_card.model_var.get() == "face_yolov8n.pt"
    assert checkpoint_for_stage(cards, "adetailer") == "alternate"
    assert controller.rollback_last_recommendation_apply()
    assert cards.adetailer_card.stage_model_override_var.get() == ""
    cards.adetailer_card.stage_model_override_var.set("Inherit Base Generation")
    assert checkpoint_for_stage(cards, "adetailer") == "ordinary"


def test_adetailer_denoise_and_inherited_vae_do_not_touch_img2img(cards):
    controller = controller_for(cards)
    recs = SimpleNamespace(
        stage="adetailer",
        recommendations=[
            {"parameter": "denoise_strength", "value": 0.5},
            {"parameter": "vae", "value": "alternate-vae"},
        ],
    )
    assert controller.apply_recommendations_to_pipeline(recs)
    assert cards.adetailer_card.denoise_var.get() == 0.5
    assert cards.txt2img_card.vae_var.get() == "alternate-vae"
    assert cards.img2img_card.denoise_var.get() == 0.3
    assert cards.img2img_card.vae_var.get() == "hidden-vae"


@pytest.mark.parametrize("parameter", ["steps", "lora_strength", "unsupported"])
def test_missing_or_unrepresentable_control_preflights_before_any_write(cards, parameter):
    del cards.txt2img_card.steps_var
    recs = [{"parameter": "cfg_scale", "value": 8}, {"parameter": parameter, "value": 30}]
    assert not controller_for(cards).apply_recommendations_to_pipeline(recs)
    assert cards.txt2img_card.cfg_var.writes == []


def test_real_adetailer_card_serializes_checkpoint_denoise_and_inherited_vae():
    from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
    from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
    from tests.gui_v2.tk_test_utils import get_shared_tk_root

    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk unavailable")
    base = AdvancedTxt2ImgStageCardV2(root)
    base.model_var.set("ordinary")
    ad = ADetailerStageCardV2(root)
    cards = SimpleNamespace(txt2img_card=base, adetailer_card=ad)
    detector = ad.model_var.get()
    try:
        recs = SimpleNamespace(
            stage="adetailer",
            recommendations=[
                {"parameter": "model", "value": "alternate"},
                {"parameter": "denoise_strength", "value": 0.55},
                {"parameter": "vae", "value": "alternate-vae"},
            ],
        )
        assert controller_for(cards).apply_recommendations_to_pipeline(recs)
        config = ad.to_config_dict()
        assert config["adetailer_checkpoint_model"] == "alternate"
        assert config["adetailer_model"] == detector
        assert config["adetailer_denoise"] == 0.55
        assert "vae" not in config
        assert base.vae_var.get() == "alternate-vae"
    finally:
        ad.destroy()
        base.destroy()
