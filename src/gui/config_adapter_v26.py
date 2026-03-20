from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from src.pipeline.config_contract_v26 import (
    CONFIG_CONTRACT_SCHEMA_V26,
    attach_config_layers,
    build_config_layers,
)

if TYPE_CHECKING:  # pragma: no cover
    from src.gui.app_state_v2 import AppStateV2, PackJobEntry


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    return {}


class GuiConfigAdapterV26:
    """Stable GUI-facing facade over canonical config layers.

    The adapter does not introduce a new config model. It keeps the existing
    `run_config` projection available for GUI compatibility while treating
    `intent_config`, `execution_config`, and `backend_options` as canonical.
    """

    def __init__(self, app_state: AppStateV2) -> None:
        self._app_state = app_state

    def get_run_config_projection(self) -> dict[str, Any]:
        direct = _mapping_dict(getattr(self._app_state, "run_config", {}))
        if direct:
            return direct
        layers = self._derive_layers_from_state()
        return self._build_projection_from_layers(layers)

    def get_intent_config(self) -> dict[str, Any]:
        direct = _mapping_dict(getattr(self._app_state, "intent_config", {}))
        if direct:
            return direct
        return _mapping_dict(self._derive_layers_from_state().get("intent_config"))

    def get_execution_config(self) -> dict[str, Any]:
        direct = _mapping_dict(getattr(self._app_state, "execution_config", {}))
        if direct:
            return direct
        return _mapping_dict(self._derive_layers_from_state().get("execution_config"))

    def get_backend_options(self) -> dict[str, Any]:
        direct = _mapping_dict(getattr(self._app_state, "backend_options", {}))
        if direct:
            return direct
        return _mapping_dict(self._derive_layers_from_state().get("backend_options"))

    def get_config_layers(self) -> dict[str, Any]:
        return {
            "schema": CONFIG_CONTRACT_SCHEMA_V26,
            "intent_config": self.get_intent_config(),
            "execution_config": self.get_execution_config(),
            "backend_options": self.get_backend_options(),
        }

    def apply_run_config(self, value: Mapping[str, Any] | None) -> bool:
        if value is None:
            return False
        normalized = _mapping_dict(value)
        backend_seed = normalized.get("backend_options")
        layers = build_config_layers(
            intent_config=normalized,
            execution_config=normalized,
            backend_options=backend_seed,
        )
        projection = self._build_projection_from_layers(layers.to_dict(), seed_payload=normalized)
        changed = False
        if getattr(self._app_state, "run_config", None) != projection:
            self._app_state.run_config = projection
            changed = True
        if getattr(self._app_state, "intent_config", None) != layers.intent_config:
            self._app_state.intent_config = dict(layers.intent_config)
            changed = True
        if getattr(self._app_state, "execution_config", None) != layers.execution_config:
            self._app_state.execution_config = dict(layers.execution_config)
            changed = True
        if getattr(self._app_state, "backend_options", None) != layers.backend_options:
            self._app_state.backend_options = dict(layers.backend_options)
            changed = True
        return changed

    def update_projection(self, patch: Mapping[str, Any] | None) -> bool:
        if patch is None:
            return False
        merged = self.get_run_config_projection()
        merged.update(_mapping_dict(patch))
        return self.apply_run_config(merged)

    def get_randomizer_config(self, *, fallback_current_config: Any | None = None) -> dict[str, Any]:
        projection = self.get_run_config_projection()
        enabled = projection.get("randomization_enabled")
        max_variants = projection.get("max_variants")
        if enabled is None and fallback_current_config is not None:
            enabled = getattr(fallback_current_config, "randomization_enabled", False)
        if max_variants is None and fallback_current_config is not None:
            max_variants = getattr(fallback_current_config, "max_variants", 1)
        if enabled is None and max_variants is None:
            return {}
        try:
            normalized_max = int(max_variants or 1)
        except (TypeError, ValueError):
            normalized_max = 1
        return {
            "randomization_enabled": bool(enabled),
            "max_variants": max(1, normalized_max),
        }

    def set_randomizer(
        self,
        *,
        enabled: bool | None = None,
        max_variants: int | None = None,
    ) -> bool:
        patch: dict[str, Any] = {}
        if enabled is not None:
            patch["randomization_enabled"] = bool(enabled)
        if max_variants is not None:
            patch["max_variants"] = max(1, int(max_variants))
        if not patch:
            return False
        return self.update_projection(patch)

    def build_submission_projection(
        self,
        *,
        lora_strengths: list[Any] | None = None,
        prompt_optimizer_config: Mapping[str, Any] | None = None,
        fallback_current_config: Any | None = None,
    ) -> dict[str, Any]:
        projection = self.get_run_config_projection()
        if lora_strengths:
            projection["lora_strengths"] = [
                item.to_dict() if hasattr(item, "to_dict") else _mapping_dict(item)
                for item in lora_strengths
            ]
        if prompt_optimizer_config is not None:
            projection["prompt_optimizer"] = _mapping_dict(prompt_optimizer_config)
        randomizer = self.get_randomizer_config(fallback_current_config=fallback_current_config)
        for key, value in randomizer.items():
            projection.setdefault(key, value)
        return projection

    def resolve_prompt_pack_context(self) -> tuple[str, str]:
        selected_pack_id = str(getattr(self._app_state, "selected_prompt_pack_id", "") or "").strip()
        if selected_pack_id:
            return "pack", selected_pack_id
        job_draft = getattr(self._app_state, "job_draft", None)
        draft_pack_id = str(getattr(job_draft, "pack_id", "") or "").strip()
        if draft_pack_id:
            return "pack", draft_pack_id
        pack_entries = getattr(job_draft, "packs", None) or []
        for entry in pack_entries:
            pack_id = str(getattr(entry, "pack_id", "") or "").strip()
            if pack_id:
                return "pack", pack_id
        return "manual", ""

    def _build_projection_from_layers(
        self,
        layers: Mapping[str, Any],
        *,
        seed_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent = _mapping_dict(layers.get("intent_config"))
        execution = _mapping_dict(layers.get("execution_config"))
        backend = _mapping_dict(layers.get("backend_options"))
        projection: dict[str, Any] = {}
        if seed_payload is not None:
            projection.update(
                {
                    key: deepcopy(value)
                    for key, value in dict(seed_payload).items()
                    if key
                    not in {
                        "config_schema",
                        "config_layers",
                        "intent_config",
                        "execution_config",
                        "backend_options",
                    }
                }
            )
        projection.update(intent)
        projection.update(execution)
        if backend:
            projection["backend_options"] = backend
        return attach_config_layers(
            projection,
            intent_config=intent,
            execution_config=execution,
            backend_options=backend,
        )

    def _derive_layers_from_state(self) -> dict[str, Any]:
        direct = _mapping_dict(getattr(self._app_state, "run_config", {}))
        derived = build_config_layers(
            intent_config=direct,
            execution_config=direct,
            backend_options=getattr(self._app_state, "backend_options", {}),
        )
        return derived.to_dict()


__all__ = ["GuiConfigAdapterV26"]
