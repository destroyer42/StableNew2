"""
WebUI mock infrastructure for CI testing.

Provides:
- MockWebUIServer: HTTP server mock for SD WebUI API
- MockWebUIClient: Client implementation that uses mock server
- mock_responses: Realistic API response payloads
"""

__all__ = [
    "MockWebUIServer",
    "MockWebUIClient",
    "get_mock_server",
]

from tests.mocks.webui_mock_server import MockWebUIServer, get_mock_server
from tests.mocks.webui_mock_client import MockWebUIClient
