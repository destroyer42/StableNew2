"""Frozen masked reprocess jobs: CPU-only real image bytes, admission and wire integrity."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.controller import masked_edit_service as edits
from src.image_backends import masked_inpaint as capability
from src.image_backends.image_backend_types import ImageExecutionRequest
from src.image_backends.webui_family_backend import WebUIFamilyImageBackend
from src.pipeline import image_edit_inputs as inputs
from src.pipeline.executor import Pipeline
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.utils import StructuredLogger
from tests.pipeline.test_img2img_masked_edit_runtime import _Client, _fake_save_image


def png(size=(128, 128), *, mask=False):
    image = Image.new("L" if mask else "RGB", size, 0 if mask else "blue")
    if mask:
        ImageDraw.Draw(image).rectangle((20, 20, 60, 60), fill=255)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(
        inputs, "default_snapshot_root", lambda: tmp_path / "state" / "image_edit_inputs"
    )

    def lookup(name):
        return (
            CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
            if name == "sdxl"
            else None
        )

    monkeypatch.setattr(capability, "RegistryFamilyLookup", lambda: lookup)
    source = tmp_path / "original.png"
    source.write_bytes(png())
    config = {
        "model": "sdxl",
        "backend_options": {"image": {"backend_id": "forge_webui"}},
        "img2img": {
            "steps": 23,
            "sampler_name": "Euler",
            "scheduler": "Karras",
            "cfg_scale": 6.5,
            "seed": 42,
        },
    }
    settings = edits.MaskEditSettings("replace the blue region with flowers", 0.55, 8, 24)

    def prepare(**kwargs):
        args = {
            "source_path": str(source),
            "source_sha256": kwargs.get("source_sha256") or inputs.read_source(source).sha256,
            "mask_data": png(mask=True),
            "settings": settings,
            "fallback_config": deepcopy(config),
            "baseline": {"model": "sdxl", "job_id": "parent-job"},
        }
        args.update(kwargs)
        return edits.prepare_mask_edit(**args)

    return SimpleNamespace(source=source, prepare=prepare, config=config, settings=settings)


def test_preview_submits_identical_njr_and_keeps_original_and_lineage(prepared):
    original = prepared.source.read_bytes()
    preview = prepared.prepare()
    job = preview.job
    frozen = deepcopy(job.to_queue_snapshot())
    service = SimpleNamespace(submit_njrs=Mock(return_value=[job.job_id]))
    assert preview.submit(service) == 1
    assert service.submit_njrs.call_args.args[0][0] is job
    assert job.to_queue_snapshot() == frozen
    assert prepared.source.read_bytes() == original
    assert job.input_image_paths[0] != str(prepared.source)
    assert job.source.parent_job_id == "parent-job"
    assert job.source.parent_artifact_id == "sha256:" + inputs.read_source(prepared.source).sha256
    stage = job.config["img2img"]
    assert (stage["width"], stage["height"], stage["denoising_strength"]) == (128, 128, 0.55)
    assert stage["mask_image_path"] != str(prepared.source)
    assert not verify_inputs(frozen_input_checks(job))
    assert any(check.label == "inpainting mask" for check in frozen_input_checks(job))
    restored = NormalizedJobRecord.from_dict(json.loads(json.dumps(job.to_dict())))
    assert restored.to_queue_snapshot() == job.to_queue_snapshot()
    assert not verify_inputs(frozen_input_checks(restored))


def test_explicit_edit_settings_override_inherited_flat_aliases(prepared):
    baseline = {
        "model": "sdxl",
        "config": {
            "img2img_denoising_strength": 0.1,
            "width": 1024,
            "height": 1024,
            "seed": -1,
            "txt2img": {"seed": -1},
        },
    }
    preview = prepared.prepare(baseline=baseline)
    assert preview.job.stage_chain[0].denoising_strength == 0.55
    assert preview.job.width == 128 and preview.job.height == 128
    assert preview.job.config["seed"] == preview.job.config["img2img"]["seed"] == 42
    assert preview.job.config["txt2img"]["seed"] == 42


def test_snapshot_path_cannot_escape_owned_state(prepared):
    preview = prepared.prepare()
    raw = dict(preview.job.config["img2img"][inputs.KEY]["mask"])
    raw["path"] = str(prepared.source)
    with pytest.raises(ValueError, match="outside StableNew-owned"):
        inputs.verified_snapshot(raw)


def _redirect_directory(link, target):
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("directory", ["state", "image_edit_inputs"])
def test_redirected_snapshot_directory_refused_before_any_write(prepared, tmp_path, directory):
    root = inputs.default_snapshot_root()
    link = root.parent if directory == "state" else root
    outside = tmp_path / "outside"
    _redirect_directory(link, outside)
    with pytest.raises(ValueError, match="outside StableNew-owned"):
        prepared.prepare()
    assert list(outside.iterdir()) == []


def test_redirected_snapshot_directory_is_refused_during_verification(prepared, tmp_path):
    preview = prepared.prepare()
    root = inputs.default_snapshot_root()
    outside = tmp_path / "outside"
    root.rename(outside)
    _redirect_directory(root, outside)
    raw = preview.job.config["img2img"][inputs.KEY]["source"]
    with pytest.raises(ValueError, match="outside StableNew-owned"):
        inputs.verified_snapshot(raw)


def test_animation_is_not_silently_treated_as_one_still_image():
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), "blue").save(
        stream,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGB", (128, 128), "green")],
        duration=100,
        loop=0,
    )
    with pytest.raises(ValueError, match="still image"):
        inputs.inspect_bytes(stream.getvalue())


def test_missing_or_corrupt_source_refused_without_building_a_job(prepared):
    sha = inputs.read_source(prepared.source).sha256
    prepared.source.unlink()
    with pytest.raises((ValueError, OSError)):
        prepared.prepare(source_sha256=sha)
    prepared.source.write_bytes(b"broken image")
    with pytest.raises((ValueError, OSError)):
        prepared.prepare(source_sha256=sha)


def test_backend_cannot_silently_project_a_masked_job_to_a1111(prepared):
    from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend

    preview = prepared.prepare()
    with pytest.raises(ValueError, match="Masked Review edits require"):
        A1111WebUIImageBackend().validate_njr_intent(preview.job, ["img2img"])


@pytest.mark.parametrize(
    "change", ["original", "source_snapshot", "mask_snapshot", "missing_mask", "corrupt_mask"]
)
def test_input_drift_refuses_before_admission(prepared, change):
    preview = prepared.prepare()
    config = preview.job.config["img2img"]
    contract = config[inputs.KEY]
    path = {
        "original": prepared.source,
        "source_snapshot": Path(contract["source"]["path"]),
        "mask_snapshot": Path(contract["mask"]["path"]),
        "missing_mask": Path(contract["mask"]["path"]),
        "corrupt_mask": Path(contract["mask"]["path"]),
    }[change]
    if change == "missing_mask":
        path.unlink()
    elif change == "corrupt_mask":
        path.write_bytes(b"not an image")
    else:
        Image.new("L" if "mask" in change else "RGB", (128, 128), 127).save(path)
    service = SimpleNamespace(submit_njrs=Mock())
    with pytest.raises((ValueError, OSError)):
        preview.submit(service)
    service.submit_njrs.assert_not_called()


def test_dimension_mismatch_and_empty_mask_refused(prepared):
    with pytest.raises(ValueError, match="dimensions"):
        prepared.prepare(mask_data=png((64, 64), mask=True))
    stream = io.BytesIO()
    Image.new("L", (128, 128), 0).save(stream, format="PNG")
    with pytest.raises(ValueError, match="Paint"):
        prepared.prepare(mask_data=stream.getvalue())


@pytest.mark.parametrize(
    "backend,model",
    [
        ("a1111", "sdxl"),
        ("comfy", "sdxl"),
        ("forge_webui", "unknown"),
        ("forge_webui", "flux-2-klein-4b-fp8.safetensors"),
    ],
)
def test_unsupported_target_refused_without_freezing(prepared, backend, model):
    config = deepcopy(prepared.config)
    config["backend_options"]["image"]["backend_id"] = backend
    with pytest.raises(ValueError, match="Masked Review edits require"):
        prepared.prepare(fallback_config=config, baseline={"model": model})
    assert not inputs.default_snapshot_root().exists()


@pytest.mark.parametrize(
    "settings",
    [
        edits.MaskEditSettings(""),
        edits.MaskEditSettings("edit", float("nan")),
        edits.MaskEditSettings("edit", 1.1),
        edits.MaskEditSettings("edit", mask_blur=-1),
        edits.MaskEditSettings("edit", padding=300),
    ],
)
def test_invalid_settings_refused(prepared, settings):
    with pytest.raises(ValueError):
        prepared.prepare(settings=settings)


def test_failed_admission_does_not_change_preview_or_inputs(prepared):
    preview = prepared.prepare()
    before = deepcopy(preview.job.to_queue_snapshot())
    service = SimpleNamespace(submit_njrs=Mock(side_effect=ValueError("admission refused")))
    with pytest.raises(ValueError, match="admission refused"):
        preview.submit(service)
    assert preview.job.to_queue_snapshot() == before
    assert not verify_inputs(frozen_input_checks(preview.job))


def test_frozen_wire_payload_uses_verified_bytes_even_if_files_change_after_read(
    prepared, tmp_path, monkeypatch
):
    preview = prepared.prepare()
    stage = preview.job.stage_chain[0]
    request = ImageExecutionRequest(
        backend_id="forge_webui",
        stage_name="img2img",
        stage_config=stage.to_dict(),
        output_dir=tmp_path,
        input_image_path=Path(preview.job.input_image_paths[0]),
        prompt=preview.job.positive_prompt,
        selected_model=preview.job.base_model,
        sampler=stage.sampler_name,
        scheduler=stage.scheduler,
        steps=stage.steps,
        cfg_scale=stage.cfg_scale,
        seed=preview.job.config["seed"],
        execution_config=dict(preview.job.config),
    )
    config = WebUIFamilyImageBackend._stage_executor_config(request)
    source_data, mask_data = inputs.verified_inputs(config, preview.job.input_image_paths[0])
    pipeline = Pipeline(client=_Client(), structured_logger=StructuredLogger())
    captured = {}

    def after_read(*_args, **_kwargs):
        Path(config["mask_image_path"]).write_bytes(png(mask=False))

    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", after_read)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_: None)
    monkeypatch.setattr(
        pipeline,
        "_generate_images",
        lambda stage, payload: captured.update(stage=stage, payload=deepcopy(payload))
        or {"images": ["ignored"], "info": {"seed": 42}},
    )
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)
    config["model"] = "sdxl"
    result = pipeline.run_img2img_stage(
        Path(preview.job.input_image_paths[0]),
        preview.job.positive_prompt,
        config,
        tmp_path,
        "masked",
        full_config=dict(preview.job.config),
    )
    assert result is not None
    payload = captured["payload"]
    assert captured["stage"] == "img2img"
    assert base64.b64decode(payload["init_images"][0]) == source_data
    assert base64.b64decode(payload["mask"]) == mask_data
    assert payload["mask_blur"] == 8 and payload["inpaint_full_res_padding"] == 24
    assert payload["inpainting_mask_invert"] == 0 and payload["inpainting_fill"] == 1
    assert payload["prompt"] == preview.job.positive_prompt
    assert payload["denoising_strength"] == 0.55


def test_corrupt_frozen_input_never_calls_backend(prepared, tmp_path, monkeypatch):
    preview = prepared.prepare()
    config = dict(preview.job.config["img2img"])
    Path(config["mask_image_path"]).write_bytes(b"corrupt")
    pipeline = Pipeline(client=_Client(), structured_logger=StructuredLogger())
    generate = Mock()
    monkeypatch.setattr(pipeline, "_generate_images", generate)
    result = pipeline.run_img2img_stage(
        Path(preview.job.input_image_paths[0]), "edit", config, tmp_path, "bad"
    )
    assert result is None
    generate.assert_not_called()
