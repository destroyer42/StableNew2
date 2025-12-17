"""Tests for WebUIAPI.wait_until_ready() polling and sleep behavior."""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.api.webui_api import WebUIAPI


class TestWaitUntilReadySuccessPath:
    """Test wait_until_ready succeeds after polling."""

    def test_returns_true_when_ready_on_third_attempt(self):
        """Verify wait_until_ready polls and returns True when API becomes ready."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(side_effect=[False, False, True])

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=6, base_delay=1.0, max_delay=8.0)

        assert result is True
        assert mock_client.check_api_ready.call_count == 3
        assert len(sleep_calls) == 2  # Sleep between attempt 1→2 and 2→3
        assert sleep_calls[0] == 1.0  # base_delay
        assert sleep_calls[1] == 2.0  # doubled

    def test_returns_false_when_never_ready(self):
        """Verify wait_until_ready returns False when API never becomes ready."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=False)

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=3, base_delay=0.5, max_delay=4.0)

        assert result is False
        assert mock_client.check_api_ready.call_count == 3
        assert len(sleep_calls) == 2  # Sleep after attempt 1 and 2, not after 3 (final)
        assert sleep_calls[0] == 0.5  # base_delay
        assert sleep_calls[1] == 1.0  # doubled (0.5 * 2)

    def test_exponential_backoff_respects_max_delay(self):
        """Verify exponential backoff does not exceed max_delay."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=False)

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=5, base_delay=1.0, max_delay=2.0)

        assert result is False
        assert len(sleep_calls) == 4
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 2.0  # capped at max_delay
        assert sleep_calls[2] == 2.0  # capped at max_delay
        assert sleep_calls[3] == 2.0  # capped at max_delay


class TestWaitUntilReadyExceptionHandling:
    """Test wait_until_ready handles exceptions gracefully."""

    def test_handles_exception_on_first_attempt_then_succeeds(self):
        """Verify wait_until_ready continues after exception on first attempt."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(side_effect=[RuntimeError("connection error"), True])

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=3, base_delay=0.1, max_delay=1.0)

        assert result is True
        assert mock_client.check_api_ready.call_count == 2
        assert len(sleep_calls) == 1  # One sleep between attempts

    def test_handles_all_exceptions_returns_false(self):
        """Verify wait_until_ready returns False when all attempts raise exceptions."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(side_effect=RuntimeError("always fails"))

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=2, base_delay=0.1, max_delay=1.0)

        assert result is False
        assert mock_client.check_api_ready.call_count == 2
        assert len(sleep_calls) == 1  # One sleep between first and second attempt


class TestWaitUntilReadySleepIntegration:
    """Test that _sleep method is called correctly."""

    def test_sleep_method_is_invoked_not_missing(self):
        """Verify _sleep() method exists and is called (AttributeError regression test)."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=False)

        api = WebUIAPI(client=mock_client)

        # This should not raise AttributeError: 'WebUIAPI' object has no attribute '_sleep'
        with patch.object(api, "_sleep") as mock_sleep:
            result = api.wait_until_ready(max_attempts=2, base_delay=0.1, max_delay=1.0)

        assert result is False
        assert mock_sleep.call_count == 1  # Sleep called after first attempt


class TestWaitUntilReadyEdgeCases:
    """Test edge cases in wait_until_ready."""

    def test_single_attempt_failure(self):
        """Verify wait_until_ready works with max_attempts=1."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=False)

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=1, base_delay=1.0, max_delay=8.0)

        assert result is False
        assert mock_client.check_api_ready.call_count == 1
        assert len(sleep_calls) == 0  # No sleep after single final attempt

    def test_single_attempt_success(self):
        """Verify wait_until_ready succeeds immediately with max_attempts=1."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(return_value=True)

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=1, base_delay=1.0, max_delay=8.0)

        assert result is True
        assert mock_client.check_api_ready.call_count == 1
        assert len(sleep_calls) == 0  # No sleep needed

    def test_zero_base_delay(self):
        """Verify wait_until_ready works with zero base_delay."""
        mock_client = Mock()
        mock_client.check_api_ready = Mock(side_effect=[False, False, True])

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("time.sleep", side_effect=track_sleep):
            api = WebUIAPI(client=mock_client)
            result = api.wait_until_ready(max_attempts=6, base_delay=0.0, max_delay=1.0)

        assert result is True
        assert sleep_calls[0] == 0.0  # base_delay is 0
