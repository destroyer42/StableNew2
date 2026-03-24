from __future__ import annotations

from typing import Any

from src.pipeline.payload_builder import build_sdxl_payload
from src.pipeline.stage_models import StageType
from src.pipeline.stage_sequencer import StageConfig, StageExecution, StageMetadata


def _make_stage(config_overrides: dict[str, Any] | None = None) -> StageExecution:
    payload = {
        "prompt": "masterpiece, beautiful woman, cinematic lighting",
        "negative_prompt": "watermark, blurry, bad anatomy",
        "steps": 20,
        "cfg_scale": 7.0,
        "sampler_name": "Euler a",
        "width": 1024,
        "height": 1024,
        "model": "model.safetensors",
        "prompt_optimizer": {"enabled": True},
    }
    if config_overrides:
        payload.update(config_overrides)
    return StageExecution(
        stage_type=StageType.TXT2IMG.value,
        config=StageConfig(enabled=True, payload=payload, metadata=StageMetadata()),
        order_index=0,
        requires_input_image=False,
        produces_output_image=True,
    )


def test_payload_builder_applies_prompt_optimizer() -> None:
    payload = build_sdxl_payload(_make_stage())
    assert payload["prompt"] == "beautiful woman, cinematic lighting, masterpiece"
    assert payload["negative_prompt"] == "bad anatomy, blurry, watermark"


def test_payload_builder_respects_disabled_prompt_optimizer() -> None:
    payload = build_sdxl_payload(_make_stage({"prompt_optimizer": {"enabled": False}}))
    assert payload["prompt"] == "masterpiece, beautiful woman, cinematic lighting"
    assert payload["negative_prompt"] == "watermark, blurry, bad anatomy"


def test_payload_builder_applies_stage_policy_for_auto_values() -> None:
    payload = build_sdxl_payload(
        _make_stage(
            {
                "sampler_name": "AUTO",
                "scheduler": "AUTO",
                "steps": "AUTO",
                "cfg_scale": "AUTO",
            }
        )
    )

    assert payload["sampler_name"] == "DPM++ 2M"
    assert payload["scheduler"] == "Karras"
    assert payload["steps"] == 28
    assert payload["cfg_scale"] == 6.5
