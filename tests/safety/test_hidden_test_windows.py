"""PR-TEST-HIDDEN-WINDOWS: test windows stay mapped but never show on the operator's screen."""

from __future__ import annotations

import sys
import tkinter as tk

import pytest

from tests.helpers import hidden_test_windows
from tests.helpers.hidden_test_windows import (
    DESKTOP_LANE_ENV,
    OFF_SCREEN_X,
    OFF_SCREEN_Y,
    VISIBLE_ENV,
    show_test_root,
    windows_stay_hidden,
)

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="window transparency is applied on Windows only"
)


def _settle(root: tk.Tk) -> None:
    for _ in range(5):
        root.update()


@pytest.fixture
def root():
    try:
        made = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
    yield made
    made.destroy()


def test_the_root_conftest_hides_every_window_a_test_creates() -> None:
    # A new GUI test, in any directory, gets the hook without opting in.
    assert hidden_test_windows.is_installed()


@pytest.mark.parametrize(
    ("environ", "platform", "hidden"),
    [
        ({}, "win32", True),
        ({VISIBLE_ENV: "1"}, "win32", False),  # the operator asked to watch
        ({DESKTOP_LANE_ENV: "1"}, "win32", False),  # physical input needs real windows
        ({VISIBLE_ENV: "0"}, "win32", True),
        ({}, "linux", False),  # hosted Linux shards keep their behaviour
    ],
)
def test_windows_stay_hidden_unless_an_opt_out_or_another_platform(
    environ: dict[str, str], platform: str, hidden: bool
) -> None:
    assert windows_stay_hidden(environ, platform) is hidden


@windows_only
def test_a_shown_root_and_toplevel_are_transparent_but_still_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The opt-out is read when a window is created, so clear it before creating any (even under VISIBLE=1).
    monkeypatch.delenv(VISIBLE_ENV, raising=False)
    monkeypatch.delenv(DESKTOP_LANE_ENV, raising=False)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
    try:
        child = tk.Toplevel(root)
        root.deiconify()  # what app code and visibility fixtures do
        label = tk.Label(root, text="x")
        label.pack()
        _settle(root)
        assert float(root.wm_attributes("-alpha")) == 0.0
        assert float(child.wm_attributes("-alpha")) == 0.0
        # Visibility assertions still mean something.
        assert label.winfo_ismapped() and label.winfo_viewable()
        assert child.winfo_ismapped()
    finally:
        root.destroy()


@windows_only
def test_the_visible_opt_out_leaves_windows_opaque(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VISIBLE_ENV, "1")
    try:
        made = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
    try:
        made.withdraw()
        assert float(made.wm_attributes("-alpha")) == 1.0
    finally:
        made.destroy()


def test_show_test_root_returns_with_the_root_mapped_at_its_size(root: tk.Tk) -> None:
    root.withdraw()
    show_test_root(root, 640, 480)
    # A precondition, not a settle: no further event processing is needed for the root to be shown.
    assert root.winfo_ismapped()
    assert (root.winfo_width(), root.winfo_height()) == (640, 480)
    label = tk.Label(root, text="x")
    label.pack()
    root.update_idletasks()  # geometry work only: the label maps inside the already-shown root
    assert label.winfo_ismapped()
    expected = f"+{OFF_SCREEN_X}+{OFF_SCREEN_Y}" if windows_stay_hidden() else "+0+0"
    assert root.wm_geometry().endswith(expected)


def test_show_test_root_is_not_capped_by_the_screen(root: tk.Tk) -> None:
    width, height = root.winfo_screenwidth() + 300, root.winfo_screenheight() + 200

    show_test_root(root, width, height)

    assert (root.winfo_width(), root.winfo_height()) == (width, height)
