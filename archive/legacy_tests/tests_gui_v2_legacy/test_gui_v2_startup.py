"""Basic startup smoke tests for the v2 GUI harness."""

from __future__ import annotations

import pytest


def test_gui_v2_startup(gui_app_factory):
    """StableNewGUI should initialize key panels without raising."""

    app = gui_app_factory()

    assert app.root.winfo_exists()
    assert hasattr(app, "prompt_pack_panel")
    assert hasattr(app, "center_notebook")
    assert hasattr(app, "pipeline_controls_panel")
