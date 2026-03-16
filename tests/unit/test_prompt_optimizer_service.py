from __future__ import annotations

from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_service import PromptOptimizerService


def test_service_bypasses_opted_out_pipeline() -> None:
    config = PromptOptimizerConfig(opt_out_pipeline_names=["adetailer"])
    service = PromptOptimizerService(config)
    result = service.optimize_prompts("masterpiece, beautiful woman", "blurry, bad anatomy", pipeline_name="adetailer")
    assert result.positive.optimized_prompt == "masterpiece, beautiful woman"
    assert result.negative.optimized_prompt == "blurry, bad anatomy"


def test_service_uses_optimizer_when_enabled() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts("masterpiece, beautiful woman", "", pipeline_name="txt2img")
    assert result.positive.optimized_prompt == "beautiful woman, masterpiece"
