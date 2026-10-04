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
    resolve_forge_data_dir,
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


class _Settings:
    def __init__(self, path: str) -> None:
        self.path = path

    def __call__(self, *_a, **_k):
        return self

    def load_settings(self):
        return {"forge_runtime_profile_path": self.path}


def test_the_data_dir_comes_from_the_existing_runtime_profile_authority(tmp_path, monkeypatch):
    import json

    profile_file = tmp_path / "forge-profile.json"
    profile_file.write_text(json.dumps({
        "runtime_identity": "forge_webui", "command": ["py", "launch.py", "--data-dir", str(tmp_path / "data")],
        "endpoint": "http://127.0.0.1:7871", "working_dir": str(tmp_path),
    }), encoding="utf-8")
    monkeypatch.setattr("src.utils.config.ConfigManager", _Settings(str(profile_file)))
    assert resolve_forge_data_dir() == tmp_path / "data"


@pytest.mark.parametrize("configured", ["", "does-not-exist.json"])
def test_an_unverifiable_runtime_fails_closed(monkeypatch, configured):
    monkeypatch.setattr("src.utils.config.ConfigManager", _Settings(configured))
    with pytest.raises(KleinProfileError, match="cannot be established"):
        resolve_forge_data_dir()
