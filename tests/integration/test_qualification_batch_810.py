"""Synthetic qualification batches over real JobService/SQLite and Learning compilation."""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.controller.job_service import JobService
from src.generation_profiles.evidence_catalog import Claim, EvidenceCatalog, EvidenceRecord
from src.gui.controllers.model_evidence_proposals import compile_qualification_state
from src.gui.learning_state import LearningExperiment, LearningState
from src.learning.evidence_autopilot import EvidenceProposalPlanner
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_store import LearningExperimentStore
from src.learning.qualification_batch import QualificationBatchService
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller.test_job_service_unit import FakeRunner
from tests.learning_v2.test_evidence_autopilot_800 import context as context_fixture
from tests.learning_v2.test_profile_publication_660 import make_publication

PROMPT = ("a lighthouse at dusk", "blurry", {"prompt_source": "custom"})


@pytest.fixture
def batch_env(tmp_path, monkeypatch):
    context = context_fixture.__wrapped__(tmp_path)
    resolver = make_publication(tmp_path).resolver
    monkeypatch.setattr("src.generation_profiles.identity.ModelIdentityResolver", lambda: resolver)
    context = replace(
        context,
        catalog=EvidenceCatalog(
            (
                *context.catalog.records,
                EvidenceRecord(
                    "batch-sampler",
                    "checkpoint",
                    "sdxl",
                    "exact",
                    (
                        Claim(
                            "sampler_name",
                            "DPM++ 2M",
                            "community",
                            "https://example.com",
                            "2026-10-28",
                            "hypothesis",
                            "low",
                        ),
                    ),
                    sha256=context.target.identity.sha256,
                ),
            )
        ),
    )
    plan = EvidenceProposalPlanner().plan(context)
    ids = tuple(p.proposal_id for p in plan.proposals if p.runnable)
    assert len(ids) == 3
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    runner = FakeRunner()
    service = JobService(
        JobQueue(repository=repository), runner=runner, require_normalized_records=True
    )
    visible = LearningState()
    execution = LearningExecutionController(visible, service)
    store = LearningExperimentStore(tmp_path / "experiments")
    coordinator = QualificationBatchService(store, execution, compile_qualification_state)
    yield SimpleNamespace(
        context=context,
        plan=plan,
        ids=ids,
        repository=repository,
        runner=runner,
        service=service,
        visible=visible,
        execution=execution,
        store=store,
        coordinator=coordinator,
        root=tmp_path,
    )
    execution.close()
    repository.close()


def prepare(env, ids=None):
    return env.coordinator.prepare(env.plan, ids or env.ids, env.context, PROMPT)


def admit(env, batch):
    return env.coordinator.admit(batch, env.context, confirmed=True)


def terminal(env, entry, *, status=JobStatus.COMPLETED, readback="valid", missing=False):
    variant = entry.state.plan[0]
    paths = [env.root / f"{variant.job_id}-{i}.png" for i in range(6)]
    if not missing:
        for path in paths:
            path.write_bytes(b"synthetic artifact")
    setting = entry.records[0].extra_metadata["learning"]["variable_under_test"]
    # Runtime readback uses the canonical internal tested variable.
    from src.learning.evidence_proposals import variable_name

    name = variable_name(setting)
    observed = variant.param_value if readback == "valid" else "mismatched"
    result = {
        "variants": [
            {
                "output_paths": [str(p) for p in paths],
                "all_seeds": list(range(42, 48)),
                "final_prompt": PROMPT[0],
                "dispatched_settings": {name: variant.param_value},
                "backend_reported_settings": {} if readback == "missing" else {name: observed},
            }
        ]
    }
    job = env.repository.get_job_model(variant.job_id)
    if status != JobStatus.CANCELLED:
        job = env.repository.transition_job(job, JobStatus.RUNNING)
    job = env.repository.transition_job(
        job,
        status,
        result=result if status == JobStatus.COMPLETED else None,
        error_message="synthetic failure" if status == JobStatus.FAILED else None,
    )
    env.service._emit("job_finished" if status == JobStatus.COMPLETED else "job_failed", job)
    return variant


@pytest.mark.parametrize("count", [1, 3])
def test_batch_admits_once_and_repeat_preserves_exact_jobs(batch_env, count):
    env = batch_env
    ids = env.ids[:count]
    batch = prepare(env, ids)
    assert env.repository.count() == 0
    assert f"New images: {12 * count}" in batch.confirmation
    assert env.context.target.identity.sha256 in batch.confirmation
    assert "Prompt source: custom" in batch.confirmation
    outcome = admit(env, batch)
    assert len(outcome.admitted) == count, outcome.describe()
    assert not outcome.stopped
    assert env.repository.count() == 2 * count
    existing = prepare(env, ids)
    assert all(not e.records for e in existing.experiments)
    repeated = admit(env, existing)
    assert repeated.existing == ids
    assert env.repository.count() == 2 * count
    assert env.visible.current_experiment is None
    assert not env.runner.started
    assert len(env.service._listeners["job_finished"]) == 1
    assert not (env.root / "profiles").exists()
    assert not (env.root / "ratings.jsonl").exists()


def test_one_bad_design_refuses_entire_selection_and_preserves_edits(batch_env):
    env = batch_env
    first = prepare(env)
    identity = env.ids[-1]
    payload = env.store.load_session(identity)
    payload["current_experiment"]["values"] = [999]
    payload["current_experiment"]["metadata"]["selected_items"] = [999]
    env.store.save_session(display_name="edited", experiment_id=identity, payload=payload)
    prior = env.store.session_path_for(identity).read_bytes()
    with pytest.raises(ValueError):
        prepare(env)
    with pytest.raises(ValueError, match="Library changed"):
        admit(env, first)
    assert env.store.session_path_for(identity).read_bytes() == prior
    assert env.repository.count() == 0


@pytest.mark.parametrize("drift", ["resources", "model", "catalog", "baseline"])
def test_confirmation_revalidates_all_before_first_admission(batch_env, drift):
    env = batch_env
    batch = prepare(env)
    context = env.context
    if drift == "resources":
        context = replace(context, resources={**context.resources, "samplers": ["Euler"]})
    elif drift == "catalog":
        context = replace(context, catalog=EvidenceCatalog())
    elif drift == "model":
        identity = replace(context.target.identity, sha256="b" * 64)
        context = replace(context, target=replace(context.target, identity=identity))
    else:
        baseline = copy.deepcopy(context.baseline)
        baseline["txt2img"]["steps"] = 40
        context = replace(context, baseline=baseline)
    with pytest.raises(ValueError, match="stale"):
        env.coordinator.admit(batch, context, confirmed=True)
    assert env.repository.count() == 0


@pytest.mark.parametrize(
    "mode,confirmed_count", [("refused", 1), ("lost_response", 2), ("unknown", 1)]
)
def test_partial_or_ambiguous_submission_stops_without_retry(
    batch_env, monkeypatch, mode, confirmed_count
):
    env = batch_env
    batch = prepare(env)
    submit = env.service.submit_njrs
    calls = []

    def fault(records, policy):
        calls.append(records)
        if len(calls) == 2:
            if mode == "lost_response":
                submit(records, policy)
            if mode == "unknown":
                monkeypatch.setattr(
                    env.repository,
                    "get_job_model",
                    lambda _id: (_ for _ in ()).throw(RuntimeError("repository unavailable")),
                )
            raise RuntimeError("synthetic response failure")
        return submit(records, policy)

    monkeypatch.setattr(env.service, "submit_njrs", fault)
    outcome = admit(env, batch)
    assert len(calls) == 2
    assert len(outcome.admitted) == confirmed_count, outcome.describe()
    assert outcome.stopped and "do not retry" in outcome.stopped.lower()
    assert env.repository.count() == 2 * confirmed_count
    assert all(v.job_id for v in batch.experiments[1].state.plan)
    saved = env.store.load_session(env.ids[1])
    assert all(v["job_id"] for v in saved["plan"])
    if mode != "lost_response":
        with pytest.raises(ValueError, match="Do not retry"):
            prepare(env)
    else:
        remaining = prepare(env)
        assert not remaining.experiments[0].records and not remaining.experiments[1].records
        assert remaining.experiments[2].records
    assert len(calls) == 2


def test_completion_during_admission_and_visible_switch_keeps_every_mapping(batch_env, monkeypatch):
    env = batch_env
    batch = prepare(env)
    submit = env.service.submit_njrs
    entered = []

    def complete_inside(records, policy):
        ids = submit(records, policy)
        if not entered:
            entered.append(True)
            terminal(env, batch.experiments[0])
        return ids

    monkeypatch.setattr(env.service, "submit_njrs", complete_inside)
    assert not admit(env, batch).stopped
    variant = batch.experiments[0].state.plan[0]
    assert variant.status == "completed", variant.execution_metadata
    env.visible.current_experiment = LearningExperiment(name="unrelated", experiment_id="unrelated")
    env.visible.plan = []
    env.execution.reconcile()
    other = terminal(env, batch.experiments[1])
    assert other.status == "completed"
    assert other.execution_metadata["qualification_tested_value_verified"] is True
    saved = env.store.load_session(env.ids[1])
    assert saved["plan"][0]["status"] == "completed"
    assert env.visible.current_experiment.experiment_id == "unrelated"
    assert env.visible.plan == []
    assert len(env.execution._job_contexts) == 4


@pytest.mark.parametrize(
    "readback,missing", [("valid", False), ("missing", False), ("mismatch", False), ("valid", True)]
)
def test_restart_restores_all_mapping_and_evidence_truth(batch_env, readback, missing):
    env = batch_env
    batch = prepare(env)
    assert not admit(env, batch).stopped
    terminal(env, batch.experiments[0], readback=readback, missing=missing)
    terminal(env, batch.experiments[1], status=JobStatus.FAILED)
    terminal(env, batch.experiments[2], status=JobStatus.CANCELLED)
    env.execution.close()
    restored = LearningExecutionController(LearningState(), env.service)
    coordinator = QualificationBatchService(env.store, restored, compile_qualification_state)
    try:
        assert set(coordinator.restore()) == set(env.ids)
        first = restored._sessions[env.ids[0]].plan[0]
        assert first.status == ("completed" if readback == "valid" else "uncontrolled")
        assert first.execution_metadata["controlled_evidence_valid"] is (readback == "valid")
        if missing:
            assert first.execution_metadata["missing_output_paths"]
        assert restored._sessions[env.ids[1]].plan[0].status == "failed"
        assert restored._sessions[env.ids[2]].plan[0].status == "cancelled"
        assert len(restored._job_contexts) == 3
        assert len(env.service._listeners["job_finished"]) == 1
        assert env.repository.count() == 6
    finally:
        restored.close()


def test_explicit_confirmation_and_cancellation_are_admission_boundaries(batch_env):
    env = batch_env
    batch = prepare(env)
    with pytest.raises(ValueError, match="confirmation"):
        env.coordinator.admit(batch, env.context, confirmed=False)
    outcome = env.coordinator.admit(batch, env.context, confirmed=True, cancelled=lambda: True)
    assert outcome.stopped and not outcome.admitted
    assert env.repository.count() == 0


def test_changed_last_compiler_refuses_before_any_submission(batch_env):
    env = batch_env
    batch = prepare(env)
    freeze = env.coordinator.freeze

    def fail(state, context, build):
        if not build and state.current_experiment.experiment_id == env.ids[-1]:
            raise ValueError("last experiment backend preflight failed")
        return freeze(state, context, build)

    env.coordinator.freeze = fail
    with pytest.raises(ValueError, match="backend preflight"):
        admit(env, batch)
    assert env.repository.count() == 0


def test_stale_visible_run_and_save_cannot_duplicate_or_erase_batch_admission(batch_env):
    from src.gui.controllers.learning_controller import LearningController

    env = batch_env
    batch = prepare(env, env.ids[:1])
    stale = copy.deepcopy(env.store.load_session(env.ids[0]))
    controller = LearningController(
        env.visible,
        execution_controller=env.execution,
        pipeline_controller=SimpleNamespace(_job_service=env.service),
    )
    assert controller.restore_resume_state(stale)
    assert not admit(env, batch).stopped
    controller.app_state = SimpleNamespace(resources=env.context.resources)
    controller._learning_policy_resolver = lambda _name: env.context.target.policy
    controller._evidence_catalog_provider = lambda: env.context.catalog
    controller._evidence_identity_resolver = lambda _name: env.context.target
    controller.build_plan(env.visible.current_experiment)
    with pytest.raises(ValueError, match="already has recorded admission"):
        controller.run_plan()
    assert env.repository.count() == 2
    with pytest.raises(ValueError, match="Saved batch associations"):
        env.store.save_session(display_name="stale", payload=stale, experiment_id=env.ids[0])
    assert all(v["job_id"] for v in env.store.load_session(env.ids[0])["plan"])


def test_worker_restart_uses_canonical_foreground_state_and_existing_ui_dispatcher(batch_env):
    import threading

    from src.gui.controllers.learning_controller import LearningController

    env = batch_env
    batch = prepare(env, env.ids[:1])
    assert not admit(env, batch).stopped
    payload = env.store.load_session(env.ids[0])
    controller = LearningController(
        env.visible,
        execution_controller=env.execution,
        pipeline_controller=SimpleNamespace(_job_service=env.service),
    )
    assert controller.restore_resume_state(payload)
    # Complete in SQLite without delivering a live event (the restart gap).
    entry = batch.experiments[0]
    callbacks = env.service._listeners["job_finished"]
    env.service._listeners["job_finished"] = []
    terminal(env, entry)
    env.service._listeners["job_finished"] = callbacks
    queued = []
    env.service.set_event_dispatcher(queued.append)
    presentations = []
    env.execution.set_presentation_callback(
        lambda _variant, _result: presentations.append(threading.get_ident())
    )
    worker_errors = []

    def restore():
        try:
            env.coordinator.restore()
        except Exception as exc:
            worker_errors.append(exc)

    worker = threading.Thread(target=restore)
    worker.start()
    worker.join(5)
    assert not worker.is_alive() and not worker_errors
    assert not presentations
    assert queued
    for callback in queued:
        callback()
    assert presentations == [threading.get_ident()]
    assert env.visible.plan[0].status == "completed"
    saved = env.store.load_session(env.ids[0])
    assert saved["plan"][0]["status"] == "completed"
    assert saved["plan"][0]["execution_metadata"]["qualification_tested_value_verified"]


def test_stale_terminal_checkpoint_preserves_newer_library_projection_and_review_drafts(batch_env):
    env = batch_env
    batch = prepare(env, env.ids[:1])
    assert not admit(env, batch).stopped
    stale = env.store.load_session(env.ids[0])
    terminal(env, batch.experiments[0])
    stale["review_drafts"] = {"operator draft": {"rating": 4}}
    env.store.save_session(display_name="review", payload=stale, experiment_id=env.ids[0])
    saved = env.store.load_session(env.ids[0])
    assert saved["plan"][0]["status"] == "completed"
    assert saved["review_drafts"] == stale["review_drafts"]


def test_last_draft_edited_during_admission_is_preserved(batch_env, monkeypatch):
    env = batch_env
    batch = prepare(env)
    submit = env.service.submit_njrs
    edited = []

    def edit_after_first(records, policy):
        ids = submit(records, policy)
        payload = env.store.load_session(env.ids[1])
        payload["current_experiment"]["description"] = "operator edit during admission"
        env.store.save_session(display_name="edited", payload=payload, experiment_id=env.ids[1])
        edited.append(env.store.session_path_for(env.ids[1]).read_bytes())
        return ids

    monkeypatch.setattr(env.service, "submit_njrs", edit_after_first)
    outcome = admit(env, batch)
    assert len(outcome.admitted) == 1
    assert "Library changed" in outcome.stopped
    assert env.store.session_path_for(env.ids[1]).read_bytes() == edited[0]
    assert env.repository.count() == 2


def test_background_completion_preserves_newer_review_and_authoring_fields(batch_env):
    env = batch_env
    batch = prepare(env, env.ids[:1])
    assert not admit(env, batch).stopped
    saved = env.store.load_session(env.ids[0])
    saved["review_drafts"] = {"operator image": {"rating": 5, "notes": "keep"}}
    saved["current_experiment"]["description"] = "operator's updated hypothesis"
    env.store.save_session(display_name="Learning", payload=saved, experiment_id=env.ids[0])
    terminal(env, batch.experiments[0])
    updated = env.store.load_session(env.ids[0])
    assert updated["plan"][0]["status"] == "completed"
    assert updated["review_drafts"] == saved["review_drafts"]
    assert (
        updated["current_experiment"]["description"] == saved["current_experiment"]["description"]
    )


@pytest.mark.parametrize("after_commit", [False, True])
def test_checkpoint_failure_preserves_writeahead_ids_and_stops(
    batch_env, monkeypatch, after_commit
):
    env = batch_env
    batch = prepare(env)
    save = env.store.save_session

    def fail_save(**kwargs):
        if env.repository.count() and after_commit:
            raise OSError("checkpoint disk failure")
        if not after_commit:
            save(**kwargs)  # File committed, but its response was lost before submit.
            raise OSError("write response lost")
        return save(**kwargs)

    monkeypatch.setattr(env.store, "save_session", fail_save)
    outcome = admit(env, batch)
    assert outcome.stopped
    assert len(outcome.admitted) == (1 if after_commit else 0)
    assert env.repository.count() == (2 if after_commit else 0)
    saved = env.store.load_session(env.ids[0])
    assert all(v["job_id"] for v in saved["plan"])
    assert not env.store.load_session(env.ids[1])["plan"]


def test_mid_batch_cancel_reports_prefix_and_never_submits_next(batch_env):
    env = batch_env
    batch = prepare(env)
    outcome = env.coordinator.admit(
        batch, env.context, confirmed=True, cancelled=lambda: env.repository.count() >= 2
    )
    assert len(outcome.admitted) == 1 and "Cancelled" in outcome.stopped
    assert env.repository.count() == 2
    assert not env.store.load_session(env.ids[1])["plan"]


def test_saved_context_is_reused_and_conflicting_prompt_drafts_are_preserved(batch_env):
    env = batch_env
    prepare(env)
    assert env.coordinator.saved_prompt_context(env.ids)[:2] == PROMPT[:2]
    saved = env.store.load_session(env.ids[0])
    saved["current_experiment"]["prompt_text"] = "different prompt"
    env.store.save_session(display_name="Edited", payload=saved, experiment_id=env.ids[0])
    with pytest.raises(ValueError, match="different prompt contexts"):
        env.coordinator.saved_prompt_context(env.ids)
    assert env.repository.count() == 0
