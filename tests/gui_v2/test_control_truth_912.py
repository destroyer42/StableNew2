"""GUI-TRUTH-912: every header control and every Output Settings control does something, and Add to Job does not
silently queue an older saved copy of a pack that the Prompt tab has modified.

Deterministic Tk widgets only (no display-dependent layout assertions, no native dialogs).
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import HeaderZone
from src.gui.output_settings_panel_v2 import OutputSettingsPanelV2
from src.gui.prompt_pack_adapter_v2 import PromptPackSummary
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.view_contracts import stale_pack_contract
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION

# ----------------------------------------------------------------------------- header


def test_header_has_no_preview_control_and_the_controller_has_no_stub_for_it(
    tk_root: tk.Tk,
) -> None:
    header = HeaderZone(tk_root)
    try:
        buttons = {
            child.cget("text")
            for child in header.winfo_children()
            if child.winfo_class() == "TButton"
        }
        assert "Preview" not in buttons
        assert not hasattr(header, "preview_button")
        assert not hasattr(AppController, "on_preview_clicked")
        # The Preview that remains is the Pipeline tab's panel, not a header button.
        assert buttons == {
            "Run",
            "Stop",
            "Settings",
            "Refresh",
            "Help Mode: Off",
            "Debug",
            "Readiness",
        }
    finally:
        header.destroy()


# ----------------------------------------------------------------------------- output card


def test_output_card_exposes_only_controls_that_are_consumed(tk_root: tk.Tk) -> None:
    panel = OutputSettingsPanelV2(tk_root, embed_mode=True)
    try:
        assert set(panel.get_output_overrides()) == {
            "output_dir",
            "batch_size",
            "seed_mode",
            "output_route",
        }
        assert not hasattr(panel, "image_format_var") and not hasattr(panel, "filename_pattern_var")
        labels = {
            widget.cget("text")
            for widget in _descendants(panel)
            if widget.winfo_class() == "TLabel"
        }
        assert "Format:" not in labels
        # Old pack keys are accepted and ignored: no failure, no effect on the remaining values.
        panel.apply_from_overrides(
            {"image_format": "webp", "filename_pattern": "x", "output_dir": "D:/somewhere"}
        )
        assert panel.get_output_overrides()["output_dir"] == "D:/somewhere"
        assert "image_format" not in panel.get_output_overrides()
    finally:
        panel.destroy()


def _descendants(root: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack = list(root.winfo_children())
    while stack:
        node = stack.pop(0)
        found.append(node)
        stack.extend(node.winfo_children())
    return found


# ----------------------------------------------------------------------------- stale-pack notice


def _write_pack(path: Path, text: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {"slots": [{"index": 0, "text": text, "negative": ""}]},
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )


class _Controller:
    def __init__(self) -> None:
        self.pack_calls: list[list[str]] = []

    def get_current_config(self) -> dict[str, object]:
        return {}

    def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
        self.pack_calls.append(list(pack_ids))


class _NoPackLists:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    def get_list_names(self) -> list[str]:
        return []

    def refresh(self) -> None:
        pass


@pytest.fixture
def stale_env(tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.gui.sidebar_panel_v2.PromptPackListManager", _NoPackLists)
    alpha, beta = tmp_path / "alpha.json", tmp_path / "beta.json"
    _write_pack(alpha, "saved text")
    _write_pack(beta, "other pack")
    workspace = PromptWorkspaceState()
    workspace.load_pack(alpha)
    state = AppStateV2()
    state.prompt_workspace_state = workspace
    controller = _Controller()
    panel = SidebarPanelV2(tk_root, controller=controller, app_state=state)
    panel._prompt_summaries = [
        PromptPackSummary(name="alpha", path=alpha, prompt_count=1),
        PromptPackSummary(name="beta", path=beta, prompt_count=1),
    ]
    panel._current_pack_names = ["alpha", "beta"]
    panel.pack_listbox.delete(0, "end")
    for name in panel._current_pack_names:
        panel.pack_listbox.insert("end", name)
    yield panel, controller, workspace, alpha
    panel.destroy()


def _select(panel: SidebarPanelV2, *indexes: int) -> None:
    panel.pack_listbox.selection_clear(0, "end")
    for index in indexes:
        panel.pack_listbox.selection_set(index)


def _notice_visible(panel: SidebarPanelV2) -> bool:
    return bool(panel.stale_pack_notice.winfo_manager())


def test_adding_a_clean_pack_needs_no_notice(stale_env) -> None:
    panel, controller, _workspace, _alpha = stale_env
    _select(panel, 0)

    panel._on_add_to_job()

    assert controller.pack_calls == [["alpha"]]
    assert not _notice_visible(panel)


def test_adding_a_pack_with_unsaved_prompt_tab_edits_holds_back_and_offers_both_choices(
    stale_env,
) -> None:
    panel, controller, workspace, _alpha = stale_env
    workspace.set_slot_text(0, "edited, not saved")
    _select(panel, 0)

    panel._on_add_to_job()

    assert controller.pack_calls == []  # nothing queued from the older saved file yet
    assert _notice_visible(panel)
    assert "unsaved edits" in panel.stale_pack_label.cget("text")
    assert panel.save_and_add_button.cget("text") == stale_pack_contract.SAVE_AND_ADD_LABEL
    assert panel.add_saved_button.cget("text") == stale_pack_contract.ADD_SAVED_LABEL


def test_a_dirty_other_pack_does_not_trigger_the_notice(stale_env) -> None:
    panel, controller, workspace, _alpha = stale_env
    workspace.set_slot_text(0, "edited, not saved")  # alpha is the open, dirty pack
    _select(panel, 1)  # beta is the one being added

    panel._on_add_to_job()

    assert controller.pack_calls == [["beta"]]
    assert not _notice_visible(panel)


def test_save_and_add_saves_the_pack_then_adds_it(stale_env) -> None:
    panel, controller, workspace, alpha = stale_env
    workspace.set_slot_text(0, "edited, not saved")
    _select(panel, 0)
    panel._on_add_to_job()

    panel.save_and_add_button.invoke()

    assert workspace.dirty is False
    assert "edited, not saved" in alpha.read_text(encoding="utf-8")
    assert controller.pack_calls == [["alpha"]]
    assert not _notice_visible(panel)


def test_add_saved_version_adds_without_writing_the_pack(stale_env) -> None:
    panel, controller, workspace, alpha = stale_env
    workspace.set_slot_text(0, "edited, not saved")
    before = alpha.read_bytes()
    _select(panel, 0)
    panel._on_add_to_job()

    panel.add_saved_button.invoke()

    assert alpha.read_bytes() == before
    assert workspace.dirty is True  # the Prompt tab's edits are left exactly as they were
    assert controller.pack_calls == [["alpha"]]
    assert not _notice_visible(panel)


def test_a_failed_save_adds_nothing_and_keeps_the_notice(stale_env, monkeypatch) -> None:
    panel, controller, workspace, _alpha = stale_env
    workspace.set_slot_text(0, "edited, not saved")
    _select(panel, 0)
    panel._on_add_to_job()

    def refuse(*_args, **_kwargs):
        raise OSError("disk is read-only")

    monkeypatch.setattr(workspace, "save_current_pack", refuse)
    panel.save_and_add_button.invoke()

    assert controller.pack_calls == []
    assert _notice_visible(panel)
    assert "disk is read-only" in panel.pack_action_label.cget("text")


def test_changing_the_selection_dismisses_the_notice(stale_env) -> None:
    panel, controller, workspace, _alpha = stale_env
    workspace.set_slot_text(0, "edited, not saved")
    _select(panel, 0)
    panel._on_add_to_job()
    assert _notice_visible(panel)

    _select(panel, 1)
    panel._update_pack_actions_state()

    assert not _notice_visible(panel)
    assert controller.pack_calls == []


def test_contract_matches_only_the_same_file_and_only_when_dirty(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha.json"
    _write_pack(alpha, "x")
    elsewhere = tmp_path / "sub"
    elsewhere.mkdir()
    twin = elsewhere / "alpha.json"  # same name, different file
    _write_pack(twin, "y")
    workspace = PromptWorkspaceState()
    summaries = [PromptPackSummary(name="alpha", path=twin)]

    assert stale_pack_contract.unsaved_prompt_tab_pack(None, summaries, ["alpha"]) is None
    assert stale_pack_contract.unsaved_prompt_tab_pack(workspace, summaries, ["alpha"]) is None
    workspace.load_pack(alpha)
    workspace.set_slot_text(0, "edit")
    assert stale_pack_contract.unsaved_prompt_tab_pack(workspace, summaries, ["alpha"]) is None
    summaries = [PromptPackSummary(name="alpha", path=alpha)]
    assert stale_pack_contract.unsaved_prompt_tab_pack(workspace, summaries, ["alpha"]) == "alpha"
    workspace.save_current_pack()
    assert stale_pack_contract.unsaved_prompt_tab_pack(workspace, summaries, ["alpha"]) is None
