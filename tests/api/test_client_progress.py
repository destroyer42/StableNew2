"""Tests for SDWebUIClient progress polling."""

import unittest
from unittest.mock import Mock, patch

import requests

from src.api.client import ProgressInfo, SDWebUIClient


class TestProgressInfo(unittest.TestCase):
    """Test ProgressInfo dataclass."""

    def test_from_response_parses_valid_data(self) -> None:
        """Test parsing valid progress response."""
        data = {
            "progress": 0.45,
            "eta_relative": 12.5,
            "state": {
                "sampling_step": 18,
                "sampling_steps": 40,
                "job": "txt2img",
            },
            "current_image": "base64_image_data",
        }

        info = ProgressInfo.from_response(data)

        assert info.progress == 0.45
        assert info.eta_relative == 12.5
        assert info.current_step == 18
        assert info.total_steps == 40
        assert info.current_image == "base64_image_data"
        assert info.state["job"] == "txt2img"

    def test_from_response_handles_missing_fields(self) -> None:
        """Test parsing response with missing optional fields."""
        data = {
            "progress": 0.2,
            "eta_relative": 5.0,
            "state": {},
        }

        info = ProgressInfo.from_response(data)

        assert info.progress == 0.2
        assert info.eta_relative == 5.0
        assert info.current_step is None
        assert info.total_steps is None
        assert info.current_image is None

    def test_from_response_handles_zero_progress(self) -> None:
        """Test parsing response with zero progress (idle state)."""
        data = {
            "progress": 0.0,
            "eta_relative": 0.0,
            "state": {},
        }

        info = ProgressInfo.from_response(data)

        assert info.progress == 0.0
        assert info.eta_relative == 0.0


class TestGetProgress(unittest.TestCase):
    """Test SDWebUIClient.get_progress method."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.client = SDWebUIClient(
            base_url="http://127.0.0.1:7860",
            timeout=10,
        )

    def test_get_progress_returns_progress_info(self) -> None:
        """Test get_progress returns ProgressInfo when generation in progress."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "progress": 0.5,
            "eta_relative": 10.0,
            "state": {
                "sampling_step": 20,
                "sampling_steps": 40,
                "job": "txt2img",
            },
        }

        with patch.object(self.client._session, "get", return_value=mock_response):
            info = self.client.get_progress()

        assert info is not None
        assert info.progress == 0.5
        assert info.eta_relative == 10.0
        assert info.current_step == 20
        assert info.total_steps == 40

    def test_get_progress_returns_none_when_idle(self) -> None:
        """Test get_progress returns None when WebUI is idle."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "progress": 0,
            "eta_relative": 0,
            "state": {},  # No job running
        }

        with patch.object(self.client._session, "get", return_value=mock_response):
            info = self.client.get_progress()

        assert info is None

    def test_get_progress_handles_timeout(self) -> None:
        """Test get_progress returns None on timeout."""
        with patch.object(
            self.client._session,
            "get",
            side_effect=requests.Timeout("Connection timeout"),
        ):
            info = self.client.get_progress()

        assert info is None

    def test_get_progress_handles_connection_error(self) -> None:
        """Test get_progress returns None on connection error."""
        with patch.object(
            self.client._session,
            "get",
            side_effect=requests.ConnectionError("Connection refused"),
        ):
            info = self.client.get_progress()

        assert info is None

    def test_get_progress_handles_non_200_status(self) -> None:
        """Test get_progress returns None for non-200 status codes."""
        mock_response = Mock()
        mock_response.status_code = 500

        with patch.object(self.client._session, "get", return_value=mock_response):
            info = self.client.get_progress()

        assert info is None

    def test_get_progress_skip_current_image_parameter(self) -> None:
        """Test get_progress passes skip_current_image parameter correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "progress": 0.3,
            "eta_relative": 5.0,
            "state": {"job": "txt2img"},
        }

        with patch.object(self.client._session, "get", return_value=mock_response) as mock_get:
            self.client.get_progress(skip_current_image=False)

            # Verify the parameters passed
            call_args = mock_get.call_args
            assert call_args[1]["params"]["skip_current_image"] == "false"

    def test_get_progress_uses_short_timeout(self) -> None:
        """Test get_progress uses a short timeout (5 seconds read)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "progress": 0.3,
            "eta_relative": 5.0,
            "state": {"job": "txt2img"},
        }

        with patch.object(self.client._session, "get", return_value=mock_response) as mock_get:
            self.client.get_progress()

            # Verify timeout is (connect_timeout, read_timeout)
            call_args = mock_get.call_args
            timeout = call_args[1]["timeout"]
            assert timeout[1] == 5.0  # Read timeout should be 5 seconds


if __name__ == "__main__":
    unittest.main()
