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


def test_optimizer_moves_lora_tokens_to_absolute_end_of_positive_prompt() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "beautiful woman, low angle full body shot <lora:add-detail-xl:0.3> <lora:cinematic:0.8>, photorealistic",
        "",
        pipeline_name="txt2img",
    )

    assert result.positive.optimized_prompt == (
        "beautiful woman, low angle full body shot, photorealistic, <lora:add-detail-xl:0.3>, <lora:cinematic:0.8>"
    )
    assert result.positive.buckets["lora_tokens"] == [
        "<lora:add-detail-xl:0.3>",
        "<lora:cinematic:0.8>",
    ]


def test_optimizer_can_disable_lora_relative_order_preservation() -> None:
    service = PromptOptimizerService(
        PromptOptimizerConfig(preserve_lora_relative_order=False, preserve_unknown_order=False)
    )
    result = service.optimize_prompts(
        "beautiful woman, low angle full body shot <lora:add-detail-xl:0.3> <lora:cinematic:0.8>, photorealistic",
        "",
        pipeline_name="txt2img",
    )

    assert result.positive.optimized_prompt.endswith(
        "<lora:add-detail-xl:0.3>, <lora:cinematic:0.8>"
    )


def test_optimizer_preserves_unknown_chunk_order_when_enabled() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "masterpiece, crystal sigil, beautiful woman, cinematic lighting",
        "",
        pipeline_name="txt2img",
    )

    assert result.positive.optimized_prompt == (
        "beautiful woman, crystal sigil, cinematic lighting, masterpiece"
    )


def test_optimizer_can_disable_unknown_chunk_order_preservation() -> None:
    service = PromptOptimizerService(
        PromptOptimizerConfig(preserve_unknown_order=False, preserve_lora_relative_order=False)
    )
    result = service.optimize_prompts(
        "masterpiece, crystal sigil, beautiful woman, cinematic lighting",
        "",
        pipeline_name="txt2img",
    )

    assert result.positive.optimized_prompt == (
        "beautiful woman, cinematic lighting, masterpiece, crystal sigil"
    )


def test_optimizer_preserves_negative_embedding_prefix() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "",
        "<embedding:SDXLnegXL>, blurry, bad anatomy, watermark",
        pipeline_name="txt2img",
    )

    assert result.negative.optimized_prompt == "<embedding:SDXLnegXL>, bad anatomy, blurry, watermark"
    assert result.negative.buckets["embedding_tokens"] == ["<embedding:SDXLnegXL>"]


def test_optimizer_keeps_embeddings_front_and_loras_end_for_mixed_positive_prompt() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "global polish, <embedding:face_refiner>, beautiful woman, golden-hour natural lighting <lora:add-detail-xl:0.3> <lora:cinematic:0.8>",
        "",
        pipeline_name="txt2img",
    )

    assert result.positive.optimized_prompt.startswith("<embedding:face_refiner>, ")
    assert result.positive.optimized_prompt.endswith(
        "<lora:add-detail-xl:0.3>, <lora:cinematic:0.8>"
    )
    assert "golden-hour natural lighting, <lora:add-detail-xl:0.3>" in result.positive.optimized_prompt
    assert result.positive.buckets["embedding_tokens"] == ["<embedding:face_refiner>"]
    assert result.positive.buckets["lora_tokens"] == [
        "<lora:add-detail-xl:0.3>",
        "<lora:cinematic:0.8>",
    ]


def test_optimizer_extracts_mixed_positive_embeddings_to_absolute_front() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "cinematic lighting, beautiful woman (<embedding:face_refiner>:0.8), japanese garden, <embedding:styleA>, masterpiece",
        "",
        pipeline_name="txt2img",
    )

    assert result.positive.optimized_prompt.startswith(
        "(<embedding:face_refiner>:0.8), <embedding:styleA>, beautiful woman"
    )
    assert result.positive.buckets["embedding_tokens"] == [
        "(<embedding:face_refiner>:0.8)",
        "<embedding:styleA>",
    ]


def test_optimizer_extracts_negative_embeddings_to_absolute_front_even_when_text_leads() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "",
        "weird tongue, tongue sticking out, <embedding:SDXLnegXL>, blurry, watermark",
        pipeline_name="txt2img",
    )

    assert result.negative.optimized_prompt == (
        "<embedding:SDXLnegXL>, weird tongue, tongue sticking out, blurry, watermark"
    )
    assert result.negative.buckets["embedding_tokens"] == ["<embedding:SDXLnegXL>"]


def test_optimizer_preserves_legacy_bare_embedding_tokens_at_front() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    result = service.optimize_prompts(
        "dramatic light, woman portrait <stable_yogis_pdxl_positives>, sharp focus",
        "",
        pipeline_name="adetailer",
    )

    assert result.positive.optimized_prompt == (
        "<stable_yogis_pdxl_positives>, dramatic light, woman portrait, sharp focus"
    )
    assert result.positive.buckets["embedding_tokens"] == ["<stable_yogis_pdxl_positives>"]
