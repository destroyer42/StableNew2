from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.image_backends import (
    A1111WebUIImageBackend,
    ImageBackendCapabilities,
    ImageBackendRegistry,
    ImageExecutionRequest,
    ImageExecutionResult,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


class _FakeTxt2ImgBackend:
    backend_id = "fake_test"
    capabilities = ImageBackendCapabilities(backend_id=backend_id, stage_types=("txt2img",))

    def __init__(self) -> None:
        self.calls: list[ImageExecutionRequest] = []

    def execute(self, _pipeline: object, request: ImageExecutionRequest) -> ImageExecutionResult:
        self.calls.append(request)
        output = request.output_dir / f"{request.image_name}.png"
        output.write_bytes(
            bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082")
        )
        return ImageExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name=request.stage_name,
            result={"path": str(output), "all_paths": [str(output)]},
        )


class _NoWebUIPipeline:
    def __init__(self) -> None:
        self.client = Mock()

    def _begin_run_metrics(self) -> None:
        return None

    def get_run_efficiency_metrics(self, _variant_count: int) -> dict[str, object]:
        return {}


def _runner(tmp_path: Path, backend: _FakeTxt2ImgBackend) -> PipelineRunner:
    registry = ImageBackendRegistry()
    registry.register(backend)
    runner = PipelineRunner(
        Mock(), Mock(), runs_base_dir=str(tmp_path), image_backend_registry=registry
    )
    runner._pipeline = _NoWebUIPipeline()
    return runner


def test_image_workload_defaults_backend_and_preserves_video_options() -> None:
    record = make_pipeline_njr(
        backend_options={"video": {"svd_native": {"fps": 7}}},
    )
    assert record.backend_options["image"]["backend_id"] == "a1111_webui"
    assert record.backend_options["video"]["svd_native"]["fps"] == 7
    restored = NormalizedJobRecord.from_dict(record.to_dict())
    assert restored.backend_options["image"]["backend_id"] == "a1111_webui"


def test_historical_missing_image_backend_resolves_to_a1111() -> None:
    record = make_pipeline_njr()
    payload = record.to_dict()
    payload["workload"]["backend_options"] = {"video": {"svd_native": {"fps": 7}}}
    restored = NormalizedJobRecord.from_dict(payload)
    assert restored.backend_options["image"]["backend_id"] == "a1111_webui"
    assert restored.backend_options["video"]["svd_native"]["fps"] == 7


def test_fake_backend_uses_normal_runner_path_without_webui(tmp_path: Path) -> None:
    backend = _FakeTxt2ImgBackend()
    runner = _runner(tmp_path, backend)
    record = make_pipeline_njr(backend_options={"image": {"backend_id": backend.backend_id}})

    result = runner.run_njr(record)

    assert result.success is True
    assert len(backend.calls) == 1
    assert result.metadata["image_backend_id"] == backend.backend_id
    assert Path(result.output_paths[0]).is_file()
    assert runner._pipeline.client.mock_calls


def test_unsupported_fake_stage_chain_rejects_before_dispatch(tmp_path: Path) -> None:
    backend = _FakeTxt2ImgBackend()
    runner = _runner(tmp_path, backend)
    record = make_pipeline_njr(
        backend_options={"image": {"backend_id": backend.backend_id}},
        stage_chain=(make_stage_config("txt2img"), make_stage_config("adetailer")),
    )

    with pytest.raises(ValueError, match="does not support stage chain"):
        runner.run_njr(record)
    assert backend.calls == []


def test_unknown_explicit_backend_fails_without_a1111_fallback(tmp_path: Path) -> None:
    backend = _FakeTxt2ImgBackend()
    runner = _runner(tmp_path, backend)
    record = make_pipeline_njr(backend_options={"image": {"backend_id": "unknown"}})

    with pytest.raises(KeyError, match="unknown"):
        runner.run_njr(record)
    assert backend.calls == []


@pytest.mark.parametrize("stage_name", ["txt2img", "img2img", "adetailer", "upscale"])
def test_a1111_adapter_delegates_each_supported_stage(stage_name: str, tmp_path: Path) -> None:
    pipeline = Mock()
    method = getattr(pipeline, f"run_{stage_name}_stage")
    output = tmp_path / f"{stage_name}.png"
    method.return_value = {"path": str(output)}
    input_path = tmp_path / "input.png" if stage_name != "txt2img" else None
    if input_path:
        input_path.write_bytes(b"input")
    token = object()

    result = A1111WebUIImageBackend().execute(
        pipeline,
        ImageExecutionRequest(
            backend_id="a1111_webui",
            stage_name=stage_name,
            stage_config={"model": "known-good"},
            output_dir=tmp_path,
            input_image_path=input_path,
            image_name=stage_name,
            prompt="prompt",
            negative_prompt="negative",
            cancel_token=token,
        ),
    )

    assert result is not None
    assert result.backend_id == "a1111_webui"
    method.assert_called_once()
    assert method.call_args.kwargs["cancel_token"] is token
