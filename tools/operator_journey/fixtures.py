"""Deterministic synthetic historical outputs for Discovered Outputs journeys."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PROMPT = "operator fixture, a lighthouse at dusk, oil painting"
NEGATIVE = "blurry, low quality"
MODEL = "fixture-model.safetensors"
CFG_VALUES = (5.0, 7.0, 9.0)
_COLORS = ((200, 40, 40), (40, 200, 40), (40, 40, 200))


def seed_sdxl_checkpoint_evidence(workspace, model: str) -> None:
    """Persist declared fixture metadata through the existing v2 cache schema.

    Called only after workspace activation and before app/policy construction.
    The content identity is synthetic fixture data, not a hash of a real model.
    AssetRegistry interprets embedded metadata; names supply no family evidence.
    """
    from src.assets import AssetRegistry
    from src.assets.compatibility import ModelFamily
    from src.state.workspace_paths import workspace_paths

    cache = workspace_paths.asset_registry_cache()
    if cache.parent != workspace.state_dir.resolve():
        raise RuntimeError("Fixture evidence requires the activated isolated workspace")
    filename = Path(model).name
    if not Path(filename).suffix:
        filename += ".safetensors"
    # RegistryFamilyLookup requires a configured root even for cache-only reads.
    # OperatorWorkspace restores this process-local seam on exit.
    os.environ["STABLENEW_WEBUI_ROOT"] = str(workspace.root / "fixture-webui")
    path = workspace.root / "fixture-models" / filename
    cache.write_text(
        json.dumps(
            {
                "version": 2,
                "entries": {
                    str(path): {
                        "sha256": "0" * 64,
                        "kind": "checkpoint",
                        "path": str(path),
                        "root": str(path.parent),
                        "name": path.name,
                        "size": 0,
                        "metadata": {"modelspec.architecture": "sdxl"},
                        "provenance": "operator-journey-declared-fixture",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    records = AssetRegistry(cache_path=cache).cached_snapshot().records
    if len(records) != 1 or records[0].compatibility.family is not ModelFamily.SDXL:
        raise RuntimeError("Fixture metadata did not establish canonical SDXL evidence")


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
