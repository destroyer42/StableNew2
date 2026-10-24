from __future__ import annotations

import json
import time
import tkinter as tk
from pathlib import Path

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from tests.helpers.gui_harness_v2 import GuiV2Harness


def _write_native_pack(path: Path, slots: list[tuple[str, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "slots": [
                        {"index": index, "text": text, "negative": negative}
                        for index, (text, negative) in enumerate(slots)
                    ]
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )


class _FakePackListManager:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    def get_list_names(self) -> list[str]:
        return []

    def refresh(self) -> None:
        pass


class _DummyController:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.pack_calls: list[list[str]] = []

    def get_current_config(self) -> dict[str, object]:
        return {}

    def add_single_prompt_to_draft(self) -> None:
        self.calls.append("single")

    def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
        self.pack_calls.append(list(pack_ids))


def test_add_to_job_with_no_pack_selection_uses_single_prompt_handler(
    monkeypatch, tk_root: tk.Tk
) -> None:
    monkeypatch.setattr("src.gui.sidebar_panel_v2.PromptPackListManager", _FakePackListManager)
    controller = _DummyController()
    panel = SidebarPanelV2(tk_root, controller=controller, app_state=AppStateV2())
    panel.pack_listbox.selection_clear(0, "end")
    panel._on_add_to_job()
    assert controller.calls == ["single"]
    assert not controller.pack_calls


def test_add_to_job_with_pack_selection_calls_pack_handler(monkeypatch, tk_root: tk.Tk) -> None:
    monkeypatch.setattr("src.gui.sidebar_panel_v2.PromptPackListManager", _FakePackListManager)
    controller = _DummyController()
    panel = SidebarPanelV2(tk_root, controller=controller, app_state=AppStateV2())
    panel._current_pack_names = ["pack-alpha"]
    panel.pack_listbox.delete(0, "end")
    panel.pack_listbox.insert("end", "pack-alpha")
    panel.pack_listbox.selection_set(0)
    panel._on_add_to_job()
    assert controller.pack_calls == [["pack-alpha"]]
    assert controller.calls == []


def test_add_to_job_is_announced_and_refused_while_a_history_variation_is_open(
    monkeypatch, tk_root: tk.Tk
) -> None:
    from src.pipeline.history_variation_compiler import HistoryVariationDraft
    from tests.pipeline.test_history_variation_compiler_610a import _source

    monkeypatch.setattr("src.gui.sidebar_panel_v2.PromptPackListManager", _FakePackListManager)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "src.gui.sidebar_panel_v2.messagebox.showinfo",
        lambda title, message, **_: shown.append((title, message)),
    )
    controller, state = _DummyController(), AppStateV2()
    draft = HistoryVariationDraft.from_source(_source()).with_edits(steps=44)
    state.begin_history_variation(draft)
    panel = SidebarPanelV2(tk_root, controller=controller, app_state=state)
    panel._current_pack_names = ["pack-alpha"]
    panel.pack_listbox.delete(0, "end")
    panel.pack_listbox.insert("end", "pack-alpha")
    panel.pack_listbox.selection_set(0)
    panel._on_add_to_job()
    panel.pack_listbox.selection_clear(0, "end")
    panel._on_add_to_job()
    assert (
        len(shown) == 2
        and "Discard variation" in shown[0][1]
        and "Nothing was changed" in shown[0][1]
    )
    assert controller.pack_calls == [] and controller.calls == []
    assert state.job_draft.history_variation is draft


@pytest.mark.gui
def test_main_window_pack_selection_keeps_sidebar_actions_live(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STABLENEW_PROMPTPACK_DIR", str(packs_dir))
    _write_native_pack(packs_dir / "safe_pack.json", [("portrait of a traveler", "")])

    harness = GuiV2Harness(tk_root)
    try:
        harness.controller.load_packs()
        sidebar = harness.pipeline_tab.sidebar
        assert str(sidebar.add_to_job_button.cget("state")) == "disabled"

        sidebar.pack_listbox.selection_set(0)
        sidebar.pack_listbox.event_generate("<<ListboxSelect>>")
        tk_root.update()

        assert str(sidebar.add_to_job_button.cget("state")) == "normal"
    finally:
        harness.cleanup()


@pytest.mark.gui
def test_add_to_job_resolves_visible_pack_after_visibility_toggle_with_stale_controller_cache(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STABLENEW_PROMPTPACK_DIR", str(packs_dir))
    _write_native_pack(
        packs_dir / "safe_pack.json",
        [("safe prompt one", ""), ("safe prompt two", "avoid blur")],
    )
    _write_native_pack(
        packs_dir / "explicit_pack.json",
        [("nude prompt one", ""), ("nude prompt two", "")],
    )

    harness = GuiV2Harness(tk_root)
    try:
        harness.controller.set_main_window(harness.window)
        sidebar = harness.pipeline_tab.sidebar
        tk_root.update()

        harness.controller.app_state.set_content_visibility_mode("sfw")
        sidebar.on_content_visibility_mode_changed("sfw")
        tk_root.update()

        visible_after_sfw = list(sidebar.pack_listbox.get(0, tk.END))
        assert visible_after_sfw == ["safe_pack"]

        harness.controller.packs = []
        sidebar.pack_listbox.selection_clear(0, "end")
        sidebar.pack_listbox.selection_set(0)
        sidebar._on_add_to_job()
        # Draft updates are marshalled through the GUI invoker pump, which needs a
        # few Tk event-loop turns rather than a single update() call.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not harness.controller.app_state.job_draft.packs:
            tk_root.update()
            time.sleep(0.01)

        draft_prompts = [
            entry.prompt_text for entry in harness.controller.app_state.job_draft.packs
        ]
        assert draft_prompts == ["safe prompt one", "safe prompt two"]
    finally:
        harness.cleanup()
