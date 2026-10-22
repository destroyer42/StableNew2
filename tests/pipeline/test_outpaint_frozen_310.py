"""Frozen outpainting jobs: preview/queue identity, input integrity, finalization and layering (CPU only)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.controller import outpaint_edit_service as service
from src.controller.reprocess_admission import submit_reprocess_njrs
from src.image_backends import masked_inpaint as capability
from src.pipeline import image_edit_inputs as inputs
from src.pipeline.executor import Pipeline
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.outpaint_canvas import Extents
from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs
from src.utils import StructuredLogger
from tests.pipeline.test_img2img_masked_edit_runtime import _Client

W, H = 128, 96
EXTENTS = Extents(left=16, right=8, top=24, bottom=0)


def original_image() -> Image.Image:
    image = Image.new("RGB", (W, H))
    image.putdata(
        [((x * 2) % 256, (y * 3) % 256, (x + y) % 256) for y in range(H) for x in range(W)]
    )
    return image


def png_bytes(image: Image.Image) -> bytes:
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
    source.write_bytes(png_bytes(original_image()))
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
    settings = service.OutpaintSettings("a wide meadow continues", EXTENTS, 0.8, 6)

    def prepare(**kwargs):
        args = {
            "source_path": str(source),
            "source_sha256": kwargs.get("source_sha256") or inputs.read_source(source).sha256,
            "settings": settings,
            "fallback_config": deepcopy(config),
            "baseline": {"model": "sdxl", "job_id": "parent-job"},
        }
        args.update(kwargs)
        return service.prepare_outpaint_edit(**args)

    return SimpleNamespace(
        source=source, prepare=prepare, config=config, settings=settings, tmp=tmp_path
    )


def frozen_of(job):
    return job.config["img2img"][inputs.KEY]


# ------------------------------------------------------------------ preview and queue identity


def test_preview_is_the_exact_immutable_job_submitted_once_with_lineage(prepared):
    original = prepared.source.read_bytes()
    preview = prepared.prepare()
    job = preview.job
    frozen = deepcopy(job.to_queue_snapshot())
    admission = SimpleNamespace(submit_njrs=Mock(return_value=[job.job_id]))
    assert preview.submit(admission) == 1
    admission.submit_njrs.assert_called_once()
    assert admission.submit_njrs.call_args.args[0][0] is job
    assert job.to_queue_snapshot() == frozen
    assert prepared.source.read_bytes() == original
    assert tuple(job.stage_chain_labels) == ("img2img",)
    assert job.source.parent_job_id == "parent-job"
    assert job.source.parent_artifact_id == "sha256:" + hashlib.sha256(original).hexdigest()
    stage = job.config["img2img"]
    expanded = (W + 24, H + 24)
    assert (stage["width"], stage["height"]) == expanded == (job.width, job.height)
    assert stage["denoising_strength"] == 0.8 and stage["mask_blur"] == 6
    assert stage["inpaint_full_res"] is False and stage["inpainting_mask_invert"] is False
    contract = frozen_of(job)
    record = contract["outpaint"]
    assert record["schema"] == "stablenew.image_edit.outpaint.v1"
    assert record["extents"] == EXTENTS.as_dict()
    assert record["original_bbox"] == {"left": 16, "top": 24, "right": 16 + W, "bottom": 24 + H}
    assert contract["original"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert job.input_image_paths[0] == contract["source"]["path"] != str(prepared.source)
    assert len(json.dumps(job.to_queue_snapshot())) < 60_000  # snapshots by identity, no raw bytes
    restored = NormalizedJobRecord.from_dict(json.loads(json.dumps(job.to_dict())))
    assert restored.to_queue_snapshot() == job.to_queue_snapshot()
    assert not verify_inputs(frozen_input_checks(restored))
    assert any(check.label == "outpaint original image" for check in frozen_input_checks(job))


def test_frozen_snapshots_hold_the_derived_expanded_image_and_mask(prepared):
    job = prepared.prepare().job
    contract = frozen_of(job)
    expanded = Image.open(contract["source"]["path"])
    mask = Image.open(contract["mask"]["path"])
    assert expanded.size == mask.size == (W + 24, H + 24)
    assert expanded.crop((16, 24, 16 + W, 24 + H)).tobytes() == original_image().tobytes()
    assert mask.crop((16, 24, 16 + W, 24 + H)).getextrema() == (0, 0)
    assert mask.getpixel((0, 0)) == 255 and mask.getpixel((W + 23, H + 23)) == 255


def test_preview_summary_is_bounded_and_states_policy_and_identity(prepared):
    preview = prepared.prepare()
    summary = service.outpaint_preview_summary(preview)
    for key in (
        "original",
        "expanded",
        "extents",
        "original_bbox",
        "mask",
        "model",
        "backend",
        "prompt",
        "denoising_strength",
        "preservation",
        "snapshots",
        "lineage",
        "pressure",
        "quality_notice",
    ):
        assert key in summary
    assert summary["preservation"]["policy"] == "original_pixels_pasted.v1"
    assert summary["lineage"]["parent_job_id"] == "parent-job"
    assert "not been qualified" in summary["quality_notice"]
    assert len(json.dumps(summary)) < 12_000


# ------------------------------------------------------------------ refusals before anything is frozen


@pytest.mark.parametrize(
    "backend,model",
    [
        ("a1111", "sdxl"),
        ("comfy", "sdxl"),
        ("forge_webui", "unknown"),
        ("forge_webui", "flux-2-klein-4b-fp8.safetensors"),
    ],
)
def test_unsupported_targets_are_refused_without_freezing(prepared, backend, model):
    config = deepcopy(prepared.config)
    config["backend_options"]["image"]["backend_id"] = backend
    with pytest.raises(ValueError, match="require Forge"):
        prepared.prepare(fallback_config=config, baseline={"model": model})
    assert not inputs.default_snapshot_root().exists()


@pytest.mark.parametrize(
    "extents,message",
    [
        (Extents(), "at least one"),
        (Extents(left=-8), "negative"),
        (Extents(left=5), "multiple of 8"),
        (Extents(right=4096), "supported"),
        (Extents(bottom=3200, right=3000), "supported|too large"),
    ],
)
def test_invalid_geometry_refused_without_freezing(prepared, extents, message):
    settings = service.OutpaintSettings("more sky", extents)
    with pytest.raises(ValueError, match=message):
        prepared.prepare(settings=settings)
    assert not inputs.default_snapshot_root().exists()


@pytest.mark.parametrize(
    "settings",
    [
        service.OutpaintSettings("", EXTENTS),
        service.OutpaintSettings("x", EXTENTS, float("nan")),
        service.OutpaintSettings("x", EXTENTS, 0.0),
        service.OutpaintSettings("x", EXTENTS, 1.2),
        service.OutpaintSettings("x", EXTENTS, mask_blur=-1),
        service.OutpaintSettings("x", EXTENTS, mask_blur=65),
    ],
)
def test_invalid_settings_refused(prepared, settings):
    with pytest.raises(ValueError):
        prepared.prepare(settings=settings)


def test_source_changed_missing_corrupt_or_animated_is_refused(prepared):
    sha = inputs.read_source(prepared.source).sha256
    Image.new("RGB", (W, H), "green").save(prepared.source)
    with pytest.raises(ValueError, match="Source changed"):
        prepared.prepare(source_sha256=sha)
    prepared.source.write_bytes(b"broken")
    with pytest.raises((ValueError, OSError)):
        prepared.prepare(source_sha256=sha)
    prepared.source.unlink()
    with pytest.raises((ValueError, OSError)):
        prepared.prepare(source_sha256=sha)
    stream = io.BytesIO()
    Image.new("RGB", (W, H), "blue").save(
        stream,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGB", (W, H))],
        duration=50,
        loop=0,
    )
    prepared.source.write_bytes(stream.getvalue())
    with pytest.raises(ValueError, match="still image"):
        prepared.prepare(source_sha256=hashlib.sha256(stream.getvalue()).hexdigest())


# ------------------------------------------------------------------ frozen identity


def _snapshot_path(job, key):
    return Path(frozen_of(job)[key]["path"])


@pytest.mark.parametrize("target", ["source", "mask", "original"])
def test_same_size_content_replacement_of_a_snapshot_refuses_admission(prepared, target):
    preview = prepared.prepare()
    path = _snapshot_path(preview.job, target)
    with Image.open(path) as current:
        size, mode = current.size, current.mode
    Image.new(mode, size, 127).save(path, format="PNG")
    admission = SimpleNamespace(submit_njrs=Mock())
    with pytest.raises((ValueError, OSError)):
        preview.submit(admission)
    admission.submit_njrs.assert_not_called()


@pytest.mark.parametrize("target", ["source", "mask", "original"])
def test_missing_or_corrupt_snapshot_refuses_admission(prepared, target):
    preview = prepared.prepare()
    path = _snapshot_path(preview.job, target)
    path.write_bytes(b"not an image")
    admission = SimpleNamespace(submit_njrs=Mock())
    with pytest.raises((ValueError, OSError)):
        preview.submit(admission)
    path.unlink()
    with pytest.raises((ValueError, OSError)):
        preview.submit(admission)
    admission.submit_njrs.assert_not_called()


def test_original_file_changed_after_preview_refuses_admission(prepared):
    preview = prepared.prepare()
    Image.new("RGB", (W, H), "green").save(prepared.source)  # same dimensions, different content
    admission = SimpleNamespace(submit_njrs=Mock())
    with pytest.raises(ValueError, match="Source changed after Preview"):
        preview.submit(admission)
    admission.submit_njrs.assert_not_called()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["outpaint"]["extents"].__setitem__("left", 24),
        lambda c: c["outpaint"]["original_bbox"].__setitem__("left", 0),
        lambda c: c["outpaint"]["expanded_size"].__setitem__("width", 1),
        lambda c: c["outpaint"].__setitem__("original_sha256", "0" * 64),
        lambda c: c["outpaint"].__setitem__("padding_policy", "mirror"),
        lambda c: c["outpaint"].pop("schema"),
    ],
)
def test_forged_outpaint_metadata_is_refused(prepared, mutate):
    job = prepared.prepare().job
    stage = thaw_json(job.config["img2img"])
    mutate(stage[inputs.KEY])
    with pytest.raises(ValueError):
        inputs.verified_inputs(stage, job.input_image_paths[0])


@pytest.mark.parametrize("dropped", ["outpaint", "original"])
def test_dropping_half_of_the_outpaint_contract_cannot_downgrade_to_an_unpreserved_edit(
    prepared, dropped
):
    job = prepared.prepare().job
    stage = thaw_json(job.config["img2img"])
    del stage[inputs.KEY][dropped]
    with pytest.raises(ValueError, match="Incomplete frozen outpaint"):
        inputs.verified_inputs(stage, job.input_image_paths[0])


def test_deleting_the_whole_outpaint_contract_cannot_downgrade_to_an_unpreserved_edit(prepared):
    job = prepared.prepare().job
    assert job.config["img2img"]["edit_operation"] == "outpaint"
    stage = thaw_json(job.config["img2img"])
    del stage[inputs.KEY]["outpaint"], stage[inputs.KEY]["original"]
    with pytest.raises(ValueError, match="Incomplete frozen outpaint"):
        inputs.verified_inputs(stage, job.input_image_paths[0])


def test_the_operation_marker_survives_the_backend_adapter_and_guards_dispatch(prepared, tmp_path):
    from src.image_backends.image_backend_types import ImageExecutionRequest
    from src.image_backends.webui_family_backend import WebUIFamilyImageBackend

    job = prepared.prepare().job
    stage = job.stage_chain[0]
    request = ImageExecutionRequest(
        backend_id="forge_webui",
        stage_name="img2img",
        stage_config=stage.to_dict(),
        output_dir=tmp_path,
        input_image_path=Path(job.input_image_paths[0]),
        prompt=job.positive_prompt,
        selected_model=job.base_model,
        sampler=stage.sampler_name,
        scheduler=stage.scheduler,
        steps=stage.steps,
        cfg_scale=stage.cfg_scale,
        seed=job.config["seed"],
        execution_config=dict(job.config),
    )
    config = WebUIFamilyImageBackend._stage_executor_config(request)
    assert config["edit_operation"] == "outpaint"
    inputs.verified_inputs(config, job.input_image_paths[0])
    assert inputs.verified_outpaint(config) is not None
    thawed = thaw_json(config)
    del thawed[inputs.KEY]["outpaint"], thawed[inputs.KEY]["original"]
    with pytest.raises(ValueError, match="Incomplete frozen outpaint"):
        inputs.verified_inputs(thawed, job.input_image_paths[0])


def test_ordinary_mask_edits_carry_no_operation_marker(prepared):
    from src.controller import masked_edit_service as edits
    from tests.pipeline.test_inpaint300 import png as mask_png

    source = prepared.tmp / "plain.png"
    source.write_bytes(mask_png())
    job = edits.prepare_mask_edit(
        source_path=str(source),
        source_sha256=inputs.read_source(source).sha256,
        mask_data=mask_png(mask=True),
        settings=edits.MaskEditSettings("edit", 0.5, 4, 8),
        fallback_config=deepcopy(prepared.config),
        baseline={"model": "sdxl"},
    ).job
    assert "edit_operation" not in job.config["img2img"]
    assert inputs.verified_outpaint(thaw_json(job.config["img2img"])) is None


def test_original_snapshot_path_cannot_escape_owned_state(prepared):
    job = prepared.prepare().job
    stage = thaw_json(job.config["img2img"])
    stage[inputs.KEY]["original"]["path"] = str(prepared.source)
    with pytest.raises(ValueError, match="outside StableNew-owned"):
        inputs.verified_inputs(stage, job.input_image_paths[0])


def test_model_or_backend_change_after_preview_refuses_admission(prepared, monkeypatch):
    preview = prepared.prepare()
    monkeypatch.setattr(capability, "RegistryFamilyLookup", lambda: (lambda _name: None))
    admission = SimpleNamespace(submit_njrs=Mock())
    with pytest.raises(ValueError, match="require Forge"):
        preview.submit(admission)
    admission.submit_njrs.assert_not_called()


def test_combined_stages_and_other_backends_are_refused_at_the_shared_boundary(prepared):
    job = prepared.prepare().job
    with pytest.raises(ValueError, match="one img2img stage"):
        capability.validate_frozen_mask_target(
            job.base_model, job.backend_options, job.config, ["img2img", "upscale"]
        )
    from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend

    with pytest.raises(ValueError, match="require Forge"):
        A1111WebUIImageBackend().validate_njr_intent(job, ["img2img"])


def test_failed_admission_leaves_the_preview_and_inputs_unchanged_and_never_retries(prepared):
    preview = prepared.prepare()
    before = deepcopy(preview.job.to_queue_snapshot())
    admission = SimpleNamespace(submit_njrs=Mock(side_effect=ValueError("admission refused")))
    with pytest.raises(ValueError, match="admission refused"):
        preview.submit(admission)
    assert admission.submit_njrs.call_count == 1
    assert preview.job.to_queue_snapshot() == before
    assert not verify_inputs(frozen_input_checks(preview.job))


def test_admission_uses_only_the_canonical_job_service_boundary(prepared):
    job = prepared.prepare().job
    admission = SimpleNamespace(
        submit_njrs=Mock(return_value=[job.job_id])
    )  # no other attribute exists
    assert submit_reprocess_njrs(admission, [job]) == 1
    policy = admission.submit_njrs.call_args.args[1]
    assert type(policy).__name__ == "SubmissionPolicy"


def test_new_modules_have_no_independent_runner_client_or_queue():
    forbidden = re.compile(
        r"PipelineRunner|SDWebUIClient|import requests|httpx|JobQueue|JobRepository|subprocess|threading"
    )
    root = Path(__file__).resolve().parents[2]
    for module in (
        "src/controller/outpaint_edit_service.py",
        "src/pipeline/outpaint_canvas.py",
        "src/gui_v2/outpaint_canvas_view.py",
    ):
        text = (root / module).read_text(encoding="utf-8")
        assert not forbidden.search(text), module


# ------------------------------------------------------------------ final pixel preservation at the artifact boundary


def _run_stage(prepared, job, tmp_path, monkeypatch, *, backend_image, calls=None):
    pipeline = Pipeline(client=_Client(), structured_logger=StructuredLogger())
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *a, **k: None)
    seen = [] if calls is None else calls

    def fake_generate(stage, payload):
        seen.append(deepcopy(payload))
        return {
            "images": [base64.b64encode(png_bytes(backend_image)).decode()],
            "info": {"seed": 42},
        }

    monkeypatch.setattr(pipeline, "_generate_images", fake_generate)
    config = dict(job.config["img2img"])
    config["model"] = "sdxl"
    output = tmp_path / "out"
    result = pipeline.run_img2img_stage(
        Path(job.input_image_paths[0]),
        job.positive_prompt,
        config,
        output,
        "outpaint",
        full_config=dict(job.config),
    )
    return result, output, seen


def _backend_image(job, *, inside=(250, 0, 250), outside=(10, 200, 10)):
    width, height = job.width, job.height
    image = Image.new("RGB", (width, height), outside)
    image.paste(Image.new("RGB", (W, H), inside), (16, 24))
    return image


def test_finalized_artifact_keeps_original_pixels_and_backend_exterior(prepared, monkeypatch):
    job = prepared.prepare().job
    protected = [
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            prepared.source,
            *map(
                Path,
                (
                    frozen_of(job)["source"]["path"],
                    frozen_of(job)["mask"]["path"],
                    frozen_of(job)["original"]["path"],
                ),
            ),
        )
    ]
    result, output, calls = _run_stage(
        prepared, job, prepared.tmp, monkeypatch, backend_image=_backend_image(job)
    )
    assert result is not None and len(calls) == 1
    payload = calls[0]
    assert (payload["width"], payload["height"]) == (W + 24, H + 24)
    assert (
        base64.b64decode(payload["init_images"][0]) == Path(job.input_image_paths[0]).read_bytes()
    )
    assert payload["inpaint_full_res"] is False and payload["mask_blur"] == 6
    saved = Image.open(result["path"])
    assert saved.size == (W + 24, H + 24)
    assert saved.crop((16, 24, 16 + W, 24 + H)).tobytes() == original_image().tobytes()
    assert saved.getpixel((0, 0)) == (10, 200, 10) and saved.getpixel((W + 23, H + 23)) == (
        10,
        200,
        10,
    )
    evidence = result["outpaint"]
    assert evidence["preservation_applied"] is True
    assert evidence["original_bbox"] == frozen_of(job)["outpaint"]["original_bbox"]
    manifest_path = (
        output / "manifests" / f"{Path(result['path']).stem}.json"
    )  # beside it sits an optimizer sidecar
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["outpaint"]["preservation_applied"] is True
    after = [
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            prepared.source,
            *map(
                Path,
                (
                    frozen_of(job)["source"]["path"],
                    frozen_of(job)["mask"]["path"],
                    frozen_of(job)["original"]["path"],
                ),
            ),
        )
    ]
    assert after == protected  # no source artifact or snapshot was modified


@pytest.mark.parametrize("size", [(W, H), (W + 24, H + 16), (8, 8)])
def test_wrong_sized_backend_result_creates_no_artifact(prepared, monkeypatch, size):
    job = prepared.prepare().job
    result, output, calls = _run_stage(
        prepared, job, prepared.tmp, monkeypatch, backend_image=Image.new("RGB", size, "red")
    )
    assert result is None and len(calls) == 1  # dispatched once, never replayed
    assert not list(output.rglob("*.png")) and not list(output.rglob("*.json"))


def test_corrupt_backend_result_creates_no_artifact(prepared, monkeypatch):
    job = prepared.prepare().job
    pipeline = Pipeline(client=_Client(), structured_logger=StructuredLogger())
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *a, **k: None)
    monkeypatch.setattr(
        pipeline,
        "_generate_images",
        lambda *_: {"images": [base64.b64encode(b"garbage").decode()], "info": {}},
    )
    config = dict(job.config["img2img"])
    config["model"] = "sdxl"
    result = pipeline.run_img2img_stage(
        Path(job.input_image_paths[0]),
        "x",
        config,
        prepared.tmp / "out",
        "bad",
        full_config=dict(job.config),
    )
    assert result is None
    assert not list((prepared.tmp / "out").rglob("*.png"))


def test_pre_dispatch_verification_refuses_before_any_backend_call(prepared, monkeypatch):
    job = prepared.prepare().job
    _snapshot_path(job, "original").write_bytes(b"corrupt")
    result, output, calls = _run_stage(
        prepared, job, prepared.tmp, monkeypatch, backend_image=_backend_image(job)
    )
    assert result is None and calls == []


def test_ordinary_mask_edits_are_not_composited(prepared, monkeypatch):
    """A masked edit (no outpaint record) keeps the backend pixels everywhere, exactly as before."""

    from src.controller import masked_edit_service as edits
    from tests.pipeline.test_inpaint300 import png as mask_png

    source = prepared.tmp / "edit.png"
    source.write_bytes(mask_png())
    job = edits.prepare_mask_edit(
        source_path=str(source),
        source_sha256=inputs.read_source(source).sha256,
        mask_data=mask_png(mask=True),
        settings=edits.MaskEditSettings("edit", 0.5, 4, 8),
        fallback_config=deepcopy(prepared.config),
        baseline={"model": "sdxl"},
    ).job
    backend = Image.new("RGB", (128, 128), (9, 9, 9))
    result, _, _ = _run_stage(prepared, job, prepared.tmp, monkeypatch, backend_image=backend)
    assert result is not None and "outpaint" not in result
    assert set(Image.open(result["path"]).getdata()) == {(9, 9, 9)}
