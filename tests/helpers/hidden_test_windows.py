"""Keep test windows off the operator's screen while they stay mapped.

Local Windows runs already go to a private desktop (``tools/ci/quiet_run.py``), but not every test process does: an
in-process ``pytest.main()``, a run where the private desktop could not be created, or another tool's launcher.
``install()`` (called when ``tests/conftest.py`` is imported) therefore makes every ``tk.Tk`` and ``tk.Toplevel`` a test
creates fully transparent. The window is still mapped and viewable for ``winfo_ismapped``/``winfo_viewable``
assertions, but nothing shows and nothing flickers, whatever the test or the app code does to it later
(``deiconify``, ``geometry``, ``state("zoomed")``).

``show_test_root`` maps a root for a visibility assertion. It places the root off screen while windows are hidden, and
returns only once the root is mapped at the requested size.

Opt-outs (the window is left as Tk made it): off Windows (hosted Linux shards keep their current behaviour),
``STABLENEW_TESTS_VISIBLE=1`` (the operator wants to watch), and ``STABLENEW_DESKTOP_LANE=1`` (the physical-input lane
needs real, visible windows). The opt-out is read when each window is created.
"""

from __future__ import annotations

import functools
import os
import sys
import time
import tkinter as tk
from collections.abc import Mapping

VISIBLE_ENV = "STABLENEW_TESTS_VISIBLE"
DESKTOP_LANE_ENV = "STABLENEW_DESKTOP_LANE"
# Far left of any monitor layout, but not Windows' -32000 "minimised" sentinel.
OFF_SCREEN_X = -20000
OFF_SCREEN_Y = -20000
WINDOW_SIZE_CAP = (8000, 8000)
HIT_TEST_ALPHA = 0.01
_MARKER = "_stablenew_hidden_test_window"


def windows_stay_hidden(
    environ: Mapping[str, str] | None = None, platform: str = sys.platform
) -> bool:
    """Whether a window created now should be made transparent."""

    env = os.environ if environ is None else environ
    if platform != "win32":
        return False
    return env.get(VISIBLE_ENV) != "1" and env.get(DESKTOP_LANE_ENV) != "1"


def _hide(window: tk.Misc) -> None:
    if not windows_stay_hidden():
        return
    try:
        window.wm_attributes("-alpha", 0.0)  # type: ignore[attr-defined]
    except (tk.TclError, AttributeError):  # useTk=False roots have no window manager
        pass


def _wrap(cls: type) -> None:
    original = cls.__init__
    if getattr(original, _MARKER, False):
        return

    @functools.wraps(original)
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        original(self, *args, **kwargs)
        _hide(self)

    setattr(__init__, _MARKER, True)
    cls.__init__ = __init__  # type: ignore[misc]


def install() -> None:
    """Make every ``tk.Tk`` and ``tk.Toplevel`` created from now on transparent (idempotent)."""

    _wrap(tk.Tk)
    _wrap(tk.Toplevel)


def is_installed() -> bool:
    return all(getattr(cls.__init__, _MARKER, False) for cls in (tk.Tk, tk.Toplevel))


def uncap_window_size(root: tk.Misc) -> None:
    """Let a test window be any size, whatever this machine's screen is.

    Windows caps a window at the screen size until ``wm maxsize`` says otherwise, so a test laid out for 1342 pixels got
    1028 on a 1024-wide display. The hosted runner's X server applies no such cap.
    """

    root.wm_maxsize(*WINDOW_SIZE_CAP)  # type: ignore[attr-defined]


def keep_hit_testable(window: tk.Misc) -> None:
    """For a test that asks which widget is under a point (``winfo_containing``, pointer events).

    Windows hit testing passes straight through a fully transparent window, so such a test finds nothing there. One
    percent opacity is still practically invisible, and the private desktop of a quiet run shows nothing anyway.
    """

    if windows_stay_hidden():
        window.wm_attributes("-alpha", HIT_TEST_ALPHA)  # type: ignore[attr-defined]


def show_test_root(root: tk.Misc, width: int, height: int, *, timeout_s: float = 10.0) -> None:
    """Map ``root`` at ``width`` x ``height`` and return only once it is mapped at that size.

    ``deiconify`` maps a toplevel later, and its real size arrives as window-system events. Until both have been
    processed the root is 1x1, so widgets packed into it get no room and stay unmapped. A fixed settle after it then
    passes or fails with machine load. Waiting here makes "the root is shown at this size" a precondition of the test.
    Windows caps a window at the screen size unless ``wm maxsize`` says otherwise, so the cap is raised first: a test
    laid out for 1342 pixels gets them on a 1024-wide display, as it does on the hosted runner's X server.
    The root goes off screen while windows are hidden, and to ``+0+0`` when the operator opted to watch.
    """

    x, y = (OFF_SCREEN_X, OFF_SCREEN_Y) if windows_stay_hidden() else (0, 0)
    uncap_window_size(root)
    root.wm_geometry(f"{width}x{height}+{x}+{y}")  # type: ignore[attr-defined]
    root.wm_deiconify()  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout_s
    while True:
        root.update()
        if root.winfo_ismapped() and (root.winfo_width(), root.winfo_height()) == (width, height):
            return
        if time.monotonic() > deadline:
            raise AssertionError(
                f"test root not shown at {width}x{height} within {timeout_s}s: "
                f"mapped={root.winfo_ismapped()} size={root.winfo_width()}x{root.winfo_height()}"
            )
        time.sleep(0.005)
