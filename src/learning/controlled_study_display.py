"""Presentation dispatch for the controlled single-position studies (Prompt Slot, LoRA Composition, Embedding)."""

from __future__ import annotations

import json
from typing import Any

from src.learning import embedding_experiment, lora_composition
from src.learning.prompt_slot_experiment import candidate_caption as slot_caption

#: Studies whose review captions and experiment-local conclusion text are shown beside the ratings.
DISPLAYED_STUDIES = ("prompt_slot", "lora_composition", embedding_experiment.STUDY_TYPE)


def _frozen_study(experiment: Any) -> str:
    try:
        return str(
            json.loads(getattr(experiment, "execution_snapshot_json", "") or "{}").get(
                "study_type", ""
            )
        )
    except (TypeError, ValueError, AttributeError):
        return ""


def visibility_prompt(experiment: Any) -> str:
    """Private input to the existing visibility classifier, never a presentation caption."""
    if _frozen_study(experiment) == embedding_experiment.STUDY_TYPE:
        return embedding_experiment.visibility_prompt(experiment)
    return lora_composition.visibility_prompt(experiment)


def candidate_caption(study: str, experiment: Any, label: str, *, visible: bool) -> str:
    if study == embedding_experiment.STUDY_TYPE:
        return embedding_experiment.candidate_caption(experiment, label, visible=visible)
    if study == "lora_composition":
        return lora_composition.candidate_caption(experiment, label, visible=visible)
    return slot_caption(experiment, label, visible=visible)


def candidate_label_text(study: str, experiment: Any, label: str, *, visible: bool) -> str:
    """The tested-position text of a candidate ("" for Prompt Slot, which has no named asset)."""
    if study == embedding_experiment.STUDY_TYPE:
        return embedding_experiment.candidate_label_text(experiment, label, visible=visible)
    if study == "lora_composition":
        return lora_composition.candidate_label_text(experiment, label, visible=visible)
    return ""
