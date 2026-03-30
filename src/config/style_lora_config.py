from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STYLE_LORA_CATALOG_PATH = Path("data") / "style_loras.json"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_text(value: Any) -> str | None:
    text = _normalize_text(value)
    return text or None


def _normalize_weight(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _normalize_family_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = list(value)
    else:
        values = []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _normalize_text(item).lower()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class StyleLoRADefinition:
    style_id: str
    display_name: str
    trigger_phrase: str
    lora_name: str
    weight: float = 0.65
    file_path: str | None = None
    compatible_model_families: tuple[str, ...] = ()
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
            "notes": self.notes,
        }


def load_style_lora_definitions(
    catalog_path: str | Path = DEFAULT_STYLE_LORA_CATALOG_PATH,
) -> list[StyleLoRADefinition]:
    path = Path(catalog_path)
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("styles") if isinstance(payload, Mapping) else payload
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
        return []

    definitions: list[StyleLoRADefinition] = []
    seen: set[str] = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            continue
        style_id = _normalize_text(
            raw_entry.get("style_id")
            or raw_entry.get("id")
            or raw_entry.get("name")
        )
        if not style_id:
            continue
        lowered_id = style_id.lower()
        if lowered_id in seen:
            continue

        file_path = _normalize_optional_text(raw_entry.get("file_path"))
        lora_name = _normalize_text(raw_entry.get("lora_name"))
        if not lora_name and file_path:
            lora_name = Path(file_path).stem
        trigger_phrase = _normalize_text(raw_entry.get("trigger_phrase") or raw_entry.get("trigger_token"))
        if not lora_name or not trigger_phrase:
            continue

        definitions.append(
            StyleLoRADefinition(
                style_id=style_id,
                display_name=_normalize_text(raw_entry.get("display_name") or style_id),
                trigger_phrase=trigger_phrase,
                lora_name=lora_name,
                weight=_normalize_weight(raw_entry.get("weight"), default=0.65),
                file_path=file_path,
                compatible_model_families=_normalize_family_list(
                    raw_entry.get("compatible_model_families")
                    or raw_entry.get("base_model_family")
                ),
                notes=_normalize_text(raw_entry.get("notes")),
            )
        )
        seen.add(lowered_id)
    return definitions


def get_style_lora_definition(
    style_id: str,
    catalog_path: str | Path = DEFAULT_STYLE_LORA_CATALOG_PATH,
) -> StyleLoRADefinition:
    target = _normalize_text(style_id).lower()
    for definition in load_style_lora_definitions(catalog_path):
        if definition.style_id.lower() == target:
            return definition
    raise KeyError(f"Unknown style LoRA '{style_id}'")


__all__ = [
    "DEFAULT_STYLE_LORA_CATALOG_PATH",
    "StyleLoRADefinition",
    "get_style_lora_definition",
    "load_style_lora_definitions",
]