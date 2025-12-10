"""Tests ensuring the resolution helpers produce consistent data for previews."""

from src.pipeline.job_models_v2 import PipelineConfigSnapshot
from src.pipeline.resolution_layer import UnifiedConfigResolver, UnifiedPromptResolver


def test_prompt_resolution_applies_global_and_safety_negatives() -> None:
    resolver = UnifiedPromptResolver(max_preview_length=10, safety_negative="safety")
    result = resolver.resolve(
        gui_prompt="sunrise over hills",
        global_negative="no noise",
        apply_global_negative=True,
        negative_override="no ripples",
    )

    assert "sunrise" in result.positive
    assert "no noise" in result.negative
    assert "safety" in result.negative
    assert result.global_negative_applied
    assert result.positive_preview.endswith("...")


def test_config_resolver_honors_stage_flags_and_seed() -> None:
    config = PipelineConfigSnapshot.default()
    resolver = UnifiedConfigResolver()
    resolved = resolver.resolve(
        config_snapshot=config,
        stage_flags={"img2img": True, "adetailer": True},
        batch_count=3,
        seed_value=123,
    )

    enabled = resolved.enabled_stage_names()
    assert "img2img" in enabled
    assert "adetailer" in enabled
    assert resolved.batch_count == 3
    assert resolved.seed == 123
    assert resolved.final_size == (resolved.width, resolved.height)
