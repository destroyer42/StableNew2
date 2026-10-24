"""PR-GUI-UX-560: Matrix editor guidance, counts and examples (projection and Tk panel)."""

from __future__ import annotations

import copy
import random
import time
from unittest.mock import Mock

import pytest

from src.gui.models.prompt_pack_model import MatrixConfig, MatrixSlot
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.widgets.matrix_tab_panel import MatrixTabPanel
from src.gui_v2.matrix_editor_view import (
    PREVIEW_AUTHORITY_NOTE,
    STARTER_DIMENSIONS,
    UNSEEDED_RANDOM_NOTICE,
    build_matrix_editor_view,
    parse_seed_entry,
)
from tests.gui_v2.tk_test_utils import get_shared_tk_root

PROMPT = "A [[outfit]] by the [[location]] in [[lighting]]"


def _config(**overrides) -> MatrixConfig:
    base = {
        "enabled": True,
        "mode": "fanout",
        "limit": 8,
        "slots": [
            MatrixSlot("outfit", ["a", "b", "c"]),
            MatrixSlot("location", ["w", "x", "y", "z"]),
            MatrixSlot("lighting", ["d", "n"]),
        ],
    }
    return MatrixConfig(**{**base, **overrides})


def _text(view) -> str:
    return "\n".join((*view.count_lines, *view.multiplicity_lines, *view.warnings))


# ---- projection (no Tk) -------------------------------------------------------------------------------------


def test_view_reports_theoretical_effective_selected_and_excluded_counts() -> None:
    view = build_matrix_editor_view(_config(), PROMPT)

    assert "Dimensions: 3 (outfit 3, location 4, lighting 2)." in view.count_lines
    assert "Possible combinations: 24." in view.count_lines
    assert "Limit in effect: 8 (from this Matrix limit)." in view.count_lines
    assert "Compiled per prompt row: 8 of 24." in view.count_lines
    assert any(
        "Not selected: 16" in line and "will not be queued" in line for line in view.count_lines
    )
    assert PREVIEW_AUTHORITY_NOTE in _text(view)


def test_view_does_not_claim_exclusions_when_everything_is_selected() -> None:
    view = build_matrix_editor_view(_config(limit=50), PROMPT)

    assert "Compiled per prompt row: 24 of 24." in view.count_lines
    assert not any("Not selected" in line for line in view.count_lines)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(0, "built-in default"), (-2, "built-in default"), (5, "this Matrix limit")],
)
def test_view_names_where_the_limit_in_effect_came_from(stored, expected) -> None:
    view = build_matrix_editor_view(_config(limit=stored), PROMPT)

    assert any(expected in line for line in view.count_lines if line.startswith("Limit in effect"))


def test_view_reads_a_malformed_stored_limit_as_the_compiler_does_and_warns() -> None:
    loaded = MatrixConfig.from_mapping(
        {"enabled": True, "limit": "abc", "slots": [{"name": "outfit", "values": ["a", "b"]}]}
    )
    view = build_matrix_editor_view(loaded, "[[outfit]]", randomizer_limit=3)

    assert any("randomizer" in line and "Limit in effect: 3" in line for line in view.count_lines)
    assert any("does not mean 'unlimited'" in warning for warning in view.warnings)


def test_view_uses_the_randomizer_hint_only_when_the_matrix_limit_is_unusable() -> None:
    assert "Limit in effect: 6" in "\n".join(
        build_matrix_editor_view(_config(limit=6), PROMPT, randomizer_limit=2).count_lines
    )
    assert "Limit in effect: 2" in "\n".join(
        build_matrix_editor_view(_config(limit=0), PROMPT, randomizer_limit=2).count_lines
    )


def test_mode_wording_is_truthful_about_sequential_and_keeps_identities() -> None:
    fanout = build_matrix_editor_view(_config(mode="fanout"), PROMPT)
    sequential = build_matrix_editor_view(_config(mode="sequential"), PROMPT)
    random_view = build_matrix_editor_view(_config(mode="random"), PROMPT)
    unknown = build_matrix_editor_view(_config(mode="grid"), PROMPT)

    assert fanout.mode_title == "All combinations (fanout)"
    assert sequential.mode_title == "Sequential (legacy)"
    assert "exactly like fanout" in sequential.mode_help
    assert "does not control the order jobs run in the queue" in sequential.mode_help
    assert random_view.mode_title == "Random sample"
    assert "like fanout" in unknown.mode_help
    assert sequential.plan.mode == "sequential"  # never relabeled


def test_the_seed_control_is_relevant_only_for_random_and_is_not_confused_with_image_seeds() -> (
    None
):
    assert build_matrix_editor_view(_config(mode="fanout"), PROMPT).show_seed is False
    random_view = build_matrix_editor_view(_config(mode="random"), PROMPT)

    assert random_view.show_seed is True
    assert "image seed" in random_view.seed_help and "randomizer seed" in random_view.seed_help


def test_unseeded_random_examples_are_labeled_not_frozen_and_guidance_is_shown() -> None:
    view = build_matrix_editor_view(_config(mode="random", limit=4), PROMPT, rng=random.Random(1))

    assert view.exact_examples is False
    assert view.examples_heading == "Illustrative examples (not frozen)"
    assert UNSEEDED_RANDOM_NOTICE in view.warnings
    assert "may pick different combinations" in view.examples_footer
    assert len(view.example_rows) == 4


def test_seeded_random_examples_are_the_exact_selection() -> None:
    config = _config(mode="random", limit=4, sample_seed=31)
    view = build_matrix_editor_view(config, PROMPT)
    again = build_matrix_editor_view(config, PROMPT, rng=random.Random(99))
    plan = view.plan

    assert view.exact_examples is True
    assert "sample seed 31" in view.examples_heading
    assert view.example_rows == again.example_rows
    assert len(view.example_rows) == plan.selected_count == 4
    assert UNSEEDED_RANDOM_NOTICE not in view.warnings


def test_ordered_examples_are_the_first_combinations_in_compile_order() -> None:
    view = build_matrix_editor_view(_config(limit=3), PROMPT)

    assert view.examples_heading == "First combinations, in compile order"
    assert view.example_rows == (
        "1. A a by the w in d",
        "2. A a by the w in n",
        "3. A a by the x in d",
    )


def test_examples_are_bounded_and_say_how_many_more_are_selected() -> None:
    view = build_matrix_editor_view(_config(limit=24), PROMPT, max_example_rows=5)

    assert len(view.example_rows) == 5
    assert "19 more selected" in view.examples_footer


def test_unresolved_tokens_are_reported_not_removed() -> None:
    view = build_matrix_editor_view(_config(), "[[outfit]] with [[mood]] at [[Location]]")

    assert any(
        "[[mood]]" in warning and "stays in the prompt text" in warning for warning in view.warnings
    )
    assert not any("[[Location]]" in warning for warning in view.warnings)  # alias resolves
    assert all("[[mood]]" in row for row in view.example_rows)


def test_a_disabled_matrix_still_shows_counts_but_says_nothing_is_expanded() -> None:
    view = build_matrix_editor_view(_config(enabled=False), PROMPT)

    assert "Possible combinations: 24." in view.count_lines
    assert any("Matrix is off" in line for line in view.count_lines)


def test_an_empty_matrix_explains_what_to_add() -> None:
    view = build_matrix_editor_view(MatrixConfig(enabled=True), PROMPT)

    assert view.count_lines[0].startswith("No dimensions yet")
    assert view.example_rows == ()


def test_batch_factors_are_an_estimate_and_images_are_not_jobs() -> None:
    view = build_matrix_editor_view(_config(limit=8), PROMPT, batch_runs=2, images_per_prompt=3)
    text = "\n".join(view.multiplicity_lines)

    assert "about 16 jobs and 48 images per prompt row (estimate)" in text
    assert "Preview shows the jobs that were actually compiled" in text


def test_a_huge_theoretical_count_is_computed_without_enumerating_and_stays_fast() -> None:
    config = MatrixConfig(
        enabled=True,
        mode="random",
        limit=5,
        slots=[MatrixSlot(f"d{i}", [str(v) for v in range(10)]) for i in range(40)],
    )
    started = time.perf_counter()
    view = build_matrix_editor_view(config, "[[d0]] [[d39]]", rng=random.Random(2))

    assert f"Possible combinations: {10**40:,}." in view.count_lines
    assert time.perf_counter() - started < 2.0
    assert len(view.example_rows) == 5


def test_projection_never_mutates_the_configuration() -> None:
    config = _config(mode="random", sample_seed=4)
    before = copy.deepcopy(config)
    build_matrix_editor_view(config, PROMPT)

    assert config == before


@pytest.mark.parametrize(
    ("typed", "seed", "has_error"),
    [
        ("", None, False),
        ("  ", None, False),
        ("42", 42, False),
        ("0", 0, False),
        ("4294967295", 4294967295, False),
        ("4294967296", None, True),
        ("-1", None, True),
        ("1.5", None, True),
        ("abc", None, True),
        ("٣", None, True),
    ],
)
def test_seed_entry_parsing(typed, seed, has_error) -> None:
    parsed, error = parse_seed_entry(typed)

    assert parsed == seed
    assert bool(error) is has_error


def test_starter_examples_cover_the_documented_themes() -> None:
    assert {item.name for item in STARTER_DIMENSIONS} >= {
        "character",
        "outfit",
        "location",
        "lighting",
        "framing",
    }


# ---- Tk panel -----------------------------------------------------------------------------------------------


@pytest.fixture
def panel_env():
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk unavailable")
    workspace = PromptWorkspaceState()
    pack = workspace.new_pack("Matrix 560")
    pack.get_slot(0).text = PROMPT
    pack.matrix = _config()
    changes = Mock()
    panel = MatrixTabPanel(root, workspace, on_matrix_changed=changes)
    panel.refresh()
    yield panel, workspace, changes
    panel.destroy()


def test_loading_refreshing_and_showing_examples_never_marks_the_pack_dirty(panel_env) -> None:
    panel, _workspace, changes = panel_env

    panel.refresh()
    panel._update_preview()  # noqa: SLF001

    changes.assert_not_called()
    assert "Possible combinations: 24." in panel.summary_var.get()
    assert panel.preview_heading_var.get() == "First combinations, in compile order"


def test_count_summary_and_truncation_warning_follow_edits(panel_env) -> None:
    panel, workspace, changes = panel_env
    panel.limit_spin.delete(0, "end")
    panel.limit_spin.insert(0, "5")
    panel._on_limit_typed()  # noqa: SLF001

    assert workspace.get_matrix_config().limit == 5
    assert "Compiled per prompt row: 5 of 24." in panel.summary_var.get()
    assert "Not selected: 19" in panel.summary_var.get()
    changes.assert_called_once()


def test_an_unchanged_key_release_is_not_an_edit(panel_env) -> None:
    panel, _workspace, changes = panel_env
    panel._on_slot_changed(0)  # noqa: SLF001
    panel._on_slot_changed(1)  # noqa: SLF001
    panel._on_limit_typed()  # noqa: SLF001
    panel._on_seed_typed()  # noqa: SLF001
    for widget, sequence in (
        (panel.limit_spin, "<KeyRelease>"),
        (panel.seed_entry, "<KeyRelease>"),
        (panel.slot_widgets[0][0], "<KeyRelease>"),
    ):
        assert widget.bind(sequence), f"{sequence} is not bound"

    changes.assert_not_called()


def test_an_invalid_typed_limit_changes_nothing_and_a_malformed_stored_one_is_kept(
    panel_env,
) -> None:
    panel, workspace, changes = panel_env
    workspace.current_pack.matrix = MatrixConfig.from_mapping(
        {"enabled": True, "limit": "abc", "slots": [{"name": "outfit", "values": ["a"]}]}
    )
    panel.refresh()
    panel.limit_spin.delete(0, "end")
    panel.limit_spin.insert(0, "-3")
    panel._on_limit_typed()  # noqa: SLF001
    panel.limit_spin.delete(0, "end")
    panel.limit_spin.insert(0, "x")
    panel._on_limit_typed()  # noqa: SLF001

    assert workspace.get_matrix_config().to_mapping()["limit"] == "abc"
    changes.assert_not_called()

    panel.limit_spin.delete(0, "end")
    panel.limit_spin.insert(0, "4")
    panel._on_limit_typed()  # noqa: SLF001
    assert workspace.get_matrix_config().to_mapping()["limit"] == 4
    changes.assert_called_once()


def test_mode_selection_updates_the_help_and_only_random_shows_the_seed_row(panel_env) -> None:
    panel, workspace, changes = panel_env
    assert not panel.seed_frame.winfo_manager()

    panel.mode_var.set("sequential")
    panel._on_mode_changed()  # noqa: SLF001
    assert workspace.get_matrix_config().mode == "sequential"
    assert panel.mode_help_var.get().startswith("Sequential (legacy):")
    assert not panel.seed_frame.winfo_manager()

    panel.mode_var.set("random")
    panel._on_mode_changed()  # noqa: SLF001
    assert panel.seed_frame.winfo_manager()
    assert panel.preview_heading_var.get() == "Illustrative examples (not frozen)"
    assert changes.call_count == 2

    panel._on_mode_changed()  # noqa: SLF001  (re-selecting the same mode is not an edit)
    assert changes.call_count == 2


def test_seed_entry_validates_and_persists_only_valid_values(panel_env) -> None:
    panel, workspace, changes = panel_env
    panel.mode_var.set("random")
    panel._on_mode_changed()  # noqa: SLF001
    changes.reset_mock()

    panel.seed_var.set("12x")
    panel._on_seed_typed()  # noqa: SLF001
    assert workspace.get_matrix_config().sample_seed is None
    assert "whole number" in panel.seed_error_var.get()
    changes.assert_not_called()

    panel.seed_var.set("2026")
    panel._on_seed_typed()  # noqa: SLF001
    assert workspace.get_matrix_config().sample_seed == 2026
    assert panel.seed_error_var.get() == ""
    panel._update_preview()  # noqa: SLF001
    assert panel.preview_heading_var.get() == "Selection for sample seed 2026"
    changes.assert_called_once()

    panel.seed_var.set("")
    panel._on_seed_typed()  # noqa: SLF001
    assert workspace.get_matrix_config().sample_seed is None


def test_add_and_remove_dimensions_and_edit_values(panel_env) -> None:
    panel, workspace, changes = panel_env
    panel._on_slot_added()  # noqa: SLF001
    assert len(panel.slot_widgets) == 4
    name_entry, values_entry, _ = panel.slot_widgets[3]
    name_entry.insert(0, "mood")
    values_entry.insert(0, "calm, tense")
    panel._on_slot_changed(3)  # noqa: SLF001

    slot = workspace.get_matrix_config().slots[3]
    assert (slot.name, slot.values) == ("mood", ["calm", "tense"])
    panel._schedule_preview_update(immediate=True)  # noqa: SLF001
    assert "Dimensions: 4" in panel.summary_var.get()

    panel._on_slot_deleted(3)  # noqa: SLF001
    assert len(workspace.get_matrix_config().slots) == 3
    assert changes.called


def test_a_starter_example_adds_a_new_dimension_and_never_overwrites(panel_env) -> None:
    panel, workspace, changes = panel_env
    outfit = next(item for item in STARTER_DIMENSIONS if item.name == "outfit")
    panel.example_var.set(outfit.label)
    panel._on_example_added()  # noqa: SLF001

    assert "already exists" in panel.example_message_var.get()
    assert [s.values for s in workspace.get_matrix_config().slots][0] == ["a", "b", "c"]
    changes.assert_not_called()

    framing = next(item for item in STARTER_DIMENSIONS if item.name == "framing")
    panel.example_var.set(framing.label)
    panel._on_example_added()  # noqa: SLF001

    names = [s.name for s in workspace.get_matrix_config().slots]
    assert names == ["outfit", "location", "lighting", "framing"]
    assert workspace.get_matrix_config().slots[3].values == list(framing.values)
    assert "[[framing]]" in panel.example_message_var.get()
    changes.assert_called_once()


def test_debounce_replaces_the_pending_update_and_destroy_cancels_it(panel_env) -> None:
    panel, _workspace, _changes = panel_env
    panel.after_cancel = Mock(wraps=panel.after_cancel)  # type: ignore[method-assign]

    panel._schedule_preview_update()  # noqa: SLF001
    first = panel._preview_refresh_after_id  # noqa: SLF001
    panel._schedule_preview_update()  # noqa: SLF001
    second = panel._preview_refresh_after_id  # noqa: SLF001

    assert first is not None and second is not None and first != second
    panel.after_cancel.assert_called_with(first)

    panel.destroy()
    assert panel._preview_refresh_after_id is None  # noqa: SLF001
    panel._run_scheduled_preview_update()  # noqa: SLF001  a stale callback must be harmless
    panel._schedule_preview_update(immediate=True)  # noqa: SLF001


def test_example_rows_follow_the_content_visibility_mode() -> None:
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk unavailable")
    workspace = PromptWorkspaceState()
    pack = workspace.new_pack("Hidden")
    pack.get_slot(0).text = "A [[subject]] portrait"
    pack.matrix = MatrixConfig(
        enabled=True, limit=4, slots=[MatrixSlot("subject", ["nude model", "knight"])]
    )
    mode = {"value": "sfw"}
    panel = MatrixTabPanel(
        root,
        workspace,
        on_matrix_changed=lambda: None,
        visibility_mode_provider=lambda: mode["value"],
    )
    try:
        panel.refresh()
        shown = panel.preview_text.get("1.0", "end")
        assert "[Hidden in SFW mode]" in shown and "nude" not in shown
        assert "A knight portrait" in shown

        mode["value"] = "nsfw"
        panel._update_preview()  # noqa: SLF001
        assert "A nude model portrait" in panel.preview_text.get("1.0", "end")
    finally:
        panel.destroy()


def test_the_panel_content_lives_in_the_shared_scrollable_frame(panel_env) -> None:
    panel, _workspace, _changes = panel_env
    inner = panel._scroll.inner  # noqa: SLF001
    ancestors = []
    widget = panel.preview_text
    while widget is not None:
        ancestors.append(widget)
        widget = widget.master

    assert inner in ancestors


def test_prompt_tab_summary_line_comes_from_the_same_plan() -> None:
    from src.gui_v2.matrix_editor_view import matrix_summary_line

    assert matrix_summary_line(_config()) == (
        "Matrix combinations: 24 possible, 8 selected (limit 8; 16 not queued)"
    )
    assert matrix_summary_line(_config(limit=50)) == "Matrix combinations: 24 possible, 24 selected"
    assert matrix_summary_line(_config(enabled=False)).endswith(" - Matrix is off")
    assert matrix_summary_line(MatrixConfig(enabled=True)) == ""
