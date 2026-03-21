from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SavedRecipeSummary:
    name: str
    model: str
    sampler: str
    resolution: str
    enabled_stages: tuple[str, ...]
    last_updated: str

    def to_label_text(self) -> str:
        if not self.name:
            return "Working state"
        stages = ", ".join(self.enabled_stages) if self.enabled_stages else "txt2img"
        updated = f" | updated {self.last_updated}" if self.last_updated else ""
        return (
            f"Saved Recipe: {self.name}\n"
            f"{self.model or 'Unknown model'} | {self.resolution or 'Unknown size'} | "
            f"{self.sampler or 'Unknown sampler'} | stages: {stages}{updated}"
        )


def build_saved_recipe_summary(
    recipe_name: str,
    recipe_config: dict[str, Any] | None,
    *,
    recipe_path: Path | None = None,
) -> SavedRecipeSummary:
    config = dict(recipe_config or {})
    txt2img = dict(config.get("txt2img") or {})
    pipeline = dict(config.get("pipeline") or {})
    model = str(txt2img.get("model") or txt2img.get("model_name") or "").strip()
    sampler = str(txt2img.get("sampler_name") or txt2img.get("sampler") or "").strip()
    width = txt2img.get("width")
    height = txt2img.get("height")
    resolution = ""
    if width and height:
        resolution = f"{width}x{height}"

    enabled_stages: list[str] = []
    for stage in ("txt2img", "img2img", "adetailer", "upscale"):
        key = f"{stage}_enabled"
        if key not in pipeline:
            if stage == "txt2img":
                enabled_stages.append(stage)
            continue
        if bool(pipeline.get(key)):
            enabled_stages.append(stage)

    last_updated = ""
    if recipe_path and recipe_path.exists():
        try:
            timestamp = datetime.fromtimestamp(recipe_path.stat().st_mtime)
            last_updated = timestamp.strftime("%Y-%m-%d %H:%M")
        except Exception:
            last_updated = ""

    return SavedRecipeSummary(
        name=recipe_name,
        model=model,
        sampler=sampler,
        resolution=resolution,
        enabled_stages=tuple(enabled_stages),
        last_updated=last_updated,
    )


__all__ = ["SavedRecipeSummary", "build_saved_recipe_summary"]
