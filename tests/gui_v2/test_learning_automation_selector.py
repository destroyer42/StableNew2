"""The Learning tab's recommendation-mode selector: default, choice, persistence and migration of the old value."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.learning.automation_modes import AUTOMATION_MODE_LABELS
from src.services.ui_state_store import UIStateStore
from tests.gui_v2.tk_test_utils import get_shared_tk_root


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


@pytest.fixture
def tab(tmp_path: Path):
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("No display available for Tkinter tests")
    store = UIStateStore(tmp_path / "ui_state.json")
    with (
        patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store),
        patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=tmp_path / "experiments",
        ),
    ):
        frame = LearningTabFrame(
            root, app_state=AppStateV2(), pipeline_controller=_StubPipelineController()
        )
        yield frame
        frame.destroy()


def _choose(tab: LearningTabFrame, mode: str) -> None:
    tab.automation_mode_box.set(AUTOMATION_MODE_LABELS[mode])
    tab.automation_mode_box.event_generate("<<ComboboxSelected>>")
    tab.update()


def test_a_new_tab_starts_in_apply_with_confirm(tab: LearningTabFrame) -> None:
    assert tab.learning_controller.get_automation_mode() == "apply_with_confirm"
    assert tab.automation_mode_box.get() == AUTOMATION_MODE_LABELS["apply_with_confirm"]
    state = tab.get_learning_session_state()
    assert state["automation_mode"] == "apply_with_confirm"
    assert state["automation_mode_user_set"] is False


def test_every_mode_is_selectable_including_auto_micro_experiment(tab: LearningTabFrame) -> None:
    assert list(tab.automation_mode_box.cget("values")) == [
        AUTOMATION_MODE_LABELS[mode]
        for mode in ("suggest_only", "apply_with_confirm", "auto_micro_experiment")
    ]


@pytest.mark.parametrize("mode", ["suggest_only", "auto_micro_experiment"])
def test_choosing_a_mode_reaches_the_controller_and_is_saved_as_a_choice(
    tab: LearningTabFrame, mode: str
) -> None:
    _choose(tab, mode)

    assert tab.learning_controller.get_automation_mode() == mode
    state = tab.get_learning_session_state()
    assert (state["automation_mode"], state["automation_mode_user_set"]) == (mode, True)


def test_a_saved_choice_is_restored(tab: LearningTabFrame) -> None:
    tab.restore_learning_session_state(
        {"enabled": True, "automation_mode": "suggest_only", "automation_mode_user_set": True}
    )

    assert tab.learning_controller.get_automation_mode() == "suggest_only"
    assert tab.automation_mode_box.get() == AUTOMATION_MODE_LABELS["suggest_only"]


def test_the_old_hardcoded_suggest_only_is_migrated_to_the_default(tab: LearningTabFrame) -> None:
    tab.restore_learning_session_state({"enabled": True, "automation_mode": "suggest_only"})

    assert tab.learning_controller.get_automation_mode() == "apply_with_confirm"
    assert tab.get_learning_session_state()["automation_mode_user_set"] is False


def test_a_stored_session_saved_under_the_old_default_is_migrated_too(
    tab: LearningTabFrame,
) -> None:
    session = {
        "current_experiment": {"name": "Old", "experiment_id": "exp-old"},
        "plan": [],
        "automation_mode": "suggest_only",
    }

    tab._restore_from_store_payload(session)  # noqa: SLF001

    assert tab.learning_controller.get_automation_mode() == "apply_with_confirm"


def _report(committed: int):
    from src.gui.controllers.learning_stored_drafts import StoredDraftsReport
    from src.learning.draft_commit import DraftCommitSummary

    return StoredDraftsReport(
        experiments_with_drafts=2,
        skipped_open_experiments=0,
        unreadable_sessions=0,
        summary=DraftCommitSummary(committed=committed),
        applied=False,
    )


def test_save_stored_drafts_previews_then_applies_only_when_confirmed(
    tab: LearningTabFrame, monkeypatch
) -> None:
    from tkinter import messagebox
    from unittest.mock import Mock

    calls: list[bool] = []

    def fake(store, *, apply):
        calls.append(apply)
        return _report(5)

    monkeypatch.setattr(tab.learning_controller, "commit_stored_review_drafts", fake)
    monkeypatch.setattr(messagebox, "showinfo", Mock())
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: False)
    tab._on_commit_stored_drafts()  # noqa: SLF001
    assert calls == [False]

    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
    tab._on_commit_stored_drafts()  # noqa: SLF001
    assert calls == [False, False, True]


def test_save_stored_drafts_with_nothing_to_save_does_not_ask(
    tab: LearningTabFrame, monkeypatch
) -> None:
    from tkinter import messagebox
    from unittest.mock import Mock

    calls: list[bool] = []
    monkeypatch.setattr(
        tab.learning_controller,
        "commit_stored_review_drafts",
        lambda store, *, apply: calls.append(apply) or _report(0),
    )
    ask = Mock()
    monkeypatch.setattr(messagebox, "askyesno", ask)
    monkeypatch.setattr(messagebox, "showinfo", Mock())

    tab._on_commit_stored_drafts()  # noqa: SLF001

    assert calls == [False]
    ask.assert_not_called()
