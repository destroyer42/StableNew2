from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.model_policy_panel_projection import ModelPolicyPanelProjection
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.gui_v2.model_policy_projection import project_model_controls
from src.image_backends.model_policy import resolve_model_policy
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_model_capabilities_130d import (
    exact_resolver,
    klein_config,
    make_controller,
    sdxl,
)


def panel_for_test(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk unavailable")
    controller = make_controller({"txt2img": {"model": "ordinary"}})
    controller._learning_lora_resolver = exact_resolver
    panel = ExperimentDesignPanel(root, controller, packs_dir=tmp_path)
    return root, controller, panel


def test_listener_round_trip_preserves_authoring_and_backend(tmp_path, monkeypatch):
    import requests

    from src.assets import AssetRegistry

    def forbidden(*args, **kwargs):
        raise AssertionError("Refresh attempted external/scanning work")

    monkeypatch.setattr(AssetRegistry, "snapshot", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    root, controller, panel = panel_for_test(tmp_path)
    model_var = SimpleNamespace(get=lambda: "ordinary")
    base = SimpleNamespace(model_var=model_var)
    import tkinter as tk

    for name in (
        "sampler_var",
        "scheduler_var",
        "steps_var",
        "cfg_var",
        "vae_var",
        "width_var",
        "height_var",
        "resolution_preset_var",
    ):
        setattr(base, name, tk.StringVar(master=root, value="1"))
    base._preset_map = {}
    base._preset_reverse_map = {}
    projection = ModelPolicyPanelProjection(
        base, policy_resolver=sdxl, backend_id_provider=lambda: "forge_webui"
    )
    projection.add_listener(panel.on_model_projection)
    projection.refresh()
    panel.variable_var.set("CFG Scale")
    panel._on_variable_changed()
    panel.start_var.set(6)
    projection._policy_resolver = lambda _: resolve_model_policy(klein_config()["txt2img"]["model"])
    projection.refresh()
    assert "profile v2" in panel.model_target_var.get()
    assert panel.variable_var.get() == ""
    assert str(panel.build_button.cget("state")) == "disabled"
    assert str(panel.run_button.cget("state")) == "disabled"
    assert list(panel.stage_combo.cget("values")) == ["txt2img", "img2img"]
    assert "CFG Scale" not in panel.variable_combo.cget("values")
    assert panel.start_var.get() == 6
    assert controller._get_baseline_config()["txt2img"]["model"] == "ordinary"
    projection._policy_resolver = sdxl
    projection.refresh()
    assert "CFG Scale" in panel.variable_combo.cget("values")
    assert "adetailer" in panel.stage_combo.cget("values")
    panel.destroy()


def test_exact_lora_projection_uses_cached_evidence_and_stage_applicability(tmp_path):
    root, controller, panel = panel_for_test(tmp_path)
    resolver = Mock(side_effect=exact_resolver)
    controller._learning_lora_resolver = resolver
    controller._learning_prompt_snapshot = lambda: SimpleNamespace(
        loras=(("adapter", 0.8),), style_lora=None, style_lora_pending=False
    )
    policy = resolve_model_policy(klein_config()["txt2img"]["model"])
    panel.on_model_projection(project_model_controls(policy, "forge_webui", model_name="klein"))
    assert list(panel.variable_combo.cget("values")) == ["LoRA Strength"]
    resolver.assert_called_with("adapter")
    panel.stage_var.set("img2img")
    panel._on_stage_changed()
    assert not panel.variable_combo.cget("values")
    panel.variable_var.set("Denoise Strength")
    controller.run_plan = Mock()
    panel._on_run_experiment()
    controller.run_plan.assert_not_called()
    assert "fixed" in panel.feedback_var.get()
    panel.destroy()
