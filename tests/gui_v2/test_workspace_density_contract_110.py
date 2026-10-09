"""PR-GUI-110: pure sizing/disclosure rules (no Tk)."""

from __future__ import annotations

import pytest

from src.gui.view_contracts.workspace_density_contract import (
    PREVIEW_MAX_EDGE,
    PREVIEW_MIN_EDGE,
    changed_value_count,
    disclosure_title,
    preview_panel_stacked,
    preview_resize_needed,
    preview_side,
    severity_counts,
    severity_summary,
    wrap_width,
)


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (0, PREVIEW_MAX_EDGE),  # not laid out yet: keep the historical size
        (1, PREVIEW_MAX_EDGE),
        (100, PREVIEW_MIN_EDGE),  # never smaller than a recognisable thumbnail
        (200, 200),
        (437, 437),
        (620, 620),
        (1400, PREVIEW_MAX_EDGE),  # never larger than the old fixed size
    ],
)
def test_preview_side_follows_the_parent_width_within_bounds(available: int, expected: int) -> None:
    assert preview_side(available) == expected


def test_preview_resize_ignores_jitter_but_follows_real_changes() -> None:
    assert not preview_resize_needed(620, 622)
    assert not preview_resize_needed(620, 617)
    assert preview_resize_needed(620, 600)
    assert preview_resize_needed(300, 620)


@pytest.mark.parametrize(
    ("container", "kwargs", "expected"),
    [
        (0, {}, 520),  # unrealised: keep a sane default rather than collapsing
        (800, {"margin": 24}, 776),
        (100, {"margin": 24}, 160),  # floor
        (1400, {"margin": 24, "maximum": 880}, 880),  # the old fixed value is now a cap
    ],
)
def test_wrap_width_tracks_the_container_with_a_floor_and_optional_cap(container, kwargs, expected) -> None:
    assert wrap_width(container, **kwargs) == expected


def test_severity_counts_include_repeats_and_never_drop_errors() -> None:
    entries = [
        {"level": "INFO"},
        {"level": "WARNING", "repeat_count": 4},
        {"level": "ERROR"},
        {"level": "CRITICAL", "repeat_count": 2},
        {"level": "DEBUG"},
        {"level": "WARNING", "repeat_count": "bad"},
    ]
    assert severity_counts(entries) == (5, 3)
    assert severity_summary(5, 3) == "3 errors | 5 warnings"
    assert severity_summary(1, 0) == "1 warning"
    assert severity_summary(0, 1) == "1 error"
    assert severity_summary(0, 0) == ""


def test_changed_value_count_compares_normalised_values_to_defaults() -> None:
    defaults = {"camera": "none", "strength": "0.35", "depth": "none", "path": ""}
    assert changed_value_count(dict(defaults), defaults) == 0
    assert changed_value_count({**defaults, "strength": "0.350"}, defaults) == 0  # numerically equal
    assert changed_value_count({**defaults, "camera": "dolly_in", "path": "x.png"}, defaults) == 2
    assert changed_value_count({"unknown": "v"}, defaults) == 1  # a key with no default differs from empty


@pytest.mark.parametrize(
    ("width", "stacked"),
    [(0, False), (1, False), (440, True), (560, False), (900, False)],
)
def test_preview_panel_stacks_only_when_labels_would_be_squeezed(width: int, stacked: bool) -> None:
    assert preview_panel_stacked(width, thumbnail_edge=300, label_min=240) is stacked


def test_disclosure_title_shows_status_only_while_collapsed() -> None:
    collapsed = disclosure_title("Advanced Conditioning", expanded=False, status="2 edited")
    expanded = disclosure_title("Advanced Conditioning", expanded=True, status="2 edited")
    assert "2 edited" in collapsed and collapsed.startswith("▸")
    assert "2 edited" not in expanded and expanded.startswith("▾")
