from __future__ import annotations

from src.prompting.contracts import PromptContext, PromptIntentBundle
from src.prompting.stage_policy_engine import StagePolicyEngine


def _prompt_context(*, stage: str, positive_chunk_count: int = 8, warnings: list[str] | None = None) -> PromptContext:
    return PromptContext(
        stage=stage,
        pipeline_name=stage,
        positive_chunk_count=positive_chunk_count,
        negative_chunk_count=3,
        positive_bucket_counts={"subject": 1},
        negative_bucket_counts={"anatomy_defects": 1},
        warnings=list(warnings or []),
    )


def _portrait_intent(*, conflicts: list[str] | None = None) -> PromptIntentBundle:
    return PromptIntentBundle(
        intent_band="portrait",
        shot_type="portrait",
        style_mode="photoreal",
        requested_pose="frontal",
        wants_face_detail=True,
        wants_full_body=False,
        wants_portrait=True,
        has_people_tokens=True,
        has_lora_tokens=False,
        sensitive=False,
        conflicts=list(conflicts or []),
    )


def test_stage_policy_engine_applies_missing_txt2img_values() -> None:
    engine = StagePolicyEngine()

    result = engine.apply(
        stage_name="txt2img",
        current_config={"steps": 20, "cfg_scale": 7.0, "sampler_name": "Euler a", "scheduler": None},
        source_config={"sampler_name": "AUTO", "scheduler": "AUTO"},
        prompt_context=_prompt_context(stage="txt2img"),
        intent=_portrait_intent(),
    )

    assert result.config["sampler_name"] == "DPM++ 2M"
    assert result.config["scheduler"] == "Karras"
    assert result.config["steps"] == 28
    assert result.config["cfg_scale"] == 6.5
    assert result.bundle.applied_settings["sampler_name"] == "DPM++ 2M"


def test_stage_policy_engine_preserves_explicit_adetailer_values() -> None:
    engine = StagePolicyEngine()

    result = engine.apply(
        stage_name="adetailer",
        current_config={"adetailer_confidence": 0.45, "adetailer_sampler": "Euler a"},
        source_config={"adetailer_confidence": 0.45, "adetailer_sampler": "Euler a"},
        prompt_context=_prompt_context(stage="adetailer"),
        intent=_portrait_intent(),
    )

    assert result.config["adetailer_confidence"] == 0.45
    assert result.config["adetailer_sampler"] == "Euler a"
    preserved = {item.key: item for item in result.bundle.preserved_decisions}
    assert preserved["adetailer_confidence"].action == "preserved"
    assert preserved["adetailer_sampler"].action == "preserved"


def test_stage_policy_engine_applies_conservative_upscale_img2img_values() -> None:
    engine = StagePolicyEngine()

    result = engine.apply(
        stage_name="upscale",
        current_config={"upscale_mode": "img2img", "sampler_name": "Euler a", "scheduler": "normal", "steps": 20, "cfg_scale": 7.0, "denoising_strength": 0.35},
        source_config={
            "upscale_mode": "img2img",
            "sampler_name": "AUTO",
            "scheduler": "AUTO",
            "steps": "AUTO",
            "cfg_scale": "AUTO",
            "denoising_strength": "AUTO",
        },
        prompt_context=_prompt_context(stage="upscale", positive_chunk_count=20, warnings=["large_chunk_count"]),
        intent=_portrait_intent(conflicts=["positive_negative_style_conflict"]),
    )

    assert result.config["sampler_name"] == "DPM++ 2M"
    assert result.config["scheduler"] == "Karras"
    assert result.config["steps"] == 18
    assert result.config["cfg_scale"] == 5.0
    assert result.config["denoising_strength"] == 0.18
    assert "stage_policy_dense_prompt" in result.bundle.warnings
