"""PR-IMG-MODELS-158: PromptPack editor readiness separates structure from target readiness, on unsaved state."""

from __future__ import annotations

import copy
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.gui.models.prompt_pack_model import MatrixConfig, MatrixSlot, PromptPackModel
from src.gui.views import prompt_tab_frame_v2
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as ZP
from src.image_backends.model_policy import resolve_model_policy
from src.prompting.pack_target_readiness import assess_pack_readiness, validate_pack_structure
from tests.gui_v2.test_prompt_target_130b import (
    KLEIN,
    MYSTERY,
    SDXL,
    _authoring_state,
    _lookup,
    _projection,
    _resolver,
)

ZIMAGE = ZP.transformer.filename


def pack(text="A ceramic teapot on a wooden table.", *, width=1024, height=1024, matrix=None, **slot):
    model = PromptPackModel.new("readiness", slot_count=1)
    model.slots[0].text = text
    for key, value in slot.items():
        setattr(model.slots[0], key, value)
    model.preset_data = {"txt2img": {"width": width, "height": height}}
    if matrix is not None:
        model.matrix = matrix
    return model


def assess(model, target, *, backend="forge_webui", dirty=False):
    policy = resolve_model_policy(target, family_lookup=_lookup)
    return assess_pack_readiness(
        model, policy, model_name=target, backend_id=backend, dirty=dirty,
        lora_resolver=lambda name: None,
    )


# --- structure vs target ---------------------------------------------------------------------------------------------


def test_structure_is_validated_from_the_in_memory_matrix():
    ok = MatrixConfig(enabled=True, slots=[MatrixSlot("place", ["forest"])])
    assert validate_pack_structure(pack(matrix=ok)).valid
    bad = MatrixConfig(enabled=True, slots=[MatrixSlot("", ["a"]), MatrixSlot("empty", [])])
    result = validate_pack_structure(pack(matrix=bad))
    assert not result.valid and "Matrix slot missing name" in result.errors
    assert any("no values" in item for item in result.warnings)
    assert validate_pack_structure(pack(matrix=MatrixConfig(enabled=True))).warnings


def test_a_structurally_valid_pack_can_still_be_refused_by_the_target():
    model = pack(width=576, height=1024)
    readiness = assess(model, ZIMAGE)
    assert readiness.structure.valid
    assert not readiness.clean
    assert any("576x1024" in item and "1024x1024" in item for item in readiness.refusals)
    assert assess(pack(width=1024, height=1024), ZIMAGE).clean


def test_backend_and_unresolved_inline_tokens_are_target_refusals():
    assert any("a1111_webui" in r for r in assess(pack(), ZIMAGE, backend="a1111_webui").refusals)
    tokens = assess(pack("a portrait <lora:style:1> in soft light"), ZIMAGE)
    assert any("natural-language positive prompt" in r for r in tokens.refusals)
    assert tokens.structure.valid


def test_matrix_values_are_checked_one_at_a_time_without_changing_the_pack():
    matrix = MatrixConfig(enabled=True, slots=[MatrixSlot("place", ["forest", "<lora:bad:1>"])])
    model = pack("A teapot in [[place]]", matrix=matrix)
    before = copy.deepcopy(asdict(model))
    readiness = assess(model, ZIMAGE)
    assert any("natural-language positive prompt" in r for r in readiness.refusals)
    assert asdict(model) == before


def test_adaptation_is_reported_as_a_note_not_a_refusal_and_never_applied():
    model = pack("(red dress:1.2) in soft light", negative="blurry", loras=[("adapter", 0.7)])
    before = copy.deepcopy(asdict(model))
    readiness = assess(model, ZIMAGE)
    assert readiness.clean
    assert {"weighted_attention_flattened", "negative_prompt_dropped_unsupported"} <= set(readiness.notes)
    assert asdict(model) == before  # the authored pack is the source of truth; nothing was adapted in place


def test_unknown_evidence_claims_nothing_and_ordinary_sdxl_is_unchanged():
    unknown = assess(pack("(red dress:1.2)", width=576, height=1024), MYSTERY)
    assert not unknown.target_checked and unknown.clean
    sdxl = assess(pack("(red dress:1.2)", width=576, height=1024, negative="blurry"), SDXL)
    assert sdxl.clean and sdxl.notes == ()
    klein_bad = assess(pack(width=832, height=1216), KLEIN)
    assert not klein_bad.clean and "832x1216" in klein_bad.refusals[0]
    assert assess(pack(width=768, height=1024), KLEIN).clean


def test_every_result_states_what_was_evaluated_and_its_limits():
    unsaved = assess(pack(), ZIMAGE, dirty=True)
    assert unsaved.evaluated == "unsaved editor state"
    assert assess(pack(), ZIMAGE, dirty=False).evaluated == "saved pack file"
    text = "\n".join(unsaved.lines())
    assert "Execution readiness is confirmed by Preview" in text and "Structure: valid." in text


# --- the Tk editor ---------------------------------------------------------------------------------------------------


@pytest.fixture
def tab(tk_root: tk.Tk, tmp_path: Path, monkeypatch):
    frame = PromptTabFrame(tk_root, packs_dir=tmp_path)
    frame.target_lora_resolver = _resolver({})
    boxes = Mock()
    monkeypatch.setattr(prompt_tab_frame_v2, "messagebox", boxes)
    monkeypatch.setattr(prompt_tab_frame_v2, "configured_image_backend_id", lambda: "forge_webui")
    frame.boxes = boxes
    yield frame
    frame.destroy()


def _open_saved(frame: PromptTabFrame, tmp_path: Path, text: str, *, width=1024, height=1024) -> Path:
    state = frame.workspace_state
    state.new_pack("readiness", slot_count=1)
    state.set_slot_text(0, text)
    state.current_pack.preset_data = {"txt2img": {"width": width, "height": height}}
    path = state.save_current_pack(tmp_path / "readiness.json")
    frame._refresh_pack_list()
    frame.pack_listbox.selection_clear(0, "end")
    frame.pack_listbox.selection_set(0)
    frame._refresh_editor()
    return path


def test_validate_checks_unsaved_edits_not_the_older_saved_file(tab: PromptTabFrame, tmp_path: Path) -> None:
    path = _open_saved(tab, tmp_path, "A ceramic teapot on a wooden table.")
    tab.on_model_projection(_projection(ZIMAGE))
    saved_bytes = path.read_bytes()

    tab._on_validate_pack()
    assert tab.boxes.showinfo.called and "saved pack file" in tab.boxes.showinfo.call_args.args[1]
    assert tab.boxes.showinfo.call_args.args[1].startswith("Pack: readiness")

    tab.workspace_state.set_slot_text(0, "A teapot <lora:style:1> on a table")  # unsaved edit; disk is still valid
    assert tab.workspace_state.dirty
    state_before = _authoring_state(tab)
    tab.boxes.reset_mock()
    tab._on_validate_pack()

    assert not tab.boxes.showinfo.called  # the edit must not be labelled valid/ready
    kind, message = tab.boxes.showwarning.call_args.args
    assert "unsaved editor state" in message and "natural-language positive prompt" in message
    assert path.read_bytes() == saved_bytes  # nothing was saved
    assert _authoring_state(tab) == state_before and tab.workspace_state.dirty  # nothing was mutated or cleaned


def test_validate_reports_structure_and_target_separately_and_never_says_ready(tab: PromptTabFrame, tmp_path) -> None:
    _open_saved(tab, tmp_path, "A ceramic teapot.", width=576, height=1024)
    tab.on_model_projection(_projection(ZIMAGE))
    tab._on_validate_pack()
    message = tab.boxes.showwarning.call_args.args[1]
    assert "Structure: valid." in message and "Will be refused:" in message and "576x1024" in message
    assert "is valid!" not in message and "ready" not in message.lower().replace("execution readiness", "")


def test_model_switching_restores_the_same_readiness_and_authoring_state(tab: PromptTabFrame, tmp_path) -> None:
    _open_saved(tab, tmp_path, "(red dress:1.2) in soft light", width=768, height=1024)
    before = _authoring_state(tab)
    tab.on_model_projection(_projection(SDXL))
    tab._on_validate_pack()
    first = tab.boxes.showinfo.call_args.args[1]
    tab.on_model_projection(_projection(ZIMAGE))
    tab.boxes.reset_mock()
    tab._on_validate_pack()
    assert "576x1024" not in tab.boxes.showwarning.call_args.args[1]  # 768x1024 refused for Z-Image, not 576
    assert "768x1024" in tab.boxes.showwarning.call_args.args[1]
    tab.on_model_projection(_projection(SDXL))
    tab.boxes.reset_mock()
    tab._on_validate_pack()
    assert tab.boxes.showinfo.call_args.args[1] == first
    assert _authoring_state(tab) == before


def test_validate_with_no_pack_asks_for_one(tab: PromptTabFrame) -> None:
    tab.workspace_state.current_pack = None
    tab._on_validate_pack()
    assert tab.boxes.showinfo.call_args.args[0] == "Validate Pack"


# --- the editor agrees with the production compiler for the same configured pack -----------------------------------


@pytest.mark.parametrize(("width", "height", "compiles"), [(1024, 1024, True), (576, 1024, False)])
def test_editor_readiness_matches_the_production_compile_boundary(tmp_path, monkeypatch, width, height, compiles):
    from src.image_backends.forge_zimage_profile import ZImageProfileError
    from tests.pipeline.test_zimage_compile_policy import _pack

    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    builder._config_manager._config["txt2img"].update(width=width, height=height)
    document = PromptPackModel.load_from_file(path)
    document.preset_data = {"txt2img": {"width": width, "height": height}}  # the pack's own configured geometry

    readiness = assess(document, ZIMAGE)
    assert readiness.structure.valid
    assert readiness.clean is compiles
    if compiles:
        assert len(builder.build_jobs([entry])) == 1
    else:
        with pytest.raises(ZImageProfileError, match="width 576 conflicts"):
            builder.build_jobs([entry])
    assert path.read_bytes() == original  # neither the readiness check nor the compile touched the saved pack
