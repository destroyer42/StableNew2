"""An off-screen main window is pulled back when it is shown again or a widget maps: real window, production bindings.

This describes behaviour that predates STARTUP-STALL-2 (the file also passes on the code before it).
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable

import pytest

from tests.helpers.gui_harness import pipeline_harness


def _pump_until(root: tk.Tk, ready: Callable[[], bool], timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while True:
        root.update()
        if ready():
            return
        assert time.monotonic() < end, f"never reached; geometry={root.geometry()}"
        time.sleep(0.01)


def _settle(root: tk.Tk, seconds: float = 1.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


@pytest.mark.gui
def test_an_off_screen_window_comes_back_when_shown_again_or_a_widget_maps(isolated_cwd) -> None:
    with pipeline_harness() as harness:
        root, window = harness.root, harness.window

        def on_screen() -> bool:
            return window._is_window_geometry_visible(root.geometry())

        def move_off_screen() -> None:
            root.geometry(f"+{root.winfo_screenwidth() + 400}+80")
            root.update_idletasks()
            assert not on_screen()

        root.deiconify()
        _pump_until(root, lambda: bool(root.winfo_ismapped()))
        _settle(root)
        assert on_screen()

        for hide in ("withdraw", "iconify"):
            getattr(root, hide)()
            root.update()
            if root.winfo_ismapped():
                continue  # no window manager (CI's Xvfb): iconify leaves the window as it was
            move_off_screen()
            root.deiconify()
            _pump_until(root, lambda: bool(root.winfo_ismapped()) and on_screen())
            _settle(root)

        # Moved while it stays mapped: Tk delivers descendants' <Map> to the root binding, so a tab switch re-checks.
        move_off_screen()
        notebook = window.center_notebook
        notebook.select(next(tab for tab in notebook.tabs() if tab != notebook.select()))
        _pump_until(root, on_screen)
