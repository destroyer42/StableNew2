"""PR-IMG-FORGE-100: the runtime-ports seam picks the WebUI-family client from configuration."""

from __future__ import annotations

import pytest

from src.api.client import SDWebUIClient
from src.api.forge_client import ForgeWebUIClient
from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts


def test_default_identity_builds_the_a1111_client() -> None:
    client = DefaultImageRuntimePorts(runtime_identity="a1111_webui").create_client(
        base_url="http://127.0.0.1:7860"
    )
    assert type(client) is SDWebUIClient


def test_forge_identity_builds_the_forge_client_bound_to_the_given_endpoint() -> None:
    client = DefaultImageRuntimePorts(runtime_identity="forge_webui").create_client(
        base_url="http://127.0.0.1:7861/"
    )
    assert isinstance(client, ForgeWebUIClient)
    assert client.base_url == "http://127.0.0.1:7861"


def test_explicit_but_unknown_identity_is_rejected_rather_than_coerced() -> None:
    ports = DefaultImageRuntimePorts(runtime_identity="forge")
    with pytest.raises(ValueError):
        ports.create_client(base_url="http://127.0.0.1:7860")


def test_identity_comes_from_the_configured_setting_when_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.utils.config as config_module

    class _Settings:
        def __init__(self, identity: str) -> None:
            self._identity = identity

        def load_settings(self) -> dict[str, object]:
            return {"webui_runtime_identity": self._identity}

    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: _Settings("forge_webui"))
    assert isinstance(
        DefaultImageRuntimePorts().create_client(base_url="http://127.0.0.1:7861"), ForgeWebUIClient
    )
    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: _Settings("a1111_webui"))
    assert (
        type(DefaultImageRuntimePorts().create_client(base_url="http://127.0.0.1:7860"))
        is SDWebUIClient
    )


def test_one_client_per_created_runtime_and_no_dynamic_swap_api() -> None:
    ports = DefaultImageRuntimePorts(runtime_identity="forge_webui")
    first = ports.create_client(base_url="http://127.0.0.1:7861")
    second = ports.create_client(base_url="http://127.0.0.1:7861")
    assert first is not second  # factories create; they never mutate an existing Pipeline client
    assert not hasattr(ports, "set_client") and not hasattr(ports, "swap_client")
