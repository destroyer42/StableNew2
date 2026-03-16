from __future__ import annotations

import logging

from src.pipeline.executor import Pipeline
from src.utils import StructuredLogger


def test_prompt_optimizer_logs_before_after(caplog) -> None:
    pipeline = Pipeline(client=object(), structured_logger=StructuredLogger())
    config = {
        "prompt_optimizer": {
            "enabled": True,
            "log_before_after": True,
            "log_bucket_assignments": True,
        }
    }

    with caplog.at_level(logging.INFO):
        result, _ = pipeline._run_prompt_optimizer(
            positive_prompt="masterpiece, beautiful woman",
            negative_prompt="watermark, blurry",
            config=config,
            stage_name="txt2img",
        )

    assert result.positive.optimized_prompt == "beautiful woman, masterpiece"
    assert "PROMPT OPTIMIZER ENABLED" in caplog.text
    assert "ORIGINAL POSITIVE:" in caplog.text
    assert "OPTIMIZED NEGATIVE:" in caplog.text
