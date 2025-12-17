"""Tests for WebUIAPI.wait_until_true_ready() gate relaxation (PR-CORE1-D11F).

Tests that the true-ready gate returns once API endpoints (models + options) are
responsive, and does NOT require stdout boot markers (which may be version-specific).
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout


class TestWaitUntilTrueReadyRelaxedGate:
    """True-ready gate should accept API readiness without boot marker."""

    def test_returns_when_endpoints_ok_without_boot_marker(self):
        """Gate returns successfully when models/options OK, even if boot marker never appears."""
        client = Mock()
        api = WebUIAPI(client=client)

        # Setup: models and options endpoints respond, but boot marker is never found
        poll_count = [0]

        def mock_check_api_ready():
            return True

        client.check_api_ready = mock_check_api_ready
        client._session = Mock()
        client.base_url = "http://127.0.0.1:7860"

        # Options endpoint returns 200
        mock_response = Mock()
        mock_response.status_code = 200
        client._session.get = Mock(return_value=mock_response)

        # stdout callback never returns boot marker
        def get_stdout_without_marker():
            poll_count[0] += 1
            return "Some WebUI output without any recognized boot marker"

        # Patch sleep to avoid real delays
        with patch.object(api, "_sleep"):
            # Should return after first poll cycle (API ready, no wait for marker)
            result = api.wait_until_true_ready(
                timeout_s=10.0,
                poll_interval_s=0.1,
                get_stdout_tail=get_stdout_without_marker,
            )

        assert result is True
        # Should have returned quickly without excessive polls
        assert poll_count[0] <= 3

    def test_still_times_out_when_endpoints_not_ok(self):
        """Gate still respects timeout if API endpoints are not responsive."""
        client = Mock()
        api = WebUIAPI(client=client)

        # Setup: models endpoint fails
        client.check_api_ready = Mock(return_value=False)
        client._session = Mock()
        client.base_url = "http://127.0.0.1:7860"

        # Options endpoint fails too
        mock_response = Mock()
        mock_response.status_code = 500
        client._session.get = Mock(return_value=mock_response)

        def get_stdout():
            return "Still loading..."

        # Patch sleep and time to avoid real delays
        with patch.object(api, "_sleep"):
            with patch("src.api.webui_api.time") as mock_time:
                # Use a lambda to simulate time advancing: start at 0, increment by 2 each call
                current_time = [0.0]

                def time_side_effect():
                    result = current_time[0]
                    current_time[0] += 2.0
                    return result

                mock_time.time.side_effect = time_side_effect
                with patch("src.api.webui_api.logger"):
                    try:
                        api.wait_until_true_ready(
                            timeout_s=10.0,
                            poll_interval_s=0.1,
                            get_stdout_tail=get_stdout,
                        )
                        assert False, "Should have raised WebUIReadinessTimeout"
                    except WebUIReadinessTimeout as e:
                        # Should still include checks_status in exception
                        assert e.checks_status is not None
                        assert e.checks_status.get("models_endpoint") is False

    def test_error_message_includes_boot_marker_status(self):
        """On timeout, error includes boot_marker_found status for diagnostics."""
        client = Mock()
        api = WebUIAPI(client=client)

        # Setup: endpoints OK but boot marker never found, and we'll force a timeout
        client.check_api_ready = Mock(return_value=True)
        client._session = Mock()
        client.base_url = "http://127.0.0.1:7860"

        mock_response = Mock()
        mock_response.status_code = 200
        client._session.get = Mock(return_value=mock_response)

        def get_stdout():
            return "Output without markers"

        # Force immediate return (since API is ready)
        with patch.object(api, "_sleep"):
            result = api.wait_until_true_ready(
                timeout_s=10.0,
                poll_interval_s=0.1,
                get_stdout_tail=get_stdout,
            )

        # Should succeed (endpoints OK)
        assert result is True

    def test_no_stdout_callback_assumes_marker_present(self):
        """When no stdout callback provided, gate assumes boot marker present."""
        client = Mock()
        api = WebUIAPI(client=client)

        client.check_api_ready = Mock(return_value=True)
        client._session = Mock()
        client.base_url = "http://127.0.0.1:7860"

        mock_response = Mock()
        mock_response.status_code = 200
        client._session.get = Mock(return_value=mock_response)

        with patch.object(api, "_sleep"):
            result = api.wait_until_true_ready(
                timeout_s=10.0,
                poll_interval_s=0.1,
                get_stdout_tail=None,  # No callback
            )

        # Should return successfully (endpoints OK, boot marker assumed)
        assert result is True

    def test_partial_endpoint_failure_still_waits(self):
        """If one endpoint fails, gate continues polling until both OK or timeout."""
        client = Mock()
        api = WebUIAPI(client=client)

        # Models OK, options fails initially then succeeds
        client.check_api_ready = Mock(return_value=True)
        client._session = Mock()
        client.base_url = "http://127.0.0.1:7860"

        poll_count = [0]

        def mock_get(*args, **kwargs):
            poll_count[0] += 1
            # Fail first 2 times, then succeed
            if poll_count[0] <= 2:
                raise Exception("Connection refused")
            mock_response = Mock()
            mock_response.status_code = 200
            return mock_response

        client._session.get = mock_get

        def get_stdout():
            return "Loading..."

        with patch.object(api, "_sleep"):
            result = api.wait_until_true_ready(
                timeout_s=10.0,
                poll_interval_s=0.1,
                get_stdout_tail=get_stdout,
            )

        # Should succeed once options endpoint recovers
        assert result is True
        assert poll_count[0] >= 3
