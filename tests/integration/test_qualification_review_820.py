"""Freeze, observed artifact proof, existing writer, reopen and create-only follow-up."""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

from src.gui.controllers.learning_controller import LearningController
from src.gui.controllers.model_evidence_proposals import (
    compile_qualification_state,
    preview_selected,
)
from src.gui.learning_state import LearningState
from src.gui_v2.qualification_review_session import QualificationReviewSession
from src.learning.evidence_autopilot import EvidenceProposalPlanner
from src.learning.experiment_reconciliation import completion_evidence
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_record import LearningRecordWriter
from src.learning.qualification_followup import prepare_followup, save_followup
from src.learning.qualification_review import project_qualification
from src.pipeline.learning_sample_evidence import observed_sample
from tests.learning_v2.test_evidence_autopilot_800 import context as context_fixture


@pytest.fixture
def completed(tmp_path, monkeypatch):
    context = context_fixture.__wrapped__(tmp_path)
    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver",
        lambda: SimpleNamespace(resolve=lambda _name: context.target),
    )
    proposals = EvidenceProposalPlanner().plan(context)
    chosen = next(
        p for p in proposals.proposals if p.runnable and p.document["variable"] == "steps"
    )
    [(state, _, _)] = preview_selected(
        proposals, (chosen.proposal_id,), context, prompt="lighthouse"
    )
    for variant in state.plan:
        variant.job_id = "job-" + variant.variant_id
        refs = []
        for i in range(6):
            path = tmp_path / f"{variant.variant_id.replace(':', '_')}-{i}.png"
            Image.new("RGB", (8, 8)).save(path)
            refs.append(str(path))
        info = {"all_seeds": list(range(42, 48))}
        payload = {
            "all_seeds": info["all_seeds"],
            "runtime_admission": {"launch_profile": "launch"},
            "learning_samples": {
                "contract": "learning_samples/1",
                "runtime_before": {
                    "pid": 100,
                    "started": 1000,
                    "ready_epoch": 1,
                    "endpoint": "http://test",
                    "backend": "forge_webui",
                },
                "runtime_after": {
                    "pid": 100,
                    "started": 1000,
                    "ready_epoch": 1,
                    "endpoint": "http://test",
                    "backend": "forge_webui",
                },
                "samples": [
                    observed_sample(path, i, info, 6, variant.job_id) for i, path in enumerate(refs)
                ],
            },
            "backend_reported_settings": {"steps": variant.param_value},
            "dispatched_settings": {"steps": variant.param_value},
        }
        evidence = completion_evidence(state.current_experiment, variant, {"variants": [payload]})
        variant.status, variant.execution_metadata = evidence.status, evidence.execution_metadata
        state.current_experiment.metadata = evidence.experiment_metadata
        variant.image_refs, variant.completed_images = refs, 6
    writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    controller = LearningController(state, learning_record_writer=writer)
    controller.refresh_recommendations = lambda: None
    for i, variant in enumerate(state.plan):
        for path in variant.image_refs:
            controller.record_rating(path, 3 + i)
    return context, state, controller, writer


def test_forward_completion_writer_and_reopen_produce_defensible_outcome(completed, tmp_path):
    context, state, controller, writer = completed
    result = project_qualification(
        state.current_experiment, state.plan, controller._rating_details_cache
    )
    assert result.outcome == "Follow-up supported", result.exclusions
    assert result.rated_pairs == 6
    store = LearningExperimentStore(tmp_path / "experiments")
    experiment_id = state.current_experiment.experiment_id
    store.save_session(display_name="parent", payload=state.to_dict(), experiment_id=experiment_id)
    restored = LearningState.from_dict(store.load_session(experiment_id))
    ratings = writer.get_rating_details_for_experiment(experiment_id)
    assert project_qualification(restored.current_experiment, restored.plan, ratings) == result
    # Changed ratings use the existing latest record semantics; unchanged saves do not append.
    session = QualificationReviewSession(controller)
    ref = state.plan[1].image_refs[0]
    before = len(writer.records_path.read_text().splitlines())
    payload = controller.get_rating_details_for_image(ref)
    assert session.save(ref, payload, lambda _: True)[0]
    assert len(writer.records_path.read_text().splitlines()) == before
    controller.record_rating(ref, 1)
    controller.record_rating(state.plan[1].image_refs[1], 1)
    assert (
        project_qualification(
            restored.current_experiment,
            restored.plan,
            writer.get_rating_details_for_experiment(experiment_id),
        ).outcome
        == "Inconclusive"
    )


def test_followup_new_identity_frozen_parent_create_only_no_admission(completed, tmp_path):
    context, state, controller, writer = completed
    parent = state.current_experiment
    original = copy.deepcopy(state.to_dict())
    draft = prepare_followup(
        parent,
        state.plan,
        controller._rating_details_cache,
        context,
        candidate=state.plan[1].param_value,
        prompt="mountain lake",
        negative="",
        seed=900,
    )
    assert draft.state.current_experiment.experiment_id != parent.experiment_id
    assert (
        draft.state.current_experiment.metadata["parent_qualification"]["experiment_id"]
        == parent.experiment_id
    )
    records, _ = compile_qualification_state(draft.state, context, True)
    assert len(records) == 2
    assert all(not v.job_id for v in draft.state.plan)
    store = LearningExperimentStore(tmp_path / "experiments")
    experiment_id = save_followup(draft, store)
    payload = store.load_session(experiment_id)
    payload["current_experiment"]["name"] = "edited by operator"
    store.save_session(display_name="edited", experiment_id=experiment_id, payload=payload)
    assert save_followup(draft, store) == experiment_id
    assert store.load_session(experiment_id)["current_experiment"]["name"] == "edited by operator"
    assert state.to_dict() == original
    assert len(writer.records_path.read_text().splitlines()) == 12


@pytest.mark.parametrize(
    "fault",
    [
        "same_context",
        "different_model",
        "missing_resources",
        "unsupported_value",
        "unrated",
        "invalid",
    ],
)
def test_ineligible_followup_creates_nothing(completed, tmp_path, fault):
    context, state, controller, _writer = completed
    candidate = state.plan[1].param_value
    prompt, seed = "new prompt", 900
    if fault == "same_context":
        prompt, seed = "lighthouse", 42
    elif fault == "different_model":
        context = replace(
            context,
            target=replace(
                context.target, identity=replace(context.target.identity, sha256="b" * 64)
            ),
        )
    elif fault == "missing_resources":
        context = replace(context, resources={})
    elif fault == "unsupported_value":
        candidate = 999
    elif fault == "unrated":
        controller._rating_details_cache.pop(state.plan[0].image_refs[0])
    else:
        state.plan[0].execution_metadata["controlled_evidence_valid"] = False
    with pytest.raises(ValueError):
        prepare_followup(
            state.current_experiment,
            state.plan,
            controller._rating_details_cache,
            context,
            candidate=candidate,
            prompt=prompt,
            negative="",
            seed=seed,
        )
    assert not (tmp_path / "experiments").exists()


def test_shared_non_tested_drift_cannot_be_a_supported_screen(completed):
    _context, state, controller, _writer = completed
    for variant in state.plan:
        variant.executed_config["txt2img"]["cfg_scale"] = 123.0
    result = project_qualification(
        state.current_experiment, state.plan, controller._rating_details_cache
    )
    assert result.outcome == "Execution evidence invalid"
    assert any("frozen expected settings" in reason for reason in result.exclusions)


@pytest.mark.parametrize("fault", ["catalog", "model", "policy"])
def test_delayed_followup_result_rechecks_sources_before_persistence(
    completed, tmp_path, monkeypatch, fault
):
    from src.generation_profiles.evidence_catalog import EvidenceCatalog
    from src.gui.controllers import qualification_review as adapter

    context, state, controller, _writer = completed
    draft = prepare_followup(
        state.current_experiment,
        state.plan,
        controller._rating_details_cache,
        context,
        candidate=state.plan[1].param_value,
        prompt="independent prompt",
        negative="",
        seed=900,
    )
    compile_qualification_state(draft.state, context, True)
    target, catalog = context.target, context.catalog
    monkeypatch.setattr(adapter, "AssetRegistry", lambda: object())
    monkeypatch.setattr(
        adapter, "ModelIdentityResolver", lambda **_: SimpleNamespace(resolve=lambda _name: target)
    )
    monkeypatch.setattr(adapter, "load_operator_catalog", lambda: catalog)
    adapter.revalidate_followup_sources(draft)
    if fault == "catalog":
        catalog = EvidenceCatalog(())
    elif fault == "model":
        target = replace(target, identity=replace(target.identity, sha256="b" * 64))
    else:
        target = replace(target, policy=replace(target.policy, family="sd15"))
    with pytest.raises(ValueError):
        adapter.revalidate_followup_sources(draft)
        save_followup(draft, LearningExperimentStore(tmp_path / "never-saved"))
    assert not (tmp_path / "never-saved").exists()


def test_reverted_controls_remove_obsolete_draft_on_navigation(completed):
    _context, state, controller, _writer = completed
    session = QualificationReviewSession(controller)
    ref = state.plan[0].image_refs[0]
    saved = controller.get_rating_details_for_image(ref)
    session.stage(ref, {**saved, "overall_rating": 5})
    assert session.payload(ref)[0]["overall_rating"] == 5
    session.stage(ref, saved)
    assert controller.get_review_draft(ref) is None
    assert session.payload(ref)[0]["overall_rating"] == 3
