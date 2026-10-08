from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.gui.learning_state import LearningExperiment
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from tests.gui_v2.tk_test_utils import get_shared_tk_root


@pytest.fixture
def panel(tmp_path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk display unavailable")
    controller = SimpleNamespace(
        app_controller=SimpleNamespace(
            app_state=SimpleNamespace(
                resources={
                    "models": [
                        {"title": "First", "name": "first.safetensors"},
                        {"title": "Klein", "name": "flux-2-klein-4b-fp8.safetensors"},
                    ]
                }
            )
        ),
        learning_state=SimpleNamespace(current_experiment=None),
    )
    view = ExperimentDesignPanel(root, learning_controller=controller, packs_dir=tmp_path)
    yield view
    view.destroy()


def test_study_mode_is_explicit_and_restores_controlled_controls(panel):
    assert panel.study_type_var.get() == "Controlled Variable"
    original = list(panel.variable_combo.cget("values"))
    panel.variable_var.set("Steps")
    panel.prompt_source_var.set("custom")
    panel.study_type_var.set("Model Comparison")
    panel._on_study_type_changed()
    assert panel.stage_var.get() == "txt2img"
    assert str(panel.stage_combo.cget("state")) == "disabled"
    assert panel.prompt_source_var.get() == "pack"
    assert str(panel.prompt_source_combo.cget("state")) == "disabled"
    assert panel.variable_combo.winfo_manager() == ""
    assert panel.checklist_frame.cget("text") == "Models to Compare"
    assert len(panel.choice_vars) == 2
    assert str(panel.build_button.cget("state")) == "disabled"
    for value in panel.choice_vars.values():
        value.set(True)
    assert str(panel.build_button.cget("state")) == "normal"
    panel.study_type_var.set("Controlled Variable")
    panel._on_study_type_changed()
    assert panel.variable_var.get() == "Steps"
    assert panel.prompt_source_var.get() == "custom"
    assert list(panel.variable_combo.cget("values")) == original
    assert panel.variable_combo.winfo_manager() == "grid"


def test_model_comparison_validation_is_distinct(panel):
    data = {
        "name": "study",
        "study_type": "model_comparison",
        "stage": "txt2img",
        "prompt_source": "pack",
        "selected_prompt_pack_path": "fixture.json",
        "selected_models": ["a", "b"],
        "images_per_value": 1,
    }
    assert panel._validate_experiment_data(data) is None
    data["selected_models"] = ["a"]
    assert "two distinct" in panel._validate_experiment_data(data)
    data["prompt_source"] = "custom"
    assert "PromptPack" in panel._validate_experiment_data(data)


def test_resume_reconstructs_mode_and_candidate_selection(panel):
    experiment = LearningExperiment(
        name="study",
        metadata={
            "study_type": "model_comparison",
            "prompt_source": "pack",
            "selected_models": ["first.safetensors", "flux-2-klein-4b-fp8.safetensors"],
        },
    )
    panel.restore_state(experiment)
    assert panel.study_type_var.get() == "Model Comparison"
    assert all(value.get() for value in panel.choice_vars.values())
    assert panel.stage_var.get() == "txt2img"


def test_successful_preview_enables_run_immediately(panel):
    controller = panel.learning_controller
    exp = LearningExperiment(name="study", metadata={"study_type": "model_comparison"})
    exp.execution_snapshot_json = json.dumps(
        {
            "study_type": "model_comparison",
            "model_comparison": {
                "shared_geometry": {"width": 768, "height": 1024},
                "arms": [
                    {
                        "candidate_index": 0,
                        "model_policy_context": {"family": "sdxl"},
                        "prompt_adaptation": {"changed": False},
                    }
                ],
            },
        }
    )
    controller.update_experiment_design = lambda data: setattr(
        controller.learning_state, "current_experiment", exp
    )
    controller.build_plan = lambda _: None
    panel._get_selected_prompt_payload = lambda: {
        "prompt_text": "fixture",
        "prompt_pack_name": "fixture",
        "prompt_pack_path": "fixture.json",
        "prompt_index": 0,
    }
    panel.name_var.set("study")
    panel.study_type_var.set("Model Comparison")
    panel._on_study_type_changed()
    for value in panel.choice_vars.values():
        value.set(True)
    assert str(panel.run_button.cget("state")) == "disabled"
    panel._on_build_preview()
    assert panel.feedback_var.get() == "Model Comparison preview ready"
    assert str(panel.run_button.cget("state")) == "normal"
