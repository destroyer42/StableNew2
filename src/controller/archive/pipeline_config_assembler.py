from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.controller.archive.pipeline_config_types import PipelineConfig
"""
# VIEW-ONLY (v2.6)
This module is archive-only and may import legacy PipelineConfig types from
src.controller.archive.pipeline_config_types for reference.
"""
from src.utils.config import ConfigManager
from src.utils.randomizer import PromptRandomizer
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.state import PipelineState


@dataclass
class GuiOverrides:
    prompt: str = ""
    model: str = ""
    model_name: str = ""
    vae_name: str = ""
    sampler: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    resolution_preset: str = ""
    negative_prompt: str = ""
    output_dir: str = ""
    filename_pattern: str = ""
    image_format: str = ""
    batch_size: int = 1
    seed_mode: str = ""
    metadata: dict[str, Any] | None = None


@dataclass
class PlannedJob:
    """A single job in a RunPlan."""
    prompt_text: str
    lora_settings: dict[str, dict[str, Any]] | None = None
    randomizer_metadata: dict[str, Any] | None = None


@dataclass
class RunPlan:
    """Plan for a pipeline run with multiple jobs."""
    jobs: list[PlannedJob]
    summary: str = ""


class PipelineConfigAssembler:
    """Translate GUI/controller inputs into a PipelineConfig instance."""

    def __init__(self, *, config_manager: ConfigManager | None = None, max_megapixels: float = 16.0) -> None:
        self._config_manager = config_manager or ConfigManager()
        self._max_megapixels = max(max_megapixels, 0.1)

    def build_from_gui_input(
        self,
        *,
        base_config: dict[str, Any] | None = None,
        overrides: GuiOverrides | dict[str, Any] | None = None,
        randomizer_metadata: dict[str, Any] | None = None,
        learning_metadata: dict[str, Any] | None = None,
        lora_settings: dict[str, dict[str, Any]] | None = None,
    ) -> PipelineConfig:
        gui_overrides = self._normalize_overrides(overrides)
        base = deepcopy(base_config or self._default_txt2img())
        merged = self._merge_base_and_overrides(base, gui_overrides)

        preset_value = gui_overrides.get("resolution_preset") or merged.get("resolution_preset")
        if preset_value:
            merged = self._apply_resolution_preset(merged, preset_value)

        merged = self.apply_megapixel_clamp(merged)

        metadata = dict(gui_overrides.get("metadata") or {})
        if gui_overrides.get("negative_prompt") is not None:
            metadata["negative_prompt"] = gui_overrides.get("negative_prompt", "")
        if gui_overrides.get("vae_name"):
            metadata["vae"] = gui_overrides.get("vae_name", "")
        if gui_overrides.get("model_name"):
            metadata["model_name"] = gui_overrides.get("model_name", "")
        output_meta = {
            "output_dir": gui_overrides.get("output_dir"),
            "filename_pattern": gui_overrides.get("filename_pattern"),
            "image_format": gui_overrides.get("image_format"),
            "batch_size": gui_overrides.get("batch_size"),
            "seed_mode": gui_overrides.get("seed_mode"),
        }
        metadata["output"] = {k: v for k, v in output_meta.items() if v not in (None, "")}
        if learning_metadata:
            metadata["learning"] = learning_metadata
            metadata["learning_enabled"] = bool(learning_metadata.get("learning_enabled", True))
        if randomizer_metadata:
            metadata["randomizer"] = randomizer_metadata

        selected_model = gui_overrides.get("model_name") or gui_overrides.get("model") or merged.get("model", "")

        return PipelineConfig(
            prompt=gui_overrides.get("prompt", merged.get("prompt", "")),
            negative_prompt=gui_overrides.get("negative_prompt", merged.get("negative_prompt", "")),
            model=selected_model,
            sampler=gui_overrides.get("sampler", merged.get("sampler_name", "")),
            width=int(merged.get("width", 512)),
            height=int(merged.get("height", 512)),
            steps=int(merged.get("steps", 20)),
            cfg_scale=float(merged.get("cfg_scale", 7.0)),
            lora_settings=lora_settings,
            metadata=metadata,
        )

    def build_for_learning_run(
        self,
        *,
        base_config: dict[str, Any] | None = None,
        overrides: GuiOverrides | dict[str, Any] | None = None,
        learning_metadata: dict[str, Any] | None = None,
        randomizer_metadata: dict[str, Any] | None = None,
    ) -> PipelineConfig:
        learning_meta = dict(learning_metadata or {})
        learning_meta["learning_enabled"] = True
        return self.build_from_gui_input(
            base_config=base_config,
            overrides=overrides,
            randomizer_metadata=randomizer_metadata,
            learning_metadata=learning_meta,
        )

    def apply_megapixel_clamp(self, cfg: dict[str, Any]) -> dict[str, Any]:
        width = int(cfg.get("width", 512))
        height = int(cfg.get("height", 512))
        if width <= 0 or height <= 0:
            return cfg

        current_mp = (width * height) / 1_000_000
        if current_mp <= self._max_megapixels:
            return cfg

        scale = math.sqrt(self._max_megapixels / current_mp)
        cfg["width"] = max(64, int(width * scale))
        cfg["height"] = max(64, int(height * scale))
        return cfg

    def attach_randomizer_metadata(self, config: PipelineConfig, rand_meta: dict[str, Any]) -> PipelineConfig:
        config.metadata = config.metadata or {}
        config.metadata["randomizer"] = rand_meta
        return config

    def _default_txt2img(self) -> dict[str, Any]:
        defaults = self._config_manager.get_default_config()
        return deepcopy(defaults.get("txt2img", {}))

    def _normalize_overrides(self, overrides: GuiOverrides | dict[str, Any] | None) -> dict[str, Any]:
        if overrides is None:
            return {}
        if isinstance(overrides, GuiOverrides):
            return {
                "prompt": overrides.prompt,
                "model": overrides.model,
                "model_name": overrides.model_name,
                "vae_name": overrides.vae_name,
                "sampler": overrides.sampler,
                "width": overrides.width,
                "height": overrides.height,
                "steps": overrides.steps,
                "cfg_scale": overrides.cfg_scale,
                "resolution_preset": overrides.resolution_preset,
                "negative_prompt": overrides.negative_prompt,
                "output_dir": overrides.output_dir,
                "filename_pattern": overrides.filename_pattern,
                "image_format": overrides.image_format,
                "batch_size": overrides.batch_size,
                "seed_mode": overrides.seed_mode,
                "metadata": overrides.metadata or {},
            }
        return dict(overrides)

    def _merge_base_and_overrides(self, base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base or {})
        for k, v in overrides.items():
            if v is None:
                continue
            merged[k] = v
        return merged

    def _apply_resolution_preset(self, cfg: dict[str, Any], preset: str) -> dict[str, Any]:
        width_height = self._parse_resolution_preset(preset)
        if width_height:
            cfg["width"], cfg["height"] = width_height
            cfg["resolution_preset"] = preset
        return cfg

    @staticmethod
    def _parse_resolution_preset(preset: str) -> tuple[int, int] | None:
        if not preset:
            return None
        token = preset.lower().replace(" ", "")
        if "x" not in token:
            return None
        try:
            parts = token.split("x")
            if len(parts) != 2:
                return None
            width = int(parts[0])
            height = int(parts[1])
            return width, height
        except Exception:
            return None

    def build_run_plan(
        self,
        prompt_workspace_state: PromptWorkspaceState,
        pipeline_state: PipelineState,
    ) -> RunPlan:
        """Build a RunPlan from the current prompt and pipeline state."""
        prompt_text = prompt_workspace_state.get_current_prompt_text()
        if not prompt_text.strip():
            return RunPlan(jobs=[], summary="No prompt text")

        # Get randomizer config from pipeline_state
        randomizer_config = {
            "enabled": pipeline_state.randomizer_mode != "off",
            "mode": pipeline_state.randomizer_mode,
            "max_variants": pipeline_state.max_variants,
        }

        randomizer = PromptRandomizer(randomizer_config)
        variants = randomizer.generate(prompt_text)

        jobs = []
        for variant in variants:
            # Convert LoraRuntimeSettings to dict
            lora_dict = {}
            for name, settings in pipeline_state.lora_settings.items():
                lora_dict[name] = {"enabled": settings.enabled, "strength": settings.strength}
            job = PlannedJob(
                prompt_text=variant.text,
                lora_settings=lora_dict if lora_dict else None,
                randomizer_metadata={"variant_label": variant.label} if variant.label else None,
            )
            jobs.append(job)

        summary = f"{len(jobs)} job(s) planned"
        return RunPlan(jobs=jobs, summary=summary)
