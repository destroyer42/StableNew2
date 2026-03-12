"""Tests for WebUIAPI.wait_until_true_ready() strict readiness contract.

The true-ready gate must require both API endpoint readiness and a recognizable
boot marker when stdout is available.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout


class TestWaitUntilTrueReadyStrictGate:
    """True-ready gate should require both API readiness and boot marker."""

    def test_times_out_when_endpoints_ok_without_boot_marker(self):
        """Gate must not return successfully when the boot marker never appears."""
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
            with pytest.raises(WebUIReadinessTimeout) as excinfo:
                api.wait_until_true_ready(
                    timeout_s=0.1,
                    poll_interval_s=0.01,
                    get_stdout_tail=get_stdout_without_marker,
                )

        assert excinfo.value.checks_status["models_endpoint"] is True
        assert excinfo.value.checks_status["options_endpoint"] is True
        assert excinfo.value.checks_status["boot_marker_found"] is False
        assert poll_count[0] >= 1

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
                    with pytest.raises(WebUIReadinessTimeout) as excinfo:
                        api.wait_until_true_ready(
                            timeout_s=10.0,
                            poll_interval_s=0.1,
                            get_stdout_tail=get_stdout,
                        )

        assert excinfo.value.checks_status is not None
        assert excinfo.value.checks_status.get("models_endpoint") is False

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

        with patch.object(api, "_sleep"):
            with pytest.raises(WebUIReadinessTimeout) as excinfo:
                api.wait_until_true_ready(
                    timeout_s=0.1,
                    poll_interval_s=0.01,
                    get_stdout_tail=get_stdout,
                )

        assert excinfo.value.checks_status["boot_marker_found"] is False
        assert "boot_marker_found" in str(excinfo.value.checks_status)

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

        assert result is True

    def test_partial_endpoint_failure_still_waits(self):
        """If one endpoint fails, gate continues polling until endpoints and marker all pass."""
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
            return "Loading...\nStartup time: 5s"

        with patch.object(api, "_sleep"):
            result = api.wait_until_true_ready(
                timeout_s=10.0,
                poll_interval_s=0.1,
                get_stdout_tail=get_stdout,
            )

        # Should succeed once options endpoint recovers
        assert result is True
        assert poll_count[0] >= 3
