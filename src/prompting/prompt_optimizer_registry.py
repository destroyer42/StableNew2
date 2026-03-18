from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.prompting.prompt_types import PromptOptimizationPairResult


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
