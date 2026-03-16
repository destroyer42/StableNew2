from __future__ import annotations

from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_service import PromptOptimizerService


def test_optimizer_reorders_positive_prompt_into_target_order() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "masterpiece, best quality, cinematic lighting, beautiful woman, japanese garden, autumn maple trees, standing, looking toward camera, 85mm lens, natural skin texture, photorealistic",
        "",
        pipeline_name="txt2img",
    )
    assert result.positive.optimized_prompt == (
        "beautiful woman, japanese garden, autumn maple trees, standing, looking toward camera, "
        "cinematic lighting, 85mm lens, natural skin texture, photorealistic, masterpiece, best quality"
    )


def test_optimizer_reorders_negative_prompt_into_target_order() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "",
        "watermark, text, blurry, low quality, bad anatomy, bad hands, extra fingers, cropped, anime, cartoon",
        pipeline_name="txt2img",
    )
    assert result.negative.optimized_prompt == (
        "bad anatomy, bad hands, extra fingers, blurry, low quality, cropped, watermark, text, anime, cartoon"
    )


def test_optimizer_is_deterministic_across_repeated_runs() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    first = service.optimize_prompts("beautiful woman, cinematic lighting, 85mm lens", "", pipeline_name="txt2img")
    second = service.optimize_prompts("beautiful woman, cinematic lighting, 85mm lens", "", pipeline_name="txt2img")
    assert first.positive.optimized_prompt == second.positive.optimized_prompt
    assert first.positive.buckets == second.positive.buckets
