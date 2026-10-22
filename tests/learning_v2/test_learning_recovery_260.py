"""Restart/admission truth using real compiler output and disposable SQLite."""

from __future__ import annotations

import copy
import json
import threading
from collections import defaultdict
from types import SimpleNamespace

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState
from src.learning.execution_controller import LearningExecutionController
from src.learning.learning_record import LearningRecordWriter
from src.queue.job_model import Job, JobStatus
from src.queue.job_repository import JobRepository
from tests.learning_v2.test_model_comparison_140 import baseline, controller_for, experiment


class RepositoryService:
    """Admission fake; never dispatches and exposes only the canonical repository."""

    def __init__(self, repository):
        self.history_store = repository
        self.listeners = defaultdict(list)
        self.calls = []
        self.mode = "success"

    def register_callback(self, event, callback):
        self.listeners[event].append(callback)

    def submit_njrs(self, records, policy):
        self.calls.append(list(records))
        if self.mode == "raise_before":
            raise RuntimeError("admission refused")
        if self.mode not in {"empty", "partial"}:
            self.history_store.record_job_submissions(
                [Job(record.job_id, _normalized_record=record) for record in records]
            )
        if self.mode in {"empty", "ambiguous"}:
            return []
        if self.mode == "partial":
            return [records[0].job_id]
        if self.mode == "raise_after":
            raise RuntimeError("response lost after commit")
        return [record.job_id for record in records]

    def finish(self, job):
        for callback in self.listeners["job_finished"]:
            callback(job)


@pytest.fixture
def repository(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    yield repo
    repo.close()


def planned(tmp_path, repository, *, comparison=False):
    exp = (
        experiment(tmp_path, models=["ordinary.safetensors", "peer.safetensors"])
        if comparison
        else LearningExperiment(
            name="recovery",
            experiment_id="recovery",
            prompt_text="portrait",
            variable_under_test="CFG Scale",
            values=[6.0, 7.0, 8.0],
            images_per_value=2,
        )
    )
    controller = controller_for(exp, baseline())
    service = RepositoryService(repository)
    controller.pipeline_controller = SimpleNamespace(_job_service=service)
    controller.execution_controller = LearningExecutionController(
        controller.learning_state, service
    )
    controller.execution_controller.set_completion_callback(
        controller._apply_variant_completion_evidence
    )
    controller.execution_controller.set_presentation_callback(
        controller._on_variant_completion_published
    )
    controller.execution_controller.set_failure_callback(controller._on_variant_job_failed)
    return controller, service


def recreated(payload, repository, *, plan_table=None):
    service = RepositoryService(repository)
    state = LearningState()
    controller = LearningController(
        state, pipeline_controller=SimpleNamespace(_job_service=service), plan_table=plan_table
    )
    assert controller.restore_resume_state(copy.deepcopy(payload))
    return controller, service


def transition(repository, job_id, status, result=None, error=None):
    job = repository.get_job_model(job_id)
    if job.status == JobStatus.QUEUED and status != JobStatus.CANCELLED:
        job = repository.transition_job(job, JobStatus.RUNNING)
    return repository.transition_job(job, status, result=result, error_message=error)


def result_for(tmp_path, *, seeds=True, profile="forge-profile-1"):
    paths = [str(tmp_path / "one.png"), str(tmp_path / "two.png")]
    for path in paths:
        from PIL import Image

        Image.new("RGB", (8, 8)).save(path)
    payload = {
        "output_paths": paths,
        "final_prompt": "portrait",
        "runtime_admission": {"launch_profile": profile},
    }
    if seeds:
        payload.update(all_seeds=[42, 43], all_subseeds=[700, 701])
    return {"variants": [payload]}


@pytest.mark.parametrize("comparison", [False, True])
def test_restart_recovers_repository_truth_without_submission(tmp_path, repository, comparison):
    controller, service = planned(tmp_path, repository, comparison=comparison)
    controller.run_plan()
    state = controller.learning_state
    state.selected_variant = state.plan[0]
    state.review_drafts = {"keep": {"rating": 4, "notes": "draft"}}
    payload = json.loads(json.dumps(controller.export_resume_state()))
    ids = [v.job_id for v in state.plan]
    del controller, service, state
    completed = result_for(tmp_path)
    transition(repository, ids[0], JobStatus.COMPLETED, completed)
    transition(repository, ids[1], JobStatus.FAILED, error="backend interrupted")
    restored, fresh_service = recreated(payload, repository)
    first, second = restored.learning_state.plan[:2]
    assert first.status == "completed"
    assert first.image_refs == completed["variants"][0]["output_paths"]
    assert first.completed_images == 2
    assert first.execution_metadata["controlled_evidence_valid"] is True
    assert second.status == "failed"
    assert "backend interrupted" in str(second.execution_metadata)
    assert restored.learning_state.selected_variant is first
    assert restored.learning_state.review_drafts == {"keep": {"rating": 4, "notes": "draft"}}
    assert fresh_service.calls == []
    assert len(fresh_service.listeners["job_finished"]) == 1


@pytest.mark.parametrize("mode", ["empty", "partial"])
def test_unsuccessful_admission_never_reports_queued(tmp_path, repository, mode):
    controller, service = planned(tmp_path, repository)
    service.mode = mode
    with pytest.raises(RuntimeError):
        controller.run_plan()
    assert all(v.status == "pending" for v in controller.learning_state.plan)
    assert not controller.execution_controller._job_to_variant
    assert repository.list_job_models() == []


def test_admission_checkpoints_resume_immediately(tmp_path, repository):
    controller, service = planned(tmp_path, repository)
    saved = []
    controller.add_resume_state_listener(
        lambda: saved.append(copy.deepcopy(controller.export_resume_state()))
    )
    controller.run_plan()
    assert len(saved) == 1
    assert [item["job_id"] for item in saved[0]["plan"]] == [r.job_id for r in service.calls[0]]


def test_completion_does_not_increment_existing_artifacts_twice(tmp_path, repository):
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    variant = controller.learning_state.plan[0]
    variant.image_refs = result_for(tmp_path)["variants"][0]["output_paths"]
    variant.completed_images = 2
    job = transition(repository, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path))
    service.finish(job)
    service.finish(job)
    assert variant.completed_images == 2
    assert len(variant.image_refs) == 2


@pytest.mark.parametrize("mode", ["raise_before", "ambiguous", "raise_after"])
def test_admission_exception_checks_actual_repository_admission(tmp_path, repository, mode):
    controller, service = planned(tmp_path, repository)
    service.mode = mode
    saved = []
    controller.add_resume_state_listener(
        lambda: saved.append(copy.deepcopy(controller.export_resume_state()))
    )
    with pytest.raises(RuntimeError):
        controller.run_plan()
    jobs = repository.list_job_models()
    if mode == "raise_before":
        assert not jobs
        assert all(not v.job_id and v.status == "pending" for v in controller.learning_state.plan)
        assert not controller.execution_controller._job_to_variant
    else:
        assert {job.job_id for job in jobs} == {v.job_id for v in controller.learning_state.plan}
        assert all(
            v.status == "queued" and v.execution_metadata["admission_error"]
            for v in controller.learning_state.plan
        )
        assert controller.get_workflow_state() == "action_required"
        assert saved[-1]["plan"][0]["job_id"]
    controller.run_plan() if mode != "raise_before" else None
    assert len(service.calls) == 1


def test_checkpoint_failure_keeps_confirmed_admission_and_prevents_retry(tmp_path, repository):
    controller, service = planned(tmp_path, repository)

    def fail_save():
        raise OSError("disk full")

    controller.add_resume_state_listener(fail_save)
    with pytest.raises(RuntimeError, match="checkpoint failed.*disk full"):
        controller.run_plan()
    assert len(repository.list_job_models()) == len(controller.learning_state.plan)
    assert all(v.status == "queued" and v.job_id for v in controller.learning_state.plan)
    assert (
        controller.learning_state.current_experiment.metadata["resume_persistence_error"]
        == "disk full"
    )
    assert controller.get_workflow_state() == "action_required"
    controller.run_plan()
    assert len(service.calls) == 1


def test_restored_queued_completion_repeat_restore_and_duplicate_notification(tmp_path, repository):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    restored, service = recreated(payload, repository)
    execution = restored.execution_controller
    calls = []
    original = restored._apply_variant_completion_evidence
    execution.set_completion_callback(
        lambda variant, result: (calls.append(variant.job_id), original(variant, result))
    )
    variant = restored.learning_state.plan[0]
    job = transition(repository, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path))
    service.finish(job)
    service.finish(job)
    execution.on_job_failed(job.job_id, RuntimeError("late duplicate failure"))
    restored.restore_resume_state(copy.deepcopy(payload))
    restored.restore_resume_state(copy.deepcopy(payload))
    variant = restored.learning_state.plan[0]
    assert calls == [job.job_id]
    assert variant.status == "completed"
    assert variant.completed_images == 2
    assert len(variant.image_refs) == 2
    assert len(service.listeners["job_finished"]) == 1
    assert len(execution._job_to_variant) == len(payload["plan"]) - 1
    assert not service.calls


def test_completion_during_stale_read_waits_for_identity_then_wins(
    tmp_path, repository, monkeypatch
):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    state = LearningState()
    service = RepositoryService(repository)
    restored = LearningController(state, pipeline_controller=SimpleNamespace(_job_service=service))
    lookup = repository.get_job_model
    target = payload["plan"][0]["job_id"]
    delivered = []

    def race(job_id):
        stale = lookup(job_id)
        if job_id == target and not delivered:
            delivered.append(job_id)
            running = repository.transition_job(stale, JobStatus.RUNNING)
            job = repository.transition_job(
                running, JobStatus.COMPLETED, result=result_for(tmp_path)
            )
            service.finish(job)
        return stale

    monkeypatch.setattr(repository, "get_job_model", race)
    assert restored.restore_resume_state(payload)
    variant = state.plan[0]
    assert variant.status == "completed"
    assert variant.completed_images == 2
    assert variant.execution_metadata["controlled_evidence_valid"] is True
    assert not service.calls


def test_worker_completion_during_restore_is_delivered_on_ui_dispatch(
    tmp_path, repository, monkeypatch
):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    state = LearningState()
    service = RepositoryService(repository)
    restored = LearningController(state, pipeline_controller=SimpleNamespace(_job_service=service))
    ui_calls = []
    delivered = threading.Event()
    lookup = repository.get_job_model
    target = payload["plan"][0]["job_id"]
    workers = []

    def race(job_id):
        stale = lookup(job_id)
        if job_id == target and not workers:

            def finish():
                running = repository.transition_job(stale, JobStatus.RUNNING)
                job = repository.transition_job(
                    running, JobStatus.COMPLETED, result=result_for(tmp_path)
                )
                ui_calls.append(lambda: service.finish(job))
                delivered.set()

            worker = threading.Thread(target=finish)
            workers.append(worker)
            worker.start()
            assert delivered.wait(5)
        return stale

    monkeypatch.setattr(repository, "get_job_model", race)
    restored.restore_resume_state(payload)
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()
    assert state.plan[0].status == "queued"
    for callback in ui_calls:
        callback()
    assert state.plan[0].status == "completed"
    assert state.plan[0].completed_images == 2


def test_switch_experiments_discards_old_mapping_and_legacy_delivery(tmp_path, repository):
    first, _ = planned(tmp_path, repository)
    first.run_plan()
    restored, service = recreated(first.export_resume_state(), repository)
    old_job = restored.learning_state.plan[0].job_id
    second = copy.deepcopy(first.export_resume_state())
    second["current_experiment"]["experiment_id"] = "other"
    for item in second["plan"]:
        item.update(
            experiment_id="other",
            variant_id="other:" + item["variant_id"],
            job_id="",
            status="pending",
        )
    restored.restore_resume_state(second)
    before = restored.learning_state.to_dict()
    job = transition(repository, old_job, JobStatus.COMPLETED, result_for(tmp_path))
    service.finish(job)
    restored.on_job_completed_callback(job, {"success": True})
    assert restored.learning_state.to_dict() == before
    assert not restored.execution_controller._job_to_variant


def test_gpu_quarantine_is_read_only_and_interrupted_status_is_visible(tmp_path, repository):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    quarantine = {"active": True, "reason": "GPU device loss"}
    repository.set_setting("gpu_dispatch_quarantine", quarantine)
    job_id = payload["plan"][0]["job_id"]
    repository.transition_job(repository.get_job_model(job_id), JobStatus.RUNNING)
    assert repository.recover_interrupted_jobs() == 1
    restored, service = recreated(payload, repository)
    variant = restored.learning_state.plan[0]
    assert variant.status == "failed"
    assert variant.execution_metadata["action_required"] is True
    assert (
        variant.execution_metadata["recovery_identifier"] == "INTERRUPTED_RESTART_ACTION_REQUIRED"
    )
    assert restored.learning_state.plan[1].status == "queued"
    assert repository.get_setting("gpu_dispatch_quarantine") == quarantine
    assert not service.calls


@pytest.mark.parametrize("fault", ["experiment", "variant", "job_id", "missing", "snapshot"])
def test_missing_or_conflicting_identity_stays_unresolved(tmp_path, repository, fault):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    original_id = payload["plan"][0]["job_id"]
    if fault == "experiment":
        payload["current_experiment"]["experiment_id"] = "wrong"
    elif fault == "variant":
        payload["plan"][0]["variant_id"] = "wrong"
    elif fault == "job_id":
        payload["plan"][0]["job_id"] = ""
    elif fault == "missing":
        payload["plan"][0]["job_id"] = "missing-job"
    else:
        with repository.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET njr_snapshot = ? WHERE job_id = ?", ("{}", original_id)
            )
    restored, service = recreated(payload, repository)
    variant = restored.learning_state.plan[0]
    assert variant.status == "requires_attention"
    assert variant.execution_metadata["reconciliation_error"]
    assert variant.job_id == payload["plan"][0]["job_id"]
    assert not service.calls
    assert variant.job_id not in restored.execution_controller._job_to_variant


@pytest.mark.parametrize("case", ["seed", "profile", "deleted"])
def test_recovered_evidence_never_invents_missing_readback_or_files(tmp_path, repository, case):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    result = result_for(tmp_path, seeds=case != "seed", profile="profile-new")
    if case == "profile":
        payload["current_experiment"]["metadata"]["observed_launch_profile"] = "profile-old"
    if case == "deleted":
        from pathlib import Path

        Path(result["variants"][0]["output_paths"][0]).unlink()
    transition(repository, payload["plan"][0]["job_id"], JobStatus.COMPLETED, result)
    restored, _ = recreated(payload, repository)
    variant = restored.learning_state.plan[0]
    assert variant.completed_images == 2
    if case == "deleted":
        assert variant.execution_metadata["missing_output_paths"]
        assert variant.status == "completed"
    else:
        assert variant.status == "uncontrolled"
        assert variant.execution_metadata["controlled_evidence_valid"] is False
        assert variant.execution_metadata["seed_validation_reason"] == (
            "seed_readback_unavailable" if case == "seed" else "backend_restart_boundary"
        )


def test_saved_ratings_drafts_uncontrolled_evidence_and_selection_survive(tmp_path, repository):
    controller, service = planned(tmp_path, repository)
    writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    controller._learning_record_writer = writer
    controller.run_plan()
    variant = controller.learning_state.plan[0]
    service.finish(
        transition(
            repository, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path, seeds=False)
        )
    )
    controller.learning_state.selected_variant = variant
    controller.learning_state.review_drafts = {"keep": {"rating": 3, "notes": "unsaved"}}
    controller.record_rating(variant.image_refs[0], 4, notes="keep saved rating")
    payload = controller.export_resume_state()
    before = writer.records_path.read_bytes()
    restored, _ = recreated(payload, repository)
    restored._learning_record_writer = writer
    restored.load_existing_ratings()
    recovered = restored.learning_state.plan[0]
    assert recovered.status == "uncontrolled"
    assert recovered.execution_metadata["controlled_evidence_valid"] is False
    assert restored.learning_state.selected_variant is recovered
    assert restored.learning_state.review_drafts == {"keep": {"rating": 3, "notes": "unsaved"}}
    assert restored.get_rating_for_image(recovered.image_refs[0]) == 4
    restored.restore_resume_state(payload)
    assert writer.records_path.read_bytes() == before


def test_recreated_controller_reuses_one_listener_pair_and_closed_owner_is_inert(
    tmp_path, repository
):
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    controller.execution_controller.close()
    state = LearningState()
    restored = LearningController(state, pipeline_controller=SimpleNamespace(_job_service=service))
    restored.restore_resume_state(payload)
    assert len(service.listeners["job_finished"]) == len(service.listeners["job_failed"]) == 1
    job = transition(repository, state.plan[0].job_id, JobStatus.COMPLETED, result_for(tmp_path))
    service.finish(job)
    assert state.plan[0].status == "completed"
    assert controller.learning_state.plan[0].status == "queued"


@pytest.mark.parametrize("status", [JobStatus.RUNNING, JobStatus.CANCELLED])
def test_restores_actual_running_or_cancelled_without_reviving_work(tmp_path, repository, status):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    job_id = payload["plan"][0]["job_id"]
    job = repository.get_job_model(job_id)
    repository.transition_job(
        job, status, error_message="operator cancelled" if status == JobStatus.CANCELLED else None
    )
    restored, service = recreated(payload, repository)
    assert restored.learning_state.plan[0].status == status.value
    assert not service.calls
    if status == JobStatus.CANCELLED:
        assert (
            "operator cancelled" in restored.learning_state.plan[0].execution_metadata["job_error"]
        )


@pytest.mark.parametrize("lost_response", [False, True])
def test_synchronous_completion_during_admission_cannot_be_downgraded(
    tmp_path, repository, lost_response
):
    controller, service = planned(tmp_path, repository)
    submit = service.submit_njrs

    def immediate(records, policy):
        result = submit(records, policy)
        service.finish(
            transition(repository, records[0].job_id, JobStatus.COMPLETED, result_for(tmp_path))
        )
        return [] if lost_response else result

    service.submit_njrs = immediate
    if lost_response:
        with pytest.raises(RuntimeError, match="requires attention"):
            controller.run_plan()
    else:
        controller.run_plan()
    variant = controller.learning_state.plan[0]
    assert variant.status == "completed"
    assert variant.completed_images == 2
    assert variant.execution_metadata["controlled_evidence_valid"] is True
    assert variant.job_id == service.calls[0][0].job_id


@pytest.mark.parametrize(
    "prompt,reason",
    [
        ("", "lora_readback_unavailable"),
        ("portrait <lora:adapter:0.25>", "lora_strength_mismatch"),
        ("portrait <lora:adapter:0.5>", "valid"),
    ],
)
def test_recovery_reuses_lora_execution_validation(tmp_path, repository, prompt, reason):
    from src.gui.learning_state import LearningVariant
    from tests.learning_v2.test_pr_learn_300_lora_strength import _controller

    controller, _experiment = _controller()
    state = controller.learning_state
    variant = LearningVariant(param_value={"name": "adapter", "weight": 0.5}, planned_images=1)
    state.plan = [variant]
    service = RepositoryService(repository)
    execution = LearningExecutionController(state, service)
    execution.set_completion_callback(controller._on_variant_job_completed)
    controller.execution_controller = execution
    controller.run_plan()
    payload = controller.export_resume_state()
    path = result_for(tmp_path)["variants"][0]["output_paths"][0]
    result = {"variants": [{"path": path, "all_seeds": [12345], "final_prompt": prompt}]}
    transition(repository, variant.job_id, JobStatus.COMPLETED, result)
    restored, _ = recreated(payload, repository)
    recovered = restored.learning_state.plan[0]
    assert recovered.execution_metadata["variable_validation_reason"] == reason
    assert recovered.execution_metadata["controlled_evidence_valid"] is (reason == "valid")
    assert recovered.status == ("completed" if reason == "valid" else "uncontrolled")


def test_run_cannot_resubmit_stale_pending_variant_with_existing_job_id(tmp_path, repository):
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    controller.learning_state.plan[0].status = "pending"
    controller.run_plan()
    assert len(service.calls) == 1


def test_duplicate_persisted_identity_cannot_duplicate_recovered_artifacts(tmp_path, repository):
    controller, _ = planned(tmp_path, repository)
    controller.run_plan()
    payload = controller.export_resume_state()
    payload["plan"].append(copy.deepcopy(payload["plan"][0]))
    restored, service = recreated(payload, repository)
    assert restored.learning_state.plan[0].status == "requires_attention"
    assert restored.learning_state.plan[-1].status == "requires_attention"
    job_id = payload["plan"][0]["job_id"]
    service.finish(transition(repository, job_id, JobStatus.COMPLETED, result_for(tmp_path)))
    assert restored.learning_state.plan[0].image_refs == []
    assert restored.learning_state.plan[-1].image_refs == []


def malformed_result(tmp_path, fault):
    result = result_for(tmp_path)
    result["output_paths"] = list(result["variants"][0]["output_paths"])
    if fault == "runtime_admission":
        result["variants"][0]["runtime_admission"] = "corrupt persisted readback"
    elif fault == "metadata":
        result["metadata"] = "corrupt metadata"
    elif fault == "variants":
        result["variants"] = {"corrupt": "not a list"}
    elif fault == "variant_item":
        result["variants"].insert(0, "corrupt variant")
    elif fault == "launch_profile":
        result["variants"][0]["runtime_admission"]["launch_profile"] = ["not a profile"]
    elif fault == "final_prompt":
        result["variants"][0]["final_prompt"] = {"not": "prompt text"}
    else:
        result["variants"][0]["artifact"] = {"output_paths": 42}
    return result


@pytest.mark.parametrize(
    "fault",
    [
        "runtime_admission",
        "metadata",
        "variants",
        "variant_item",
        "launch_profile",
        "final_prompt",
        "artifact_paths",
    ],
)
def test_malformed_completion_is_atomic_uncontrolled_and_repeatable(tmp_path, repository, fault):
    source, _ = planned(tmp_path, repository)
    source.run_plan()
    saved = source.export_resume_state()
    saved["review_drafts"] = {"keep": {"rating": 3, "notes": "preserve"}}
    result = malformed_result(tmp_path, fault)
    job_id = saved["plan"][0]["job_id"]
    # A malformed artifact readback is introduced only in the returned object:
    # repository admission/lifecycle remain their existing supported contract.
    stored = result_for(tmp_path) if fault == "artifact_paths" else result
    transition(repository, job_id, JobStatus.COMPLETED, stored)
    service = RepositoryService(repository)
    restored = LearningController(
        LearningState(), pipeline_controller=SimpleNamespace(_job_service=service)
    )
    if fault == "artifact_paths":
        lookup = repository.get_job_model

        def malformed_lookup(identity):
            job = lookup(identity)
            if identity == job_id:
                job.result = result
            return job

        service.history_store = SimpleNamespace(get_job_model=malformed_lookup)
    assert restored.restore_resume_state(copy.deepcopy(saved))
    first = restored.learning_state.plan[0]
    assert first.status == "uncontrolled"
    assert first.execution_metadata["controlled_evidence_valid"] is False
    assert first.execution_metadata["reconciliation_error"]
    assert first.execution_metadata["action_required"] is True
    assert first.job_id == job_id
    assert first.image_refs == result["output_paths"]
    assert first.completed_images == 2
    assert not restored.learning_state.current_experiment.metadata.get("observed_seed_vector")
    assert not restored.learning_state.current_experiment.metadata.get("observed_launch_profile")
    before = copy.deepcopy(restored.learning_state.to_dict())
    assert restored.restore_resume_state(copy.deepcopy(saved))
    assert restored.learning_state.to_dict() == before
    record, _, _ = restored.build_rating_record(
        restored.learning_state.current_experiment,
        restored.learning_state.plan[0],
        first.image_refs[0],
        4,
        "",
        None,
    )
    assert record.metadata["frozen_experiment"]["controlled_evidence_valid"] is False
    assert restored.learning_state.review_drafts == saved["review_drafts"]
    assert all(v.status == "queued" for v in restored.learning_state.plan[1:])
    assert not service.calls


def test_live_malformed_completion_cannot_cache_success_or_fabricate_rating(tmp_path, repository):
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    variant = controller.learning_state.plan[0]
    job = transition(
        repository,
        variant.job_id,
        JobStatus.COMPLETED,
        malformed_result(tmp_path, "runtime_admission"),
    )
    service.finish(job)
    before = copy.deepcopy(controller.learning_state.to_dict())
    service.finish(job)
    assert controller.learning_state.to_dict() == before
    assert variant.status == "uncontrolled"
    assert variant.execution_metadata["controlled_evidence_valid"] is False
    record, _, _ = controller.build_rating_record(
        controller.learning_state.current_experiment, variant, variant.image_refs[0], 4, "", None
    )
    assert record.metadata["frozen_experiment"]["controlled_evidence_valid"] is False


def test_raising_evidence_callback_cannot_publish_partial_experiment_or_terminal_success(
    tmp_path, repository
):
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    variant = controller.learning_state.plan[0]
    experiment = controller.learning_state.current_experiment
    original_metadata = copy.deepcopy(experiment.metadata)

    def reject(partial, _result):
        partial.execution_metadata.update(controlled_evidence_valid=True, actual_all_seeds=[999])
        experiment.metadata["observed_seed_vector"] = [999]
        raise RuntimeError("evidence interpretation rejected")

    controller.execution_controller.set_completion_callback(reject)
    service.finish(
        transition(repository, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path))
    )
    assert variant.status == "uncontrolled"
    assert variant.execution_metadata["controlled_evidence_valid"] is False
    assert variant.execution_metadata.get("actual_all_seeds") != [999]
    assert experiment.metadata == original_metadata
    assert variant.completed_images == 2
    assert variant.image_refs


def test_reentrant_terminal_notification_cannot_mutate_staged_completion(tmp_path, repository):
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    variant = controller.learning_state.plan[0]
    execution = controller.execution_controller
    interpret = controller._apply_variant_completion_evidence

    def interpret_with_late_failure(current, result):
        interpret(current, result)
        execution._handle_job_failed(
            SimpleNamespace(
                job_id=current.job_id,
                status=JobStatus.FAILED,
                error_message="duplicate terminal notification",
            )
        )

    execution.set_completion_callback(interpret_with_late_failure)
    service.finish(
        transition(repository, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path))
    )
    assert variant.status == "completed"
    assert variant.execution_metadata["controlled_evidence_valid"] is True
    assert not variant.execution_metadata.get("job_error")


def test_rating_requires_positive_interpretation_and_preserves_valid_controlled_evidence(
    tmp_path, repository
):
    controller, service = planned(tmp_path, repository)
    controller.run_plan()
    variant = controller.learning_state.plan[0]
    paths = result_for(tmp_path)["variants"][0]["output_paths"]
    variant.image_refs = paths
    provisional, _, _ = controller.build_rating_record(
        controller.learning_state.current_experiment, variant, paths[0], 4, "", None
    )
    assert provisional.metadata["frozen_experiment"]["controlled_evidence_valid"] is False
    service.finish(
        transition(repository, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path))
    )
    validated, _, _ = controller.build_rating_record(
        controller.learning_state.current_experiment, variant, paths[0], 4, "", None
    )
    assert validated.metadata["frozen_experiment"]["controlled_evidence_valid"] is True
    assert validated.metadata["frozen_experiment"]["actual_all_seeds"] == [42, 43]
