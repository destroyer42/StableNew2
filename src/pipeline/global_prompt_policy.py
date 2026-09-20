"""Freeze and read the operator-selected global prompt policy.

Global prompt text and enablement are run intent.  New work therefore carries
these values in its execution configuration rather than consulting mutable
prompt files while it runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

GLOBAL_NEGATIVE_STAGE_FLAGS = (
    "apply_global_negative_txt2img",
    "apply_global_negative_img2img",
    "apply_global_negative_adetailer",
    "apply_global_negative_upscale",
)
GLOBAL_POSITIVE_STAGE_FLAG = "apply_global_positive_txt2img"
FROZEN_POLICY_SOURCE = "frozen_njr"
LEGACY_POLICY_SOURCE = "legacy_runtime_fallback"


def apply_global_prompt_policy(
    config: Mapping[str, Any] | None,
    *,
    positive_enabled: bool,
    positive_text: str,
    negative_enabled: bool,
    negative_text: str,
    source: str = FROZEN_POLICY_SOURCE,
) -> dict[str, Any]:
    """Return an isolated config with one explicit, stage-consistent policy."""

    result = deepcopy(dict(config or {}))
    pipeline = dict(result.get("pipeline") or {})
    pipeline[GLOBAL_POSITIVE_STAGE_FLAG] = bool(positive_enabled)
    for key in GLOBAL_NEGATIVE_STAGE_FLAGS:
        pipeline[key] = bool(negative_enabled)
    result["pipeline"] = pipeline
    result["global_positive_prompt"] = str(positive_text or "").strip()
    result["global_negative_prompt"] = str(negative_text or "").strip()
    result["global_prompt_policy_source"] = str(source or FROZEN_POLICY_SOURCE)
    return result


def has_frozen_global_prompt_policy(config: Mapping[str, Any] | None) -> bool:
    """Whether an execution config contains the complete modern policy."""

    data = dict(config or {})
    pipeline = data.get("pipeline")
    return (
        str(data.get("global_prompt_policy_source") or "") == FROZEN_POLICY_SOURCE
        and "global_positive_prompt" in data
        and "global_negative_prompt" in data
        and isinstance(pipeline, Mapping)
        and GLOBAL_POSITIVE_STAGE_FLAG in pipeline
        and all(key in pipeline for key in GLOBAL_NEGATIVE_STAGE_FLAGS)
    )

