from __future__ import annotations

import json
import os
import struct
from pathlib import Path

from src.assets import (
    ActivationRequirement,
    AssetKind,
    AssetMetadataService,
    AssetRegistry,
    CompatibilityStatus,
    EvidenceStrength,
    MetadataSource,
    ModelFamily,
)


def _safe(
    path: Path, metadata: dict[str, object] | None = None, tensors: dict[str, object] | None = None
) -> None:
    header: dict[str, object] = {"__metadata__": metadata or {}}
    header.update(tensors or {})
    encoded = json.dumps(header).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + b"weights")


def _service(
    tmp_path: Path, *, cache_roots: tuple[Path, ...] = ()
) -> tuple[Path, AssetRegistry, AssetMetadataService]:
    webui = tmp_path / "webui"
    registry = AssetRegistry(webui, cache_path=tmp_path / "state" / "registry.json")
    return webui, registry, AssetMetadataService(registry, legacy_keyword_cache_roots=cache_roots)


def test_embedded_metadata_wins_and_conflicts_preserve_lower_precedence_evidence(
    tmp_path: Path,
) -> None:
    webui, _, service = _service(tmp_path)
    lora = webui / "models" / "Lora" / "portrait.safetensors"
    _safe(
        lora,
        {
            "ss_base_model_version": "sdxl_base_v1-0",
            "ss_network_module": "networks.lora",
            "modelspec.name": "Embedded portrait",
        },
    )
    lora.with_name("portrait.civitai.info").write_text(
        json.dumps(
            {
                "baseModel": "SD 1.5",
                "creator": "sidecar creator",
                "trainedWords": ["sidecar trigger"],
                "examplePositivePrompt": "sidecar positive",
                "exampleNegativePrompt": "sidecar negative",
                "recommendedWeight": "0.65",
            }
        ),
        encoding="utf-8",
    )
    lora.with_suffix(".txt").write_text(
        'Trigger words: documented trigger\nPositive prompt: documented positive\n"not a trigger"',
        encoding="utf-8",
    )

    snapshot = service.refresh()
    metadata = snapshot.metadata[0]

    assert metadata.kind is AssetKind.LORA
    assert metadata.base_family.value is ModelFamily.SDXL
    assert metadata.base_family.provenance.source is MetadataSource.EMBEDDED
    assert metadata.activation_keywords.value == ("sidecar trigger",)
    assert metadata.example_positive_prompts.value == ("sidecar positive",)
    assert metadata.example_negative_prompts.value == ("sidecar negative",)
    assert metadata.weight_guidance.value and metadata.weight_guidance.value.default == 0.65
    assert metadata.activation_requirement.value is ActivationRequirement.UNKNOWN
    assert {conflict.field for conflict in metadata.conflicts} == {
        "base_family",
        "activation_keywords",
        "example_positive_prompts",
    }
    assert (
        service.compatibility_with_family(metadata.sha256, ModelFamily.SDXL)
        is CompatibilityStatus.COMPATIBLE
    )
    assert (
        service.compatibility_with_family(metadata.sha256, ModelFamily.SD1)
        is CompatibilityStatus.INCOMPATIBLE
    )


def test_legacy_cache_joins_only_by_exact_hash_and_empty_keywords_remain_unknown(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "extension"
    webui, registry, service = _service(tmp_path, cache_roots=(cache_root,))
    lora = webui / "models" / "Lora" / "same-name.safetensors"
    _safe(lora)
    registry.refresh()
    digest = registry.snapshot.records_for(AssetKind.LORA)[0].sha256
    known = cache_root / "known"
    known.mkdir(parents=True)
    (known / f"{digest}.json").write_text("[]", encoding="utf-8")
    (known / ("a" * 64 + ".json")).write_text('["filename-only"]', encoding="utf-8")

    service.refresh()
    empty = service.metadata_for(digest)
    assert empty is not None
    assert len(empty.legacy_keyword_records) == 1
    assert empty.legacy_keyword_records[0].keywords == ()
    assert empty.activation_keywords.value is None
    assert empty.activation_requirement.value is ActivationRequirement.UNKNOWN

    cache_file = known / f"{digest}.json"
    cache_file.write_text('["exact hash trigger"]', encoding="utf-8")
    os.utime(cache_file, None)
    service.refresh()
    refreshed = service.metadata_for(digest)
    assert refreshed is not None
    assert refreshed.activation_keywords.value == ("exact hash trigger",)
    assert refreshed.activation_keywords.provenance.source is MetadataSource.EXACT_HASH_SIDECAR


def test_embedding_structure_classifies_dual_encoder_sd1_and_unknown_without_filename_hints(
    tmp_path: Path,
) -> None:
    webui, _, service = _service(tmp_path)
    embeddings = webui / "embeddings"
    _safe(
        embeddings / "xl-name-is-not-evidence.safetensors",
        tensors={"clip_l": {"shape": [1, 768]}, "clip_g": {"shape": [1, 1280]}},
    )
    _safe(embeddings / "easynegative.safetensors", tensors={"emb_params": {"shape": [1, 768]}})
    _safe(embeddings / "sdxl-in-name-only.safetensors", tensors={"mystery": {"shape": [1, 1024]}})

    service.refresh()
    profiles = {
        profile.family.value: profile
        for profile in service.snapshot.profiles
        if profile.kind is AssetKind.EMBEDDING
    }
    assert profiles[ModelFamily.SDXL].text_encoder_expectation.value == "dual_encoder_sdxl"
    assert (
        profiles[ModelFamily.SDXL].family.provenance.strength is EvidenceStrength.STRONG_INFERENCE
    )
    assert profiles[ModelFamily.SD1].embedding_dimension.value == 768
    unknown = next(
        profile
        for profile in service.snapshot.profiles
        if profile.family.value is ModelFamily.UNKNOWN
    )
    assert unknown.embedding_dimension.value == 1024
    assert (
        service.compatibility_with_family(unknown.sha256, ModelFamily.SDXL)
        is CompatibilityStatus.UNKNOWN
    )


def test_sidecar_refresh_does_not_carry_metadata_to_changed_sha_or_rehash_unchanged_file(
    tmp_path: Path,
) -> None:
    webui, registry, service = _service(tmp_path)
    lora = webui / "models" / "Lora" / "refresh.safetensors"
    _safe(lora, {"ss_base_model_version": "sdxl"})
    sidecar = lora.with_name("refresh.civitai.info")
    sidecar.write_text('{"creator": "first"}', encoding="utf-8")
    initial = service.refresh().metadata[0]
    sidecar.write_text('{"creator": "second"}', encoding="utf-8")
    os.utime(sidecar, None)
    service.refresh()
    updated = service.metadata_for(initial.sha256)
    assert updated and updated.creator.value == "second"
    assert registry.refresh().hashes_computed == 0

    _safe(lora, {"ss_base_model_version": "sd1"})
    changed = service.refresh().metadata[0]
    assert changed.sha256 != initial.sha256
    assert changed.creator.value == "second"
    assert changed.base_family.value is ModelFamily.SD1


def test_malformed_local_sources_are_reported_without_network_or_asset_mutation(
    tmp_path: Path,
) -> None:
    webui, _, service = _service(tmp_path)
    lora = webui / "models" / "Lora" / "broken.safetensors"
    lora.parent.mkdir(parents=True)
    lora.write_bytes(struct.pack("<Q", 50) + b"{}")
    lora.with_name("broken.civitai.info").write_text("not json", encoding="utf-8")

    metadata = service.refresh().metadata[0]
    assert metadata.base_family.value is ModelFamily.UNKNOWN
    assert metadata.source_errors
    assert service.assets_with_unknown_family()


def test_documentation_only_activation_requirement_is_explicit_and_constructor_is_inert(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    cache_path = tmp_path / "state" / "registry.json"
    registry = AssetRegistry(webui, cache_path=cache_path)
    service = AssetMetadataService(registry)
    assert not cache_path.exists()
    assert service.snapshot.metadata == ()

    lora = webui / "models" / "Lora" / "no-family-in-name.safetensors"
    _safe(lora)
    lora.with_suffix(".txt").write_text(
        'Activation words: documented token\nActivation requirement: required\n"quoted text"',
        encoding="utf-8",
    )
    metadata = service.refresh().metadata[0]
    assert metadata.base_family.value is ModelFamily.UNKNOWN
    assert metadata.activation_keywords.value == ("documented token",)
    assert metadata.activation_requirement.value is ActivationRequirement.REQUIRED
    assert metadata.activation_requirement.provenance.source is MetadataSource.LOCAL_DOCUMENTATION
