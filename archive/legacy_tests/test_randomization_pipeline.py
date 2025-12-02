from copy import deepcopy
from pathlib import Path

import pytest

from src.pipeline.executor import Pipeline
from src.utils.config import ConfigManager
from src.utils.logger import StructuredLogger


class StubClient:
    def __init__(self):
        self.payloads = []

    def txt2img(self, payload):
        self.payloads.append(payload)
        return {"images": ["stub"]}

    def set_model(self, *_args, **_kwargs):
        return True

    def set_vae(self, *_args, **_kwargs):
        return True

    def set_hypernetwork(self, *_args, **_kwargs):
        return True


@pytest.fixture
def pipeline_with_stub(tmp_path, monkeypatch):
    client = StubClient()
    logger = StructuredLogger(output_dir=str(tmp_path))
    pipeline = Pipeline(client, logger)

    captured = {}

    def fake_txt2img_stage(prompt, negative_prompt, config, output_dir, image_name):
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"{image_name}.png"
        image_path.write_text("stub")
        captured["prompt"] = prompt
        captured["negative"] = negative_prompt
        captured["config_negative"] = config.get("txt2img", {}).get("negative_prompt")
        pipeline.client.txt2img(
            {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
            }
        )
        return {
            "path": str(image_path),
            "summary": [{"generated": True}],
        }

    monkeypatch.setattr(pipeline, "run_txt2img_stage", fake_txt2img_stage)
    monkeypatch.setattr(pipeline, "run_img2img_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "run_adetailer", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "run_upscale_stage", lambda *args, **kwargs: None)

    return pipeline, client, captured


def test_run_pack_pipeline_uses_variant_negative(tmp_path, pipeline_with_stub):
    pipeline, client, captured = pipeline_with_stub

    base_config = ConfigManager().get_default_config()
    base_config.setdefault("pipeline", {})["img2img_enabled"] = False
    base_config.setdefault("pipeline", {})["adetailer_enabled"] = False
    base_config.setdefault("pipeline", {})["upscale_enabled"] = False
    base_config["txt2img"]["negative_prompt"] = "config base"
    base_config["img2img"]["negative_prompt"] = ""

    config = deepcopy(base_config)
    run_dir = Path(tmp_path)
    negative_prompt = "config base extra"

    result = pipeline.run_pack_pipeline(
        pack_name="demo",
        prompt="hero",
        config=config,
        run_dir=run_dir,
        prompt_index=0,
        batch_size=1,
        variant_index=0,
        variant_label=None,
        negative_prompt=negative_prompt,
    )

    assert captured["negative"] == negative_prompt
    assert captured["config_negative"] == negative_prompt
    assert result["txt2img"], "txt2img metadata should be captured"
    assert client.payloads, "txt2img call should have occurred"
    assert client.payloads[0]["negative_prompt"] == negative_prompt
