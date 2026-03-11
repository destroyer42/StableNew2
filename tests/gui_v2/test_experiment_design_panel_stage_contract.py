from __future__ import annotations

from types import SimpleNamespace

from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from tests.gui_v2.tk_test_utils import get_shared_tk_root


def test_experiment_design_panel_updates_stage_specific_controls() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    panel = ExperimentDesignPanel(root)

    panel.stage_var.set("upscale")
    panel._on_stage_changed()  # noqa: SLF001

    values = list(panel.variable_combo.cget("values"))
    assert "Upscale Factor" in values
    assert "CFG Scale" not in values
    assert panel.input_image_frame.winfo_manager() == "grid"

    panel.stage_var.set("txt2img")
    panel._on_stage_changed()  # noqa: SLF001

    txt_values = list(panel.variable_combo.cget("values"))
    assert "CFG Scale" in txt_values
    assert panel.input_image_frame.winfo_manager() == ""

    panel.destroy()


def test_experiment_design_panel_resource_checklist_uses_internal_names() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    app_state = SimpleNamespace(
        resources={
            "models": [
                {"title": "Juggernaut XL", "name": "juggernautXL_ragnarokBy.safetensors"},
                {"title": "Photon", "name": "photon_v1.safetensors"},
            ]
        }
    )
    controller = SimpleNamespace(app_controller=SimpleNamespace(_app_state=app_state))
    panel = ExperimentDesignPanel(root, learning_controller=controller)

    panel.variable_var.set("Model")
    panel._on_variable_changed()  # noqa: SLF001

    assert "juggernautXL_ragnarokBy.safetensors" in panel.choice_vars
    assert "photon_v1.safetensors" in panel.choice_vars

    texts = [
        child.cget("text")
        for child in panel.checkbox_container.winfo_children()
        if hasattr(child, "cget")
    ]
    assert "Juggernaut XL" in texts
    assert "Photon" in texts

    panel.destroy()


def test_experiment_design_panel_can_switch_away_from_lora_mode() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    panel = ExperimentDesignPanel(root, learning_controller=SimpleNamespace(_get_current_loras=lambda: []))

    panel.variable_var.set("LoRA Strength")
    panel._on_variable_changed()  # noqa: SLF001
    assert panel.lora_frame.winfo_manager() == "grid"

    panel.variable_var.set("Steps")
    panel._on_variable_changed()  # noqa: SLF001
    assert panel.lora_frame.winfo_manager() == ""
    assert panel.value_frame.winfo_manager() == "grid"

    panel.destroy()
