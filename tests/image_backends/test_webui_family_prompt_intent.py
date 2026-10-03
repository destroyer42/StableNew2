"""Neutral prompt intent survives both WebUI adapters; no runtime or transport work."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.image_backends.image_backend_types import ImageExecutionRequest
from src.pipeline.executor import Pipeline
from src.pipeline.global_prompt_policy import (
    apply_global_prompt_policy,
    has_frozen_global_prompt_policy,
)
from src.utils import StructuredLogger

BACKENDS = (A1111WebUIImageBackend, ForgeWebUIImageBackend)


@pytest.mark.parametrize("stage", ["txt2img", "img2img", "adetailer", "upscale"])
@pytest.mark.parametrize("optimizer", [{"enabled": False}, {"enabled": True, "dedupe_enabled": False}])
def test_both_adapters_preserve_exact_optimizer_mapping_and_complete_policy(stage, optimizer):
    execution = apply_global_prompt_policy(
        {"prompt_optimizer": optimizer}, positive_enabled=False, negative_enabled=False,
        positive_text="frozen positive", negative_text="frozen negative",
    )
    translated = []
    for backend in BACKENDS:
        request = ImageExecutionRequest(backend_id=backend.backend_id, stage_name=stage,
                                        stage_config={}, output_dir=Path("unused"),
                                        execution_config=execution)
        translate = (backend._txt2img_executor_config if stage == "txt2img"
                     else backend._stage_executor_config)
        config = translate(request)
        assert config["prompt_optimizer"] == optimizer
        assert has_frozen_global_prompt_policy(config)
        translated.append(config)
    assert translated[0] == translated[1]
    assert execution["prompt_optimizer"] == optimizer


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("stage", ["txt2img", "img2img", "adetailer", "upscale"])
def test_omitted_optimizer_remains_omitted_and_retains_enabled_default(backend, stage):
    request = ImageExecutionRequest(backend_id=backend.backend_id, stage_name=stage,
                                    stage_config={}, output_dir=Path("unused"))
    translate = (backend._txt2img_executor_config if stage == "txt2img"
                 else backend._stage_executor_config)
    config = translate(request)
    assert "prompt_optimizer" not in config
    pipeline = Pipeline(object(), StructuredLogger())
    result, optimizer, _ = pipeline._run_prompt_optimizer(
        positive_prompt="masterpiece, beautiful woman, cinematic lighting",
        negative_prompt="watermark, blurry, bad anatomy", config=config, stage_name=stage,
    )
    assert optimizer.enabled
    assert result.positive.optimized_prompt == "beautiful woman, cinematic lighting, masterpiece"
    assert result.negative.optimized_prompt == "bad anatomy, blurry, watermark"


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("stage", ["txt2img", "img2img", "adetailer", "upscale"])
def test_explicitly_disabled_optimizer_preserves_order_duplicates_and_unicode(backend, stage):
    request = ImageExecutionRequest(backend_id=backend.backend_id, stage_name=stage,
                                    stage_config={}, output_dir=Path("unused"),
                                    execution_config={"prompt_optimizer": {"enabled": False}})
    translate = (backend._txt2img_executor_config if stage == "txt2img"
                 else backend._stage_executor_config)
    pipeline = Pipeline(object(), StructuredLogger())
    positive = "masterpiece, café athlete, cinematic lighting, masterpiece, <lora:detail:0.82>"
    negative = "watermark, blurry, bad anatomy, watermark"
    result, optimizer, _ = pipeline._run_prompt_optimizer(
        positive_prompt=positive, negative_prompt=negative,
        config=translate(request), stage_name=stage,
    )
    assert optimizer.enabled is False
    assert result.positive.optimized_prompt.encode("utf-8") == positive.encode("utf-8")
    assert result.negative.optimized_prompt.encode("utf-8") == negative.encode("utf-8")
    assert not result.positive.changed and not result.negative.changed
