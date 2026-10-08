"""Ordinary Learning executor-base freeze and explicit saved-preview admission."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

BASE_CONTRACT = "learning_executor_base/1"
PROMPT_SEMANTICS = "executor_base_before_globals_and_optimizer"


def freeze_preview_global_policy(config: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze only supplied run intent; preserve explicit stage enablement."""
    from src.pipeline.global_prompt_policy import (
        GLOBAL_NEGATIVE_STAGE_FLAGS,
        GLOBAL_POSITIVE_STAGE_FLAG,
        apply_global_prompt_policy,
    )

    pipeline = dict(config.get("pipeline") or {})
    frozen = apply_global_prompt_policy(
        config,
        positive_enabled=bool(pipeline.get(GLOBAL_POSITIVE_STAGE_FLAG, False)),
        positive_text=str(config.get("global_positive_prompt") or ""),
        negative_enabled=bool(pipeline.get("apply_global_negative_txt2img", True)),
        negative_text=str(config.get("global_negative_prompt") or ""),
    )
    for key in (GLOBAL_POSITIVE_STAGE_FLAG, *GLOBAL_NEGATIVE_STAGE_FLAGS):
        if key in pipeline:
            frozen["pipeline"][key] = bool(pipeline[key])
    return frozen


def freeze_ordinary_prompt_source(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the row once; selected negative is its display projection."""
    from src.learning.experiment_freeze import freeze_prompt_pack_source

    source = freeze_prompt_pack_source(
        metadata, apply_global_negative=False, include_selected_negative=False
    )
    source.update(executor_base_contract=BASE_CONTRACT, prompt_semantics=PROMPT_SEMANTICS)
    return source


def validate_ordinary_prompt_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Admit safe previews unchanged; refuse legacy preapplication, never repair it."""
    from src.pipeline.global_prompt_policy import has_frozen_global_prompt_policy

    if not snapshot:
        return
    source = dict(snapshot.get("prompt_source") or {})
    baseline = dict(snapshot.get("baseline_config") or {})
    if not has_frozen_global_prompt_policy(baseline):
        raise ValueError(
            "Saved Learning preview has no frozen global policy. Rebuild Preview before Run."
        )
    contract = source.get("executor_base_contract")
    if contract:
        if (
            contract != BASE_CONTRACT
            or source.get("prompt_semantics") != PROMPT_SEMANTICS
            or not has_frozen_global_prompt_policy(baseline)
        ):
            raise ValueError("Invalid frozen Learning prompt contract. Rebuild Preview before Run.")
        if source.get("prompt_source") == "pack" and (
            snapshot.get("prompt_text") != source.get("rendered_positive_prompt")
            or snapshot.get("negative_prompt_text") != source.get("rendered_negative_prompt")
        ):
            raise ValueError("Frozen Learning base prompt mismatch. Rebuild Preview before Run.")
        return
    # The old ordinary Pack freeze passed enabled txt2img Global Negative to
    # the resolver, even for other target stages. Do not guess it away in text.
    pipeline = dict(baseline.get("pipeline") or {})
    stage = str(snapshot.get("stage") or "txt2img").strip().lower()
    if (
        source.get("prompt_source") == "pack"
        and baseline.get("global_negative_prompt")
        and pipeline.get("apply_global_negative_txt2img", False)
        and pipeline.get(f"apply_global_negative_{stage}", True)
    ):
        raise ValueError(
            "Saved Learning preview predates executor-base freezing and may preapply "
            "Global Negative. Rebuild Preview before Run; the saved snapshot was not changed."
        )


def apply_executor_base_prompts(
    config: dict[str, Any], prompt: str, negative: str, stage: str
) -> None:
    """Keep executable config fields consistent after any ordinary LoRA override."""
    for section in (config, config.setdefault(stage, {})):
        section["prompt"] = prompt
        section["negative_prompt"] = negative


def frozen_negative_prompt(snapshot: dict[str, Any], experiment: Any) -> str:
    """An explicit new frozen empty base stays empty; retain legacy fallback semantics."""
    if (snapshot.get("prompt_source") or {}).get("executor_base_contract") == BASE_CONTRACT:
        return str(snapshot.get("negative_prompt_text") or "")
    return str(
        snapshot.get("negative_prompt_text")
        or getattr(experiment, "negative_prompt_text", "")
        or (getattr(experiment, "metadata", {}) or {}).get("selected_prompt_negative_text", "")
        or ""
    )


def ordinary_rating_prompt_evidence(
    snapshot: dict[str, Any], execution_metadata: dict[str, Any]
) -> dict[str, Any]:
    """Classify fresh ordinary base strings and retain existing executor readback."""
    if (
        snapshot.get("study_type", "controlled_variable") != "controlled_variable"
        or (snapshot.get("prompt_source") or {}).get("executor_base_contract") != BASE_CONTRACT
    ):
        return {}
    return {
        "prompt_semantics": PROMPT_SEMANTICS,
        "runtime_prompt_readback": dict(execution_metadata.get("runtime_prompt_readback") or {}),
    }
