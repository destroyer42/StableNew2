from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


INTENT_ARTIFACT_SCHEMA_V1 = "stablenew.intent-artifact.v1"
INTENT_ARTIFACT_VERSION_V1 = "1.0"
_INTENT_TOP_LEVEL_KEYS = (
    "run_mode",
    "source",
    "prompt_source",
    "prompt_pack_id",
    "adaptive_refinement",
    "secondary_motion",
    "config_snapshot_id",
    "requested_job_label",
    "selected_row_ids",
    "tags",
    "pipeline_state_snapshot",
)


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


def canonicalize_intent_artifact(value: Any) -> dict[str, Any]:
    """Return the stable, hashable intent payload used for persistence/replay."""
    data = _mapping_dict(value)
    normalized: dict[str, Any] = {}
    for key in _INTENT_TOP_LEVEL_KEYS:
        if key not in data:
            continue
        item = data[key]
        if item in (None, ""):
            continue
        if isinstance(item, Mapping) and not item:
            continue
        normalized[key] = deepcopy(item)
    return normalized


def compute_intent_hash(value: Any) -> str:
    payload = canonicalize_intent_artifact(value)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_intent_artifact_contract(value: Any) -> dict[str, Any]:
    payload = canonicalize_intent_artifact(value)
    return {
        "intent_artifact_schema": INTENT_ARTIFACT_SCHEMA_V1,
        "intent_artifact_version": INTENT_ARTIFACT_VERSION_V1,
        "intent_hash": compute_intent_hash(payload),
        "intent_payload": deepcopy(payload),
    }


def validate_intent_artifact_contract(contract: Mapping[str, Any] | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, Mapping):
        return ["intent artifact contract must be a mapping"]

    schema = str(contract.get("intent_artifact_schema") or "")
    version = str(contract.get("intent_artifact_version") or "")
    if schema != INTENT_ARTIFACT_SCHEMA_V1:
        errors.append(f"intent_artifact_schema must be {INTENT_ARTIFACT_SCHEMA_V1}")
    if version != INTENT_ARTIFACT_VERSION_V1:
        errors.append(f"intent_artifact_version must be {INTENT_ARTIFACT_VERSION_V1}")

    payload = contract.get("intent_payload")
    if not isinstance(payload, Mapping):
        errors.append("intent_payload must be a mapping")
        return errors

    expected_hash = compute_intent_hash(payload)
    actual_hash = str(contract.get("intent_hash") or "")
    if not actual_hash:
        errors.append("intent_hash is required")
    elif actual_hash != expected_hash:
        errors.append("intent_hash does not match canonicalized intent_payload")
    return errors


__all__ = [
    "INTENT_ARTIFACT_SCHEMA_V1",
    "INTENT_ARTIFACT_VERSION_V1",
    "build_intent_artifact_contract",
    "canonicalize_intent_artifact",
    "compute_intent_hash",
    "validate_intent_artifact_contract",
]
