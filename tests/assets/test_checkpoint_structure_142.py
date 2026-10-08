"""Conservative structural family evidence and header-only cache upgrades."""

import json
import struct

import pytest

from src.assets import AssetRegistry, CompatibilityStatus, EvidenceConfidence, ModelFamily
from src.assets.checkpoint_structure import checkpoint_header_evidence
from src.image_backends.model_policy import resolve_model_policy
from src.learning.model_evidence_readiness import prepare_comparison_evidence
from tests.assets.checkpoint_fixtures import checkpoint, tensor_checkpoint


def test_structure_without_metadata_is_registry_evidence(tmp_path):
    path = tensor_checkpoint(tmp_path / "ordinary.safetensors")
    registry = AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json")
    inspection = registry.inspect_checkpoint(path)
    assert not hasattr(inspection, "sha256")
    assert not registry.cache_path.exists()
    assert inspection.compatibility.family is ModelFamily.SDXL
    assert inspection.compatibility.evidence[0].confidence is EvidenceConfidence.STRUCTURAL
    policy = resolve_model_policy(path.stem, family_lookup=lambda _: inspection.compatibility)
    assert policy.family == "sdxl" and policy.evidence == "registry_evidence"


@pytest.mark.parametrize("architecture", ["refiner", "inpaint"])
def test_unsupported_sdxl_architecture_never_gets_base_policy(tmp_path, architecture):
    path = tensor_checkpoint(
        tmp_path / "candidate.safetensors",
        architecture=architecture,
        metadata={"ss_base_model_version": "sdxl"},
    )
    registry = AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json")
    inspection = registry.inspect_checkpoint(path)
    assert inspection.compatibility.family is ModelFamily.SDXL
    assert (
        resolve_model_policy(path.stem, family_lookup=lambda _: inspection.compatibility).evidence
        == "unknown_evidence"
    )
    entries = [
        {"name": "candidate", "filename": str(path)},
        {"name": "other", "filename": str(tensor_checkpoint(tmp_path / "other.safetensors"))},
    ]
    with pytest.raises(ValueError, match=f"candidate: .*sdxl_{architecture}"):
        prepare_comparison_evidence(["candidate", "other"], entries, registry=registry)
    assert not registry.cache_path.exists()  # no full hash solely to classify a rejected target


@pytest.mark.parametrize(
    "metadata,sidecar",
    [
        ({"ss_base_model_version": "sd_v1.5"}, None),
        ({"modelspec.architecture": "stable-diffusion-xl-v1-refiner"}, None),
        ({}, {"baseModel": "SD 2.1"}),
    ],
)
def test_structural_and_explicit_metadata_conflicts(tmp_path, metadata, sidecar):
    path = tensor_checkpoint(tmp_path / "candidate.safetensors", metadata=metadata)
    if sidecar:
        path.with_suffix(".civitai.info").write_text(json.dumps(sidecar))
    inspection = AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json").inspect_checkpoint(
        path
    )
    assert inspection.compatibility.status is CompatibilityStatus.CONFLICTING
    assert (
        resolve_model_policy(path.stem, family_lookup=lambda _: inspection.compatibility).evidence
        == "conflicting_evidence"
    )


def test_unclassified_metadata_does_not_suppress_distinct_structure(tmp_path):
    path = tensor_checkpoint(
        tmp_path / "candidate.safetensors", metadata={"modelspec.architecture": "custom derivative"}
    )
    profile = AssetRegistry(tmp_path).inspect_checkpoint(path).compatibility
    assert profile.family is ModelFamily.SDXL


@pytest.mark.parametrize(
    "damage",
    [
        "short_length",
        "short_header",
        "oversized",
        "invalid_json",
        "wrong_shape",
        "negative_offset",
        "out_of_bounds",
        "duplicate",
        "wrong_dtype",
    ],
)
def test_malformed_headers_cannot_admit_a_target(tmp_path, damage):
    path = tensor_checkpoint(
        tmp_path / "candidate.safetensors", metadata={"ss_base_model_version": "sdxl"}
    )
    if damage == "short_length":
        path.write_bytes(b"short")
    elif damage == "short_header":
        path.write_bytes(struct.pack("<Q", 100) + b"{}")
    elif damage == "oversized":
        path.write_bytes(struct.pack("<Q", 64 * 1024 * 1024 + 1))
    elif damage == "invalid_json":
        path.write_bytes(struct.pack("<Q", 1) + b"{")
    elif damage == "duplicate":
        h = b'{"__metadata__":{},"__metadata__":{}}'
        path.write_bytes(struct.pack("<Q", len(h)) + h)
    else:
        with path.open("rb") as stream:
            size = struct.unpack("<Q", stream.read(8))[0]
            header = json.loads(stream.read(size))
        tensor = header["model.diffusion_model.input_blocks.0.0.weight"]
        if damage == "wrong_shape":
            tensor["shape"] = [320, 4, 3, 4]
        elif damage == "negative_offset":
            tensor["data_offsets"][0] = -1
        elif damage == "wrong_dtype":
            tensor["dtype"] = "imaginary"
        else:
            tensor["data_offsets"][1] = path.stat().st_size + 100
        encoded = json.dumps(header).encode()
        with path.open("wb") as stream:
            stream.write(struct.pack("<Q", len(encoded)) + encoded)
            stream.truncate(20_000_000)
    inspection = AssetRegistry(tmp_path).inspect_checkpoint(path)
    assert inspection.compatibility.structural_error
    assert (
        resolve_model_policy(path.stem, family_lookup=lambda _: inspection.compatibility).evidence
        == "unknown_evidence"
    )


def test_non_sdxl_signature_conflicts_with_sdxl_metadata(tmp_path):
    path = tensor_checkpoint(
        tmp_path / "candidate.safetensors", metadata={"ss_base_model_version": "sdxl"}
    )
    with path.open("rb") as stream:
        size = struct.unpack("<Q", stream.read(8))[0]
        header = json.loads(stream.read(size))
    header.pop("model.diffusion_model.label_emb.0.0.weight")
    header.pop("model.diffusion_model.input_blocks.7.1.transformer_blocks.9.attn2.to_k.weight")
    header["model.diffusion_model.input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight"][
        "shape"
    ] = [640, 768]
    offset = 0
    import math

    for name, tensor in header.items():
        if name == "__metadata__":
            continue
        end = offset + math.prod(tensor["shape"]) * 2
        tensor["data_offsets"] = [offset, end]
        offset = end
    encoded = json.dumps(header).encode()
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(encoded)) + encoded)
        stream.truncate(8 + len(encoded) + offset)
    profile = AssetRegistry(tmp_path).inspect_checkpoint(path).compatibility
    assert profile.checkpoint_architecture == "sd1"
    assert profile.status is CompatibilityStatus.CONFLICTING


def test_header_upgrade_reuses_existing_byte_identity_then_warm_reads_nothing(
    tmp_path, monkeypatch
):
    paths = [tensor_checkpoint(tmp_path / f"{name}.safetensors") for name in ("one", "two")]
    cache = tmp_path / "cache.json"
    registry = AssetRegistry(tmp_path, cache_path=cache)
    registry.refresh(checkpoint_paths=paths)
    old = json.loads(cache.read_text())
    for entry in old["entries"].values():
        entry.pop("structure")
    cache.write_text(json.dumps(old))
    monkeypatch.setattr(
        "src.assets.registry.hashlib.sha256", lambda: pytest.fail("header upgrade rehash")
    )
    entries = [{"name": p.stem, "filename": str(p)} for p in paths]
    evidence = prepare_comparison_evidence(
        [p.stem for p in paths], entries, registry=AssetRegistry(tmp_path, cache_path=cache)
    )
    assert evidence.policy_lookups == 2
    for path in paths:
        assert (
            evidence.model_identities[path.stem]["sha256"]
            == old["entries"][str(path.resolve())]["sha256"]
        )
    monkeypatch.setattr(
        "src.assets.registry.checkpoint_header_evidence", lambda *_: pytest.fail("warm header read")
    )
    monkeypatch.setattr(AssetRegistry, "refresh", lambda *a, **k: pytest.fail("warm refresh"))
    prepare_comparison_evidence(
        [p.stem for p in paths], entries, registry=AssetRegistry(tmp_path, cache_path=cache)
    )


def test_unsupported_format_and_filename_hint_stay_unverified_without_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.assets.registry.hashlib.sha256", lambda: pytest.fail("hash solely for family")
    )
    for path in (tmp_path / "sdxl.ckpt", tmp_path / "sdxl.safetensors"):
        checkpoint(path)
        other = tensor_checkpoint(tmp_path / "other.safetensors")
        with pytest.raises(
            ValueError, match="unsupported checkpoint format|structure unrecognized"
        ):
            prepare_comparison_evidence(
                [path.stem, "other"],
                [{"name": p.stem, "filename": str(p)} for p in (path, other)],
                registry=AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json"),
            )


def test_partial_signature_does_not_accept_metadata_override(tmp_path):
    path = tensor_checkpoint(tmp_path / "candidate.safetensors")
    evidence = checkpoint_header_evidence(path)
    assert evidence["structure"]["architecture"] == "sdxl_base"
    # A header lacking tensors never becomes structurally recognized.
    checkpoint(path)
    assert checkpoint_header_evidence(path)["structure"]["architecture"] == "unrecognized"


def test_truncated_tensor_payload_refuses_structural_admission(tmp_path):
    path = tensor_checkpoint(tmp_path / "candidate.safetensors")
    with path.open("r+b") as stream:
        stream.truncate(path.stat().st_size - 1)
    inspection = AssetRegistry(tmp_path).inspect_checkpoint(path)
    assert inspection.compatibility.structural_error
    assert inspection.compatibility.checkpoint_architecture == "unrecognized"
