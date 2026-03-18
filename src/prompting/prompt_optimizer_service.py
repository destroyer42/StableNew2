from __future__ import annotations

import logging
from typing import Any

from src.prompting.prompt_bucket_rules import build_default_prompt_bucket_rules
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_types import PromptOptimizationPairResult, PromptOptimizationResult
from src.prompting.sdxl_prompt_optimizer import SDXLPromptOptimizer

logger = logging.getLogger(__name__)


class PromptOptimizerService:
    def __init__(self, config: PromptOptimizerConfig) -> None:
        self.config = config
        self.config.validate()
        self.optimizer = SDXLPromptOptimizer(config, build_default_prompt_bucket_rules())

    def optimize_prompts(
        self,
        positive_prompt: str,
        negative_prompt: str,
        pipeline_name: str | None = None,
    ) -> PromptOptimizationPairResult:
        positive_prompt = str(positive_prompt or "")
        negative_prompt = str(negative_prompt or "")
        if not self.should_optimize_for_pipeline(pipeline_name):
            return _unchanged_pair(positive_prompt, negative_prompt)
        return self.optimizer.optimize_pair(positive_prompt, negative_prompt)

    def should_optimize_for_pipeline(self, pipeline_name: str | None) -> bool:
        if not self.config.enabled:
            return False
        name = str(pipeline_name or "").strip().lower()
        if not name:
            return True
        return name not in {item.strip().lower() for item in (self.config.opt_out_pipeline_names or [])}


def optimize_with_config(
    positive_prompt: str,
    negative_prompt: str,
    *,
    config_payload: dict[str, Any] | None,
    pipeline_name: str | None,
) -> PromptOptimizationPairResult:
    try:
        config = PromptOptimizerConfig.from_dict(config_payload)
    except Exception as exc:
        logger.warning("Prompt optimizer disabled due to invalid config: %s", exc)
        return _unchanged_pair(str(positive_prompt or ""), str(negative_prompt or ""))
    try:
        service = PromptOptimizerService(config)
        return service.optimize_prompts(positive_prompt, negative_prompt, pipeline_name=pipeline_name)
    except Exception as exc:
        logger.warning("Prompt optimization failed for %s: %s", pipeline_name or "unknown", exc)
        return _unchanged_pair(str(positive_prompt or ""), str(negative_prompt or ""))


def _unchanged_pair(positive_prompt: str, negative_prompt: str) -> PromptOptimizationPairResult:
    return PromptOptimizationPairResult(
        positive=PromptOptimizationResult(
            original_prompt=positive_prompt,
            optimized_prompt=positive_prompt,
            polarity="positive",
            changed=False,
        ),
        negative=PromptOptimizationResult(
            original_prompt=negative_prompt,
            optimized_prompt=negative_prompt,
            polarity="negative",
            changed=False,
        ),
    )
