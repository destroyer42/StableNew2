"""Per-stage prompt provenance of a Review image (PR-REVIEW-LIFECYCLE-621).

Every stage records the prompt it was given (``original``) and the prompt it actually sent after the prompt optimizer
(``final``). Review used to collapse the two and re-work started from the optimized text, which each later stage then
optimized again. This module projects both, per stage, from the embedded payload, marks what was not recorded, says
which prompt a re-work starts from, and redacts everything through the shared content-visibility policy.

Tk-free and read-only: it reads an already extracted payload and never touches a file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.utils.image_metadata import (
    BASELINE_AS_SENT,
    BASELINE_ORIGINAL,
    resolve_rework_baseline,
)

NOT_RECORDED = "not recorded"
#: The image carries no prompt at all, so a re-work has nothing to start from.
BASELINE_NONE = "not_recorded"


@dataclass(frozen=True)
class StagePromptView:
    """One stage's prompts; ``None`` means the payload did not record that value."""

    stage: str
    original: str | None = None
    final: str | None = None
    negative_original: str | None = None
    negative_final: str | None = None
    #: True for the stage that produced this image (the others are earlier stages in its history).
    current: bool = False


@dataclass(frozen=True)
class EffectivePromptView:
    stages: tuple[StagePromptView, ...]
    #: The ADetailer stage's prompts, or ``None`` when no ADetailer stage was recorded for the image.
    adetailer: StagePromptView | None
    baseline_prompt: str
    baseline_negative: str
    #: ``original``, ``as_sent`` or ``not_recorded``.
    baseline_basis: str

    @property
    def baseline_label(self) -> str:
        return baseline_label(self.baseline_basis)


def baseline_label(basis: str) -> str:
    if basis == BASELINE_ORIGINAL:
        return "the original prompt"
    if basis == BASELINE_AS_SENT:
        return "the prompt as sent (no original was recorded)"
    return "nothing: no prompt was recorded"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _stage_view(entry: Mapping[str, Any], *, current: bool) -> StagePromptView:
    return StagePromptView(
        stage=str(entry.get("stage") or entry.get("name") or "stage").strip() or "stage",
        original=_text(entry.get("original_prompt")),
        final=_text(entry.get("final_prompt"), entry.get("prompt")),
        negative_original=_text(entry.get("original_negative_prompt")),
        negative_final=_text(entry.get("final_negative_prompt"), entry.get("negative_prompt")),
        current=current,
    )


def project_effective_prompts(payload: Mapping[str, Any] | None) -> EffectivePromptView:
    """Per-stage original and final prompts of an embedded payload, in pipeline order (current stage last)."""

    data = _mapping(payload)
    views: list[StagePromptView] = []
    history = data.get("stage_history")
    for entry in history if isinstance(history, list) else []:
        if isinstance(entry, Mapping):
            views.append(_stage_view(entry, current=False))
    manifest = _mapping(data.get("stage_manifest"))
    if manifest:
        current = _stage_view({"stage": data.get("stage"), **manifest}, current=True)
        # The current stage can already end the recorded history; show it once, as the current stage.
        if views and (views[-1].stage, views[-1].original, views[-1].final) == (
            current.stage,
            current.original,
            current.final,
        ):
            views.pop()
        views.append(current)
    baseline = resolve_rework_baseline(dict(data)) if data else None
    prompt = baseline.prompt if baseline else ""
    basis = baseline.prompt_basis if baseline and prompt else BASELINE_NONE
    ad = next((view for view in reversed(views) if view.stage.lower() == "adetailer"), None)
    return EffectivePromptView(
        stages=tuple(views),
        adetailer=ad,
        baseline_prompt=prompt,
        baseline_negative=baseline.negative_prompt if baseline else "",
        baseline_basis=basis,
    )


def redact_view(
    view: EffectivePromptView, resolver: ContentVisibilityResolver, subject: Mapping[str, Any]
) -> EffectivePromptView:
    """The same view with every prompt passed through the content-visibility policy (SFW hides explicit text)."""

    def hide(value: str | None) -> str | None:
        return None if value is None else resolver.redact_text(value, item=dict(subject))

    def hide_stage(stage: StagePromptView | None) -> StagePromptView | None:
        if stage is None:
            return None
        return StagePromptView(
            stage=stage.stage,
            original=hide(stage.original),
            final=hide(stage.final),
            negative_original=hide(stage.negative_original),
            negative_final=hide(stage.negative_final),
            current=stage.current,
        )

    return EffectivePromptView(
        stages=tuple(hide_stage(stage) for stage in view.stages if stage is not None),  # type: ignore[misc]
        adetailer=hide_stage(view.adetailer),
        baseline_prompt=hide(view.baseline_prompt) or "",
        baseline_negative=hide(view.baseline_negative) or "",
        baseline_basis=view.baseline_basis,
    )


def _shown(value: str | None) -> str:
    return NOT_RECORDED if value is None else value


def format_stage(stage: StagePromptView) -> str:
    label = f"{stage.stage}{' (this image)' if stage.current else ''}"
    return "\n".join(
        (
            label,
            f"  original: {_shown(stage.original)}",
            f"  final:    {_shown(stage.final)}",
            f"  negative, original: {_shown(stage.negative_original)}",
            f"  negative, final:    {_shown(stage.negative_final)}",
        )
    )


def format_provenance(view: EffectivePromptView) -> str:
    """The Review provenance panel text for an (already redacted) view."""

    lines = [f"Re-work starts from {view.baseline_label}."]
    if not view.stages:
        lines.append("Prompts: not recorded")
    for stage in view.stages:
        lines.append(format_stage(stage))
    lines.append(
        "ADetailer: not recorded" if view.adetailer is None else "ADetailer prompts shown above."
    )
    return "\n".join(lines)


__all__ = [
    "BASELINE_NONE",
    "EffectivePromptView",
    "NOT_RECORDED",
    "StagePromptView",
    "baseline_label",
    "format_provenance",
    "format_stage",
    "project_effective_prompts",
    "redact_view",
]
