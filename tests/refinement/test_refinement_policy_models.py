from __future__ import annotations

from src.refinement.refinement_policy_models import (
    ADAPTIVE_REFINEMENT_SCHEMA_V1,
    REFINEMENT_DECISION_SCHEMA_V1,
    AdaptiveRefinementIntent,
    RefinementDecisionBundle,
)


def test_adaptive_refinement_intent_round_trip() -> None:
    intent = AdaptiveRefinementIntent(
        enabled=True,
        mode="observe",
        profile_id="auto_v2",
        detector_preference="opencv",
        record_decisions=False,
        algorithm_version="v2",
    )

    restored = AdaptiveRefinementIntent.from_dict(intent.to_dict())

    assert restored == intent
    assert restored.schema == ADAPTIVE_REFINEMENT_SCHEMA_V1


def test_refinement_decision_bundle_round_trip() -> None:
    bundle = RefinementDecisionBundle(
        mode="observe",
        policy_id="observe_v1",
        detector_id="null",
        observation={"scale_band": "unknown"},
        applied_overrides={},
        prompt_patch={},
        notes=("observation_only",),
    )

    restored = RefinementDecisionBundle.from_dict(bundle.to_dict())

    assert restored == bundle
    assert restored.schema == REFINEMENT_DECISION_SCHEMA_V1


def test_invalid_mode_defaults_to_disabled() -> None:
    restored = AdaptiveRefinementIntent.from_dict({"enabled": True, "mode": "chaos"})
    bundle = RefinementDecisionBundle.from_dict({"mode": "chaos"})

    assert restored.mode == "disabled"
    assert bundle.mode == "disabled"
