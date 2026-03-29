"""GUI tests for the structured error modal."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.views.error_modal_v2 import ErrorModalV2
from src.gui.theme_v2 import BACKGROUND_DARK, BACKGROUND_ELEVATED
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope


def _make_envelope() -> UnifiedErrorEnvelope:
    return UnifiedErrorEnvelope(
        error_type="PipelineError",
        subsystem="pipeline",
        severity="ERROR",
        message="Something exploded",
        cause=None,
        stack="Traceback (most recent call last): ...",
        job_id="job-1",
        stage="TXT2IMG",
        remediation="Check configuration and retry.",
        context={"job_id": "job-1"},
    )


def test_error_modal_displays_details() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    envelope = _make_envelope()
    modal = ErrorModalV2(root, envelope=envelope)
    try:
        assert "Run Failed" in modal.title()
        assert envelope.error_type
        assert modal.cget("bg") == BACKGROUND_DARK
        text_widgets = [child for child in modal.winfo_children() if isinstance(child, tk.Text)]
        if not text_widgets:
            for child in modal.winfo_children():
                text_widgets.extend(
                    grandchild for grandchild in child.winfo_children() if isinstance(grandchild, tk.Text)
                )
        assert text_widgets
        assert all(widget.cget("bg") == BACKGROUND_ELEVATED for widget in text_widgets)
    finally:
        modal.destroy()
        root.destroy()
