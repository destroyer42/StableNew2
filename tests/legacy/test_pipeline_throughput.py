from unittest.mock import Mock, patch

import pytest

from src.pipeline.executor import Pipeline
from src.utils.logger import StructuredLogger


@pytest.fixture
def pipeline(tmp_path):
    client = Mock()
    client.txt2img.return_value = {
        "images": [
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEklEQVR42mP8/5+hHgAHggJ/lTp12wAAAABJRU5ErkJggg=="
        ]
    }
    client.set_model = Mock()
    client.set_vae = Mock()
    logger = StructuredLogger(output_dir=tmp_path / "logs")
    pipe = Pipeline(client, logger)
    return pipe, client


def test_model_cache_prevents_duplicate_set_model(tmp_path, pipeline):
    pipe, client = pipeline
    config = {"txt2img": {"model": "juggernautXL.safetensors", "vae": "sdxl_vae.safetensors"}}
    output_dir = tmp_path / "txt"
    output_dir.mkdir()

    with patch("src.pipeline.executor.save_image_from_base64", return_value=True):
        pipe.run_txt2img_stage("prompt one", "", config, output_dir, "img1")
        pipe.run_txt2img_stage("prompt two", "", config, output_dir, "img2")

    # Each weight should be pushed only once thanks to caching
    assert client.set_model.call_count == 1
    assert client.set_vae.call_count == 1
