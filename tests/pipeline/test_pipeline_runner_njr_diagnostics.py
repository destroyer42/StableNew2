from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.image_backends import (
    ImageBackendCapabilities,
    ImageBackendRegistry,
    ImageExecutionResult,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


class FakeImageBackend:
    backend_id = "fake"
    capabilities = ImageBackendCapabilities(backend_id=backend_id, stage_types=("txt2img",))

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def execute(self, _pipeline: Any, request: Any) -> ImageExecutionResult:
        self.requests.append(request)
        output = request.output_dir / "diagnostic.png"
        return ImageExecutionResult.from_stage_result(
            backend_id=request.backend_id,
            stage_name=request.stage_name,
            result={"path": str(output), "all_paths": [str(output)]},
        )


def test_pipeline_runner_records_stage_events(monkeypatch, tmp_path) -> None:
    class DummyPipeline:
        def __init__(self, api_client, structured_logger, status_callback=None):
            self.api_client = api_client
            self.logger = structured_logger
            self.status_callback = status_callback

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

    monkeypatch.setattr("src.pipeline.executor.Pipeline", DummyPipeline)
    fake_backend = FakeImageBackend()
    fake_registry = ImageBackendRegistry()
    fake_registry.register(fake_backend)

    configured_endpoint_probes: list[str] = []

    def record_unexpected_endpoint_probe(*_args: Any, **_kwargs: Any) -> str:
        configured_endpoint_probes.append("configured")
        return "free"

    monkeypatch.setattr(
        "src.api.healthcheck.probe_webui_endpoint",
        record_unexpected_endpoint_probe,
    )
    monkeypatch.setattr(
        "src.video.comfy_healthcheck.probe_comfy_endpoint",
        record_unexpected_endpoint_probe,
    )
    runner = PipelineRunner(
        api_client=SimpleNamespace(),
        structured_logger=StructuredLogger(output_dir=str(tmp_path)),
        runs_base_dir=str(tmp_path / "runs"),
        image_backend_registry=fake_registry,
    )

    njr = make_pipeline_njr(
        stage_chain=[make_stage_config()],
        backend_options={"image": {"backend_id": "fake"}},
    )
    cancel_token = SimpleNamespace(is_cancelled=lambda: False)

    result = runner.run_njr(njr, cancel_token=cancel_token)

    assert result.stage_plan is not None
    assert result.stage_plan.enabled_stages == ["txt2img"]
    assert result.stage_events
    assert result.stage_events[0]["stage"] == "txt2img"
    assert result.stage_events[0]["phase"] == "exit"
    assert fake_backend.requests and fake_backend.requests[0].backend_id == "fake"
    assert configured_endpoint_probes == []
