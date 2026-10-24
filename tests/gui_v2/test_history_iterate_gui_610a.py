"""PR-HISTORY-610A: the History Iterate action and the Pipeline variation editor (real Tk, no GPU, no queueing)."""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.gui import job_history_panel_v2 as panel_module
from src.gui.app_state_v2 import AppStateV2
from src.gui.controllers.history_iterate_service import HistoryIterateRefused, IterateOutcome
from src.gui.history_browser_panel_v2 import HistoryBrowserPanelV2, resolve_history_search
from src.gui.history_iterate_dialog import HistoryIterateDialog
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.history_variation_panel import HistoryVariationPanelV2
from src.gui_v2.history_iterate_model import (
    PIPELINE_SUMMARY,
    REVIEW_SUMMARY,
    IterateAssessment,
    IterateChoice,
)
from src.pipeline.history_variation_compiler import HistoryVariationDraft, compile_history_variation
from tests.gui_v2 import test_history_browser_panel as browser_tests
from tests.gui_v2.test_history_browser_panel import _Controller, _settle, _shown_ids
from tests.pipeline.test_history_variation_compiler_610a import _source

SECRET = "super private prompt words"

repository = browser_tests.repository  # the browser tests' seeded-repository fixture, reused as-is


# --- the History action ------------------------------------------------------------------------


class _FakeService:
    calls: list[tuple[str, str]] = []
    assessment: IterateAssessment | None = None
    failure: Exception | None = None

    def __init__(self, _controller) -> None:
        pass

    def assess(self, job_id: str) -> IterateAssessment:
        return type(self).assessment or IterateAssessment(
            job_id, IterateChoice(True, REVIEW_SUMMARY), IterateChoice(True, PIPELINE_SUMMARY)
        )

    def _run(self, name: str, job_id: str, confirm) -> IterateOutcome:
        type(self).calls.append((name, job_id))
        if type(self).failure is not None:
            raise type(self).failure
        return IterateOutcome(True, f"{name} ok")

    def edit_in_review(self, job_id, confirm_replace=None):
        return self._run("review", job_id, confirm_replace)

    def regenerate_in_pipeline(self, job_id, confirm_replace=None):
        return self._run("pipeline", job_id, confirm_replace)


@pytest.fixture
def fake_service(monkeypatch):
    _FakeService.calls, _FakeService.assessment, _FakeService.failure = [], None, None
    monkeypatch.setattr(panel_module, "HistoryIterateService", _FakeService)
    return _FakeService


class _IterateController(_Controller):
    def __init__(self, repo) -> None:
        super().__init__(repo)
        self.pipeline_controller = SimpleNamespace()


def _browser(tk_root, repo) -> HistoryBrowserPanelV2:
    controller = _IterateController(repo)
    panel = HistoryBrowserPanelV2(
        tk_root, search=resolve_history_search(controller), controller=controller
    )
    panel.pack()
    _settle(tk_root, panel)
    return panel


def _select(panel, job_id: str) -> None:
    item = next(item for item, job in panel._item_to_job.items() if job == job_id)
    panel.history_tree.selection_set(item)
    panel._on_select()


def _dialog(panel) -> HistoryIterateDialog:
    return next(
        child for child in panel.winfo_children() if isinstance(child, HistoryIterateDialog)
    )


def test_browse_all_offers_iterate_for_the_selected_job_even_after_paging(
    tk_root, repository, fake_service
):
    panel = _browser(tk_root, repository)
    panel.page_size = 3
    panel._on_search()
    _settle(tk_root, panel)
    panel._on_load_more()
    _settle(tk_root, panel)
    assert (
        len(_shown_ids(panel)) == 6
    )  # the second page was appended: selection must map to the right row
    _select(panel, "job-1")
    assert str(panel.iterate_btn.cget("state")) == "normal"
    panel._on_iterate()
    dialog = _dialog(panel)
    dialog.edit_btn.invoke()
    assert fake_service.calls == [("review", "job-1")]
    assert panel.replay_status_var.get() == "review ok"
    assert not dialog.winfo_exists()
    panel.destroy()


def test_compact_panel_and_browse_all_expose_the_same_iterate_decision(tk_root, repository):
    browser = _browser(tk_root, repository)
    _select(browser, "job-2")
    entry = browser._selected_entry()
    compact = JobHistoryPanelV2(
        tk_root,
        controller=_IterateController(repository),
        app_state=None,
        manage_app_state_subscriptions=False,
    )
    assert (
        compact._history_action_state(entry).iterate
        is browser._history_action_state(entry).iterate
        is True
    )
    failed = replace(entry, status=type(entry.status)("failed"))
    assert not compact._history_action_state(failed).iterate
    assert not browser._history_action_state(failed).iterate
    no_controller = JobHistoryPanelV2(
        tk_root, controller=None, app_state=None, manage_app_state_subscriptions=False
    )
    assert not no_controller._history_action_state(entry).iterate
    for widget in (browser, compact, no_controller):
        widget.destroy()


def test_unavailable_choice_is_disabled_with_its_reason_and_never_calls_the_service(
    tk_root, repository, fake_service
):
    fake_service.assessment = IterateAssessment(
        "job-4",
        IterateChoice(True, REVIEW_SUMMARY),
        IterateChoice(
            False, PIPELINE_SUMMARY, "Randomized or Matrix-expanded recipes cannot be represented."
        ),
    )
    panel = _browser(tk_root, repository)
    _select(panel, "job-4")
    panel._on_iterate()
    dialog = _dialog(panel)
    assert str(dialog.regenerate_btn.cget("state")) == "disabled"
    assert str(dialog.edit_btn.cget("state")) == "normal"
    texts = []

    def walk(widget):
        texts.append(str(widget.cget("text")) if "text" in widget.keys() else "")
        for child in widget.winfo_children():
            walk(child)

    walk(dialog)
    assert any("Not available: Randomized" in text for text in texts)
    dialog.destroy()
    assert fake_service.calls == []
    panel.destroy()


def test_refusal_and_failure_are_reported_in_the_status_line_without_loading(
    tk_root, repository, fake_service
):
    panel = _browser(tk_root, repository)
    _select(panel, "job-3")
    fake_service.failure = HistoryIterateRefused("Recorded image file is missing: out.png")
    panel._on_iterate()
    _dialog(panel).regenerate_btn.invoke()
    assert panel.replay_status_var.get() == "Not loaded: Recorded image file is missing: out.png"
    fake_service.failure = RuntimeError(SECRET)
    panel._on_iterate()
    _dialog(panel).edit_btn.invoke()
    status = panel.replay_status_var.get()
    assert "Iterate failed" in status and SECRET not in status
    panel.destroy()


def test_replay_is_unchanged_by_the_new_action(tk_root, repository, fake_service):
    panel = _browser(tk_root, repository)
    _select(panel, "job-2")
    panel._on_replay_job()
    assert panel.controller.replayed == ["job-2"] and fake_service.calls == []
    panel.destroy()


# --- the variation editor ----------------------------------------------------------------------


@pytest.fixture
def editor(tk_root):
    state = AppStateV2()
    panel = HistoryVariationPanelV2(tk_root, app_state=state)
    panel.pack()
    yield state, panel
    panel.destroy()


def _begin(state, **kwargs) -> HistoryVariationDraft:
    draft = HistoryVariationDraft.from_source(
        _source(**kwargs), recorded_seed=777, parent_artifact_id="sha256:abc"
    )
    state.begin_history_variation(draft)
    return draft


def _type(panel, entry, value: str) -> None:
    entry.delete(0, tk.END)
    entry.insert(0, value)
    panel._apply_from_widgets()


def test_panel_is_empty_without_a_variation_and_shows_the_recipe_with_one(editor):
    state, panel = editor
    assert not panel._body.winfo_manager()
    _begin(state)
    assert panel._body.winfo_manager()
    assert panel.title_var.get() == "Variation of parent-job (unsent draft)"
    assert panel.positive_text.get("1.0", "end-1c") == "a red fox, <lora:fox:0.8>"
    assert (panel.seed_var.get(), panel.steps_var.get(), panel.cfg_var.get()) == (
        "1234",
        "30",
        "6.5",
    )
    assert "Checkpoint: sdxlBase.safetensors" in panel.inherited_var.get()
    assert "777" in panel.seed_hint_var.get()
    assert panel.changes_var.get().startswith("No changes")


def test_each_edit_replaces_the_draft_and_invalidates_the_preview(editor):
    state, panel = editor
    draft = _begin(state)
    state.preview_jobs = [object()]
    panel.positive_text.insert("end", " at dusk")
    _type(panel, panel.seed_entry, "9")
    _type(panel, panel.steps_entry, "44")
    _type(panel, panel.cfg_entry, "7.5")
    current = state.job_draft.history_variation
    assert (current.edits.seed, current.edits.steps, current.edits.cfg_scale) == (9, 44, 7.5)
    assert current.edits.positive_prompt.endswith("at dusk") and current.baseline == draft.baseline
    assert state.preview_jobs == []
    changes = panel.changes_var.get()
    assert (
        "seed: 1234 -> 9" in changes
        and "steps: 30 -> 44" in changes
        and "positive prompt edited" in changes
    )
    assert "dusk" not in changes  # the summary never repeats prompt text


def test_an_unparseable_field_blocks_compilation_instead_of_keeping_a_stale_value(editor):
    state, panel = editor
    _begin(state)
    _type(panel, panel.seed_entry, "nine")
    assert "Seed must be a whole number." in panel.error_var.get()
    with pytest.raises(ValueError, match="Seed"):
        compile_history_variation(state.job_draft.history_variation)
    _type(panel, panel.seed_entry, "10")
    assert panel.error_var.get() == ""
    assert compile_history_variation(state.job_draft.history_variation).seed == 10


def test_out_of_range_values_show_the_validation_error(editor):
    state, panel = editor
    _begin(state)
    _type(panel, panel.steps_entry, "999")
    assert "Steps must be an integer from 1 through 150." in panel.error_var.get()


def test_recorded_seed_reset_and_discard(editor):
    state, panel = editor
    _begin(state)
    panel.recorded_seed_btn.invoke()
    assert state.job_draft.history_variation.edits.seed == 777 and panel.seed_var.get() == "777"
    assert str(panel.recorded_seed_btn.cget("state")) == "disabled"
    panel.reset_btn.invoke()
    assert state.job_draft.history_variation.edits == state.job_draft.history_variation.baseline
    assert panel.seed_var.get() == "1234"
    panel.discard_btn.invoke()
    assert state.job_draft.history_variation is None and not panel._body.winfo_manager()


def test_negative_prompt_is_read_only_when_the_frozen_profile_forbids_one(editor):
    state, panel = editor
    draft = HistoryVariationDraft.from_source(_source())
    state.begin_history_variation(replace(draft, negative_editable=False))
    assert str(panel.negative_text.cget("state")) == "disabled"
    assert "does not accept a negative prompt" in panel.negative_note_var.get()
    panel.positive_text.insert("end", "!")
    panel._apply_from_widgets()
    assert state.job_draft.history_variation.edits.negative_prompt == draft.baseline.negative_prompt


def test_sfw_mode_redacts_and_locks_prompts_it_cannot_show(editor):
    state, panel = editor
    state.content_visibility_mode = "sfw"
    state.begin_history_variation(
        HistoryVariationDraft.from_source(
            _source(
                positive_prompt="explicit scene",
                config={**_source().config, "prompt": "explicit scene"},
            )
        )
    )
    assert panel.positive_text.get("1.0", "end-1c") == "[Hidden in SFW mode]"
    assert str(panel.positive_text.cget("state")) == "disabled"
    _type(
        panel, panel.steps_entry, "40"
    )  # numbers stay editable and never write the redacted text back
    edits = state.job_draft.history_variation.edits
    assert edits.steps == 40 and edits.positive_prompt == "explicit scene"
    assert "explicit" not in panel.changes_var.get() + panel.error_var.get() + panel.title_var.get()


def test_the_editor_survives_the_clock(editor):
    state, panel = editor
    _begin(state)
    deadline = time.monotonic() + 0.05
    while time.monotonic() < deadline:
        panel.update()
    assert panel._body.winfo_manager()
