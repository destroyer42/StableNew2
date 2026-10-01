"""Deterministic pytest must not interact with the host's A1111/Comfy autostart."""

from __future__ import annotations

import os

import pytest

import src.config.app_config as app_config


def test_default_test_environment_pins_backend_autostart_off() -> None:
    assert os.environ["STABLENEW_WEBUI_AUTOSTART"] == "0"
    assert os.environ["STABLENEW_COMFY_AUTOSTART"] == "0"
    assert app_config.webui_autostart_enabled_default() is False
    assert app_config.get_webui_autostart_enabled() is False


def test_autostart_tests_can_override_the_default_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STABLENEW_WEBUI_AUTOSTART", "1")
    monkeypatch.setattr(app_config, "_webui_autostart_enabled", None)

    assert app_config.get_webui_autostart_enabled() is True
