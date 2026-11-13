from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.gui_v2.adapters.config_adapter_v26 import GuiConfigAdapterV26
from src.pipeline.config_merger_v2 import (
    ADetailerOverrides,
    ConfigMergerV2,
    HiresOverrides,
    Img2ImgOverrides,
    RefinerOverrides,
    StageOverrideFlags,
    StageOverridesBundle,
    Txt2ImgOverrides,
    UpscaleOverrides,
)
from src.pipeline.global_prompt_policy import apply_global_prompt_policy


@dataclass(frozen=True)
class PackDraftConfig:
    """Working inputs captured once on the GUI thread for one Add to Job action."""

    base_config: dict[str, Any]
    global_prompt_policy: dict[str, Any]
    stage_overrides: StageOverridesBundle | None

    def merge(self, pack_config: dict[str, Any]) -> dict[str, Any]:
        config = {**self.base_config, **pack_config}
        if self.stage_overrides is not None:
            config = ConfigMergerV2.merge_pipeline(
                config,
                self.stage_overrides,
                StageOverrideFlags(
                    txt2img_override_enabled=True,
                    img2img_override_enabled=True,
                    upscale_override_enabled=True,
                    refiner_override_enabled=True,
                    hires_override_enabled=True,
                    adetailer_override_enabled=True,
                ),
            )
        return apply_global_prompt_policy(config, **self.global_prompt_policy)


def build_stage_overrides(current_config: dict[str, Any]) -> StageOverridesBundle:
    """Translate exported stage settings into the canonical typed overrides."""
    # Extract txt2img settings (stage cards export under "txt2img")
    txt2img_overrides = None
    txt2img_config = current_config.get("txt2img") or {}
    if txt2img_config:
        txt2img_overrides = Txt2ImgOverrides(
            model=txt2img_config.get("model"),
            vae=txt2img_config.get("vae"),
            sampler=txt2img_config.get(
                "sampler_name"
            ),  # Note: field is "sampler", not "sampler_name"
            scheduler=txt2img_config.get("scheduler"),
            steps=txt2img_config.get("steps"),
            cfg_scale=txt2img_config.get("cfg_scale"),
            width=txt2img_config.get("width"),
            height=txt2img_config.get("height"),
            seed=txt2img_config.get("seed"),
            subseed=txt2img_config.get("subseed"),
            subseed_strength=txt2img_config.get("subseed_strength"),
        )

    # Extract img2img settings (if any)
    img2img_overrides = None
    img2img_config = current_config.get("img2img", {})
    if img2img_config:
        img2img_overrides = Img2ImgOverrides(
            enabled=img2img_config.get("enabled", False),
            denoise_strength=img2img_config.get(
                "denoising_strength"
            ),  # Note: field is "denoise_strength"
        )

    # Extract upscale settings (if any)
    upscale_overrides = None
    upscale_config = current_config.get("upscale", {})
    if upscale_config:
        upscale_overrides = UpscaleOverrides(
            enabled=upscale_config.get("enabled", False),
            upscaler_name=upscale_config.get("upscaler"),  # Note: field is "upscaler_name"
            scale_factor=upscale_config.get("scale_factor"),
            denoise_strength=upscale_config.get("denoise_strength"),
        )

    # Extract refiner settings (if any)
    refiner_overrides = None
    if (
        any(key.startswith("refiner_") for key in txt2img_config.keys())
        or "use_refiner" in txt2img_config
    ):
        refiner_overrides = RefinerOverrides(
            enabled=txt2img_config.get("use_refiner", False),
            model_name=txt2img_config.get("refiner_model_name")
            or txt2img_config.get("refiner_checkpoint"),
            switch_at=txt2img_config.get("refiner_switch_at"),
        )

    # Extract hires fix settings (if any)
    hires_overrides = None
    if any(key.startswith("hr_") for key in txt2img_config.keys()) or "enable_hr" in txt2img_config:
        hires_overrides = HiresOverrides(
            enabled=txt2img_config.get("enable_hr", False),
            scale_factor=txt2img_config.get("hr_scale"),
            upscaler_name=txt2img_config.get("hr_upscaler"),
            steps=txt2img_config.get("hr_second_pass_steps"),
            denoise_strength=txt2img_config.get("denoising_strength"),
        )

    return StageOverridesBundle(
        txt2img=txt2img_overrides,
        img2img=img2img_overrides,
        upscale=upscale_overrides,
        refiner=refiner_overrides,
        hires=hires_overrides,
        adetailer=ADetailerOverrides.from_stage_config(current_config.get("adetailer") or {}),
    )


class GuiConfigService:
    """Own GUI-facing config adapter flows for AppController."""

    def get_adapter(self, app_state: Any | None) -> GuiConfigAdapterV26 | None:
        if app_state is None:
            return None
        adapter = getattr(app_state, "config_adapter", None)
        if isinstance(adapter, GuiConfigAdapterV26):
            return adapter
        return GuiConfigAdapterV26(app_state)

    def update_randomizer(
        self,
        *,
        app_state: Any | None,
        enabled: bool | None = None,
        max_variants: int | None = None,
    ) -> bool:
        adapter = self.get_adapter(app_state)
        if adapter is None:
            return False
        return adapter.set_randomizer(enabled=enabled, max_variants=max_variants)

    def apply_randomizer_from_config(
        self,
        *,
        app_state: Any | None,
        fallback_current_config: Any,
        config: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if not config:
            return {}
        fallback = fallback_current_config
        random_section = config.get("randomization") or {}
        enabled = config.get("randomization_enabled")
        if enabled is None:
            enabled = random_section.get(
                "enabled", getattr(fallback, "randomization_enabled", False)
            )
        max_variants = config.get("max_variants")
        if max_variants is None:
            max_variants = random_section.get("max_variants", getattr(fallback, "max_variants", 1))
        try:
            normalized_max = int(max_variants)
        except (TypeError, ValueError):
            normalized_max = getattr(fallback, "max_variants", 1)
        normalized_max = max(1, normalized_max)
        normalized_enabled = bool(enabled)
        fallback.randomization_enabled = normalized_enabled
        fallback.max_variants = normalized_max
        self.update_randomizer(
            app_state=app_state,
            enabled=normalized_enabled,
            max_variants=normalized_max,
        )
        return {
            "randomization_enabled": normalized_enabled,
            "max_variants": normalized_max,
        }

    def get_panel_randomizer_config(
        self,
        *,
        app_state: Any | None,
        fallback_current_config: Any | None = None,
    ) -> dict[str, Any] | None:
        adapter = self.get_adapter(app_state)
        if adapter is None:
            return None
        config = adapter.get_randomizer_config(fallback_current_config=fallback_current_config)
        return config or None

    def build_run_config_with_lora(
        self,
        *,
        app_state: Any | None,
        fallback_current_config: Any | None,
        prompt_optimizer_config: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        adapter = self.get_adapter(app_state)
        if adapter is None:
            return {}
        lora_strengths = (
            getattr(app_state, "lora_strengths", None) if app_state is not None else None
        )
        return adapter.build_submission_projection(
            lora_strengths=lora_strengths,
            prompt_optimizer_config=prompt_optimizer_config,
            fallback_current_config=fallback_current_config,
        )


__all__ = ["GuiConfigService", "PackDraftConfig", "build_stage_overrides"]
