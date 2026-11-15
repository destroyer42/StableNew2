"""PR-IMG-ADETAILER-LOCAL-240B: localized-only ADetailer refinement and original-pixel preservation.

Synthetic pixels, a fake companion response and mocked transport only: nothing here contacts a runtime, a detector or a
GPU. The fake backend deliberately misbehaves (it repaints the whole image) so preservation is proven by StableNew's own
composite, never assumed from the backend.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
import requests
from PIL import Image, ImageChops, ImageDraw

from src.api.client import LOCALIZED_ADETAILER_SCHEMA, SDWebUIClient
from src.image_backends.a1111_webui_backend import A1111WebUIImageBackend
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.pipeline import adetailer_localized as localized
from src.pipeline.adetailer_localized import (
    EXECUTION_MODE_KEY,
    LEGACY_WHOLE_IMAGE,
    LOCALIZED_ONLY,
    SCHEMA,
    LocalizedRefinementError,
    blend_margin,
    build_request,
    encode_png,
    execution_mode,
    localized_refusals,
    pixel_sha256,
    stage_refusals,
    stamp_fresh_execution_mode,
    verify_and_composite,
    verify_published,
)
from src.pipeline.executor import Pipeline, PipelineStageError
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.njr_compiler import _with_fresh_adetailer_mode
from src.pipeline.njr_core_v26 import StageConfig, thaw_json
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from tests.helpers.njr_factory import make_pipeline_njr

SIZE = (96, 72)
FACE = ("face", {"ad_model": "face_yolov8n.pt", "ad_mask_blur": 0, "ad_mask_merge_invert": "None"})
HANDS = (
    "hands",
    {"ad_model": "hand_yolov8n.pt", "ad_mask_blur": 0, "ad_mask_merge_invert": "None"},
)


def source_image() -> Image.Image:
    """A non-uniform image, so a pixel copied from the wrong place would be noticed."""

    image = Image.new("RGB", SIZE)
    image.putdata(
        [
            ((x * 7) % 256, (y * 11) % 256, (x + y) % 256)
            for y in range(SIZE[1])
            for x in range(SIZE[0])
        ]
    )
    return image


def mask(
    *boxes: tuple[int, int, int, int], size: tuple[int, int] = SIZE, mode: str = "L"
) -> Image.Image:
    image = Image.new("L", size, 0)
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(box, fill=255)
    return image.convert(mode)


def repainted(original: Image.Image) -> Image.Image:
    """What a backend that ignored its masks would return: every pixel differs from the source."""

    return ImageChops.invert(original)


def respond(
    original: Image.Image,
    masks: dict[str, list[Image.Image]],
    *,
    passes: tuple = (FACE, HANDS),
    generated: Image.Image | None = None,
    sampled: bool | None = None,
) -> dict[str, Any]:
    total = sum(len(masks.get(label, [])) for label, _ in passes)
    did_sample = total > 0 if sampled is None else sampled
    return {
        "schema": SCHEMA,
        "companion_version": "1.0.0",
        "adetailer_version": "26.2.0",
        "source": {
            "width": original.width,
            "height": original.height,
            "sha256": pixel_sha256(original),
        },
        "sampled": did_sample,
        "image": encode_png(generated or repainted(original)) if did_sample else None,
        "passes": [
            {
                "label": label,
                "model": args["ad_model"],
                "mask_count": len(masks.get(label, [])),
                "masks": [encode_png(item) for item in masks.get(label, [])],
            }
            for label, args in passes
        ],
    }


def outside_is_untouched(
    original: Image.Image, final: Image.Image, authorized: Image.Image
) -> bool:
    outside = ImageChops.invert(authorized)
    return all(
        ImageChops.multiply(channel, outside).getbbox() is None
        for channel in ImageChops.difference(final.convert("RGB"), original).split()
    )


# ------------------------------------------------------------------------------------------------ mode and refusals


def test_an_absent_mode_is_legacy_and_only_new_sections_are_stamped_localized():
    assert (
        execution_mode({}) == execution_mode(None) == LEGACY_WHOLE_IMAGE
    )  # a job compiled before the mode existed
    assert execution_mode({EXECUTION_MODE_KEY: LOCALIZED_ONLY}) == LOCALIZED_ONLY
    assert stamp_fresh_execution_mode({"adetailer_steps": 12})[EXECUTION_MODE_KEY] == LOCALIZED_ONLY
    explicit = {EXECUTION_MODE_KEY: LEGACY_WHOLE_IMAGE}
    assert stamp_fresh_execution_mode(explicit) == explicit  # an explicit mode is never rewritten
    with pytest.raises(LocalizedRefinementError, match="unknown"):
        execution_mode({EXECUTION_MODE_KEY: "whole_image_fast"})


def test_background_targeting_inversion_is_refused_per_enabled_pass():
    inverted = {"ad_mask_merge_invert": "Merge and Invert"}
    assert localized_refusals([FACE, HANDS]) == ()
    assert localized_refusals([("face", {"ad_mask_merge_invert": "Merge"})]) == ()
    [reason] = localized_refusals([FACE, ("hands", inverted)])
    assert "hands pass" in reason and "background" in reason
    assert len(stage_refusals({"ad_mask_merge_invert": "Merge and Invert"})) == 1
    assert (
        stage_refusals({"enable_face_pass": False, "ad_mask_merge_invert": "Merge and Invert"})
        == ()
    )
    assert (
        stage_refusals({"ad_hands_mask_merge_invert": "Merge and Invert"}) == ()
    )  # hand pass not enabled
    assert (
        len(
            stage_refusals(
                {"enable_hands_pass": True, "ad_hands_mask_merge_invert": "Merge and Invert"}
            )
        )
        == 1
    )


def test_the_blend_margin_is_the_half_width_of_forges_mask_blur_kernel():
    assert [blend_margin(blur) for blur in (0, 1, 2, 4, 6)] == [0, 3, 5, 10, 15]
    for bad in ("soft", None, -1):
        with pytest.raises(LocalizedRefinementError):
            blend_margin(bad)


# ------------------------------------------------------------------------------------------------ preservation


@pytest.mark.parametrize(
    ("passes", "masks"),
    [
        ((FACE,), {"face": [mask((10, 10, 30, 30))]}),
        ((HANDS,), {"hands": [mask((50, 40, 60, 55)), mask((70, 5, 80, 15))]}),
        ((FACE, HANDS), {"face": [mask((10, 10, 30, 30))], "hands": [mask((50, 40, 60, 55))]}),
    ],
    ids=["face-only", "hands-only", "combined"],
)
def test_only_the_effective_masks_change_and_everything_else_equals_the_source_exactly(
    passes, masks
):
    original = source_image()
    outcome = verify_and_composite(
        original=original, response=respond(original, masks, passes=passes), passes=passes
    )

    union = Image.new("L", SIZE, 0)
    for items in masks.values():
        for item in items:
            union = ImageChops.lighter(union, item)
    assert outcome.image is not None
    assert outside_is_untouched(original, outcome.image, union)
    assert (
        ImageChops.difference(
            outcome.image, Image.composite(repainted(original), original, union)
        ).getbbox()
        is None
    )
    record = outcome.record
    assert record["execution_mode"] == LOCALIZED_ONLY and record["preservation"]["verified"] is True
    assert record["effective_mask_count"] == sum(len(v) for v in masks.values())
    assert record["authorized_region"]["pixels"] == union.histogram()[255]
    assert record["pixel_change"]["changed_pixels"] == union.histogram()[255]
    # The backend repainted the whole image; those pixels were restored and the count is kept as evidence.
    assert (
        record["preservation"]["backend_changed_pixels_outside_authorized"]
        == SIZE[0] * SIZE[1] - union.histogram()[255]
    )
    assert [p["label"] for p in record["passes"]] == [label for label, _ in passes]
    assert record["zero_mask_passthrough"] is False and record["refinement_sampled"] is True


def test_blur_extends_the_authorized_region_by_exactly_its_margin_and_overlaps_stay_bounded():
    original = source_image()
    blurred = ("face", {**FACE[1], "ad_mask_blur": 2})  # margin 5
    masks = {"face": [mask((30, 30, 40, 40)), mask((38, 30, 50, 40))]}  # overlapping regions
    outcome = verify_and_composite(
        original=original, response=respond(original, masks, passes=(blurred,)), passes=(blurred,)
    )

    assert outcome.image is not None
    expected = mask((25, 25, 55, 45))  # the union box grown by 5 on every side
    assert ImageChops.difference(outcome.authorized, expected).getbbox() is None
    for inside in ((25, 25), (55, 45), (40, 35)):
        assert outcome.image.getpixel(inside) != original.getpixel(inside)
    for outside in ((24, 25), (56, 45), (40, 46), (40, 24), (0, 0)):
        assert outcome.image.getpixel(outside) == original.getpixel(outside)
    assert outcome.record["passes"][0]["blend_margin_px"] == 5
    assert outcome.record["authorized_region"]["pixels"] == 31 * 21  # overlap counted once


def test_a_mask_at_the_image_edge_stays_inside_the_image():
    original = source_image()
    blurred = ("face", {**FACE[1], "ad_mask_blur": 4})
    outcome = verify_and_composite(
        original=original,
        response=respond(original, {"face": [mask((0, 0, 5, 5))]}, passes=(blurred,)),
        passes=(blurred,),
    )
    assert outcome.authorized.getbbox() == (0, 0, 16, 16)
    assert outcome.image.getpixel((16, 16)) == original.getpixel((16, 16))


def test_zero_eligible_masks_pass_the_source_through_without_sampling():
    original = source_image()
    outcome = verify_and_composite(
        original=original, response=respond(original, {}), passes=(FACE, HANDS)
    )

    assert outcome.image is None
    assert (
        outcome.record["zero_mask_passthrough"] is True
        and outcome.record["refinement_sampled"] is False
    )
    assert outcome.record["pixel_change"] == {
        "changed_pixels": 0,
        "output_identical_to_source": True,
    }
    assert outcome.record["authorized_region"]["pixels"] == 0


def _broken(mutate) -> dict[str, Any]:
    original = source_image()
    response = respond(
        original, {"face": [mask((10, 10, 30, 30))], "hands": [mask((50, 40, 60, 55))]}
    )
    mutate(response)
    return response


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.update(schema="stablenew.adetailer-localized.v0"), "schema"),
        (lambda r: r.pop("companion_version"), "companion"),
        (lambda r: r.pop("source"), "does not identify the image"),
        (lambda r: r["source"].update(sha256="0" * 64), "different pixels"),
        (lambda r: r["source"].update(width=SIZE[0] + 1), "not the"),
        (lambda r: r.update(passes=r["passes"][:1]), "exactly the requested passes"),
        (lambda r: r["passes"].reverse(), "out of order"),
        (lambda r: r["passes"][0].update(model="person_yolov8n-seg.pt"), "detector"),
        (lambda r: r["passes"][0].update(mask_count=2), "mask count"),
        (lambda r: r["passes"][0].update(masks=["not-base64!"]), "not a decodable image"),
        (
            lambda r: r["passes"][0].update(masks=[encode_png(mask((1, 1, 4, 4), size=(48, 36)))]),
            "not the source",
        ),
        (lambda r: r["passes"][0].update(masks=[encode_png(mask())]), "is empty"),
        (
            lambda r: r["passes"][0].update(masks=[encode_png(mask((1, 1, 4, 4)).convert("RGB"))]),
            "single-channel",
        ),
        (lambda r: r.update(sampled="yes"), "whether refinement sampling ran"),
        (lambda r: r.update(image=None), "refined image is missing"),
        (
            lambda r: r.update(image=encode_png(Image.new("RGB", (48, 36)))),
            "refined image is 48x36",
        ),
        (lambda r: r.update(sampled=False), "reports no sampling"),
    ],
)
def test_malformed_or_mismatched_evidence_is_refused(mutate, message):
    with pytest.raises(LocalizedRefinementError, match=message):
        verify_and_composite(
            original=source_image(), response=_broken(mutate), passes=(FACE, HANDS)
        )


def test_missing_evidence_unbounded_mask_counts_and_sampling_without_masks_are_refused():
    original = source_image()
    with pytest.raises(LocalizedRefinementError, match="no localized-refinement evidence"):
        verify_and_composite(original=original, response=None, passes=(FACE,))
    flood = respond(
        original, {"face": [mask((1, 1, 2, 2))] * (localized.MAX_MASKS + 1)}, passes=(FACE,)
    )
    with pytest.raises(LocalizedRefinementError, match="more than"):
        verify_and_composite(original=original, response=flood, passes=(FACE,))
    with pytest.raises(LocalizedRefinementError, match="without any effective mask"):
        verify_and_composite(
            original=original, response=respond(original, {}, sampled=True), passes=(FACE, HANDS)
        )


def test_the_written_file_must_be_the_verified_composite():
    original = source_image()
    outcome = verify_and_composite(
        original=original,
        response=respond(original, {"face": [mask((10, 10, 30, 30))]}, passes=(FACE,)),
        passes=(FACE,),
    )
    verify_published(original=original, published=outcome.image, outcome=outcome)
    tampered = outcome.image.copy()
    tampered.putpixel((0, 0), (1, 2, 3))
    with pytest.raises(LocalizedRefinementError, match="not the verified composite"):
        verify_published(original=original, published=tampered, outcome=outcome)
    with pytest.raises(LocalizedRefinementError, match="not the verified composite"):
        verify_published(original=original, published=repainted(original), outcome=outcome)


def test_the_request_carries_source_identity_passes_and_no_whole_image_generation_fields():
    original = source_image()
    request = build_request(
        original=original, passes=(FACE, HANDS), generation={"prompt": "p", "seed": 7}
    )

    assert request["schema"] == SCHEMA == LOCALIZED_ADETAILER_SCHEMA
    assert request["source"] == {
        "width": SIZE[0],
        "height": SIZE[1],
        "sha256": pixel_sha256(original),
    }
    assert (request["width"], request["height"]) == SIZE and request["seed"] == 7
    assert [entry["label"] for entry in request["passes"]] == ["face", "hands"]
    assert not {"init_images", "alwayson_scripts", "denoising_strength"} & set(request)


# ------------------------------------------------------------------------------------------------ executor


@pytest.fixture(autouse=True)
def _healthy(monkeypatch):
    monkeypatch.setattr(
        Pipeline,
        "_ensure_runtime_admissible",
        lambda *_a, **_k: {
            "schema": "stablenew.runtime-admission.v1",
            "status": "healthy",
            "reasons": [],
            "cause_codes": [],
        },
    )


def execute(tmp_path: Path, config: dict[str, Any], backend, *, tamper: bool = False):
    """Run the ADetailer stage against ``backend(payload) -> companion response`` (or an exception to raise)."""

    client = Mock()
    client.get_current_model.return_value = "model"
    client.get_current_vae.return_value = "Automatic"
    pipeline = Pipeline(client, Mock())
    source = tmp_path / "in.png"
    source_image().save(source)
    sent: list[dict[str, Any]] = []

    def generate(stage, payload, **_kwargs):
        sent.append({"stage": stage, "payload": payload})
        data = backend(payload)
        if payload.get("schema") != SCHEMA:
            return data
        image = data.pop("image", None)
        return {"images": [image] if image else [], "info": {"stablenew_localized": data}}

    real_save = __import__(
        "src.utils.file_io", fromlist=["save_image_from_base64"]
    ).save_image_from_base64

    def save(b64, path, metadata_builder=None):
        saved = real_save(b64, path, metadata_builder=metadata_builder)
        if tamper and saved:
            with Image.open(saved) as written:
                changed = written.convert("RGB")
            changed.putpixel((0, 0), (255, 0, 255))
            changed.save(saved)
        return saved

    with (
        patch.object(pipeline, "_generate_images_with_progress", side_effect=generate),
        patch("src.pipeline.executor.save_image_from_base64", side_effect=save) as saver,
    ):
        try:
            result = pipeline.run_adetailer(
                source,
                "prompt",
                "negative",
                {"adetailer_enabled": True, "seed": 7, **config},
                tmp_path / "out",
                "case",
            )
            error = None
        except PipelineStageError as exc:
            result, error = None, exc
    return result, error, sent, saver, source


def companion(masks_for) -> Any:
    def backend(payload):
        original = source_image()
        labels = [entry["label"] for entry in payload["passes"]]
        passes = tuple((entry["label"], entry["args"]) for entry in payload["passes"])
        return respond(original, {label: masks_for(label) for label in labels}, passes=passes)

    return backend


LOCALIZED = {EXECUTION_MODE_KEY: LOCALIZED_ONLY, "ad_mask_blur": 0, "ad_hands_mask_blur": 0}
REGIONS = {"face": [mask((10, 10, 30, 30))], "hands": [mask((50, 40, 60, 55))]}


def test_a_localized_stage_sends_one_companion_request_and_publishes_only_the_verified_composite(
    tmp_path,
):
    result, error, sent, saver, source = execute(
        tmp_path, {**LOCALIZED, "enable_hands_pass": True}, companion(lambda label: REGIONS[label])
    )

    assert error is None and len(sent) == 1 and saver.call_count == 1  # one dispatch, one artifact
    payload = sent[0]["payload"]
    assert sent[0]["stage"] == "adetailer" and payload["schema"] == SCHEMA
    assert not {"init_images", "alwayson_scripts", "denoising_strength"} & set(
        payload
    )  # no whole-image img2img
    assert [entry["label"] for entry in payload["passes"]] == ["face", "hands"]
    with Image.open(result["path"]) as written:
        final = written.convert("RGB")
    union = ImageChops.lighter(REGIONS["face"][0], REGIONS["hands"][0])
    assert outside_is_untouched(source_image(), final, union)
    assert final.getpixel((20, 20)) != source_image().getpixel((20, 20))
    assert result[EXECUTION_MODE_KEY] == LOCALIZED_ONLY
    evidence = result["adetailer_localized"]
    assert evidence["preservation"]["verified"] is True and evidence["effective_mask_count"] == 2
    assert evidence["backend"]["companion_version"] == "1.0.0"
    assert evidence["output_pixel_sha256"] == pixel_sha256(final)
    assert (
        "image" not in result["config"] and result["config"]["schema"] == SCHEMA
    )  # the request, without pixels
    with Image.open(source) as untouched:
        assert pixel_sha256(untouched) == pixel_sha256(source_image())


@pytest.mark.parametrize("face_limit", [1, 0], ids=["single", "multiple"])
@pytest.mark.parametrize("hands", [True, False])
def test_face_retention_and_hand_selection_reach_the_request_independently(
    tmp_path, face_limit, hands
):
    _result, error, sent, _saver, _source = execute(
        tmp_path,
        {
            **LOCALIZED,
            "ad_mask_k_largest": face_limit,
            "enable_hands_pass": hands,
            "ad_hands_mask_k": 6,
        },
        companion(lambda label: REGIONS[label]),
    )

    assert error is None
    passes = {entry["label"]: entry["args"] for entry in sent[0]["payload"]["passes"]}
    assert passes["face"]["ad_mask_k"] == face_limit
    assert ("hands" in passes) is hands
    if hands:
        assert passes["hands"]["ad_mask_k"] == 6  # the hand limit does not follow the face mode


def test_zero_eligible_masks_return_the_input_itself_and_write_nothing(tmp_path):
    result, error, sent, saver, source = execute(tmp_path, LOCALIZED, companion(lambda _label: []))

    assert error is None and len(sent) == 1 and saver.call_count == 0
    assert result["skipped"] is True and Path(result["path"]) == source
    assert result["adetailer_localized"]["zero_mask_passthrough"] is True
    assert result["adetailer_localized"]["refinement_sampled"] is False
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").rglob("*.png"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["source"].update(sha256="0" * 64),
        lambda r: r["passes"][0].update(masks=[encode_png(mask((1, 1, 4, 4), size=(48, 36)))]),
        lambda r: r.pop("passes"),
        lambda r: r.clear(),
    ],
    ids=["other-pixels", "mask-size", "no-passes", "empty"],
)
def test_unverifiable_evidence_fails_the_stage_and_publishes_no_artifact(tmp_path, mutate):
    def backend(payload):
        response = companion(lambda label: REGIONS[label])(payload)
        mutate(response)
        return response

    result, error, _sent, saver, _source = execute(tmp_path, LOCALIZED, backend)

    assert result is None and "could not be verified" in str(error) and saver.call_count == 0
    assert not list(tmp_path.rglob("out/**/*.png"))


def test_a_written_file_that_differs_from_the_composite_is_removed_and_the_stage_fails(tmp_path):
    result, error, _sent, saver, _source = execute(
        tmp_path, LOCALIZED, companion(lambda label: REGIONS[label]), tamper=True
    )

    assert (
        result is None
        and "failed preservation verification" in str(error)
        and saver.call_count == 1
    )
    assert not list((tmp_path / "out").rglob("*.png"))


def test_inversion_and_unknown_modes_are_refused_before_any_dispatch(tmp_path):
    for config in (
        {**LOCALIZED, "ad_mask_merge_invert": "Merge and Invert"},
        {**LOCALIZED, "enable_hands_pass": True, "ad_hands_mask_merge_invert": "Merge and Invert"},
        {EXECUTION_MODE_KEY: "something_else"},
    ):
        result, error, sent, saver, _source = execute(
            tmp_path, config, companion(lambda label: REGIONS[label])
        )
        assert result is None and error is not None and sent == [] and saver.call_count == 0


def test_a_configuration_without_the_mode_keeps_the_recorded_whole_image_request(tmp_path):
    result, error, sent, _saver, _source = execute(
        tmp_path,
        {},
        lambda _payload: {"images": [encode_png(repainted(source_image()))], "info": "{}"},
    )

    assert error is None and len(sent) == 1
    payload = sent[0]["payload"]
    assert (
        "schema" not in payload
        and "init_images" in payload
        and "ADetailer" in payload["alwayson_scripts"]
    )
    assert result[EXECUTION_MODE_KEY] == LEGACY_WHOLE_IMAGE and "adetailer_localized" not in result


def test_a_backend_failure_is_never_followed_by_a_whole_image_request(tmp_path):
    def backend(_payload):
        raise PipelineStageError(Mock(stage="adetailer", message="HTTP 404", code="unknown_error"))

    result, error, sent, saver, _source = execute(tmp_path, LOCALIZED, backend)

    assert result is None and error is not None and len(sent) == 1 and saver.call_count == 0


# ------------------------------------------------------------------------------------------------ client transport


class _Response:
    def __init__(self, data: Any) -> None:
        self._data = data

    def json(self) -> Any:
        return self._data


def test_the_client_posts_the_localized_operation_once_and_never_uses_img2img(monkeypatch):
    client = SDWebUIClient()
    calls: list[tuple[str, str, Any]] = []

    @contextmanager
    def request_context(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs.get("policy")))
        yield _Response({"schema": SCHEMA, "image": "PNG", "seed": 11, "passes": []})

    monkeypatch.setattr(client, "_request_context", request_context)
    monkeypatch.setattr(
        client, "img2img", Mock(side_effect=AssertionError("whole-image img2img must not be used"))
    )
    outcome = client.generate_images(stage="adetailer", payload={"schema": SCHEMA})

    assert outcome.ok and [(m, e) for m, e, _ in calls] == [
        ("post", "/stablenew/v1/adetailer/localized")
    ]
    assert calls[0][2].max_attempts == 1  # the fail-fast ADetailer policy
    assert outcome.result.images == ["PNG"] and outcome.result.info["seed"] == 11
    assert "image" not in outcome.result.info["stablenew_localized"]


def test_a_runtime_without_the_companion_is_an_error_outcome_not_a_fallback(monkeypatch):
    client = SDWebUIClient()

    @contextmanager
    def request_context(method, endpoint, **_kwargs):
        raise requests.HTTPError("404 Client Error: Not Found for url: " + endpoint)
        yield  # pragma: no cover

    monkeypatch.setattr(client, "_request_context", request_context)
    monkeypatch.setattr(client, "img2img", Mock(side_effect=AssertionError("no fallback")))
    outcome = client.generate_images(stage="adetailer", payload={"schema": SCHEMA})

    assert not outcome.ok and "404" in outcome.error.message


# ------------------------------------------------------------------------------------------------ backend capability


def _request(mode: str | None) -> Any:
    extra = {} if mode is None else {EXECUTION_MODE_KEY: mode}
    return Mock(
        stage_name="adetailer",
        stage_config={"extra": extra},
        backend_options=None,
        selected_model="",
        execution_config={},
    )


def test_only_the_forge_backend_declares_localized_refinement_and_others_refuse_it():
    assert ForgeWebUIImageBackend.capabilities.supports_localized_adetailer is True
    assert A1111WebUIImageBackend.capabilities.supports_localized_adetailer is False
    forge, a1111 = object.__new__(ForgeWebUIImageBackend), object.__new__(A1111WebUIImageBackend)

    forge._require_adetailer_mode_supported({"extra": {EXECUTION_MODE_KEY: LOCALIZED_ONLY}})
    a1111._require_adetailer_mode_supported(
        {"extra": {}}
    )  # a recorded legacy job still runs on the rollback backend
    a1111._require_adetailer_mode_supported({EXECUTION_MODE_KEY: LEGACY_WHOLE_IMAGE})
    with pytest.raises(ValueError, match="never falls back"):
        a1111._require_adetailer_mode_supported({"extra": {EXECUTION_MODE_KEY: LOCALIZED_ONLY}})
    with pytest.raises(ValueError, match="unknown"):
        forge._require_adetailer_mode_supported({EXECUTION_MODE_KEY: "fast"})


# ------------------------------------------------------------------------------------------------ compile and replay


def _stages(extra: dict[str, Any], *, enabled: bool = True) -> tuple[StageConfig, ...]:
    return (
        StageConfig("txt2img", enabled=True),
        StageConfig("adetailer", enabled=enabled, extra=extra),
    )


def test_newly_compiled_stages_state_localized_only_and_refuse_inversion_at_compile():
    txt2img, adetailer = _with_fresh_adetailer_mode(_stages({"adetailer_steps": 12}))
    assert EXECUTION_MODE_KEY not in thaw_json(txt2img.extra)
    assert thaw_json(adetailer.extra) == {"adetailer_steps": 12, EXECUTION_MODE_KEY: LOCALIZED_ONLY}
    [_, disabled] = _with_fresh_adetailer_mode(_stages({}, enabled=False))
    assert EXECUTION_MODE_KEY not in thaw_json(disabled.extra)
    [_, explicit] = _with_fresh_adetailer_mode(
        _stages(
            {EXECUTION_MODE_KEY: LEGACY_WHOLE_IMAGE, "ad_mask_merge_invert": "Merge and Invert"}
        )
    )
    assert (
        thaw_json(explicit.extra)[EXECUTION_MODE_KEY] == LEGACY_WHOLE_IMAGE
    )  # an explicit legacy stage is untouched
    with pytest.raises(ValueError, match="background"):
        _with_fresh_adetailer_mode(_stages({"ad_mask_merge_invert": "Merge and Invert"}))


@pytest.mark.parametrize("recorded", [None, LEGACY_WHOLE_IMAGE, LOCALIZED_ONLY])
def test_replay_and_serialization_keep_the_recorded_mode(recorded):
    extra = {"adetailer_steps": 12, **({} if recorded is None else {EXECUTION_MODE_KEY: recorded})}
    parent = replace(make_pipeline_njr(), stages=_stages(extra))

    replayed = compile_replay_intent(ReplayIntent(record=parent), id_fn=lambda: "replay-1")
    restored = NormalizedJobRecord.from_dict(json.loads(json.dumps(replayed.to_dict())))

    for record in (replayed, restored):
        stage = next(s for s in record.stage_chain if s.stage_type == "adetailer")
        assert thaw_json(stage.extra) == extra  # never migrated, in either direction
        assert execution_mode(thaw_json(stage.extra)) == (recorded or LEGACY_WHOLE_IMAGE)
    assert replayed.job_id == "replay-1" and replayed.source.parent_job_id == parent.job_id
