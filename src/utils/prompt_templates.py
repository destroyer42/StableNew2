from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any, cast

DEFAULT_PROMPT_TEMPLATE_PATH = Path("data") / "prompt_templates.json"

_FALLBACK_PROMPT_TEMPLATE_PAYLOAD: dict[str, Any] = {
    "version": 1,
    "templates": {
        "establishing_wide": {
            "label": "Establishing Wide Shot",
            "category": "shot",
            "template": "cinematic wide establishing shot of {scene}, {environment}, {lighting}, {style}",
            "description": "Use for scene-setting openers and location reveals.",
            "examples": {
                "scene": "a lone knight arriving at an ancient fortress",
                "environment": "mist-covered stone walls and a mountain valley",
                "lighting": "warm golden-hour backlighting",
                "style": "cinematic realism",
            },
        },
        "character_close_up": {
            "label": "Character Close-Up",
            "category": "portrait",
            "template": "intimate close-up of {subject}, {expression}, {lighting}, {style}",
            "description": "Use for emotional beats and performance-driven framing.",
            "examples": {
                "subject": "a weathered sea captain",
                "expression": "quiet determination",
                "lighting": "soft window light",
                "style": "cinematic realism",
            },
        },
        "over_the_shoulder": {
            "label": "Over-The-Shoulder",
            "category": "coverage",
            "template": "over-the-shoulder shot of {subject} facing {focus}, {environment}, {lighting}",
            "description": "Use for dialogue, reveals, and guided audience focus.",
            "examples": {
                "subject": "a detective",
                "focus": "a rain-streaked apartment window",
                "environment": "a dim city apartment at night",
                "lighting": "cool neon spill",
            },
        },
        "tracking_action": {
            "label": "Tracking Action Shot",
            "category": "action",
            "template": "tracking shot of {subject} {action}, {environment}, {camera}, {style}",
            "description": "Use for motion-heavy beats with cinematic camera language.",
            "examples": {
                "subject": "a courier",
                "action": "sprinting across rooftops",
                "environment": "a dense city skyline at dusk",
                "camera": "low tracking angle, shallow depth of field",
                "style": "cinematic realism",
            },
        },
        "moody_portrait": {
            "label": "Moody Portrait",
            "category": "portrait",
            "template": "moody portrait of {subject}, {environment}, {lighting}, {mood}, {style}",
            "description": "Use for stylized character portraiture with strong atmosphere.",
            "examples": {
                "subject": "a young violinist",
                "environment": "an empty concert hall",
                "lighting": "a single warm spotlight",
                "mood": "melancholic and reflective",
                "style": "painterly realism",
            },
        },
        "aerial_reveal": {
            "label": "Aerial Reveal",
            "category": "shot",
            "template": "dramatic aerial reveal of {scene}, {environment}, {lighting}, {mood}",
            "description": "Use for scale, geography, and cinematic reveal moments.",
            "examples": {
                "scene": "a hidden valley city",
                "environment": "terraced cliffs and winding rivers",
                "lighting": "early morning haze",
                "mood": "awe and discovery",
            },
        },
    },
}

_PROMPT_TEMPLATE_CACHE: dict[str, tuple[int | None, dict[str, PromptTemplateDefinition]]] = {}


@dataclass(frozen=True)
class PromptTemplateDefinition:
    id: str
    label: str
    category: str
    template: str
    description: str = ""
    #: Optional editable starting values keyed by placeholder (presentation only; never stored with a pack).
    examples: tuple[tuple[str, str], ...] = ()

    @property
    def placeholders(self) -> tuple[str, ...]:
        return extract_template_placeholders(self)

    @property
    def example_values(self) -> dict[str, str]:
        return dict(self.examples)


class _PartialTemplateValues(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def clear_prompt_template_cache() -> None:
    _PROMPT_TEMPLATE_CACHE.clear()


def _default_prompt_template_payload() -> dict[str, Any]:
    return cast(dict[str, Any], deepcopy(_FALLBACK_PROMPT_TEMPLATE_PAYLOAD))


def _normalize_examples(raw_examples: Any, template_text: str) -> tuple[tuple[str, str], ...]:
    """Keep non-empty example strings for placeholders the template really has; anything else is ignored."""

    if not isinstance(raw_examples, Mapping):
        return ()
    placeholders = extract_template_placeholders(template_text)
    examples: list[tuple[str, str]] = []
    for placeholder in placeholders:
        value = raw_examples.get(placeholder)
        text = value.strip() if isinstance(value, str) else ""
        if text:
            examples.append((placeholder, text))
    return tuple(examples)


def _normalize_template_definition(
    template_id: str, raw_definition: Mapping[str, Any]
) -> PromptTemplateDefinition:
    template_text = str(raw_definition.get("template") or "").strip()
    if not template_text:
        raise ValueError(f"Prompt template '{template_id}' must define a non-empty template string")

    return PromptTemplateDefinition(
        id=template_id,
        label=str(raw_definition.get("label") or template_id).strip() or template_id,
        category=str(raw_definition.get("category") or "general").strip() or "general",
        template=template_text,
        description=str(raw_definition.get("description") or "").strip(),
        examples=_normalize_examples(raw_definition.get("examples"), template_text),
    )


def _load_prompt_template_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_prompt_template_payload()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse prompt template file '{path}': {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Failed to read prompt template file '{path}': {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Prompt template payload must be a JSON object")
    return cast(dict[str, Any], payload)


def _parse_prompt_templates(payload: Mapping[str, Any]) -> dict[str, PromptTemplateDefinition]:
    raw_templates = payload.get("templates", payload)
    if not isinstance(raw_templates, Mapping):
        raise ValueError("Prompt template payload must contain a 'templates' object")

    templates: dict[str, PromptTemplateDefinition] = {}
    for raw_id, raw_definition in raw_templates.items():
        template_id = str(raw_id or "").strip()
        if not template_id:
            raise ValueError("Prompt template ids must be non-empty strings")
        if not isinstance(raw_definition, Mapping):
            raise ValueError(f"Prompt template '{template_id}' must be an object")
        templates[template_id] = _normalize_template_definition(template_id, raw_definition)

    if not templates:
        raise ValueError("Prompt template payload must define at least one template")

    return templates


def load_prompt_templates(
    path: Path | str | None = None,
) -> dict[str, PromptTemplateDefinition]:
    resolved_path = Path(path) if path is not None else DEFAULT_PROMPT_TEMPLATE_PATH
    cache_key = str(resolved_path.resolve())
    mtime = resolved_path.stat().st_mtime_ns if resolved_path.exists() else None
    cached = _PROMPT_TEMPLATE_CACHE.get(cache_key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    payload = _load_prompt_template_payload(resolved_path)
    if not isinstance(payload, Mapping):
        raise ValueError("Prompt template payload must be a JSON object")

    templates = _parse_prompt_templates(payload)
    _PROMPT_TEMPLATE_CACHE[cache_key] = (mtime, templates)
    return templates


def list_prompt_templates(
    path: Path | str | None = None,
) -> list[PromptTemplateDefinition]:
    return sorted(
        load_prompt_templates(path).values(),
        key=lambda definition: (definition.category, definition.label, definition.id),
    )


def get_prompt_template(
    template_id: str, path: Path | str | None = None
) -> PromptTemplateDefinition:
    template_key = str(template_id or "").strip()
    if not template_key:
        raise ValueError("Prompt template id is required")

    try:
        return load_prompt_templates(path)[template_key]
    except KeyError as exc:
        raise ValueError(f"Unknown prompt template '{template_key}'") from exc


def extract_template_placeholders(
    template: PromptTemplateDefinition | str,
) -> tuple[str, ...]:
    template_text = (
        template.template if isinstance(template, PromptTemplateDefinition) else str(template)
    )
    placeholders: list[str] = []
    seen: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template_text):
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        placeholders.append(field_name)
    return tuple(placeholders)


def _normalize_template_values(values: Mapping[str, Any] | None) -> dict[str, str]:
    if not values:
        return {}

    normalized: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        normalized[key] = "" if raw_value is None else str(raw_value).strip()
    return normalized


def apply_prompt_template(
    template: PromptTemplateDefinition | str,
    values: Mapping[str, Any] | None = None,
    *,
    strict: bool = True,
) -> str:
    definition = template if isinstance(template, PromptTemplateDefinition) else None
    template_text = definition.template if definition is not None else str(template)
    normalized_values = _normalize_template_values(values)
    missing = [
        placeholder
        for placeholder in extract_template_placeholders(definition or template_text)
        if placeholder not in normalized_values
    ]
    if strict and missing:
        raise ValueError(f"Missing prompt template values: {', '.join(missing)}")

    if strict:
        return template_text.format(**normalized_values).strip()
    return template_text.format_map(_PartialTemplateValues(normalized_values)).strip()


def compose_prompt_text(
    template_id: str | None,
    template_values: Mapping[str, Any] | None = None,
    freeform_text: str = "",
    *,
    path: Path | str | None = None,
    strict: bool = False,
) -> str:
    parts: list[str] = []
    template_key = str(template_id or "").strip()
    if template_key:
        try:
            definition = get_prompt_template(template_key, path)
            rendered = apply_prompt_template(definition, template_values, strict=strict)
        except ValueError:
            if strict:
                raise
            rendered = ""
        if rendered:
            parts.append(rendered)

    extra_text = str(freeform_text or "").strip()
    if extra_text and (not parts or parts[-1] != extra_text):
        parts.append(extra_text)

    return ", ".join(part for part in parts if part).strip(" ,")


__all__ = [
    "DEFAULT_PROMPT_TEMPLATE_PATH",
    "PromptTemplateDefinition",
    "apply_prompt_template",
    "clear_prompt_template_cache",
    "compose_prompt_text",
    "extract_template_placeholders",
    "get_prompt_template",
    "list_prompt_templates",
    "load_prompt_templates",
]
