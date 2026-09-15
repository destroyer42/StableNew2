from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.controller.job_service import JobService
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.image_backends import (
    A1111WebUIImageBackend,
    ImageBackendCapabilities,
    ImageBackendRegistry,
    ImageExecutionRequest,
    ImageExecutionResult,
    normalize_image_backend_options,
    resolve_image_backend_id,
)
from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot
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
        self.client = None

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


def test_new_cli_image_build_persists_backend_and_preserves_video_options() -> None:
    record = build_cli_njr(
        prompt="prompt",
        config={
            "txt2img": {},
            "backend_options": {"video": {"svd_native": {"fps": 7}}},
        },
        batch_size=1,
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
    assert "image" not in restored.backend_options
    assert resolve_image_backend_id(restored.backend_options) == "a1111_webui"
    assert restored.backend_options["video"]["svd_native"]["fps"] == 7


def test_new_image_normalizer_rejects_malformed_identity() -> None:
    with pytest.raises(ValueError, match="must be a string"):
        normalize_image_backend_options({"image": {"backend_id": 3}})


def test_replay_preserves_explicit_backend_identity_and_creates_new_lineage() -> None:
    original = build_cli_njr(
        prompt="prompt",
        config={"txt2img": {"model": "model.safetensors"}},
        batch_size=1,
        run_name="parent-job",
    )

    replay = compile_replay_intent(
        ReplayIntent(record=original, parent_artifact_id="artifact-parent"),
        id_fn=lambda: "replay-job",
    )

    assert replay.job_id == "replay-job"
    assert replay.source.parent_job_id == original.job_id
    assert replay.backend_options["image"]["backend_id"] == "a1111_webui"


def test_fake_backend_uses_normal_runner_path_without_webui(tmp_path: Path) -> None:
    backend = _FakeTxt2ImgBackend()
    runner = _runner(tmp_path, backend)
    record = make_pipeline_njr(backend_options={"image": {"backend_id": backend.backend_id}})

    result = runner.run_njr(record)

    assert result.success is True
    assert len(backend.calls) == 1
    assert result.metadata["image_backend_id"] == backend.backend_id
    assert Path(result.output_paths[0]).is_file()
    request = backend.calls[0]
    assert request.stage_config.get("extra") == {}
    assert request.sampler == "Euler a"
    assert "batch_size" not in request.stage_config
    assert "n_iter" not in request.stage_config
    assert "sd_model_checkpoint" not in request.stage_config
    assert "adetailer_enabled" not in request.stage_config
    assert runner._pipeline.client is None


def test_fake_backend_traverses_job_service_sqlite_and_canonical_result(tmp_path: Path) -> None:
    backend = _FakeTxt2ImgBackend()
    pipeline_runner = _runner(tmp_path / "artifacts", backend)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)

    def execute(job: object):
        record = normalized_job_from_snapshot(getattr(job, "snapshot", {}) or {})
        assert record is not None
        return pipeline_runner.run_njr(record, cancel_token=getattr(job, "_cancel_token", None))

    service = JobService(queue, run_callable=execute, require_normalized_records=True)
    service.auto_run_enabled = False
    record = make_pipeline_njr(
        job_id="fake-queue-spine",
        backend_options={"image": {"backend_id": backend.backend_id}},
    )
    assert service.submit_njrs([record], SubmissionPolicy(start_when_idle=False)) == [record.job_id]
    queued = repository.get_job(record.job_id)
    assert queued is not None and queued.status is JobStatus.QUEUED
    queued_snapshot = normalized_job_from_snapshot(queued.snapshot or {})
    assert queued_snapshot is not None
    assert queued_snapshot.backend_options["image"]["backend_id"] == backend.backend_id

    service.runner.run_once(queue.get_job(record.job_id))

    completed = repository.get_job(record.job_id)
    assert completed is not None and completed.status is JobStatus.COMPLETED
    assert completed.result is not None
    assert Path(completed.result["variants"][0]["path"]).is_file()
    assert len(backend.calls) == 1
    assert pipeline_runner._pipeline.client is None


def test_runner_keeps_model_vae_policy_neutral_and_adapter_translates_aliases(
    tmp_path: Path,
) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "artifacts"))
    pipeline = Mock()
    pipeline.client = Mock()
    txt_path = tmp_path / "txt.png"
    img_path = tmp_path / "img.png"
    detail_path = tmp_path / "detail.png"
    upscale_path = tmp_path / "upscale.png"
    for path in (txt_path, img_path, detail_path, upscale_path):
        path.write_bytes(b"png")
    pipeline.run_txt2img_stage.return_value = {"path": str(txt_path), "all_paths": [str(txt_path)]}
    pipeline.run_img2img_stage.return_value = {"path": str(img_path)}
    pipeline.run_adetailer_stage.return_value = {"path": str(detail_path)}
    pipeline.run_upscale_stage.return_value = {"path": str(upscale_path)}
    runner._pipeline = pipeline
    record = make_pipeline_njr(
        config={
            "model": "base-model.safetensors",
            "vae": "base-vae.safetensors",
            "sampler_name": "Euler a",
            "scheduler": "Karras",
            "steps": 20,
            "cfg_scale": 5.0,
            "width": 768,
            "height": 1024,
        },
        stage_chain=(
            make_stage_config(model="base-model.safetensors", vae="base-vae.safetensors"),
            make_stage_config(
                "img2img", model="hidden-model", vae="hidden-vae", extra={"strength": 0.3}
            ),
            make_stage_config(
                "adetailer", model="hidden-model", vae="hidden-vae", extra={"prompt": "face"}
            ),
            make_stage_config(
                "upscale", model="hidden-model", vae="hidden-vae", extra={"upscaler": "R-ESRGAN 4x+"}
            ),
        ),
        backend_options={"image": {"backend_id": "a1111_webui"}},
    )

    result = runner.run_njr(record)

    assert result.success is True
    for method in (
        pipeline.run_img2img_stage,
        pipeline.run_adetailer_stage,
        pipeline.run_upscale_stage,
    ):
        config = method.call_args.kwargs["config"]
        assert config["model"] == "base-model.safetensors"
        assert config["sd_model_checkpoint"] == "base-model.safetensors"
        assert config["vae"] == "base-vae.safetensors"
        assert config["sd_vae"] == "base-vae.safetensors"


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
            stage_config={
                "extra": {
                    "prompt": "stage prompt",
                    "negative_prompt": "stage negative",
                    "upscaler": "R-ESRGAN 4x+",
                }
            },
            output_dir=tmp_path,
            input_image_path=input_path,
            image_name=stage_name,
            prompt="prompt",
            negative_prompt="negative",
            selected_model="known-good",
            selected_vae="known-vae",
            sampler="Euler a",
            scheduler="Karras",
            steps=20,
            cfg_scale=5.0,
            width=768,
            height=1024,
            seed=100100,
            image_count=2,
            execution_config={"enable_hr": True, "hr_scale": 1.5},
            cancel_token=token,
        ),
    )

    assert result is not None
    assert result.backend_id == "a1111_webui"
    method.assert_called_once()
    assert method.call_args.kwargs["cancel_token"] is token
    if stage_name == "txt2img":
        config = method.call_args.args[2]
        assert config["batch_size"] == 1
        assert config["n_iter"] == 2
        assert config["sampler_name"] == "Euler a"
        assert config["enable_hr"] is True
    else:
        config = method.call_args.kwargs["config"]
        assert config["model"] == "known-good"
        assert config["sd_model_checkpoint"] == "known-good"
        assert config["vae"] == "known-vae"
        assert config["sd_vae"] == "known-vae"
        assert config["scheduler"] == "Karras"
    if stage_name == "adetailer":
        assert config["adetailer_enabled"] is True
        assert config["adetailer_prompt"] == "stage prompt"
    if stage_name == "upscale":
        assert config["upscaler"] == "R-ESRGAN 4x+"
        assert config["prompt"] == "stage prompt"
