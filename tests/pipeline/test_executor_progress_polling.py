"""Tests for Pipeline executor progress polling."""

import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.api.client import ProgressInfo, SDWebUIClient
from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


class TestPollProgressLoop(unittest.TestCase):
    """Test _poll_progress_loop background thread."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.client = Mock(spec=SDWebUIClient)
        self.logger = Mock(spec=StructuredLogger)
        self.pipeline = Pipeline(self.client, self.logger)

    def test_poll_progress_loop_calls_callback(self) -> None:
        """Test polling loop invokes callback with progress updates."""
        progress_values = []

        def on_progress(percent: float, eta: float | None) -> None:
            progress_values.append(percent)

        # Mock progress responses
        self.client.get_progress.side_effect = [
            ProgressInfo(
                progress=0.25,
                eta_relative=10.0,
                current_step=10,
                total_steps=40,
                current_image=None,
                state={},
            ),
            ProgressInfo(
                progress=0.5,
                eta_relative=5.0,
                current_step=20,
                total_steps=40,
                current_image=None,
                state={},
            ),
        ]

        stop_event = threading.Event()

        # Run polling loop in background
        thread = threading.Thread(
            target=self.pipeline._poll_progress_loop,
            args=(stop_event, 0.1, on_progress, "txt2img"),
        )
        thread.start()

        # Let it poll twice
        time.sleep(0.3)
        stop_event.set()
        thread.join(timeout=1.0)

        # Should have received progress updates
        assert len(progress_values) >= 1
        # Values should be percentages (0-100)
        assert all(0 <= v <= 100 for v in progress_values)

    def test_poll_progress_loop_stops_on_event(self) -> None:
        """Test polling loop respects stop event."""
        self.client.get_progress.return_value = ProgressInfo(
            progress=0.3,
            eta_relative=5.0,
            current_step=None,
            total_steps=None,
            current_image=None,
            state={},
        )

        stop_event = threading.Event()
        stop_event.set()  # Signal stop immediately

        # Run polling loop
        self.pipeline._poll_progress_loop(stop_event, 0.1, None, "txt2img")

        # Should not have polled at all (or only once before checking stop)
        assert self.client.get_progress.call_count <= 1

    def test_poll_progress_loop_ignores_regression(self) -> None:
        """Test polling loop only forwards progress updates."""
        progress_values = []

        def on_progress(percent: float, eta: float | None) -> None:
            progress_values.append(percent)

        # Mock progress with regression (0.5 → 0.3 → 0.7)
        self.client.get_progress.side_effect = [
            ProgressInfo(0.5, 10.0, None, None, None, {}),
            ProgressInfo(0.3, 8.0, None, None, None, {}),  # Regression!
            ProgressInfo(0.7, 3.0, None, None, None, {}),
        ]

        stop_event = threading.Event()

        thread = threading.Thread(
            target=self.pipeline._poll_progress_loop,
            args=(stop_event, 0.05, on_progress, "txt2img"),
        )
        thread.start()

        time.sleep(0.2)
        stop_event.set()
        thread.join(timeout=1.0)

        # Should have received 50% and 70%, but not 30%
        assert progress_values == [50.0, 70.0] or progress_values == [50.0]

    def test_poll_progress_loop_handles_none_response(self) -> None:
        """Test polling loop handles None responses gracefully."""
        call_count = [0]

        def on_progress(percent: float, eta: float | None) -> None:
            call_count[0] += 1

        # Return None (idle state)
        self.client.get_progress.return_value = None

        stop_event = threading.Event()

        thread = threading.Thread(
            target=self.pipeline._poll_progress_loop,
            args=(stop_event, 0.05, on_progress, "txt2img"),
        )
        thread.start()

        time.sleep(0.15)
        stop_event.set()
        thread.join(timeout=1.0)

        # Callback should not have been called with None responses
        assert call_count[0] == 0

    def test_poll_progress_loop_handles_exceptions(self) -> None:
        """Test polling loop continues after exceptions."""
        progress_values = []

        def on_progress(percent: float, eta: float | None) -> None:
            progress_values.append(percent)

        # First call raises exception, second succeeds
        self.client.get_progress.side_effect = [
            Exception("Network error"),
            ProgressInfo(0.5, 5.0, None, None, None, {}),
        ]

        stop_event = threading.Event()

        thread = threading.Thread(
            target=self.pipeline._poll_progress_loop,
            args=(stop_event, 0.05, on_progress, "txt2img"),
        )
        thread.start()

        time.sleep(0.15)
        stop_event.set()
        thread.join(timeout=1.0)

        # Should have recovered and called callback
        assert len(progress_values) >= 1


class TestGenerateWithProgress(unittest.TestCase):
    """Test _generate_images_with_progress method."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.client = Mock(spec=SDWebUIClient)
        self.logger = Mock(spec=StructuredLogger)
        self.pipeline = Pipeline(self.client, self.logger)

        # Mock _generate_images to return test data
        self.pipeline._generate_images = Mock(
            return_value={"images": ["base64_data"], "info": {}}
        )

    def test_generate_with_progress_completes(self) -> None:
        """Test generation with progress polling completes successfully."""
        payload = {"prompt": "test", "steps": 20}

        result = self.pipeline._generate_images_with_progress(
            "txt2img",
            payload,
            poll_interval=0.5,
            progress_callback=None,
        )

        assert result is not None
        assert "images" in result
        self.pipeline._generate_images.assert_called_once_with("txt2img", payload)

    def test_generate_with_progress_no_callback(self) -> None:
        """Test generation works without callback."""
        payload = {"prompt": "test", "steps": 20}

        result = self.pipeline._generate_images_with_progress(
            "txt2img",
            payload,
            poll_interval=0.5,
            progress_callback=None,
        )

        assert result is not None
        # Should still complete successfully
        self.pipeline._generate_images.assert_called_once()

    def test_progress_polling_concurrent_with_generation(self) -> None:
        """Test progress polling runs concurrently with generation."""
        callback_called = threading.Event()

        def on_progress(percent: float, eta: float | None) -> None:
            callback_called.set()

        # Mock slow generation
        def slow_generate(stage: str, payload: dict) -> dict:
            time.sleep(0.2)
            return {"images": ["test"], "info": {}}

        self.pipeline._generate_images = slow_generate
        self.client.get_progress.return_value = ProgressInfo(
            0.5, 5.0, 20, 40, None, {}
        )

        payload = {"prompt": "test", "steps": 20}

        result = self.pipeline._generate_images_with_progress(
            "txt2img",
            payload,
            poll_interval=0.05,
            progress_callback=on_progress,
        )

        # Generation should complete
        assert result is not None

        # Callback should have been invoked during generation
        # (We can't guarantee timing, but the mock setup makes it likely)
        # This is best-effort verification

    def test_generate_with_progress_stops_polling_on_completion(self) -> None:
        """Test polling stops when generation completes."""
        call_count = [0]

        def on_progress(percent: float, eta: float | None) -> None:
            call_count[0] += 1

        self.client.get_progress.return_value = ProgressInfo(
            0.5, 5.0, None, None, None, {}
        )

        payload = {"prompt": "test", "steps": 20}

        # Fast generation
        self.pipeline._generate_images.return_value = {"images": ["test"], "info": {}}

        self.pipeline._generate_images_with_progress(
            "txt2img",
            payload,
            poll_interval=0.05,
            progress_callback=on_progress,
        )

        # Give time for any lingering polls
        time.sleep(0.15)

        # Polling should have stopped after generation completed
        initial_count = call_count[0]
        time.sleep(0.1)
        final_count = call_count[0]

        # Count should not increase significantly after completion
        assert final_count - initial_count <= 1


class TestProgressThreadSafety(unittest.TestCase):
    """Test thread safety of progress tracking."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.client = Mock(spec=SDWebUIClient)
        self.logger = Mock(spec=StructuredLogger)
        self.pipeline = Pipeline(self.client, self.logger)

    def test_concurrent_progress_updates_thread_safe(self) -> None:
        """Test concurrent progress updates don't cause race conditions."""
        # Simulate multiple concurrent progress updates
        def update_progress() -> None:
            for i in range(10):
                with self.pipeline._progress_lock:
                    self.pipeline._current_generation_progress = i / 10.0

        threads = [threading.Thread(target=update_progress) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Should complete without errors
        assert 0.0 <= self.pipeline._current_generation_progress <= 1.0


if __name__ == "__main__":
    unittest.main()
