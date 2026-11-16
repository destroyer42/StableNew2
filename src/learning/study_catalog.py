"""One declarative catalog of the Learning study types: data and references, no behaviour.

Each study engine (ordinary controlled sweep, Prompt Slot, LoRA Composition, Embedding, Model Comparison, Two-Axis
Grid, Prompt x Model Matrix, Compatibility Probe) keeps its own frozen mechanism. This module only names them once so
the consumers that used to keep private subsets (the experiment-local study set, the rated-study set, the conclusion
dispatch and the outcome derivation) read the same descriptor.

References are ``"module:attribute"`` strings resolved lazily by ``resolve_ref``; nothing here imports a study engine,
so the catalog is cheap and cycle free. Evidence classes only describe what an engine may claim; they add no rule.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

#: One tested variable, controlled seeds; the only class whose ratings feed ``RecommendationEngine``.
CLASS_CONTROLLED = "controlled_one_variable"
#: One designated position, controlled; a preference that stays inside this experiment.
CLASS_LOCAL = "controlled_local"
#: Frozen per-target envelopes; a preference under each envelope, never a causal winner.
CLASS_ENVELOPE = "envelope"
#: Several varying settings or a feasibility observation; descriptive only, no winner.
CLASS_EXPLORATORY = "exploratory"
EVIDENCE_CLASSES = (CLASS_CONTROLLED, CLASS_LOCAL, CLASS_ENVELOPE, CLASS_EXPLORATORY)

RATING_KIND_EXPERIMENT = "learning_experiment_rating"
EXCLUSIONS_REF = "src.learning.baseline_exclusions:STUDY_EXCLUSIONS"


@dataclass(frozen=True)
class StudyDescriptor:
    slug: str  # the frozen ``study_type`` literal
    label: str
    objective: str
    evidence_class: str
    rating_record_kind: str
    feeds_recommendations: bool
    #: The existing check that decides whether a design may be previewed (not called by the catalog).
    eligibility_ref: str
    #: The study's own conclusion function; ``""`` means the generic ``experiment_conclusion`` builder.
    conclusion_ref: str = ""
    #: Where the study's refused settings are listed (``STUDY_EXCLUSIONS[slug]``); ``""`` when it refuses none.
    exclusions_ref: str = ""
    #: Module under ``learning_controller_services`` that coordinates the study, ``""`` for the ordinary sweep path.
    service: str = ""
    #: Other literals that name the same study in saved data.
    aliases: tuple[str, ...] = ()
    #: The plain next test offered when the finished study is inconclusive.
    next_test: str = ""


STUDIES: tuple[StudyDescriptor, ...] = (
    StudyDescriptor(
        slug="controlled_variable",
        label="Controlled Variable",
        objective="Which value of one setting is better rated, with every other setting and the seeds held fixed.",
        evidence_class=CLASS_CONTROLLED,
        rating_record_kind=RATING_KIND_EXPERIMENT,
        feeds_recommendations=True,
        eligibility_ref="src.learning.model_policy_service:validate_experiment",
        aliases=("ordinary",),
        next_test="Add images per value, or repeat the test under a different prompt, so the ratings can separate the values.",
    ),
    StudyDescriptor(
        slug="prompt_slot",
        label="Prompt Slot",
        objective="Which of 2-8 candidates for one named prompt slot is better rated on a fixed model, settings and seeds.",
        evidence_class=CLASS_LOCAL,
        rating_record_kind=RATING_KIND_EXPERIMENT,
        feeds_recommendations=False,
        eligibility_ref="src.learning.prompt_slot_experiment:validate_design",
        conclusion_ref="src.learning.prompt_slot_experiment:conclusion",
        exclusions_ref=EXCLUSIONS_REF,
        service="prompt_slot",
        next_test="Rate more images per candidate, or add a fourth candidate that differs in the same slot.",
    ),
    StudyDescriptor(
        slug="lora_composition",
        label="LoRA Composition",
        objective="Which composition of one designated LoRA position is better rated, with everything else fixed.",
        evidence_class=CLASS_LOCAL,
        rating_record_kind=RATING_KIND_EXPERIMENT,
        feeds_recommendations=False,
        eligibility_ref="src.learning.lora_composition:validate_operation",
        conclusion_ref="src.learning.lora_composition:conclusion",
        exclusions_ref=EXCLUSIONS_REF,
        service="lora_composition",
        next_test="Rate more images per candidate, or narrow the strengths around the best-rated candidate.",
    ),
    StudyDescriptor(
        slug="embedding_experiment",
        label="Embedding",
        objective="Which embedding presence, weight or identity at one designated position is better rated.",
        evidence_class=CLASS_LOCAL,
        rating_record_kind=RATING_KIND_EXPERIMENT,
        feeds_recommendations=False,
        eligibility_ref="src.learning.embedding_experiment:validate_operation",
        conclusion_ref="src.learning.embedding_experiment:conclusion",
        exclusions_ref=EXCLUSIONS_REF,
        service="embedding_experiment",
        next_test="Rate more images per candidate, or repeat with a narrower range of weights.",
    ),
    StudyDescriptor(
        slug="model_comparison",
        label="Model Comparison",
        objective="Which model is preferred under each model's own frozen, validated settings.",
        evidence_class=CLASS_ENVELOPE,
        rating_record_kind="learning_model_comparison_rating",
        feeds_recommendations=False,
        eligibility_ref="src.learning.model_comparison:verify_arms_admissible",
        next_test="Rate more images per model, or compare the two closest models on a second prompt.",
    ),
    StudyDescriptor(
        slug="two_axis_grid",
        label="Two-Axis Grid",
        objective="How two settings jointly change the result on one prompt, model and seed set (descriptive).",
        evidence_class=CLASS_EXPLORATORY,
        rating_record_kind="learning_grid_rating",
        feeds_recommendations=False,
        eligibility_ref="src.learning.two_axis_grid:require_plain_txt2img",
        exclusions_ref=EXCLUSIONS_REF,
        next_test="Test the most promising cell's setting alone with a Controlled Variable experiment.",
    ),
    StudyDescriptor(
        slug="prompt_model_matrix",
        label="Prompt x Model Matrix",
        objective="Which prompt candidate is preferred within each model's own validated settings (descriptive).",
        evidence_class=CLASS_ENVELOPE,
        rating_record_kind="learning_prompt_model_matrix_rating",
        feeds_recommendations=False,
        eligibility_ref="src.learning.prompt_model_matrix:require_matrix_baseline",
        conclusion_ref="src.learning.prompt_model_matrix:conclusion",
        exclusions_ref=EXCLUSIONS_REF,
        service="prompt_model_matrix",
        next_test="Rate more images per cell, or repeat the matrix on a second seed cohort.",
    ),
    StudyDescriptor(
        slug="compatibility_probe",
        label="Compatibility Probe",
        objective="Does this checkpoint run here, and under which lineage recipe does it look best (descriptive).",
        evidence_class=CLASS_EXPLORATORY,
        rating_record_kind=RATING_KIND_EXPERIMENT,
        feeds_recommendations=False,
        eligibility_ref="src.learning.compatibility_probe:verify_spec",
        service="compatibility_probe",
        next_test="Record a verdict with Review Probe Result, or test the best recipe's settings in a Controlled Variable experiment.",
    ),
)

_BY_SLUG: dict[str, StudyDescriptor] = {}
for _descriptor in STUDIES:
    for _name in (_descriptor.slug, *_descriptor.aliases):
        if _name in _BY_SLUG:
            raise RuntimeError(f"Study literal {_name!r} is cataloged twice")
        _BY_SLUG[_name] = _descriptor
del _descriptor, _name


def lookup(study: str | None) -> StudyDescriptor | None:
    """The descriptor for a saved ``study_type`` literal (or alias), else ``None``."""
    return _BY_SLUG.get(str(study or ""))


def slugs() -> tuple[str, ...]:
    return tuple(descriptor.slug for descriptor in STUDIES)


def local_only_studies() -> frozenset[str]:
    """Experiment-local studies that own a coordination service (the set ``reports_setting_recommendations`` reads)."""
    return frozenset(d.slug for d in STUDIES if d.service)


def non_recommending_studies() -> frozenset[str]:
    """Every study whose ratings never feed ``RecommendationEngine``."""
    return frozenset(d.slug for d in STUDIES if not d.feeds_recommendations)


def rated_studies() -> frozenset[str]:
    """Every study literal (aliases included) whose generated images are rated and can be completed."""
    return frozenset(_BY_SLUG)


def rating_record_kinds() -> frozenset[str]:
    return frozenset(d.rating_record_kind for d in STUDIES)


def resolve_ref(ref: str) -> Any:
    """Import ``"module:attribute"`` lazily; an empty reference resolves to ``None``."""
    if not ref:
        return None
    module_name, _, attribute = ref.partition(":")
    return getattr(importlib.import_module(module_name), attribute)


def exclusions(slug: str) -> tuple[str, ...]:
    """The settings this study refuses, read from the baseline-exclusion table the catalog points at."""
    descriptor = lookup(slug)
    if descriptor is None or not descriptor.exclusions_ref:
        return ()
    return tuple(resolve_ref(descriptor.exclusions_ref).get(descriptor.slug, ()))


def conclusion_function(slug: str) -> Any:
    """The study's own conclusion function, or ``None`` for the generic builder."""
    descriptor = lookup(slug)
    return resolve_ref(descriptor.conclusion_ref) if descriptor else None
