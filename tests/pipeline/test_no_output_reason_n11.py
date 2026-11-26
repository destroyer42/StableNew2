"""N11: a stage that produces nothing says why, and that reason (not a generic text) becomes the job's error."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.pipeline.executor import Pipeline
from src.pipeline.job_models_v2 import StageConfig
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr
from tests.helpers.runtime_isolation import isolated_image_backends

GENERIC = "No images were generated successfully"


class _Client:
    """Fake WebUI client whose generation answer the test chooses."""

    options_write_enabled = True
    last_options_write_failure = None

    def __init__(self, images: list[str] | None = None, info: object = None) -> None:
        self.images = ["aGVsbG8="] if images is None else images
        self.info = {} if info is None else info

    def get_current_model(self):
        return "model-a.safetensors"

    def set_model(self, _name):
        return True

    def get_current_vae(self):
        return "Automatic"

    def set_vae(self, *_a, **_k):
        return True

    def check_connection(self, **_k):
        return True

    def generate_images(self, *, stage, payload, **_k):
        return SimpleNamespace(
            ok=True,
            result=SimpleNamespace(
                images=list(self.images), info=self.info, stage=stage, timings={}
            ),
        )


def _run(client: _Client, tmp_path: Path, **patches):
    pipeline = Pipeline(client, StructuredLogger(output_dir=tmp_path / "logs"))
    runner = PipelineRunner(
        client,
        StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "runs"),
        image_backend_registry=isolated_image_backends(),
    )
    runner._pipeline = pipeline
    njr = make_pipeline_njr(
        job_id="n11-no-output",
        config={
            "model": "model-a.safetensors",
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
        base_model="model-a.safetensors",
        stage_chain=[StageConfig(stage_type="txt2img", enabled=True, steps=5, cfg_scale=7.0)],
    )
    with patch.object(pipeline, "_ensure_webui_true_ready", return_value=None):
        if patches:
            with patch.multiple(pipeline, **patches):
                result = runner.run_njr(njr)
        else:
            result = runner.run_njr(njr)
    return result, pipeline


def test_an_empty_backend_answer_names_the_stage_and_the_backend_detail(tmp_path):
    result, pipeline = _run(
        _Client(images=[], info={"error": "OutOfMemoryError", "detail": "CUDA out of memory"}),
        tmp_path,
    )

    assert result.success is False
    assert result.error != GENERIC
    assert "txt2img" in result.error and "no images" in result.error
    assert "CUDA out of memory" in result.error
    assert pipeline.take_no_output_reason() is None  # taken once, never carried into the next job


def test_an_empty_answer_without_detail_still_says_what_happened(tmp_path):
    result, _ = _run(_Client(images=[]), tmp_path)

    assert result.error != GENERIC
    assert "txt2img" in result.error and "returned no images" in result.error


def test_a_stage_exception_that_was_swallowed_reaches_the_job_error(tmp_path):
    boom = RuntimeError("sampler 'Euler z' not found")
    result, _ = _run(
        _Client(),
        tmp_path,
        _generate_images_with_progress=lambda *a, **k: (_ for _ in ()).throw(boom),
    )

    assert result.success is False
    assert "txt2img" in result.error and "sampler 'Euler z' not found" in result.error
    assert "RuntimeError" in result.error


def test_a_save_failure_says_the_images_could_not_be_saved(tmp_path):
    with patch("src.pipeline.executor.save_image_from_base64", return_value=None):
        result, _ = _run(_Client(), tmp_path)

    assert result.success is False
    assert "txt2img" in result.error and "could not be saved" in result.error


def test_the_reason_is_bounded_and_single_line(tmp_path):
    boom = RuntimeError("line one\nline two " + "x" * 2000)
    result, _ = _run(
        _Client(),
        tmp_path,
        _generate_images_with_progress=lambda *a, **k: (_ for _ in ()).throw(boom),
    )

    assert "\n" not in result.error and len(result.error) <= 600
    assert "line one line two" in result.error


def test_with_no_recorded_reason_the_fallback_names_the_stage(tmp_path):
    result, _ = _run(_Client(), tmp_path, run_txt2img_stage=lambda *a, **k: None)

    assert result.error.startswith(GENERIC)
    assert "txt2img" in result.error


class _DeadForge:
    def __init__(self, record):
        self.record = record
        self.asked_since: list[float] = []

    def unexpected_exit_since(self, started):
        self.asked_since.append(started)
        return self.record


def test_a_job_that_failed_after_forge_died_says_how_forge_died(tmp_path):
    forge = _DeadForge({"exit_cause": "exit code 0xC0000005: access violation", "pid": 9})
    with patch("src.pipeline.pipeline_runner.get_global_webui_process_manager", return_value=forge):
        result, _ = _run(_Client(images=[]), tmp_path)

    assert result.error.startswith("txt2img: the backend returned no images")
    assert result.error.endswith(
        "(the managed WebUI process exited during this job: exit code 0xC0000005: access violation)"
    )
    assert forge.asked_since, "the runner asks only about exits since this job started"


def test_no_exit_during_the_job_leaves_the_error_alone(tmp_path):
    with patch(
        "src.pipeline.pipeline_runner.get_global_webui_process_manager",
        return_value=_DeadForge(None),
    ):
        result, _ = _run(_Client(images=[]), tmp_path)

    assert "managed WebUI process" not in result.error
