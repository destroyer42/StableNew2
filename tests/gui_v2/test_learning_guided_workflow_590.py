"""Real-Tk coverage of the guided Designed Experiments workflow with a fake JobService.

Nothing here starts generation: the only submission seam is a recording fake over a temporary repository.
"""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import thaw_snapshot
from src.learning.guided_workflow import (
    ACTION_BUILD_PREVIEW,
    ACTION_RUN,
    ACTION_VIEW_PROGRESS,
    STEP_COMPARE,
    STEP_DESIGN,
    STEP_ORDER,
    STEP_PREVIEW,
    STEP_RATE,
    STEP_RUN,
)
from src.queue.job_repository import JobRepository
from src.services.ui_state_store import UIStateStore
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_learning_recovery_260 import RepositoryService
from tests.learning_v2.test_model_comparison_140 import baseline, policy


@pytest.fixture
def root():
    shared = get_shared_tk_root()
    if shared is None:
        pytest.skip("No display available for Tkinter tests")
    return shared


@pytest.fixture
def repository(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    yield repo
    repo.close()


def build_tab(root, tmp_path, repository):
    store = UIStateStore(tmp_path / "ui_state.json")
    service = RepositoryService(repository)
    cards = SimpleNamespace(
        txt2img_card=SimpleNamespace(cfg_var=tk.DoubleVar(master=root, value=7.0))
    )
    with (
        patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store),
        patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=tmp_path / "experiments",
        ),
        patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_records_path",
            return_value=tmp_path / "learning_records.jsonl",
        ),
    ):
        tab = LearningTabFrame(
            root,
            app_state=AppStateV2(),
            pipeline_controller=SimpleNamespace(_job_service=service, stage_cards_panel=cards),
        )
    controller = tab.learning_controller
    controller._get_baseline_config = lambda: baseline()
    controller._learning_policy_resolver = policy
    controller.execution_controller = LearningExecutionController(
        controller.learning_state, service
    )
    controller.execution_controller.set_completion_callback(
        controller._apply_variant_completion_evidence
    )
    controller.execution_controller.set_presentation_callback(
        controller._on_variant_completion_published
    )
    controller.execution_controller.set_failure_callback(controller._on_variant_job_failed)
    return tab, service


@pytest.fixture
def tab_and_service(root, tmp_path, repository):
    tab, service = build_tab(root, tmp_path, repository)
    tab.pack(fill="both", expand=True)
    root.update()
    yield tab, service
    tab.destroy()


def design_cfg_sweep(panel, *, end=8.0):
    panel.name_var.set("cfg sweep")
    panel.stage_var.set("txt2img")
    panel._on_stage_changed()
    panel.variable_var.set("CFG Scale")
    panel._on_variable_changed()
    panel.start_var.set(6.0)
    panel.end_var.set(end)
    panel.step_var.set(1.0)
    panel.images_var.set(2)
    panel.prompt_source_var.set("custom")
    panel._on_prompt_source_changed()
    panel.custom_prompt_text.config(state="normal")
    panel.custom_prompt_text.delete("1.0", tk.END)
    panel.custom_prompt_text.insert("1.0", "portrait")


def primary(tab):
    return tab.workflow_bar.primary_action, str(tab.workflow_bar.primary_button.cget("text"))


def primary_enabled(tab):
    return "disabled" not in tab.workflow_bar.primary_button.state()


def click_primary(tab, root):
    tab.workflow_bar.primary_button.invoke()
    root.update()


# ------------------------------------------------------------------------------------------- design and preview


def test_a_new_session_opens_on_design_with_controlled_variable_as_the_default(tab_and_service):
    tab, _service = tab_and_service
    panel = tab.experiment_panel

    assert tab._viewed_step == STEP_DESIGN
    assert primary(tab) == (ACTION_BUILD_PREVIEW, "Build Preview")
    assert panel.study_type_var.get() == "Controlled Variable"
    assert "Test several values for one setting" in panel.study_hint_var.get()
    assert not panel.study_section.is_expanded()
    # Only the design page is shown; the plan, review and recommendation panes are not competing with it.
    assert [str(p) for p in tab.designed_horizontal_panes.panes()] == [str(tab.design_host)]
    assert tab.workflow_bar.step_buttons[STEP_PREVIEW].instate(["disabled"])
    assert str(panel.run_button.winfo_manager()) == ""  # one primary action on Design, not two


def test_the_estimated_work_is_visible_before_any_preview_exists(tab_and_service, root):
    tab, service = tab_and_service
    panel = tab.experiment_panel

    design_cfg_sweep(panel)
    root.update()

    assert "3 variants x 2 images = 6 images" in panel.estimate_var.get()
    panel.end_var.set(5.0)  # an invalid range (start 6 > end 5) is reported, not guessed
    assert "valid range" in panel.estimate_var.get()
    assert service.calls == []


def test_advanced_study_types_stay_reachable_and_keep_their_own_forms(tab_and_service, root):
    tab, _service = tab_and_service
    panel = tab.experiment_panel

    panel.study_section.set_expanded(True)  # the disclosure is a real, labelled control
    assert "Advanced study types" in panel.study_section.header_text()
    assert list(panel.study_type_combo.cget("values")) == [
        "Controlled Variable",
        "Prompt Slot",
        "Model Comparison",
        "Two-Axis Grid",
    ]
    panel.study_type_var.set("Model Comparison")
    panel._on_study_type_changed()
    root.update()
    assert "Compare several models" in panel.study_hint_var.get()
    assert panel.stage_var.get() == "txt2img" and str(panel.stage_combo.cget("state")) == "disabled"
    assert panel.study_section.is_expanded()

    panel.study_type_var.set("Two-Axis Grid")
    panel._on_study_type_changed()
    root.update()
    assert "Vary two settings" in panel.study_hint_var.get()
    assert panel.grid_frame.winfo_manager() == "grid"

    panel.study_type_var.set("Controlled Variable")
    panel._on_study_type_changed()
    assert panel.grid_frame.winfo_manager() == ""
    assert str(panel.stage_combo.cget("state")) == "readonly"


def test_build_preview_queues_nothing_and_opens_the_preview_with_a_frozen_summary(
    tab_and_service, root
):
    tab, service = tab_and_service
    design_cfg_sweep(tab.experiment_panel)

    click_primary(tab, root)

    experiment = tab.learning_controller.learning_state.current_experiment
    assert experiment is not None and experiment.execution_snapshot_json
    assert service.calls == []
    assert tab._viewed_step == STEP_PREVIEW
    assert primary(tab) == (ACTION_RUN, "Run Experiment") and primary_enabled(tab)
    assert tab.workflow_bar.status_var.get().endswith("Preview ready - not queued")
    headline = tab.preview_card.headline_var.get()
    assert headline == "3 variants x 2 images = 6 expected images"
    assert [str(p) for p in tab.designed_horizontal_panes.panes()] == [str(tab.workspace_host)]
    assert str(tab.summary_host) in [str(p) for p in tab.workspace_panes.panes()]
    assert len(tab.learning_controller.learning_state.plan) == 3
    assert all(not v.job_id for v in tab.learning_controller.learning_state.plan)


def test_editing_after_preview_marks_it_stale_and_run_cannot_submit_it(tab_and_service, root):
    tab, service = tab_and_service
    panel = tab.experiment_panel
    design_cfg_sweep(panel)
    click_primary(tab, root)
    frozen = tab.learning_controller.learning_state.current_experiment.execution_snapshot_json
    assert not panel.preview_is_stale()

    tab._on_step_selected(STEP_DESIGN)
    panel.end_var.set(9.0)
    root.update()
    tab._on_step_selected(STEP_PREVIEW)

    assert panel.preview_is_stale()
    assert not primary_enabled(tab) and primary(tab)[0] == ACTION_RUN
    assert "Preview out of date" in tab.workflow_bar.status_var.get()
    assert "OUT OF DATE" in tab.preview_card.headline_var.get()
    assert panel.request_run() == 0
    assert "Build Preview again" in panel.feedback_var.get()
    assert service.calls == []
    assert (
        tab.learning_controller.learning_state.current_experiment.execution_snapshot_json == frozen
    )

    tab._on_step_selected(STEP_DESIGN)
    click_primary(tab, root)  # rebuilding produces a new frozen snapshot from the edited design
    assert not panel.preview_is_stale()
    rebuilt = tab.learning_controller.learning_state.current_experiment.execution_snapshot_json
    assert thaw_snapshot(rebuilt)["variant_values"] == [6.0, 7.0, 8.0, 9.0]
    assert tab.preview_card.headline_var.get() == "4 variants x 2 images = 8 expected images"


def test_a_validation_error_is_shown_inline_with_the_corrective_action(tab_and_service, root):
    tab, service = tab_and_service
    panel = tab.experiment_panel
    design_cfg_sweep(panel)
    panel.name_var.set("")

    click_primary(tab, root)

    assert "Experiment name is required" in panel.feedback_var.get()
    assert service.calls == []
    assert tab._viewed_step == STEP_DESIGN
    assert tab.learning_controller.learning_state.plan == []


# ------------------------------------------------------------------------------------------------- run


def test_run_is_one_all_or_none_admission_and_a_second_click_admits_nothing_more(
    tab_and_service, root
):
    tab, service = tab_and_service
    panel = tab.experiment_panel
    design_cfg_sweep(panel)
    click_primary(tab, root)

    click_primary(tab, root)  # Run Experiment

    assert len(service.calls) == 1 and len(service.calls[0]) == 3
    plan = tab.learning_controller.learning_state.plan
    assert [v.job_id for v in plan] == [record.job_id for record in service.calls[0]]
    assert all(v.status == "queued" for v in plan)
    assert tab._viewed_step == STEP_RUN
    assert "Sent 3 jobs to the queue" in panel.feedback_var.get()
    assert primary(tab) == (ACTION_VIEW_PROGRESS, "View Progress")
    assert tab.workflow_bar.status_var.get().endswith("Queued")

    click_primary(tab, root)  # the same button no longer runs; it follows progress
    assert panel.request_run() == 0  # and a direct second Run admits nothing either
    assert len(service.calls) == 1
    # The frozen NJRs are what was submitted: nothing was recompiled from live cards.
    assert {record.job_id for record in service.calls[0]} == {v.job_id for v in plan}


def test_run_does_not_claim_success_when_nothing_was_admitted(tab_and_service, root):
    tab, service = tab_and_service
    panel = tab.experiment_panel
    design_cfg_sweep(panel)
    click_primary(tab, root)
    tab.learning_controller.pipeline_controller = None  # run_plan returns without admitting

    assert panel.request_run() == 0

    assert "Sent" not in panel.feedback_var.get()
    assert "Nothing new was queued" in panel.feedback_var.get()
    assert service.calls == []


def test_an_ambiguous_admission_stays_requires_attention_and_is_never_retried(
    tab_and_service, root
):
    tab, service = tab_and_service
    panel = tab.experiment_panel
    design_cfg_sweep(panel)
    click_primary(tab, root)
    service.mode = "raise_after"  # the response is lost after the repository committed the jobs

    click_primary(tab, root)

    assert len(service.calls) == 1
    assert "Do not retry" in panel.feedback_var.get() and "Sent" not in panel.feedback_var.get()
    assert tab.workflow_bar.status_var.get().endswith("Requires attention")
    assert "Nothing is retried automatically" in tab.workflow_bar.notice_var.get()
    assert tab._viewed_step == STEP_RUN
    # Every job kept its exact identity, so the primary action follows progress; it cannot run again.
    assert all(v.job_id for v in tab.learning_controller.learning_state.plan)
    assert primary(tab)[0] == ACTION_VIEW_PROGRESS
    click_primary(tab, root)
    assert panel.request_run() == 0
    assert len(service.calls) == 1


# ----------------------------------------------------------------------------------------------- navigation


def test_navigating_between_steps_only_changes_the_page(tab_and_service, root):
    tab, service = tab_and_service
    design_cfg_sweep(tab.experiment_panel)
    click_primary(tab, root)
    click_primary(tab, root)
    controller = tab.learning_controller
    plan_before = [v.to_dict() for v in controller.learning_state.plan]
    snapshot_before = controller.learning_state.current_experiment.execution_snapshot_json
    drafts_before = dict(controller.learning_state.review_drafts)

    for step in (STEP_DESIGN, STEP_PREVIEW, STEP_RUN, STEP_DESIGN, STEP_RUN):
        tab.workflow_bar.step_buttons[step].invoke()
        root.update()
        assert tab._viewed_step == step

    assert [v.to_dict() for v in controller.learning_state.plan] == plan_before
    assert controller.learning_state.current_experiment.execution_snapshot_json == snapshot_before
    assert controller.learning_state.review_drafts == drafts_before
    assert len(service.calls) == 1
    # Earlier steps stay reachable after the experiment moved on.
    assert not tab.workflow_bar.step_buttons[STEP_DESIGN].instate(["disabled"])
    assert not tab.workflow_bar.step_buttons[STEP_PREVIEW].instate(["disabled"])


def test_compare_and_rate_pages_show_the_right_controls_and_one_task_at_a_time(
    tab_and_service, root
):
    tab, _service = tab_and_service
    review = tab.review_panel

    tab._goto_step(STEP_COMPARE)
    assert review._mode == "compare"
    assert review.variant_summary_list.winfo_manager() == "grid"
    assert (
        review.rating_frame.winfo_manager() == ""
        and review.rating_action_strip.winfo_manager() == ""
    )
    assert [str(p) for p in tab.workspace_panes.panes()] == [str(tab.review_host)]

    tab._goto_step(STEP_RATE)
    assert review._mode == "rate"
    assert (
        review.rating_frame.winfo_manager() == "grid"
        and review.rating_action_strip.winfo_manager() == "grid"
    )
    assert review.variant_summary_list.winfo_manager() == ""
    assert review.recommendations_frame.winfo_manager() == "grid"
    assert str(tab.summary_host) not in [str(p) for p in tab.workspace_panes.panes()]


def test_the_recommendation_mode_selector_lives_with_the_recommendations_not_the_header(
    tab_and_service,
):
    tab, _service = tab_and_service

    assert tab.automation_mode_box.master is tab.review_panel.mode_host
    header_text = {
        str(c.cget("text")) for c in tab.header_frame.winfo_children() if "text" in c.keys()
    }
    assert "Recommendations:" not in header_text
    assert tab.learning_controller.get_automation_mode() == "apply_with_confirm"


def test_existing_tools_stay_reachable_in_the_header_and_notebook(tab_and_service):
    tab, _service = tab_and_service

    header_buttons = {
        str(c.cget("text"))
        for c in tab.header_frame.winfo_children()
        if c.winfo_class() == "TButton"
    }
    assert {
        "New Experiment",
        "Clone as New",
        "Experiment Library",
        "Save Stored Drafts...",
    } <= header_buttons
    tabs = [tab._mode_notebook.tab(t, "text") for t in tab._mode_notebook.tabs()]
    assert tabs == ["Designed Experiments", "Discovered Outputs", "Staged Curation"]
    assert tab.review_panel.analytics_button.winfo_exists()
    assert tab.review_panel.save_all_drafts_button.winfo_exists()
    assert tab.review_panel.compare_button.winfo_exists()


def test_every_step_button_and_the_primary_action_are_keyboard_reachable_in_a_compact_window(
    root, tmp_path, repository
):
    tab, _service = build_tab(root, tmp_path, repository)
    try:
        root.geometry("1366x768")
        tab.place(x=0, y=0, width=1366, height=720)
        root.deiconify()
        root.update()
        bar = tab.workflow_bar
        assert bar.winfo_reqwidth() <= 1366
        for step in STEP_ORDER:
            assert str(bar.step_buttons[step].cget("takefocus")) in {"", "1", "ttk::takefocus"}
            assert bar.step_buttons[step].winfo_ismapped()
        assert bar.primary_button.winfo_ismapped()
        assert tab.experiment_scroll._vsb.winfo_manager() == "grid"
        bar.primary_button.focus_force()
        root.update()
        assert root.focus_get() is bar.primary_button
    finally:
        tab.destroy()
        root.withdraw()


# ------------------------------------------------------------------------------------------------- restore


def test_restoring_a_queued_experiment_reopens_at_run_without_resubmitting(
    root, tmp_path, repository
):
    first, service = build_tab(root, tmp_path, repository)
    try:
        first.pack(
            fill="both", expand=True
        )  # the Design step is on screen: the baseline seeds on first display
        root.update()
        design_cfg_sweep(first.experiment_panel)
        click_primary(first, root)
        click_primary(first, root)
        payload = first.get_learning_session_state()
        job_ids = [v.job_id for v in first.learning_controller.learning_state.plan]
        assert len(service.calls) == 1
    finally:
        first.destroy()

    second, second_service = build_tab(root, tmp_path, repository)
    try:
        assert second.restore_learning_session_state(payload)
        root.update()
        restored = second.learning_controller.learning_state.plan
        assert [v.job_id for v in restored] == job_ids
        assert second._viewed_step == STEP_RUN
        assert second_service.calls == []  # restoring reconciles; it never resubmits
        assert primary(second)[0] == ACTION_VIEW_PROGRESS
        assert not second.experiment_panel.preview_is_stale()
    finally:
        second.destroy()


def test_no_ui_navigation_reaches_a_runner_or_backend(tab_and_service, root):
    tab, service = tab_and_service
    design_cfg_sweep(tab.experiment_panel)
    with patch(
        "src.pipeline.pipeline_runner.PipelineRunner.run_njr", side_effect=AssertionError("runner")
    ):
        for _ in range(2):
            click_primary(tab, root)
        for step in STEP_ORDER:
            tab._goto_step(step)
            root.update()
    assert len(service.calls) == 1  # only the one explicit, queue-first Run
