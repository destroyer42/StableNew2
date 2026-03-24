from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.prompting.contracts import PromptOptimizerAnalysisBundle
from src.prompting.prompt_types import PromptOptimizationPairResult


PROMPT_OPTIMIZER_V3_SCHEMA = "stablenew.prompt-optimizer.v3"
PROMPT_OPTIMIZER_V3_VERSION = "3.0.0"


def build_prompt_optimization_record(
    result: PromptOptimizationPairResult,
) -> Dict[str, Any]:
    return {
        "positive": {
            "original_prompt": result.positive.original_prompt,
            "optimized_prompt": result.positive.optimized_prompt,
            "buckets": result.positive.buckets,
            "dropped_duplicates": result.positive.dropped_duplicates,
            "changed": result.positive.changed,
        },
        "negative": {
            "original_prompt": result.negative.original_prompt,
            "optimized_prompt": result.negative.optimized_prompt,
            "buckets": result.negative.buckets,
            "dropped_duplicates": result.negative.dropped_duplicates,
            "changed": result.negative.changed,
        },
    }


def build_prompt_optimizer_analysis_record(
    bundle: PromptOptimizerAnalysisBundle,
) -> Dict[str, Any]:
    return bundle.to_dict()


def build_prompt_optimizer_v3_record_from_prompts(
    *,
    positive_original: str,
    negative_original: str,
    positive_final: str,
    negative_final: str,
    bundle: PromptOptimizerAnalysisBundle,
) -> Dict[str, Any]:
    policy_rationales: list[str] = []
    if bundle.stage_policy is not None:
        policy_rationales.extend(item.rationale for item in bundle.stage_policy.applied_decisions)
        policy_rationales.extend(item.rationale for item in bundle.stage_policy.preserved_decisions)
        policy_rationales.extend(item.rationale for item in bundle.stage_policy.recommended_decisions)
    rationales = list(
        dict.fromkeys([item.rationale for item in bundle.recommendations] + policy_rationales)
    )
    return {
        "schema": PROMPT_OPTIMIZER_V3_SCHEMA,
        "version": PROMPT_OPTIMIZER_V3_VERSION,
        "stage": bundle.stage,
        "mode": bundle.mode,
        "inputs": {
            "positive_original": positive_original,
            "negative_original": negative_original,
            "prompt_source": bundle.context.source.to_dict(),
        },
        "outputs": {
            "positive_final": positive_final,
            "negative_final": negative_final,
        },
        "context": {
            "bucket_counts": {
                "positive": dict(bundle.context.positive_bucket_counts),
                "negative": dict(bundle.context.negative_bucket_counts),
            },
            "chunk_counts": {
                "positive": bundle.context.positive_chunk_count,
                "negative": bundle.context.negative_chunk_count,
            },
            "loras": [dict(item) for item in bundle.context.loras],
            "embeddings": [dict(item) for item in bundle.context.embeddings],
        },
        "intent": bundle.intent.to_dict(),
        "policy": {
            "stage_policy": bundle.stage_policy.to_dict() if bundle.stage_policy is not None else None,
            "recommendations": [item.to_dict() for item in bundle.recommendations],
            "rationale": rationales,
        },
        "delta_guard": {
            "status": "pass",
            "added_tokens": [],
            "removed_tokens": [],
            "weight_changes": [],
            "lora_changes": [],
        },
        "warnings": list(bundle.warnings),
        "errors": list(bundle.errors),
    }


def build_prompt_optimizer_v3_record(
    result: PromptOptimizationPairResult,
    bundle: PromptOptimizerAnalysisBundle,
) -> Dict[str, Any]:
    return build_prompt_optimizer_v3_record_from_prompts(
        positive_original=result.positive.original_prompt,
        negative_original=result.negative.original_prompt,
        positive_final=result.positive.optimized_prompt,
        negative_final=result.negative.optimized_prompt,
        bundle=bundle,
    )


def write_prompt_optimization_record(
    output_path: Path,
    result: PromptOptimizationPairResult,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_prompt_optimization_record(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def write_prompt_optimizer_analysis_record(
    output_path: Path,
    bundle: PromptOptimizerAnalysisBundle,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_prompt_optimizer_analysis_record(bundle), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def write_prompt_optimizer_v3_record(
    output_path: Path,
    result: PromptOptimizationPairResult,
    bundle: PromptOptimizerAnalysisBundle,
) -> Path:
    return write_prompt_optimizer_v3_payload(
        output_path,
        build_prompt_optimizer_v3_record(result, bundle),
    )


def write_prompt_optimizer_v3_payload(
    output_path: Path,
    payload: Dict[str, Any],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path
