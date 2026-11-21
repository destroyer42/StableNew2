"""Shared SDXL Turbo recipe for compatibility probes and advisory Research."""

from types import MappingProxyType

SDXL_TURBO_LABEL = "SDXL Turbo (512², Euler a SGM Uniform, 4 steps, CFG 1)"
SDXL_TURBO_SOURCE = "https://huggingface.co/stabilityai/sdxl-turbo"
SDXL_TURBO_NOTE = "Publisher recipe is 1–4 steps without guidance (CFG 1 here); many steps or high CFG burn the image."
SDXL_TURBO_SETTINGS = MappingProxyType({
    "sampler_name": "Euler a",
    "scheduler": "SGM Uniform",
    "steps": 4,
    "cfg_scale": 1.0,
    "width": 512,
    "height": 512,
})
