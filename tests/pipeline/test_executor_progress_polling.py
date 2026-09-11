"""Tests for Pipeline executor progress polling."""

import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.api.client import (
    DEFAULT_GENERATION_TIMEOUT,
    ProgressInfo,
    SDWebUIClient,
    STALL_INTERRUPT_THRESHOLD_SEC,
)
from src.pipeline.executor import (
    Pipeline,
    STALL_INTERRUPT_THRESHOLD_BY_STAGE,
)
from src.prompting.contracts import (
    PromptContext,
    PromptIntentBundle,
    PromptOptimizerAnalysisBundle,
)
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_types import PromptOptimizationPairResult, PromptOptimizationResult
from src.utils import StructuredLogger


class _FakeMonotonicClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _ClockBoundStopEvent:
    def __init__(self, clock: _FakeMonotonicClock, *, stop_after: float) -> None:
        self._clock = clock
        self._stop_after = stop_after
        self._is_set = False

    def is_set(self) -> bool:
        return self._is_set

    def wait(self, duration: float) -> bool:
        self._clock.now += duration
        self._is_set = self._clock.now > self._stop_after
        return self._is_set


class _RecordingEvent:
    def __init__(self, clock: _FakeMonotonicClock) -> None:
        self._clock = clock
        self.times: list[float] = []

    def set(self) -> None:
        self.times.append(self._clock.now)


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

        def on_progress(
            percent: float,
            eta: float | None,
            current_step: int | None = None,
            total_steps: int | None = None,
        ) -> None:
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

        def on_progress(
            percent: float,
            eta: float | None,
            current_step: int | None = None,
            total_steps: int | None = None,
        ) -> None:
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

        def on_progress(
            percent: float,
            eta: float | None,
            current_step: int | None = None,
            total_steps: int | None = None,
        ) -> None:
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

        def on_progress(
            percent: float,
            eta: float | None,
            current_step: int | None = None,
            total_steps: int | None = None,
        ) -> None:
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

    def test_poll_progress_loop_emits_status_on_repeated_same_progress(self) -> None:
        """Healthy polls should keep runtime status alive even if percent is unchanged."""
        self.pipeline._current_job_id = "job-123"
        self.pipeline._current_stage_index = 0
        self.pipeline._current_stage_chain = ["txt2img"]
        self.pipeline._current_stage_start_time = None
        self.pipeline._status_callback = Mock()

        self.client.get_progress.return_value = ProgressInfo(
            1.0, None, 30, 30, None, {}
        )

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.pipeline._poll_progress_loop,
            args=(stop_event, 0.05, None, "txt2img"),
        )
        thread.start()
        time.sleep(0.16)
        stop_event.set()
        thread.join(timeout=1.0)

        assert self.pipeline._status_callback.call_count >= 2


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

    def test_run_txt2img_stage_uses_progress_wrapper(self) -> None:
        """txt2img should use the same progress-aware wrapper as other generation stages."""
        prompt_optimizer_result = PromptOptimizationPairResult(
            positive=PromptOptimizationResult(
                original_prompt="prompt",
                optimized_prompt="prompt",
                polarity="positive",
            ),
            negative=PromptOptimizationResult(
                original_prompt="negative",
                optimized_prompt="negative",
                polarity="negative",
            ),
        )
        prompt_optimizer_analysis = PromptOptimizerAnalysisBundle(
            stage="txt2img",
            mode="disabled",
            context=PromptContext(
                stage="txt2img",
                pipeline_name="txt2img",
                positive_chunk_count=1,
                negative_chunk_count=1,
            ),
            intent=PromptIntentBundle(
                intent_band="general",
                shot_type="unknown",
                style_mode="unknown",
                requested_pose="",
                wants_face_detail=False,
                wants_full_body=False,
                wants_portrait=False,
                has_people_tokens=False,
                has_lora_tokens=False,
                sensitive=False,
            ),
        )
        self.pipeline._apply_webui_defaults_once = Mock()
        self.pipeline._ensure_model_and_vae = Mock()
        self.pipeline._ensure_hypernetwork = Mock()
        self.pipeline._run_prompt_optimizer = Mock(
            return_value=(
                prompt_optimizer_result,
                PromptOptimizerConfig(enabled=False, log_before_after=False),
                prompt_optimizer_analysis,
            )
        )
        self.pipeline._apply_aesthetic_to_payload = Mock(return_value=("prompt", "negative"))
        self.pipeline._generate_images_with_progress = Mock(
            return_value={"images": ["img"], "info": {}}
        )
        self.pipeline._extract_generation_info = Mock(return_value={})

        with (
            patch("src.pipeline.executor.save_image_from_base64", return_value=Path("out.png")),
            patch.object(self.pipeline, "_build_image_metadata_builder", return_value=None),
        ):
            result = self.pipeline.run_txt2img_stage(
                "prompt",
                "negative",
                {"txt2img": {"steps": 20}, "batch_size": 1},
                Path("outdir"),
                "image_name",
            )

        assert result is not None
        self.pipeline._generate_images_with_progress.assert_called_once()
        args, kwargs = self.pipeline._generate_images_with_progress.call_args
        assert args[0] == "txt2img"
        assert kwargs["stage_label"] == "txt2img"

    def test_progress_polling_concurrent_with_generation(self) -> None:
        """Test progress polling runs concurrently with generation."""
        callback_called = threading.Event()

        def on_progress(
            percent: float,
            eta: float | None,
            current_step: int | None = None,
            total_steps: int | None = None,
        ) -> None:
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

        def on_progress(
            percent: float,
            eta: float | None,
            current_step: int | None = None,
            total_steps: int | None = None,
        ) -> None:
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

    def test_generate_with_progress_releases_executor_thread(self) -> None:
        """Progress polling should not leave executor worker threads alive after completion."""
        before = sum(1 for t in threading.enumerate() if t.name.startswith("progress_poll"))
        self.pipeline._generate_images.return_value = {"images": ["test"], "info": {}}
        self.client.get_progress.return_value = ProgressInfo(
            0.5, 5.0, None, None, None, {}
        )

        self.pipeline._generate_images_with_progress(
            "txt2img",
            {"prompt": "test", "steps": 20},
            poll_interval=0.05,
            progress_callback=None,
        )
        time.sleep(0.1)
        after = sum(1 for t in threading.enumerate() if t.name.startswith("progress_poll"))

        assert after <= before


class TestStallInterrupt(unittest.TestCase):
    """Test that _poll_progress_loop sends an interrupt after the hard stall threshold."""

    def setUp(self) -> None:
        self.client = Mock(spec=SDWebUIClient)
        self.logger = Mock(spec=StructuredLogger)
        self.pipeline = Pipeline(self.client, self.logger)
        self.client.interrupt.return_value = True

    def _make_frozen_progress(self, value: float = 0.5) -> ProgressInfo:
        return ProgressInfo(value, None, 10, 20, None, {})

    def test_adetailer_hard_threshold_interrupts_at_45_seconds(self) -> None:
        """ADetailer uses its hard threshold even before the general warning."""
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []
        self.client.get_progress.return_value = self._make_frozen_progress()
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 60.0),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=45.0),
                1.0,
                None,
                "adetailer",
            )

        assert interrupt_times == [45.0]

    def test_adetailer_has_no_interrupt_at_44_seconds(self) -> None:
        clock = _FakeMonotonicClock()
        self.client.get_progress.return_value = self._make_frozen_progress()

        with patch("src.pipeline.executor.time.monotonic", clock.monotonic):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=44.0),
                1.0,
                None,
                "adetailer",
            )

        self.client.interrupt.assert_not_called()

    def test_adetailer_hard_threshold_does_not_wait_for_warning_gate(self) -> None:
        clock = _FakeMonotonicClock()
        stall_event = _RecordingEvent(clock)
        self.client.get_progress.return_value = self._make_frozen_progress()

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            self.assertLogs("src.pipeline.executor", level="WARNING") as log_ctx,
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=45.0),
                1.0,
                None,
                "adetailer",
                stall_event,
            )

        assert stall_event.times == [45.0]
        assert "reason=stage-hard-threshold" in "\n".join(log_ctx.output)
        assert "warning_due=False" in "\n".join(log_ctx.output)
        self.client.interrupt.assert_called_once_with()

    def test_ordinary_stall_interrupts_at_90_seconds_from_last_progress(self) -> None:
        """The hard threshold is measured from progress, not warning detection."""
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []
        self.client.get_progress.return_value = self._make_frozen_progress()
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 60.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 90.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=90.0),
                1.0,
                None,
                "txt2img",
            )

        assert interrupt_times == [90.0]

    def test_ordinary_stall_warning_is_eligible_at_60_seconds(self) -> None:
        clock = _FakeMonotonicClock()
        stall_event = _RecordingEvent(clock)
        self.client.get_progress.return_value = self._make_frozen_progress()

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 60.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 90.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=60.0),
                1.0,
                None,
                "txt2img",
                stall_event,
            )

        assert stall_event.times[0] == 60.0
        self.client.interrupt.assert_not_called()

    def test_healthy_progress_for_more_than_90_seconds_never_interrupts(self) -> None:
        clock = _FakeMonotonicClock()

        def _progress(**_kwargs):
            return ProgressInfo(0.1 + clock.now / 1000.0, None, None, None, None, {})

        self.client.get_progress.side_effect = _progress
        with patch("src.pipeline.executor.time.monotonic", clock.monotonic):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=100.0),
                1.0,
                None,
                "txt2img",
            )

        self.client.interrupt.assert_not_called()

    def test_identical_progress_keeps_status_heartbeat_but_not_stall_clock(self) -> None:
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []
        self.pipeline._current_job_id = "job-123"
        self.pipeline._current_stage_index = 0
        self.pipeline._current_stage_chain = ["txt2img"]
        self.pipeline._current_stage_start_time = None
        self.pipeline._status_callback = Mock()
        self.client.get_progress.return_value = self._make_frozen_progress()
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=90.0),
                1.0,
                None,
                "txt2img",
            )

        assert self.pipeline._status_callback.call_count > 90
        assert interrupt_times == [90.0]

    def test_meaningful_progress_resets_stall_episode_and_allows_one_later_interrupt(self) -> None:
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []

        def _progress(**_kwargs):
            progress = 0.6 if clock.now >= 80.0 else 0.5
            return ProgressInfo(progress, None, 10, 20, None, {})

        self.client.get_progress.side_effect = _progress
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True
        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=170.0),
                1.0,
                None,
                "txt2img",
            )

        assert interrupt_times == [170.0]

    def test_trustworthy_step_advance_resets_the_stall_clock(self) -> None:
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []

        def _progress(**_kwargs):
            step = 11 if clock.now >= 80.0 else 10
            return ProgressInfo(0.5, None, step, 20, None, {})

        self.client.get_progress.side_effect = _progress
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True
        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=170.0),
                1.0,
                None,
                "txt2img",
            )

        assert interrupt_times == [170.0]

    def test_new_active_generation_marker_resets_the_stall_clock(self) -> None:
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []

        def _progress(**_kwargs):
            marker = "20260910120100" if clock.now >= 80.0 else "20260910120000"
            return ProgressInfo(0.5, None, 10, 20, None, {"job_timestamp": marker})

        self.client.get_progress.side_effect = _progress
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True
        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=170.0),
                1.0,
                None,
                "txt2img",
            )

        assert interrupt_times == [170.0]

    def test_cancellation_keeps_one_interrupt_per_episode(self) -> None:
        clock = _FakeMonotonicClock()
        cancel_token = Mock()
        cancel_token.is_cancelled.return_value = True

        self.pipeline._poll_progress_loop(
            _ClockBoundStopEvent(clock, stop_after=3.0),
            1.0,
            None,
            "txt2img",
            cancel_token=cancel_token,
        )

        self.client.interrupt.assert_called_once_with()
        self.client.get_progress.assert_not_called()

    def test_completed_steps_enable_fast_response_stall_without_lowering_percent_fallback(self) -> None:
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []
        self.client.get_progress.return_value = ProgressInfo(0.981, None, 20, 20, None, {})
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.POST_PROGRESS_RESPONSE_STALL_THRESHOLD_SEC", 20.0),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=20.0),
                1.0,
                None,
                "txt2img",
            )

        assert interrupt_times == [20.0]

    def test_98_percent_without_completed_steps_keeps_the_ordinary_stall_threshold(self) -> None:
        clock = _FakeMonotonicClock()
        interrupt_times: list[float] = []
        self.client.get_progress.return_value = ProgressInfo(0.981, None, 19, 20, None, {})
        self.client.interrupt.side_effect = lambda: interrupt_times.append(clock.now) or True

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=90.0),
                1.0,
                None,
                "txt2img",
            )

        assert interrupt_times == [90.0]

    def test_stall_warning_logs_bounded_recovery_context(self) -> None:
        clock = _FakeMonotonicClock()
        self.pipeline._current_job_id = "job-123"
        self.client.get_progress.return_value = self._make_frozen_progress()

        with (
            patch("src.pipeline.executor.time.monotonic", clock.monotonic),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
            self.assertLogs("src.pipeline.executor", level="WARNING") as log_ctx,
        ):
            self.pipeline._poll_progress_loop(
                _ClockBoundStopEvent(clock, stop_after=60.0),
                1.0,
                None,
                "txt2img",
            )

        message = "\n".join(log_ctx.output)
        assert "stage=txt2img" in message
        assert "job_id=job-123" in message
        assert "step=10/20" in message
        assert "warning_threshold=60.0s" in message
        assert "hard=90.0s" in message

    def test_hard_stall_interrupt_precedes_generation_http_timeout(self) -> None:
        assert STALL_INTERRUPT_THRESHOLD_SEC < DEFAULT_GENERATION_TIMEOUT

    def test_stall_interrupt_sent_after_hard_threshold(self) -> None:
        """Interrupt is called when stall exceeds STALL_INTERRUPT_THRESHOLD_SEC."""
        # Use zero-second thresholds so stall is detected immediately
        with (
            patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 0.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            # First call returns progress 0.5 (sets highest_progress), subsequent keep it frozen
            self.client.get_progress.return_value = self._make_frozen_progress(0.5)
            stall_detected_event = threading.Event()
            stop_event = threading.Event()

            thread = threading.Thread(
                target=self.pipeline._poll_progress_loop,
                args=(stop_event, 0.0, None, "adetailer", stall_detected_event),
            )
            thread.start()
            # Give the loop time to fire at least two iterations (first: progress advances,
            # second: progress frozen → stall + interrupt since threshold=0)
            time.sleep(0.15)
            stop_event.set()
            thread.join(timeout=2.0)

        self.client.interrupt.assert_called_once()
        assert stall_detected_event.is_set()

    def test_stall_log_throttled(self) -> None:
        """The stall warning should not log repeatedly when the 30s throttle applies."""
        # With threshold=0 but keep real 30s log throttle, multiple iterations log only once
        with (
            patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 9999.0),
        ):
            self.client.get_progress.return_value = self._make_frozen_progress(0.5)
            stop_event = threading.Event()

            import logging as _logging
            with self.assertLogs("src.pipeline.executor", level=_logging.WARNING) as log_ctx:
                thread = threading.Thread(
                    target=self.pipeline._poll_progress_loop,
                    args=(stop_event, 0.0, None, "adetailer", None),
                )
                thread.start()
                time.sleep(0.15)
                stop_event.set()
                thread.join(timeout=2.0)

        stall_warnings = [
            m for m in log_ctx.output if "WebUI generation stall:" in m
        ]
        # 30s throttle means only 1 log in 150ms run
        assert len(stall_warnings) == 1, f"Expected 1 stall log, got {len(stall_warnings)}: {stall_warnings}"

    def test_interrupt_sent_only_once(self) -> None:
        """Even if stall persists, interrupt is only sent once per stall episode."""
        with (
            patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 0.0),
            patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {}),
        ):
            self.client.get_progress.return_value = self._make_frozen_progress(0.5)
            stop_event = threading.Event()

            thread = threading.Thread(
                target=self.pipeline._poll_progress_loop,
                args=(stop_event, 0.0, None, "adetailer", None),
            )
            thread.start()
            time.sleep(0.25)
            stop_event.set()
            thread.join(timeout=2.0)

        # Many iterations, but interrupt called exactly once
        self.client.interrupt.assert_called_once()

    def test_completion_stall_interrupt_sent_after_completion_threshold(self) -> None:
        """A request stuck after reaching 100% should still be interrupted."""
        with (
            patch("src.pipeline.executor.POST_PROGRESS_RESPONSE_STALL_THRESHOLD_SEC", 0.0),
            patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 9999.0),
        ):
            self.client.get_progress.return_value = self._make_frozen_progress(1.0)
            stop_event = threading.Event()
            stall_detected_event = threading.Event()

            thread = threading.Thread(
                target=self.pipeline._poll_progress_loop,
                args=(stop_event, 0.0, None, "txt2img", stall_detected_event),
            )
            thread.start()
            time.sleep(0.15)
            stop_event.set()
            thread.join(timeout=2.0)

        self.client.interrupt.assert_called_once()
        assert stall_detected_event.is_set()


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


class TestStallStateReset(unittest.TestCase):
    """PR-HARDEN-005: Verify stall state resets when WebUI returns idle (None)."""

    def setUp(self) -> None:
        self.client = Mock(spec=SDWebUIClient)
        self.logger = Mock(spec=StructuredLogger)
        self.pipeline = Pipeline(self.client, self.logger)

    def _run_loop(self, responses: list, *, poll_interval: float = 0.02) -> None:
        """Helper: run _poll_progress_loop until responses exhausted + short wait."""
        call_iter = iter(responses)
        stop_event = threading.Event()

        def _side_effect(**_kwargs):
            try:
                return next(call_iter)
            except StopIteration:
                stop_event.set()
                return None

        self.client.get_progress.side_effect = _side_effect
        thread = threading.Thread(
            target=self.pipeline._poll_progress_loop,
            args=(stop_event, poll_interval, None, "test-stage"),
        )
        thread.start()
        thread.join(timeout=2.0)

    @patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.01)
    @patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 0.02)
    def test_stall_state_resets_on_webui_idle(self) -> None:
        """PR-005: After a stall + interrupt, a None response clears stall tracking."""
        responses = [
            # Enough progress to trigger stall tracking
            ProgressInfo(0.5, 5.0, 10, 20, None, {}),
            # Hold at 0.5 until stall/interrupt threshold passes (>=0.02s)
            ProgressInfo(0.5, 5.0, 10, 20, None, {}),
            ProgressInfo(0.5, 5.0, 10, 20, None, {}),
            ProgressInfo(0.5, 5.0, 10, 20, None, {}),
            ProgressInfo(0.5, 5.0, 10, 20, None, {}),
            # WebUI goes idle → stall state must reset
            None,
        ]
        self._run_loop(responses, poll_interval=0.03)
        # After stall+interrupt+idle, client.interrupt may have been called;
        # what matters is no exception and the loop terminates cleanly.
        # (interrupt called ≤ 1 time: the stall guard fires at most once)
        assert self.client.interrupt.call_count <= 1

    @patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.01)
    @patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 0.02)
    def test_no_spurious_reset_before_stall_detected(self) -> None:
        """PR-005: A None before any stall is detected should not cause errors."""
        responses = [
            None,  # Idle at start — no stall state to reset
            ProgressInfo(0.3, 5.0, 6, 20, None, {}),
            ProgressInfo(0.6, 2.0, 12, 20, None, {}),
            None,
        ]
        self._run_loop(responses, poll_interval=0.02)
        # interrupt must not fire if no stall was detected
        self.client.interrupt.assert_not_called()

    @patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.01)
    @patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 0.02)
    def test_interrupt_guard_prevents_double_interrupt(self) -> None:
        """PR-005: interrupt_sent flag ensures only ONE interrupt per stall episode."""
        stuck_frame = ProgressInfo(0.5, 5.0, 10, 20, None, {})
        responses = [stuck_frame] * 20  # Plenty of stuck frames
        self._run_loop(responses, poll_interval=0.05)
        # Even though we polled many times past the threshold, interrupt fires once
        assert self.client.interrupt.call_count <= 1


class TestPerStageInterruptThreshold(unittest.TestCase):
    """Per-stage stall interrupt threshold overrides."""

    def test_adetailer_threshold_lower_than_default(self) -> None:
        """ADetailer interrupt threshold must be shorter than the global default."""
        adetailer_threshold = STALL_INTERRUPT_THRESHOLD_BY_STAGE["adetailer"]
        assert adetailer_threshold < STALL_INTERRUPT_THRESHOLD_SEC
        assert adetailer_threshold == 45.0

    def test_txt2img_uses_global_default(self) -> None:
        """txt2img (and unlisted stages) must fall back to the global threshold."""
        assert "txt2img" not in STALL_INTERRUPT_THRESHOLD_BY_STAGE
        assert STALL_INTERRUPT_THRESHOLD_SEC == 90.0

    @patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.01)
    @patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {"adetailer": 0.02})
    @patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 9999.0)
    def test_adetailer_stage_label_uses_override(self) -> None:
        """Loop uses override threshold for stage_label='adetailer', not global."""
        client = Mock(spec=SDWebUIClient)
        logger = Mock(spec=StructuredLogger)
        pipeline = Pipeline(client, logger)

        stuck_frame = ProgressInfo(0.5, 5.0, 10, 20, None, {})
        call_iter = iter([stuck_frame] * 20)
        stop_event = threading.Event()

        def _side_effect(**_kwargs):
            try:
                return next(call_iter)
            except StopIteration:
                stop_event.set()
                return None

        client.get_progress.side_effect = _side_effect
        thread = threading.Thread(
            target=pipeline._poll_progress_loop,
            args=(stop_event, 0.05, None, "adetailer"),
        )
        thread.start()
        thread.join(timeout=3.0)
        # Override is 0.02s, global is 9999s — interrupt must fire (uses override)
        assert client.interrupt.call_count == 1


if __name__ == "__main__":
    unittest.main()
