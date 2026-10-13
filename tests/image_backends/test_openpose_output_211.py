"""Generated-image boundaries, decoded pose identity and all-or-nothing refusal, without a backend."""

from __future__ import annotations

import base64
import copy
import io
import json

import pytest
from PIL import Image, PngImagePlugin

from src.image_backends.openpose_output import OpenPoseResponseError, classify_openpose_response
from tests.conditioning.openpose_fixtures_210 import png_bytes

POSE = png_bytes(128, 192, (10, 20, 30))
GENERATED = png_bytes(64, 96, (100, 110, 120))


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _response(count: int = 1, *, grid: bool = False, extra: bytes | None = None) -> dict:
    images = [_encoded(GENERATED)] * count
    if grid:
        images.insert(0, _encoded(png_bytes(128, 96, (50, 60, 70))))
    if extra is not None:
        images.append(_encoded(extra))
    return {
        "images": images,
        "info": json.dumps(
            {
                "index_of_first_image": int(grid),
                "all_seeds": list(range(count)),
                "infotexts": ["grid"] * int(grid) + [f"generation {i}" for i in range(count)],
            }
        ),
    }


@pytest.mark.parametrize("count", [1, 2, 4])
@pytest.mark.parametrize("grid", [False, True])
def test_metadata_selects_only_generations_and_preserves_the_original_response(count, grid) -> None:
    raw = _response(count, grid=grid)
    before = copy.deepcopy(raw)
    classified, facts = classify_openpose_response(raw, expected=count, input_bytes=POSE)
    assert raw == before
    assert classified["images"] == [_encoded(GENERATED)] * count
    assert classified["info"]["index_of_first_image"] == 0
    assert classified["info"]["infotexts"] == [f"generation {i}" for i in range(count)]
    assert facts["generated_images"] == count and facts["grids_discarded"] == int(grid)
    assert facts["control_images_discarded"] == 0


def test_a_reencoded_input_is_identified_by_pixels_not_encoded_bytes() -> None:
    with Image.open(io.BytesIO(POSE)) as image:
        buffer = io.BytesIO()
        info = PngImagePlugin.PngInfo()
        info.add_text("description", "a reencoded map")
        image.save(buffer, format="PNG", pnginfo=info)
    extra = buffer.getvalue()
    assert extra != POSE
    raw = _response(2, grid=True, extra=extra)
    classified, facts = classify_openpose_response(raw, expected=2, input_bytes=POSE)
    assert len(classified["images"]) == 2 and facts["control_images_discarded"] == 1


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "missing_generations"),
        ("partial", "missing_generations"),
        ("no_info", "ambiguous_metadata"),
        ("bad_info", "ambiguous_metadata"),
        ("no_boundary", "ambiguous_metadata"),
        ("bad_boundary", "ambiguous_metadata"),
        ("short_seeds", "generation_count"),
        ("short_texts", "generation_count"),
        ("empty_text", "generation_count"),
        ("unknown_extra", "unexpected_images"),
        ("pose_first", "pose_in_generation_slot"),
        ("only_pose", "pose_in_generation_slot"),
        ("corrupt", "invalid_image"),
        ("not_list", "missing_generations"),
        ("too_many", "unexpected_images"),
    ],
)
def test_unsubstantiated_outputs_are_refused_with_content_free_diagnostics(case, code) -> None:
    count = 2 if case == "partial" else 1
    response = _response(count)
    info = json.loads(response["info"])
    if case == "missing":
        response["images"] = []
    elif case == "partial":
        response["images"].pop()
    elif case == "no_info":
        info = None
    elif case == "bad_info":
        info = "{bad json"
    elif case == "no_boundary":
        info.pop("index_of_first_image")
    elif case == "bad_boundary":
        info["index_of_first_image"] = True
    elif case == "short_seeds":
        info["all_seeds"] = []
    elif case == "short_texts":
        info["infotexts"] = []
    elif case == "empty_text":
        info["infotexts"] = [""]
    elif case == "unknown_extra":
        response["images"].append(_encoded(GENERATED))
    elif case == "pose_first":
        response["images"] = [_encoded(POSE), _encoded(GENERATED)]
    elif case == "only_pose":
        response["images"] = [_encoded(POSE)]
    elif case == "corrupt":
        response["images"] = ["not base64"]
    elif case == "not_list":
        response["images"] = _encoded(GENERATED)
    elif case == "too_many":
        response["images"].extend([_encoded(POSE)] * 3)
    response["info"] = info
    with pytest.raises(OpenPoseResponseError) as caught:
        classify_openpose_response(response, expected=count, input_bytes=POSE)
    assert caught.value.code == code
    assert caught.value.diagnostics["expected_generations"] == count
    assert _encoded(POSE) not in str(caught.value) and "No response images were saved" in str(
        caught.value
    )


def test_forge_white_alpha_composite_is_a_pose_map_even_after_reencoding() -> None:
    image = Image.new("RGBA", (128, 192), (255, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    transparent_pose = buffer.getvalue()
    raw = _response(extra=png_bytes(128, 192, (255, 255, 255)))
    _, facts = classify_openpose_response(raw, expected=1, input_bytes=transparent_pose)
    assert facts["control_images_discarded"] == 1


@pytest.mark.parametrize("limit", ["MAX_RESULT_BYTES", "MAX_RESULT_PIXELS"])
def test_decode_limits_refuse_before_artifact_saving(monkeypatch, limit) -> None:
    monkeypatch.setattr(f"src.image_backends.openpose_output.{limit}", 10)
    response = _response()
    response["info"] = json.loads(response["info"])  # exercise the image limit independently of JSON byte limits
    with pytest.raises(OpenPoseResponseError) as caught:
        classify_openpose_response(response, expected=1, input_bytes=POSE)
    assert caught.value.code == "invalid_image"
