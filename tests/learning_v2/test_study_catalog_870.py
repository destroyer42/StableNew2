"""LEARN-OUTCOME-870: the study catalog names every study once and agrees with the consumers that keep subsets."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.learning import study_catalog
from src.learning.baseline_exclusions import STUDY_EXCLUSIONS
from src.learning.experiment_conclusion import build_experiment_conclusion
from src.learning.learning_controller_services import controlled_studies
from src.learning.recommendation_engine import RecommendationEngine

LEARNING_SRC = Path(study_catalog.__file__).parent
#: The set the engine, LOCAL_ONLY_STUDIES and the rated-study tuple each kept privately before the catalog.
PREVIOUS_LOCAL_ONLY = {
    "prompt_slot",
    "lora_composition",
    "embedding_experiment",
    "prompt_model_matrix",
    "compatibility_probe",
}
PREVIOUS_ENGINE_EXCLUSIONS = PREVIOUS_LOCAL_ONLY | {"model_comparison", "two_axis_grid"}


def _declared_study_literals() -> set[str]:
    found = {"controlled_variable"}  # model_comparison.study_type()'s default
    for path in LEARNING_SRC.rglob("*.py"):
        found.update(re.findall(r'^STUDY_TYPE\s*=\s*"([a-z_]+)"', path.read_text("utf-8"), re.M))
    return found


def test_every_study_literal_has_exactly_one_descriptor():
    declared = _declared_study_literals()
    assert declared == set(study_catalog.slugs())
    assert len(study_catalog.slugs()) == len(set(study_catalog.slugs())) == 8
    for slug in declared:
        assert study_catalog.lookup(slug).slug == slug
    assert study_catalog.lookup("ordinary").slug == "controlled_variable"  # saved-data alias
    assert study_catalog.lookup("nonsense") is None


def test_every_reference_resolves_to_the_existing_function():
    for descriptor in study_catalog.STUDIES:
        assert callable(study_catalog.resolve_ref(descriptor.eligibility_ref)), descriptor.slug
        if descriptor.conclusion_ref:
            assert callable(study_catalog.conclusion_function(descriptor.slug))
        else:
            assert study_catalog.conclusion_function(descriptor.slug) is None
        assert descriptor.evidence_class in study_catalog.EVIDENCE_CLASSES
        assert descriptor.objective and descriptor.next_test


def test_exclusions_are_read_from_the_existing_table():
    for descriptor in study_catalog.STUDIES:
        assert study_catalog.exclusions(descriptor.slug) == STUDY_EXCLUSIONS.get(
            descriptor.slug, ()
        )
    assert study_catalog.exclusions("controlled_variable") == ()


def test_local_only_studies_equal_todays_set_and_the_controller_reads_the_catalog():
    assert study_catalog.local_only_studies() == PREVIOUS_LOCAL_ONLY
    assert controlled_studies.LOCAL_ONLY_STUDIES == PREVIOUS_LOCAL_ONLY
    assert set(controlled_studies._SERVICES) == PREVIOUS_LOCAL_ONLY
    for slug in PREVIOUS_LOCAL_ONLY:
        assert controlled_studies.service_for(slug) is not None
    assert controlled_studies.service_for("controlled_variable") is None
    assert controlled_studies.service_for("model_comparison") is None


def test_non_recommending_set_equals_local_only_plus_engine_exclusions():
    assert study_catalog.non_recommending_studies() == PREVIOUS_ENGINE_EXCLUSIONS
    assert study_catalog.non_recommending_studies() == (
        study_catalog.local_only_studies() | {"model_comparison", "two_axis_grid"}
    )
    assert {d.slug for d in study_catalog.STUDIES if d.feeds_recommendations} == {
        "controlled_variable"
    }


@pytest.mark.parametrize("descriptor", study_catalog.STUDIES, ids=study_catalog.slugs())
def test_the_engine_scores_a_study_only_when_the_catalog_says_it_feeds_recommendations(
    descriptor, tmp_path
):
    record = {
        "timestamp": "2026-11-01T10:00:00",
        "primary_steps": 30,
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "study_type": descriptor.slug,
            "experiment_id": "exp",
            "variable_under_test": "Steps",
            "variant_value": 30,
            "user_rating": 4,
            "frozen_experiment": {
                "snapshot": {"study_type": descriptor.slug},
                "executed_config": {},
                "controlled_evidence_valid": True,
            },
        },
    }
    scored = RecommendationEngine(tmp_path / "records.jsonl")._score_records([record])
    assert bool(scored) is descriptor.feeds_recommendations


def test_the_catalog_rating_kinds_match_what_each_study_writes():
    assert (
        study_catalog.lookup("model_comparison").rating_record_kind
        == "learning_model_comparison_rating"
    )
    assert study_catalog.lookup("two_axis_grid").rating_record_kind == "learning_grid_rating"
    assert (
        study_catalog.lookup("prompt_model_matrix").rating_record_kind
        == "learning_prompt_model_matrix_rating"
    )
    from src.learning import model_comparison, prompt_model_matrix, two_axis_grid

    assert (
        model_comparison.RECORD_KIND == study_catalog.lookup("model_comparison").rating_record_kind
    )
    assert two_axis_grid.RECORD_KIND == study_catalog.lookup("two_axis_grid").rating_record_kind
    assert (
        prompt_model_matrix.RECORD_KIND
        == study_catalog.lookup("prompt_model_matrix").rating_record_kind
    )


def test_conclusion_dispatch_reads_the_catalog_and_unknown_studies_use_the_generic_builder():
    class Variant:
        def __init__(self, value):
            self.param_value = value
            self.image_refs = [f"{value}.png"]
            self.execution_metadata = {"controlled_evidence_valid": True}
            self.status = "completed"

    plan = [Variant("A"), Variant("B")]
    ratings = {"A.png": {"overall_rating": 5}, "B.png": {"overall_rating": 2}}
    generic = build_experiment_conclusion(plan, ratings, {}, study_type="controlled_variable")
    assert generic["comparison_claim"] == "controlled_variable"
    unknown = build_experiment_conclusion(plan, ratings, {}, study_type="unknown_study")
    assert {**unknown, "study_type": "controlled_variable"} == generic
    slot = build_experiment_conclusion(plan, ratings, {}, study_type="prompt_slot")
    assert slot["study_type"] == "prompt_slot"
    assert slot["comparison_claim"] == "experiment_local_prompt_preference"
    comparison = build_experiment_conclusion(plan, ratings, {}, study_type="model_comparison")
    assert comparison["comparison_claim"] == "target_envelope_preference"
    assert comparison["causal_one_variable"] is False
