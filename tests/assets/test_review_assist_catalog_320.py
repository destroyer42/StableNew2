"""The two Smart Review models are pinned byte-for-byte in the curated catalog and are never marked ready by files alone."""

from __future__ import annotations

import re

import pytest

from src.assets.resource_catalog import load_catalog
from src.conditioning.reference_map import auxiliary

FLORENCE_REVISION = "0b03b6f15a4a211370fb204aee4e7dd48887ea37"
SAM_REVISION = "ee5bba1d82bb8749febdf90f45e84b687142ba03"
FLORENCE_ROLES = {
    "weights",
    "model_config",
    "generation_config",
    "image_processor_config",
    "processor_config",
    "tokenizer",
    "tokenizer_config",
    "special_tokens_map",
    "added_tokens",
    "vocabulary",
    "merges",
}


@pytest.fixture(scope="module")
def resources():
    return {item.id: item for item in load_catalog().resources}


def variants(resource):
    return [variant for file in resource.files for variant in file.variants]


def test_florence_is_the_native_conversion_with_every_required_file_pinned(resources):
    resource = resources["florence-2-base-ft"]
    assert resource.source["publisher_repo"] == "florence-community/Florence-2-base-ft"
    assert resource.source["revision"] == FLORENCE_REVISION
    roles = [file.role for file in resource.files]
    assert len(roles) == len(set(roles)) == 11 and set(roles) == FLORENCE_ROLES
    assert all(file.required for file in resource.files)
    for variant in variants(resource):
        assert re.fullmatch(r"[0-9a-f]{64}", variant.sha256 or ""), variant.variant_id
        assert variant.size_bytes and variant.hash_status == "verified_upstream"
        assert variant.hash_basis == "pinned_revision_byte_hash"
        assert not variant.variant_id.endswith((".bin", ".pt", ".pth", ".ckpt", ".pkl", ".py"))
    weights = next(v for v in variants(resource) if v.variant_id == "model.safetensors")
    assert weights.sha256 == "ab06dea66b16d5e54513256d64854be2194443452fd0d84353b40a278bf87d42"
    assert weights.size_bytes == 463178864


def test_florence_keeps_the_original_identity_only_as_lineage(resources):
    raw = resources["florence-2-base-ft"].source
    assert raw["publisher_repo"] == "florence-community/Florence-2-base-ft"
    assert raw["lineage"]["original_repo"] == "microsoft/Florence-2-base-ft"
    text = repr(raw)
    assert "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e" in text  # lineage evidence is retained
    assert raw["license"]["status"] in {"model_card_declared", "unknown"}


def test_sam_pins_weights_and_the_three_json_files_but_not_the_unneeded_video_file(resources):
    resource = resources["sam-2-1-small"]
    assert resource.source["revision"] == SAM_REVISION
    by_name = {v.variant_id: v for v in variants(resource)}
    assert by_name["model.safetensors"].hash_basis == "hub_lfs_oid"
    for name in ("config.json", "preprocessor_config.json", "processor_config.json"):
        assert (
            by_name[name].hash_status == "verified_upstream"
            and by_name[name].hash_basis == "pinned_revision_byte_hash"
        )
    assert (
        by_name["config.json"].sha256
        == "97ff9f65b76d107acda4247885f0a5555d0048850ae3c5f97183df289aaecde9"
    )
    required = {file.role for file in resource.files if file.required}
    assert "video_processor_config" not in required
    assert by_name["video_preprocessor_config.json"].sha256 is None


@pytest.mark.parametrize("resource_id", ["florence-2-base-ft", "sam-2-1-small"])
def test_files_alone_never_make_the_capability_ready(resources, resource_id):
    capability = resources[resource_id].capability
    assert capability.policy == "needs_integration"
    assert "inference_not_qualified" in capability.reason_codes
    assert "qualified" in capability.basis and "not qualified" in capability.basis


def test_review_modalities_resolve_to_catalog_resources(resources):
    for modality in ("sam2", "florence2"):
        assert auxiliary.RESOURCE_BY_MODALITY[modality] in resources
