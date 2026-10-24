"""Read-only optimizer illustrations and frozen-job evidence; no compilation or I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.image_backends.model_policy import (
    EVIDENCE_REGISTRY,
    FAMILY_SDXL,
    Support,
    policy_for_model_profile_reference,
)
from src.prompting.prompt_compatibility import PromptTargetProjection
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_errors import PromptConfigError
from src.prompting.prompt_optimizer_service import PromptOptimizerService
from src.prompting.prompt_splitter import lora_token_positions, split_prompt_chunks

LORA_POSITION_LABEL = "Keep LoRA positions"
LORA_POSITION_HELP = (
    "Keeps inline LoRA references near their authored chunk positions while other terms reorder. "
    "Turning this off groups movable LoRA tags later; unknown chunks can remain anchored. "
    "With both position options off, LoRA tags go to the end. Neither option removes LoRAs."
)
UNKNOWN_POSITION_HELP = (
    "Anchors unclassified chunks at their original parsed positions among surviving chunks, "
    "not absolute character offsets. Known terms reorder around them."
)
EXECUTION_NOTE = (
    "Execution-time projection unavailable: stage prompt selection, PromptPatch, global terms, "
    "aesthetic terms, optimization, stage policy and backend/profile normalization may still apply. "
    "An observed outbound prompt requires execution evidence; this is not an observed Forge payload."
)


def _status(
    config: PromptOptimizerConfig, stage: str, target: PromptTargetProjection | None
) -> str:
    if target is not None and not target.optimizer_available:
        return "Unavailable for model: " + target.optimizer_note
    if not config.enabled:
        return "Disabled by user"
    if not PromptOptimizerService(config).should_optimize_for_pipeline(stage):
        return "Not applicable to stage"
    if not config.optimize_positive and not config.optimize_negative:
        return "Disabled for both prompt channels"
    if target is None or target.evidence != EVIDENCE_REGISTRY or target.family != FAMILY_SDXL:
        return "Not confirmed: model support/effective job settings are not established"
    return "Enabled for editor target; effective job settings must be checked in Preview"


def _lora_chunk_positions(text: str) -> list[tuple[str, int]]:
    return [
        (token, index)
        for index, chunk in enumerate(split_prompt_chunks(text))
        for token, _offset in lora_token_positions(chunk)
    ]


def editor_comparison_lines(
    positive: str,
    negative: str,
    settings: Mapping[str, Any],
    *,
    target: PromptTargetProjection | None = None,
    stage: str = "txt2img",
    visible: bool = True,
    diagnostics: bool = False,
) -> list[str]:
    lines = ["", "━━━ PROMPT OPTIMIZER — EDITOR ILLUSTRATION ━━━"]
    if not visible:
        return lines + ["Prompt comparison and diagnostics hidden by content visibility."]
    try:
        config = PromptOptimizerConfig.from_dict(dict(settings))
    except (PromptConfigError, TypeError, ValueError):
        return lines + ["Optimizer illustration unavailable: invalid settings."]
    lines.extend(
        [
            f"Stage: {stage} — {_status(config, stage, target)}",
            "Text-only illustration using editor settings. Selected row/actor/style LoRAs, embeddings, "
            "Matrix expansion, adaptation and globals are not composed here. Authored text is unchanged.",
            "For authoritative compiled prompts and settings: Pipeline Preview → Effective Settings / Prompt Evidence.",
        ]
    )
    if target is not None and not target.optimizer_available:
        return lines + ["No optimizer transformation illustrated for this target."]
    result = PromptOptimizerService(config).optimize_prompts(
        positive, negative, pipeline_name=stage
    )
    for label, channel in (("Positive", result.positive), ("Negative", result.negative)):
        before = _lora_chunk_positions(channel.original_prompt)
        after = _lora_chunk_positions(channel.optimized_prompt)
        moved = (
            sum(a != b for a, b in zip(before, after, strict=False))
            if len(before) == len(after)
            else None
        )
        lines.extend(
            [
                f"{label}: {'Changed' if channel.changed else 'Unchanged'}",
                f"Before ({label} authored text):",
                channel.original_prompt or "(empty)",
                f"After ({label} illustration):",
                channel.optimized_prompt or "(empty)",
                f"LoRA references: {len(before)} → {len(after)}; "
                + (
                    f"{moved} changed parsed chunk position"
                    if moved is not None
                    else "position comparison unavailable after deduplication"
                ),
                f"Duplicate chunks removed ({label}): {len(channel.dropped_duplicates)}",
            ]
        )
        lines.extend(f"  Removed: {item}" for item in channel.dropped_duplicates)
        if (
            config.warn_on_large_chunk_count
            and len(split_prompt_chunks(channel.original_prompt))
            >= config.large_chunk_warning_threshold
        ):
            lines.append(
                "Warning: large prompt chunk count; review for over-constraint (no truncation)."
            )
        if diagnostics:
            lines.append(f"{label} bucket diagnostics:")
            lines.extend(f"  {key}: {', '.join(values)}" for key, values in channel.buckets.items())
    lines.append(EXECUTION_NOTE)
    return lines


def compiled_prompt_lines(jobs: Sequence[Any], *, visible: bool) -> list[str]:
    """Describe only the NJRs currently accepted by Preview, with no inferred execution output."""
    lines = [
        "",
        "Compiled NJR prompt evidence",
        "Frozen inputs for queued jobs; authored source may differ after compilation.",
    ]
    if not jobs:
        return lines + ["No compiled Preview. Execution-time projection unavailable."]
    # Bound presentation independently of potentially huge Matrix fan-out.
    for index, job in enumerate(jobs[:3], 1):
        config = job.config
        try:
            optimizer = PromptOptimizerConfig.from_dict(dict(config.get("prompt_optimizer") or {}))
            policy = policy_for_model_profile_reference(job.backend_options)
        except (PromptConfigError, TypeError, ValueError):
            lines.append(
                f"Job {index}: optimizer status unavailable (invalid frozen configuration)."
            )
            continue
        lines.append(f"Job {index}: compiled input")
        if not visible:
            lines.append(
                "Prompt text, LoRA identities and diagnostics hidden by content visibility."
            )
        else:
            lines.extend(
                [
                    "Compiled Positive:",
                    job.positive_prompt or "(empty)",
                    "Compiled Negative:",
                    job.negative_prompt or "(empty)",
                ]
            )
        if policy is not None and policy.feature("prompt_optimizer").support is Support.UNSUPPORTED:
            lines.append("Optimizer: Unavailable for model (frozen exact profile).")
        else:
            lines.append(
                f"Optimizer frozen enabled setting: {optimizer.enabled}; this does not prove model/stage applicability."
            )
        lines.append(
            f"Channels: positive={optimizer.optimize_positive}, negative={optimizer.optimize_negative}; "
            f"dedupe={optimizer.dedupe_enabled}; keep LoRA positions={optimizer.preserve_lora_relative_order}; "
            f"keep unknown positions={optimizer.preserve_unknown_order}"
        )
        # Names of opted-out stages are configuration, not user prompt text.
        lines.append(
            "Excluded stages: "
            + (", ".join(optimizer.opt_out_pipeline_names or []) if visible else "hidden")
        )
    if len(jobs) > 3:
        lines.append(f"Showing 3 of {len(jobs)} compiled jobs.")
    lines.append(EXECUTION_NOTE)
    return lines
