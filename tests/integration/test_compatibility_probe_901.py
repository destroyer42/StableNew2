"""MEC-901 compatibility probes over real Learning compilation, JobService and SQLite."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.controller.job_service import JobService
from src.gui.controllers.model_evidence_proposals import compile_qualification_state
from src.gui.learning_state import LearningState
from src.learning.compatibility_probe import (
    RECIPES,
    STUDY_TYPE,
    ProbeDesign,
    probe_baseline,
    probe_payload,
    suggest_recipes,
)
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_store import LearningExperimentStore
from src.learning.learning_controller_services.controlled_studies import (
    LOCAL_ONLY_STUDIES,
    service_for,
)
from src.learning.qualification_batch import QualificationBatchService
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller.test_job_service_unit import FakeRunner
from tests.learning_v2.test_evidence_autopilot_800 import context as context_fixture
from tests.learning_v2.test_profile_publication_660 import make_publication


@pytest.fixture
def probe_env(tmp_path, monkeypatch):
    context = context_fixture.__wrapped__(tmp_path)
    resolver = make_publication(tmp_path).resolver
    monkeypatch.setattr(
        "src.generation_profiles.identity.ModelIdentityResolver", lambda **_: resolver
    )
    context = replace(
        context,
        baseline={
            **context.baseline,
            "txt2img": {**context.baseline["txt2img"], "vae": "external.vae.pt"},
            "pipeline": {"adetailer_enabled": True, "apply_global_positive_txt2img": True},
            "global_positive_prompt": "masterpiece",
        },
    )
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(
        JobQueue(repository=repository), runner=FakeRunner(), require_normalized_records=True
    )
    execution = LearningExecutionController(LearningState(), service)
    store = LearningExperimentStore(tmp_path / "experiments")
    coordinator = QualificationBatchService(store, execution, compile_qualification_state)
    yield SimpleNamespace(
        context=context, repository=repository, store=store, coordinator=coordinator
    )
    execution.close()
    repository.close()


def design(context, recipes=None, images=2):
    target = context.target
    return ProbeDesign(
        model=target.identity.display_name,
        sha256=target.identity.sha256,
        family=target.policy.family,
        recipes=tuple(recipes or (RECIPES["sdxl"], RECIPES["sd15"])),
        images_per_recipe=images,
    )


def payload(context, probe):
    return probe_payload(
        probe,
        probe_baseline(context.baseline, context.target),
        context.target.identity.display_name,
    )


def test_probe_is_a_local_only_registered_study():
    assert STUDY_TYPE in LOCAL_ONLY_STUDIES
    module = service_for(STUDY_TYPE)
    assert callable(module.build_plan) and callable(module.build_variant)


def test_probe_baseline_is_isolated_generation_only(probe_env):
    baseline = probe_baseline(probe_env.context.baseline, probe_env.context.target)
    assert baseline["txt2img"]["model"] == "test.safetensors"
    assert baseline["txt2img"]["vae"] == ""
    assert baseline["pipeline"]["adetailer_enabled"] is False
    assert baseline["pipeline"]["apply_global_positive_txt2img"] is False
    assert baseline["pipeline"]["apply_global_negative_txt2img"] is False
    assert baseline["prompt_optimizer"] == {"enabled": False}


def test_probe_preview_confirms_then_admits_each_recipe_once(probe_env):
    env = probe_env
    probe = design(env.context)
    batch = env.coordinator.prepare_probe(payload(env.context, probe), env.context)
    assert env.repository.count() == 0
    assert "new images: 4" in batch.confirmation
    assert env.context.target.identity.sha256 in batch.confirmation
    assert "nothing is classified" in batch.confirmation
    (entry,) = batch.experiments
    configs = [record.config["txt2img"] for record in entry.records]
    assert [(c["steps"], c["cfg_scale"], c["width"]) for c in configs] == [
        (30, 6.0, 1024),
        (25, 7.0, 512),
    ]
    assert {c["sampler_name"] for c in configs} == {"DPM++ 2M", "Euler a"}
    for record in entry.records:
        assert record.positive_prompt == probe.prompt
        assert "masterpiece" not in record.positive_prompt
        assert [stage.stage_type for stage in record.stages if stage.enabled] == ["txt2img"]
        assert record.workload.metadata[STUDY_TYPE]["sha256"] == probe.sha256
    assert len({record.seed for record in entry.records}) == 1

    outcome = env.coordinator.admit(batch, env.context, confirmed=True)
    assert outcome.admitted == (probe.experiment_id,)
    assert env.repository.count() == 2
    saved = env.store.load_session(probe.experiment_id)
    assert (
        saved["current_experiment"]["metadata"]["qualification_batch"]["admission"] == "confirmed"
    )
    assert (
        json.loads(saved["current_experiment"]["execution_snapshot_json"])["study_type"]
        == STUDY_TYPE
    )

    from src.gui.controllers.model_evidence_probe import describe_sessions, probe_sessions

    (session,) = probe_sessions(env.store, probe.sha256)
    assert session.experiment_id == probe.experiment_id and len(session.statuses) == 2
    assert probe_sessions(env.store, "e" * 64) == ()
    assert RECIPES["sdxl"].label in describe_sessions([session])

    again = env.coordinator.prepare_probe(payload(env.context, probe), env.context)
    assert "already queued" in again.confirmation
    assert env.coordinator.admit(again, env.context, confirmed=True).existing == (
        probe.experiment_id,
    )
    assert env.repository.count() == 2


def test_probe_refuses_unverified_or_changed_checkpoint(probe_env):
    env = probe_env
    probe = replace(design(env.context), sha256="b" * 64)
    with pytest.raises(ValueError, match="not the verified file"):
        env.coordinator.prepare_probe(payload(env.context, probe), env.context)
    assert env.repository.count() == 0


def test_probe_requires_confirmation(probe_env):
    env = probe_env
    batch = env.coordinator.prepare_probe(payload(env.context, design(env.context)), env.context)
    with pytest.raises(ValueError, match="confirmation"):
        env.coordinator.admit(batch, env.context, confirmed=False)
    assert env.repository.count() == 0


def test_suggestions_lead_with_evidence_then_lineage_defaults():
    keys = [r.key for r in suggest_recipes(family="sdxl", variant="sdxl_turbo")]
    assert keys[0] == "sdxl_turbo" and "sdxl" in keys and len(keys) <= 4
    hinted = [r.key for r in suggest_recipes(family="unknown", base_model_hint="SD 1.5")]
    assert hinted[0] == "sd15"
