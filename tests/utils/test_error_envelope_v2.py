"""Tests for the Unified Error Envelope utilities."""

from __future__ import annotations

from src.utils.error_envelope_v2 import UnifiedErrorEnvelope, wrap_exception
from src.utils.exceptions_v2 import PipelineError


def test_wrap_exception_captures_stack_trace() -> None:
    try:
        raise PipelineError("boom")
    except PipelineError as exc:
        envelope = wrap_exception(exc, subsystem="pipeline", job_id="job-1", stage="TXT2IMG")
    assert isinstance(envelope, UnifiedErrorEnvelope)
    assert envelope.subsystem == "pipeline"
    assert envelope.job_id == "job-1"
    assert envelope.stage == "TXT2IMG"
    assert "PipelineError" in envelope.stack
    assert envelope.remediation is not None


def test_wrap_exception_includes_context() -> None:
    exc = ValueError("bad")
    envelope = wrap_exception(
        exc,
        subsystem="executor",
        message="bad request",
        context={"stage": "img2img"},
    )
    assert envelope.message == "bad request"
    assert envelope.context["stage"] == "img2img"
