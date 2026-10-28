"""One synthetic journey through existing compilation, SQLite, ratings and immutable reuse owners."""

import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from src.controller.generation_profile_controller import GenerationProfileController
from src.controller.job_service import JobService
from src.generation_profiles.contract import ProfileError
from src.generation_profiles.service import GenerationProfileService
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_record import LearningRecordWriter
from src.learning.recommendation_engine import RecommendationEngine
from src.learning.recommendation_summary import build_recommendation_summary
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller import test_generation_profile_integration_630 as profile_bench
from tests.controller.test_generation_profile_integration_630 import (
    _add_to_draft,
    _compat,
    _snapshot_from_panel,
)
from tests.controller.test_job_service_unit import FakeRunner
from tests.learning_v2.test_learning_independent_baseline_650 import Bench
from tests.learning_v2.test_model_comparison_140 import SDXL, policy
from tests.learning_v2.test_profile_publication_660 import make_publication


@pytest.fixture
def ordinary_environment(tmp_path):
    return profile_bench.env.__wrapped__(tmp_path)


def test_durable_controlled_evidence_to_next_ordinary_sqlite_job(
    ordinary_environment, tmp_path, monkeypatch
):
    publication = make_publication(tmp_path)
    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver", lambda: publication.resolver
    )
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(
        JobQueue(repository=repository), runner=FakeRunner(), require_normalized_records=True
    )
    bench = Bench(tmp_path)
    controller = bench.controller
    writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    controller._learning_record_writer = writer
    controller._recommendation_engine = RecommendationEngine(
        writer.records_path, policy_resolver=policy
    )
    controller.execution_controller = LearningExecutionController(bench.state, service)
    controller.execution_controller.set_completion_callback(
        controller._apply_variant_completion_evidence
    )
    controller.execution_controller.set_presentation_callback(
        controller._on_variant_completion_published
    )
    experiment = bench.preview(variable="CFG Scale", values=(4, 8, 2), images=1)
    frozen = experiment.execution_snapshot_json
    assert repository.count() == 0
    controller._learning_enabled = True
    controller.run_plan()
    ids = [variant.job_id for variant in bench.state.plan]
    assert len(set(ids)) == 3
    assert repository.count() == 3
    controller.run_plan()
    assert repository.count() == 3  # Repetition never admits the frozen experiment twice.
    assert experiment.execution_snapshot_json == frozen
    for variant in bench.state.plan:
        stored = repository.get_job_model(variant.job_id)._normalized_record
        assert stored.job_id == variant.job_id
        assert stored.config["txt2img"]["cfg_scale"] == variant.param_value
        image = tmp_path / f"{variant.variant_id}.png"
        Image.new("RGB", (8, 8)).save(image)
        result = {
            "variants": [
                {
                    "output_paths": [str(image)],
                    "all_seeds": [42],
                    "all_subseeds": [700],
                    "final_prompt": experiment.prompt_text,
                }
            ]
        }
        job = repository.transition_job(repository.get_job_model(variant.job_id), JobStatus.RUNNING)
        repository.transition_job(job, JobStatus.COMPLETED, result=result)
    controller.execution_controller.reconcile()
    assert all(v.status == "completed" for v in bench.state.plan)
    assert all(v.execution_metadata["controlled_evidence_valid"] for v in bench.state.plan)
    artifacts = {ref: Path(ref).read_bytes() for v in bench.state.plan for ref in v.image_refs}
    for variant in bench.state.plan:
        controller.record_rating(variant.image_refs[0], 5 if variant.param_value == 6 else 2)
    rows = [json.loads(line) for line in writer.records_path.read_text().splitlines()]
    ratings_bytes = writer.records_path.read_bytes()
    assert len(rows) == 3
    assert len({row["run_id"] for row in rows}) == 3
    store = LearningExperimentStore(tmp_path / "experiments")
    store.save_session(
        display_name=experiment.name,
        experiment_id=experiment.experiment_id,
        payload=bench.state.to_dict(),
    )
    restored = LearningController(
        LearningState.from_dict(
            LearningExperimentStore(store.root).load_session(experiment.experiment_id)
        ),
        learning_record_writer=LearningRecordWriter(writer.records_path),
    )
    restored.load_existing_ratings()
    assert restored.get_review_counts()["saved"] == 3
    recs = RecommendationEngine(writer.records_path, policy_resolver=policy).recommend(
        experiment.prompt_text, "txt2img", model=SDXL
    )
    assert recs.automation_eligible
    assert recs.get_best_for_parameter("cfg_scale").recommended_value == 6
    summary = build_recommendation_summary(recs, mode="apply_with_confirm")
    assert "3 usable controlled ratings in 1 experiments" in summary.progress
    proposal = publication.evaluate(rows, SDXL, experiment_id=experiment.experiment_id)
    assert proposal.settings == {"cfg_scale": 6}, (proposal.blockers, proposal.excluded)
    assert proposal.sample_count == 3
    with pytest.raises(ValueError, match="confirmation"):
        publication.publish(proposal, rows, SDXL, name="Evidence", confirmed=False)
    assert not publication.store.root.exists()
    published = publication.publish(proposal, rows, SDXL, name="Evidence", confirmed=True)
    immutable = publication.store.load(published.ref).to_dict()
    with pytest.raises(ProfileError, match="stale|ineligible"):
        publication.publish(proposal, rows[:-1], SDXL, name="Stale", confirmed=True)

    pipeline, manager, _, host, pack = ordinary_environment
    pack_bytes = pack.read_bytes()
    pipeline._prompt_pack_builder = PromptPackNormalizedJobBuilder(
        config_manager=manager,
        job_builder=pipeline._job_builder,
        packs_dir=manager.packs_dir,
        model_family_lookup=lambda _name: _compat("sdxl"),
    )
    pipeline._job_service = service
    host.profiles = GenerationProfileController(
        host, GenerationProfileService(publication.store, publication.resolver)
    )
    host.panel.values.update(
        model=SDXL, sampler="DPM++ 2M", scheduler="Karras", cfg_scale=4, vae=""
    )
    host.override_pack_config_enabled = True
    prior = {identity: repository.get_job(identity).snapshot for identity in ids}
    # Publication does not touch the working settings or select itself.
    assert host.panel.values["cfg_scale"] == 4
    assert host.profiles.state().selected != published.ref
    host.profiles.on_profile_selected(published.ref)
    assert host.profiles.state().selected == published.ref
    snapshot = _snapshot_from_panel(host.panel)
    snapshot["txt2img"].update(vae="", seed=123)
    [preview] = _add_to_draft(pipeline, host, snapshot, {"txt2img": True})
    expected = NormalizedJobRecord.from_dict(preview.to_dict()).to_dict()
    assert pipeline.enqueue_draft_jobs() == 1
    stored = repository.get_job_model(preview.job_id)._normalized_record
    assert stored.to_dict() == expected
    assert stored.config["cfg_scale"] == 6
    assert stored.job_id not in ids
    assert repository.count() == 4
    assert {identity: repository.get_job(identity).snapshot for identity in ids} == prior
    assert publication.store.load(published.ref).to_dict() == immutable
    assert publication.store.favorite_for(published.model.key) is None
    assert publication.store.load_startup_document() is None
    assert writer.records_path.read_bytes() == ratings_bytes
    assert pack.read_bytes() == pack_bytes
    assert {ref: Path(ref).read_bytes() for ref in artifacts} == artifacts
    controller.execution_controller.close()
    repository.close()


@pytest.mark.parametrize("damage", ["empty", "sparse", "readback", "identity"])
def test_negative_publication_has_no_side_effects(tmp_path, damage):
    from tests.learning_v2.test_profile_publication_660 import records

    publication = make_publication(tmp_path)
    rows = records(publication)
    if damage == "empty":
        rows = []
    elif damage == "sparse":
        rows = rows[:1]
    else:
        rows = copy.deepcopy(rows)
        for row in rows:
            frozen = row["metadata"]["frozen_experiment"]
            if damage == "readback":
                frozen.pop("actual_all_seeds")
            else:
                row["primary_model"] = "other.safetensors"
    original = copy.deepcopy(rows)
    proposal = publication.evaluate(rows, "test.safetensors")
    assert not proposal.ready
    with pytest.raises(ProfileError):
        publication.publish(proposal, rows, "test.safetensors", name="Refused", confirmed=True)
    assert rows == original
    assert not publication.store.root.exists()
    assert not (tmp_path / "jobs.sqlite3").exists()
