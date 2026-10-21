"""PR-VID-GOV-316: the approved TI2V-5B 1.2.0 on the canonical path, and old jobs still replaying.

Real VideoWorkflowController -> NJR -> JobService -> SQLite -> run_njr -> Comfy adapter with a fake
Comfy client. Proves a new 1.2.0 job needs and records no opt-in, a job built *before* the promotion
(recorded ``experimental_opt_in: true`` on 1.2.0, or on the still-experimental 1.1.0) still runs and
replays on the same path, and that replay keeps the recorded intent unchanged.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.video_workflow_controller import VideoWorkflowController
from src.queue.job_model import JobStatus
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry
from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
from tests.video.test_pr_vid_190_comfy_lifecycle_frame_count import _backend, _FakeManager
from tests.video.test_wan22_experimental_workflow import WAN_ID, _FakeComfy


def _form(version: str, **overrides):
    form = {
        "workflow_id": WAN_ID,
        "workflow_version": version,
        "prompt": "the person waves at the camera",
        "negative_prompt": "",
        "seed": "4242",
    }
    form.update(overrides)
    return form


def _pre_promotion_registry() -> WorkflowRegistry:
    """The catalog as it was before PR-VID-GOV-316: every TI2V version experimental."""

    registry = WorkflowRegistry()
    for workflow_id in build_default_workflow_registry().list_workflow_ids():
        for version in build_default_workflow_registry().list_versions(workflow_id):
            spec = build_default_workflow_registry().get(
                workflow_id, version, allow_experimental=True
            )
            if workflow_id == WAN_ID and spec.governance_state == "approved":
                spec = dataclasses.replace(spec, governance_state="experimental")
            registry.register(spec)
    return registry


def _video_controller(
    tmp_path: Path, service, registry: WorkflowRegistry | None = None
) -> VideoWorkflowController:
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(
        app_controller=app,
        workflow_registry=DefaultWorkflowRegistryPort(registry) if registry is not None else None,
    )


def _submit(tmp_path: Path, service, form, *, registry: WorkflowRegistry | None = None) -> str:
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "navy").save(source)
    return _video_controller(tmp_path, service, registry).submit_video_workflow_job(
        source_image_path=source, form_data=form
    )


def _stage(queue, job_id: str) -> dict:
    return queue.get_job(job_id)._normalized_record.stage_chain[0].to_dict()["extra"]


def _stack(tmp_path: Path):
    client = _FakeComfy(tmp_path)
    repository, queue, service, controller = _build_stack(
        tmp_path, [_backend(client, _FakeManager())]
    )
    return client, repository, queue, service, controller


def test_a_new_approved_ti2v_job_needs_and_records_no_opt_in_and_replays(tmp_path: Path) -> None:
    client, repository, queue, service, controller = _stack(tmp_path)
    job_id = _submit(tmp_path, service, _form("1.2.0"))  # no opt-in anywhere in the form

    stage = _stage(queue, job_id)
    assert stage["video_execution"]["experimental_opt_in"] is False
    assert stage["video_execution"]["workflow_version"] == "1.2.0"
    assert stage["frame_count"] == 49 and stage["seed"] == 4242
    record = queue.get_job(job_id)._normalized_record
    assert record.extra_metadata["video_workflow"]["governance_state"] == "approved"
    assert record.extra_metadata["video_workflow"]["experimental_opt_in"] is False

    service.runner.run_once(queue.get_job(job_id))
    done = repository.get_job(job_id)
    assert done is not None and done.status is JobStatus.COMPLETED
    assert len(client.queued) == 1

    assert controller.replay_job_from_history(job_id) == 1
    [replay] = queue.list_jobs(JobStatus.QUEUED)
    replayed = replay._normalized_record
    assert replayed.job_id != job_id and replayed.source.parent_job_id == job_id
    assert replayed.stage_chain[0].to_dict()["extra"]["video_execution"] == stage["video_execution"]
    service.runner.run_once(replay)
    assert repository.get_job(replayed.job_id).status is JobStatus.COMPLETED
    assert len(client.queued) == 2
    service.runner.stop()
    repository.close()


def test_a_ti2v_1_2_0_job_recorded_with_an_opt_in_before_the_promotion_still_runs_and_replays(
    tmp_path: Path,
) -> None:
    client, repository, queue, service, controller = _stack(tmp_path)
    job_id = _submit(
        tmp_path,
        service,
        _form("1.2.0", experimental_opt_in=True),
        registry=_pre_promotion_registry(),  # what the builder recorded while 1.2.0 was experimental
    )
    stage = _stage(queue, job_id)
    assert stage["video_execution"]["experimental_opt_in"] is True
    assert (
        queue.get_job(job_id)._normalized_record.extra_metadata["video_workflow"][
            "governance_state"
        ]
        == "experimental"
    )  # the history keeps the governance the job was admitted under

    service.runner.run_once(queue.get_job(job_id))  # the production registry now approves 1.2.0
    done = repository.get_job(job_id)
    assert done is not None and done.status is JobStatus.COMPLETED
    assert len(client.queued) == 1

    assert controller.replay_job_from_history(job_id) == 1
    [replay] = queue.list_jobs(JobStatus.QUEUED)
    assert (
        replay._normalized_record.stage_chain[0].to_dict()["extra"]["video_execution"]
        == (stage["video_execution"])
    )  # replay copies the recorded intent; it neither upgrades nor drops it
    service.runner.run_once(replay)
    assert repository.get_job(replay._normalized_record.job_id).status is JobStatus.COMPLETED
    service.runner.stop()
    repository.close()


def test_a_still_experimental_ti2v_1_1_0_job_runs_with_its_recorded_opt_in_and_is_refused_without(
    tmp_path: Path,
) -> None:
    client, repository, queue, service, _pipeline_controller = _stack(tmp_path)
    ticked = _submit(tmp_path, service, _form("1.1.0", experimental_opt_in=True))
    assert _stage(queue, ticked)["video_execution"]["experimental_opt_in"] is True
    service.runner.run_once(queue.get_job(ticked))
    assert repository.get_job(ticked).status is JobStatus.COMPLETED
    assert len(client.queued) == 1

    # Admission still refuses an un-opted-in 1.1.0 job before it can be queued.
    controller = _video_controller(tmp_path, service)
    ok, reason = controller.validate_form_data(_form("1.1.0"))
    assert not ok and "Enable experimental workflow" in str(reason)
    ok, reason = controller.validate_form_data(_form("1.2.0"))
    assert ok, reason
    service.runner.stop()
    repository.close()
