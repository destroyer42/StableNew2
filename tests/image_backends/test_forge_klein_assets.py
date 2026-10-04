"""PR-IMG-116 review repair: the bytes Forge loads are verified locally (tiny stand-in assets; no 12 GB reads)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

import src.image_backends.forge_klein_assets as assets_module
from src.image_backends.forge_klein_assets import (
    clear_verified_cache,
    data_dir_from_launch_command,
    verify_klein_assets,
)
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1, KleinAsset, KleinProfileError

CONTENT = {"transformer": b"transformer-bytes", "text_encoder": b"text-encoder-bytes", "vae": b"vae-bytes"}


def tiny_profile():
    def asset(base: KleinAsset) -> KleinAsset:
        data = CONTENT[base.role]
        return replace(base, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    p = KLEIN_PROFILE_V1
    return replace(p, transformer=asset(p.transformer), text_encoder=asset(p.text_encoder), vae=asset(p.vae))


def install(data_dir: Path, profile) -> None:
    for a in profile.assets:
        target = data_dir / "models" / a.models_subdir / a.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(CONTENT[a.role])


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_verified_cache()
    yield
    clear_verified_cache()


@pytest.fixture
def hashed(monkeypatch):
    calls: list[str] = []
    real = assets_module._sha256

    def counting(path: Path) -> str:
        calls.append(path.name)
        return real(path)

    monkeypatch.setattr(assets_module, "_sha256", counting)
    return calls


def test_exact_files_pass_and_report_the_verified_identity(tmp_path):
    profile = tiny_profile()
    install(tmp_path, profile)
    identity = verify_klein_assets(profile, data_dir=tmp_path)
    assert set(identity) == {"transformer", "text_encoder", "vae"}
    for a in profile.assets:
        assert identity[a.role] == {"name": a.filename, "size": a.size, "sha256": a.sha256, "verified": "sha256", "cache": "miss"}
    assert str(tmp_path) not in repr(identity)  # no machine path leaks into evidence


def test_same_name_file_with_wrong_bytes_fails_closed(tmp_path):
    profile = tiny_profile()
    install(tmp_path, profile)
    target = tmp_path / "models" / "VAE" / profile.vae.filename
    target.write_bytes(b"x" * profile.vae.size)  # same name, same size, different bytes
    with pytest.raises(KleinProfileError, match="SHA-256"):
        verify_klein_assets(profile, data_dir=tmp_path)


def test_wrong_size_and_missing_files_fail_closed(tmp_path):
    profile = tiny_profile()
    install(tmp_path, profile)
    (tmp_path / "models" / "text_encoder" / profile.text_encoder.filename).write_bytes(b"short")
    with pytest.raises(KleinProfileError, match="bytes, expected"):
        verify_klein_assets(profile, data_dir=tmp_path)
    (tmp_path / "models" / "text_encoder" / profile.text_encoder.filename).unlink()
    with pytest.raises(KleinProfileError, match="not installed"):
        verify_klein_assets(profile, data_dir=tmp_path)


def test_a_verified_file_is_not_rehashed_until_it_changes(tmp_path, hashed):
    profile = tiny_profile()
    install(tmp_path, profile)
    verify_klein_assets(profile, data_dir=tmp_path)
    assert len(hashed) == 3  # first use is cryptographically verified
    again = verify_klein_assets(profile, data_dir=tmp_path)
    assert len(hashed) == 3 and {e["cache"] for e in again.values()} == {"hit"}


def test_mutation_after_verification_forces_a_rehash_and_fails(tmp_path, hashed):
    profile = tiny_profile()
    install(tmp_path, profile)
    verify_klein_assets(profile, data_dir=tmp_path)
    target = tmp_path / "models" / "Stable-diffusion" / profile.transformer.filename
    before = target.stat()
    target.write_bytes(b"y" * profile.transformer.size)  # same size, different bytes
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000))  # an observable stat change
    with pytest.raises(KleinProfileError, match="SHA-256"):
        verify_klein_assets(profile, data_dir=tmp_path)
    assert hashed.count(profile.transformer.filename) == 2  # rehashed, not served from the cache


def test_restoring_the_exact_bytes_verifies_again(tmp_path):
    profile = tiny_profile()
    install(tmp_path, profile)
    verify_klein_assets(profile, data_dir=tmp_path)
    target = tmp_path / "models" / "VAE" / profile.vae.filename
    target.write_bytes(b"z" * profile.vae.size)
    with pytest.raises(KleinProfileError):
        verify_klein_assets(profile, data_dir=tmp_path)
    target.write_bytes(CONTENT["vae"])
    assert verify_klein_assets(profile, data_dir=tmp_path)["vae"]["sha256"] == profile.vae.sha256


def test_launch_command_data_dir_parsing():
    assert data_dir_from_launch_command(["py", "launch.py", "--data-dir", "C:/d", "--api"]) == Path("C:/d")
    assert data_dir_from_launch_command(["py", "--data-dir=C:/e"]) == Path("C:/e")
    assert data_dir_from_launch_command(["py", "launch.py"]) is None


ENDPOINT = "http://127.0.0.1:7871"


def owned_manager(data_dir, *, identity="forge_webui", owns=True, endpoint=ENDPOINT, command=None):
    from types import SimpleNamespace

    cmd = command if command is not None else (["py", "launch.py", "--port", "7871", "--data-dir", str(data_dir)] if data_dir else ["py"])
    return SimpleNamespace(runtime_identity=identity, owns_process=owns, endpoint=endpoint,
                           launch_session_command=cmd if owns else None)


def use_manager(monkeypatch, manager) -> None:
    monkeypatch.setattr("src.image_backends.forge_klein_assets._active_manager", lambda: manager)


def test_owned_managed_forge_with_the_right_endpoint_and_command_passes(tmp_path, monkeypatch):
    profile = tiny_profile()
    install(tmp_path, profile)
    use_manager(monkeypatch, owned_manager(tmp_path))
    identity = verify_klein_assets(profile, endpoint=ENDPOINT)
    assert {r: e["sha256"] for r, e in identity.items()} == {a.role: a.sha256 for a in profile.assets}
    assert verify_klein_assets(profile, endpoint="http://localhost:7871/")["vae"]["cache"] == "hit"  # same endpoint, cache kept


@pytest.mark.parametrize(
    ("manager_kwargs", "fragment"),
    [
        ({"manager": None}, "No StableNew WebUI process manager"),  # B: an external Forge with no manager of ours
        ({"owns": False}, "does not own"),  # C
        ({"identity": "a1111_webui"}, "not forge_webui"),  # D
        ({"endpoint": "http://127.0.0.1:7999"}, "not the client endpoint"),  # E
        ({"command": ["py", "launch.py"]}, "declares no --data-dir"),
    ],
)
def test_anything_but_a_positively_owned_serving_forge_fails_closed(tmp_path, monkeypatch, manager_kwargs, fragment):
    profile = tiny_profile()
    install(tmp_path, profile)
    manager = None if "manager" in manager_kwargs else owned_manager(tmp_path, **manager_kwargs)
    use_manager(monkeypatch, manager)
    with pytest.raises(KleinProfileError, match=fragment) as caught:
        verify_klein_assets(profile, endpoint=ENDPOINT)
    assert "requires the StableNew-owned managed Forge" in str(caught.value)  # actionable


def test_an_empty_client_endpoint_cannot_be_matched(tmp_path, monkeypatch):
    profile = tiny_profile()
    install(tmp_path, profile)
    use_manager(monkeypatch, owned_manager(tmp_path))
    with pytest.raises(KleinProfileError, match="not the client endpoint"):
        verify_klein_assets(profile, endpoint="")


def test_verification_follows_the_actual_owned_launch_command_not_a_configured_profile(tmp_path, monkeypatch):
    import json

    profile = tiny_profile()
    actual, configured = tmp_path / "actual-data", tmp_path / "configured-data"
    install(actual, profile)
    for a in profile.assets:  # the configured profile tree has WRONG bytes: it must never be consulted
        target = configured / "models" / a.models_subdir / a.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"w" * a.size)
    profile_file = tmp_path / "forge-profile.json"
    profile_file.write_text(json.dumps({"command": ["py", "--data-dir", str(configured)]}), encoding="utf-8")
    monkeypatch.setattr("src.utils.config.ConfigManager", type("C", (), {"load_settings": lambda self: {"forge_runtime_profile_path": str(profile_file)}}))
    use_manager(monkeypatch, owned_manager(actual))
    assert verify_klein_assets(profile, endpoint=ENDPOINT)["transformer"]["sha256"] == profile.transformer.sha256


def test_wrong_bytes_in_the_owned_data_dir_fail(tmp_path, monkeypatch):
    profile = tiny_profile()
    install(tmp_path, profile)
    (tmp_path / "models" / "VAE" / profile.vae.filename).write_bytes(b"x" * profile.vae.size)
    use_manager(monkeypatch, owned_manager(tmp_path))
    with pytest.raises(KleinProfileError, match="SHA-256"):
        verify_klein_assets(profile, endpoint=ENDPOINT)


def test_the_real_manager_exposes_the_launch_session_only_while_it_owns_the_process():
    from types import SimpleNamespace

    from src.api.webui_process_manager import (
        WebUIProcessConfig,
        WebUIProcessManager,
        clear_global_webui_process_manager,
    )

    try:
        manager = WebUIProcessManager(WebUIProcessConfig(command=["py", "--data-dir", "D:/a"], base_url="http://127.0.0.1:7871/", runtime_identity="forge_webui"))
        assert manager.launch_session_command is None and manager.endpoint == "http://127.0.0.1:7871/"
        manager._owns_process, manager._process, manager._pid = True, SimpleNamespace(pid=7), 7
        manager._launch_session_command = ("py", "--data-dir", "D:/a")
        manager._config.command = ["py", "--data-dir", "D:/changed-later"]  # a later config change must not rewrite the session
        assert manager.launch_session_command == ["py", "--data-dir", "D:/a"]
        manager._owns_process = False
        assert manager.launch_session_command is None
    finally:
        clear_global_webui_process_manager()
