"""PR-IMG-MODELS-158: Review/reprocess refuses an exact profile's unsupported operation before queue admission."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image

import src.controller.reprocess_admission as admission_module
from src.controller.app_controller import AppController
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as ZP
from src.image_backends.operation_compatibility import OperationNotSupportedError
from src.review.workflow_adapter import ReviewWorkflowAdapter
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service_with_queue

ZIMAGE = ZP.transformer.filename
KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "ordinary.safetensors"
FALLBACK = {"steps": 20, "cfg_scale": 7.0, "img2img": {"denoising_strength": 0.2}}


def _controller(baselines: dict[str, dict]):
    with patch("src.controller.app_controller.AppController.__init__", return_value=None):
        controller = AppController.__new__(AppController)
    service, queue, _history = make_stubbed_job_service_with_queue()
    service.submit_njrs = Mock(wraps=service.submit_njrs)
    controller.job_service = service
    controller._append_log = Mock()
    controller._api_client = Mock()
    controller.cancel_token = None
    controller._build_reprocess_config = Mock(return_value=dict(FALLBACK))
    controller._extract_reprocess_baseline_from_image = Mock(
        side_effect=lambda path: baselines[Path(path).name]
    )
    return controller, service, queue


def _image(tmp_path: Path, name: str, size=(1024, 1024)) -> str:
    path = tmp_path / name
    Image.new("RGB", size, (30, 60, 90)).save(path)
    return str(path)


def _baseline(model: str, **config) -> dict:
    return {"prompt": "a ceramic teapot", "negative_prompt": "", "model": model, "vae": None, "stage": "txt2img",
            "config": config}


@pytest.mark.parametrize("stages", [["img2img"], ["adetailer"], ["upscale"], ["img2img", "adetailer", "upscale"]])
def test_zimage_reprocess_is_refused_before_any_queue_insertion(tmp_path, stages):
    image = _image(tmp_path, "z.png")
    controller, service, queue = _controller({"z.png": _baseline(ZIMAGE)})
    with pytest.raises(OperationNotSupportedError, match="Z-Image.*Nothing was queued"):
        controller.on_reprocess_images_with_prompt_delta(
            image_paths=[image], stages=stages, prompt_delta="warmer light"
        )
    service.submit_njrs.assert_not_called()
    assert queue.list_jobs() == []


def test_a_multi_image_zimage_batch_is_refused_as_a_whole(tmp_path):
    names = {f"z{i}.png": _baseline(ZIMAGE) for i in range(3)}
    images = [_image(tmp_path, name) for name in names]
    controller, service, queue = _controller(names)
    with pytest.raises(OperationNotSupportedError):
        controller.on_reprocess_images_with_prompt_delta(
            image_paths=images, stages=["upscale"], batch_size=3
        )
    service.submit_njrs.assert_not_called()
    assert queue.list_jobs() == []


def test_one_unsupported_image_refuses_the_whole_mixed_request_atomically(tmp_path):
    controller, service, queue = _controller({"a.png": _baseline(SDXL), "z.png": _baseline(ZIMAGE)})
    images = [_image(tmp_path, "a.png"), _image(tmp_path, "z.png")]
    with pytest.raises(OperationNotSupportedError):
        controller.on_reprocess_images_with_prompt_delta(image_paths=images, stages=["adetailer"], batch_size=2)
    service.submit_njrs.assert_not_called()
    assert queue.list_jobs() == []  # the ordinary SDXL image was not admitted either


@pytest.mark.parametrize("stages", [["img2img"], ["adetailer"], ["upscale"], ["img2img", "adetailer", "upscale"]])
def test_ordinary_sdxl_reprocess_behavior_is_unchanged(tmp_path, stages):
    image = _image(tmp_path, "a.png")
    controller, service, queue = _controller({"a.png": _baseline(SDXL, steps=32)})
    assert controller.on_reprocess_images_with_prompt_delta(
        image_paths=[image], stages=stages, prompt_delta="warmer light"
    ) == 1
    (job,) = queue.list_jobs()
    assert job.status.value == "queued"
    assert [stage.stage_type for stage in job._normalized_record.stages] == stages
    assert job._normalized_record.config["steps"] == 32


def test_explicit_klein_single_reference_edit_keeps_its_admission_and_source_binding(tmp_path):
    image = _image(tmp_path, "k.png", size=(1024, 1024))
    controller, service, queue = _controller({"k.png": _baseline(KLEIN)})
    marked = ReviewWorkflowAdapter.with_klein_edit_request(None, [Path(image)])
    assert controller.on_reprocess_images_with_prompt_delta(
        image_paths=[image], stages=["img2img"], prompt_delta="make the jacket red",
        prompt_mode="replace", negative_prompt_mode="replace", source_metadata_by_image=marked,
    ) == 1
    (job,) = queue.list_jobs()
    record = job._normalized_record
    item = record.extra_metadata["reprocess"]["source_items"][0]["metadata"]
    assert item["klein_single_reference_edit"]["mode"] == "single_reference_edit"
    assert len(item["klein_single_reference_edit"]["source_image_sha256"]) == 64
    assert [Path(p).name for p in record.input_image_paths] == ["k.png"]


def test_a_klein_img2img_that_was_not_explicitly_requested_is_refused_before_queueing(tmp_path):
    image = _image(tmp_path, "k.png")
    controller, service, queue = _controller({"k.png": _baseline(KLEIN)})
    with pytest.raises(OperationNotSupportedError, match="explicitly requested single-reference edit"):
        controller.on_reprocess_images_with_prompt_delta(image_paths=[image], stages=["img2img"])
    assert queue.list_jobs() == []


def test_review_preview_projects_the_same_readiness_without_changing_settings(tmp_path):
    z_image = _image(tmp_path, "z.png")
    s_image = _image(tmp_path, "a.png")
    controller, service, queue = _controller({"z.png": _baseline(ZIMAGE), "a.png": _baseline(SDXL)})
    adapter = ReviewWorkflowAdapter()
    original = dict(FALLBACK)

    refused = controller.get_review_reprocess_effective_settings_preview(
        image_path=z_image, stages=["adetailer"]
    )
    assert refused.effective_model == ZIMAGE
    assessment = adapter.assess_readiness(refused, backend_id="forge_webui")
    assert not assessment.ready
    summary = adapter.format_effective_settings_summary(refused, readiness=assessment)
    assert "Readiness: NOT READY" in summary and "Nothing is queued or changed" in summary
    assert "model=" + ZIMAGE in summary  # the effective model/settings stay visible, unchanged

    ready = controller.get_review_reprocess_effective_settings_preview(
        image_path=s_image, stages=["adetailer"]
    )
    ok = adapter.assess_readiness(ready, backend_id="forge_webui")
    assert ok.ready and "Readiness:" in adapter.format_effective_settings_summary(ready, readiness=ok)

    assert controller._build_reprocess_config.return_value == original
    assert queue.list_jobs() == []


def test_klein_edit_readiness_assesses_the_explicit_single_reference_request(tmp_path):
    image = _image(tmp_path, "k.png")
    controller, _service, _queue = _controller({"k.png": _baseline(KLEIN)})
    adapter = ReviewWorkflowAdapter()
    preview = controller.get_review_reprocess_effective_settings_preview(image_path=image, stages=["img2img"])
    assert not adapter.assess_readiness(preview, backend_id="forge_webui").ready
    assert adapter.assess_readiness(preview, single_reference_edit=True, backend_id="forge_webui").ready
    assert not adapter.assess_readiness(preview, single_reference_edit=True, backend_id="a1111_webui").ready


def test_klein_edit_readiness_assesses_the_klein_job_the_submission_would_carry(tmp_path):
    for model, expected_ready in ((ZIMAGE, True), (SDXL, True)):
        image = _image(tmp_path, "src.png")
        controller, _service, queue = _controller({"src.png": _baseline(model)})
        adapter = ReviewWorkflowAdapter()
        preview = controller.get_review_reprocess_effective_settings_preview(image_path=image, stages=["img2img"])
        assert adapter.assess_readiness(
            preview, single_reference_edit=True, backend_id="forge_webui"
        ).ready is expected_ready
        # Submission freezes the qualified Klein checkpoint over the artifact's own model, so readiness must too.
        marked = ReviewWorkflowAdapter.with_klein_edit_request(None, [Path(image)])
        assert controller.on_reprocess_images_with_prompt_delta(
            image_paths=[image], stages=["img2img"], prompt_delta="red jacket",
            prompt_mode="replace", negative_prompt_mode="replace", source_metadata_by_image=marked,
        ) == 1
        assert queue.list_jobs()[0]._normalized_record.base_model == KLEIN
    # ... and the Klein envelope (here: the configured backend) is what the readiness enforces.
    assert not adapter.assess_readiness(preview, single_reference_edit=True, backend_id="a1111_webui").ready


def test_admission_adds_no_second_queue_runner_or_fallback_route():
    source = inspect.getsource(admission_module)
    assert source.count("submit_njrs(") == 1
    for token in ("Runner", "run_njr", "JobQueue", "Backend", "a1111", "forge", "downgrade", "replace("):
        assert token not in source, token
