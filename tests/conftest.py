import os
import time
import tkinter as tk

import pytest


@pytest.fixture
def tk_root():
    """Fixture to provide a Tk root window for GUI tests, skips if Tk is not available or no display."""
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
        root.destroy()
    except tk.TclError:
        pytest.skip("No display available for Tkinter tests")


@pytest.fixture
def tk_pump(tk_root):
    """Pump Tk events without blocking the main thread."""

    def pump(duration=0.2, step=0.01):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            try:
                tk_root.update()
            except Exception:
                break
            time.sleep(step)

    return pump


"""Global test configuration and monkeypatches"""


@pytest.fixture(autouse=True)
def _mock_webui_discovery(monkeypatch):
    """Prevent tests from launching or probing real WebUI services.

    This avoids background threads calling Tkinter/after() which crash on Windows CI.
    """
    monkeypatch.setenv("STABLENEW_NO_WEBUI", "1")

    try:
        import src.utils.webui_discovery as wd  # type: ignore
    except Exception:
        return

    def fake_find_port(*_args, **_kwargs):
        return None

    def fake_launch_safely(*_args, **_kwargs):
        return None

    monkeypatch.setattr(wd, "find_webui_api_port", fake_find_port, raising=False)
    monkeypatch.setattr(wd, "launch_webui_safely", fake_launch_safely, raising=False)

    try:
        import src.api.client as api_client  # type: ignore

        current_test = os.environ.get("PYTEST_CURRENT_TEST", "")
        if "tests/test_api.py" not in current_test and "tests/test_api_client.py" not in current_test:
            monkeypatch.setattr(
                api_client.SDWebUIClient,
                "check_api_ready",
                lambda self, *args, **kwargs: False,
                raising=False,
            )
    except Exception:
        pass

    try:
        import src.gui.main_window as main_window  # type: ignore

        monkeypatch.setattr(
            main_window.StableNewGUI, "_check_api_connection", lambda self: None, raising=False
        )
        monkeypatch.setattr(
            main_window.StableNewGUI, "_launch_webui", lambda self: None, raising=False
        )
    except Exception:
        pass


# Preserve existing tmp_path fixture override
@pytest.fixture
def tmp_path(tmp_path_factory):
    """Provide a temporary directory for tests"""
    return tmp_path_factory.mktemp("test_data")
