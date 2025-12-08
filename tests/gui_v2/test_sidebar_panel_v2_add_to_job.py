from __future__ import annotations

import tkinter as tk

from src.gui.app_state_v2 import AppStateV2
from src.gui.sidebar_panel_v2 import SidebarPanelV2


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


def test_add_to_job_with_no_pack_selection_uses_single_prompt_handler(monkeypatch, tk_root: tk.Tk) -> None:
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
