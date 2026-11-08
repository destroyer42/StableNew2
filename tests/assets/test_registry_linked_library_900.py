"""MEC-900: a library folder moved behind a link keeps its verified identities.

The owner moved ``models/Stable-diffusion`` to another drive and left a junction at the old path. Cache entries
written before the move are keyed by the old (unresolved) path; lookups key by the resolved path. Without the alias
rule every checkpoint looked unverified and "Verify identities" re-hashed hundreds of GB each session.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from src.assets.registry import AssetKind, AssetRegistry
from tests.assets.checkpoint_fixtures import checkpoint


def _link_directory(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if sys.platform != "win32":
            raise
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def _moved_library(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Hash under a real folder, then move it to another root and leave a link at the old path."""
    webui = tmp_path / "webui"
    old_root = webui / "models" / "Stable-diffusion"
    model = checkpoint(old_root / "Not Working" / "probe.safetensors", payload=b"moved bytes")
    cache = tmp_path / "state" / "asset_registry_v1.json"
    AssetRegistry(webui, cache_path=cache).refresh(kinds=[AssetKind.CHECKPOINT])
    keys = json.loads(cache.read_text(encoding="utf-8"))["entries"]
    assert str(model) in keys  # written under the then-real path
    new_root = tmp_path / "other_drive" / "Stable-diffusion"
    new_root.parent.mkdir(parents=True)
    shutil.move(str(old_root), str(new_root))  # a move keeps size and mtime
    try:
        _link_directory(old_root, new_root)
    except OSError as exc:  # pragma: no cover - host without link support
        pytest.skip(f"directory links unavailable: {exc}")
    return webui, cache, model


def test_alias_entry_verifies_the_same_file_without_hashing(tmp_path, monkeypatch):
    webui, cache, model = _moved_library(tmp_path)
    assert model.resolve() != model  # the old path now goes through the link
    expected = hashlib.sha256(model.read_bytes()).hexdigest()
    registry = AssetRegistry(webui, cache_path=cache)
    assert registry.verified_sha256(model) == expected
    assert registry.checkpoint_status(model).current

    calls = []
    import src.assets.registry as module

    real = module.hashlib.sha256
    monkeypatch.setattr(
        module.hashlib, "sha256", lambda *a, **kw: calls.append(1) or real(*a, **kw)
    )
    result = registry.refresh(checkpoint_paths=[model])
    assert result.hashes_computed == 0 and not calls  # reused, not re-read

    entries = json.loads(cache.read_text(encoding="utf-8"))["entries"]
    assert str(model.resolve()) in entries and str(model) not in entries  # re-keyed, alias retired
    assert entries[str(model.resolve())]["sha256"] == expected
    assert AssetRegistry(webui, cache_path=cache).verified_sha256(model) == expected


def test_alias_entry_is_refused_when_the_file_changed(tmp_path):
    webui, cache, model = _moved_library(tmp_path)
    model.write_bytes(model.read_bytes() + b"edited")
    assert AssetRegistry(webui, cache_path=cache).verified_sha256(model) is None


def test_alias_lookup_never_borrows_another_files_entry(tmp_path):
    webui = tmp_path / "webui"
    root = webui / "models" / "Stable-diffusion"
    first = checkpoint(root / "a.safetensors", payload=b"a")
    second = checkpoint(root / "b.safetensors", payload=b"b")
    cache = tmp_path / "cache.json"
    registry = AssetRegistry(webui, cache_path=cache)
    registry.refresh(kinds=[AssetKind.CHECKPOINT])
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["entries"].pop(str(second.resolve()))
    cache.write_text(json.dumps(data), encoding="utf-8")
    fresh = AssetRegistry(webui, cache_path=cache)
    assert fresh.verified_sha256(first) is not None
    assert fresh.verified_sha256(second) is None
