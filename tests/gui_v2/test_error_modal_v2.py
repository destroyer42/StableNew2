"""GUI tests for the structured error modal."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.views.error_modal_v2 import ErrorModalV2
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
        content = modal.children.values()
        assert envelope.error_type
    finally:
        modal.destroy()
        root.destroy()
