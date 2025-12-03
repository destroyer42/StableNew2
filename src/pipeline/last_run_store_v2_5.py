from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from src.gui.app_state_v2 import CurrentConfig

LAST_RUN_PATH = Path("state/last_run_v2_5.json")

@dataclass
class LastRunConfigV2_5:
    model: str | None = None
    vae: str | None = None
    sampler_name: str | None = None
    scheduler: str | None = None
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    negative_prompt: str = ""
    prompt: str = ""
    preset_name: str = ""
    batch_size: int = 1
    seed: int | None = None
    refiner_enabled: bool = False
    refiner_model_name: str = ""
    refiner_switch_at: float = 0.8
    hires_enabled: bool = False
    hires_upscaler_name: str = "Latent"
    hires_upscale_factor: float = 2.0
    hires_steps: int | None = None
    hires_denoise: float = 0.3
    hires_use_base_model: bool = True


def current_config_to_last_run(cfg: CurrentConfig) -> LastRunConfigV2_5:
    return LastRunConfigV2_5(
        model=cfg.model_name or None,
        vae=cfg.vae_name or None,
        sampler_name=cfg.sampler_name or None,
        scheduler=cfg.scheduler_name or None,
        width=cfg.width,
        height=cfg.height,
        steps=cfg.steps,
        cfg_scale=cfg.cfg_scale,
        preset_name=cfg.preset_name,
        batch_size=cfg.batch_size,
        seed=cfg.seed,
        refiner_enabled=cfg.refiner_enabled,
        refiner_model_name=cfg.refiner_model_name,
        refiner_switch_at=cfg.refiner_switch_at,
        hires_enabled=cfg.hires_enabled,
        hires_upscaler_name=cfg.hires_upscaler_name,
        hires_upscale_factor=cfg.hires_upscale_factor,
        hires_steps=cfg.hires_steps,
        hires_denoise=cfg.hires_denoise,
        hires_use_base_model=cfg.hires_use_base_model_for_hires,
    )


def update_current_config_from_last_run(cfg: CurrentConfig, last: LastRunConfigV2_5) -> None:
    cfg.model_name = last.model or ""
    cfg.vae_name = last.vae or ""
    cfg.sampler_name = last.sampler_name or ""
    cfg.scheduler_name = last.scheduler or ""
    cfg.width = last.width
    cfg.height = last.height
    cfg.steps = last.steps
    cfg.cfg_scale = last.cfg_scale
    cfg.preset_name = last.preset_name or cfg.preset_name
    cfg.batch_size = last.batch_size
    cfg.seed = last.seed
    cfg.refiner_enabled = last.refiner_enabled
    cfg.refiner_model_name = last.refiner_model_name
    cfg.refiner_switch_at = last.refiner_switch_at
    cfg.hires_enabled = last.hires_enabled
    cfg.hires_upscaler_name = last.hires_upscaler_name
    cfg.hires_upscale_factor = last.hires_upscale_factor
    cfg.hires_steps = last.hires_steps
    cfg.hires_denoise = last.hires_denoise
    cfg.hires_use_base_model_for_hires = last.hires_use_base_model

class LastRunStoreV2_5:
    def __init__(self, path: Path | None = None):
        self.path = path or LAST_RUN_PATH

    def load(self) -> LastRunConfigV2_5 | None:
        if not self.path.exists():
            logging.info(f"Last-run config file not found: {self.path}")
            return None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Tolerate missing/extra fields
            return LastRunConfigV2_5(**{k: v for k, v in data.items() if k in LastRunConfigV2_5.__annotations__})
        except Exception as exc:
            logging.warning(f"Failed to load last-run config: {exc}")
            return None

    def save(self, cfg: LastRunConfigV2_5) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(asdict(cfg), f, indent=2)
            logging.info(f"Saved last-run config: model={cfg.model}, sampler={cfg.sampler_name}, steps={cfg.steps}, size={cfg.width}x{cfg.height}")
        except Exception as exc:
            logging.warning(f"Failed to save last-run config: {exc}")
