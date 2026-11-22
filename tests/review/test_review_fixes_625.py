"""PR-REVIEW-FIXES-625: regression tests for the defects the live acceptance run found in the Review lifecycle."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.controller.app_controller import AppController
from src.controller.review_batch_service import prepare_review_batch, review_output_dir
from src.review.archive import configured_output_root
from src.utils.image_metadata import build_contract_kv, write_image_metadata

FALLBACK = {"model": "fallback.safetensors", "steps": 20, "cfg_scale": 7, "img2img": {"denoising_strength": 0.3}}


class _Config:
    def __init__(self, output_dir: str | None) -> None:
        self._output_dir = output_dir

    def get_setting(self, key: str, default=None):
        return self._output_dir if key == "output_dir" and self._output_dir else default


def _controller(*, output_dir: str | None = None, parent_jobs: dict | None = None):
    controller = object.__new__(AppController)
    controller._append_log = lambda _: None
    if output_dir is not None:
        controller._config_manager = _Config(output_dir)
    jobs = parent_jobs or {}
    controller.job_service = SimpleNamespace(
        job_queue=SimpleNamespace(get_job=lambda job_id: jobs.get(job_id))
    )
    return controller


def _image(path: Path, *, stage_model: str | None, job_id: str = "parent-job", stage: str = "txt2img") -> Path:
    Image.new("RGB", (32, 32), (10, 20, 30)).save(path)
    payload = {
        "job_id": job_id,
        "generation": {"model": stage_model} if stage_model and stage_model != "Unknown" else {},
        "stage_manifest": {
            "stage": stage, "final_prompt": "neutral", "config": {"steps": 20, "cfg_scale": 7},
            **({"model": stage_model} if stage_model else {}),
        },
    }
    assert write_image_metadata(path, build_contract_kv(payload, job_id=job_id, run_id="synthetic", stage=stage))
    return path


def _prepare(controller, path: Path, **options):
    return prepare_review_batch(
        controller, image_paths=[str(path)], stages=["img2img"], fallback_config=FALLBACK, **options
    )


# --- A: re-work output location -------------------------------------------------------------------------------

def test_rework_jobs_use_the_configured_output_root(tmp_path):
    configured = tmp_path / "chosen output"
    controller = _controller(output_dir=str(configured))
    path = _image(tmp_path / "src.png", stage_model="chk.safetensors")
    preview = _prepare(controller, path)
    job = preview.jobs[0]
    assert Path(job.output_plan.base_output_dir) == configured_output_root(controller._config_manager)
    assert Path(job.path_output_dir) == configured.resolve()
    assert Path(job.path_output_dir).is_absolute()


def test_rework_batch_size_greater_than_one_also_uses_the_configured_root(tmp_path):
    configured = tmp_path / "chosen output"
    controller = _controller(output_dir=str(configured))
    paths = [_image(tmp_path / f"src{i}.png", stage_model="chk.safetensors", job_id=f"p{i}") for i in range(2)]
    preview = prepare_review_batch(
        controller, image_paths=[str(p) for p in paths], stages=["img2img"], fallback_config=FALLBACK, batch_size=2
    )
    assert preview.jobs
    assert {Path(job.path_output_dir) for job in preview.jobs} == {configured.resolve()}


def test_route_folder_in_the_setting_is_stripped_like_the_archive_root(tmp_path):
    controller = _controller(output_dir=str(tmp_path / "out" / "Pipeline"))
    assert Path(review_output_dir(controller)) == (tmp_path / "out").resolve()


def test_a_bare_controller_keeps_the_builder_default(tmp_path):
    controller = _controller()
    path = _image(tmp_path / "src.png", stage_model="chk.safetensors")
    assert _prepare(controller, path).jobs[0].path_output_dir == "output"


# --- B: checkpoint carried into re-work children ------------------------------------------------------------

def test_missing_embedded_checkpoint_is_carried_from_the_parent_job(tmp_path):
    parent = SimpleNamespace(snapshot={"base_model": "parent-model.safetensors"})
    controller = _controller(output_dir=str(tmp_path / "out"), parent_jobs={"parent-job": parent})
    path = _image(tmp_path / "child.png", stage_model="Unknown", stage="img2img")
    preview = _prepare(controller, path)
    assert preview.items[0].model == "parent-model.safetensors"
    job = preview.jobs[0]
    assert job.base_model == "parent-model.safetensors"
    assert job.config["img2img"]["model"] == "parent-model.safetensors"


def test_embedded_checkpoint_wins_over_the_parent_job(tmp_path):
    parent = SimpleNamespace(snapshot={"base_model": "parent-model.safetensors"})
    controller = _controller(output_dir=str(tmp_path / "out"), parent_jobs={"parent-job": parent})
    path = _image(tmp_path / "src.png", stage_model="embedded.safetensors")
    assert _prepare(controller, path).items[0].model == "embedded.safetensors"


def test_unknown_parent_leaves_the_checkpoint_empty_without_failing(tmp_path):
    controller = _controller(output_dir=str(tmp_path / "out"))
    path = _image(tmp_path / "child.png", stage_model="Unknown", stage="img2img")
    baseline = controller._extract_reprocess_baseline_from_image(path)
    assert baseline["model"] is None


# --- B: the img2img stage manifest records the checkpoint ----------------------------------------------------

def _run_img2img(tmp_path, monkeypatch, config):
    from src.pipeline.executor import Pipeline
    from src.utils import StructuredLogger

    class _Client:
        options_write_enabled = True

        def get_current_model(self):
            return "current.safetensors"

        def get_current_vae(self):
            return "vae.pt"

    source = tmp_path / "input.png"
    source.write_bytes(b"")
    pipeline = Pipeline(client=_Client(), structured_logger=StructuredLogger())
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_load_image_base64", lambda _path: "INPUT")
    monkeypatch.setattr(
        pipeline, "_generate_images",
        lambda _stage, _payload: {"images": ["x"], "info": {"seed": 1, "subseed": 2}},
    )

    def save(_data, path, metadata_builder=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("image", encoding="utf-8")
        return path

    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", save)
    return pipeline.run_img2img_stage(
        input_image_path=source, prompt="p", config=config, output_dir=tmp_path, image_name="child"
    )


def test_img2img_manifest_records_the_stage_checkpoint_and_vae(tmp_path, monkeypatch):
    result = _run_img2img(
        tmp_path, monkeypatch,
        {"steps": 20, "cfg_scale": 7.0, "denoising_strength": 0.3, "width": 64, "height": 64,
         "model": "stage-model.safetensors", "vae": "Automatic"},
    )
    assert result["model"] == "stage-model.safetensors"
    assert result["vae"] == "Automatic"


def test_img2img_manifest_has_no_placeholder_when_no_checkpoint_was_requested(tmp_path, monkeypatch):
    result = _run_img2img(
        tmp_path, monkeypatch, {"steps": 20, "cfg_scale": 7.0, "denoising_strength": 0.3, "width": 64, "height": 64}
    )
    assert "model" not in result and "vae" not in result
