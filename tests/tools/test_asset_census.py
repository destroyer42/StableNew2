from __future__ import annotations

import json
import struct
from pathlib import Path

from tools.asset_census import AssetRoot, HashCache, census, main, read_safetensors_metadata


def _write_safetensors(
    path: Path, metadata: dict[str, str] | None = None, payload: bytes = b"weights"
) -> None:
    header = {
        "__metadata__": metadata or {},
        "layer": {"data_offsets": [0, len(payload)], "dtype": "F32", "shape": [1]},
    }
    encoded = json.dumps(header).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + payload)


def test_census_reads_safetensors_metadata_streams_hashes_and_finds_duplicates(
    tmp_path: Path,
) -> None:
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    _write_safetensors(root_a / "first.safetensors", {"ss_base_model_version": "sdxl_base_v1-0"})
    (root_b / "copied.safetensors").write_bytes((root_a / "first.safetensors").read_bytes())
    cache = HashCache(tmp_path / "hashes.json")

    result = census([AssetRoot("lora", root_b), AssetRoot("lora", root_a)], hash_cache=cache)

    assert result["asset_count_by_kind"] == {"lora": 2}
    assert len(result["duplicate_sha256_groups"]) == 1
    assert result["assets"][0]["embedded_metadata"]["ss_base_model_version"] == "sdxl_base_v1-0"
    assert result["assets"][0]["inferred_technical_family"]["family"] == "SDXL"
    cache.save()
    assert "sha256" in json.loads((tmp_path / "hashes.json").read_text())["entries"].popitem()[1]


def test_census_handles_dual_embedding_roots_and_same_name_different_hash(tmp_path: Path) -> None:
    active = tmp_path / "embeddings"
    legacy = tmp_path / "models_embeddings"
    active.mkdir()
    legacy.mkdir()
    _write_safetensors(active / "shared.safetensors", payload=b"active")
    _write_safetensors(legacy / "shared.safetensors", payload=b"legacy")

    result = census([AssetRoot("embedding", legacy), AssetRoot("embedding", active)])

    assert result["asset_count_by_kind"] == {"embedding": 2}
    assert len(result["same_name_different_hash_groups"]) == 1
    assert [asset["local_path"] for asset in result["assets"]] == sorted(
        asset["local_path"] for asset in result["assets"]
    )


def test_lora_cache_formats_are_preserved_and_joined_by_exact_hash(tmp_path: Path) -> None:
    loras = tmp_path / "loras"
    extension = tmp_path / "extension"
    loras.mkdir()
    (extension / "known").mkdir(parents=True)
    (extension / "metadata_cache").mkdir()
    _write_safetensors(loras / "portrait.safetensors")
    digest = HashCache(None).sha256(loras / "portrait.safetensors")
    (extension / "known" / f"{digest}.json").write_text('["legacy trigger"]', encoding="utf-8")
    (extension / "metadata_cache" / f"{digest}.json").write_text(
        '{"trainedWords": ["current trigger"], "modelId": 12}', encoding="utf-8"
    )

    result = census([AssetRoot("lora", loras)], cache_roots=[extension])

    records = result["assets"][0]["lora_keyword_enrichment"]
    assert {record["cache_format"] for record in records} == {"legacy_keyword_list", "rich_object"}
    assert result["lora_keyword_cache_hashes"] == [digest]


def test_corrupt_safetensors_metadata_is_reported_without_loading_weights(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.safetensors"
    corrupt.write_bytes(struct.pack("<Q", 50) + b"{}")

    metadata, error = read_safetensors_metadata(corrupt)

    assert metadata == {}
    assert error == "truncated safetensors header"


def test_cli_is_offline_and_deterministic_for_unchanged_inputs(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    _write_safetensors(root / "asset.safetensors")
    output = tmp_path / "inventory.json"

    assert main(["--root", f"checkpoint={root}", "--out", str(output)]) == 0
    first = output.read_text(encoding="utf-8")
    assert main(["--root", f"checkpoint={root}", "--out", str(output)]) == 0

    assert output.read_text(encoding="utf-8") == first
