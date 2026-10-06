from __future__ import annotations

import json
import struct
from pathlib import Path

from src.assets import AssetKind, AssetRegistry
from src.utils.embedding_scanner import EmbeddingScanner
from src.utils.lora_scanner import LoRAScanner


def _safe(path: Path, metadata: dict[str, str] | None = None, payload: bytes = b"x") -> None:
    header = json.dumps({"__metadata__": metadata or {}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)


def test_identity_cache_duplicates_changes_and_active_embedding_root(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    first = webui / "models" / "Lora" / "same.safetensors"
    duplicate = webui / "models" / "LyCORIS" / "copy.safetensors"
    _safe(first, {"ss_base_model_version": "sdxl"})
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_bytes(first.read_bytes())
    _safe(webui / "embeddings" / "active.safetensors")
    _safe(webui / "models" / "embeddings" / "legacy.safetensors")
    registry = AssetRegistry(webui, cache_path=cache)
    first_result = registry.refresh()
    assert first_result.hashes_computed == 3
    assert len(registry.snapshot.records_for(AssetKind.EMBEDDING)) == 1
    assert len(registry.snapshot.records_for(AssetKind.LORA)) == 1
    assert len(registry.snapshot.records_for(AssetKind.LORA)[0].locations) == 2
    second = registry.refresh()
    assert second.hashes_computed == 0
    assert second.hash_cache_hits == 3
    first.write_bytes(first.read_bytes() + b"changed")
    assert registry.refresh(kinds={AssetKind.LORA}).hashes_computed == 1


def test_registry_handles_corrupt_cache_and_legacy_projections_do_not_write_old_caches(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    cache.parent.mkdir()
    cache.write_text("not json", encoding="utf-8")
    _safe(webui / "models" / "Lora" / "style.safetensors")
    _safe(webui / "embeddings" / "negative.safetensors")
    registry = AssetRegistry(webui, cache_path=cache)
    assert registry.refresh().hashes_computed == 2
    assert (
        LoRAScanner(webui, registry=registry).scan_loras()["style"].path.name == "style.safetensors"
    )
    assert EmbeddingScanner(str(webui), registry=registry).get_embedding_names() == ["negative"]
    assert not (tmp_path / "data" / "lora_cache.json").exists()
    assert not (tmp_path / "data" / "embedding_cache.json").exists()


def test_cached_snapshot_reads_only_the_persisted_cache_and_never_scans_or_hashes(tmp_path: Path) -> None:
    """PR-IMG-117: UI threads may read decisions from the last persisted snapshot without hashing anything."""

    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    lora = webui / "models" / "Lora" / "one.safetensors"
    _safe(lora, {"ss_base_model_version": "flux2_klein_4b"})

    cold = AssetRegistry(webui, cache_path=cache)
    assert cold.cached_snapshot().records == ()  # no cache yet: nothing is scanned or hashed
    assert not cache.exists()

    AssetRegistry(webui, cache_path=cache).refresh()
    warm = AssetRegistry(webui, cache_path=cache)
    (record,) = warm.cached_snapshot().records_for(AssetKind.LORA)
    assert record.embedded_metadata["ss_base_model_version"] == "flux2_klein_4b"

    _safe(webui / "models" / "Lora" / "added-later.safetensors")
    assert len(warm.cached_snapshot().records_for(AssetKind.LORA)) == 1  # a new file is invisible until a refresh
