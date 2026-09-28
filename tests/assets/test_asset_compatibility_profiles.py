"""Deterministic fixtures for PR-ASSET-120 provenance-rich compatibility evidence.

All fixtures use temporary roots; none reads the operator's real A1111
library, and none contacts a network or CivitAI.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from src.assets import (
    AssetKind,
    AssetRegistry,
    CompatibilityStatus,
    ModelFamily,
)
from src.utils.embedding_scanner import EmbeddingScanner
from src.utils.lora_scanner import LoRAScanner


def _safetensors(path: Path, metadata: dict[str, str] | None = None, payload: bytes = b"x") -> None:
    header = json.dumps({"__metadata__": metadata or {}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)


def _sidecar(model_path: Path, data: dict | str) -> Path:
    sidecar_path = model_path.with_suffix(model_path.suffix + ".civitai.info")
    sidecar_path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return sidecar_path


def test_embedded_metadata_produces_resolved_family_with_provenance(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "style.safetensors"
    _safetensors(path, {"ss_base_model_version": "sdxl_base_v1-0"})

    registry = AssetRegistry(webui, cache_path=cache)
    record = registry.refresh().snapshot.records_for(AssetKind.LORA)[0]

    assert record.compatibility.status is CompatibilityStatus.RESOLVED
    assert record.compatibility.family is ModelFamily.SDXL
    assert any(item.source == "embedded_metadata" for item in record.compatibility.evidence)
    assert record.embedded_metadata_error is None


def test_sidecar_metadata_is_captured_with_location_provenance_and_can_resolve_family(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "no_embedded.safetensors"
    _safetensors(path)  # no embedded metadata
    _sidecar(path, {"baseModel": "SDXL 1.0"})

    registry = AssetRegistry(webui, cache_path=cache)
    record = registry.refresh().snapshot.records_for(AssetKind.LORA)[0]
    location = record.locations[0]

    assert location.sidecar_provenance == "civitai_sidecar"
    assert location.sidecar_metadata == {"baseModel": "SDXL 1.0"}
    assert location.sidecar_error is None
    assert record.compatibility.status is CompatibilityStatus.RESOLVED
    assert record.compatibility.family is ModelFamily.SDXL
    assert any(item.source == "sidecar_metadata" for item in record.compatibility.evidence)


def test_agreeing_embedded_and_sidecar_evidence_resolve_one_family_and_preserve_both_sources(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "agree.safetensors"
    _safetensors(path, {"ss_base_model_version": "sdxl_base_v1-0"})
    _sidecar(path, {"baseModel": "SDXL 1.0"})

    registry = AssetRegistry(webui, cache_path=cache)
    record = registry.refresh().snapshot.records_for(AssetKind.LORA)[0]

    assert record.compatibility.status is CompatibilityStatus.RESOLVED
    assert record.compatibility.family is ModelFamily.SDXL
    sources = {item.source for item in record.compatibility.evidence}
    assert {"embedded_metadata", "sidecar_metadata"} <= sources


def test_disagreeing_embedded_and_sidecar_evidence_is_an_explicit_conflict(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "disagree.safetensors"
    _safetensors(path, {"ss_base_model_version": "sd_v1.5"})
    _sidecar(path, {"baseModel": "SDXL 1.0"})

    registry = AssetRegistry(webui, cache_path=cache)
    record = registry.refresh().snapshot.records_for(AssetKind.LORA)[0]

    assert record.compatibility.status is CompatibilityStatus.CONFLICTING
    assert record.compatibility.family is None
    families = {item.family for item in record.compatibility.evidence}
    assert families == {ModelFamily.SD1, ModelFamily.SDXL}


def test_unrecognized_metadata_and_filename_remain_unknown(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "mystery_asset.safetensors"
    _safetensors(path, {"trainedWords": "not a base model field"})

    registry = AssetRegistry(webui, cache_path=cache)
    record = registry.refresh().snapshot.records_for(AssetKind.LORA)[0]

    assert record.compatibility.status is CompatibilityStatus.UNKNOWN
    assert record.compatibility.family is None
    assert record.compatibility.evidence == ()


def test_malformed_sidecar_records_an_issue_and_does_not_fail_refresh(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "broken_sidecar.safetensors"
    _safetensors(path)
    _sidecar(path, "not valid json {{{")

    registry = AssetRegistry(webui, cache_path=cache)
    result = registry.refresh()  # must not raise
    record = result.snapshot.records_for(AssetKind.LORA)[0]
    location = record.locations[0]

    assert location.sidecar_error is not None
    assert location.sidecar_metadata == {}
    assert record.compatibility.status is CompatibilityStatus.UNKNOWN


def test_duplicate_bytes_share_one_sha_but_preserve_distinct_location_sidecar_metadata(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    first = webui / "models" / "Lora" / "first.safetensors"
    duplicate = webui / "models" / "LyCORIS" / "second.safetensors"
    _safetensors(first)
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_bytes(first.read_bytes())
    _sidecar(first, {"baseModel": "SD 1.5"})
    _sidecar(duplicate, {"baseModel": "SD 1.5"})

    registry = AssetRegistry(webui, cache_path=cache)
    record = registry.refresh().snapshot.records_for(AssetKind.LORA)[0]

    assert len(record.locations) == 2
    assert {location.sidecar_metadata.get("baseModel") for location in record.locations} == {"SD 1.5"}
    assert {str(location.sidecar_path) for location in record.locations} == {
        str(first.with_suffix(first.suffix + ".civitai.info")),
        str(duplicate.with_suffix(duplicate.suffix + ".civitai.info")),
    }


def test_conflicting_sidecars_on_duplicate_bytes_are_not_collapsed_to_first_location(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    first = webui / "models" / "Lora" / "a_first.safetensors"
    duplicate = webui / "models" / "LyCORIS" / "b_second.safetensors"
    _safetensors(first)
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_bytes(first.read_bytes())
    _sidecar(first, {"baseModel": "SD 1.5"})
    _sidecar(duplicate, {"baseModel": "SDXL 1.0"})

    registry = AssetRegistry(webui, cache_path=cache)
    record = registry.refresh().snapshot.records_for(AssetKind.LORA)[0]

    assert record.compatibility.status is CompatibilityStatus.CONFLICTING
    sidecar_evidence = [
        item for item in record.compatibility.evidence if item.source == "sidecar_metadata"
    ]
    assert {item.family for item in sidecar_evidence} == {ModelFamily.SD1, ModelFamily.SDXL}


def test_sidecar_change_and_removal_update_profile_without_rehashing_unchanged_model_bytes(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "evolving.safetensors"
    _safetensors(path)
    sidecar_path = _sidecar(path, {"baseModel": "SD 1.5"})

    registry = AssetRegistry(webui, cache_path=cache)
    first_result = registry.refresh()
    assert first_result.hashes_computed == 1
    record = first_result.snapshot.records_for(AssetKind.LORA)[0]
    assert record.compatibility.family is ModelFamily.SD1

    # Sidecar content changes; model bytes are untouched.
    sidecar_path.write_text(json.dumps({"baseModel": "SDXL 1.0"}), encoding="utf-8")
    second_result = registry.refresh()
    assert second_result.hashes_computed == 0
    record = second_result.snapshot.records_for(AssetKind.LORA)[0]
    assert record.compatibility.family is ModelFamily.SDXL

    # Sidecar removed entirely; evidence must stop projecting it, still no rehash.
    sidecar_path.unlink()
    third_result = registry.refresh()
    assert third_result.hashes_computed == 0
    record = third_result.snapshot.records_for(AssetKind.LORA)[0]
    assert record.locations[0].sidecar_metadata == {}
    assert record.compatibility.status is CompatibilityStatus.UNKNOWN


def test_v1_cache_upgrades_without_rehashing_unchanged_model_bytes(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "legacy.safetensors"
    _safetensors(path, {"ss_base_model_version": "sdxl_base_v1-0"})
    stat = path.stat()

    cache.parent.mkdir(parents=True, exist_ok=True)
    legacy_entry = {
        "path": str(path.resolve()),
        "root": str((webui / "models" / "Lora").resolve()),
        "kind": AssetKind.LORA.value,
        "name": path.stem,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        # Deliberately wrong, to prove a valid v1 entry is trusted/reused as-is.
        "sha256": "0" * 64,
        "metadata": {"ss_base_model_version": "sdxl_base_v1-0"},
        "provenance": "safetensors_header",
        "metadata_error": None,
    }
    cache.write_text(
        json.dumps({"version": 1, "entries": {str(path.resolve()): legacy_entry}}),
        encoding="utf-8",
    )

    registry = AssetRegistry(webui, cache_path=cache)
    result = registry.refresh()

    assert result.hashes_computed == 0  # the v1 entry already matched size/mtime/kind
    record = result.snapshot.records_for(AssetKind.LORA)[0]
    assert record.sha256 == "0" * 64  # reused, not recomputed
    assert record.compatibility.family is ModelFamily.SDXL

    upgraded = json.loads(cache.read_text(encoding="utf-8"))
    assert upgraded["version"] == 2


def test_hash_invalidation_still_works_when_model_bytes_change(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    path = webui / "models" / "Lora" / "changing.safetensors"
    _safetensors(path)

    registry = AssetRegistry(webui, cache_path=cache)
    assert registry.refresh().hashes_computed == 1
    assert registry.refresh().hashes_computed == 0

    path.write_bytes(path.read_bytes() + b"more-bytes")
    assert registry.refresh().hashes_computed == 1


def test_legacy_scanner_projections_remain_functional_over_the_enriched_registry(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache = tmp_path / "state" / "assets.json"
    _safetensors(
        webui / "models" / "Lora" / "keep_working.safetensors",
        {"ss_base_model_version": "sd_v1.5"},
    )
    _safetensors(webui / "embeddings" / "still_here.safetensors")

    registry = AssetRegistry(webui, cache_path=cache)
    assert (
        LoRAScanner(webui, registry=registry).scan_loras()["keep_working"].path.name
        == "keep_working.safetensors"
    )
    assert EmbeddingScanner(str(webui), registry=registry).get_embedding_names() == ["still_here"]
