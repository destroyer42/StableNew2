"""Tests covering the validation color helper exposed by theme_v2."""

from __future__ import annotations

from src.gui.theme_v2 import (
    VALIDATION_ERROR_BG,
    VALIDATION_ERROR_FG,
    VALIDATION_NORMAL_BG,
    VALIDATION_NORMAL_FG,
    VALIDATION_WARN_BG,
    VALIDATION_WARN_FG,
    apply_validation_colors,
    get_validation_palette,
)


class _DummyWidget:
    """Simple object that records configure calls."""

    def __init__(self) -> None:
        self.config: dict[str, str] = {}

    def configure(self, **kwargs: str) -> None:  # type: ignore[override]
        self.config.update(kwargs)


def test_validation_palette_returns_expected_colors() -> None:
    normal = get_validation_palette("normal")
    warn = get_validation_palette("warn")
    error = get_validation_palette("error")

    assert normal["background"] == VALIDATION_NORMAL_BG
    assert normal["foreground"] == VALIDATION_NORMAL_FG
    assert warn["background"] == VALIDATION_WARN_BG
    assert warn["foreground"] == VALIDATION_WARN_FG
    assert error["background"] == VALIDATION_ERROR_BG
    assert error["foreground"] == VALIDATION_ERROR_FG


def test_apply_validation_colors_updates_widget() -> None:
    widget = _DummyWidget()
    apply_validation_colors(widget, "error")

    assert widget.config["background"] == VALIDATION_ERROR_BG
    assert widget.config["foreground"] == VALIDATION_ERROR_FG
