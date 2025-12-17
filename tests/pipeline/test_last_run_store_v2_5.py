import json

from src.gui.app_state_v2 import CurrentConfig
from src.pipeline.last_run_store_v2_5 import (
    LastRunConfigV2_5,
    LastRunStoreV2_5,
    current_config_to_last_run,
)


def test_save_and_load_roundtrip(tmp_path):
    store_path = tmp_path / "last_run.json"
    store = LastRunStoreV2_5(path=store_path)
    cfg = LastRunConfigV2_5(
        model="test-model",
        vae="test-vae",
        sampler_name="test-sampler",
        scheduler="test-scheduler",
        width=640,
        height=480,
        steps=42,
        cfg_scale=1.5,
        negative_prompt="neg",
        prompt="prompt text",
    )
    store.save(cfg)
    loaded = store.load()
    assert loaded is not None
    assert loaded.model == "test-model"
    assert loaded.width == 640
    assert loaded.prompt == "prompt text"


def test_missing_file(tmp_path):
    store_path = tmp_path / "missing.json"
    store = LastRunStoreV2_5(path=store_path)
    loaded = store.load()
    assert loaded is None


def test_corrupted_file(tmp_path):
    store_path = tmp_path / "corrupt.json"
    store_path.write_text("not a json")
    store = LastRunStoreV2_5(path=store_path)
    loaded = store.load()
    assert loaded is None


def test_extra_fields_ignored(tmp_path):
    store_path = tmp_path / "extra.json"
    data = {
        "model": "x",
        "vae": "y",
        "width": 123,
        "height": 456,
        "steps": 10,
        "cfg_scale": 2.0,
        "negative_prompt": "neg",
        "prompt": "p",
        "extra_field": "should be ignored",
    }
    store_path.write_text(json.dumps(data))
    store = LastRunStoreV2_5(path=store_path)
    loaded = store.load()
    assert loaded is not None
    assert not hasattr(loaded, "extra_field")


def test_current_config_to_last_run_includes_hires_defaults():
    cfg = CurrentConfig()
    last = current_config_to_last_run(cfg)
    assert last.hires_enabled is False
    assert last.hires_upscaler_name == "Latent"
    assert last.hires_upscale_factor == 2.0
    assert last.hires_use_base_model is True
