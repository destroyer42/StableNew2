# Subsystem: Pipeline
# Role: Canonical config merger for PromptPack + stage overrides → merged PipelineConfig.

"""ConfigMergerV2: Merge PromptPack-derived base configs with stage card overrides.

This module provides the canonical merging logic for combining:
- A base PipelineConfig (from PromptPack + defaults)
- Per-stage overrides (from Pipeline tab stage cards)
- Override flags (the "config override" checkbox semantics)

The merger is pure and pipeline-local: no Tk, no AppState, no queue types.
It always returns new instances (deep copies) and never mutates inputs.

Merging Rules:
- Override flag OFF: ignore stage overrides, use base config
- Override flag ON:
  - Scalar fields: override wins if not None, else fallback to base
  - Nested configs (Refiner/Hires/ADetailer):
    - If override.enabled=False → stage disabled
    - If override.enabled=True → merge nested fields with same precedence
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocols for type safety without importing concrete types
# ---------------------------------------------------------------------------

@runtime_checkable
class StageConfigLike(Protocol):
    """Protocol for stage config objects that have an enabled flag."""
    enabled: bool


@runtime_checkable
class HasRefinerConfig(Protocol):
    """Protocol for configs that have refiner sub-config."""
    refiner_enabled: bool
    refiner_model_name: str | None
    refiner_switch_at: float


@runtime_checkable
class HasHiresConfig(Protocol):
    """Protocol for configs that have hires fix sub-config."""
    hires_fix: dict[str, Any]


# ---------------------------------------------------------------------------
# Data classes for override structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StageOverrideFlags:
    """Flags indicating which stage overrides should be applied.
    
    When a flag is True, the corresponding stage card settings will override
    the PromptPack/base config. When False, base config is used unchanged.
    """
    txt2img_override_enabled: bool = False
    img2img_override_enabled: bool = False
    upscale_override_enabled: bool = False
    refiner_override_enabled: bool = False
    hires_override_enabled: bool = False
    adetailer_override_enabled: bool = False


@dataclass
class RefinerOverrides:
    """Refiner-specific override settings."""
    enabled: bool | None = None
    model_name: str | None = None
    switch_at: float | None = None


@dataclass
class HiresOverrides:
    """Hires fix override settings."""
    enabled: bool | None = None
    upscaler_name: str | None = None
    denoise_strength: float | None = None
    scale_factor: float | None = None
    steps: int | None = None


@dataclass
class ADetailerOverrides:
    """ADetailer override settings."""
    enabled: bool | None = None
    model: str | None = None
    confidence: float | None = None
    mask_blur: int | None = None
    denoise_strength: float | None = None


@dataclass
class Txt2ImgOverrides:
    """Override settings for txt2img stage."""
    enabled: bool | None = None
    model: str | None = None
    vae: str | None = None
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | None = None
    cfg_scale: float | None = None
    width: int | None = None
    height: int | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    # Nested sub-configs
    refiner: RefinerOverrides | None = None
    hires: HiresOverrides | None = None


@dataclass
class Img2ImgOverrides:
    """Override settings for img2img stage."""
    enabled: bool | None = None
    model: str | None = None
    vae: str | None = None
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | None = None
    cfg_scale: float | None = None
    denoise_strength: float | None = None
    width: int | None = None
    height: int | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None


@dataclass
class UpscaleOverrides:
    """Override settings for upscale stage."""
    enabled: bool | None = None
    upscaler_name: str | None = None
    scale_factor: float | None = None
    denoise_strength: float | None = None
    tile_size: int | None = None


@dataclass
class StageOverridesBundle:
    """Container for all stage-specific overrides.
    
    This bundle is passed to ConfigMergerV2.merge_pipeline along with
    StageOverrideFlags to indicate which overrides should be applied.
    """
    txt2img: Txt2ImgOverrides | None = None
    img2img: Img2ImgOverrides | None = None
    upscale: UpscaleOverrides | None = None
    refiner: RefinerOverrides | None = None
    hires: HiresOverrides | None = None
    adetailer: ADetailerOverrides | None = None


# ---------------------------------------------------------------------------
# ConfigMergerV2 implementation
# ---------------------------------------------------------------------------


class ConfigMergerV2:
    """Canonical merger for PromptPack + stage overrides into a PipelineConfig.

    This class provides pure static methods that:
    - Accept base pipeline config (from PromptPack + defaults)
    - Accept stage-specific overrides (or None when not present)
    - Accept override-enabled flags per stage
    - Compute a new pipeline config respecting precedence rules

    Key guarantees:
    - All methods are pure: no side effects, no mutations
    - Always returns new instances (deep copies)
    - No GUI imports, no controller imports, no randomizer/executor imports
    """

    @staticmethod
    def merge_pipeline(
        base_config: dict[str, Any],
        stage_overrides: StageOverridesBundle | None,
        override_flags: StageOverrideFlags,
    ) -> dict[str, Any]:
        """Merge base pipeline config with stage overrides.
        
        Args:
            base_config: PromptPack-derived base configuration dict.
            stage_overrides: Container with per-stage override configs.
            override_flags: Flags indicating which overrides to apply.
            
        Returns:
            A NEW merged config dict; base_config is not mutated.
        """
        # Start with a deep copy of base config
        merged = deepcopy(base_config)
        
        if stage_overrides is None:
            return merged
        
        # Merge txt2img stage
        if override_flags.txt2img_override_enabled and stage_overrides.txt2img is not None:
            merged = ConfigMergerV2._merge_txt2img_into_config(
                merged, stage_overrides.txt2img, override_flags
            )
        
        # Merge img2img stage
        if override_flags.img2img_override_enabled and stage_overrides.img2img is not None:
            merged = ConfigMergerV2._merge_img2img_into_config(
                merged, stage_overrides.img2img
            )
        
        # Merge upscale stage
        if override_flags.upscale_override_enabled and stage_overrides.upscale is not None:
            merged = ConfigMergerV2._merge_upscale_into_config(
                merged, stage_overrides.upscale
            )
        
        # Merge refiner settings (can be overridden independently)
        if override_flags.refiner_override_enabled and stage_overrides.refiner is not None:
            merged = ConfigMergerV2._merge_refiner_into_config(
                merged, stage_overrides.refiner
            )
        
        # Merge hires settings (can be overridden independently)
        if override_flags.hires_override_enabled and stage_overrides.hires is not None:
            merged = ConfigMergerV2._merge_hires_into_config(
                merged, stage_overrides.hires
            )
        
        # Merge adetailer settings
        if override_flags.adetailer_override_enabled and stage_overrides.adetailer is not None:
            merged = ConfigMergerV2._merge_adetailer_into_config(
                merged, stage_overrides.adetailer
            )
        
        return merged

    @staticmethod
    def merge_stage(
        base_stage_config: dict[str, Any],
        override_stage_config: dict[str, Any] | None,
        override_enabled: bool,
    ) -> dict[str, Any]:
        """Merge a single stage config with field-level precedence rules.
        
        Args:
            base_stage_config: Base stage configuration dict.
            override_stage_config: Override values (or None).
            override_enabled: Whether overrides should be applied.
            
        Returns:
            A NEW merged stage config dict.
        """
        # If override disabled or no overrides, return deep copy of base
        if not override_enabled or override_stage_config is None:
            return deepcopy(base_stage_config)
        
        # Start with deep copy of base
        merged = deepcopy(base_stage_config)
        
        # Apply overrides: override field wins if not None
        for key, value in override_stage_config.items():
            if value is not None:
                # Handle nested dicts (like hires_fix, refiner settings)
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = ConfigMergerV2._merge_nested_dict(
                        merged[key], value
                    )
                else:
                    merged[key] = value
        
        return merged

    @staticmethod
    def merge_refiner_config(
        base_refiner: dict[str, Any],
        override_refiner: RefinerOverrides | None,
        override_enabled: bool,
    ) -> dict[str, Any]:
        """Merge refiner sub-config with precedence rules.
        
        If override.enabled is False, the entire refiner stage is disabled.
        If override.enabled is True, individual fields are merged.
        """
        if not override_enabled or override_refiner is None:
            return deepcopy(base_refiner)
        
        merged = deepcopy(base_refiner)
        
        # Check enable flag first - if override explicitly disables, disable entirely
        if override_refiner.enabled is not None:
            merged["enabled"] = override_refiner.enabled
            if not override_refiner.enabled:
                # Disabled - return with enabled=False
                return merged
        
        # Merge individual fields (override wins if not None)
        if override_refiner.model_name is not None:
            merged["model_name"] = override_refiner.model_name
        if override_refiner.switch_at is not None:
            merged["switch_at"] = override_refiner.switch_at
        
        return merged

    @staticmethod
    def merge_hires_config(
        base_hires: dict[str, Any],
        override_hires: HiresOverrides | None,
        override_enabled: bool,
    ) -> dict[str, Any]:
        """Merge hires fix sub-config with precedence rules.
        
        If override.enabled is False, the entire hires stage is disabled.
        If override.enabled is True, individual fields are merged.
        """
        if not override_enabled or override_hires is None:
            return deepcopy(base_hires)
        
        merged = deepcopy(base_hires)
        
        # Check enable flag first
        if override_hires.enabled is not None:
            merged["enabled"] = override_hires.enabled
            if not override_hires.enabled:
                return merged
        
        # Merge individual fields
        if override_hires.upscaler_name is not None:
            merged["upscaler_name"] = override_hires.upscaler_name
        if override_hires.denoise_strength is not None:
            merged["denoise_strength"] = override_hires.denoise_strength
        if override_hires.scale_factor is not None:
            merged["scale_factor"] = override_hires.scale_factor
        if override_hires.steps is not None:
            merged["steps"] = override_hires.steps
        
        return merged

    @staticmethod
    def merge_adetailer_config(
        base_adetailer: dict[str, Any],
        override_adetailer: ADetailerOverrides | None,
        override_enabled: bool,
    ) -> dict[str, Any]:
        """Merge ADetailer sub-config with precedence rules."""
        if not override_enabled or override_adetailer is None:
            return deepcopy(base_adetailer)
        
        merged = deepcopy(base_adetailer)
        
        if override_adetailer.enabled is not None:
            merged["enabled"] = override_adetailer.enabled
            if not override_adetailer.enabled:
                return merged
        
        if override_adetailer.model is not None:
            merged["model"] = override_adetailer.model
        if override_adetailer.confidence is not None:
            merged["confidence"] = override_adetailer.confidence
        if override_adetailer.mask_blur is not None:
            merged["mask_blur"] = override_adetailer.mask_blur
        if override_adetailer.denoise_strength is not None:
            merged["denoise_strength"] = override_adetailer.denoise_strength
        
        return merged

    # ---------------------------------------------------------------------------
    # Internal helper methods
    # ---------------------------------------------------------------------------

    @staticmethod
    def _merge_nested_dict(
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """Recursively merge nested dicts (override wins for non-None values)."""
        merged = deepcopy(base)
        for key, value in override.items():
            if value is not None:
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = ConfigMergerV2._merge_nested_dict(merged[key], value)
                else:
                    merged[key] = value
        return merged

    @staticmethod
    def _merge_txt2img_into_config(
        config: dict[str, Any],
        overrides: Txt2ImgOverrides,
        flags: StageOverrideFlags,
    ) -> dict[str, Any]:
        """Apply txt2img overrides to the merged config."""
        # Apply top-level txt2img fields
        if overrides.model is not None:
            config["model"] = overrides.model
        if overrides.vae is not None:
            config["vae"] = overrides.vae
        if overrides.sampler is not None:
            config["sampler"] = overrides.sampler
        if overrides.scheduler is not None:
            config["scheduler"] = overrides.scheduler
        if overrides.steps is not None:
            config["steps"] = overrides.steps
        if overrides.cfg_scale is not None:
            config["cfg_scale"] = overrides.cfg_scale
        if overrides.width is not None:
            config["width"] = overrides.width
        if overrides.height is not None:
            config["height"] = overrides.height
        if overrides.prompt is not None:
            config["prompt"] = overrides.prompt
        if overrides.negative_prompt is not None:
            config["negative_prompt"] = overrides.negative_prompt
        if overrides.seed is not None:
            config["seed"] = overrides.seed
        
        # Handle nested refiner config within txt2img overrides
        if overrides.refiner is not None:
            base_refiner = config.get("refiner", {}) or {}
            merged_refiner = ConfigMergerV2.merge_refiner_config(
                base_refiner, overrides.refiner, True
            )
            config["refiner"] = merged_refiner
            # Also set top-level refiner_enabled flag
            if overrides.refiner.enabled is not None:
                config["refiner_enabled"] = overrides.refiner.enabled
        
        # Handle nested hires config within txt2img overrides
        if overrides.hires is not None:
            base_hires = config.get("hires_fix", {}) or {}
            merged_hires = ConfigMergerV2.merge_hires_config(
                base_hires, overrides.hires, True
            )
            config["hires_fix"] = merged_hires
        
        return config

    @staticmethod
    def _merge_img2img_into_config(
        config: dict[str, Any],
        overrides: Img2ImgOverrides,
    ) -> dict[str, Any]:
        """Apply img2img overrides to the merged config."""
        img2img = config.get("img2img", {}) or {}
        
        if overrides.enabled is not None:
            img2img["enabled"] = overrides.enabled
        if overrides.model is not None:
            img2img["model"] = overrides.model
        if overrides.vae is not None:
            img2img["vae"] = overrides.vae
        if overrides.sampler is not None:
            img2img["sampler"] = overrides.sampler
        if overrides.scheduler is not None:
            img2img["scheduler"] = overrides.scheduler
        if overrides.steps is not None:
            img2img["steps"] = overrides.steps
        if overrides.cfg_scale is not None:
            img2img["cfg_scale"] = overrides.cfg_scale
        if overrides.denoise_strength is not None:
            img2img["denoise_strength"] = overrides.denoise_strength
        if overrides.width is not None:
            img2img["width"] = overrides.width
        if overrides.height is not None:
            img2img["height"] = overrides.height
        if overrides.prompt is not None:
            img2img["prompt"] = overrides.prompt
        if overrides.negative_prompt is not None:
            img2img["negative_prompt"] = overrides.negative_prompt
        if overrides.seed is not None:
            img2img["seed"] = overrides.seed
        
        config["img2img"] = img2img
        return config

    @staticmethod
    def _merge_upscale_into_config(
        config: dict[str, Any],
        overrides: UpscaleOverrides,
    ) -> dict[str, Any]:
        """Apply upscale overrides to the merged config."""
        upscale = config.get("upscale", {}) or {}
        
        if overrides.enabled is not None:
            upscale["enabled"] = overrides.enabled
        if overrides.upscaler_name is not None:
            upscale["upscaler_name"] = overrides.upscaler_name
        if overrides.scale_factor is not None:
            upscale["scale_factor"] = overrides.scale_factor
        if overrides.denoise_strength is not None:
            upscale["denoise_strength"] = overrides.denoise_strength
        if overrides.tile_size is not None:
            upscale["tile_size"] = overrides.tile_size
        
        config["upscale"] = upscale
        return config

    @staticmethod
    def _merge_refiner_into_config(
        config: dict[str, Any],
        overrides: RefinerOverrides,
    ) -> dict[str, Any]:
        """Apply refiner overrides at the top level of config."""
        base_refiner = config.get("refiner", {}) or {}
        merged = ConfigMergerV2.merge_refiner_config(base_refiner, overrides, True)
        config["refiner"] = merged
        
        # Also update top-level refiner_enabled flag
        if overrides.enabled is not None:
            config["refiner_enabled"] = overrides.enabled
        
        return config

    @staticmethod
    def _merge_hires_into_config(
        config: dict[str, Any],
        overrides: HiresOverrides,
    ) -> dict[str, Any]:
        """Apply hires fix overrides at the top level of config."""
        base_hires = config.get("hires_fix", {}) or {}
        merged = ConfigMergerV2.merge_hires_config(base_hires, overrides, True)
        config["hires_fix"] = merged
        return config

    @staticmethod
    def _merge_adetailer_into_config(
        config: dict[str, Any],
        overrides: ADetailerOverrides,
    ) -> dict[str, Any]:
        """Apply ADetailer overrides to the merged config."""
        base_ad = config.get("adetailer", {}) or {}
        merged = ConfigMergerV2.merge_adetailer_config(base_ad, overrides, True)
        config["adetailer"] = merged
        return config


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "StageOverrideFlags",
    "StageOverridesBundle",
    "Txt2ImgOverrides",
    "Img2ImgOverrides",
    "UpscaleOverrides",
    "RefinerOverrides",
    "HiresOverrides",
    "ADetailerOverrides",
    "ConfigMergerV2",
]
