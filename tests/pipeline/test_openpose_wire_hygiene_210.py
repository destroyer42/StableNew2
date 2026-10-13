"""PR-IMG-CNET-210: failure records, logs and manifests never carry conditioning image bytes."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import pytest

from src.utils.api_failure_store_v2 import ApiFailureStore


def test_failure_records_keep_the_request_shape_without_nested_image_bytes() -> None:
    image = base64.b64encode(b"\x89PNG" + b"x" * 4000).decode("ascii")
    payload = {
        "prompt": "p",
        "alwayson_scripts": {
            "ControlNet": {"args": [{"enabled": True, "module": "None", "model": "m", "image": image, "weight": 1.0}]},
            "ADetailer": {"args": [True, {"ad_model": "face_yolov8n.pt"}]},
        },
    }
    store = ApiFailureStore()

    store.record(
        stage="txt2img", endpoint="/sdapi/v1/txt2img", method="POST", payload=payload,
        status_code=500, response_text=None, error_message="boom",
    )

    kept = store.get_recent(1)[0].payload
    unit = kept["alwayson_scripts"]["ControlNet"]["args"][0]
    assert unit["image"].startswith("<") and image[:32] not in json.dumps(kept)
    assert (unit["model"], unit["weight"], unit["module"]) == ("m", 1.0, "None")
    assert kept["alwayson_scripts"]["ADetailer"] == payload["alwayson_scripts"]["ADetailer"]
    assert payload["alwayson_scripts"]["ControlNet"]["args"][0]["image"] == image  # the caller's request is untouched


def test_the_executor_never_logs_the_image(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from unittest.mock import patch

    from src.api.client import SDWebUIClient
    from src.conditioning.openpose import OpenPoseSelection
    from src.conditioning.openpose_snapshot import freeze_selection
    from src.image_backends.forge_controlnet import RUNTIME_KEY
    from src.pipeline.executor import Pipeline
    from src.utils import StructuredLogger
    from tests.conditioning.openpose_fixtures_210 import make_library, png_bytes

    data = png_bytes(128, 192)
    library = make_library(tmp_path / "webui", {"Standing/relaxed.png": data})
    frozen = freeze_selection(
        OpenPoseSelection(asset="Standing/relaxed.png", model="m"), library=library, snapshot_root=tmp_path / "snap"
    )
    pipeline = Pipeline(SDWebUIClient(base_url="http://127.0.0.1:7860"), StructuredLogger())
    pipeline.client.get_current_model = lambda: "mock-model"  # type: ignore[method-assign]
    pipeline.client.get_current_vae = lambda: "Automatic"  # type: ignore[method-assign]
    sent: list[dict] = []

    def fake_generate(self, stage, payload):
        sent.append(payload)
        return {"images": ["aGVsbG8="], "info": "{}"}

    healthy = {"schema": "stablenew.runtime-admission.v1", "status": "healthy", "reasons": [], "cause_codes": []}
    config = {
        "txt2img": {"steps": 20, "cfg_scale": 7.0, "width": 512, "height": 512},
        "controlnet_openpose": frozen.to_config(),
        RUNTIME_KEY: {"model": "m [abcd1234]"},
    }
    caplog.set_level(logging.DEBUG)
    with (
        patch("src.pipeline.executor.save_image_from_base64", side_effect=lambda _i, p, metadata_builder=None: p),
        patch.object(Pipeline, "_generate_images", fake_generate),
        patch.object(Pipeline, "_ensure_webui_true_ready"),
        patch.object(Pipeline, "_ensure_runtime_admissible", return_value=healthy),
        patch.object(Pipeline, "_apply_webui_defaults_once"),
    ):
        result = pipeline.run_txt2img_stage(
            prompt="p", negative_prompt="n", config=config, output_dir=tmp_path / "out", image_name="img"
        )

    encoded = base64.b64encode(data).decode("ascii")
    assert len(sent) == 1
    unit = sent[0]["alwayson_scripts"]["ControlNet"]["args"][0]
    assert unit["image"] == encoded and unit["model"] == "m [abcd1234]"
    assert encoded[:48] not in caplog.text  # neither the debug payload dump nor any other log line
    assert result is not None
    assert encoded[:48] not in json.dumps(result, default=str)  # manifest/metadata carry evidence, not bytes
    assert result["controlnet_openpose"]["units"] == 1


def _run_conditioned_stage(tmp_path: Path, images: list[str], *, batch: int = 1, n_iter: int = 1):
    """Drive the real ``Pipeline.run_txt2img_stage`` with a conditioned config; returns (result, saved image paths)."""

    from unittest.mock import patch

    from src.api.client import SDWebUIClient
    from src.conditioning.openpose import OpenPoseSelection
    from src.conditioning.openpose_snapshot import freeze_selection
    from src.image_backends.forge_controlnet import RUNTIME_KEY
    from src.pipeline.executor import Pipeline
    from src.utils import StructuredLogger
    from tests.conditioning.openpose_fixtures_210 import make_library, png_bytes

    library = make_library(tmp_path / "webui", {"Standing/relaxed.png": png_bytes(128, 192)})
    frozen = freeze_selection(
        OpenPoseSelection(asset="Standing/relaxed.png", model="m"), library=library, snapshot_root=tmp_path / "snap"
    )
    pipeline = Pipeline(SDWebUIClient(base_url="http://127.0.0.1:7860"), StructuredLogger())
    pipeline.client.get_current_model = lambda: "mock-model"  # type: ignore[method-assign]
    pipeline.client.get_current_vae = lambda: "Automatic"  # type: ignore[method-assign]
    saved: list[Path] = []
    healthy = {"schema": "stablenew.runtime-admission.v1", "status": "healthy", "reasons": [], "cause_codes": []}
    config = {
        "txt2img": {"steps": 20, "cfg_scale": 7.0, "width": 512, "height": 512, "batch_size": batch, "n_iter": n_iter},
        "batch_size": batch,
        "controlnet_openpose": frozen.to_config(),
        RUNTIME_KEY: {"model": "m [abcd1234]"},
    }

    def fake_save(_image, image_path, metadata_builder=None):
        saved.append(image_path)
        return image_path

    with (
        patch("src.pipeline.executor.save_image_from_base64", side_effect=fake_save),
        patch.object(Pipeline, "_generate_images", lambda self, stage, payload: {"images": list(images), "info": "{}"}),
        patch.object(Pipeline, "_ensure_webui_true_ready"),
        patch.object(Pipeline, "_ensure_runtime_admissible", return_value=healthy),
        patch.object(Pipeline, "_apply_webui_defaults_once"),
    ):
        result = pipeline.run_txt2img_stage(
            prompt="p", negative_prompt="n", config=config, output_dir=tmp_path / "out", image_name="img"
        )
    return result, saved


def test_the_appended_control_map_is_not_saved_as_a_result(tmp_path: Path) -> None:
    result, saved = _run_conditioned_stage(tmp_path, ["R0=", "TUFQ"])  # generated image, then the detect map

    assert result is not None
    assert [path.name for path in saved] == ["img.png"]  # one artifact, no `_batch1` pose map
    assert result["controlnet_openpose"]["control_images_discarded"] == 1
    assert result["controlnet_openpose"]["units"] == 1


def test_a_response_with_exactly_the_requested_images_is_untouched(tmp_path: Path) -> None:
    result, saved = _run_conditioned_stage(tmp_path, ["R0="])

    assert result is not None and len(saved) == 1
    assert "control_images_discarded" not in result["controlnet_openpose"]


def test_batched_results_are_kept_and_only_the_trailing_maps_are_dropped(tmp_path: Path) -> None:
    result, saved = _run_conditioned_stage(tmp_path, ["R0=", "R1=", "TUFQ"], n_iter=2)

    assert result is not None
    assert [path.name for path in saved] == ["img_batch0.png", "img_batch1.png"]
    assert result["controlnet_openpose"]["control_images_discarded"] == 1


def _png_b64(width: int, height: int) -> str:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _record(payload: dict):
    store = ApiFailureStore()
    store.record(
        stage="txt2img", endpoint="/sdapi/v1/txt2img", method="POST", payload=payload,
        status_code=500, response_text=None, error_message="boom",
    )
    return store.get_recent(1)[0]


def _unit(**fields) -> dict:
    return {"enabled": True, "module": "None", "model": "thibaud_xl_openpose", "weight": 1.0, **fields}


def test_a_small_valid_png_unit_image_is_redacted_whatever_its_length() -> None:
    small = _png_b64(1, 1)
    assert 0 < len(small) < 256  # the length-gated redaction used to leave exactly this one in the record

    kept = _record({"alwayson_scripts": {"ControlNet": {"args": [_unit(image=small)]}}}).payload
    unit = kept["alwayson_scripts"]["ControlNet"]["args"][0]

    assert unit["image"] == f"<{len(small)} base64 characters omitted>"
    assert small not in json.dumps(kept)


def test_a_larger_unit_image_is_redacted_too() -> None:
    large = _png_b64(256, 256)
    assert len(large) > 256

    kept = _record({"alwayson_scripts": {"ControlNet": {"args": [_unit(image=large)]}}}).payload

    assert kept["alwayson_scripts"]["ControlNet"]["args"][0]["image"] == f"<{len(large)} base64 characters omitted>"
    assert large[:48] not in json.dumps(kept)


def test_every_unit_image_field_and_the_dict_form_are_redacted() -> None:
    tiny = _png_b64(1, 1)
    unit = _unit(
        image={"image": tiny, "mask": tiny, "note": "keep"}, mask_image=tiny, image_fg=tiny, mask_image_fg=tiny
    )

    kept = _record({"alwayson_scripts": {"ControlNet": {"args": [unit]}}}).payload
    redacted = kept["alwayson_scripts"]["ControlNet"]["args"][0]

    assert tiny not in json.dumps(kept)
    assert redacted["mask_image"] == redacted["image_fg"] == redacted["mask_image_fg"] == f"<{len(tiny)} base64 characters omitted>"
    assert redacted["image"] == {
        "image": f"<{len(tiny)} base64 characters omitted>",
        "mask": f"<{len(tiny)} base64 characters omitted>",
        "note": "keep",
    }


def test_other_script_fields_and_scripts_are_preserved_and_the_callers_payload_is_untouched() -> None:
    tiny = _png_b64(1, 1)
    adetailer = {"args": [True, {"ad_model": "face_yolov8n.pt", "ad_confidence": 0.3}]}
    payload = {
        "prompt": "p",
        "steps": 20,
        "alwayson_scripts": {
            "ControlNet": {"args": [_unit(image=tiny, guidance_end=0.8), _unit(image="")], "extra": 1},
            "ADetailer": adetailer,
        },
    }
    snapshot = json.dumps(payload, sort_keys=True)

    kept = _record(payload).payload

    scripts = kept["alwayson_scripts"]
    assert scripts["ADetailer"] == adetailer
    assert scripts["ControlNet"]["extra"] == 1
    first, second = scripts["ControlNet"]["args"]
    assert (first["model"], first["weight"], first["guidance_end"], first["module"]) == ("thibaud_xl_openpose", 1.0, 0.8, "None")
    assert second["image"] == ""  # an empty value is not data and is left alone
    assert (kept["prompt"], kept["steps"]) == ("p", 20)
    assert json.dumps(payload, sort_keys=True) == snapshot


def test_payloads_without_scripts_and_the_top_level_image_preview_behave_as_before() -> None:
    tiny = _png_b64(1, 1)

    plain = _record({"prompt": "p", "init_images": [tiny]})
    scripted_without_args = _record({"prompt": "p", "alwayson_scripts": {"Other": "not-a-dict"}})

    assert plain.payload == {"prompt": "p", "init_images": [tiny]}  # top-level images are an existing, separate path
    assert plain.image_base64 == tiny
    assert scripted_without_args.payload == {"prompt": "p", "alwayson_scripts": {"Other": "not-a-dict"}}
