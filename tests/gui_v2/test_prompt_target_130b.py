"""PR-IMG-130B: the Prompt tab understands the selected model's policy (Tk, deterministic, no I/O).

The Prompt tab only *projects* the canonical ``ModelPolicy``: it shows its target, explains limits, and makes controls
unavailable, but never rewrites or deletes authoring state, so SDXL -> Klein -> SDXL leaves everything exactly as it was.
Model/asset evidence and the LoRA resolver are injected; nothing scans, hashes or reaches the network.
"""

from __future__ import annotations

import copy
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.gui.app_state_v2 import AppStateV2
from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui.prompt_target_presenter import NO_TARGET_LABEL
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui_v2.model_policy_projection import project_model_controls
from src.image_backends import model_policy as mp
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.model_policy import ControlPolicy, FeaturePolicy, ModelPolicy, Support
from src.utils.prompt_templates import list_prompt_templates

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "juggernaut.safetensors"
MYSTERY = "mystery.safetensors"
_SDXL_EVIDENCE = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())


def _lookup(name: str):
    return {SDXL: _SDXL_EVIDENCE, MYSTERY: CompatibilityProfile(CompatibilityStatus.CONFLICTING, None, ())}.get(name)


def _projection(model: str, backend: str = "forge_webui"):
    policy = mp.resolve_model_policy(model, family_lookup=_lookup)
    return project_model_controls(policy, backend, model_name=model)


def _resolver(table: dict[str, KleinLoraStatus]):
    return lambda name: KleinLoraDecision(name=name, status=table.get(name, KleinLoraStatus.UNVERIFIED), reason="test evidence")


@pytest.fixture
def tab(tk_root: tk.Tk, tmp_path: Path):
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path)
    frame.target_lora_resolver = _resolver({})
    yield frame
    frame.destroy()


def _detail(frame: PromptTabFrame) -> str:
    return frame.target_detail_var.get()


def _optimizer_disabled(frame: PromptTabFrame) -> list[bool]:
    return [widget.instate(["disabled"]) for widget in frame._prompt_optimizer_widgets]


def _authoring_state(frame: PromptTabFrame) -> dict:
    slot = frame.workspace_state.get_slot(frame.workspace_state.get_current_slot_index())
    return {
        "text": slot.text, "negative": slot.negative, "loras": copy.deepcopy(slot.loras),
        "pos_emb": copy.deepcopy(slot.positive_embeddings), "neg_emb": copy.deepcopy(slot.negative_embeddings),
        "template_id": slot.template_id, "template_variables": dict(slot.template_variables),
        "style": dict(frame.workspace_state.get_pack_style_lora_config()),
        "matrix": copy.deepcopy(frame.workspace_state.get_matrix_config()),
        "optimizer": dict(frame.get_prompt_optimizer_config()),
        "dirty": frame.workspace_state.dirty,
    }


def _author(frame: PromptTabFrame) -> None:
    ws = frame.workspace_state
    ws.set_slot_text(0, "masterpiece, a lighthouse at dusk")
    ws.set_slot_negative(0, "blurry, watermark")
    ws.set_slot_loras(0, [("one_lora", 0.8)])
    ws.set_slot_embeddings(0, [("pos_embed", 0.9)], [("neg_embed", 0.7)])
    template = list_prompt_templates()[0]
    ws.set_slot_template(0, template.id, {"x": "y"})
    ws.set_pack_style_lora_config({"enabled": True, "style_id": "some_style"})
    frame.apply_prompt_optimizer_config({"enabled": True, "dedupe_enabled": False, "large_chunk_warning_threshold": 11})
    frame._refresh_editor()


# --- target display -----------------------------------------------------------------------------------------------------------


def test_the_banner_follows_the_selected_model_policy(tab: PromptTabFrame) -> None:
    assert tab.target_banner_var.get() == NO_TARGET_LABEL

    tab.on_model_projection(_projection(SDXL))
    assert tab.target_banner_var.get() == f"Prompt Target: SDXL — {SDXL}"

    tab.on_model_projection(_projection(KLEIN))
    assert tab.target_banner_var.get() == "Prompt Target: FLUX.2 Klein 4B FP8 — profile v2"

    tab.on_model_projection(_projection(MYSTERY))
    assert tab.target_banner_var.get().startswith(f"Prompt Target: Unclassified — {MYSTERY} — evidence conflicting")
    assert tab._prompt_target.family == mp.FAMILY_UNKNOWN


# --- SDXL: unchanged -----------------------------------------------------------------------------------------------------------


def test_sdxl_keeps_every_prompt_tool_usable(tab: PromptTabFrame) -> None:
    _author(tab)
    tab.on_model_projection(_projection(SDXL))

    assert _detail(tab) == "" and tab.negative_note_var.get() == "" and tab.optimizer_note_var.get() == ""
    assert not any(_optimizer_disabled(tab)) and tab.embedding_picker.additions_allowed
    assert "Optimized Positive:" in tab.meta_text.get("1.0", "end")


# --- Klein ------------------------------------------------------------------------------------------------------------------------


def test_klein_shows_natural_language_guidance_and_leaves_the_positive_editor_alone(tab: PromptTabFrame) -> None:
    tab.workspace_state.set_slot_text(0, "A quiet harbor at dawn.")
    tab._refresh_editor()

    tab.on_model_projection(_projection(KLEIN))

    assert "natural-language" in _detail(tab)
    assert str(tab.editor.cget("state")) == "normal" and tab.editor.get("1.0", "end").strip() == "A quiet harbor at dawn."


def test_klein_flags_negative_content_but_keeps_it_editable_and_removable(tab: PromptTabFrame) -> None:
    tab.workspace_state.set_slot_negative(0, "blurry, watermark")
    tab._refresh_editor()
    tab.workspace_state.dirty = False

    tab.on_model_projection(_projection(KLEIN))

    assert "negative prompt is present" in _detail(tab) and "Not supported" in tab.negative_note_var.get()
    assert tab.negative_editor.get("1.0", "end").strip() == "blurry, watermark"  # preserved, never cleared
    assert str(tab.negative_editor.cget("state")) == "normal"
    assert tab.workspace_state.get_current_negative_text() == "blurry, watermark" and not tab.workspace_state.dirty

    tab.negative_editor.delete("1.0", "end")  # the operator removes it to make the prompt runnable
    tab.negative_editor.edit_modified(True)
    tab._on_negative_modified()

    assert tab.workspace_state.get_current_negative_text() == ""
    assert "negative prompt is present" not in _detail(tab)


def test_klein_makes_the_optimizer_unavailable_without_touching_stored_settings(tab: PromptTabFrame) -> None:
    tab.apply_prompt_optimizer_config({"enabled": True, "optimize_negative": False, "large_chunk_warning_threshold": 9})
    tab.workspace_state.set_slot_text(0, "masterpiece, a cat")
    tab._refresh_editor()
    before = tab.get_prompt_optimizer_config()

    tab.on_model_projection(_projection(KLEIN))

    assert all(_optimizer_disabled(tab)) and tab._prompt_optimizer_widgets
    assert tab.get_prompt_optimizer_config() == before
    preview = tab.meta_text.get("1.0", "end")
    assert "Optimized Positive:" not in preview and "Not applied for FLUX.2 Klein 4B FP8" in preview
    assert "prompt optimizer is enabled in your settings" in _detail(tab).lower()

    tab.on_model_projection(_projection(SDXL))
    assert not any(_optimizer_disabled(tab)) and tab.get_prompt_optimizer_config() == before
    assert "Optimized Positive:" in tab.meta_text.get("1.0", "end")


def test_klein_embeddings_are_unsupported_but_existing_ones_stay_visible_and_removable(tab: PromptTabFrame) -> None:
    tab.workspace_state.set_slot_embeddings(0, [("pos_embed", 0.9)], [("neg_embed", 0.7)])
    tab._refresh_editor()

    tab.on_model_projection(_projection(KLEIN))
    picker = tab.embedding_picker

    assert not picker.additions_allowed and "not supported" in picker.note_var.get()
    assert picker.get_positive_embeddings() == [("pos_embed", pytest.approx(0.9))]
    assert picker.get_negative_embeddings() == [("neg_embed", pytest.approx(0.7))]
    assert "2 embedding(s)" in _detail(tab)
    picker.pos_entry.configure(state="normal")
    picker.pos_entry.set("another")
    picker._on_add_positive()  # a new unsupported addition is refused
    assert [name for name, _ in picker.get_positive_embeddings()] == ["pos_embed"]

    picker._remove_entry(picker._positive_entries, "pos_embed")  # existing entries stay removable
    assert picker.get_positive_embeddings() == []
    assert tab.workspace_state.get_slot(0).positive_embeddings == []
    assert "1 embedding(s)" in _detail(tab)

    tab.on_model_projection(_projection(SDXL))
    assert picker.additions_allowed and picker.note_var.get() == ""


# --- LoRA: existing exact evidence, including the style LoRA ---------------------------------------------------------------------


def test_klein_lora_findings_use_the_injected_exact_evidence_and_never_remove_a_selection(tab: PromptTabFrame) -> None:
    tab.workspace_state.set_slot_loras(0, [("one_lora", 0.8)])
    tab._refresh_editor()
    tab.target_lora_resolver = _resolver({"one_lora": KleinLoraStatus.COMPATIBLE})

    tab.on_model_projection(_projection(KLEIN))
    assert _detail(tab) == "" or "LoRA" not in _detail(tab)

    tab.target_lora_resolver = _resolver({})
    tab._refresh_metadata()
    assert "not verified" in _detail(tab) and "one_lora" not in _detail(tab)
    assert tab.lora_picker.get_loras() == [("one_lora", pytest.approx(0.8))]  # preserved


def test_a_slot_lora_plus_an_applied_style_lora_is_not_presented_as_runnable(tab: PromptTabFrame, monkeypatch) -> None:
    tab.workspace_state.set_slot_loras(0, [("one_lora", 0.8)])
    tab._refresh_editor()
    tab.target_lora_resolver = _resolver({"one_lora": KleinLoraStatus.COMPATIBLE, "style_lora": KleinLoraStatus.COMPATIBLE})
    style = SimpleNamespace(applied=True, lora_name="style_lora", weight=0.65, trigger_phrase="", display_name="S", warning="")
    monkeypatch.setattr(tab, "_resolve_selected_style_lora", lambda: style)

    tab.on_model_projection(_projection(KLEIN))

    assert "admits at most 1" in _detail(tab) and "Style Consistency" in _detail(tab)
    assert not tab._prompt_target.runnable_as_authored
    assert tab.lora_picker.get_loras() == [("one_lora", pytest.approx(0.8))]  # nothing silently cleared

    tab.on_model_projection(_projection(SDXL))
    assert tab._prompt_target.findings == ()


# --- non-destructive round trip -----------------------------------------------------------------------------------------------------


def test_sdxl_to_klein_to_sdxl_preserves_the_complete_prompt_authoring_state(tab: PromptTabFrame, monkeypatch) -> None:
    _author(tab)
    tab.workspace_state.dirty = False
    before = _authoring_state(tab)
    editor_before = (tab.editor.get("1.0", "end"), tab.negative_editor.get("1.0", "end"))
    marks: list[int] = []
    monkeypatch.setattr(tab, "_mark_pack_modified", lambda: marks.append(1))

    tab.on_model_projection(_projection(SDXL))
    tab.on_model_projection(_projection(KLEIN))
    assert all(_optimizer_disabled(tab)) and not tab.embedding_picker.additions_allowed
    assert _authoring_state(tab) == before  # even while Klein is projected
    tab.on_model_projection(_projection(MYSTERY))
    tab.on_model_projection(_projection(SDXL))

    assert _authoring_state(tab) == before
    assert (tab.editor.get("1.0", "end"), tab.negative_editor.get("1.0", "end")) == editor_before
    assert not any(_optimizer_disabled(tab)) and tab.embedding_picker.additions_allowed
    assert marks == [] and tab.workspace_state.dirty is False  # model selection never dirties the pack


def test_templates_and_matrix_stay_available_and_unchanged_under_klein(tab: PromptTabFrame) -> None:
    _author(tab)
    template = list_prompt_templates()[0]
    matrix_before = copy.deepcopy(tab.workspace_state.get_matrix_config())

    tab.on_model_projection(_projection(KLEIN))

    assert str(tab.template_selector.cget("state")) != "disabled" and tab.template_selector_var.get() == template.id
    assert tab.workspace_state.get_current_template_id() == template.id
    assert tab.workspace_state.get_matrix_config() == matrix_before
    assert str(tab.editor_notebook.tab(tab.matrix_tab_panel, "state")) == "normal"


# --- SDXL syntax under Klein: advisory and non-destructive -----------------------------------------------------------------------------


def test_sdxl_syntax_under_klein_is_an_advisory_and_the_text_is_preserved(tab: PromptTabFrame) -> None:
    text = "(masterpiece:1.3), a cat BREAK a dog"
    tab.workspace_state.set_slot_text(0, text)
    tab._refresh_editor()

    tab.on_model_projection(_projection(KLEIN))

    assert "attention-weight syntax" in _detail(tab) and "BREAK" in _detail(tab) and "preserved" in _detail(tab)
    assert tab.workspace_state.get_current_raw_prompt_text() == text
    assert tab._prompt_target.runnable_as_authored  # advisory only

    tab.workspace_state.set_slot_text(0, "A cat resting beside a dog.")
    tab._refresh_editor()
    tab._refresh_metadata()
    assert "attention-weight" not in _detail(tab)


# --- content visibility -------------------------------------------------------------------------------------------------------------------


def test_hidden_content_produces_no_text_derived_diagnostics(tk_root: tk.Tk, tmp_path: Path) -> None:
    app_state = AppStateV2()
    frame = PromptTabFrame(tk_root, app_state=app_state, packs_dir=tmp_path)
    try:
        frame.target_lora_resolver = _resolver({})
        frame.workspace_state.set_slot_text(0, "(nude portrait reference:1.3) BREAK")
        frame.workspace_state.set_slot_negative(0, "explicit_private_negative")
        app_state.set_content_visibility_mode("sfw")
        frame.on_content_visibility_mode_changed("sfw")
        frame.on_model_projection(_projection(KLEIN))

        detail = _detail(frame)
        assert "hidden by the content-visibility mode" in detail
        assert "attention-weight" not in detail and "negative prompt is present" not in detail
        assert "explicit_private_negative" not in detail and "nude" not in detail
        assert "explicit_private_negative" not in frame.meta_text.get("1.0", "end")  # existing redaction unchanged

        app_state.set_content_visibility_mode("nsfw")
        frame.on_content_visibility_mode_changed("nsfw")
        assert "negative prompt is present" in _detail(frame)
    finally:
        frame.destroy()


# --- policy-driven, not Klein-specific ----------------------------------------------------------------------------------------------------------


def test_a_synthetic_future_policy_drives_the_prompt_tab_without_any_klein_branch(tab: PromptTabFrame) -> None:
    future = ModelPolicy(
        policy_id="future_nl", family="future_nl", display_name="Future NL Model", evidence=mp.EVIDENCE_PROFILE,
        controls={name: ControlPolicy() for name in mp.VALUE_CONTROLS},
        features={
            **{name: FeaturePolicy(Support.SUPPORTED) for name in mp.FEATURES},
            "negative_prompt": FeaturePolicy(Support.UNSUPPORTED),
            "embeddings": FeaturePolicy(Support.UNSUPPORTED),
            "prompt_optimizer": FeaturePolicy(Support.UNSUPPORTED),
        },
        prompt_dialect=mp.DIALECT_NATURAL_LANGUAGE,
        profile_ref={"id": "future_nl", "version": 3},
    )
    _author(tab)
    before = _authoring_state(tab)

    tab.on_model_projection(project_model_controls(future, "forge_webui", model_name="future.safetensors"))

    assert tab.target_banner_var.get() == "Prompt Target: Future NL Model — profile v3"
    assert all(_optimizer_disabled(tab)) and not tab.embedding_picker.additions_allowed
    assert "Future NL Model" in tab.negative_note_var.get() and "Future NL Model" in _detail(tab)
    assert _authoring_state(tab) == before


# --- wiring + no scan -----------------------------------------------------------------------------------------------------------------------------


def test_the_base_generation_selection_drives_the_prompt_tab_and_never_switches_the_backend(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel = BaseGenerationPanelV2(tk_root, models=[SDXL, KLEIN], samplers=["Euler"], include_vae=True)
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path)
    try:
        backend = Mock(return_value="a1111_webui")
        projection = panel._model_policy_projection
        projection._backend_id_provider = backend
        projection._family_lookup = _lookup
        projection.add_listener(frame.on_model_projection)

        panel.model_var.set(SDXL)
        assert frame.target_banner_var.get() == f"Prompt Target: SDXL — {SDXL}"
        panel.model_var.set(KLEIN)
        assert frame.target_banner_var.get() == "Prompt Target: FLUX.2 Klein 4B FP8 — profile v2"
        panel.model_var.set(SDXL)
        assert frame.target_banner_var.get() == f"Prompt Target: SDXL — {SDXL}"
        assert backend.return_value == "a1111_webui"  # only ever read
    finally:
        frame.destroy()
        panel.destroy()


def test_the_prompt_tab_uses_the_cache_only_resolver_and_never_scans(tk_root: tk.Tk, tmp_path: Path) -> None:
    from src.image_backends.forge_klein_lora import RegistryLoraResolver

    frame = PromptTabFrame(tk_root, packs_dir=tmp_path)
    try:
        resolver = frame._target_resolver()
        assert isinstance(resolver, RegistryLoraResolver) and resolver._cache_only is True
    finally:
        frame.destroy()
