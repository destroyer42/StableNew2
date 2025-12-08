"""Model/profile defaults resolver for SD models and GUI helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional

from src.learning.model_profiles import STYLE_DEFAULTS, infer_style_id_for_model
from src.utils.config import ConfigManager


@dataclass(frozen=True)
class ModelDefaultsContext:
    """Context describing the current model/preset selection."""

    model_name: str | None = None
    preset_name: str | None = None


class ModelDefaultsResolver:
    """Resolves model/profile defaults on top of ConfigManager presets."""

    def __init__(self, *, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager or ConfigManager()

    def resolve_config(
        self,
        context: ModelDefaultsContext,
        *,
        runtime_overrides: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a config dict that includes defaults for the model/preset."""
        config = self._config_manager.resolve_config(
            preset_name=context.preset_name,
            pack_overrides=None,
            runtime_params=None,
        )
        self._apply_style_defaults(config, context.model_name)
        if runtime_overrides:
            config = self._merge(runtime_overrides, config)
        return config

    def _merge(
        self,
        overrides: Mapping[str, Any],
        base: dict[str, Any],
    ) -> dict[str, Any]:
        return self._config_manager._merge_configs(base, dict(overrides))

    def _apply_style_defaults(self, config: dict[str, Any], model_name: str | None) -> None:
        style_id = infer_style_id_for_model(model_name)
        style_defaults = STYLE_DEFAULTS.get(style_id or "", {}) if style_id else {}
        if not style_defaults:
            return
        txt2img = config.setdefault("txt2img", {})
        hires = config.setdefault("hires_fix", {})
        engine_defaults = self._config_manager.get_default_config()
        base_txt = engine_defaults.get("txt2img", {})
        base_hires = engine_defaults.get("hires_fix", {})

        refiner_model = style_defaults.get("default_refiner_id")
        if refiner_model:
            existing = (txt2img.get("refiner_model_name") or "").strip()
            baseline = (base_txt.get("refiner_model_name") or "").strip()
            if not existing or existing == baseline:
                txt2img["refiner_enabled"] = True
                txt2img["refiner_model_name"] = refiner_model
        hires_upscaler = style_defaults.get("default_hires_upscaler_id")
        if hires_upscaler:
            existing = (hires.get("upscaler_name") or "").strip()
            baseline = (base_hires.get("upscaler_name") or "").strip()
            if not existing or existing == baseline:
                hires["enabled"] = True
                hires["upscaler_name"] = hires_upscaler
        hires_denoise = style_defaults.get("default_hires_denoise")
        if hires_denoise is not None:
            existing = hires.get("denoise")
            baseline = base_hires.get("denoise")
            if existing in (None, baseline):
                hires["denoise"] = hires_denoise


class GuiDefaultsResolver:
    """Helper that adapts resolved configs into GUI-friendly defaults."""

    def __init__(self, *, config_manager: ConfigManager | None = None) -> None:
        self._model_resolver = ModelDefaultsResolver(config_manager=config_manager)

    def resolve_for_gui(self, *, model_name: str | None, preset_name: str | None = None) -> dict[str, Any]:
        ctx = ModelDefaultsContext(model_name=model_name, preset_name=preset_name)
        config = self._model_resolver.resolve_config(ctx)
        txt2img = config.get("txt2img", {})
        hires = config.get("hires_fix", {})
        return {
            "txt2img": {
                "steps": txt2img.get("steps"),
                "cfg_scale": txt2img.get("cfg_scale"),
                "sampler_name": txt2img.get("sampler_name"),
                "scheduler": txt2img.get("scheduler"),
                "width": txt2img.get("width"),
                "height": txt2img.get("height"),
                "refiner_enabled": txt2img.get("refiner_enabled"),
                "refiner_model_name": txt2img.get("refiner_model_name"),
                "refiner_switch_at": txt2img.get("refiner_switch_at"),
            },
            "hires_fix": {
                "enabled": hires.get("enabled"),
                "upscaler_name": hires.get("upscaler_name"),
                "upscale_factor": hires.get("upscale_factor"),
                "denoise": hires.get("denoise"),
                "steps": hires.get("steps"),
            },
        }
