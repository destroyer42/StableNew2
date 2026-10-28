"""V2 drafts reuse real Learning/JobService/SQLite, reconciliation, ratings and publication."""

import json
from types import SimpleNamespace

import pytest
from PIL import Image

from src.controller.job_service import JobService
from src.generation_profiles.evidence_catalog import EvidenceCatalog
from src.gui.controllers.learning_controller import LearningController
from src.gui.controllers.model_evidence_proposals import preview_selected, save_drafts
from src.gui.learning_state import LearningState
from src.learning.evidence_autopilot import EvidenceProposalPlanner
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_record import LearningRecordWriter
from src.learning.recommendation_engine import RecommendationEngine
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller.test_job_service_unit import FakeRunner
from tests.learning_v2.test_evidence_autopilot_800 import context as context_fixture
from tests.learning_v2.test_profile_publication_660 import make_publication


def test_v2_steps_draft_preview_admission_restart_ratings_and_explicit_publication(
    tmp_path, monkeypatch
):
    context = context_fixture.__wrapped__(tmp_path)
    publication = make_publication(tmp_path)
    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver", lambda: publication.resolver
    )
    plan = EvidenceProposalPlanner().plan(context)
    chosen = next(p for p in plan.proposals if p.runnable and p.document["variable"] == "steps")
    ids = (chosen.proposal_id,)
    [(prepared, _njrs, summary)] = preview_selected(
        plan, ids, context, prompt="a lighthouse at dusk"
    )
    assert summary.total_images == 12
    store = LearningExperimentStore(tmp_path / "experiments")
    save_drafts(
        plan,
        ids,
        context,
        store,
        prompt_context=("a lighthouse at dusk", "blurry", {"prompt_source": "custom"}),
    )
    state = LearningState.from_dict(
        LearningExperimentStore(store.root).load_session(chosen.proposal_id)
    )
    assert not state.plan
    assert not state.current_experiment.execution_snapshot_json
    assert state.current_experiment.prompt_text == prepared.current_experiment.prompt_text
    writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(
        JobQueue(repository=repository), runner=FakeRunner(), require_normalized_records=True
    )
    controller = LearningController(
        state,
        learning_record_writer=writer,
        pipeline_controller=SimpleNamespace(_job_service=service),
    )
    controller.app_state = SimpleNamespace(resources=context.resources)
    controller._learning_policy_resolver = lambda _name: context.target.policy
    controller._evidence_catalog_provider = lambda: context.catalog
    controller._evidence_identity_resolver = lambda _name: context.target
    controller.build_plan(state.current_experiment)
    assert all(type(v.param_value) is int for v in state.plan)
    controller._learning_enabled = True
    controller.run_plan()
    assert repository.count() == 2
    job_ids = [v.job_id for v in state.plan]
    controller.run_plan()
    assert [v.job_id for v in state.plan] == job_ids
    assert repository.count() == 2
    for variant in state.plan:
        njr = repository.get_job_model(variant.job_id)._normalized_record
        assert njr.config["txt2img"]["steps"] == variant.param_value
        assert njr.config["txt2img"]["seed"] == 42
        paths = [tmp_path / f"{variant.variant_id.replace(':', '_')}-{i}.png" for i in range(6)]
        for path in paths:
            Image.new("RGB", (8, 8)).save(path)
        result = {
            "variants": [
                {
                    "output_paths": [str(path) for path in paths],
                    "all_seeds": list(range(42, 48)),
                    "final_prompt": state.current_experiment.prompt_text,
                    "backend_reported_settings": {"steps": variant.param_value},
                    "dispatched_settings": {"steps": variant.param_value},
                }
            ]
        }
        job = repository.transition_job(repository.get_job_model(variant.job_id), JobStatus.RUNNING)
        repository.transition_job(job, JobStatus.COMPLETED, result=result)
    controller.execution_controller.reconcile()
    assert all(v.execution_metadata["controlled_evidence_valid"] for v in state.plan)
    assert all(v.execution_metadata["qualification_tested_value_verified"] for v in state.plan)
    for variant in state.plan:
        for ref in variant.image_refs:
            controller.record_rating(ref, 5 if variant.param_value == 50 else 2)
    ratings_bytes = writer.records_path.read_bytes()
    rows = [json.loads(line) for line in ratings_bytes.decode().splitlines()]
    assert len(rows) == 12
    store.save_session(
        display_name=state.current_experiment.name,
        experiment_id=chosen.proposal_id,
        payload=state.to_dict(),
    )
    controller.execution_controller.close()
    restored = LearningController(
        LearningState.from_dict(
            LearningExperimentStore(store.root).load_session(chosen.proposal_id)
        ),
        learning_record_writer=LearningRecordWriter(writer.records_path),
        pipeline_controller=SimpleNamespace(_job_service=service),
    )
    restored.execution_controller.reconcile()
    restored.load_existing_ratings()
    assert restored.get_review_counts()["saved"] == 12
    assert repository.count() == 2
    recommendations = RecommendationEngine(
        writer.records_path, policy_resolver=lambda _name: context.target.policy
    ).recommend("a lighthouse at dusk", "txt2img", model="test.safetensors")
    assert recommendations.get_best_for_parameter("steps").recommended_value == 50
    proposal = publication.evaluate(rows, "test.safetensors", experiment_id=chosen.proposal_id)
    assert proposal.settings == {"steps": 50}, (proposal.blockers, proposal.excluded)
    assert not publication.store.root.exists()
    with pytest.raises(ValueError, match="confirmation"):
        publication.publish(
            proposal, rows, "test.safetensors", name="Steps finding", confirmed=False
        )
    published = publication.publish(
        proposal, rows, "test.safetensors", name="Steps finding", confirmed=True
    )
    assert published.settings == {"steps": 50}
    assert publication.store.favorite_for(published.model.key) is None
    assert publication.store.load_startup_document() is None
    assert writer.records_path.read_bytes() == ratings_bytes
    restored.execution_controller.close()
    repository.close()


@pytest.mark.parametrize(
    "damage", ["catalog", "resources", "values", "removed_metadata", "downgraded_metadata"]
)
def test_v2_stale_run_preflight_admits_zero_jobs(tmp_path, monkeypatch, damage):
    context = context_fixture.__wrapped__(tmp_path)
    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver",
        lambda: make_publication(tmp_path).resolver,
    )
    plan = EvidenceProposalPlanner().plan(context)
    selected = next(p for p in plan.proposals if p.runnable)
    [(state, _records, _summary)] = preview_selected(
        plan, (selected.proposal_id,), context, prompt="a lighthouse"
    )
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(
        JobQueue(repository=repository), runner=FakeRunner(), require_normalized_records=True
    )
    controller = LearningController(
        state, pipeline_controller=SimpleNamespace(_job_service=service)
    )
    controller.app_state = SimpleNamespace(
        resources={k: list(v) for k, v in context.resources.items()}
    )
    controller._evidence_catalog_provider = (
        lambda: EvidenceCatalog() if damage == "catalog" else context.catalog
    )
    controller._evidence_identity_resolver = lambda _name: context.target
    controller._learning_policy_resolver = lambda _name: context.target.policy
    if damage == "resources":
        controller.app_state.resources["samplers"].append("different inventory")
    if damage == "values":
        state.current_experiment.metadata["evidence_proposal"]["values"] = [7.0, 6.0]
    if damage == "removed_metadata":
        state.current_experiment.metadata.pop("evidence_proposal")
    if damage == "downgraded_metadata":
        state.current_experiment.metadata["evidence_proposal"]["contract"] = (
            "qualification_proposal/1"
        )
    controller._learning_enabled = True
    with pytest.raises(ValueError, match="stale|changed"):
        controller.run_plan()
    assert repository.count() == 0
    assert not (tmp_path / "ratings.jsonl").exists()
    controller.execution_controller.close()
    repository.close()
