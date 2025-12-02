from __future__ import annotations

from copy import deepcopy

from src.gui_v2.adapters.pipeline_adapter_v2 import build_effective_config, run_controller


class _DummyController:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_pipeline(self, config: dict) -> str:
        self.calls.append(deepcopy(config))
        return "ok"


def test_build_effective_config_merges_stage_overrides_without_mutation() -> None:
    base_config = {
        "txt2img": {"steps": 20, "cfg_scale": 7.0},
        "img2img": {"denoising_strength": 0.3},
        "upscale": {"upscaler": "R-ESRGAN 4x+"},
        "pipeline": {"variant_mode": "fanout"},
    }
    original = deepcopy(base_config)

    effective = build_effective_config(
        base_config,
        txt2img_overrides={"steps": 10, "width": 768},
        img2img_overrides={"denoising_strength": 0.5},
        upscale_overrides={"upscaler": "Latent"},
        pipeline_overrides={"variant_fanout": 2},
    )

    assert base_config == original  # no mutation
    assert effective["txt2img"]["steps"] == 10
    assert effective["txt2img"]["width"] == 768
    assert effective["img2img"]["denoising_strength"] == 0.5
    assert effective["upscale"]["upscaler"] == "Latent"
    assert effective["pipeline"]["variant_mode"] == "fanout"
    assert effective["pipeline"]["variant_fanout"] == 2


def test_run_controller_invokes_controller_once() -> None:
    controller = _DummyController()
    payload = {"txt2img": {"steps": 5}}

    result = run_controller(controller, payload)

    assert result == "ok"
    assert controller.calls == [payload]
