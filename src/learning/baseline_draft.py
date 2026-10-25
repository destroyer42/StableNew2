"""The editable Learning baseline draft: lifecycle rules over ``LearningState.baseline_draft``.

The draft is ``{"config": <stage-section config>, "authoring": <authoring record>}``.  It is created by one explicit
copy from the Pipeline's settings (or by cloning/adopting an experiment's own baseline) and is then edited only
through ``edit_field``.  Nothing here reads the Pipeline on its own: the caller passes the Pipeline's settings in
exactly when the operator asks for a copy.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from src.learning import baseline_authoring as authoring


def has_draft(state: Any) -> bool:
    draft = getattr(state, "baseline_draft", None)
    return (
        isinstance(draft, dict) and isinstance(draft.get("config"), dict) and bool(draft["config"])
    )


def config_of(state: Any) -> dict[str, Any]:
    """An isolated copy of the draft's settings (empty when no baseline has been authored yet)."""
    return copy.deepcopy(state.baseline_draft["config"]) if has_draft(state) else {}


def authoring_of(state: Any) -> dict[str, Any]:
    draft = getattr(state, "baseline_draft", None)
    return copy.deepcopy(draft.get("authoring") or {}) if isinstance(draft, dict) else {}


def clear(state: Any) -> None:
    state.baseline_draft = None


def copy_from_pipeline(
    state: Any,
    pipeline_config: Mapping[str, Any] | None,
    stage: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Replace the editable baseline with a one-time copy of the Pipeline's settings.

    Only the editable baseline changes: the experiment's prompt, variable, values and any recorded evidence are
    untouched, and a Preview built from the previous baseline becomes stale by its signature.
    """
    stage = authoring.require_stage(stage)
    if not pipeline_config or not any(
        isinstance(pipeline_config.get(name), Mapping) and pipeline_config.get(name)
        for name in ("txt2img", "img2img", "adetailer", "upscale")
    ):
        raise ValueError(
            "The Pipeline has no settings to copy yet. Choose the settings in Learning instead."
        )
    config, record = authoring.seed_from_pipeline(pipeline_config, stage, now=now)
    state.baseline_draft = {"config": config, "authoring": record}
    return copy.deepcopy(record)


def adopt(
    state: Any,
    config: Mapping[str, Any] | None,
    record: Mapping[str, Any] | None,
    *,
    origin: str = "",
) -> None:
    """Make an experiment's own baseline the draft (open/restore/clone); never reads the Pipeline."""
    if not config:
        clear(state)
        return
    adopted = dict(record or {})
    if not adopted.get("origin"):
        adopted = authoring.new_authoring(origin or authoring.ORIGIN_LEGACY, source="experiment")
    elif origin:
        adopted = {**adopted, "origin": origin, "copied_from": "experiment"}
    state.baseline_draft = {"config": copy.deepcopy(dict(config)), "authoring": adopted}


def edit_field(state: Any, stage: str, name: str, value: Any) -> Any:
    """Set one Learning-owned setting.  Raises ValueError for a value the setting cannot hold."""
    spec = authoring.field_for(stage, name)
    if not has_draft(state):
        state.baseline_draft = {
            "config": {
                section: {}
                for section in ("txt2img", "img2img", "adetailer", "upscale", "pipeline")
            },
            "authoring": authoring.new_authoring(authoring.ORIGIN_LEARNING, source="learning"),
        }
    text = str(value).strip() if value is not None else ""
    if spec.kind in {"int", "float"} and text:
        try:
            float(text)
        except ValueError as exc:
            raise ValueError(f"{spec.label} must be a number") from exc
    draft = state.baseline_draft
    if not text and not spec.required:
        # An optional setting cleared by the operator is genuinely unset, not zero.
        section = draft["config"].get(spec.section)
        if isinstance(section, dict):
            for key in (spec.key, *spec.aliases):
                section.pop(key, None)
        authoring.record_edit(draft["authoring"], stage, name)
        return None
    if not text:
        section = draft["config"].get(spec.section)
        if isinstance(section, dict):
            section.pop(spec.key, None)
        authoring.record_edit(draft["authoring"], stage, name)
        return None
    coerced = authoring.write_field(draft["config"], spec, text)
    authoring.record_edit(draft["authoring"], stage, name)
    return coerced


def signature(state: Any, stage: str) -> str:
    return authoring.signature(state.baseline_draft["config"], stage) if has_draft(state) else ""
