"""N6: the simple Generate workspace and the Advanced switch.

Real ``MainWindowV2`` over the real ``AppController`` with a fake pipeline runner (no WebUI, model, GPU or network).
Simple is the default; Advanced shows every tab and option that exists today; the choice persists; nothing is
removed, refused or submitted by navigation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.gui.batch_builder_dialog import BatchBuilderPanel
from src.gui.controllers.video_workspace_handoff import show_queue_view
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.view_contracts import task_navigation_contract as nav
from src.gui.view_contracts import workspace_mode_contract as mode
from src.gui.views.generate_tab_frame_v2 import GenerateTabFrameV2
from src.services.ui_state_store import get_ui_state_store
from tests.helpers.gui_harness_v2 import GuiV2Harness

pytestmark = pytest.mark.gui

SIMPLE_TABS = ["generate", "review", "video_workflow", "storyboard", "learning"]


@pytest.fixture
def build(tk_root):
    harnesses: list[GuiV2Harness] = []

    def _build(stored_state: dict | None = None) -> GuiV2Harness:
        if stored_state is not None:
            assert get_ui_state_store().save_state(dict(stored_state))
        harness = GuiV2Harness(tk_root)
        harness.controller.main_window = harness.window
        harnesses.append(harness)
        tk_root.update()
        return harness

    yield _build
    for harness in harnesses:
        harness.cleanup()


def _pump(window) -> None:
    window.root.update()


def _shown_destinations(bar) -> list[str]:
    shown: list[str] = []
    for group in nav.TASK_GROUPS:
        if not bar.group_button(group.group_id).winfo_manager():
            continue
        bar.group_button(group.group_id).invoke()
        shown.extend(bar.visible_destination_ids())
    return shown


# ------------------------------------------------------------------------------------------------ Simple default


def test_a_fresh_install_opens_on_generate_in_the_simple_workspace(build) -> None:
    window = build().window
    assert window.workspace_mode == mode.WORKSPACE_SIMPLE
    assert window._current_tab_id() == "generate"
    assert isinstance(window.generate_tab, GenerateTabFrameV2)
    assert window.get_tab("generate") is window.generate_tab
    bar = window.task_navigation
    assert bar.advanced_var.get() is False
    assert str(bar.advanced_check.cget("text")) == "Advanced"
    shown_groups = [
        g.group_id for g in nav.TASK_GROUPS if bar.group_button(g.group_id).winfo_manager()
    ]
    assert shown_groups == ["create", "edit", "motion", "learn"]
    assert _shown_destinations(bar) == SIMPLE_TABS


def test_the_generate_workspace_is_the_batch_builder_queue_and_recent_outputs(build) -> None:
    tab = build().window.generate_tab
    assert isinstance(tab.batch_panel, BatchBuilderPanel)
    assert isinstance(tab.queue_panel, QueuePanelV2)
    assert isinstance(tab.recent_outputs_panel, JobHistoryPanelV2)
    assert tab.batch_panel.cancel_button is None
    assert str(tab.refresh_button.cget("text")) == "Refresh lists"


def test_hidden_tabs_are_still_built_registered_and_selectable(build) -> None:
    window = build().window
    for tab_id in (
        "prompt",
        "pipeline",
        "photo_optimize",
        "svd",
        "movie_clips",
        "character_training",
    ):
        assert window.get_tab(tab_id) is not None
        assert window.select_tab(tab_id)
        _pump(window)
        assert window._current_tab_id() == tab_id
        # a tab reached by a handoff or Ctrl+Tab is shown on the bar while it is open
        assert window.task_navigation.selected_tab_id == tab_id
        assert tab_id in window.task_navigation.visible_destination_ids()
    window.select_tab("review")
    _pump(window)
    window.task_navigation.group_button("create").invoke()
    _pump(window)
    assert window.task_navigation.visible_destination_ids() == ["generate"]


def test_a_handoff_to_the_queue_view_still_works_in_simple(build) -> None:
    window = build().window
    assert show_queue_view(window)
    _pump(window)
    assert window._current_tab_id() == "pipeline"


# ------------------------------------------------------------------------------------------------ Advanced switch


def test_advanced_shows_todays_tabs_and_persists(build) -> None:
    window = build().window
    bar = window.task_navigation
    bar.advanced_check.invoke()
    _pump(window)
    assert window.workspace_mode == mode.WORKSPACE_ADVANCED
    assert _shown_destinations(bar) == list(nav.all_tab_ids())
    assert get_ui_state_store().load_state()["workspace"] == {"mode": "advanced"}


def test_the_stored_mode_and_tab_are_restored_at_startup(build) -> None:
    window = build(
        {"workspace": {"mode": "advanced"}, "tabs": {"selected_tab_id": "pipeline"}}
    ).window
    assert window.workspace_mode == mode.WORKSPACE_ADVANCED
    assert window.task_navigation.advanced_var.get() is True
    assert window._current_tab_id() == "pipeline"


def test_simple_never_opens_on_a_hidden_tab(build) -> None:
    window = build({"tabs": {"selected_tab_id": "pipeline"}}).window
    assert window._current_tab_id() == "generate"


def test_switching_to_simple_on_a_hidden_tab_moves_to_generate(build) -> None:
    window = build({"workspace": {"mode": "advanced"}}).window
    window.select_tab("prompt")
    _pump(window)
    window.set_workspace_mode(mode.WORKSPACE_SIMPLE)
    _pump(window)
    assert window._current_tab_id() == "generate"
    window.select_tab("review")
    window.set_workspace_mode(mode.WORKSPACE_ADVANCED)
    window.set_workspace_mode(mode.WORKSPACE_SIMPLE)
    _pump(window)
    assert window._current_tab_id() == "review"  # a tab Simple shows is kept


def test_mode_switching_never_submits_work(build) -> None:
    harness = build()
    window = harness.window
    with patch("src.controller.job_service.JobService.submit_njrs") as submit:
        window.task_navigation.advanced_check.invoke()
        window.task_navigation.advanced_check.invoke()
        _pump(window)
    submit.assert_not_called()
    assert harness.pipeline_runner.run_calls == []


# ------------------------------------------------------------------------------------------------ Learning


def test_simple_learning_hides_the_discovered_view_and_zero_use_studies(build) -> None:
    window = build().window
    learning = window.learning_tab
    notebook = learning._mode_notebook
    assert notebook.tab(learning._discovered_tab_frame, "state") == "hidden"
    assert notebook.tab(learning.body_frame, "state") == "normal"
    assert notebook.tab(learning._staged_tab_frame, "state") == "normal"
    panel = learning.experiment_panel
    for slug in mode.SIMPLE_HIDDEN_STUDY_SLUGS:
        assert not panel.objective_choices[slug].winfo_manager()
    for slug in ("controlled_variable", "lora_composition", "model_comparison"):
        assert panel.objective_choices[slug].winfo_manager()
    assert not panel._objective_headings["more_comparisons"].winfo_manager()

    window.set_workspace_mode(mode.WORKSPACE_ADVANCED)
    assert notebook.tab(learning._discovered_tab_frame, "state") == "normal"
    for slug in mode.SIMPLE_HIDDEN_STUDY_SLUGS:
        assert panel.objective_choices[slug].winfo_manager()
    assert panel._objective_headings["more_comparisons"].winfo_manager()


def test_a_selected_hidden_study_stays_shown(build) -> None:
    window = build({"workspace": {"mode": "advanced"}}).window
    panel = window.learning_tab.experiment_panel
    panel.choose_study("prompt_slot")
    window.set_workspace_mode(mode.WORKSPACE_SIMPLE)
    assert panel.objective_choices["prompt_slot"].winfo_manager()
    assert not panel.objective_choices["embedding_experiment"].winfo_manager()


# ------------------------------------------------------------------------------------------------ Generate tab


class _Sidebar:
    def __init__(self) -> None:
        self.controller = SimpleNamespace(_background_tasks=object())
        self._current_pack_names = ["castles", "portraits"]
        self.pack_listbox = SimpleNamespace(curselection=lambda: (1,))
        self.stage_states = {
            "adetailer": SimpleNamespace(get=lambda: True),
            "upscale": SimpleNamespace(get=lambda: False),
        }
        base = SimpleNamespace(
            model_choices=lambda: [
                ("Juggernaut", "jugg.safetensors"),
                ("Pony", "pony.safetensors"),
            ],
            selected_model_name=lambda: "pony.safetensors",
        )
        self.get_base_generation_panel = lambda: base


def test_refresh_reads_the_pipeline_promptpack_card(tk_root) -> None:
    sidebar = _Sidebar()
    tab = GenerateTabFrameV2(
        tk_root, app_state=None, app_controller=None, sidebar_provider=lambda: sidebar
    )
    try:
        assert tab.refresh_sources() is True
        assert tab.batch_panel.selected_packs() == ["portraits"]
        assert tab.batch_panel.selected_models() == ["pony.safetensors"]
        assert tab.batch_panel.adetailer_var.get() is True
    finally:
        tab.destroy()


def test_refresh_without_a_pipeline_card_says_so(tk_root) -> None:
    tab = GenerateTabFrameV2(
        tk_root, app_state=None, app_controller=None, sidebar_provider=lambda: None
    )
    try:
        assert tab.refresh_sources() is False
        assert "Pipeline" in tab.batch_panel.status_label.cget("text")
    finally:
        tab.destroy()


def test_hidden_queue_and_history_surfaces_defer_their_refresh(tk_root) -> None:
    from src.gui.app_state_v2 import AppStateV2

    state = AppStateV2()
    tab = GenerateTabFrameV2(
        tk_root, app_state=state, app_controller=None, sidebar_provider=lambda: None
    )
    try:
        calls: list[str] = []
        tab.queue_panel.update_from_app_state = lambda *_a, **_k: calls.append("queue")
        tab.recent_outputs_panel.update_from_app_state = lambda *_a, **_k: calls.append("history")
        tab._mark_dirty("queue", "history")
        tab._flush()
        assert calls == []  # the root is withdrawn: nothing is mapped
        assert tab._dirty == {"queue", "history"}
    finally:
        tab.destroy()
