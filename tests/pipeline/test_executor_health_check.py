"""
PR-HARDEN-007: Tests for post-recovery health check timeout behaviour in Pipeline.

The health check method (_check_webui_health_before_stage) must use an extended
probe timeout (POST_RECOVERY_HEALTH_CHECK_TIMEOUT_SEC) when called within
POST_RECOVERY_GRACE_WINDOW_SEC of a successful WebUI recovery.  Outside that
window it must fall back to the normal 5-second timeout.
"""

import time
import unittest
from unittest.mock import Mock, patch

from src.api.client import SDWebUIClient
from src.pipeline.executor import (
    Pipeline,
    POST_RECOVERY_GRACE_WINDOW_SEC,
    POST_RECOVERY_HEALTH_CHECK_TIMEOUT_SEC,
    PipelineStageError,
)
from src.utils import StructuredLogger


class TestPostRecoveryHealthCheckTimeout(unittest.TestCase):
    """_check_webui_health_before_stage timeout selector — PR-HARDEN-007."""

    def setUp(self) -> None:
        self.client = Mock(spec=SDWebUIClient)
        self.logger = Mock(spec=StructuredLogger)
        self.pipeline = Pipeline(self.client, self.logger)

    def test_normal_timeout_when_no_recovery(self) -> None:
        """Uses 5.0s timeout when _last_recovery_time is None."""
        self.pipeline._last_recovery_time = None
        self.client.check_connection.return_value = True

        self.pipeline._check_webui_health_before_stage("txt2img")

        args, kwargs = self.client.check_connection.call_args
        used_timeout = kwargs.get("timeout", args[0] if args else None)
        assert used_timeout == 5.0, f"Expected 5.0s timeout, got {used_timeout}"

    def test_extended_timeout_within_grace_window(self) -> None:
        """Uses POST_RECOVERY_HEALTH_CHECK_TIMEOUT_SEC within grace window."""
        self.pipeline._last_recovery_time = time.monotonic()  # Just recovered
        self.client.check_connection.return_value = True

        self.pipeline._check_webui_health_before_stage("txt2img")

        args, kwargs = self.client.check_connection.call_args
        used_timeout = kwargs.get("timeout", args[0] if args else None)
        assert used_timeout == POST_RECOVERY_HEALTH_CHECK_TIMEOUT_SEC, (
            f"Expected {POST_RECOVERY_HEALTH_CHECK_TIMEOUT_SEC}s extended timeout, "
            f"got {used_timeout}"
        )

    def test_normal_timeout_after_grace_window_expires(self) -> None:
        """Reverts to 5.0s timeout once POST_RECOVERY_GRACE_WINDOW_SEC has elapsed."""
        # Set recovery time well in the past
        self.pipeline._last_recovery_time = time.monotonic() - (POST_RECOVERY_GRACE_WINDOW_SEC + 10.0)
        self.client.check_connection.return_value = True

        self.pipeline._check_webui_health_before_stage("txt2img")

        args, kwargs = self.client.check_connection.call_args
        used_timeout = kwargs.get("timeout", args[0] if args else None)
        assert used_timeout == 5.0, (
            f"Expected 5.0s timeout after grace window, got {used_timeout}"
        )

    def test_last_recovery_time_set_on_successful_recovery(self) -> None:
        """_attempt_webui_recovery must stamp _last_recovery_time on success."""
        self.pipeline._last_recovery_time = None

        mock_manager = Mock()
        mock_manager.restart_webui.return_value = True

        with patch(
            "src.pipeline.executor.get_global_webui_process_manager",
            return_value=mock_manager,
        ):
            result = self.pipeline._attempt_webui_recovery(
                stage="txt2img", reason="test"
            )

        assert result is True
        assert self.pipeline._last_recovery_time is not None

    def test_health_check_raises_on_persistent_failure(self) -> None:
        """Raises PipelineStageError when recovery also fails."""
        self.pipeline._last_recovery_time = None
        self.client.check_connection.return_value = False

        with patch.object(self.pipeline, "_attempt_webui_recovery", return_value=False):
            with self.assertRaises(PipelineStageError):
                self.pipeline._check_webui_health_before_stage("txt2img")


if __name__ == "__main__":
    unittest.main()
