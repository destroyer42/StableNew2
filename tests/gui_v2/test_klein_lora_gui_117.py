"""PR-IMG-117: the Klein LoRA projection (pure) and its Base Generation / LoRA picker glue.

The decision shown in the GUI is the admission decision (``evaluate_klein_loras``); nothing here removes or
rewrites a selected LoRA, and an ordinary model leaves the picker exactly as before.
"""

from __future__ import annotations

import tkinter as tk

from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui.widgets.lora_picker_panel import LoRAPickerPanel
from src.gui_v2.model_policy_projection import project_model_selection
from src.image_backends.forge_klein_lora import (
    KleinLoraDecision,
    KleinLoraStatus,
    unavailable_decision,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"


def _decision(name: str, status: KleinLoraStatus, reason: str = "r") -> KleinLoraDecision:
    return KleinLoraDecision(name, status, reason, sha256="ab" * 32)


def _resolver(table: dict[str, KleinLoraStatus]):
    return lambda name: (
        _decision(name, table[name], "why") if name in table else unavailable_decision(name, "not in registry")
    )


# --- pure projection ---------------------------------------------------------------------------


def test_the_note_explains_the_empty_negative_and_the_one_lora_contract() -> None:
    note = project_model_selection(KLEIN, "forge_webui").note

    assert "no standard negative prompt" in note and "describe what you want positively" in note
    assert "Up to 1 LoRA" in note and "explicitly names FLUX.2 Klein 4B" in note


def test_a_verified_lora_is_annotated_and_does_not_block() -> None:
    projection = project_model_selection(
        KLEIN, "forge_webui", selected_loras=[("a", 0.8)], lora_resolver=_resolver({"a": KleinLoraStatus.COMPATIBLE})
    )

    assert projection.lora_annotations == {"a": "verified for FLUX.2 Klein 4B"}
    assert projection.lora_blocking == ""


def test_an_unverified_or_unknown_lora_is_labeled_not_hidden() -> None:
    projection = project_model_selection(
        KLEIN,
        "forge_webui",
        selected_loras=[("generic", 0.8)],
        lora_resolver=_resolver({"generic": KleinLoraStatus.UNVERIFIED}),
    )

    assert projection.lora_annotations["generic"].startswith("not verified for FLUX.2 Klein 4B (unverified)")
    assert "rejected before generation" in projection.lora_blocking
    unknown = project_model_selection(KLEIN, "forge_webui", selected_loras=[("zzz", 1.0)], lora_resolver=_resolver({}))
    assert "not verified for FLUX.2 Klein 4B" in unknown.lora_annotations["zzz"]


def test_two_loras_block_with_the_admission_message() -> None:
    projection = project_model_selection(
        KLEIN,
        "forge_webui",
        selected_loras=[("a", 0.8), ("b", 0.5)],
        lora_resolver=_resolver({"a": KleinLoraStatus.COMPATIBLE, "b": KleinLoraStatus.COMPATIBLE}),
    )

    assert "at most 1" in projection.lora_blocking


def test_a_normal_model_ignores_the_lora_selection_entirely() -> None:
    projection = project_model_selection(
        "sdxl.safetensors", "forge_webui", selected_loras=[("a", 0.8)], lora_resolver=_resolver({})
    )

    assert not projection.constrained and projection.lora_annotations == {} and projection.lora_blocking == ""


# --- panel + picker glue -----------------------------------------------------------------------


def _wired(tk_root: tk.Tk, tmp_path, table: dict[str, KleinLoraStatus]):
    panel = BaseGenerationPanelV2(
        tk_root, models=["sdxl.safetensors", KLEIN], samplers=["Euler", "Euler a"], include_vae=True
    )
    panel._model_policy_projection._backend_id_provider = lambda: "forge_webui"
    picker = LoRAPickerPanel(tk_root, webui_root=str(tmp_path))
    panel._model_policy_projection.set_lora_integration(
        provider=picker.get_loras, sink=picker.set_annotations, resolver=_resolver(table)
    )
    picker.selection_listener = panel._model_policy_projection.refresh
    return panel, picker


def _note(picker: LoRAPickerPanel, name: str) -> str:
    label = picker._entry_widgets[name]["annotation_label"]
    return str(label.cget("text")) if label.winfo_manager() else ""


def test_an_unverified_selection_is_kept_visibly_marked_then_cleared_for_a_normal_model(tk_root: tk.Tk, tmp_path) -> None:
    panel, picker = _wired(tk_root, tmp_path, {"generic": KleinLoraStatus.UNVERIFIED, "good": KleinLoraStatus.COMPATIBLE})
    try:
        panel.model_var.set("sdxl.safetensors")
        before_helper = str(panel._helper_label.cget("text"))
        picker.set_loras([("generic", 0.8)])
        assert _note(picker, "generic") == ""  # an ordinary model: the picker looks exactly as before

        panel.model_var.set(KLEIN)
        assert picker.get_loras() == [("generic", 0.8)]  # never silently removed
        assert _note(picker, "generic").startswith("⚠ not verified for FLUX.2 Klein 4B")
        assert "This LoRA selection would be rejected" in str(panel._helper_label.cget("text"))

        picker.set_loras([("good", 0.8)])  # a selection change re-projects through the listener
        assert _note(picker, "good") == "verified for FLUX.2 Klein 4B"
        assert "This LoRA selection would be rejected" not in str(panel._helper_label.cget("text"))

        panel.model_var.set("sdxl.safetensors")
        assert picker.get_loras() == [("good", 0.8)]
        assert _note(picker, "good") == ""
        assert str(panel._helper_label.cget("text")) == before_helper
    finally:
        picker.destroy()
        panel.destroy()


def test_adding_a_second_lora_surfaces_the_conflict_before_submission(tk_root: tk.Tk, tmp_path) -> None:
    panel, picker = _wired(tk_root, tmp_path, {"a": KleinLoraStatus.COMPATIBLE, "b": KleinLoraStatus.COMPATIBLE})
    try:
        panel.model_var.set(KLEIN)
        picker.set_loras([("a", 0.8), ("b", 0.5)])

        assert "at most 1" in str(panel._helper_label.cget("text"))
        assert picker.get_loras() == [("a", 0.8), ("b", 0.5)]
    finally:
        picker.destroy()
        panel.destroy()
