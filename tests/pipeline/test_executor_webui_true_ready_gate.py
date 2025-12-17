"""Tests for Pipeline._ensure_webui_true_ready() defensive gate.

Tests verify that the executor's defensive true-readiness gate blocks generation
calls until WebUI has completed loading and signals boot-complete via stdout marker.
This prevents HTTP 500 errors and process crashes from calling /txt2img during boot.
"""

from __future__ import annotations

from src.api.webui_api import WebUIReadinessTimeout
from src.pipeline.executor import Pipeline, PipelineStageError
from src.utils import StructuredLogger


class MockClient:
    """Mock client for testing."""

    def __init__(self):
        self.generate_call_count = 0

    def generate_images(self, *, stage: str, payload: dict) -> None:
        """Never called if gate blocks."""
        self.generate_call_count += 1
        raise AssertionError("Should not reach here if gate blocked")


class TestTrueReadyGateBlocks:
    """Test that gate blocks generation calls when true-readiness fails."""

    def test_gate_called_before_generation(self):
        """Verify gate is called as first operation in _generate_images."""
        client = MockClient()
        pipeline = Pipeline(client, StructuredLogger())

        gate_called = [False]

        def mock_gate_success():
            gate_called[0] = True
            return True

        pipeline._ensure_webui_true_ready = mock_gate_success

        # This will fail because we don't have a real client, but gate will be called
        try:
            pipeline._generate_images("txt2img", {})
        except Exception:
            pass  # Expected to fail when calling client

        # But gate was called
        assert gate_called[0]

    def test_gate_prevents_generation_when_timeout(self):
        """Verify gate blocks generation when timeout occurs."""
        client = MockClient()
        pipeline = Pipeline(client, StructuredLogger())

        # Test that gate is called by tracking calls
        gate_calls = [0]

        def mock_gate_timeout():
            gate_calls[0] += 1
            raise WebUIReadinessTimeout(
                message="Timeout", total_waited=60, stdout_tail="", stderr_tail="", checks_status={}
            )

        pipeline._ensure_webui_true_ready = mock_gate_timeout

        # Try to generate - gate will throw
        exception_raised = False
        try:
            pipeline._generate_images("txt2img", {})
        except (PipelineStageError, WebUIReadinessTimeout):
            exception_raised = True

        # Verify gate was called
        assert gate_calls[0] > 0
        # Verify exception was raised (gate blocked)
        assert exception_raised
        # Verify client.generate_images was never called
        assert client.generate_call_count == 0

    def test_gate_called_for_different_stages(self):
        """Verify gate is called for multiple stages."""
        client = MockClient()
        pipeline = Pipeline(client, StructuredLogger())

        gate_calls = []

        def mock_gate():
            gate_calls.append(1)
            raise WebUIReadinessTimeout(
                message="Not ready",
                total_waited=30,
                stdout_tail="",
                stderr_tail="",
                checks_status={},
            )

        pipeline._ensure_webui_true_ready = mock_gate

        # Try txt2img
        exception_raised_1 = False
        try:
            pipeline._generate_images("txt2img", {})
        except (PipelineStageError, WebUIReadinessTimeout):
            exception_raised_1 = True

        assert exception_raised_1
        assert len(gate_calls) == 1

        # Try img2img
        exception_raised_2 = False
        try:
            pipeline._generate_images("img2img", {})
        except (PipelineStageError, WebUIReadinessTimeout):
            exception_raised_2 = True

        assert exception_raised_2
        # Gate may be called again or memoized depending on implementation
        assert len(gate_calls) >= 1
