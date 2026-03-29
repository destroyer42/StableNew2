from __future__ import annotations

from src.pipeline.config_contract_v26 import build_config_layers
from src.pipeline.intent_artifact_contract import (
    INTENT_ARTIFACT_SCHEMA_V1,
    INTENT_ARTIFACT_VERSION_V1,
    build_intent_artifact_contract,
    compute_intent_hash,
    validate_intent_artifact_contract,
)


def test_intent_artifact_contract_is_deterministic_for_equivalent_payloads() -> None:
    left = {
        "source": "run",
        "run_mode": "queue",
        "adaptive_refinement": {"enabled": True, "mode": "observe"},
    }
    right = {
        "adaptive_refinement": {"mode": "observe", "enabled": True},
        "run_mode": "queue",
        "source": "run",
    }

    assert compute_intent_hash(left) == compute_intent_hash(right)


def test_build_config_layers_carries_intent_hash_and_version() -> None:
    layers = build_config_layers(
        intent_config={"run_mode": "queue", "source": "run"},
        execution_config={"prompt": "castle"},
    )
    payload = layers.to_dict()

    assert payload["intent_artifact_schema"] == INTENT_ARTIFACT_SCHEMA_V1
    assert payload["intent_artifact_version"] == INTENT_ARTIFACT_VERSION_V1
    assert payload["intent_hash"] == compute_intent_hash(payload["intent_config"])


def test_validate_intent_artifact_contract_rejects_hash_drift() -> None:
    contract = build_intent_artifact_contract({"run_mode": "queue", "source": "run"})
    contract["intent_payload"]["source"] = "changed"

    errors = validate_intent_artifact_contract(contract)

    assert any("intent_hash" in error for error in errors)
