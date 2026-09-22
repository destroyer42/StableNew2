"""PR-VID-130: real VideoWorkflowController -> NJR -> JobService -> SQLite -> run_njr -> Comfy adapter.

Fake Comfy client only.  Proves neutral intent emission, experimental opt-in persistence and replay,
capability-driven admission, and that governance/readiness failures never reach ``queue_prompt``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.result_contract_v26 import collect_canonical_artifacts
from src.queue.job_model import JobStatus
from src.video import ComfyWorkflowVideoBackend
from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_contracts import WorkflowSpec
from src.video.workflow_registry import WorkflowRegistry, build_default_workflow_registry
from tests.integration.test_pr_vid_120_neutral_video_queue import _build_stack
from tests.video.test_wan22_experimental_workflow import WAN_ID, _FakeComfy, _readiness, _stats

LTX_ID = "ltx_multiframe_anchor_v1"


def _images(tmp_path: Path) -> tuple[Path, Path]:
    source, end = tmp_path / "source.png", tmp_path / "end.png"
    Image.new("RGB", (16, 16), "navy").save(source)
    Image.new("RGB", (16, 16), "teal").save(end)
    return source, end


def _capture_controller(tmp_path: Path):
    submitted: list = []
    service = SimpleNamespace(
        submit_njrs=lambda records, _policy: [submitted.extend(records) or "job-x"][0]
    )
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "out"))
    return VideoWorkflowController(app_controller=app), submitted


def _wan_form(**overrides):
    form = {
        "workflow_id": WAN_ID,
        "workflow_version": "1.0.0",
        "prompt": "the person waves at the camera",
        "negative_prompt": "",
        "end_anchor_path": "",
        "mid_anchor_paths": [],
        "experimental_opt_in": True,
    }
    form.update(overrides)
    return form


def _block(record) -> dict:
    stage = record.stage_chain[0].to_dict()
    return stage["extra"]["video_execution"]


def test_ltx_submission_is_rejected_before_queue_admission(tmp_path) -> None:
    _source, _end = _images(tmp_path)
    controller, submitted = _capture_controller(tmp_path)
    ok, reason = controller.validate_form_data({"workflow_id": LTX_ID, "workflow_version": "1.0.0"})
    assert not ok and "not approved" in str(reason)
    assert submitted == []


def test_wan_admission_is_capability_driven_and_records_the_per_job_opt_in(tmp_path) -> None:
    source, end = _images(tmp_path)
    controller, submitted = _capture_controller(tmp_path)

    ok, reason = controller.validate_form_data(_wan_form(experimental_opt_in=False))
    assert not ok and "experimental" in reason and "Enable experimental workflow" in reason
    assert controller.build_default_form_state()["experimental_opt_in"] is False
    for override, fragment in (
        ({"end_anchor_path": str(end)}, "end anchor"),
        ({"prompt": ""}, "needs a prompt"),
        ({"camera_intent": {"preset": "dolly_in", "strength": 0.3}}, "camera intent"),
    ):
        ok, reason = controller.validate_form_data(_wan_form(**override))
        assert not ok and fragment in reason, override

    ok, reason = controller.validate_form_data(_wan_form())
    assert ok, reason  # no end anchor needed for Wan
    controller.submit_video_workflow_job(source_image_path=source, form_data=_wan_form())
    [record] = submitted
    block = _block(record)
    assert block["backend_id"] == "comfy" and block["workflow_id"] == WAN_ID
    assert block["experimental_opt_in"] is True and block["task"] == "image_to_video"
    assert block["controls"] == ["negative_prompt", "prompt_text", "source_image"]
    extra = record.stage_chain[0].to_dict()["extra"]
    assert "end_anchor_path" not in extra and "mid_anchor_paths" not in extra
    assert isinstance(extra["seed"], int)  # recorded for exact replay
    assert extra["source_preparation"]["target_dimensions"] == {"width": 480, "height": 832}


def test_specs_projection_marks_wan_experimental_and_hides_unsupported_inputs(tmp_path) -> None:
    controller, _ = _capture_controller(tmp_path)
    specs = {s["workflow_id"]: s for s in controller.list_workflow_specs()}
    assert specs[WAN_ID]["experimental"] is True and LTX_ID not in specs
    assert specs[WAN_ID]["form_visibility"]["end_anchor"] is False
    assert specs[WAN_ID]["form_visibility"]["experimental"] is True
    assert specs[WAN_ID]["form_visibility"]["seed"] is True


def _wan_backend(tmp_path: Path, client: _FakeComfy, registry: WorkflowRegistry | None = None):
    return ComfyWorkflowVideoBackend(
        client=client,
        workflow_registry=registry or build_default_workflow_registry(),
        process_manager=SimpleNamespace(
            ensure_running=lambda: True, _config=SimpleNamespace(base_url="http://x")
        ),
        readiness=_readiness(client.stats),
    )


def _real_submit(tmp_path: Path, service, form, *, source_dimensions: tuple[int, int] = (16, 16)) -> str:
    source, _ = _images(tmp_path)
    Image.new("RGB", source_dimensions, "navy").save(source)
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app).submit_video_workflow_job(
        source_image_path=source, form_data=form
    )


def test_wan_job_runs_through_queue_sqlite_runner_artifact_and_replays_with_its_opt_in(
    tmp_path,
) -> None:
    client = _FakeComfy(tmp_path)
    repository, queue, service, controller = _build_stack(
        tmp_path, [_wan_backend(tmp_path, client)]
    )
    job_id = _real_submit(tmp_path, service, _wan_form(seed="4242"))

    reloaded = repository.get_job_model(job_id)  # persisted NJR keeps the explicit authorization
    stage = reloaded._normalized_record.stage_chain[0].to_dict()["extra"]
    assert stage["video_execution"]["experimental_opt_in"] is True
    assert stage["video_execution"]["backend_id"] == "comfy"
    assert stage["seed"] == 4242
    queued = queue.get_job(job_id)
    stage = queued._normalized_record.stage_chain[0].to_dict()["extra"]
    service.runner.run_once(queued)
    done = repository.get_job(job_id)
    assert done is not None and done.status is JobStatus.COMPLETED
    assert len(client.queued) == 1
    prompt = client.queued[0]["prompt"]
    assert prompt["8"]["inputs"]["width"] == 480
    assert prompt["8"]["inputs"]["height"] == 832
    assert prompt["9"]["inputs"]["seed"] == 4242
    [artifact] = collect_canonical_artifacts(done.result)
    assert artifact["stage"] == "video_workflow" and Path(artifact["primary_path"]).is_file()

    assert controller.replay_job_from_history(job_id) == 1
    [replay] = queue.list_jobs(JobStatus.QUEUED)
    record = replay._normalized_record
    assert record.job_id != job_id and record.source.parent_job_id == job_id
    assert record.stage_chain[0].to_dict()["extra"]["video_execution"] == stage["video_execution"]
    assert record.stage_chain[0].to_dict()["extra"]["seed"] == stage["seed"]
    service.runner.run_once(replay)
    assert repository.get_job(record.job_id).status is JobStatus.COMPLETED
    assert len(client.queued) == 2
    service.runner.stop()
    repository.close()


def test_wan_landscape_source_freezes_geometry_into_the_compiled_graph_and_result(tmp_path) -> None:
    client = _FakeComfy(tmp_path)
    repository, queue, service, _controller = _build_stack(
        tmp_path, [_wan_backend(tmp_path, client)]
    )
    job_id = _real_submit(
        tmp_path,
        service,
        _wan_form(seed="77"),
        source_dimensions=(160, 90),
    )

    queued = queue.get_job(job_id)
    stage = queued._normalized_record.stage_chain[0].to_dict()["extra"]
    service.runner.run_once(queued)

    done = repository.get_job(job_id)
    assert done is not None and done.status is JobStatus.COMPLETED
    prompt = client.queued[0]["prompt"]
    assert prompt["8"]["inputs"]["width"] == 832
    assert prompt["8"]["inputs"]["height"] == 480
    assert stage["seed"] == 77
    assert stage["source_preparation"]["target_dimensions"] == {"width": 832, "height": 480}
    artifact = done.result["metadata"]["video_workflow_artifact"]
    assert artifact["source_preparation"]["original_source_path"].endswith("source.png")
    service.runner.stop()
    repository.close()


def test_a_job_compiled_without_opt_in_fails_before_queue_prompt(tmp_path) -> None:
    client = _FakeComfy(tmp_path)
    repository, queue, service, _controller = _build_stack(
        tmp_path, [_wan_backend(tmp_path, client)]
    )
    job_id = _real_submit(tmp_path, service, _wan_form())
    record = queue.get_job(job_id)._normalized_record
    assert record  # the controller path always records the choice; forge a job without it:
    blocked = _submit_forged(tmp_path, service, opt_in=False)
    service.runner.run_once(queue.get_job(blocked))
    failed = repository.get_job(blocked)
    assert failed is not None and failed.status is JobStatus.FAILED
    assert "experimental" in str(failed.error_message or failed.result)
    assert client.queued == []
    service.runner.stop()
    repository.close()


def _submit_forged(tmp_path: Path, service, *, opt_in: bool, workflow_id: str = WAN_ID) -> str:
    from src.pipeline.reprocess_builder import ReprocessJobBuilder

    source, _ = _images(tmp_path)
    config = {
        "video_workflow": {
            "enabled": True,
            "workflow_id": workflow_id,
            "workflow_version": "1.0.0",
            "seed": 5,
            "prompt": "wave",
            "negative_prompt": "blurry",
            "video_execution": {
                "backend_id": "comfy",
                "task": "image_to_video",
                "controls": ["negative_prompt", "prompt_text", "source_image"],
                "workflow_id": workflow_id,
                "workflow_version": "1.0.0",
                "experimental_opt_in": opt_in,
            },
        },
        "pipeline": {"video_workflow_enabled": True},
    }
    njr = ReprocessJobBuilder().build_reprocess_job(
        input_image_paths=[str(source)],
        stages=["video_workflow"],
        config=config,
        output_dir=str(tmp_path / "output"),
        prompt="wave",
        negative_prompt="blurry",
        pack_name="Forged",
        source="video_workflow",
    )
    return service.submit_njrs([njr], SubmissionPolicy())[0]


def test_disabled_workflow_cannot_run_even_with_opt_in(tmp_path) -> None:
    (wan,) = [s for s in build_builtin_workflow_specs() if s.workflow_id == WAN_ID]
    registry = WorkflowRegistry()
    registry.register(
        WorkflowSpec(
            **{f: getattr(wan, f) for f in wan.__dataclass_fields__}
            | {"governance_state": "disabled"}
        )
    )
    client = _FakeComfy(tmp_path)
    repository, queue, service, _controller = _build_stack(
        tmp_path, [_wan_backend(tmp_path, client, registry)]
    )
    job_id = _submit_forged(tmp_path, service, opt_in=True)
    service.runner.run_once(queue.get_job(job_id))
    failed = repository.get_job(job_id)
    assert failed is not None and failed.status is JobStatus.FAILED
    assert client.queued == []
    service.runner.stop()
    repository.close()


def test_resource_and_dependency_failures_fail_the_job_before_queue_prompt(tmp_path) -> None:
    for kwargs, fragment in (
        (
            {"stats": _stats(free_mib=1000)},
            "resource",
        ),
        ({"info": {}}, "missing required Comfy dependencies"),
    ):
        client = _FakeComfy(tmp_path, **kwargs)
        stack_dir = tmp_path / fragment[:4]
        stack_dir.mkdir()
        repository, queue, service, _controller = _build_stack(
            stack_dir, [_wan_backend(stack_dir, client)]
        )
        job_id = _submit_forged(stack_dir, service, opt_in=True)
        service.runner.run_once(queue.get_job(job_id))
        failed = repository.get_job(job_id)
        assert failed is not None and failed.status is JobStatus.FAILED
        assert fragment in str(failed.error_message or failed.result)
        assert client.queued == []
        service.runner.stop()
        repository.close()


def test_production_source_has_no_vace_and_the_runner_has_no_model_branching() -> None:
    import re

    root = Path(__file__).resolve().parents[2] / "src"
    runner = (root / "pipeline" / "pipeline_runner.py").read_text(encoding="utf-8").lower()
    assert "wan22" not in runner and "wan2." not in runner
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if re.search(r"vace", path.read_text(encoding="utf-8", errors="ignore"), re.I)
    ]
    assert offenders == []  # VACE-1.3B stays NO-GO and unregistered
