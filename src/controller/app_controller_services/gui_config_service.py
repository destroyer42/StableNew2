from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.gui.config_adapter_v26 import GuiConfigAdapterV26


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
            enabled = random_section.get("enabled", getattr(fallback, "randomization_enabled", False))
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
        lora_strengths = getattr(app_state, "lora_strengths", None) if app_state is not None else None
        return adapter.build_submission_projection(
            lora_strengths=lora_strengths,
            prompt_optimizer_config=prompt_optimizer_config,
            fallback_current_config=fallback_current_config,
        )


__all__ = ["GuiConfigService"]
