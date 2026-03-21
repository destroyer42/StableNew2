from __future__ import annotations

from types import SimpleNamespace

from src.gui.models.prompt_pack_model import PromptPackModel, PromptSlot
from src.gui.prompt_workspace_state import PromptWorkspaceState
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


def test_experiment_design_panel_lora_empty_state_mentions_prompt_or_runtime_config() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    panel = ExperimentDesignPanel(root, learning_controller=SimpleNamespace(_get_current_loras=lambda: []))

    panel.variable_var.set("LoRA Strength")
    panel._on_variable_changed()  # noqa: SLF001

    def _safe_text(widget) -> str | None:
        if not hasattr(widget, "cget"):
            return None
        try:
            return widget.cget("text")
        except Exception:
            return None

    labels = [
        text
        for child in panel.lora_content_frame.winfo_children()
        if (text := _safe_text(child))
    ]
    nested_labels = []
    for child in panel.lora_content_frame.winfo_children():
        if hasattr(child, "winfo_children"):
            nested_labels.extend(
                text
                for grandchild in child.winfo_children()
                if (text := _safe_text(grandchild))
            )
    assert "No enabled LoRAs in current prompt or runtime config" in labels + nested_labels

    panel.destroy()


def test_experiment_design_panel_suggests_identity() -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    panel = ExperimentDesignPanel(root)
    panel.variable_var.set("Steps")
    panel._on_variable_changed()  # noqa: SLF001
    panel._suggest_identity(name_only=False)  # noqa: SLF001

    assert panel.name_var.get().strip()
    assert "Steps" in panel.desc_var.get()
    assert panel.summary_var.get().strip()

    panel.destroy()


def test_experiment_design_panel_uses_explicit_pack_and_prompt_dropdowns(tmp_path) -> None:
    root = get_shared_tk_root()
    if root is None:
        return

    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    pack = PromptPackModel(
        name="LearningPack",
        slots=[
            PromptSlot(index=0, text="first prompt", loras=[("FirstLoRA", 0.7)]),
            PromptSlot(index=1, text="second prompt", loras=[("SecondLoRA", 0.9)]),
        ],
    )
    pack_path = packs_dir / "LearningPack.json"
    pack.save_to_file(pack_path)

    workspace = PromptWorkspaceState()
    workspace.load_pack(pack_path)

    controller = SimpleNamespace(_get_current_loras=lambda prompt_workspace_state_override=None: [])
    panel = ExperimentDesignPanel(
        root,
        learning_controller=controller,
        prompt_workspace_state=workspace,
        packs_dir=packs_dir,
    )

    assert "LearningPack" in list(panel.prompt_pack_combo.cget("values"))
    panel.prompt_source_var.set("pack")
    panel.prompt_pack_var.set("LearningPack")
    panel._on_prompt_pack_selected()  # noqa: SLF001

    prompt_values = list(panel.prompt_item_combo.cget("values"))
    assert len(prompt_values) == 2

    panel.prompt_item_var.set(prompt_values[1])
    panel._on_prompt_item_selected()  # noqa: SLF001

    selected = panel._get_selected_prompt_payload()  # noqa: SLF001
    assert selected is not None
    assert selected["prompt_text"] == "second prompt"
    assert selected["loras"] == [{"name": "SecondLoRA", "weight": 0.9}]
    assert panel._get_prompt_preview_text() == "second prompt"  # noqa: SLF001

    panel.destroy()
