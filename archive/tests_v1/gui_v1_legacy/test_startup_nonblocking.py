"""Headless regression test: GUI startup should not hang main thread due to WebUI discovery.

If auto-launch discovery blocks, scheduled after-callback will never fire within timeout.
"""
import os
import time
import tkinter as tk

import pytest

# Skip if display not available (CI headless behavior)
if os.environ.get("DISPLAY") is None and os.name != "nt":  # Windows can create Tk without DISPLAY
    pytest.skip("No display available for Tkinter tests", allow_module_level=True)

# Force disable WebUI launch to isolate discovery thread behavior
os.environ["STABLENEW_NO_WEBUI"] = "1"

from src.gui.main_window import StableNewGUI  # noqa: E402


def test_gui_startup_non_blocking():
    start = time.time()
    try:
        gui = StableNewGUI()  # Construct GUI (creates its own Tk root)
    except tk.TclError:
        pytest.skip("Tk not available/installed properly on this system")
    root = gui.root

    # Marker mutated by after callback
    flag = {"fired": False}

    def mark():
        flag["fired"] = True

    # Schedule marker shortly after init to ensure mainloop remains responsive
    root.after(150, mark)

    # Pump events manually for up to 2 seconds
    deadline = start + 2.0
    while time.time() < deadline and not flag["fired"]:
        root.update()
        time.sleep(0.01)

    assert flag["fired"], "Tk after() callback did not fire; GUI startup likely blocked"
    assert (time.time() - start) < 2.0, "Startup exceeded 2s without WebUI launch; potential hang"

    # Clean up
    root.destroy()
