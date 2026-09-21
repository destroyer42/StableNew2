"""Deterministic synthetic historical outputs for Discovered Outputs journeys."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PROMPT = "operator fixture, a lighthouse at dusk, oil painting"
NEGATIVE = "blurry, low quality"
MODEL = "fixture-model.safetensors"
CFG_VALUES = (5.0, 7.0, 9.0)
_COLORS = ((200, 40, 40), (40, 200, 40), (40, 40, 200))


@dataclass(frozen=True)
class FixtureArtifact:
    cfg_scale: float
    image: Path
    manifest: Path


def write_png(path: Path, color: tuple[int, int, int]) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color).save(path, format="PNG")


def write_discovered_fixture(output_root: Path) -> list[FixtureArtifact]:
    """Write three artifacts of one observational context varying only in CFG.

    Layout matches a finished pipeline run: ``<run>/<stem>.png`` with
    ``<run>/manifests/<stem>.json``.  Nothing here calls a generation backend.
    """

    run_dir = output_root / "Pipeline" / "20260101_000000_operator_fixture"
    artifacts: list[FixtureArtifact] = []
    for cfg, color in zip(CFG_VALUES, _COLORS, strict=True):
        stem = f"txt2img_fixture_cfg{int(cfg)}"
        image = run_dir / f"{stem}.png"
        manifest = run_dir / "manifests" / f"{stem}.json"
        write_png(image, color)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "stage": "txt2img",
                    "final_prompt": PROMPT,
                    "final_negative_prompt": NEGATIVE,
                    "model": MODEL,
                    "sampler_name": "Euler a",
                    "scheduler": "normal",
                    "steps": 20,
                    "cfg_scale": cfg,
                    "seed": 12345,
                    "width": 64,
                    "height": 64,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        artifacts.append(FixtureArtifact(cfg, image, manifest))
    return artifacts
