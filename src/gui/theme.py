"""
Legacy theming shim.

Phase-1 note:
    New code should import from `src.gui.theme_v2` directly.
    This module exists only to keep any remaining imports from crashing
    while we finalize the V2-only GUI path.
"""

from __future__ import annotations

# Re-export all public symbols from theme_v2 so imports that still use
# `from src.gui import theme as theme_mod` continue to work.
from src.gui.theme_v2 import *  # noqa: F401,F403

# Backward-compatibility aliases for legacy callers
COLOR_SURFACE_ALT = BACKGROUND_ELEVATED  # noqa: F405
COLOR_SURFACE = BACKGROUND_DARK  # noqa: F405
COLOR_TEXT = TEXT_PRIMARY  # noqa: F405
COLOR_TEXT_MUTED = TEXT_MUTED  # noqa: F405
COLOR_BORDER_SUBTLE = BORDER_SUBTLE  # noqa: F405
COLOR_ACCENT = ACCENT_GOLD  # noqa: F405
ASWF_BLACK = BACKGROUND_DARK  # noqa: F405

__all__ = [name for name in globals() if not name.startswith("_")]
