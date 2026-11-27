"""N6: the Tk-free workspace-mode contract (Simple by default; Advanced shows everything that exists today)."""

from __future__ import annotations

import pytest

from src.gui.view_contracts import task_navigation_contract as nav
from src.gui.view_contracts import workspace_mode_contract as mode

TODAY_TABS = (
    "prompt",
    "pipeline",
    "review",
    "photo_optimize",
    "video_workflow",
    "storyboard",
    "svd",
    "movie_clips",
    "learning",
    "character_training",
)


def test_simple_is_the_default_and_unknown_values_fall_back_to_it() -> None:
    assert mode.DEFAULT_WORKSPACE_MODE == mode.WORKSPACE_SIMPLE
    assert mode.normalize_workspace_mode("advanced") == mode.WORKSPACE_ADVANCED
    for value in (None, "", "expert", 3, {"mode": "advanced"}):
        assert mode.normalize_workspace_mode(value) == mode.WORKSPACE_SIMPLE


def test_the_mode_is_read_from_and_merged_into_the_ui_state_payload() -> None:
    assert mode.workspace_mode_from_state(None) == mode.WORKSPACE_SIMPLE
    assert mode.workspace_mode_from_state({"workspace": "advanced"}) == mode.WORKSPACE_SIMPLE
    assert mode.workspace_mode_from_state({"workspace": {"mode": "advanced"}}) == "advanced"
    merged = mode.workspace_state_payload({"mode": "simple", "other": 1}, "advanced")
    assert merged == {"mode": "advanced", "other": 1}
    assert mode.workspace_state_payload(None, "bogus") == {"mode": "simple"}


def test_simple_navigation_is_generate_review_video_storyboard_and_learning() -> None:
    assert nav.visible_tab_ids(mode.WORKSPACE_SIMPLE) == (
        "generate",
        "review",
        "video_workflow",
        "storyboard",
        "learning",
    )
    assert mode.SIMPLE_DEFAULT_TAB_ID == "generate"
    groups = nav.visible_group_ids(mode.WORKSPACE_SIMPLE)
    assert groups == ("create", "edit", "motion", "learn")  # the Advanced (HOLD) group is not shown


def test_advanced_shows_every_tab_that_exists_today_in_today_order_plus_generate_first() -> None:
    advanced = nav.visible_tab_ids(mode.WORKSPACE_ADVANCED)
    assert advanced == ("generate", *TODAY_TABS)
    assert nav.visible_group_ids(mode.WORKSPACE_ADVANCED) == nav.group_ids()
    assert nav.all_tab_ids() == advanced
    # Labels and HOLD marking are today's.
    assert nav.get_destination("character_training").display_label == "Character Training (HOLD)"
    assert nav.get_destination("svd").label == "SVD Img2Vid"


def test_hidden_tabs_are_still_destinations_and_stay_selectable() -> None:
    hidden = set(nav.all_tab_ids()) - set(nav.visible_tab_ids(mode.WORKSPACE_SIMPLE))
    assert hidden == {
        "prompt",
        "pipeline",
        "photo_optimize",
        "svd",
        "movie_clips",
        "character_training",
    }
    for tab_id in hidden:
        assert nav.get_destination(tab_id) is not None


def test_the_historic_notebook_order_is_unchanged_and_generate_is_appended() -> None:
    # Like Storyboard before it, Generate is appended, so historic saved indices 0-9 keep their meaning.
    assert nav.LEGACY_TAB_ORDER == (
        "prompt",
        "pipeline",
        "learning",
        "review",
        "photo_optimize",
        "movie_clips",
        "character_training",
        "svd",
        "video_workflow",
        "storyboard",
        "generate",
    )
    assert nav.legacy_tab_id_for_index(10) == "generate"


@pytest.mark.parametrize(
    ("stored", "workspace", "expected"),
    [
        ({"selected_tab_id": "review"}, "simple", "review"),
        ({"selected_tab_id": "pipeline"}, "simple", "generate"),  # hidden in Simple: Generate
        ({"selected_tab_id": "pipeline"}, "advanced", "pipeline"),
        ({}, "simple", "generate"),
        ({}, "advanced", "pipeline"),  # today's default
        ({"selected_index": 3}, "simple", "review"),  # historic index, visible in Simple
        ({"selected_index": 1}, "simple", "generate"),  # historic index to a hidden tab
    ],
)
def test_startup_picks_a_tab_visible_in_the_mode(stored, workspace, expected) -> None:
    available = set(nav.LEGACY_TAB_ORDER)
    assert nav.resolve_startup_tab_id(stored, available, mode=workspace) == expected


def test_startup_without_a_mode_keeps_todays_behaviour() -> None:
    available = set(nav.LEGACY_TAB_ORDER)
    assert nav.resolve_startup_tab_id({}, available) == "pipeline"
    assert nav.resolve_startup_tab_id({"selected_tab_id": "svd"}, available) == "svd"


def test_learning_simple_presentation_hides_the_zero_use_studies_and_discovered_view() -> None:
    assert mode.SIMPLE_HIDDEN_STUDY_SLUGS == (
        "prompt_slot",
        "embedding_experiment",
        "two_axis_grid",
        "prompt_model_matrix",
    )
    from src.learning import study_catalog

    for slug in mode.SIMPLE_HIDDEN_STUDY_SLUGS:
        assert study_catalog.lookup(slug) is not None  # hidden, never removed from the catalog
    assert mode.hidden_study_slugs(mode.WORKSPACE_ADVANCED) == ()
    assert mode.hidden_study_slugs(mode.WORKSPACE_SIMPLE) == mode.SIMPLE_HIDDEN_STUDY_SLUGS
    assert mode.shows_discovered_outputs(mode.WORKSPACE_ADVANCED) is True
    assert mode.shows_discovered_outputs(mode.WORKSPACE_SIMPLE) is False
