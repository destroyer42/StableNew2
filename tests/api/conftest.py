"""Fixtures for API tests."""
import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def mock_gui_running():
    """Mock SingleInstanceLock.is_gui_running() to return True for all API tests.
    
    This prevents RuntimeError when WebUIProcessManager tries to start/restart
    the WebUI process. In production, WebUI won't start unless the GUI is running
    (to prevent orphaned processes), but in tests we need to bypass this check.
    """
    with mock.patch("src.utils.single_instance.SingleInstanceLock.is_gui_running", return_value=True):
        yield
