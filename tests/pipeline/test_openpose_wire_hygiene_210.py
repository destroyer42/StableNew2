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
