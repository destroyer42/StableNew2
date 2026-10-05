"""PR-IMG-FORGE-110/120: managed Forge is the production default; selection is configuration only.

An unset ``webui_runtime_identity`` selects managed Forge (new work is stamped ``forge_webui``), an explicit
``a1111_webui`` is the supported rollback, an unrecognized or unreadable configuration fails closed, and the default
launch profile comes from the shared managed-runtime contract. There is no fallback between the backends.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.api.webui_process_manager as manager_module
from src.api.webui_process_manager import WebUIProcessManager, load_managed_forge_runtime_profile
from src.api.webui_runtime_identity import (
    A1111_DEFAULT_BASE_URL,
    WebUIRuntimeConfigurationError,
    default_webui_base_url,
    resolve_effective_webui_base_url,
)
from src.image_backends import image_backend_types as types
from src.pipeline.cli_njr_builder import build_cli_njr
from src.utils import managed_forge_runtime as mfr
from src.utils.config import ConfigManager
from tools.runtime import verify_managed_forge as verifier

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
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)


def _profile(tmp_path: Path, **override) -> str:
    path = tmp_path / "forge-profile.json"
    path.write_text(json.dumps({**PROFILE, **override}), encoding="utf-8")
    return str(path)


def _config_njr(prompt: str = "p"):
    return build_cli_njr(prompt=prompt, config={"txt2img": {"model": "m", "seed": 1}}, batch_size=1, run_name="j")


def _managed_install(tmp_path: Path, monkeypatch, *, revision: str | None = None, status: str = "verified"):
    """A structurally complete managed Forge install under ``tmp_path`` (nothing is installed or started)."""

    manifest = mfr.load_manifest()
    root = tmp_path / "Forge"
    install = mfr.managed_install_dir(manifest, root)
    (install / "venv" / "Scripts").mkdir(parents=True, exist_ok=True)
    (install / "venv" / "Scripts" / "python.exe").write_text("")
    (install / "source").mkdir(exist_ok=True)
    (install / "source" / manifest["launch_policy"]["launch_script"]).write_text("")
    (install / "data").mkdir(exist_ok=True)
    marker = {"revision": revision or manifest["upstream"]["revision"], "status": status}
    (install / manifest["install"]["marker"]).write_text(json.dumps(marker), encoding="utf-8-sig")
    monkeypatch.setattr(mfr, "default_install_root", lambda _manifest: root)
    home = tmp_path / "a1111"
    (home / "models").mkdir(parents=True, exist_ok=True)
    return manifest, install, home


# --- A. default selection -------------------------------------------------------------------------------------


def test_forge_is_the_default_for_new_work(monkeypatch):
    _settings(monkeypatch, {})
    assert types.configured_image_backend_id() == "forge_webui" == types.NEW_IMAGE_BACKEND_DEFAULT_ID
    assert _config_njr().backend_options["image"]["backend_id"] == "forge_webui"


def test_explicit_forge_and_explicit_a1111_are_both_honored_and_a1111_is_never_rewritten(monkeypatch):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui"})
    assert _config_njr().backend_options["image"]["backend_id"] == "forge_webui"
    _settings(monkeypatch, {"webui_runtime_identity": "a1111_webui"})
    assert types.configured_image_backend_id() == "a1111_webui"
    assert _config_njr().backend_options["image"]["backend_id"] == "a1111_webui"  # the rollback is operator intent


def test_an_explicit_backend_in_the_job_always_wins_over_the_configured_identity(monkeypatch):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui"})
    options = types.normalize_image_backend_options({"image": {"backend_id": "a1111_webui"}})
    assert options["image"]["backend_id"] == "a1111_webui"  # rollback per job, never overridden
    _settings(monkeypatch, {})
    assert types.normalize_image_backend_options({"image": {"backend_id": "a1111_webui"}})["image"]["backend_id"] == "a1111_webui"


def test_the_historical_compatibility_identity_is_not_the_new_work_default(monkeypatch):
    _settings(monkeypatch, {})
    assert types.LEGACY_MISSING_IMAGE_BACKEND_ID == "a1111_webui" != types.NEW_IMAGE_BACKEND_DEFAULT_ID
    assert types.resolve_image_backend_id({}) == "a1111_webui"  # persisted records without identity stay A1111
    assert types.resolve_image_backend_id({"image": {"backend_id": "  "}}) == "a1111_webui"
    assert types.resolve_image_backend_id({"image": {"backend_id": "forge_webui"}}) == "forge_webui"


def test_an_unrecognized_identity_fails_closed_instead_of_selecting_a_backend(monkeypatch):
    _settings(monkeypatch, {"webui_runtime_identity": "forgee_webui"})
    with pytest.raises(WebUIRuntimeConfigurationError, match="no backend fallback"):
        types.configured_image_backend_id()
    with pytest.raises(WebUIRuntimeConfigurationError):
        _config_njr()  # the job is never built, so it can never be dispatched on a guessed backend
    with pytest.raises(WebUIRuntimeConfigurationError):
        manager_module.build_default_webui_process_config()


def test_an_unreadable_configuration_fails_closed_and_never_degrades_to_either_backend(monkeypatch):
    import src.utils.config as config_module

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(WebUIRuntimeConfigurationError, match="could not be read"):
        types.configured_image_backend_id()


def test_a_corrupt_settings_file_fails_closed_because_it_could_hide_an_a1111_rollback(monkeypatch, tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "settings.json").write_text("{not json", encoding="utf-8")
    import src.utils.config as config_module

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: ConfigManager(presets_dir=presets))
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    with pytest.raises(WebUIRuntimeConfigurationError, match="unreadable"):
        types.configured_image_backend_id()
    (presets / "settings.json").write_text("[]", encoding="utf-8")  # valid JSON but not a settings object
    with pytest.raises(WebUIRuntimeConfigurationError, match="not a JSON object"):
        types.configured_image_backend_id()
    (presets / "settings.json").write_text(json.dumps({"webui_runtime_identity": "a1111_webui"}), encoding="utf-8")
    assert types.configured_image_backend_id() == "a1111_webui"  # a readable file is honored


# --- B. identity-aware endpoint defaults ---------------------------------------------------------------------------


def test_endpoint_defaults_are_identity_aware_and_explicit_values_stay_authoritative(monkeypatch):
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    assert default_webui_base_url("forge_webui") == "http://127.0.0.1:7871" == mfr.default_endpoint()
    assert default_webui_base_url("a1111_webui") == "http://127.0.0.1:7860" == A1111_DEFAULT_BASE_URL
    assert resolve_effective_webui_base_url({}) == "http://127.0.0.1:7871"  # nothing configured: managed Forge
    assert resolve_effective_webui_base_url({"webui_runtime_identity": "a1111_webui"}) == "http://127.0.0.1:7860"
    assert (
        resolve_effective_webui_base_url({"webui_runtime_identity": "a1111_webui", "webui_base_url": "http://127.0.0.1:7861"})
        == "http://127.0.0.1:7861"
    )
    assert resolve_effective_webui_base_url({"webui_base_url": "http://127.0.0.1:7872"}) == "http://127.0.0.1:7872"
    monkeypatch.setenv("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7873")  # the environment fallback is unchanged
    assert resolve_effective_webui_base_url({}) == "http://127.0.0.1:7873"
    assert resolve_effective_webui_base_url({"webui_base_url": "http://127.0.0.1:7872"}) == "http://127.0.0.1:7872"


def test_the_persisted_legacy_a1111_flat_default_is_not_an_explicit_forge_endpoint(monkeypatch):
    """Every pre-promotion settings file persists 7860; it carries no operator intent for Forge, only for A1111."""

    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)
    legacy = {"webui_base_url": "http://127.0.0.1:7860/"}
    assert resolve_effective_webui_base_url(legacy) == "http://127.0.0.1:7871"
    assert resolve_effective_webui_base_url({**legacy, "webui_runtime_identity": "forge_webui"}) == "http://127.0.0.1:7871"
    assert resolve_effective_webui_base_url({**legacy, "webui_runtime_identity": "a1111_webui"}) == "http://127.0.0.1:7860/"


def test_load_settings_presents_the_effective_identity_aware_endpoint(monkeypatch, tmp_path):
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)

    def load(stored: dict) -> dict:
        presets = tmp_path / f"p{len(list(tmp_path.iterdir()))}"
        presets.mkdir()
        (presets / "settings.json").write_text(json.dumps(stored), encoding="utf-8")
        return ConfigManager(presets_dir=presets).load_settings()

    assert load({})["webui_base_url"] == "http://127.0.0.1:7871"  # the Engine Settings dialog shows the real endpoint
    assert load({"webui_base_url": "http://127.0.0.1:7860"})["webui_base_url"] == "http://127.0.0.1:7871"
    assert load({"webui_runtime_identity": "a1111_webui"})["webui_base_url"] == "http://127.0.0.1:7860"
    assert load({"webui_base_url": "http://127.0.0.1:7999"})["webui_base_url"] == "http://127.0.0.1:7999"
    assert load({"webui_runtime_identity": "bogus"})["webui_runtime_identity"] == "bogus"  # reported by selection, not hidden


# --- C. default managed Forge profile (one authority, shared with the verifier) ----------------------------------------------


def test_the_default_forge_path_builds_its_profile_from_the_managed_contract_with_no_profile_file(monkeypatch, tmp_path):
    manifest, install, home = _managed_install(tmp_path, monkeypatch)
    _settings(monkeypatch, {"webui_workdir": str(home), "webui_base_url": "http://127.0.0.1:7860"})  # no identity, no profile

    config = manager_module.build_default_webui_process_config()

    assert config is not None and config.runtime_identity == "forge_webui"
    expected = mfr.build_launch_profile(manifest, install_dir=install, model_home=home, port=7871)
    assert config.command == expected["command"] and config.working_dir == expected["working_dir"]
    assert config.env_overrides == expected["env_overrides"]
    assert config.base_url == "http://127.0.0.1:7871" and config.startup_timeout_seconds == 180
    assert config.launch_profile_commands is None
    assert "webui-user.bat" not in " ".join(config.command)
    assert mfr.check_launch_command(config.command, manifest) == []  # required flags present, nothing tuned or exposed
    manager = WebUIProcessManager(config)  # the one lifecycle authority, nothing started here
    assert manager.runtime_identity == "forge_webui" and not manager.owns_process


def test_the_verifier_and_the_default_path_share_one_launch_profile_authority(monkeypatch, tmp_path):
    assert verifier.build_launch_profile is mfr.build_launch_profile
    assert verifier.check_launch_command is mfr.check_launch_command
    assert verifier.load_manifest is mfr.load_manifest
    manifest, install, home = _managed_install(tmp_path, monkeypatch)
    resolved = mfr.resolve_default_launch_profile(model_home=home)
    printed = verifier.build_launch_profile(manifest, install_dir=install, model_home=home, port=manifest["launch_policy"]["default_port"])
    assert resolved == printed  # byte-for-byte what `verify_managed_forge.py --print-profile` prints


def test_an_explicit_loopback_port_is_honored_within_the_accepted_profile_contract(monkeypatch, tmp_path):
    _manifest, _install, home = _managed_install(tmp_path, monkeypatch)
    _settings(monkeypatch, {"webui_workdir": str(home), "webui_base_url": "http://127.0.0.1:7872"})
    config = manager_module.build_default_webui_process_config()
    assert config.base_url == "http://127.0.0.1:7872" and config.command[config.command.index("--port") + 1] == "7872"
    _settings(monkeypatch, {"webui_workdir": str(home), "webui_base_url": "http://example.com:7871"})
    with pytest.raises(mfr.ManagedForgeUnavailable, match="loopback"):
        manager_module.build_default_webui_process_config()  # managed Forge is never exposed or remote


@pytest.mark.parametrize(
    ("break_it", "needle"),
    [
        (lambda install, home: (install / "venv" / "Scripts" / "python.exe").unlink(), "interpreter is missing"),
        (lambda install, home: (install / "source" / "launch.py").unlink(), "launch script is missing"),
        (lambda install, home: (home / "models").rmdir(), "no 'models' folder"),
    ],
    ids=["interpreter", "launch-script", "model-reference-home"],
)
def test_an_incomplete_install_or_model_home_fails_actionably_instead_of_falling_through(monkeypatch, tmp_path, break_it, needle):
    _manifest, install, home = _managed_install(tmp_path, monkeypatch)
    break_it(install, home)
    _settings(monkeypatch, {"webui_workdir": str(home)})
    with pytest.raises(mfr.ManagedForgeUnavailable, match=needle) as raised:
        manager_module.build_default_webui_process_config()
    assert "bootstrap_managed_forge_windows.ps1" in str(raised.value) and "a1111_webui" in str(raised.value)
    assert "does not install Forge and does not fall back to A1111" in str(raised.value)


def test_a_missing_or_wrong_managed_install_is_reported_not_installed_not_substituted(monkeypatch, tmp_path):
    manifest = mfr.load_manifest()
    monkeypatch.setattr(mfr, "default_install_root", lambda _m: tmp_path / "Forge")
    home = tmp_path / "a1111"
    (home / "models").mkdir(parents=True)
    with pytest.raises(mfr.ManagedForgeUnavailable, match="no managed Forge install was found"):
        mfr.resolve_default_launch_profile(model_home=home)
    assert not (tmp_path / "Forge").exists()  # reading the contract never creates or installs anything
    for revision, status, needle in (("0" * 40, "verified", "not the pinned"), (manifest["upstream"]["revision"], "installing", "not 'verified'")):
        _managed_install(tmp_path, monkeypatch, revision=revision, status=status)
        with pytest.raises(mfr.ManagedForgeUnavailable, match=needle):
            mfr.resolve_default_launch_profile(model_home=home)
    _managed_install(tmp_path, monkeypatch)  # a good install again: only the model reference home is missing now
    with pytest.raises(mfr.ManagedForgeUnavailable, match="no model reference home"):
        mfr.resolve_default_launch_profile(model_home="")


def test_forge_selection_with_an_explicit_profile_override_still_resolves_that_profile(monkeypatch, tmp_path):
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


def test_an_unset_endpoint_with_a_profile_override_uses_the_profile_endpoint(monkeypatch, tmp_path):
    _settings(monkeypatch, {"forge_runtime_profile_path": _profile(tmp_path, endpoint="http://127.0.0.1:7880")})
    assert manager_module.build_default_webui_process_config().base_url == "http://127.0.0.1:7880"
    # the persisted legacy A1111 flat default carries no Forge intent either
    _settings(monkeypatch, {"forge_runtime_profile_path": _profile(tmp_path), "webui_base_url": "http://127.0.0.1:7860"})
    assert manager_module.build_default_webui_process_config().base_url == "http://127.0.0.1:7871"


def test_forge_with_a_conflicting_explicit_endpoint_fails_closed(monkeypatch, tmp_path):
    _settings(monkeypatch, {"webui_runtime_identity": "forge_webui", "forge_runtime_profile_path": _profile(tmp_path),
                            "webui_base_url": "http://127.0.0.1:7999"})
    with pytest.raises(ValueError, match="managed Forge endpoint"):
        manager_module.build_default_webui_process_config()


# --- D. explicit A1111 rollback --------------------------------------------------------------------------------------------


def test_the_a1111_configuration_never_reads_the_forge_profile_or_the_managed_install(monkeypatch, tmp_path):
    workdir = tmp_path / "webui"
    workdir.mkdir()
    (workdir / "webui-user.bat").write_text("")
    _settings(monkeypatch, {"webui_runtime_identity": "a1111_webui", "forge_runtime_profile_path": "does-not-exist.json",
                            "webui_workdir": str(workdir)})
    monkeypatch.setattr(mfr, "resolve_default_launch_profile", lambda **_k: pytest.fail("the A1111 path must not resolve Forge"))

    config = manager_module.build_default_webui_process_config()

    assert config is not None and config.runtime_identity == "a1111_webui"
    assert config.launch_profile_commands and config.command[0] == "webui-user.bat"
    assert config.base_url == "http://127.0.0.1:7860"  # the A1111 default endpoint when nothing else is configured


@pytest.mark.parametrize(
    "bad",
    [{"command": []}, {"runtime_identity": "a1111_webui"}, {"endpoint": "http://example.com:7871"}, {"working_dir": ""}],
)
def test_an_invalid_managed_profile_is_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        load_managed_forge_runtime_profile(_profile(tmp_path, **bad))


# --- E. no fallback ----------------------------------------------------------------------------------------------------------


def test_there_is_no_cross_backend_fallback_in_the_selection_code():
    import ast
    import inspect

    from src.api import webui_runtime_identity as identity_module
    from src.controller.ports import default_runtime_ports as ports_module

    sources = {m.__name__: inspect.getsource(m) for m in (manager_module, types, identity_module, ports_module)}
    for name, source in sources.items():
        assert "fallback to a1111" not in source.lower() and "fall back to a1111" not in source.lower(), name
    # `configured_image_backend_id` swallows nothing: no try/except can turn a bad configuration into either backend.
    selector = ast.parse(inspect.getsource(types.configured_image_backend_id))
    assert not [n for n in ast.walk(selector) if isinstance(n, ast.Try)]
    forge_builder = ast.parse(inspect.getsource(manager_module._build_forge_process_config))
    assert not [n for n in ast.walk(forge_builder) if isinstance(n, ast.Try)]  # a setup error propagates, never A1111
    called = {n.func.id for n in ast.walk(forge_builder) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"_load_webui_cache", "_save_webui_cache", "detect_default_webui_workdir"}
