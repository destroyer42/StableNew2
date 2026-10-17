"""PR-LEARN-COMPARE-145: the cache diagnosis tool is strictly read-only and path-free by default."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.assets import AssetRegistry
from tests.assets.checkpoint_fixtures import checkpoint
from tools.diagnose_asset_registry_cache import diagnose, main

META = {"modelspec.architecture": "stable-diffusion-xl-v1-base"}


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def installed(tmp_path: Path):
    model = checkpoint(tmp_path / "webui" / "models" / "Stable-diffusion" / "m.safetensors", metadata=META)
    cache = tmp_path / "state" / "asset_registry_v1.json"
    AssetRegistry(tmp_path / "webui", cache_path=cache).refresh(checkpoint_paths=[model])
    return tmp_path, model, cache


def test_reports_reuse_and_each_kind_of_miss_without_modifying_anything(installed, capsys) -> None:
    tmp_path, model, cache = installed
    other = checkpoint(tmp_path / "webui" / "models" / "Stable-diffusion" / "new.safetensors", metadata=META)
    before = snapshot_tree(tmp_path)

    report = diagnose(cache=cache, webui_root=None, checkpoints=[model, other])
    assert report["cache"]["state"] == "ok" and report["cache"]["checkpoints_with_digest"] == 1
    warm, cold = report["checkpoints"]
    assert (warm["reason"], warm["needs_full_hash"], warm["exact_resolved_path_is_cached"]) == ("current", False, True)
    assert (cold["reason"], cold["needs_full_hash"]) == ("no_entry", True)

    checkpoint(model, metadata=META, payload=b"changed size")
    changed = diagnose(cache=cache, webui_root=None, checkpoints=[model])["checkpoints"][0]
    assert changed["reason"] == "size_changed" and changed["needs_full_hash"]

    assert main(["--cache", str(cache), "--checkpoint", str(model)]) == 0
    assert json.loads(capsys.readouterr().out)["checkpoints"][0]["reason"] == "size_changed"

    after = snapshot_tree(tmp_path)
    assert {k: v for k, v in after.items() if not k.endswith("m.safetensors")} == {
        k: v for k, v in before.items() if not k.endswith("m.safetensors")
    }


def test_default_output_hides_paths_and_names(installed) -> None:
    tmp_path, model, cache = installed
    # json.dumps escapes backslashes, so a Windows path must be compared in its JSON-escaped form (comparing the raw
    # path made the hidden-path check vacuous and the shown-path check impossible on Windows).
    def escaped(path: Path) -> str:
        return json.dumps(str(path))[1:-1]

    text = json.dumps(diagnose(cache=cache, webui_root=None, checkpoints=[model]))
    assert escaped(tmp_path) not in text and "m.safetensors" not in text
    shown = json.dumps(diagnose(cache=cache, webui_root=None, checkpoints=[model], show_paths=True))
    assert escaped(model) in shown


def test_an_unreadable_cache_is_reported_not_repaired(tmp_path: Path) -> None:
    cache = tmp_path / "state" / "asset_registry_v1.json"
    cache.parent.mkdir()
    cache.write_text("{broken", encoding="utf-8")
    report = diagnose(cache=cache, webui_root=None, checkpoints=[])
    assert report["cache"]["state"] == "unreadable"
    assert cache.read_text(encoding="utf-8") == "{broken"
    assert not cache.with_suffix(".unreadable").exists()


def test_a_moved_workspace_is_visible_as_the_same_file_cached_under_another_path(installed, tmp_path: Path) -> None:
    _tmp, model, cache = installed
    moved = checkpoint(tmp_path / "elsewhere" / model.name, metadata=META)
    item = diagnose(cache=cache, webui_root=None, checkpoints=[moved])["checkpoints"][0]
    assert item["reason"] == "no_entry"
    assert item["exact_resolved_path_is_cached"] is False
    assert item["same_file_name_cached_under_another_path"] is True
