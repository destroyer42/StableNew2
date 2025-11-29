from copy import deepcopy
from pathlib import Path

import pytest

from src.pipeline.executor import Pipeline
from src.utils.config import ConfigManager
from src.utils.logger import StructuredLogger


class DummyClient:
    def __init__(self):
        self.payloads = []

    def txt2img(self, payload):
        self.payloads.append(payload)
        return {"images": ["base64"]}

    def img2img(self, payload):
        self.payloads.append(payload)
        return {"images": ["base64"]}

    def set_model(self, *_args, **_kwargs):
        return True

    def set_vae(self, *_args, **_kwargs):
        return True

    def set_hypernetwork(self, *_args, **_kwargs):
        return True


@pytest.fixture
def dummy_pipeline(tmp_path, monkeypatch):
    client = DummyClient()
    logger = StructuredLogger(output_dir=str(tmp_path))
    pipeline = Pipeline(client, logger)
    monkeypatch.setattr("src.utils.file_io.save_image_from_base64", lambda data, path: True)
    return pipeline, client


def build_base_config():
    config = deepcopy(ConfigManager().get_default_config())
    config["txt2img"]["prompt"] = "test"
    return config


def test_aesthetic_script_injection(dummy_pipeline, tmp_path):
    pipeline, client = dummy_pipeline
    config = build_base_config()
    config["aesthetic"] = {
        "enabled": True,
        "mode": "script",
        "weight": 0.8,
        "steps": 7,
        "learning_rate": 0.0002,
        "slerp": True,
        "slerp_angle": 0.2,
        "embedding": "MyEmbed",
        "text": "pleasant tone",
        "text_is_negative": False,
        "fallback_prompt": "",
    }

    pipeline.run_txt2img_stage("castle", "", config, Path(tmp_path), "img001")

    payload = client.payloads[0]
    assert "Aesthetic embeddings" in payload["alwayson_scripts"]
    args = payload["alwayson_scripts"]["Aesthetic embeddings"]["args"]
    assert args[0] == 0.8
    assert args[1] == 7
    assert args[4] == "MyEmbed"


def test_aesthetic_prompt_fallback(dummy_pipeline, tmp_path):
    pipeline, client = dummy_pipeline
    config = build_base_config()
    config["aesthetic"] = {
        "enabled": True,
        "mode": "prompt",
        "weight": 0.9,
        "steps": 5,
        "learning_rate": 0.0001,
        "slerp": False,
        "slerp_angle": 0.1,
        "embedding": "Cozy",
        "text": "dreamy tones",
        "text_is_negative": True,
        "fallback_prompt": "soft colors",
    }

    pipeline.run_txt2img_stage("forest", "harsh shadows", config, Path(tmp_path), "img002")

    payload = client.payloads[0]
    assert "alwayson_scripts" not in payload  # fallback mode should not add script payloads
    assert "dreamy tones" not in payload["prompt"]
    assert "<embedding:Cozy>" in payload["prompt"]
    assert "soft colors" in payload["prompt"]
    assert "dreamy tones" in payload["negative_prompt"]


def test_adetailer_payload_uses_image_dimensions(dummy_pipeline, tmp_path):
    pipeline, client = dummy_pipeline

    # Create an input image with a non-default size
    from PIL import Image

    image_path = tmp_path / "input.png"
    Image.new("RGB", (1024, 768), color="white").save(image_path)

    config = {
        "adetailer_enabled": True,
        "adetailer_model": "face_yolov8n.pt",
        "adetailer_confidence": 0.3,
        "adetailer_mask_feather": 4,
        "adetailer_sampler": "DPM++ 2M",
        "adetailer_steps": 28,
        "adetailer_denoise": 0.4,
        "adetailer_cfg": 7.0,
        "adetailer_prompt": "",
        "adetailer_negative_prompt": "",
    }

    pipeline.run_adetailer(image_path, "portrait", config, tmp_path)

    payload = client.payloads[-1]
    assert payload["width"] == 1024
    assert payload["height"] == 768
