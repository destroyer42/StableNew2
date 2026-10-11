"""PR-IMG-MODELS-158: the shared, read-only operation assessment projects exact-profile policy and nothing else."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from PIL import Image

import src.image_backends.operation_compatibility as module
from src.image_backends.forge_klein_profile import KLEIN_EDIT_METADATA_KEY
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as ZP
from src.image_backends.forge_zimage_profile import ZImageProfileError
from src.image_backends.model_policy import resolve_model_policy
from src.image_backends.operation_compatibility import (
    BACKEND_MISMATCH,
    GEOMETRY_UNSUPPORTED,
    MODE_NOT_REQUESTED,
    SOURCE_IMAGE_COUNT,
    STAGE_CHAIN_UNSUPPORTED,
    STAGE_UNSUPPORTED,
    OperationNotSupportedError,
    OperationRequest,
    assess_njr,
    assess_operation,
    explicit_single_reference_edit,
    require_njr_operation,
)
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem

KLEIN = "flux-2-klein-4b-fp8.safetensors"
ZIMAGE = ZP.transformer.filename


def sdxl_policy():
    from types import SimpleNamespace

    compat = SimpleNamespace(
        status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sdxl")
    )
    return resolve_model_policy("ordinary.safetensors", family_lookup=lambda name: compat)


def request(*stages, **kw):
    return OperationRequest(stages=tuple(stages), backend_id=kw.pop("backend_id", "forge_webui"), **kw)


def test_zimage_admits_only_forge_txt2img_at_its_qualified_geometry():
    policy = resolve_model_policy(ZIMAGE)
    assert assess_operation(policy, request("txt2img", width=1024, height=1024)).ready
    wrong = assess_operation(policy, request("txt2img", width=576, height=1024))
    assert wrong.codes() == (GEOMETRY_UNSUPPORTED,) and "1024x1024" in wrong.explain()
    assert assess_operation(policy, request("txt2img", backend_id="a1111_webui")).codes() == (BACKEND_MISMATCH,)
    for stage in ("img2img", "adetailer", "upscale"):
        assessment = assess_operation(policy, request(stage, input_image_count=1))
        assert assessment.codes() == (STAGE_UNSUPPORTED,)
        assert "Z-Image" in assessment.explain()
    assert assess_operation(policy, request("txt2img", "img2img")).codes() == (STAGE_UNSUPPORTED,)


def test_zimage_never_treats_img2img_as_an_edit_even_when_requested():
    assessment = assess_operation(
        resolve_model_policy(ZIMAGE), request("img2img", single_reference_edit=True, input_image_count=1)
    )
    assert STAGE_UNSUPPORTED in assessment.codes()


def test_klein_edit_is_explicit_and_single_reference():
    policy = resolve_model_policy(KLEIN)
    assert assess_operation(policy, request("txt2img", width=768, height=1024)).ready
    assert assess_operation(
        policy, request("img2img", single_reference_edit=True, input_image_count=1)
    ).ready
    assert assess_operation(policy, request("img2img", input_image_count=1)).codes() == (MODE_NOT_REQUESTED,)
    assert assess_operation(
        policy, request("img2img", single_reference_edit=True, input_image_count=2)
    ).codes() == (SOURCE_IMAGE_COUNT,)
    assert not assess_operation(policy, request("adetailer", input_image_count=1)).ready
    assert assess_operation(policy, request("txt2img", "img2img")).codes() == (STAGE_CHAIN_UNSUPPORTED,)
    assert STAGE_UNSUPPORTED in assess_operation(policy, request("img2img", "upscale")).codes()


@pytest.mark.parametrize("stages", [("img2img",), ("adetailer",), ("upscale",), ("img2img", "adetailer", "upscale")])
def test_ordinary_models_are_never_narrowed(stages):
    for policy in (sdxl_policy(), resolve_model_policy("unknown.safetensors"), resolve_model_policy(None)):
        assert assess_operation(policy, request(*stages, backend_id="a1111_webui", input_image_count=5)).ready


def test_assessment_is_pure_and_owns_no_model_table():
    source = inspect.getsource(module)
    for token in ("1024", "768", "Euler", "z_image", "zimage", "flux-2", "open(", "requests", "tkinter"):
        assert token not in source, token


def test_explicit_edit_flag_comes_only_from_frozen_review_metadata():
    frozen = {"reprocess": {"source_items": [{"metadata": {KLEIN_EDIT_METADATA_KEY: {"mode": "single_reference_edit"}}}]}}
    assert explicit_single_reference_edit(frozen)
    for metadata in (
        None,
        {},
        {"reprocess": {"source_items": [{"metadata": {KLEIN_EDIT_METADATA_KEY: True}}]}},  # a request, not frozen evidence
        {"reprocess": {"source_items": [{"metadata": {}}]}},
        {"reprocess": {"source_items": [frozen["reprocess"]["source_items"][0], {"metadata": {}}]}},
    ):
        assert not explicit_single_reference_edit(metadata)


def _png(tmp_path: Path, size=(1024, 1024)) -> Path:
    path = tmp_path / "source.png"
    Image.new("RGB", size, (10, 20, 30)).save(path)
    return path


def _njr(tmp_path, model, stages, *, metadata=None):
    item = ReprocessSourceItem(
        input_image_path=str(_png(tmp_path)), prompt="a teapot", model=model, metadata=metadata or {}
    )
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[item], stages=list(stages), fallback_config={}, batch_size=1, output_dir=str(tmp_path / "out")
    )
    return plan.jobs[0]


@pytest.mark.parametrize("stage", ["img2img", "adetailer", "upscale"])
def test_assessment_and_backend_agree_for_a_zimage_reprocess_njr(tmp_path, stage):
    njr = _njr(tmp_path, ZIMAGE, [stage])
    assert not assess_njr(njr).ready
    with pytest.raises(OperationNotSupportedError):
        require_njr_operation(njr)
    with pytest.raises(ZImageProfileError):  # the backend still refuses independently (final authority)
        ForgeWebUIImageBackend().validate_njr_intent(njr, [stage])


def test_assessment_accepts_the_ordinary_and_explicit_klein_njrs(tmp_path):
    assert assess_njr(_njr(tmp_path, "ordinary.safetensors", ["img2img", "adetailer", "upscale"])).ready
    edit = _njr(tmp_path, KLEIN, ["img2img"], metadata={KLEIN_EDIT_METADATA_KEY: True})
    assert assess_njr(edit).ready
    free_form = _njr(tmp_path, KLEIN, ["img2img"])
    assert assess_njr(free_form).codes() == (MODE_NOT_REQUESTED,)
