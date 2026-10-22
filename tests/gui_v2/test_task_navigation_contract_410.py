"""PR-GUI-410: the pure task-navigation contract (no Tk, no controllers)."""

from __future__ import annotations

import inspect

import pytest

from src.gui.view_contracts import task_navigation_contract as nav

NINE_TAB_IDS = {
    "prompt",
    "pipeline",
    "learning",
    "review",
    "photo_optimize",
    "movie_clips",
    "character_training",
    "svd",
    "video_workflow",
}


def test_every_tab_id_appears_in_exactly_one_group_exactly_once() -> None:
    listed = [tab_id for group in nav.TASK_GROUPS for tab_id in group.tab_ids]
    assert sorted(listed) == sorted(NINE_TAB_IDS)
    assert len(listed) == len(set(listed)) == 9
    assert set(nav.all_tab_ids()) == NINE_TAB_IDS


def test_groups_and_destinations_keep_their_stable_ids_and_order() -> None:
    assert nav.group_ids() == ("create", "edit", "motion", "learn", "advanced")
    assert [(group.group_id, group.tab_ids) for group in nav.TASK_GROUPS] == [
        ("create", ("prompt", "pipeline")),
        ("edit", ("review", "photo_optimize")),
        ("motion", ("video_workflow", "svd", "movie_clips")),
        ("learn", ("learning",)),
        ("advanced", ("character_training",)),
    ]
    assert [group.label for group in nav.TASK_GROUPS] == [
        "Create",
        "Edit",
        "Motion",
        "Learn",
        "Advanced",
    ]
    for group in nav.TASK_GROUPS:
        for destination in group.destinations:
            assert destination.group_id == group.group_id
            assert nav.group_for_tab(destination.tab_id) is group


def test_there_is_no_history_destination_and_job_history_stays_in_pipeline() -> None:
    assert nav.get_destination("history") is None
    assert nav.get_destination("job_history") is None
    assert nav.group_for_tab("pipeline").group_id == "create"  # type: ignore[union-attr]


def test_only_character_training_is_on_hold_and_says_so() -> None:
    held = [d for g in nav.TASK_GROUPS for d in g.destinations if d.hold]
    assert [d.tab_id for d in held] == ["character_training"]
    assert held[0].display_label == "Character Training (HOLD)"
    assert "hold" in held[0].hold_reason.lower()
    assert nav.get_destination("pipeline").display_label == "Pipeline"  # type: ignore[union-attr]


def test_visible_names_are_spelled_correctly() -> None:
    labels = {d.tab_id: d.label for g in nav.TASK_GROUPS for d in g.destinations}
    assert labels["photo_optimize"] == "Photo Optimize"
    assert "Optomize" not in " ".join(labels.values())


def test_the_legacy_order_is_the_nine_ids_and_matches_historic_indices() -> None:
    assert set(nav.LEGACY_TAB_ORDER) == NINE_TAB_IDS
    assert len(nav.LEGACY_TAB_ORDER) == 9
    assert nav.legacy_tab_id_for_index(0) == "prompt"
    assert nav.legacy_tab_id_for_index(1) == "pipeline"
    assert nav.legacy_tab_id_for_index(8) == "video_workflow"
    for bad in (-1, 9, 100, None, "1", 1.0, True, [], {}):
        assert nav.legacy_tab_id_for_index(bad) is None


def test_default_tab_is_pipeline_and_belongs_to_the_navigation() -> None:
    assert nav.DEFAULT_TAB_ID == "pipeline"
    assert nav.DEFAULT_TAB_ID in nav.all_tab_ids()


def test_default_tab_for_group_picks_the_first_available_destination() -> None:
    assert nav.default_tab_for_group("motion") == "video_workflow"
    assert nav.default_tab_for_group("motion", {"svd", "movie_clips"}) == "svd"
    assert nav.default_tab_for_group("motion", set()) is None
    assert nav.default_tab_for_group("nonsense") is None


ALL = set(NINE_TAB_IDS)


@pytest.mark.parametrize(
    ("stored", "available", "expected"),
    [
        ({"selected_tab_id": "review"}, ALL, "review"),
        (
            {"selected_tab_id": "video_workflow", "selected_index": 0},
            ALL,
            "video_workflow",
        ),  # id beats an obsolete index
        ({"selected_index": 2}, ALL, "learning"),  # one-time read of the historic index
        ({"selected_index": 8}, ALL, "video_workflow"),
        ({"selected_index": 7}, ALL, "svd"),
        (
            {"selected_tab_id": "nonsense", "selected_index": 3},
            ALL,
            "pipeline",
        ),  # a stored id is the authority
        ({"selected_tab_id": "review"}, ALL - {"review"}, "pipeline"),  # failed/hidden tab
        ({"selected_index": 3}, ALL - {"review"}, "pipeline"),
        (
            {"selected_tab_id": "review"},
            {"prompt", "learning"},
            "prompt",
        ),  # no Pipeline either: first in nav order
        ({"selected_index": 99}, ALL, "pipeline"),
        ({"selected_index": -4}, ALL, "pipeline"),
        ({"selected_index": "2"}, ALL, "pipeline"),
        ({"selected_tab_id": 7}, ALL, "pipeline"),
        ({"selected_tab_id": ["review"]}, ALL, "pipeline"),
        ({}, ALL, "pipeline"),
        (None, ALL, "pipeline"),
        ("corrupt", ALL, "pipeline"),
        ([1, 2], ALL, "pipeline"),
    ],
)
def test_startup_tab_resolution(stored, available, expected) -> None:
    assert nav.resolve_startup_tab_id(stored, available) == expected


def test_startup_tab_resolution_is_empty_only_when_nothing_is_available() -> None:
    assert nav.resolve_startup_tab_id({"selected_tab_id": "review"}, set()) == ""
    assert nav.resolve_startup_tab_id({}, {"not_a_nav_tab"}) == ""


def test_merge_tabs_state_writes_the_id_and_keeps_unrelated_keys() -> None:
    merged = nav.merge_tabs_state(
        {"selected_index": 1, "future_key": {"a": 1}}, selected_tab_id="review", selected_index=3
    )
    assert merged == {"selected_index": 3, "selected_tab_id": "review", "future_key": {"a": 1}}


def test_merge_tabs_state_keeps_the_stored_id_when_the_current_tab_is_unresolved() -> None:
    merged = nav.merge_tabs_state(
        {"selected_tab_id": "learning", "selected_index": 2}, selected_tab_id=None, selected_index=0
    )
    assert merged["selected_tab_id"] == "learning"
    unknown = nav.merge_tabs_state(None, selected_tab_id="bogus", selected_index=None)
    assert unknown == {}
    assert nav.merge_tabs_state("junk", selected_tab_id="pipeline", selected_index=1) == {
        "selected_tab_id": "pipeline",
        "selected_index": 1,
    }


def test_the_contract_module_is_toolkit_independent() -> None:
    source = inspect.getsource(nav)
    assert "tkinter" not in source
    assert "ttk" not in source
