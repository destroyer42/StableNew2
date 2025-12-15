import contextlib
from unittest import mock

from src.api.client import SDWebUIClient


def test_options_post_skipped_when_readiness_false(monkeypatch):
    client = SDWebUIClient()
    client.set_options_readiness_provider(lambda: False)
    ctx_mock = mock.Mock(return_value=contextlib.nullcontext(mock.Mock()))
    monkeypatch.setattr(SDWebUIClient, "_request_context", ctx_mock)

    assert client.set_model("foo") is False
    ctx_mock.assert_not_called()


def test_options_post_throttled(monkeypatch):
    client = SDWebUIClient()
    client._options_min_interval_seconds = 60.0
    client.set_options_readiness_provider(lambda: True)
    ctx_mock = mock.Mock(return_value=contextlib.nullcontext(mock.Mock()))
    monkeypatch.setattr(SDWebUIClient, "_request_context", ctx_mock)

    client.set_model("first")
    client.set_model("second")

    assert ctx_mock.call_count == 1
