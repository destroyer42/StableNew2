"""Live design-token facade over the active theme (prototype only).

Every value comes from a :class:`~stablenew_qt_proto.theme.Theme` (JSON-backed, validated).
``COLORS``, ``SPACE`` and ``RADIUS`` are *live* views: reading an attribute returns the value of
whichever theme is active right now, so components built after ``set_active_theme`` pick up new
spacing and colours. The default theme is the reference preset ``blue-modern`` (the accepted
v0.3.0 look). Isolated from the production Tk theme: production Qt migration MUST re-evaluate
token ownership and may not introduce an independent runtime source of truth.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .theme import (
    Theme,
    build_stylesheet,
    contrast_checks,
    contrast_ratio,
    luminance,
    parse_theme_json,
)

ASSET_DIR = Path(__file__).resolve().parent / "assets"
THEME_DIR = Path(__file__).resolve().parent / "themes"
ASSET_FILES = ("arrow_up.svg", "arrow_down.svg", "chevron_down.svg", "check.svg")
DEFAULT_THEME_ID = "blue-modern"

__all__ = [
    "ASSET_DIR", "ASSET_FILES", "COLORS", "CONTRAST_PAIRS", "RADIUS", "SPACE", "THEME_DIR",
    "active_theme", "asset_url", "contrast_ratio", "luminance", "make_stylesheet",
    "preview_theme", "reference_theme", "reference_themes", "set_active_theme",
]


def reference_themes(directory: Path = THEME_DIR) -> dict[str, Theme]:
    """Shipped, read-only reference presets keyed by id. Files are only ever read."""
    themes: dict[str, Theme] = {}
    for path in sorted(directory.glob("*.theme.json")):
        theme = parse_theme_json(path.read_text(encoding="utf-8"))
        if theme.kind != "reference":
            raise ValueError(f"{path.name} must be a reference theme")
        themes[theme.id] = theme
    return themes


def reference_theme(theme_id: str) -> Theme:
    return reference_themes()[theme_id]


_active: Theme = reference_theme(DEFAULT_THEME_ID)


def active_theme() -> Theme:
    return _active


def set_active_theme(theme: Theme) -> None:
    global _active
    _active = theme


@contextmanager
def preview_theme(theme: Theme) -> Iterator[None]:
    """Temporarily make ``theme`` active (used to build Theme Studio previews with draft metrics)."""
    previous = active_theme()
    set_active_theme(theme)
    try:
        yield
    finally:
        set_active_theme(previous)


class _Live:
    """Attribute access resolved against the active theme at read time."""

    def __init__(self, resolve: Callable[[], Any]):
        object.__setattr__(self, "_resolve", resolve)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_resolve")(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("design tokens are read-only; edit a theme instead")


COLORS = _Live(lambda: _active.palette)
SPACE = _Live(lambda: _active.metrics())
RADIUS = _Live(lambda: _active.radius)

# (label, foreground, background, minimum ratio) for the default reference theme; asserted by tests.
CONTRAST_PAIRS: tuple[tuple[str, str, str, float], ...] = tuple(
    (check.label, check.foreground, check.background, check.minimum)
    for check in contrast_checks(reference_theme(DEFAULT_THEME_ID))
)


def asset_url(name: str, directory: Path = ASSET_DIR) -> str:
    return 'url("' + (directory / name).as_posix() + '")'


def make_stylesheet(asset_dir: Path = ASSET_DIR, theme: Theme | None = None) -> str:
    """Widget stylesheet for ``theme`` (default: the active theme); never touches the GUI."""
    return build_stylesheet(theme or _active, asset_dir)

