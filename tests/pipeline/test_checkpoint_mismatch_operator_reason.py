"""GP832-F1: a checkpoint that cannot be made active fails the job with a specific, bounded operator reason."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.pipeline.executor import Pipeline
from src.pipeline.job_models_v2 import StageConfig
from src.pipeline.model_synchronizer import (
    A1111ModelSynchronizer,
    ModelSynchronizationError,
    operator_model_title,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr
from tests.helpers.runtime_isolation import isolated_image_backends

GENERIC = "No images were generated successfully"


class _Client:
    """Fake WebUI client: counts generation POSTs; the active checkpoint is whatever the test says."""

    def __init__(
        self,
        active: str | None = "model-b.safetensors",
        *,
        writes: bool = True,
        set_result: bool = True,
        applies: bool = False,
        query_error: Exception | None = None,
    ) -> None:
        self.active = active
        self.options_write_enabled = writes
        self.last_options_write_failure = None
        self.set_result = set_result
        self.applies = applies
        self.query_error = query_error
        self.generation_posts = 0

    def get_current_model(self):
        if self.query_error is not None:
            raise self.query_error
        return self.active

    def set_model(self, name: str):
        if self.applies and self.set_result:
            self.active = name
        return self.set_result

    def get_current_vae(self):
        return "Automatic"

    def set_vae(self, *_a, **_k):
        return True

    def check_connection(self, **_k):
        return True

    def generate_images(self, *, stage, payload, **_k):
        self.generation_posts += 1
        return SimpleNamespace(
            ok=True,
            result=SimpleNamespace(images=["x"], info={}, stage=stage, timings={}),
        )


def _pipeline(client: _Client, tmp_path: Path) -> Pipeline:
    pipeline = Pipeline(client, StructuredLogger(output_dir=tmp_path / "logs"))
    pipeline._model_synchronizer = A1111ModelSynchronizer(
        client, timeout_seconds=0, poll_interval_seconds=0
    )
    return pipeline


def _njr(tmp_path: Path, model: str, job_id: str):
    return make_pipeline_njr(
        job_id=job_id,
        config={
            "model": model,
            "prompt": "a cat",
            "sampler_name": "Euler a",
            "steps": 5,
            "cfg_scale": 7.0,
            "width": 64,
            "height": 64,
        },
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        seed=1,
        positive_prompt="a cat",
        negative_prompt="",
        base_model=model,
        stage_chain=[StageConfig(stage_type="txt2img", enabled=True, steps=5, cfg_scale=7.0)],
    )


def _runner(client: _Client, pipeline: Pipeline, tmp_path: Path) -> PipelineRunner:
    # Hermetic runtime: a developer's live local WebUI must not influence dispatch.
    runner = PipelineRunner(
        client,
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "runs"),
        image_backend_registry=isolated_image_backends(),
    )
    runner._pipeline = pipeline
    return runner


def _run(client: _Client, tmp_path: Path, model: str = "model-a.safetensors"):
    pipeline = _pipeline(client, tmp_path)
    runner = _runner(client, pipeline, tmp_path)
    with patch.object(pipeline, "_ensure_webui_true_ready", return_value=None):
        return runner.run_njr(_njr(tmp_path, model, "gp832-f1"))


def test_changed_checkpoint_fails_with_the_specific_reason_and_no_generation_post(tmp_path):
    client = _Client("model-b.safetensors", applies=False)

    result = _run(client, tmp_path)

    assert result.success is False
    assert client.generation_posts == 0
    assert result.error != GENERIC
    assert "Checkpoint mismatch" in result.error
    assert "model-a.safetensors" in result.error
    assert "model-b.safetensors" in result.error
    assert "No images were generated" in result.error
    assert "Restore the selected model" in result.error
    assert "prepare a new job" in result.error
    assert len(result.error) < 400


def test_writes_disabled_and_rejected_switch_are_checkpoint_problems(tmp_path):
    disabled = _run(_Client("model-b.safetensors", writes=False), tmp_path)
    rejected = _run(_Client("model-b.safetensors", set_result=False), tmp_path)

    assert "Checkpoint mismatch" in disabled.error and "not allowed to change" in disabled.error
    assert "Checkpoint mismatch" in rejected.error and "refused to switch" in rejected.error


def test_backend_unreachable_is_not_reported_as_a_checkpoint_problem(tmp_path):
    client = _Client(query_error=ConnectionError("connection refused"))

    result = _run(client, tmp_path)

    assert result.success is False
    assert client.generation_posts == 0
    assert result.error == GENERIC
    assert "heckpoint" not in result.error


def test_a_failed_model_change_request_is_not_reported_as_a_verified_mismatch(tmp_path):
    class _Raises(_Client):
        def set_model(self, name):
            raise TimeoutError("read timed out")

    result = _run(_Raises("model-b.safetensors"), tmp_path)

    assert result.error == GENERIC


def test_unrelated_failure_keeps_its_message_and_does_not_inherit_a_stale_reason(tmp_path):
    # A previous run recorded a checkpoint problem on this executor; the next run must not report it.
    client = _Client("model-b.safetensors", applies=False)
    pipeline = _pipeline(client, tmp_path)
    with pytest.raises(ModelSynchronizationError):
        pipeline._ensure_model_and_vae("model-a.safetensors", None)
    assert pipeline._model_sync_failure_message is not None

    runner = _runner(client, pipeline, tmp_path)
    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        patch.object(pipeline, "run_txt2img_stage", side_effect=RuntimeError("sampler exploded")),
    ):
        result = runner.run_njr(_njr(tmp_path, "model-b.safetensors", "gp832-f1-other"))

    assert result.success is False
    assert result.error == "sampler exploded"
    assert pipeline.take_model_sync_failure() is None


def test_operator_message_is_path_free_and_bounded():
    exc = ModelSynchronizationError(
        "x",
        kind="not_applied",
        requested="C:\\secret\\dir\\" + "m" * 300 + ".safetensors",
        actual="/home/user/models/Other [abc123].safetensors",
    )

    text = exc.operator_message()

    assert text is not None
    assert "secret" not in text and "home/user" not in text and "C:" not in text
    assert "Other [abc123].safetensors" in text
    assert len(text) < 500
    assert operator_model_title("a\x00b\nc") == "a b c"
    assert operator_model_title("") == "unknown"


@pytest.mark.parametrize("kind", ["query_failed", "change_error", "invalid_request", "unspecified"])
def test_non_checkpoint_kinds_have_no_operator_message(kind):
    exc = ModelSynchronizationError("m", kind=kind, requested="a", actual="b")

    assert exc.operator_message() is None
