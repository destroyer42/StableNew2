"""Tests for the PipelineCommandBarV2 widget."""

from __future__ import annotations

import pytest


def test_command_bar_exposes_run_stop_and_queue_controls(tk_root):
    """The command bar should expose run, stop, and queue toggle widgets."""

    from src.gui.pipeline_command_bar_v2 import PipelineCommandBarV2

    bar = PipelineCommandBarV2(tk_root)

    assert hasattr(bar, "run_button")
    assert hasattr(bar, "stop_button")
    assert hasattr(bar, "queue_toggle")


def test_command_bar_initial_queue_state_matches_config(tk_root):
    """Queue toggle should reflect provided initial state and respond to setters."""

    from src.gui.pipeline_command_bar_v2 import PipelineCommandBarV2

    bar = PipelineCommandBarV2(tk_root, queue_enabled=True)

    assert bar.get_queue_mode() is True

    bar.set_queue_mode(False)
    assert bar.get_queue_mode() is False
