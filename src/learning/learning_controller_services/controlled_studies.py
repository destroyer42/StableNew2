"""Dispatch for the controlled single-position studies; each owns its own snapshot, NJR and evidence service."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Protocol, cast

from src.learning import study_catalog

if TYPE_CHECKING:
    from src.pipeline.njr_core_v26 import NormalizedJobRecord


class ControlledStudyService(Protocol):
    """The two entry points every controlled-study coordination module provides.

    ``prompt_model_matrix.build_plan`` additionally accepts the worker-prepared ``comparison_evidence``.
    """

    def build_plan(self, controller: Any, experiment: Any) -> None: ...

    def build_variant(
        self, controller: Any, experiment: Any, variant: Any
    ) -> NormalizedJobRecord: ...


#: study literal -> coordination module, read from the study catalog (the one place that names every study).
_SERVICES = {d.slug: d.service for d in study_catalog.STUDIES if d.service}
#: Studies whose ratings stay experiment-local: no recommendations, Apply or profile publication.
LOCAL_ONLY_STUDIES = study_catalog.local_only_studies()

LOCAL_STUDY_RECOMMENDATION_NOTICE = (
    "This study's ratings stay with this experiment. It reports a local conclusion, "
    "not setting recommendations, Apply or profiles."
)


def reports_setting_recommendations(experiment: Any) -> bool:
    """Whether setting recommendations may be shown for this experiment (None: no experiment open).

    The one eligibility rule for every recommendation entry point, so a refresh can never show what the
    getter (and Apply) refuses.
    """
    if experiment is None:
        return True
    from src.learning.model_comparison import study_type

    return study_type(experiment) not in LOCAL_ONLY_STUDIES


def service_for(study: str) -> ControlledStudyService | None:
    """The coordination module (``build_plan`` / ``build_variant``) of a controlled study, else None."""
    name = _SERVICES.get(study)
    if name is None:
        return None
    return cast(ControlledStudyService, importlib.import_module(f"{__package__}.{name}"))


def rating_metadata(snapshot: dict[str, Any], variant: Any) -> dict[str, Any]:
    """Typed rating evidence of the LoRA Composition and Embedding studies (each is {} for any other study)."""
    from src.learning.embedding_experiment import rating_metadata as embedding_metadata
    from src.learning.lora_composition import rating_metadata as lora_metadata
    from src.learning.setting_evidence import rating_metadata as qualification_metadata

    return {
        **lora_metadata(snapshot, variant),
        **embedding_metadata(snapshot, variant),
        **qualification_metadata(snapshot, variant),
    }
