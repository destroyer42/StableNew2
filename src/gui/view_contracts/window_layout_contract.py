"""Screen-aware main-window geometry policy (PR-GUI-100).

One pure authority for the root window's default size, minimum size and the normalization of a saved geometry.
Everything is derived from the available screen size, so the window never demands a viewport larger than the
display (the previous fixed 1984 x 1350 default / 1984 x 1110 minimum did on common 1920 x 1080 and 1366 x 768
desktops). Long workspaces stay reachable through scrolling instead of through window size.

No Tk calls live here; callers pass ``winfo_screenwidth()`` / ``winfo_screenheight()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Preferred (not required) sizes on a roomy display. Kept modest so a large monitor does not get a giant blank window.
# 1900 is the narrowest width at which every Pipeline control fits its column (measured); on a 1920 px display the
# usable width (1896) is used, so the default there is the same.
PREFERRED_WIDTH = 1900
PREFERRED_HEIGHT = 1000
# Smallest window the three-column Pipeline workspace is comfortable in; clamped to the screen below.
PREFERRED_MIN_WIDTH = 1280
PREFERRED_MIN_HEIGHT = 680

# Space left for window chrome, the title bar and the Windows taskbar so the client area never equals the screen.
SCREEN_MARGIN_WIDTH = 24
SCREEN_MARGIN_HEIGHT = 96

# Existing off-screen sentinel (a minimized-window position) that must still recover to a visible window.
WINDOW_SENTINEL_OFFSCREEN = -10000


@dataclass(frozen=True)
class WindowLayout:
    """Default and minimum normal-window size for one screen; every field fits inside the screen."""

    screen_width: int
    screen_height: int
    width: int
    height: int
    min_width: int
    min_height: int

    @property
    def default_geometry(self) -> str:
        return f"{self.width}x{self.height}"


def compute_window_layout(screen_width: int, screen_height: int) -> WindowLayout:
    """Pick a useful default size and a minimum that both fit the (usable) screen."""

    screen_w = max(1, int(screen_width or 0))
    screen_h = max(1, int(screen_height or 0))
    usable_w = max(1, screen_w - SCREEN_MARGIN_WIDTH)
    usable_h = max(1, screen_h - SCREEN_MARGIN_HEIGHT)
    min_w = min(PREFERRED_MIN_WIDTH, usable_w)
    min_h = min(PREFERRED_MIN_HEIGHT, usable_h)
    return WindowLayout(
        screen_width=screen_w,
        screen_height=screen_h,
        width=max(min_w, min(PREFERRED_WIDTH, usable_w)),
        height=max(min_h, min(PREFERRED_HEIGHT, usable_h)),
        min_width=min_w,
        min_height=min_h,
    )


_GEOMETRY_RE = re.compile(r"(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?")


def parse_geometry(geometry: str) -> tuple[int, int, int | None, int | None] | None:
    """``WxH`` or ``WxH+X+Y`` (Tk's form, offsets may be negative) -> (w, h, x, y); None if malformed."""

    match = _GEOMETRY_RE.fullmatch(str(geometry or "").strip())
    if match is None:
        return None
    width, height, x, y = match.groups()
    return int(width), int(height), None if x is None else int(x), None if y is None else int(y)


def normalize_saved_geometry(geometry: str, layout: WindowLayout) -> str | None:
    """Return a geometry that is safe to apply on this screen, or None to fall back to the default.

    * malformed, non-positive, or sentinel-off-screen geometries are rejected (the caller recovers to the default);
    * a size larger than the usable screen is clamped to it, a size below the minimum is raised to it;
    * a position is moved just enough that the window overlaps the screen and its title bar stays reachable;
    * a valid geometry that already fits is returned unchanged.
    """

    parsed = parse_geometry(geometry)
    if parsed is None:
        return None
    width, height, x, y = parsed
    if width <= 0 or height <= 0:
        return None
    if x is not None and y is not None and (x <= WINDOW_SENTINEL_OFFSCREEN or y <= WINDOW_SENTINEL_OFFSCREEN):
        return None
    usable_w = max(layout.min_width, layout.screen_width - SCREEN_MARGIN_WIDTH)
    usable_h = max(layout.min_height, layout.screen_height - SCREEN_MARGIN_HEIGHT)
    new_w = max(layout.min_width, min(width, usable_w))
    new_h = max(layout.min_height, min(height, usable_h))
    if x is None or y is None:
        return f"{new_w}x{new_h}"
    margin_x, margin_y = 80, 60
    visible = (
        x < layout.screen_width - margin_x
        and y < layout.screen_height - margin_y
        and (x + new_w) > margin_x
        and (y + new_h) > margin_y
    )
    if not visible:
        return None
    # keep the (possibly clamped) window on the screen
    x = max(0, min(x, layout.screen_width - new_w)) if new_w <= layout.screen_width else 0
    y = max(0, min(y, layout.screen_height - new_h)) if new_h <= layout.screen_height else 0
    return f"{new_w}x{new_h}+{x}+{y}"


__all__ = [
    "PREFERRED_HEIGHT",
    "PREFERRED_MIN_HEIGHT",
    "PREFERRED_MIN_WIDTH",
    "PREFERRED_WIDTH",
    "SCREEN_MARGIN_HEIGHT",
    "SCREEN_MARGIN_WIDTH",
    "WINDOW_SENTINEL_OFFSCREEN",
    "WindowLayout",
    "compute_window_layout",
    "normalize_saved_geometry",
    "parse_geometry",
]
