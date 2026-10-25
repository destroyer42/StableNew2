"""The frozen snapshot of an ordinary (single-variable) Learning experiment.

Toolkit-neutral: the controller supplies what it resolved at Preview and this module lays it out.  The layout is
schema 2; the independent-baseline keys are additive, so an older reader simply ignores them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from src.learning import baseline_authoring as authoring


def ordinary_snapshot(
    experiment: Any,
    *,
    baseline: Mapping[str, Any],
    negative_prompt: str,
    seed_policy: Mapping[str, Any],
    prompt_source: Mapping[str, Any],
    model_context: Any,
    authored: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "schema_version": 2,
        "experiment_id": experiment.experiment_id,
        "display_name": experiment.name,
        "baseline_config": baseline,
        "prompt_text": experiment.prompt_text,
        "negative_prompt_text": negative_prompt,
        "stage": experiment.stage,
        "variable_under_test": experiment.variable_under_test,
        "variant_values": list(experiment.values or []),
        "images_per_value": max(1, int(experiment.images_per_value or 1)),
        "seed_policy": seed_policy,
        "experiment_timestamp": datetime.utcnow().strftime("%Y%m%d-%H%M%S"),
        "prompt_source": prompt_source,
        "input_image_path": experiment.input_image_path,
        "model_policy_context": model_context,
    }
    snapshot.update(authored or {})
    return snapshot


def authored_fields(
    experiment: Any,
    baseline: Mapping[str, Any],
    stage: str,
    *,
    draft_signature: str,
    variable: str,
    variant_settings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Where the baseline came from, the stage chain Run submits, the observed source and each variant's settings."""
    return {
        authoring.AUTHORING_KEY: {
            **experiment.baseline_authoring,
            "draft_signature": draft_signature,
        },
        "stage_chain": [stage],
        "input_image": authoring.source_image_identity(experiment.input_image_path),
        "effective_settings": authoring.effective_settings(baseline, stage, variable=variable),
        "variant_effective_settings": variant_settings,
    }
