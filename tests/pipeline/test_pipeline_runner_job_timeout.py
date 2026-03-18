"""
PR-HARDEN-008: Tests for the per-job wall-clock timeout ceiling in PipelineRunner.

Covers:
- DEFAULT_JOB_TIMEOUT_SEC constant is present and reasonable
- PipelineJobTimeoutError is raised when elapsed time exceeds the ceiling
- The exception propagates through run_njr and surfaces as an error string (not a crash)
- _check_job_deadline does nothing when elapsed time is within budget
"""

import time
import unittest
from unittest.mock import Mock, patch

from src.pipeline.pipeline_runner import (
    DEFAULT_JOB_TIMEOUT_SEC,
    PipelineJobTimeoutError,
    PipelineRunner,
)
from src.utils import StructuredLogger


class TestJobTimeoutConstant(unittest.TestCase):
    """Verify the timeout constant is present and sensible."""

    def test_default_job_timeout_exists(self) -> None:
        assert DEFAULT_JOB_TIMEOUT_SEC > 0

    def test_default_job_timeout_is_reasonable(self) -> None:
        # Should be at least 5 minutes (300s) and no more than 2 hours (7200s).
        assert 300.0 <= DEFAULT_JOB_TIMEOUT_SEC <= 7200.0


class TestCheckJobDeadline(unittest.TestCase):
    """Unit tests for PipelineRunner._check_job_deadline."""

    def setUp(self) -> None:
        self.client = Mock()
        self.logger = Mock(spec=StructuredLogger)
        self.runner = PipelineRunner(self.client, self.logger)

    def test_no_error_within_budget(self) -> None:
        """No exception when elapsed time is small compared to ceiling."""
        job_start_time = time.monotonic()
        # Should not raise
        self.runner._check_job_deadline(job_start_time, "txt2img", timeout_sec=600.0)

    def test_raises_when_deadline_exceeded(self) -> None:
        """PipelineJobTimeoutError raised when elapsed >= timeout_sec."""
        # Travel back in time: simulate start 700s ago
        job_start_time = time.monotonic() - 700.0
        with self.assertRaises(PipelineJobTimeoutError) as cm:
            self.runner._check_job_deadline(job_start_time, "adetailer", timeout_sec=600.0)
        assert "adetailer" in str(cm.exception)
        assert "600" in str(cm.exception)

    def test_timeout_uses_default_when_not_specified(self) -> None:
        """When no timeout_sec arg is given, DEFAULT_JOB_TIMEOUT_SEC is used."""
        job_start_time = time.monotonic() - (DEFAULT_JOB_TIMEOUT_SEC + 1.0)
        with self.assertRaises(PipelineJobTimeoutError):
            self.runner._check_job_deadline(job_start_time, "upscale")

    def test_no_error_at_exactly_one_second_before_deadline(self) -> None:
        """Should not raise when 1 second remains before the deadline."""
        job_start_time = time.monotonic() - (DEFAULT_JOB_TIMEOUT_SEC - 1.0)
        # Should not raise
        self.runner._check_job_deadline(job_start_time, "txt2img")

    def test_error_message_includes_elapsed_time(self) -> None:
        """Exception message must contain elapsed duration for postmortem."""
        job_start_time = time.monotonic() - 999.0
        with self.assertRaises(PipelineJobTimeoutError) as cm:
            self.runner._check_job_deadline(job_start_time, "img2img", timeout_sec=600.0)
        msg = str(cm.exception)
        # "elapsed: 999.Xs" — just check the numeric part is plausible
        assert "elapsed" in msg.lower()


class TestJobTimeoutInRunNjr(unittest.TestCase):
    """Verify _check_job_deadline integrates correctly into run_njr."""

    def setUp(self) -> None:
        from src.api.client import SDWebUIClient
        self.client = Mock(spec=SDWebUIClient)
        self.logger = Mock(spec=StructuredLogger)
        self.runner = PipelineRunner(self.client, self.logger)

    def test_timeout_surfaces_as_error_not_exception(self) -> None:
        """PipelineJobTimeoutError must be caught by run_njr and set result.error (not re-raised)."""
        from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig

        record = NormalizedJobRecord(
            job_id="timeout-test",
            config={},
            path_output_dir="output",
            filename_template="{seed}",
            seed=1,
            variant_index=0,
            variant_total=1,
            batch_index=0,
            batch_total=1,
            created_ts=0.0,
            randomizer_summary=None,
            stage_chain=[
                StageConfig(
                    stage_type="txt2img",
                    enabled=True,
                    steps=20,
                    cfg_scale=7.5,
                    sampler_name="Euler a",
                )
            ],
        )

        # Make the deadline fire immediately on first check
        with patch.object(
            self.runner,
            "_check_job_deadline",
            side_effect=PipelineJobTimeoutError("Job exceeded 600s (elapsed: 601.0s) before stage 'txt2img'"),
        ):
            result = self.runner.run_njr(record, cancel_token=None)

        assert result.success is False
        assert result.error is not None
        assert "600" in str(result.error) or "timeout" in str(result.error).lower() or "exceeded" in str(result.error).lower()


if __name__ == "__main__":
    unittest.main()
