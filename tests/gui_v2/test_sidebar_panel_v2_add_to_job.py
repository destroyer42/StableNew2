from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from tests.helpers.gui_harness_v2 import GuiV2Harness


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


@pytest.mark.gui
def test_main_window_pack_selection_keeps_sidebar_actions_live(
    tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    (packs_dir / "safe_pack.txt").write_text("portrait of a traveler", encoding="utf-8")

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
