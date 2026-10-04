"""PR-IMG-FORGE-110: selecting managed Forge in production is configuration only.

``webui_runtime_identity`` picks the backend for new work and the managed-runtime profile supplies the launch
command; A1111 stays the default and the rollback; there is no fallback between them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.api.webui_process_manager as manager_module
from src.api.webui_process_manager import WebUIProcessManager, load_managed_forge_runtime_profile
from src.image_backends import image_backend_types as types
from src.pipeline.cli_njr_builder import build_cli_njr

PROFILE = {
    "runtime_identity": "forge_webui",
    "command": [r"C:\forge\venv\Scripts\python.exe", "launch.py", "--uv", "--api", "--port", "7871", "--skip-install"],
    "working_dir": r"C:\forge\source",
    "env_overrides": {"HF_HUB_OFFLINE": "1"},
    "endpoint": "http://127.0.0.1:7871",
    "startup_timeout_seconds": 180,
}


def _settings(monkeypatch, settings: dict) -> None:
    class _Config:
        def load_settings(self):
            return dict(settings)

    import src.utils.config as config_module

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: _Config())
    monkeypatch.setattr(manager_module, "_save_webui_cache", lambda _c: None)
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)


def _profile(tmp_path: Path, **override) -> str:
    path = tmp_path / "forge-profile.json"
    path.write_text(json.dumps({**PROFILE, **override}), encoding="utf-8")
    return str(path)


def _config_njr(prompt: str = "p"):
    return build_cli_njr(prompt=prompt, config={"txt2img": {"model": "m", "seed": 1}}, batch_size=1, run_name="j")


def test_a1111_remains_the_default_for_new_work(monkeypatch):
    _settings(monkeypatch, {})
    assert types.configured_image_backend_id() == "a1111_webui" == types.DEFAULT_IMAGE_BACKEND_ID
    assert _config_njr().backend_options["image"]["backend_id"] == "a1111_webui"


def test_selecting_forge_stamps_new_work_with_the_forge_identity(monkeypatch):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui"})
    assert _config_njr().backend_options["image"]["backend_id"] == "forge_webui"


def test_an_explicit_backend_in_the_job_always_wins_over_the_configured_identity(monkeypatch):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui"})
    options = types.normalize_image_backend_options({"image": {"backend_id": "a1111_webui"}})
    assert options["image"]["backend_id"] == "a1111_webui"  # rollback per job, never overridden


def test_rollback_is_just_the_setting_and_changes_nothing_else(monkeypatch):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui"})
    assert types.configured_image_backend_id() == "forge_webui"
    _settings(monkeypatch, {"webui_runtime_identity": "a1111_webui"})
    assert types.configured_image_backend_id() == "a1111_webui"


def test_an_unreadable_configuration_never_selects_forge(monkeypatch):
    import src.utils.config as config_module

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert types.configured_image_backend_id() == "a1111_webui"


def test_forge_selection_resolves_the_managed_runtime_profile(monkeypatch, tmp_path):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui", "forge_runtime_profile_path": _profile(tmp_path),
                            "webui_base_url": "http://127.0.0.1:7871", "webui_workdir": r"C:\a1111"})

    config = manager_module.build_default_webui_process_config()

    assert config is not None and config.runtime_identity == "forge_webui"
    assert config.command == PROFILE["command"] and config.working_dir == PROFILE["working_dir"]
    assert config.env_overrides == PROFILE["env_overrides"] and config.startup_timeout_seconds == 180
    assert config.launch_profile_commands is None  # no A1111 profile map, no A1111 command
    assert "webui-user.bat" not in " ".join(config.command)
    manager = WebUIProcessManager(config)  # the one lifecycle authority, nothing started here
    assert manager.runtime_identity == "forge_webui" and not manager.owns_process


def test_forge_with_a_mismatched_endpoint_fails_closed(monkeypatch, tmp_path):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui", "forge_runtime_profile_path": _profile(tmp_path),
                            "webui_base_url": "http://127.0.0.1:7860"})
    with pytest.raises(ValueError, match="managed Forge endpoint"):
        manager_module.build_default_webui_process_config()


def test_the_a1111_configuration_never_reads_the_forge_profile(monkeypatch, tmp_path):
    workdir = tmp_path / "webui"
    workdir.mkdir()
    (workdir / "webui-user.bat").write_text("")
    _settings(monkeypatch, {"webui_runtime_identity": "a1111_webui", "forge_runtime_profile_path": "does-not-exist.json",
                            "webui_workdir": str(workdir)})

    config = manager_module.build_default_webui_process_config()

    assert config is not None and config.runtime_identity == "a1111_webui"
    assert config.launch_profile_commands and config.command[0] == "webui-user.bat"


@pytest.mark.parametrize(
    "bad",
    [{"command": []}, {"runtime_identity": "a1111_webui"}, {"endpoint": "http://example.com:7871"}, {"working_dir": ""}],
)
def test_an_invalid_managed_profile_is_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        load_managed_forge_runtime_profile(_profile(tmp_path, **bad))


def test_there_is_no_cross_backend_fallback_in_the_selection_code():
    source = Path(manager_module.__file__).read_text(encoding="utf-8") + Path(types.__file__).read_text(encoding="utf-8")
    assert "fallback to a1111" not in source.lower() and "fall back to a1111" not in source.lower()
