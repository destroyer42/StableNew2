"""Operator-facing grouping and summaries for the Pipeline composer (PR-GUI-UX-530). No Tk, no state.

The Pipeline sidebar presents the canonical stage flags (``txt2img``, ``img2img``, ``adetailer``,
``upscale``) as a task-oriented composer: *Generate* a new image, optionally *Improve Result*, and a
collapsed *Advanced and legacy* area. This module only names those groups and words their summaries. It
never decides which stages run: stage enablement stays in the sidebar stage flags and the compiler.
"""

from __future__ import annotations

from collections.abc import Iterable

GENERATE_STAGE = "txt2img"
IMPROVE_STAGES: tuple[str, ...] = ("adetailer", "upscale")
LEGACY_STAGES: tuple[str, ...] = ("img2img",)

GROUP_GENERATE = "Generate"
GROUP_IMPROVE = "Improve Result (optional)"
GROUP_ADVANCED = "Advanced and legacy stages"

COMPOSER_INTRO = (
    "Create a new image: pick PromptPacks and a model, optionally improve the result, "
    "then Preview and Add to Queue. To edit an image you already have, use Review or Photo Optimize."
)

# Checkbox label and one-sentence operator help per stage.
STAGE_LABELS: dict[str, str] = {
    "txt2img": "Create a new image (txt2img)",
    "adetailer": "Fix faces and details (ADetailer)",
    "upscale": "Enlarge the result (Upscale)",
    "img2img": "Run the legacy img2img pass",
}
STAGE_HELP: dict[str, str] = {
    "txt2img": "Makes a new image from each selected PromptPack prompt using the model settings below.",
    "adetailer": "After the image is made, redraws detected faces or details to clean them up.",
    "upscale": "Makes the finished image larger with the upscaler chosen in the Upscale card. Adds time per image.",
    "img2img": (
        "An image-to-image pass kept for saved configurations. "
        "It is not part of normal Create; to edit an existing image use Review or Photo Optimize."
    ),
}

LEGACY_IMG2IMG_ON = (
    "This configuration includes an img2img stage. It stays enabled until you turn it off here."
)
LEGACY_IMG2IMG_OFF = "No legacy stage is enabled. New images start with txt2img."

LEGACY_IMG2IMG_CARD_DESCRIPTION = (
    "Legacy stage from a saved configuration. For existing images use Review."
)

REVIEW_HANDOFF_TITLE = "Edit or Reprocess Existing Image"
REVIEW_HANDOFF_MISSING = "Could not open the Review tab. Open Review from the tab bar, then choose the image to edit there."


def stage_group(stage: str) -> str:
    """Composer group for ``stage``: ``generate``, ``improve`` or ``legacy`` (unknown stages are legacy)."""

    if stage == GENERATE_STAGE:
        return "generate"
    if stage in IMPROVE_STAGES:
        return "improve"
    return "legacy"


def legacy_stage_status(enabled_stages: Iterable[str]) -> tuple[str, bool]:
    """(collapsed-header status, active) for the *Advanced and legacy stages* section."""

    active = [stage for stage in LEGACY_STAGES if stage in set(enabled_stages)]
    if active:
        return (", ".join(f"{name} ON" for name in active), True)
    return ("none enabled", False)


def legacy_stage_notice(enabled_stages: Iterable[str]) -> str:
    return LEGACY_IMG2IMG_ON if "img2img" in set(enabled_stages) else LEGACY_IMG2IMG_OFF


def advanced_generation_status(*, refiner_enabled: bool, hires_enabled: bool) -> tuple[str, bool]:
    """(collapsed-header status, active) for the txt2img *Refiner and Hires fix* section."""

    enabled = [
        name for name, on in (("Refiner", refiner_enabled), ("Hires fix", hires_enabled)) if on
    ]
    if enabled:
        return (", ".join(f"{name} ON" for name in enabled), True)
    return ("both off", False)


__all__ = [
    "COMPOSER_INTRO",
    "GENERATE_STAGE",
    "GROUP_ADVANCED",
    "GROUP_GENERATE",
    "GROUP_IMPROVE",
    "IMPROVE_STAGES",
    "LEGACY_IMG2IMG_CARD_DESCRIPTION",
    "LEGACY_IMG2IMG_OFF",
    "LEGACY_IMG2IMG_ON",
    "LEGACY_STAGES",
    "REVIEW_HANDOFF_MISSING",
    "REVIEW_HANDOFF_TITLE",
    "STAGE_HELP",
    "STAGE_LABELS",
    "advanced_generation_status",
    "legacy_stage_notice",
    "legacy_stage_status",
    "stage_group",
]
