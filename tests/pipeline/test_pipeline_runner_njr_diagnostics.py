from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


def test_pipeline_runner_records_stage_events(monkeypatch, tmp_path) -> None:
    class DummyPipeline:
        def __init__(self, api_client, structured_logger):
            self.api_client = api_client
            self.logger = structured_logger

        def run_txt2img_stage(
            self,
            prompt: str,
            negative_prompt: str,
            payload: dict[str, Any],
            run_dir,
            *,
            image_name: str | None = None,
            cancel_token: Any | None = None,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            output_path = run_dir / (image_name or "txt2img.png")
            return {"path": str(output_path), "images": [str(output_path)]}

    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", DummyPipeline)
    runner = PipelineRunner(
        api_client=SimpleNamespace(),
        structured_logger=StructuredLogger(output_dir=str(tmp_path)),
        runs_base_dir=str(tmp_path / "runs"),
    )

    njr = make_pipeline_njr(stage_chain=[make_stage_config()])
    cancel_token = SimpleNamespace(is_cancelled=lambda: False)

    result = runner.run_njr(njr, cancel_token=cancel_token)

    assert result.stage_plan is not None
    assert result.stage_plan.enabled_stages == ["txt2img"]
    assert result.stage_events
    assert result.stage_events[0]["stage"] == "txt2img"
    assert result.stage_events[0]["phase"] == "exit"
