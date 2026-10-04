"""PR-IMG-FORGE-100R: launch-profile resolution is owned by the manager, never by a process-global command.

A logical profile (``sdxl_guarded``) may replace a manager's concrete command only when THAT manager declares the
profile. A qualified isolated A1111, a managed Forge or any explicitly configured runtime keeps its command,
working directory, environment and identity byte-for-byte when a profile it does not declare is requested.
No process is started or stopped here.
"""

from __future__ import annotations

import ast
import copy
import logging
from pathlib import Path

import pytest

from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    build_default_webui_process_config,
)
from src.config import app_config

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDED = app_config.resolve_webui_launch_command("sdxl_guarded")

A1111_QUALIFIED = [
    r"C:\Users\rob\stable-diffusion-webui\venv\Scripts\python.exe",
    "launch.py", "--xformers", "--api", "--port", "7860", "--skip-prepare-environment",
    "--ad-no-huggingface", "--ui-settings-file", r"C:\qual\a1111-config.json",
]
FORGE_QUALIFIED = [
    r"C:\Users\rob\AppData\Local\StableNew\Forge\neo-d70373eb\venv\Scripts\python.exe",
    "launch.py", "--uv", "--api", "--port", "7871", "--data-dir", r"C:\forge\data",
    "--forge-ref-a1111-home", r"C:\Users\rob\stable-diffusion-webui", "--ad-no-huggingface", "--skip-install",
]


def _config(identity: str, command: list[str], working_dir: str, **extra) -> WebUIProcessConfig:
    return WebUIProcessConfig(
        command=list(command), working_dir=working_dir, env_overrides={"VIRTUAL_ENV": "qualified-venv"},
        base_url="http://127.0.0.1:7860", runtime_identity=identity, **extra,
    )


def _snapshot(manager: WebUIProcessManager) -> dict:
    config = manager._config
    return {
        "command": list(config.command), "working_dir": config.working_dir, "env": dict(config.env_overrides or {}),
        "identity": manager.runtime_identity, "profile": config.launch_profile, "base_url": config.base_url,
        "profiles": copy.deepcopy(dict(config.launch_profile_commands or {})),
    }


@pytest.fixture(autouse=True)
def _isolate_global_profile():
    before = app_config.get_webui_launch_profile()
    yield
    app_config.set_webui_launch_profile(before)


@pytest.mark.parametrize(
    ("identity", "command", "working_dir"),
    [("a1111_webui", A1111_QUALIFIED, r"C:\Users\rob\stable-diffusion-webui"), ("forge_webui", FORGE_QUALIFIED, r"C:\forge\source")],
)
def test_an_unsupported_profile_never_changes_the_qualified_command_directory_env_or_identity(identity, command, working_dir):
    manager = WebUIProcessManager(_config(identity, command, working_dir))
    before = _snapshot(manager)

    assert manager.supports_launch_profile("sdxl_guarded") is False
    assert manager.set_launch_profile("sdxl_guarded") is False

    assert _snapshot(manager) == before  # byte-for-byte: command, working_dir, env, identity, profile
    assert manager._config.command == command and "webui-user.bat" not in manager._config.command
    assert app_config.get_webui_launch_profile() != "sdxl_guarded"  # the process-global preference is untouched too


@pytest.mark.parametrize("identity", ["a1111_webui", "forge_webui"])
def test_the_current_profile_is_always_supported_as_a_no_op(identity):
    manager = WebUIProcessManager(_config(identity, FORGE_QUALIFIED, r"C:\x"))
    before = _snapshot(manager)

    assert manager.supports_launch_profile("standard") and manager.supports_launch_profile(None)
    assert manager.set_launch_profile("standard") is True
    assert _snapshot(manager) == before
    assert manager.supported_launch_profiles() == ("standard",)


def test_a_manager_that_declares_a_profile_applies_exactly_that_command_and_keeps_the_rest():
    qualified_guarded = [*A1111_QUALIFIED, "--medvram-sdxl"]  # a qualification A1111 may supply its own
    manager = WebUIProcessManager(
        _config("a1111_webui", A1111_QUALIFIED, r"C:\q", launch_profile_commands={"sdxl_guarded": qualified_guarded})
    )
    before = _snapshot(manager)

    assert manager.supports_launch_profile("sdxl_guarded") and not manager.supports_launch_profile("low_memory")
    assert manager.set_launch_profile("sdxl_guarded") is True
    after = _snapshot(manager)

    assert after["command"] == qualified_guarded  # its own executable/path/flags, not webui-user.bat
    assert after["profile"] == "sdxl_guarded"
    assert (after["working_dir"], after["env"], after["identity"]) == (before["working_dir"], before["env"], before["identity"])
    assert manager.set_launch_profile("low_memory") is False  # undeclared: refused, still the guarded command
    assert manager._config.command == qualified_guarded


def test_the_stablenew_managed_a1111_configuration_declares_the_canonical_profiles(tmp_path, monkeypatch):
    (tmp_path / "webui-user.bat").write_text("", encoding="utf-8")
    monkeypatch.setattr("src.utils.config.ConfigManager.load_settings", lambda self: {"webui_workdir": str(tmp_path)})
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    monkeypatch.setattr("src.api.webui_process_manager._save_webui_cache", lambda *_a, **_k: None)

    config = build_default_webui_process_config()

    assert config is not None and config.runtime_identity == "a1111_webui"
    assert set(config.launch_profile_commands) == {"standard", "sdxl_guarded", "sdxl_adetailer_guarded", "sdxl_adetailer_no_half", "low_memory"}
    assert config.launch_profile_commands["sdxl_guarded"] == GUARDED
    manager = WebUIProcessManager(config)
    assert manager.supports_launch_profile("sdxl_guarded") and manager.set_launch_profile("sdxl_guarded")
    assert manager._config.command == GUARDED  # normal production A1111 behavior is preserved


def test_a_configured_forge_identity_never_inherits_the_a1111_profile_commands(tmp_path, monkeypatch):
    (tmp_path / "webui-user.bat").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "src.utils.config.ConfigManager.load_settings",
        lambda self: {"webui_workdir": str(tmp_path), "webui_runtime_identity": "forge_webui"},
    )
    monkeypatch.setattr("src.api.webui_process_manager._save_webui_cache", lambda *_a, **_k: None)

    config = build_default_webui_process_config()

    assert config is not None and config.runtime_identity == "forge_webui"
    assert config.launch_profile_commands is None
    manager = WebUIProcessManager(config)
    before = _snapshot(manager)
    assert not manager.supports_launch_profile("sdxl_guarded") and manager.set_launch_profile("sdxl_guarded") is False
    assert _snapshot(manager) == before


@pytest.fixture
def owned_manager(monkeypatch):
    """A manager that 'owns' a process, whose stop/start must never be reached for an unsupported profile."""

    manager = WebUIProcessManager(_config("forge_webui", FORGE_QUALIFIED, r"C:\forge\source"))
    calls: list[str] = []
    monkeypatch.setattr(WebUIProcessManager, "owns_process", property(lambda self: True))
    monkeypatch.setattr("src.utils.single_instance.SingleInstanceLock.is_gui_running", staticmethod(lambda: True))
    monkeypatch.setattr(manager, "stop_webui", lambda *a, **k: calls.append("stop") or True)
    monkeypatch.setattr(manager, "start", lambda: calls.append("start"))
    return manager, calls


def test_restart_with_an_unsupported_profile_is_refused_before_anything_is_stopped(owned_manager, caplog):
    manager, calls = owned_manager
    before = _snapshot(manager)

    with caplog.at_level(logging.WARNING):
        assert manager.restart_webui(profile_override="sdxl_guarded", max_attempts=1) is False

    assert calls == []  # the running qualified runtime was neither stopped nor restarted
    assert _snapshot(manager) == before
    assert "webui_launch_profile_unsupported" in caplog.text  # the refusal is reported, not silent


def test_restart_without_a_profile_override_keeps_the_qualified_command(owned_manager, monkeypatch):
    manager, calls = owned_manager

    class _API:
        def __init__(self, client) -> None: ...
        def wait_until_true_ready(self, **_k) -> None: ...

    class _Client:
        def __init__(self, base_url) -> None: ...
        def close(self) -> None: ...

    monkeypatch.setattr("src.api.webui_api.WebUIAPI", _API)
    monkeypatch.setattr("src.api.client.SDWebUIClient", _Client)

    assert manager.restart_webui(wait_ready=True, max_attempts=1) is True  # the stall-escalation restart shape

    assert calls == ["stop", "start"]
    assert manager._config.command == FORGE_QUALIFIED and manager.runtime_identity == "forge_webui"


def test_process_global_launch_commands_are_resolved_only_by_the_a1111_configuration_builder():
    """Static ownership: the manager never reads the global command map when applying a profile."""

    source = (REPO_ROOT / "src" / "api" / "webui_process_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "set_launch_profile")
    body = ast.unparse(method)

    assert "resolve_webui_launch_command" not in body
    assert "launch_profile_commands" in body
    # the only producers of profile commands are the configuration builder, from the canonical A1111 map
    assert source.count("get_webui_launch_profile_commands()") == 1


def test_the_qualification_driver_builds_its_manager_without_declaring_any_profile():
    """The qualified command in a runtime profile JSON is authoritative: the driver adds no profile map."""

    driver = (REPO_ROOT / "tools" / "acceptance" / "img_forge_100_acceptance.py").read_text(encoding="utf-8")
    assert "launch_profile_commands" not in driver and "resolve_webui_launch_command" not in driver
    assert driver.count("WebUIProcessManager(") == 1
