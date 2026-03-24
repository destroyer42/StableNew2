from __future__ import annotations

from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_orchestrator import PromptOptimizerOrchestrator
from src.prompting.prompt_optimizer_service import PromptOptimizerService


def test_orchestrator_emits_recommend_only_analysis_without_changing_optimizer_contract() -> None:
    service = PromptOptimizerService(PromptOptimizerConfig())
    orchestrator = PromptOptimizerOrchestrator(service=service)

    result = orchestrator.orchestrate(
        positive_prompt="masterpiece, beautiful woman, natural skin texture, <lora:detail:0.6>, <lora:detail:0.8>",
        negative_prompt="watermark, blurry",
        stage_name="txt2img",
        config={
            "prompt_source": "pack",
            "prompt_pack_id": "pack-1",
            "prompt_pack_row_index": 3,
            "run_mode": "QUEUE",
            "source": "learning",
            "tags": ["portrait"],
            "prompt_optimizer": {"enabled": True},
        },
    )

    assert result.analysis.mode == "recommend_only_v1"
    assert result.analysis.context.source.prompt_source == "pack"
    assert result.analysis.context.source.prompt_pack_id == "pack-1"
    assert result.analysis.intent.intent_band == "portrait"
    assert any(item.action == "consider_face_pass" for item in result.analysis.recommendations)
    assert any(item.recommendation_id == "duplicate_lora_name_with_different_weights" for item in result.analysis.recommendations)
    assert result.optimization.positive.optimized_prompt == service.optimize_prompts(
        "masterpiece, beautiful woman, natural skin texture, <lora:detail:0.6>, <lora:detail:0.8>",
        "watermark, blurry",
        pipeline_name="txt2img",
    ).positive.optimized_prompt
