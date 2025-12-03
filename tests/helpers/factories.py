from __future__ import annotations

from typing import Any

from src.gui.app_state_v2 import AppStateV2, CurrentConfig


def make_run_config(
    *,
    txt2img_enabled: bool = True,
    img2img_enabled: bool = False,
    adetailer_enabled: bool = False,
    upscale_enabled: bool = False,
    refiner_enabled: bool = False,
    hires_enabled: bool = False,
    model: str = "sd_xl_base_1.0",
    sampler: str = "Euler",
    scheduler: str = "Normal",
    steps: int = 20,
    cfg_scale: float = 7.0,
    width: int = 832,
    height: int = 1216,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a normalized run configuration dict for controller tests."""

    pipeline = {
        "txt2img_enabled": txt2img_enabled,
        "img2img_enabled": img2img_enabled,
        "adetailer_enabled": adetailer_enabled,
        "upscale_enabled": upscale_enabled,
        "refiner_enabled": refiner_enabled,
        "hires_enabled": hires_enabled,
    }

    config = {
        "model": model,
        "sampler": sampler,
        "scheduler": scheduler,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "width": width,
        "height": height,
        "pipeline": pipeline,
    }

    if overrides:
        config.update(overrides)

    return config


def make_current_config(**overrides: Any) -> CurrentConfig:
    """Construct a CurrentConfig facade pre-populated with overrides."""

    config = CurrentConfig()
    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config


def update_current_config(app_state: AppStateV2, **overrides: Any) -> CurrentConfig:
    """Apply overrides to the AppStateV2 current_config in-place."""

    config = app_state.current_config
    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config
