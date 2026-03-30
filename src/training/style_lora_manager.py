from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import logging
from pathlib import Path
from typing import Any

from src.config.app_config import STABLENEW_WEBUI_ROOT
from src.config.style_lora_config import (
    DEFAULT_STYLE_LORA_CATALOG_PATH,
    StyleLoRADefinition,
    get_style_lora_definition,
    load_style_lora_definitions,
)
from src.utils.lora_scanner import LoRAScanner, get_lora_scanner


logger = logging.getLogger(__name__)


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_weight(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _infer_model_family(model_name: str | None) -> str | None:
    text = _normalize_text(model_name).lower()
    if not text:
        return None
    if "flux" in text:
        return "flux"
    if "sd3" in text or "stable diffusion 3" in text:
        return "sd3"
    if "sdxl" in text or "xl" in text:
        return "sdxl"
    if "1.5" in text or "sd15" in text or "v1-5" in text:
        return "sd15"
    return None


@dataclass(frozen=True, slots=True)
class ResolvedStyleLoRA:
    style_id: str
    display_name: str
    trigger_phrase: str
    lora_name: str
    weight: float
    file_path: str | None = None
    compatible_model_families: tuple[str, ...] = ()
    applied: bool = True
    available: bool = True
    warning: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "style_id": self.style_id,
            "display_name": self.display_name,
            "trigger_phrase": self.trigger_phrase,
            "lora_name": self.lora_name,
            "weight": self.weight,
            "file_path": self.file_path,
            "compatible_model_families": list(self.compatible_model_families),
            "applied": bool(self.applied),
            "available": bool(self.available),
            "warning": self.warning,
            "notes": self.notes,
        }


class StyleLoRAManager:
    """Loads curated style LoRA definitions and validates operator selections."""

    def __init__(
        self,
        *,
        catalog_path: str | Path = DEFAULT_STYLE_LORA_CATALOG_PATH,
        webui_root: str | Path | None = STABLENEW_WEBUI_ROOT,
    ) -> None:
        self._catalog_path = Path(catalog_path)
        self._webui_root = Path(webui_root) if webui_root else None
        self._definitions: list[StyleLoRADefinition] | None = None
        self._scanner: LoRAScanner | None = None
        self._scanner_ready = False

    def list_styles(self) -> list[StyleLoRADefinition]:
        return list(self._load_definitions())

    def get_style(self, style_id: str) -> StyleLoRADefinition:
        return get_style_lora_definition(style_id, catalog_path=self._catalog_path)

    def resolve_selection(
        self,
        selection: Mapping[str, Any] | str | None,
        *,
        base_model: str | None = None,
    ) -> ResolvedStyleLoRA | None:
        if isinstance(selection, str):
            payload = {"style_id": selection}
        else:
            payload = _mapping_dict(selection)

        enabled = bool(payload.get("enabled", True))
        style_id = _normalize_text(
            payload.get("style_id")
            or payload.get("id")
            or payload.get("name")
        )
        if not enabled or not style_id or style_id.lower() in {"none", "(none)"}:
            return None

        try:
            definition = self.get_style(style_id)
        except KeyError:
            return ResolvedStyleLoRA(
                style_id=style_id,
                display_name=style_id,
                trigger_phrase="",
                lora_name="",
                weight=_normalize_weight(payload.get("weight"), default=0.65),
                applied=False,
                available=False,
                warning=(
                    f"Style LoRA '{style_id}' is not defined in {self._catalog_path}."
                ),
            )

        resolved = ResolvedStyleLoRA(
            style_id=definition.style_id,
            display_name=definition.display_name,
            trigger_phrase=definition.trigger_phrase,
            lora_name=definition.lora_name,
            weight=_normalize_weight(payload.get("weight"), default=definition.weight),
            file_path=definition.file_path,
            compatible_model_families=definition.compatible_model_families,
            notes=definition.notes,
        )

        model_warning = self._validate_model_compatibility(definition, base_model)
        if model_warning:
            return replace(
                resolved,
                applied=False,
                available=False,
                warning=model_warning,
            )

        availability_warning = self._validate_availability(definition)
        if availability_warning:
            return replace(
                resolved,
                applied=False,
                available=False,
                warning=availability_warning,
            )

        return resolved

    def _load_definitions(self) -> list[StyleLoRADefinition]:
        if self._definitions is not None:
            return self._definitions
        try:
            self._definitions = load_style_lora_definitions(self._catalog_path)
        except Exception as exc:
            logger.warning("Failed to load style LoRA catalog '%s': %s", self._catalog_path, exc)
            self._definitions = []
        return self._definitions

    def _validate_model_compatibility(
        self,
        definition: StyleLoRADefinition,
        base_model: str | None,
    ) -> str | None:
        if not definition.compatible_model_families:
            return None
        resolved_family = _infer_model_family(base_model)
        if not resolved_family:
            return None
        if resolved_family in definition.compatible_model_families:
            return None
        allowed = ", ".join(definition.compatible_model_families)
        return (
            f"Style LoRA '{definition.display_name}' targets {allowed}, but the current base model "
            f"looks like {resolved_family}. StableNew skipped the style LoRA to avoid a mismatch."
        )

    def _validate_availability(self, definition: StyleLoRADefinition) -> str | None:
        if definition.file_path:
            file_path = Path(definition.file_path).expanduser()
            if file_path.exists() and file_path.is_file():
                return None
            return (
                f"Style LoRA '{definition.display_name}' is configured with a missing weight file: {file_path}"
            )

        scanner = self._get_scanner()
        if scanner is None:
            return (
                f"Style LoRA '{definition.display_name}' could not be validated because no WebUI root is configured "
                "and no explicit file_path was supplied."
            )

        if scanner.get_lora_info(definition.lora_name) is not None:
            return None
        return (
            f"Style LoRA '{definition.display_name}' was not found in the configured WebUI LoRA directories."
        )

    def _get_scanner(self) -> LoRAScanner | None:
        if self._webui_root is None:
            return None
        if self._scanner is None:
            self._scanner = get_lora_scanner(self._webui_root)
        if not self._scanner_ready:
            try:
                self._scanner.scan_loras()
            except Exception as exc:
                logger.warning("Failed to scan LoRA directories for style validation: %s", exc)
            finally:
                self._scanner_ready = True
        return self._scanner


__all__ = ["ResolvedStyleLoRA", "StyleLoRAManager"]