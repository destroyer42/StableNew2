from __future__ import annotations

import json
from pathlib import Path

from src.review.review_metadata_service import (
    INTERNAL_REVIEW_SUMMARY_SCHEMA,
    REVIEW_METADATA_SCHEMA,
)
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    PORTABLE_REVIEW_KEY,
    PORTABLE_REVIEW_SIDECAR_SUFFIX,
)


def _load_schema_file(name: str) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "docs" / "schemas" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_generation_metadata_schema_example_matches_runtime_constants() -> None:
    payload = _load_schema_file("stablenew.image-metadata.v2.6.json")

    assert payload["schema_id"] == ImageMetadataContractV26.SCHEMA
    assert payload["public_schema_id"] == ImageMetadataContractV26.PUBLIC_SCHEMA
    assert ImageMetadataContractV26.KEY_SCHEMA in payload["required_carrier_keys"]
    assert ImageMetadataContractV26.KEY_PAYLOAD in payload["payload_carrier_keys"]
    assert ImageMetadataContractV26.KEY_PAYLOAD_GZ_B64 in payload["payload_carrier_keys"]


def test_portable_review_schema_example_matches_runtime_constants() -> None:
    payload = _load_schema_file("stablenew.review.v2.6.json")

    assert payload["schema_id"] == REVIEW_METADATA_SCHEMA
    assert payload["namespace_key"] == PORTABLE_REVIEW_KEY
    assert payload["sidecar_suffix"] == PORTABLE_REVIEW_SIDECAR_SUFFIX
    assert "schema" in payload["always_emitted_fields"]
    assert "review_timestamp" in payload["always_emitted_fields"]


def test_normalized_summary_schema_example_matches_runtime_constants() -> None:
    payload = _load_schema_file("portable_review_summary.v2.6.json")

    assert payload["internal_schema_id"] == INTERNAL_REVIEW_SUMMARY_SCHEMA
    assert REVIEW_METADATA_SCHEMA in payload["underlying_source_schema_examples"]
    assert "internal_learning_record" in payload["source_type_values"]
    assert "embedded_review_metadata" in payload["source_type_values"]
    assert "sidecar_review_metadata" in payload["source_type_values"]


def test_artifact_inspection_schema_example_documents_precedence_values() -> None:
    payload = _load_schema_file("artifact_metadata_inspection.v2.6.json")

    assert payload["type_name"] == "ArtifactMetadataInspection"
    assert payload["active_review_precedence_values"] == [
        "internal_learning_record",
        "embedded_review_metadata",
        "sidecar_review_metadata",
        "none",
    ]
    assert "source_diagnostics" in payload["required_top_level_fields"]