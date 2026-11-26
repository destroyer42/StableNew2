"""N1b target verdict for the SDXL-only Learning studies (Embedding, LoRA Composition, Prompt Slot, Two-Axis Grid,
Model Comparison candidates).

A thin adapter over ``src/image_backends/sdxl_target.py``: it reads the study's model and backend from the Learning
baseline and the installed observed-execution index, and nothing else. A study runs with ``target.policy`` (the SDXL
policy carrying the evidence tier) and freezes ``target.warnings`` into its snapshot, so Preview shows them and Queue
records them as accepted in each job's provenance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.model_policy import ModelPolicy
from src.image_backends.sdxl_target import SdxlTarget, assess_sdxl_target
from src.pipeline.policy_warnings import SURFACE_DESKTOP, PolicyWarning, with_accepted_warnings

#: Snapshot key holding the frozen ``PolicyWarning`` records a study's Preview showed.
SNAPSHOT_WARNINGS_KEY = "policy_warnings"


def baseline_backend(baseline: Mapping[str, Any]) -> str:
    return str(
        normalize_image_backend_options(baseline.get("backend_options"))["image"]["backend_id"]
    )


def study_target(
    policy: ModelPolicy,
    baseline: Mapping[str, Any],
    *,
    operation: str,
    feature: str,
    model: str | None = None,
    backend_id: str | None = None,
) -> SdxlTarget:
    from src.history.observed_execution import observed_runs_lookup
    from src.learning.model_policy_service import selected_model

    name = model if model is not None else selected_model(dict(baseline), "txt2img")
    return assess_sdxl_target(
        policy,
        model=name,
        operation=operation,
        backend_id=backend_id if backend_id is not None else baseline_backend(baseline),
        feature=feature,
        observed=observed_runs_lookup(),
    )


def warning_records(targets: Sequence[SdxlTarget]) -> list[dict[str, str]]:
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for target in targets:
        for warning in target.warnings:
            seen.setdefault(warning.key, warning.as_dict())
    return list(seen.values())


def frozen_warnings(snapshot: Mapping[str, Any]) -> tuple[PolicyWarning, ...]:
    raw = snapshot.get(SNAPSHOT_WARNINGS_KEY)
    if not isinstance(raw, list):
        return ()
    return tuple(PolicyWarning.from_dict(item) for item in raw if isinstance(item, Mapping))


def accept_frozen_warnings[R](record: R, snapshot: Mapping[str, Any]) -> R:
    """``record`` with the warnings its study's Preview showed recorded as accepted (Queue is the acceptance)."""

    return cast(
        R, with_accepted_warnings(record, frozen_warnings(snapshot), surface=SURFACE_DESKTOP)
    )


__all__ = [
    "SNAPSHOT_WARNINGS_KEY",
    "accept_frozen_warnings",
    "baseline_backend",
    "frozen_warnings",
    "study_target",
    "warning_records",
]
