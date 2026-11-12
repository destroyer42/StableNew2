"""Regression for preserving ADetailer edits without running or saving a pack."""

from __future__ import annotations

import json
import tkinter as tk

import pytest

from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
from src.services.ui_state_store import UIStateStore


@pytest.mark.gui
def test_working_adetailer_prompts_survive_close_without_a_run(tk_root, tmp_path):
    store = UIStateStore(tmp_path / "ui_state.json")
    values = (" café\n<lora:portrait:0.5>  \n", "", "embedding:mãos\n" * 20, "  ")
    card = ADetailerStageCardV2(tk_root)
    card.restore_working_draft(store)
    for variable, value in zip(
        (
            card.face_prompt_var,
            card.face_negative_var,
            card.hands_prompt_var,
            card.hands_negative_var,
        ),
        values,
        strict=True,
    ):
        variable.set(value)
    card.flush_working_draft()
    card.destroy()

    reopened = ADetailerStageCardV2(tk_root)
    reopened.restore_working_draft(UIStateStore(tmp_path / "ui_state.json"))
    config = reopened.to_config_dict()
    assert (
        tuple(
            config[key]
            for key in (
                "adetailer_prompt",
                "adetailer_negative_prompt",
                "adetailer_hands_prompt",
                "adetailer_hands_negative_prompt",
            )
        )
        == values
    )


@pytest.mark.gui
def test_multiline_editors_switch_and_restore_independent_profiles(tk_root, tmp_path, monkeypatch):
    store = UIStateStore(tmp_path / "ui_state.json")
    card = ADetailerStageCardV2(tk_root)
    card.pack(fill="x")
    card.restore_working_draft(store)
    card._notebook.select(card._prompt_tab)
    tk_root.update()
    face, negative = card._face_prompt_widgets
    hands, hand_negative = card._hand_prompt_widgets
    for editor in (face, negative, hands, hand_negative):
        assert isinstance(editor, tk.Text)
        assert int(editor.cget("height")) == 4
        assert editor.cget("yscrollcommand")
    value = " café\n  <lora:portrait:0.5>\n"
    face.replace("1.0", "end-1c", value)
    tk_root.update()
    assert card.face_prompt_var.get() == value
    face.edit_undo()
    tk_root.update()
    assert card.face_prompt_var.get() != value
    face.edit_redo()
    tk_root.update()
    assert card.face_prompt_var.get() == value
    card._expanded_prompts.set(True)
    card._resize_prompt_editors()
    assert int(face.cget("height")) > 4

    def choose(label):
        card._mode_combo.set(label)
        card._mode_combo.event_generate("<<ComboboxSelected>>")
        tk_root.update()

    choose("Multiple Faces")
    assert card.to_config_dict()["ad_mask_k_largest"] == 0
    assert card._face_mask_spin.instate(["disabled"])
    hands.replace("1.0", "end-1c", " anatomía\n\n ")
    tk_root.update()
    card.hands_mask_k_largest_var.set(13)
    assert card.to_config_dict()["ad_hands_mask_k"] == 13
    choose("Single Face")
    assert face.get("1.0", "end-1c") == value
    card.enable_face_pass_var.set(False)
    card._sync_pass_states()
    assert face.cget("state") == negative.cget("state") == "disabled"
    assert hands.cget("state") == "normal"
    assert face.get("1.0", "end-1c") == value
    assert card.flush_working_draft()
    card.destroy()

    card = ADetailerStageCardV2(tk_root)
    card.restore_working_draft(store)
    choose("Multiple Faces")
    assert card.to_config_dict()["adetailer_hands_prompt"] == " anatomía\n\n "
    assert card.to_config_dict()["ad_hands_mask_k"] == 13
    monkeypatch.setattr(
        "src.gui.stage_cards_v2.adetailer_stage_card_v2.messagebox.askokcancel",
        lambda *a, **k: False,
    )
    card._reset_profile()
    assert card.to_config_dict()["ad_hands_mask_k"] == 13
    monkeypatch.setattr(
        "src.gui.stage_cards_v2.adetailer_stage_card_v2.messagebox.askokcancel",
        lambda *a, **k: True,
    )
    card._reset_profile()
    assert card.to_config_dict()["ad_hands_mask_k"] == 0
    choose("Single Face")
    assert card.to_config_dict()["adetailer_prompt"] == value
    card.flush_working_draft()


@pytest.mark.gui
def test_programmatic_pack_load_leaves_pending_draft_intact_and_failed_write_is_visible(
    tk_root,
    tmp_path,
    monkeypatch,
):
    store = UIStateStore(tmp_path / "ui_state.json")
    card = ADetailerStageCardV2(tk_root)
    card.restore_working_draft(store)
    card.face_prompt_var.set("working\n")
    card.load_from_dict({"adetailer_prompt": "pack value", "ad_mask_k_largest": 7})
    assert card.to_config_dict()["adetailer_prompt"] == "pack value"
    write = store.save_state
    monkeypatch.setattr(store, "save_state", lambda _state: False)
    assert not card.flush_working_draft()
    assert "Could not save" in card._draft_status.cget("text")
    assert card.face_prompt_var.get() == "pack value"
    monkeypatch.setattr(store, "save_state", write)
    assert card.flush_working_draft()
    card.restore_working_draft(store)
    assert card.face_prompt_var.get() == "working\n"


@pytest.mark.gui
def test_unreadable_ui_state_survives_edits_and_orderly_state_save(tk_root, tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_bytes(b"{ corrupt")
    store = UIStateStore(path)
    card = ADetailerStageCardV2(tk_root)
    card.restore_working_draft(store)
    assert "Could not read" in card._draft_status.cget("text")
    card.face_prompt_var.set("still here")
    assert not card.flush_working_draft()
    assert not store.save_state({"tabs": {}})
    assert path.read_bytes() == b"{ corrupt"
    assert card.face_prompt_var.get() == "still here"


@pytest.mark.gui
def test_startup_loads_default_then_last_run_and_startup_settings_before_working_draft(
    tk_root,
    tmp_path,
    monkeypatch,
):
    from types import SimpleNamespace

    from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
    from src.utils.config import ADETAILER_DEFAULT_KEY, ConfigManager

    store = UIStateStore(tmp_path / "ui_state.json")
    assert store.save_state(
        {"adetailer_working_draft": {"adetailer_prompt": "working", "ad_mask_k_largest": 4}}
    )
    bytes_before_startup = (tmp_path / "ui_state.json").read_bytes()
    monkeypatch.setattr("src.gui.views.pipeline_tab_frame_v2.get_ui_state_store", lambda: store)
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        global_prompt_dir=tmp_path / "prompts",
        packs_dir=tmp_path / "packs",
    )
    assert manager.update_settings({ADETAILER_DEFAULT_KEY: {"adetailer_prompt": "default"}})
    card = ADetailerStageCardV2(tk_root)

    def restore(expected, next_value):
        assert card.face_prompt_var.get() == expected
        card.load_from_dict({"adetailer_prompt": next_value})

    controller = SimpleNamespace(
        _config_manager=manager,
        restore_last_run=lambda: restore("default", "last run"),
        restore_startup_defaults=lambda: restore("last run", "startup"),
    )
    panel = SimpleNamespace(adetailer_card=card, load_adetailer_config=card.load_from_dict)
    tab = SimpleNamespace(stage_cards_panel=panel)
    PipelineTabFrame.restore_working_settings(tab, controller)
    assert card.face_prompt_var.get() == "working"
    assert card.flush_working_draft()
    assert (tmp_path / "ui_state.json").read_bytes() == bytes_before_startup

    card.face_prompt_var.set("new default")
    card._save_default_button.invoke()
    assert "Application default saved" in card._default_status.cget("text")
    assert manager.get_setting(ADETAILER_DEFAULT_KEY)["adetailer_prompt"] == "new default"
    assert (tmp_path / "ui_state.json").read_bytes() == bytes_before_startup
    assert card.flush_working_draft()


@pytest.mark.gui
def test_pending_autosave_and_shutdown_keep_the_latest_edit(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr("src.gui.stage_cards_v2.adetailer_stage_card_v2._DRAFT_DELAY_MS", 0)
    store = UIStateStore(tmp_path / "ui_state.json")
    assert store.save_state({"tabs": {"selected_index": 2}})
    card = ADetailerStageCardV2(tk_root)
    card.restore_working_draft(store)
    card.face_prompt_var.set("first")
    card.face_prompt_var.set("coalesced")
    assert (store.load_state() or {}).get("adetailer_working_draft") is None

    tk_root.update()
    assert card._draft_write is not None
    card.face_prompt_var.set("latest")
    assert card.flush_working_draft()
    state = store.load_state(strict=True)
    assert state["tabs"] == {"selected_index": 2}
    assert state["adetailer_working_draft"]["adetailer_prompt"] == "latest"


@pytest.mark.gui
def test_prompt_editors_are_reachable_in_scaled_scroll_view(tk_root):
    from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

    original_scale = float(tk_root.tk.call("tk", "scaling"))
    tk_root.tk.call("tk", "scaling", original_scale * 1.5)
    try:
        tk_root.geometry("590x330")
        frame = ScrollableFrame(tk_root)
        frame.pack(fill="both", expand=True)
        card = ADetailerStageCardV2(frame.inner)
        card.pack(fill="x")
        card.set_compact_layout(True)
        card._notebook.select(card._prompt_tab)
        card._expanded_prompts.set(True)
        card._resize_prompt_editors()
        tk_root.deiconify()
        tk_root.update()
        assert frame.has_scroll_overflow()

        last_editor = card._hand_prompt_widgets[-1]
        frame._canvas.yview_moveto(1.0)
        tk_root.update()
        assert last_editor.winfo_rootx() >= frame._canvas.winfo_rootx()
        assert last_editor.winfo_rootx() + last_editor.winfo_width() <= (
            frame._canvas.winfo_rootx() + frame._canvas.winfo_width()
        )
        assert (
            last_editor.winfo_rooty() < frame._canvas.winfo_rooty() + frame._canvas.winfo_height()
        )
        last_editor.insert("1.0", "pasted text\n")
        tk_root.update()
        assert card.hands_negative_var.get().startswith("pasted text\n")
    finally:
        tk_root.tk.call("tk", "scaling", original_scale)


@pytest.mark.parametrize("mode", [[], {}])
def test_malformed_content_visibility_does_not_prevent_draft_restore(tmp_path, mode):
    store = UIStateStore(tmp_path / "ui_state.json")
    draft = {"adetailer_prompt": "saved draft"}
    assert store.save_state(
        {"content_visibility": {"mode": mode}, "adetailer_working_draft": draft}
    )
    restored = store.load_state(strict=True)
    assert restored["adetailer_working_draft"] == draft
    assert restored["content_visibility"] == {"mode": "nsfw"}


def test_decoder_recursion_failure_preserves_unreadable_ui_state(tmp_path, monkeypatch):
    path = tmp_path / "ui_state.json"
    payload = '{"schema_version":"2.6","nested":[[null]]}'
    path.write_text(payload, encoding="utf-8")
    store = UIStateStore(path)
    loads = json.loads

    def fail_on_nested_document(value, *args, **kwargs):
        if value == payload:
            raise RecursionError("JSON decoder nesting limit")
        return loads(value, *args, **kwargs)

    monkeypatch.setattr("src.services.ui_state_store.json.loads", fail_on_nested_document)
    assert store.load_state() is None
    with pytest.raises(ValueError, match="nesting"):
        store.load_state(strict=True)
    assert not store.update_state({"adetailer_working_draft": {"adetailer_prompt": "new"}})
    assert path.read_text(encoding="utf-8") == payload
