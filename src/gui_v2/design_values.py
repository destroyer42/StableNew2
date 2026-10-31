"""Toolkit-neutral design values for StableNew: the single source of the raw palette, spacing, type and radii.

Pure constants. This module imports nothing, so a Tk, Qt or headless host can read the same immutable values without
loading a toolkit. Renderers own their own registration: ``src/gui/design_system_v2.py`` re-exports these names and
registers the ttk styles; semantic roles live in ``src/gui/ui_tokens.py``. Change a value here and only here.
"""

from __future__ import annotations

from dataclasses import dataclass

Color = str


@dataclass(frozen=True)
class Spacing:
    NONE: int = 0
    XS: int = 2
    SM: int = 4
    MD: int = 8
    LG: int = 12
    XL: int = 16


@dataclass(frozen=True)
class Radii:
    SM: int = 4
    MD: int = 8
    LG: int = 12


@dataclass(frozen=True)
class Typography:
    FAMILY: str = "Segoe UI"
    XS: int = 9
    SM: int = 10
    MD: int = 11
    LG: int = 12
    XL: int = 14
    BOLD: str = "bold"
    NORMAL: str = "normal"


@dataclass(frozen=True)
class Colors:
    PRIMARY_BG: Color = "#121212"
    ELEVATED_SURFACE: Color = "#1E1E1E"
    CARD_BG: Color = "#1E1E1E"
    BORDER: Color = "#2D2D2D"
    PRIMARY_ACCENT: Color = "#FFC805"
    PRIMARY_ACCENT_HOVER: Color = "#FFD94D"
    TEXT_PRIMARY: Color = "#FFFFFF"
    TEXT_MUTED: Color = "#CCCCCC"
    TEXT_DISABLED: Color = "#777777"
    # PR-GUI-400: white on the former #FF4D4F fill was 3.3:1; this deeper red keeps the identity at 4.6:1.
    DANGER_BG: Color = "#D9363E"
    DANGER_BG_HOVER: Color = "#C62F36"
    DANGER_FG: Color = "#FFFFFF"
    SEPARATOR: Color = "#2A2A2A"
    # PR-GUI-400: interactive-state surfaces and the focus edge (gold on dark surfaces, white on gold/red fills).
    SURFACE_HOVER: Color = "#262626"
    SURFACE_SELECTED: Color = "#2B2B2B"
    SECONDARY_HOVER: Color = "#3A3A3A"
    TEXT_ON_ACCENT: Color = "#000000"
    FOCUS_RING: Color = PRIMARY_ACCENT
    FOCUS_RING_ON_FILL: Color = "#FFFFFF"
    ACCENT_DISABLED_EDGE: Color = "#8C7413"


NOTICE_KINDS = ("neutral", "info", "success", "warning", "error")


__all__ = ["Color", "Colors", "NOTICE_KINDS", "Radii", "Spacing", "Typography"]
