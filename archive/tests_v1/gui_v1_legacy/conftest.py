"""Shared GUI test fixtures and helpers."""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from typing import Any, Callable

import pytest

from src.services.config_service import ConfigService
from src.utils.config import ConfigManager
from src.utils.preferences import PreferencesManager

os.environ.setdefault("STABLENEW_GUI_TEST_MODE", "1")

DEFAULT_TIMEOUT = 5.0
DEFAULT_INTERVAL = 0.05


def wait_until(
    predicate: Callable[[], Any],
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    step: float | None = None,
) -> Any:
    """
    Poll `predicate` until it returns a truthy value or `timeout` seconds elapse.

    Returns the predicate's value when truthy.
    Raises TimeoutError if the condition is never met.
    """

    end = time.monotonic() + timeout
    last_value: Any = None

    if step is not None:
        interval = step

    while time.monotonic() < end:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval)

    raise TimeoutError(f"Condition not met within {timeout} seconds")


def wait_until_tk(
    root: tk.Misc,
    predicate: Callable[[], Any],
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
) -> Any:
    """
    Poll predicate while processing Tk events via root.update().

    Useful for GUI tests that expect the event loop to progress while waiting.
    """
    end = time.monotonic() + timeout
    last_value: Any = None

    while time.monotonic() < end:
        try:
            root.update()
        except tk.TclError:
            pass
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval)

    raise TimeoutError(f"Condition not met within {timeout} seconds")


def pump_events_until(
    root: tk.Misc,
    predicate: Callable[[], Any],
    timeout: float = 3.0,
    poll_interval: float = 0.01,
) -> Any:
    """
    Pump Tk events until `predicate()` returns truthy or timeout expires.

    Raises TimeoutError if the predicate never succeeds.
    """
    end = time.monotonic() + timeout

    while time.monotonic() < end:
        try:
            root.update_idletasks()
            root.update()
        except tk.TclError:
            pass

        value = predicate()
        if value:
            return value

        time.sleep(poll_interval)

    raise TimeoutError("Timed out waiting for predicate in pump_events_until")


def create_tk_root() -> tk.Tk:
    """
    Attempt to create a Tk root window, skipping if Tcl/Tk is unavailable.
    """
    try:
        return tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")


@pytest.fixture
def tk_root():
    """Provide a Tk root window or skip if not available."""
    if sys.platform.startswith("linux") and "DISPLAY" not in os.environ:
        # Allow CI setups to inject their own xvfb display
        os.environ.setdefault("DISPLAY", ":99")

    root = create_tk_root()
    root.withdraw()

    yield root

    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def minimal_gui_app(monkeypatch, tk_root, tmp_path):
    """
    Provide a StableNewGUI instance with side-effects (WebUI launch, network checks) disabled.
    """
    monkeypatch.setenv("STABLENEW_GUI_TEST_MODE", "1")

    from src.gui.main_window import (
        StableNewGUI,
        enable_gui_test_mode,
        reset_gui_test_mode,
    )

    enable_gui_test_mode()

    monkeypatch.setattr("src.gui.main_window.StableNewGUI._launch_webui", lambda self: None)
    monkeypatch.setattr("src.gui.main_window.launch_webui_safely", lambda *_, **__: False)
    monkeypatch.setattr("src.gui.main_window.find_webui_api_port", lambda *_, **__: None)
    monkeypatch.setattr(
        "src.gui.main_window.validate_webui_health",
        lambda *_, **__: {"models_loaded": False, "model_count": 0},
    )

    config_manager = ConfigManager(tmp_path / "presets")
    preferences = PreferencesManager(tmp_path / "prefs.json")

    try:
        app = StableNewGUI(
            root=tk_root,
            config_manager=config_manager,
            preferences=preferences,
            title="TestGUI",
            geometry="1024x720",
        )

        # Redirect config service storage to the temporary test directory
        app.config_service = ConfigService(tmp_path / "packs", tmp_path / "presets", tmp_path / "lists")
        app.structured_logger.output_dir = tmp_path / "output"
        app.structured_logger.output_dir.mkdir(parents=True, exist_ok=True)

        yield app
    finally:
        reset_gui_test_mode()
