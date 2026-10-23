"""Toolkit-neutral presentation of the cinematic template editor (GUI-540).

Rendering stays with ``compose_prompt_text``; this module only labels templates, chooses editable starting values and
splits the authored preview into the parts an operator needs to see. Nothing here reads or writes a PromptPack.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.utils.prompt_templates import PromptTemplateDefinition, compose_prompt_text

NO_TEMPLATE_LABEL = "(No template)"
EXAMPLE_NOTE = (
    "Starting values are examples, not part of your pack until you keep or change them. "
    "Replace them with your own details."
)


@dataclass(frozen=True)
class TemplateChoice:
    template_id: str
    label: str


def _category_text(category: str) -> str:
    return category.replace("_", " ").strip().title()


def template_choices(
    definitions: Sequence[PromptTemplateDefinition], saved_template_id: str = ""
) -> list[TemplateChoice]:
    """Friendly selector entries; the stable ``template_id`` is what is stored.

    A saved id that is not in the catalog stays selectable (and therefore visible) so it is never silently discarded.
    """

    choices = [TemplateChoice("", NO_TEMPLATE_LABEL)]
    known: set[str] = set()
    for definition in definitions:
        known.add(definition.id)
        choices.append(
            TemplateChoice(
                definition.id, f"{definition.label} — {_category_text(definition.category)}"
            )
        )
    saved = str(saved_template_id or "").strip()
    if saved and saved not in known:
        choices.append(TemplateChoice(saved, f"{saved} — not in catalog (kept as saved)"))
    return choices


def template_guidance(definition: PromptTemplateDefinition | None, template_id: str) -> str:
    """The operator-facing purpose of the selected template, from the catalog's own label and description."""

    if not template_id:
        return "No template selected. Use the editor above for full freeform prompts."
    if definition is None:
        return (
            f"Template '{template_id}' is not in the template catalog. It is kept as saved, but nothing is "
            "rendered from it; only the freeform text contributes to the prompt."
        )
    text = f"{definition.label} ({_category_text(definition.category)})."
    if definition.description:
        text += f" {definition.description}"
    if definition.placeholders:
        names = ", ".join(name.replace("_", " ") for name in definition.placeholders)
        text += f" Fields: {names}."
    return text


def seed_template_values(
    definition: PromptTemplateDefinition | None, current_values: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """(values, seeded) for a deliberate template choice.

    Non-empty values the operator already has are kept; only empty fields receive the catalog's example. ``seeded``
    names exactly the fields that now hold an example, so the editor can label them as such.
    """

    if definition is None:
        return {}, {}
    examples = definition.example_values
    values: dict[str, str] = {}
    seeded: dict[str, str] = {}
    for placeholder in definition.placeholders:
        existing = str(current_values.get(placeholder, "") or "").strip()
        if existing:
            values[placeholder] = existing
        elif placeholder in examples:
            values[placeholder] = examples[placeholder]
            seeded[placeholder] = examples[placeholder]
        else:
            values[placeholder] = ""
    return values, seeded


@dataclass(frozen=True)
class TemplatePreview:
    """The authored prompt and where its parts come from (before any model-target adaptation)."""

    authored_text: str
    template_text: str
    freeform_text: str
    unfilled: tuple[str, ...]
    template_known: bool


def build_template_preview(
    template_id: str,
    values: Mapping[str, str],
    freeform_text: str,
    definitions: Mapping[str, PromptTemplateDefinition],
) -> TemplatePreview:
    key = str(template_id or "").strip()
    freeform = str(freeform_text or "").strip()
    definition = definitions.get(key) if key else None
    template_text = compose_prompt_text(key, values, "") if definition is not None else ""
    unfilled: tuple[str, ...] = ()
    if definition is not None:
        unfilled = tuple(
            name for name in definition.placeholders if not str(values.get(name, "") or "").strip()
        )
    return TemplatePreview(
        authored_text=compose_prompt_text(key, values, freeform),
        template_text=template_text,
        freeform_text=freeform,
        unfilled=unfilled,
        template_known=definition is not None or not key,
    )


def preview_breakdown(preview: TemplatePreview, template_id: str) -> str:
    """Short lines saying what the template and the freeform text each contribute."""

    if not template_id:
        return "No template: the prompt is your freeform text."
    lines: list[str] = []
    if not preview.template_known:
        lines.append("Template: not in the catalog, so it adds nothing to the prompt.")
    elif preview.template_text:
        lines.append(f"Template adds: {preview.template_text}")
    if preview.unfilled:
        lines.append(
            "Empty fields: " + ", ".join(name.replace("_", " ") for name in preview.unfilled)
        )
    lines.append(
        f"Freeform text adds: {preview.freeform_text}"
        if preview.freeform_text
        else "Freeform text adds: nothing"
    )
    return "\n".join(lines)


__all__ = [
    "EXAMPLE_NOTE",
    "NO_TEMPLATE_LABEL",
    "TemplateChoice",
    "TemplatePreview",
    "build_template_preview",
    "preview_breakdown",
    "seed_template_values",
    "template_choices",
    "template_guidance",
]
