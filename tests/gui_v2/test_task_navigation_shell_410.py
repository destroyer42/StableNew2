"""PR-GUI-410: the Tk shell binds the task-navigation contract to the one notebook.

Real ``MainWindowV2`` (all nine tab instances) over the real ``AppController`` with a fake pipeline runner; no WebUI,
model, GPU or network. Navigation must never submit work, and the notebook stays the single selection authority.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import pytest

from src.gui.controllers.video_workspace_handoff import (
    route_bundle_to_movie_clips,
    route_image_to_video_workflow,
    route_images_to_review,
    show_queue_view,
)
from src.gui.theme_v2 import apply_theme
from src.gui.view_contracts import task_navigation_contract as nav
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.widgets.task_navigation_bar_v2 import (
    HIDDEN_TABS_NOTEBOOK_STYLE,
    TaskNavigationBar,
)
from src.queue.job_history_store import JobHistoryEntry, JobStatus
from src.services.ui_state_store import get_ui_state_store
from tests.helpers.gui_harness_v2 import GuiV2Harness
from tests.helpers.make_video_313 import ANIMATE2_ID, TI2V_ID, make_image

pytestmark = pytest.mark.gui

TAB_ATTRIBUTES = {
    "prompt": "prompt_tab",
    "pipeline": "pipeline_tab",
    "learning": "learning_tab",
    "review": "review_tab",
    "photo_optimize": "photo_optimize_tab",
    "movie_clips": "movie_clips_tab",
    "character_training": "character_training_tab",
    "svd": "svd_tab",
    "video_workflow": "video_workflow_tab",
}


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


def _current(window) -> str | None:
    return window._current_tab_id()


def _pump(window) -> None:
    window.root.update()


# ------------------------------------------------------------------------------------------ identity and structure


def test_all_nine_tabs_keep_their_ids_attributes_and_notebook_order(build) -> None:
    window = build().window
    assert set(window._tab_registry) == set(TAB_ATTRIBUTES)
    for tab_id, attribute in TAB_ATTRIBUTES.items():
        assert getattr(window, attribute) is window.get_tab(tab_id)
    notebook_paths = [str(widget) for widget in window.center_notebook.tabs()]
    assert notebook_paths == [str(window.get_tab(tab_id)) for tab_id in nav.LEGACY_TAB_ORDER]
    assert window.tab_failures() == {}


def test_visible_names_are_corrected_and_character_training_is_marked_hold(build) -> None:
    harness = build()
    window = harness.window
    assert window.root.title() == "StableNew"
    texts = [window.center_notebook.tab(widget, "text") for widget in window.center_notebook.tabs()]
    assert "Photo Optimize - Adv" in texts
    assert not any("Optomize" in text for text in texts)
    assert "Character Training - HOLD" in texts
    bar = window.task_navigation
    assert bar is not None
    assert bar.destination_button("character_training").cget("text") == "Character Training (HOLD)"
    labels = [
        child.cget("text")
        for child in window.character_training_tab.winfo_children()[0].winfo_children()
        if isinstance(child, ttk.Label)
    ]
    assert any("HOLD" in str(label) for label in labels)


def test_one_navigation_surface_replaces_the_native_tab_strip(build) -> None:
    window = build().window
    bar = window.task_navigation
    assert bar is not None
    assert str(window.center_notebook.cget("style")) == HIDDEN_TABS_NOTEBOOK_STYLE
    assert ttk.Style(window.root).layout(f"{HIDDEN_TABS_NOTEBOOK_STYLE}.Tab") == [
        ("null", {"sticky": "nswe"})
    ]  # empty
    # the bar sits between the header and the notebook, spanning the window
    assert int(bar.grid_info()["row"]) < int(window.center_notebook.grid_info()["row"])
    assert int(window.center_notebook.grid_info()["row"]) < int(
        window.bottom_zone.grid_info()["row"]
    )
    assert window.center_notebook.grid_info().get("columnspan") == 3
    # a group choice plus only that group's destinations - never a second row of nine
    assert len(bar._group_buttons) == 5  # noqa: SLF001
    assert len(bar.visible_destination_ids()) <= 3


def test_native_strip_stays_when_the_navigation_bar_cannot_be_built(tk_root, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise tk.TclError("no bar")

    monkeypatch.setattr("src.gui.main_window_v2.TaskNavigationBar", boom)
    harness = GuiV2Harness(tk_root)
    try:
        window = harness.window
        assert window.task_navigation is None
        assert str(window.center_notebook.cget("style")) != HIDDEN_TABS_NOTEBOOK_STYLE
        # still fully functional through the notebook itself
        assert window.select_tab("review")
        assert _current(window) == "review"
    finally:
        harness.cleanup()


# --------------------------------------------------------------------------------------------- mouse and keyboard


def test_every_tab_is_reachable_by_clicking_group_and_destination_buttons(build) -> None:
    window = build().window
    bar = window.task_navigation
    for group in nav.TASK_GROUPS:
        bar.group_button(group.group_id).invoke()
        _pump(window)
        assert nav.group_for_tab(_current(window)).group_id == group.group_id
        assert bar.active_group_id == group.group_id
        assert set(bar.visible_destination_ids()) == set(group.tab_ids)
        for tab_id in group.tab_ids:
            bar.destination_button(tab_id).invoke()
            _pump(window)
            assert _current(window) == tab_id
            assert bar.selected_tab_id == tab_id
            assert bar._destination_var.get() == tab_id  # noqa: SLF001
            assert str(window.center_notebook.select()) == str(window.get_tab(tab_id))


def test_a_group_click_returns_to_the_last_destination_used_in_that_group(build) -> None:
    window = build().window
    bar = window.task_navigation
    bar.group_button("create").invoke()
    bar.destination_button("prompt").invoke()
    bar.group_button("motion").invoke()
    bar.destination_button("movie_clips").invoke()
    bar.group_button("create").invoke()
    _pump(window)
    assert _current(window) == "prompt"
    bar.group_button("motion").invoke()
    _pump(window)
    assert _current(window) == "movie_clips"


def test_real_mouse_events_select_a_destination(build) -> None:
    window = build().window
    root = window.root
    root.deiconify()
    root.update()
    bar = window.task_navigation
    bar.group_button("edit").invoke()
    root.update()
    button = bar.destination_button("photo_optimize")
    for sequence in ("<Enter>", "<ButtonPress-1>", "<ButtonRelease-1>"):
        button.event_generate(sequence, x=4, y=4)
        root.update()
    assert _current(window) == "photo_optimize"


def test_keyboard_space_and_arrows_move_through_the_navigation(build) -> None:
    window = build().window
    root = window.root
    root.deiconify()
    root.update()
    bar = window.task_navigation
    assert bar.group_button("create").winfo_ismapped()
    bar.group_button("create").focus_force()
    root.update()
    focused = root.focus_get()
    if focused is not bar.group_button("create"):
        pytest.skip("the window system did not grant keyboard focus to the test window")
    focused.event_generate("<Right>")
    root.update()
    assert _current(window) == nav.default_tab_for_group("edit")
    assert root.focus_get() is bar.group_button("edit")
    root.focus_get().event_generate("<Left>")
    root.update()
    assert bar.active_group_id == "create"
    # wrapping at the ends
    bar.group_button("advanced").invoke()
    bar.group_button("advanced").focus_force()
    root.update()
    bar.group_button("advanced").event_generate("<Right>")
    root.update()
    assert bar.active_group_id == "create"


def test_native_keyboard_tab_cycling_still_works_and_updates_the_highlight(build) -> None:
    window = build().window
    root = window.root
    assert root.bind("<Control-Key-Tab>") or root.tk.call("bind", str(root), "<Control-Key-Tab>")
    window.select_tab("prompt")
    _pump(window)
    expected = [nav.LEGACY_TAB_ORDER[1], nav.LEGACY_TAB_ORDER[2]]
    for tab_id in expected:
        root.tk.call("ttk::notebook::CycleTab", str(window.center_notebook), 1)
        _pump(window)
        assert _current(window) == tab_id
        assert window.task_navigation.selected_tab_id == tab_id
    # every tab, including the HOLD one, is reachable by cycling alone
    seen = {_current(window)}
    for _ in range(9):
        root.tk.call("ttk::notebook::CycleTab", str(window.center_notebook), 1)
        _pump(window)
        seen.add(_current(window))
    assert seen == set(TAB_ATTRIBUTES)


def test_navigation_buttons_are_all_focusable_in_tab_order(build) -> None:
    window = build().window
    bar = window.task_navigation
    for button in (*bar._group_buttons.values(), *bar._destination_buttons.values()):  # noqa: SLF001
        assert str(button.cget("takefocus")) in ("", "1", "ttk::takefocus")
        assert str(button.cget("state")) != "disabled" or button.instate(["disabled"])


# ------------------------------------------------------------------------- programmatic selection and no cycles


def test_programmatic_notebook_selection_updates_the_highlight_without_calling_back(build) -> None:
    window = build().window
    bar = window.task_navigation
    calls: list[str] = []
    real = bar._on_select  # noqa: SLF001
    bar._on_select = lambda tab_id: (calls.append(tab_id), real(tab_id))  # noqa: SLF001
    for tab_id in ("review", "video_workflow", "learning", "character_training", "pipeline"):
        window.center_notebook.select(window.get_tab(tab_id))
        _pump(window)
        assert bar.selected_tab_id == tab_id
        assert bar.active_group_id == nav.group_for_tab(tab_id).group_id
        assert bar._destination_var.get() == tab_id  # noqa: SLF001
    assert calls == []


def test_selecting_through_the_bar_selects_once_and_does_not_loop(build) -> None:
    window = build().window
    bar = window.task_navigation
    selections: list[str] = []
    window.center_notebook.bind(
        "<<NotebookTabChanged>>", lambda _e: selections.append(_current(window)), add="+"
    )
    bar.group_button("motion").invoke()
    _pump(window)
    assert selections == ["video_workflow"]


def test_inner_notebook_events_do_not_move_the_navigation(build) -> None:
    window = build().window
    window.select_tab("learning")
    _pump(window)
    window.learning_tab._mode_notebook.event_generate("<<NotebookTabChanged>>")  # noqa: SLF001
    _pump(window)
    assert window.task_navigation.selected_tab_id == "learning"


def test_navigation_never_submits_work(build) -> None:
    harness = build()
    window = harness.window
    bar = window.task_navigation
    with patch("src.controller.job_service.JobService.submit_njrs") as submit:
        for group in nav.TASK_GROUPS:
            bar.group_button(group.group_id).invoke()
            for tab_id in group.tab_ids:
                bar.destination_button(tab_id).invoke()
        _pump(window)
    submit.assert_not_called()
    assert harness.pipeline_runner.run_calls == []


# -------------------------------------------------------------------------------------- cross-workflow handoffs


def _history_entry(job_id: str, image: str) -> JobHistoryEntry:
    return JobHistoryEntry(
        job_id=job_id,
        created_at="2025-01-01T12:00:00",
        status=JobStatus.COMPLETED,
        payload_summary="PackA",
        completed_at="2025-01-01T12:00:00",
        result={
            "artifact": {
                "schema": "stablenew.artifact.v2.6",
                "artifact_type": "image",
                "primary_path": image,
                "output_paths": [image],
            }
        },
    )


def test_pipeline_to_review_to_video_workflow_make_video(build, tmp_path) -> None:
    harness = build()
    window = harness.window
    paths = [
        make_image(tmp_path / f"img_{i}.png", color=c)
        for i, c in enumerate(("red", "green", "blue"))
    ]
    window.video_workflow_tab.workflow_var.set(
        ANIMATE2_ID
    )  # experimental choice must be replaced by the approved one
    with patch("src.controller.job_service.JobService.submit_njrs") as submit:
        window.select_tab("pipeline")
        _pump(window)
        assert route_images_to_review(main_window=window, image_paths=paths) == paths
        _pump(window)
        assert _current(window) == "review"
        assert window.task_navigation.active_group_id == "edit"

        review = window.review_tab
        review.images_list.selection_clear(0, "end")
        review.images_list.selection_set(1)
        review._on_send_selected_to_video_workflow()  # noqa: SLF001 - the Review "Make Video" button command
        _pump(window)
    assert _current(window) == "video_workflow"
    assert window.task_navigation.active_group_id == "motion"
    assert window.video_workflow_tab.source_image_var.get() == paths[1]
    assert window.video_workflow_tab.workflow_var.get() == TI2V_ID
    submit.assert_not_called()


def test_history_make_video_opens_the_video_workflow_tab(build, tmp_path) -> None:
    harness = build()
    window = harness.window
    image = make_image(tmp_path / "from_history.png")
    harness.controller.app_state.history_items = [_history_entry("job-h", image)]
    window.select_tab("pipeline")
    _pump(window)
    with patch("src.controller.job_service.JobService.submit_njrs") as submit:
        assert harness.controller.send_history_job_image_to_video_workflow("job-h") == image
        _pump(window)
    assert _current(window) == "video_workflow"
    assert window.video_workflow_tab.source_image_var.get() == image
    assert window.video_workflow_tab.workflow_var.get() == TI2V_ID
    submit.assert_not_called()


def test_video_workflow_to_movie_clips_and_the_queue_view_return_to_pipeline(
    build, tmp_path
) -> None:
    window = build().window
    clip = str(tmp_path / "clip.mp4")
    Path(clip).write_bytes(b"x")
    window.select_tab("video_workflow")
    _pump(window)
    route_bundle_to_movie_clips(
        main_window=window,
        bundle={"primary_path": clip, "output_paths": [clip]},
        status_message="movie",
    )
    _pump(window)
    assert _current(window) == "movie_clips"
    assert window.task_navigation.selected_tab_id == "movie_clips"
    assert window.task_navigation.active_group_id == "motion"
    assert show_queue_view(window) is True
    _pump(window)
    assert _current(window) == "pipeline"
    assert window.task_navigation.active_group_id == "create"


def test_send_to_svd_and_direct_image_routing_follow_the_highlight(build, tmp_path) -> None:
    harness = build()
    window = harness.window
    image = make_image(tmp_path / "svd.png")
    harness.controller.send_image_to_svd(image)
    _pump(window)
    assert _current(window) == "svd"
    assert window.task_navigation.selected_tab_id == "svd"
    route_image_to_video_workflow(main_window=window, image_path=image)
    _pump(window)
    assert _current(window) == "video_workflow"


def test_learning_navigation_preserves_the_learning_draft_state(build) -> None:
    window = build().window
    bar = window.task_navigation
    bar.group_button("learn").invoke()
    _pump(window)
    assert _current(window) == "learning"
    before = window.learning_tab.get_learning_session_state()
    for group_id in ("create", "motion", "advanced", "edit"):
        bar.group_button(group_id).invoke()
        _pump(window)
    bar.group_button("learn").invoke()
    _pump(window)
    assert window.learning_tab.get_learning_session_state() == before
    assert (
        window.get_tab("learning") is window.learning_tab
    )  # the same instance, never rebuilt or reparented


def test_character_training_is_visibly_on_hold_and_navigation_runs_nothing(build) -> None:
    harness = build()
    window = harness.window
    with patch.object(
        type(harness.controller), "submit_character_training_job", create=True
    ) as submit:
        window.task_navigation.group_button("advanced").invoke()
        _pump(window)
    assert _current(window) == "character_training"
    assert (
        window.task_navigation.destination_button("character_training")
        .cget("text")
        .endswith("(HOLD)")
    )
    submit.assert_not_called()


# -------------------------------------------------------------------------------------------- persistence


def test_the_selected_tab_is_saved_by_id_and_restored_by_id(build, tk_root) -> None:
    first = build()
    first.window.select_tab("movie_clips")
    _pump(first.window)
    first.window._save_ui_state()  # noqa: SLF001
    saved = get_ui_state_store().load_state()
    assert saved["tabs"]["selected_tab_id"] == "movie_clips"
    assert saved["tabs"]["selected_index"] == nav.LEGACY_TAB_ORDER.index("movie_clips")
    first.window._disposed = True  # noqa: SLF001 - keep cleanup from re-saving a different tab
    second = build()
    assert _current(second.window) == "movie_clips"
    assert second.window.task_navigation.selected_tab_id == "movie_clips"


@pytest.mark.parametrize(
    ("tabs_state", "expected"),
    [
        ({"selected_index": 2}, "learning"),  # historic index-only state upgrades
        ({"selected_index": 8}, "video_workflow"),
        (
            {"selected_tab_id": "review", "selected_index": 0},
            "review",
        ),  # id beats an obsolete index
        ({"selected_tab_id": "not_a_tab", "selected_index": 3}, "pipeline"),
        ({"selected_index": 42}, "pipeline"),
        ({"selected_index": "x"}, "pipeline"),
        ("corrupt", "pipeline"),
        (None, "pipeline"),
    ],
)
def test_startup_restore_from_stored_tabs_state(build, tabs_state, expected) -> None:
    window = build({"tabs": tabs_state}).window
    assert _current(window) == expected
    assert window.task_navigation.selected_tab_id == expected


def test_a_missing_state_file_starts_on_pipeline(build) -> None:
    window = build().window
    assert _current(window) == "pipeline"


def test_saving_keeps_every_workspace_payload_and_unrelated_ui_keys(build) -> None:
    stored = {
        "window": {"geometry": "1300x800+10+10", "state": "normal"},
        "content_visibility": {"mode": "sfw"},
        "operator_readiness": {"intro_dismissed": True},
        "learning": {"enabled": True, "session": {"current_experiment": {"name": "Draft"}}},
        "photo_optimize": {"selected_asset_id": "photo_1"},
        "movie_clips": {"keep": "clips"},
        "svd": {"keep": "svd"},
        "video_workflow": {"keep": "video"},
        "future_section": {"keep": True},
        "tabs": {"selected_index": 1, "future_tabs_key": 7},
    }
    window = build(stored).window
    window._save_ui_state()  # noqa: SLF001
    saved = get_ui_state_store().load_state()
    for key in ("operator_readiness", "future_section"):
        assert saved[key] == stored[key]
    assert saved["tabs"]["future_tabs_key"] == 7
    assert saved["tabs"]["selected_tab_id"] == "pipeline"
    assert saved["content_visibility"]["mode"] in {"sfw", "nsfw"}
    assert saved["window"]["state"] in {"normal", "zoomed"}
    # each workspace tab still owns and writes its own payload (a missing getter result keeps the stored one)
    for key in ("learning", "photo_optimize", "movie_clips", "svd", "video_workflow"):
        assert isinstance(saved[key], dict) and saved[key]


# ------------------------------------------------------------------------------------------- failure handling


def test_a_tab_that_fails_to_be_added_is_not_registered_and_is_visibly_unavailable(
    tk_root, monkeypatch
) -> None:
    real_add = ttk.Notebook.add

    def add(self, child, **kwargs):
        if isinstance(child, ReviewTabFrame):
            raise tk.TclError("cannot add review")
        return real_add(self, child, **kwargs)

    monkeypatch.setattr(ttk.Notebook, "add", add)
    assert get_ui_state_store().save_state({"tabs": {"selected_tab_id": "review"}})
    harness = GuiV2Harness(tk_root)
    try:
        window = harness.window
        assert window.get_tab("review") is None
        assert "review" not in window._tab_registry  # noqa: SLF001
        assert "cannot add review" in window.tab_failures()["review"]
        assert window.review_tab is not None  # the legacy attribute is still set
        assert len(window.center_notebook.tabs()) == 8
        bar = window.task_navigation
        assert bar.destination_button("review").instate(["disabled"])
        assert not bar.destination_button("pipeline").instate(["disabled"])
        # the stored (unavailable) tab falls back to Pipeline instead of an arbitrary index
        assert _current(window) == "pipeline"
        assert window.select_tab("review") is False
    finally:
        harness.cleanup()


def test_a_tab_whose_constructor_fails_shows_a_placeholder_and_is_recorded(
    tk_root, monkeypatch
) -> None:
    def explode(*_args, **_kwargs):
        raise RuntimeError("svd constructor exploded")

    monkeypatch.setattr("src.gui.main_window_v2.SVDTabFrameV2", explode)
    harness = GuiV2Harness(tk_root)
    try:
        window = harness.window
        assert "svd constructor exploded" in window.tab_failures()["svd"]
        assert window.get_tab("svd") is not None  # the placeholder really is in the notebook
        assert str(window.get_tab("svd")) in [str(w) for w in window.center_notebook.tabs()]
        assert window.select_tab("svd") is True
        _pump(window)
        assert window.task_navigation.selected_tab_id == "svd"
    finally:
        harness.cleanup()


# ------------------------------------------------------------------------------------------------ layout


@pytest.mark.parametrize("scaling", [1.3333, 2.0])  # Windows 100% and 150% display scaling
def test_the_bar_fits_the_smallest_supported_window_at_100_and_150_percent(
    tk_root, scaling
) -> None:
    from src.gui.view_contracts.window_layout_contract import PREFERRED_MIN_WIDTH

    apply_theme(tk_root)
    # On X11 the scaling lives in the shared Screen record, so it would leak into every later Tk root in this process.
    original_scaling = float(tk_root.tk.call("tk", "scaling"))
    tk_root.tk.call("tk", "scaling", scaling)
    try:
        parent = ttk.Frame(tk_root)
        bar = TaskNavigationBar(parent, on_select=lambda _t: None, is_available=lambda _t: True)
        bar.pack(fill="x")
        widest = 0
        for group in nav.TASK_GROUPS:
            bar.show_selected(group.tab_ids[0])
            tk_root.update_idletasks()
            widest = max(widest, bar.winfo_reqwidth())
        assert widest < PREFERRED_MIN_WIDTH, f"navigation needs {widest}px at scaling {scaling}"
        assert bar.winfo_reqheight() < 80
    finally:
        tk_root.tk.call("tk", "scaling", original_scaling)


def test_the_window_is_not_taller_than_before_the_native_strip_was_hidden(build) -> None:
    window = build().window
    window.root.update_idletasks()
    assert window.task_navigation.winfo_reqheight() < 80
