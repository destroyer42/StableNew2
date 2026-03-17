"""Tests for WebUIAPI.wait_until_true_ready() readiness contract."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout


class TestWaitUntilTrueReadyGate:
    """True-ready gate should require API readiness and reject clearly busy instances."""

    def test_times_out_when_endpoints_ok_without_boot_marker(self):
        """Gate must still block when API is reachable but progress is not idle."""
        client = Mock()
        api = WebUIAPI(client=client)

        poll_count = [0]
        client.check_api_ready = Mock(return_value=True)
        client._session = Mock()
        client.base_url = "http://127.0.0.1:7860"

        options_response = Mock()
        options_response.status_code = 200
        progress_response = Mock()
        progress_response.status_code = 200
        progress_response.json.return_value = {"progress": 0.5}

        get_calls = {"count": 0}

        def mock_get(*_args, **_kwargs):
            get_calls["count"] += 1
            return options_response if get_calls["count"] % 2 == 1 else progress_response

        client._session.get = Mock(side_effect=mock_get)

        def get_stdout_without_marker():
            poll_count[0] += 1
            return "Some WebUI output without any recognized boot marker"

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
        assert excinfo.value.checks_status["progress_idle"] is False
        assert poll_count[0] >= 1

    def test_succeeds_when_endpoints_ok_and_progress_idle_without_boot_marker(self):
        """Idle API should be accepted even if stdout capture missed the boot marker."""
        client = Mock()
        api = WebUIAPI(client=client)

        client.check_api_ready = Mock(return_value=True)
        client._session = Mock()
        client.base_url = "http://127.0.0.1:7860"

        options_response = Mock()
        options_response.status_code = 200
        progress_response = Mock()
        progress_response.status_code = 200
        progress_response.json.return_value = {"progress": 0.0}
        client._session.get = Mock(side_effect=[options_response, progress_response])

        with patch.object(api, "_sleep"):
            result = api.wait_until_true_ready(
                timeout_s=10.0,
                poll_interval_s=0.1,
                get_stdout_tail=lambda: "Output without markers",
            )

        assert result is True

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

        options_response = Mock()
        options_response.status_code = 200
        progress_response = Mock()
        progress_response.status_code = 200
        progress_response.json.return_value = {"progress": 0.5}
        get_calls = {"count": 0}

        def mock_get(*_args, **_kwargs):
            get_calls["count"] += 1
            return options_response if get_calls["count"] % 2 == 1 else progress_response

        client._session.get = Mock(side_effect=mock_get)

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
