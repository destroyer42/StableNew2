"""PR-IMG-130C: the Prompt tab's explicit "Adapt for Target" preview (Tk, deterministic, no I/O).

The preview is a read-only projection of the pure adaptation engine: it never changes, dirties or saves the PromptPack,
never initiates an asset/style scan, and never discloses hidden content. Evidence (family lookup, LoRA resolver) is injected.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.gui.app_state_v2 import AppStateV2
from src.gui.models.prompt_pack_model import PromptPackModel
from src.gui.prompt_adaptation_dialog import PromptAdaptationDialog
from src.gui.views import prompt_tab_frame_v2
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.image_backends.forge_klein_lora import KleinLoraStatus
from src.prompting import prompt_adaptation as pa
from src.training.style_lora_manager import ResolvedStyleLoRA, StyleLoRAManager
from tests.gui_v2.test_prompt_target_130b import (
    KLEIN,
    MYSTERY,
    SDXL,
    _author,
    _authoring_state,
    _detail,
    _optimizer_disabled,
    _projection,
    _resolver,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def tab(tk_root: tk.Tk, tmp_path: Path):
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path)
    frame.target_lora_resolver = _resolver({"one_lora": KleinLoraStatus.COMPATIBLE})
    yield frame
    if frame._adaptation_dialog is not None:
        frame._adaptation_dialog.close()
    frame.destroy()


def _author_sdxl_style(frame: PromptTabFrame) -> None:
    _author(frame)
    frame.workspace_state.set_slot_text(0, "masterpiece, (red dress:1.2), a lighthouse BREAK a quiet harbor")
    frame._refresh_editor()
    frame.workspace_state.dirty = False


def _dialog_text(dialog: PromptAdaptationDialog) -> str:
    return "\n".join(
        [dialog.model.summary, dialog.model.original_positive, dialog.model.adapted_positive]
        + [dialog.model.original_negative, dialog.model.adapted_negative, dialog.model.embeddings, dialog.model.loras]
        + list(dialog.model.steps) + list(dialog.model.notes) + [dialog.visible_text()]
    )


# --- availability follows the model projection -------------------------------------------------------------------------------


def test_adapt_action_follows_the_current_model_projection(tab: PromptTabFrame) -> None:
    assert tab.adapt_button.instate(["disabled"])  # no model selected yet
    tab.on_model_projection(_projection(SDXL))
    assert tab.adapt_button.instate(["!disabled"])
    tab.on_model_projection(_projection(KLEIN))
    assert tab.adapt_button.instate(["!disabled"])
    tab.on_model_projection(_projection(MYSTERY))
    assert tab.adapt_button.instate(["disabled"])  # conflicting evidence: adaptation unavailable, never guessed
    assert tab._open_adaptation_preview() is None
    tab.on_model_projection(_projection(SDXL))
    assert tab.adapt_button.instate(["!disabled"])


def test_switching_models_changes_only_preview_availability_and_content(tab: PromptTabFrame) -> None:
    _author_sdxl_style(tab)
    before = _authoring_state(tab)

    tab.on_model_projection(_projection(SDXL))
    sdxl_dialog = tab._open_adaptation_preview()
    sdxl_model = sdxl_dialog.model
    sdxl_dialog.close()

    tab.on_model_projection(_projection(KLEIN))
    klein_dialog = tab._open_adaptation_preview()
    klein_model = klein_dialog.model
    klein_dialog.close()

    tab.on_model_projection(_projection(SDXL))
    again = tab._open_adaptation_preview()
    again_model = again.model
    again.close()

    assert not sdxl_model.changed and klein_model.changed
    assert "(red dress:1.2)" in sdxl_model.adapted_positive and "(red dress:1.2)" not in klein_model.adapted_positive
    assert again_model == sdxl_model  # SDXL -> Klein -> SDXL leaves the SDXL preview exactly as it was
    assert _authoring_state(tab) == before


# --- the preview never touches the PromptPack --------------------------------------------------------------------------------


def test_opening_and_closing_the_preview_leaves_the_workspace_identical_and_clean(tab: PromptTabFrame) -> None:
    _author_sdxl_style(tab)
    tab.on_model_projection(_projection(KLEIN))
    before = _authoring_state(tab)
    assert before["dirty"] is False

    dialog = tab._open_adaptation_preview()
    assert _authoring_state(tab) == before
    dialog.close()

    assert _authoring_state(tab) == before
    assert tab.workspace_state.dirty is False


def test_a_dirty_workspace_stays_exactly_as_dirty_and_nothing_is_saved(tab: PromptTabFrame, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_save(*_a, **_k):
        raise AssertionError("the adaptation preview must never save the PromptPack")

    monkeypatch.setattr(PromptPackModel, "save_to_file", no_save)
    monkeypatch.setattr(tab.workspace_state, "save_current_pack", no_save)
    monkeypatch.setattr(tab.workspace_state, "save_current_pack_as", no_save)
    _author(tab)
    tab.on_model_projection(_projection(KLEIN))
    assert tab.workspace_state.dirty is True

    tab._open_adaptation_preview().close()

    assert tab.workspace_state.dirty is True


def test_the_authored_negative_embeddings_and_loras_survive_the_klein_preview(tab: PromptTabFrame) -> None:
    _author(tab)
    tab.on_model_projection(_projection(KLEIN))
    before = _authoring_state(tab)

    dialog = tab._open_adaptation_preview()
    assert dialog.model.changed
    dialog.close()

    after = _authoring_state(tab)
    assert after["negative"] == "blurry, watermark" and after["pos_emb"] and after["neg_emb"] and after["loras"]
    assert after == before


# --- one interpretation system -----------------------------------------------------------------------------------------------


def test_the_preview_is_produced_by_the_pure_adapter_not_by_gui_logic(tab: PromptTabFrame, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    real = pa.adapt_prompt_for_target

    def spy(policy, source, **kwargs):
        plan = real(policy, source, **kwargs)
        calls.append((policy, source, plan))
        return plan

    monkeypatch.setattr(prompt_tab_frame_v2, "adapt_prompt_for_target", spy)
    _author_sdxl_style(tab)
    projection = _projection(KLEIN)
    tab.on_model_projection(projection)

    dialog = tab._open_adaptation_preview()

    assert len(calls) == 1 and calls[0][0] is projection.policy
    assert dialog.model.adapted_positive == calls[0][2].positive_text
    assert dialog.model.plan == calls[0][2].to_diagnostics()


# --- what the operator sees --------------------------------------------------------------------------------------------------


def test_klein_preview_explains_the_adaptation_with_counts_and_ordered_steps(tab: PromptTabFrame) -> None:
    _author_sdxl_style(tab)
    tab.on_model_projection(_projection(KLEIN))

    dialog = tab._open_adaptation_preview()
    model = dialog.model

    assert model.target_label == "Prompt Target: FLUX.2 Klein 4B FP8 — profile v2"
    rendered = tab.workspace_state.get_current_prompt_text()  # the authored template is part of the rendered text
    assert "{subject}" in rendered  # template placeholders are preserved exactly, never rewritten
    assert model.original_positive == rendered
    assert model.adapted_positive == rendered.replace("(red dress:1.2)", "red dress").replace(" BREAK ", "\n\n")
    assert "omitted" in model.adapted_negative and "present" in model.original_negative
    assert "1 LoRA" in model.loras and "retained" in model.loras
    assert "dropped" in model.embeddings
    assert len(model.steps) >= 4 and len(model.steps) == len(model.plan["operations"])
    assert "Your PromptPack is not changed" in model.summary
    assert "Original" in dialog.visible_text() and "Adapted" in dialog.visible_text()
    dialog.close()


def test_sdxl_preview_reports_no_changes(tab: PromptTabFrame) -> None:
    _author_sdxl_style(tab)
    tab.on_model_projection(_projection(SDXL))

    dialog = tab._open_adaptation_preview()

    assert not dialog.model.changed and "no changes" in dialog.model.summary.lower()
    assert dialog.model.original_positive == dialog.model.adapted_positive
    dialog.close()


def test_current_130b_diagnostics_and_controls_keep_rendering_after_the_preview(tab: PromptTabFrame) -> None:
    _author(tab)
    tab.on_model_projection(_projection(KLEIN))
    detail, banner, negative_note = _detail(tab), tab.target_banner_var.get(), tab.negative_note_var.get()

    tab._open_adaptation_preview().close()

    assert _detail(tab) == detail and tab.target_banner_var.get() == banner
    assert tab.negative_note_var.get() == negative_note and "Not supported" in negative_note
    assert all(_optimizer_disabled(tab)) and not tab.embedding_picker.additions_allowed  # 130B presentation owns these


# --- content visibility ------------------------------------------------------------------------------------------------------


def test_hidden_prompt_content_and_asset_identities_are_never_disclosed(tk_root: tk.Tk, tmp_path: Path) -> None:
    app_state = AppStateV2()
    frame = PromptTabFrame(tk_root, app_state=app_state, packs_dir=tmp_path)
    try:
        frame.target_lora_resolver = _resolver({"secret_lora": KleinLoraStatus.COMPATIBLE})
        ws = frame.workspace_state
        ws.set_slot_text(0, "(nude portrait reference:1.3) BREAK explicit_private_positive")
        ws.set_slot_negative(0, "explicit_private_negative")
        ws.set_slot_loras(0, [("secret_lora", 0.8)])
        ws.set_slot_embeddings(0, [("secret_pos_embed", 1.0)], [("secret_neg_embed", 1.0)])
        app_state.set_content_visibility_mode("sfw")
        frame.on_content_visibility_mode_changed("sfw")
        frame.on_model_projection(_projection(KLEIN))
        before = _authoring_state(frame)

        dialog = frame._open_adaptation_preview()
        everything = _dialog_text(dialog) + repr(dialog.model.plan)

        for secret in ("nude", "explicit_private_positive", "explicit_private_negative", "secret_lora", "secret_pos_embed", "secret_neg_embed"):
            assert secret not in everything, secret
        assert dialog.model.original_positive == dialog.model.adapted_positive == dialog.model.hidden_placeholder
        assert REDACTED_TEXT not in dialog.model.original_positive  # the preview speaks for itself, never echoes raw redaction
        dialog.close()
        assert _authoring_state(frame) == before
    finally:
        frame.destroy()


def test_visible_mode_never_lists_asset_names_either(tab: PromptTabFrame) -> None:
    _author(tab)
    tab.on_model_projection(_projection(KLEIN))
    dialog = tab._open_adaptation_preview()
    everything = _dialog_text(dialog) + repr(dialog.model.plan)
    for name in ("one_lora", "pos_embed", "neg_embed", "some_style"):
        assert name not in everything
    dialog.close()


# --- no scan -------------------------------------------------------------------------------------------------------------------


def test_the_preview_never_initiates_a_style_lora_scan(tab: PromptTabFrame, monkeypatch: pytest.MonkeyPatch) -> None:
    def scan(*_a, **_k):
        raise AssertionError("the adaptation preview must not resolve (scan) the Style Consistency LoRA")

    _author(tab)  # a style is selected but has never been evaluated -> pending (authoring itself may use the old path)
    tab._style_resolution_cache = None
    monkeypatch.setattr(StyleLoRAManager, "resolve_selection", scan)
    tab.on_model_projection(_projection(KLEIN))

    dialog = tab._open_adaptation_preview()

    codes = [operation["code"] for operation in dialog.model.plan["operations"]]
    assert pa.OP_STYLE_LORA_DROPPED_UNVERIFIED in codes  # explained, never silently accepted
    dialog.close()


def test_a_previously_evaluated_style_lora_is_reused_from_the_cache(tab: PromptTabFrame, monkeypatch: pytest.MonkeyPatch) -> None:
    _author(tab)
    tab.workspace_state.set_slot_loras(0, [])
    resolved = ResolvedStyleLoRA(
        style_id="some_style", display_name="Some", trigger_phrase="in the style of x", lora_name="one_lora", weight=0.6
    )
    tab._style_resolution_cache = (tab._style_selection_key(), resolved)
    monkeypatch.setattr(StyleLoRAManager, "resolve_selection", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("scan")))
    tab.on_model_projection(_projection(KLEIN))

    dialog = tab._open_adaptation_preview()

    codes = [operation["code"] for operation in dialog.model.plan["operations"]]
    assert pa.OP_STYLE_LORA_RETAINED in codes
    dialog.close()
