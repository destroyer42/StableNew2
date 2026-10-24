"""PR-GUI-UX-520: load / apply / overwrite semantics, confirmations and inline feedback in the Pipeline sidebar."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

import pytest

from src.controller.app_controller_services.pack_settings_apply_service import (
    PackApplyOutcome,
    PackApplyReport,
)
from src.gui.settings_actions_presenter import (
    CHANNEL_PACK,
    CHANNEL_SETTINGS,
    SettingsActionsPresenter,
)
from src.gui.view_contracts import config_source_contract as contract
from tests.gui_v2.test_truthful_controls_500 import FakeController, _build, _select_packs

pytestmark = pytest.mark.gui


# ------------------------------------------------------------------------------------------- presenter, no Tk


class _Ctl:
    def __init__(self) -> None:
        self.fingerprint = "a"

    def working_settings_fingerprint(self) -> str:
        return self.fingerprint


def _presenter(answer: bool = True, ctl: _Ctl | None = None):
    ctl = ctl or _Ctl()
    asked: list[tuple[str, str]] = []
    said: list[tuple[str, str]] = []

    def confirm(title: str, message: str) -> bool:
        asked.append((title, message))
        return answer

    return (
        SettingsActionsPresenter(
            controller_getter=lambda: ctl, confirm=confirm, say=lambda c, t: said.append((c, t))
        ),
        ctl,
        asked,
        said,
    )


def test_load_without_known_unsaved_edits_does_not_ask_but_says_it_replaced_the_settings() -> None:
    presenter, _ctl, asked, said = _presenter()

    outcome = presenter.load(
        CHANNEL_SETTINGS, "startup defaults", lambda: True, succeeded=lambda: False
    )

    assert outcome.loaded and not outcome.replaced_edits and asked == []
    assert said[-1][0] == CHANNEL_SETTINGS
    assert "Loaded startup defaults into the working stage settings" in said[-1][1]
    assert "No PromptPack was changed" in said[-1][1]


def test_load_over_unsaved_edits_asks_first_and_declining_keeps_them() -> None:
    presenter, ctl, asked, said = _presenter(answer=False)
    presenter.mark_working_clean()
    ctl.fingerprint = "edited"
    calls: list[int] = []

    outcome = presenter.load(
        CHANNEL_SETTINGS,
        "startup defaults",
        lambda: calls.append(1) or True,
        succeeded=lambda: True,
    )

    assert outcome.cancelled and not outcome.loaded and calls == []
    assert len(asked) == 1 and "replaces those changes" in asked[0][1]
    assert "kept" in said[-1][1]


def test_load_over_unsaved_edits_when_confirmed_reports_the_replacement() -> None:
    presenter, ctl, asked, said = _presenter(answer=True)
    presenter.mark_working_clean()
    ctl.fingerprint = "edited"

    outcome = presenter.load(CHANNEL_PACK, "x", lambda: None, succeeded=lambda: True)

    assert outcome.loaded and outcome.replaced_edits
    assert "unsaved changes were replaced" in said[-1][1]
    assert not presenter.working_is_dirty()  # the loaded source is the new baseline


def test_failed_load_says_nothing_was_changed_and_keeps_the_baseline() -> None:
    presenter, ctl, _asked, said = _presenter()
    presenter.mark_working_clean()

    outcome = presenter.load(
        CHANNEL_SETTINGS, "startup defaults", lambda: False, succeeded=lambda: True
    )

    assert not outcome.loaded
    assert "working stage settings were not changed" in said[-1][1]


def test_apply_needs_confirmation_and_declining_writes_nothing() -> None:
    presenter, _ctl, asked, said = _presenter(answer=False)
    calls: list[list[str]] = []

    result = presenter.apply_to_packs(
        "the current stage settings", ["p1", "p2"], lambda ids: calls.append(ids)
    )

    assert result is None and calls == []
    assert "2 PromptPacks" in asked[0][1] and "'p1', 'p2'" in asked[0][1]
    assert "prompts, Matrix and slot order are not changed" in asked[0][1]
    assert said[-1] == (CHANNEL_PACK, "Apply cancelled; no PromptPack was changed.")


def test_apply_result_is_truthful_for_success_partial_and_total_failure() -> None:
    presenter, _ctl, _asked, said = _presenter()
    ok = PackApplyReport("S", (PackApplyOutcome("a", True), PackApplyOutcome("b", True)))
    partial = PackApplyReport(
        "S", (PackApplyOutcome("a", True), PackApplyOutcome("b", False, "bad schema"))
    )
    none = PackApplyReport("S", (PackApplyOutcome("a", False, "missing"),))

    presenter.apply_to_packs("S", ["a", "b"], lambda ids: ok)
    assert said[-1][1] == "Applied S to 2 PromptPacks: 'a', 'b'."

    presenter.apply_to_packs("S", ["a", "b"], lambda ids: partial)
    assert "Partly applied S: updated 1 of 2 ('a')" in said[-1][1]
    assert "Not updated 'b': bad schema" in said[-1][1]
    assert "all" not in said[-1][1].lower().replace("the others", "")

    presenter.apply_to_packs("S", ["a"], lambda ids: none)
    assert said[-1][1].startswith("Could not apply S: no PromptPack was changed.")


def test_apply_with_no_target_or_a_raising_controller_is_reported_not_raised() -> None:
    presenter, _ctl, asked, said = _presenter()

    assert presenter.apply_to_packs("S", [], lambda ids: None) is None
    assert asked == [] and "Select at least one PromptPack" in said[-1][1]

    def boom(_ids: list[str]) -> Any:
        raise RuntimeError("disk gone")

    assert presenter.apply_to_packs("S", ["a"], boom) is None
    assert "Could not apply S: disk gone" in said[-1][1]


class _ReportingController(FakeController):
    def __init__(self, config_manager: Any = None) -> None:
        super().__init__(config_manager)
        self.report: PackApplyReport | None = None
        self.fingerprint = "clean"

    def working_settings_fingerprint(self) -> str:
        return self.fingerprint

    def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> PackApplyReport | None:
        self._record("save_to_packs", tuple(pack_ids))
        return self.report

    def on_pipeline_pack_load_config(self, pack_id: str) -> bool:
        self._record("load_pack", pack_id)
        return pack_id == "p1"


def _sidebar(tk_root: tk.Tk, tmp_path: Path, **kwargs: Any):
    panel, _fake, config_manager = _build(tk_root, tmp_path, **kwargs)
    controller = _ReportingController(config_manager)
    panel.controller = controller
    panel._actions._controller_getter = lambda: controller
    return panel, controller, config_manager


def test_apply_to_packs_is_confirmed_names_targets_and_reports_partial_failure(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    panel, controller, _ = _sidebar(tk_root, tmp_path, packs=["p1", "p2", "p3"])
    try:
        controller.report = PackApplyReport(
            "the current stage settings",
            (PackApplyOutcome("p1", True), PackApplyOutcome("p2", False, "schema_version 2")),
        )
        _select_packs(panel, 0, 1)
        assert panel.apply_config_button.cget("text") == "Apply to 2 Packs…"

        panel._on_pack_apply_config()

        assert panel.asked and "'p1', 'p2'" in panel.asked[-1][1]
        assert controller.calls[-1] == ("save_to_packs", (("p1", "p2"),))
        text = panel.pack_action_label.cget("text")
        assert "updated 1 of 2" in text and "Not updated 'p2': schema_version 2" in text
        # Selection survives the action.
        assert [panel._current_pack_names[i] for i in panel.pack_listbox.curselection()] == [
            "p1",
            "p2",
        ]
    finally:
        panel.destroy()


def test_declined_apply_never_reaches_the_controller(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel, controller, _ = _sidebar(tk_root, tmp_path, packs=["p1"])
    try:
        panel._confirm_override = lambda title, message: False
        _select_packs(panel, 0)
        assert panel.apply_config_button.cget("text") == "Apply to 1 Pack…"

        panel._on_pack_apply_config()

        assert controller.calls == []
        assert "Apply cancelled" in panel.pack_action_label.cget("text")
    finally:
        panel.destroy()


def test_apply_button_names_no_count_without_a_selection(tk_root: tk.Tk, tmp_path: Path) -> None:
    panel, _controller, _ = _sidebar(tk_root, tmp_path, packs=["p1", "p2"])
    try:
        _select_packs(panel, 0, 1)
        _select_packs(panel)
        assert panel.apply_config_button.cget("text") == contract.APPLY_PACK_CONFIG_LABEL
        assert str(panel.apply_config_button.cget("state")) == "disabled"
    finally:
        panel.destroy()


def test_loading_pack_settings_reports_success_and_failure_inline(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    panel, controller, _ = _sidebar(tk_root, tmp_path, packs=["p1", "p2"])
    try:
        _select_packs(panel, 0)
        panel._on_pack_load_config()
        assert "Loaded the saved settings of PromptPack 'p1'" in panel.pack_action_label.cget(
            "text"
        )

        _select_packs(panel, 1)
        panel._on_pack_load_config()
        assert "Could not load" in panel.pack_action_label.cget("text")
        assert panel._settings_source.name == "p1"
    finally:
        panel.destroy()


def test_user_facing_terms_name_the_concepts_without_mixing_them() -> None:
    texts = [
        contract.NO_PACK_LISTS_TEXT,
        contract.PACK_SELECTOR_HELP,
        contract.SAVE_PACK_CONFIG_TIP,
        contract.OVERRIDE_ON_TEXT,
        contract.SAVE_STARTUP_DEFAULTS_LABEL,
        contract.SAVE_STARTUP_DEFAULTS_TIP,
    ]
    joined = " ".join(texts)

    assert (
        "startup defaults" in joined.lower()
        and "Saved Pack List" in joined
        and "Current Job Overrides" in joined
    )
    assert "holds no settings" in contract.NO_PACK_LISTS_TEXT
    assert "Nothing is written to the packs" in contract.OVERRIDE_ON_TEXT
    assert "recipe" not in joined.lower() and "preset" not in joined.lower()


def test_selection_changed_during_confirmation_cannot_redirect_the_write(
    tk_root: tk.Tk, tmp_path: Path
) -> None:
    panel, controller, _ = _sidebar(tk_root, tmp_path, packs=["p1", "p2"])
    try:
        controller.report = PackApplyReport(
            "the current stage settings", (PackApplyOutcome("p1", True),)
        )
        _select_packs(panel, 0)

        def answer_after_reselecting(title: str, message: str) -> bool:
            _select_packs(
                panel, 1
            )  # the operator (or a refresh) changes the selection while the dialog is open
            return True

        panel._confirm_override = answer_after_reselecting
        panel._on_pack_apply_config()

        assert controller.calls[-1] == (
            "save_to_packs",
            (("p1",),),
        )  # the confirmed target, not the new selection
    finally:
        panel.destroy()
