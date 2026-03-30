from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.controller.video_workflow_controller import VideoWorkflowController


class _JobServiceStub:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_njrs(self, njrs, request):
        self.calls.append((list(njrs), request))
        return ["job-video-queued"]


def test_list_workflow_specs_surfaces_governance_metadata() -> None:
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=_JobServiceStub(), output_dir="output")
    )

    specs = controller.list_workflow_specs()

    assert specs
    assert specs[0]["governance_state"] == "approved"
    assert specs[0]["pinned_revision"]


def test_submit_video_workflow_job_builds_queue_backed_reprocess_njr(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    end = tmp_path / "end.png"
    mid = tmp_path / "mid.png"
    for path in (source, end, mid):
        path.write_bytes(b"png")

    job_service = _JobServiceStub()
    app_controller = SimpleNamespace(job_service=job_service, output_dir=str(tmp_path / "output"))
    controller = VideoWorkflowController(app_controller=app_controller)

    job_id = controller.submit_video_workflow_job(
        source_image_path=source,
        form_data={
            "workflow_id": "ltx_multiframe_anchor_v1",
            "workflow_version": "1.0.0",
            "end_anchor_path": str(end),
            "mid_anchor_paths": [str(mid)],
            "prompt": "prompt text",
            "negative_prompt": "negative text",
            "motion_profile": "balanced",
            "output_route": "Testing",
            "continuity_pack_id": "cont-001",
            "continuity_pack_name": "Hero Pack",
            "continuity_pack_summary": {
                "pack_id": "cont-001",
                "display_name": "Hero Pack",
                "character_count": 1,
            },
        },
    )

    assert job_id == "job-video-queued"
    assert len(job_service.calls) == 1
    njrs, request = job_service.calls[0]
    assert len(njrs) == 1
    njr = njrs[0]
    assert njr.start_stage == "video_workflow"
    assert njr.input_image_paths == [str(source)]
    assert njr.config["video_workflow"]["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert njr.config["video_workflow"]["end_anchor_path"] == str(end)
    assert njr.config["video_workflow"]["mid_anchor_paths"] == [str(mid)]
    assert njr.config["video_workflow"]["motion_profile"] == "balanced"
    assert njr.config["pipeline"]["output_route"] == "Testing"
    assert njr.config["metadata"]["continuity"]["pack_id"] == "cont-001"
    assert njr.extra_metadata["continuity"]["pack_id"] == "cont-001"
    assert njr.continuity_link["pack_id"] == "cont-001"
    assert request.prompt_pack_id == "video_workflow"
    assert "video_workflow" in request.tags


def test_conditioned_video_workflow_requires_depth_input_mode(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    end = tmp_path / "end.png"
    for path in (source, end):
        path.write_bytes(b"png")

    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=_JobServiceStub(), output_dir=str(tmp_path / "output"))
    )

    valid, reason = controller.validate_form_data(
        {
            "workflow_id": "ltx_multiframe_anchor_v1_conditioned",
            "workflow_version": "1.0.0",
            "end_anchor_path": str(end),
            "camera_intent": {"preset": "dolly_in", "strength": 0.4},
            "controlnet": {"model": "depth", "weight": 0.9, "guidance_start": 0.1, "guidance_end": 0.9},
            "depth_input": {"mode": "none", "path": ""},
        }
    )

    assert valid is False
    assert "requires depth_input.mode" in str(reason)


def test_submit_conditioned_video_workflow_job_carries_conditioning_payload(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    end = tmp_path / "end.png"
    depth = tmp_path / "depth.png"
    for path in (source, end, depth):
        path.write_bytes(b"png")

    job_service = _JobServiceStub()
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=job_service, output_dir=str(tmp_path / "output"))
    )

    job_id = controller.submit_video_workflow_job(
        source_image_path=source,
        form_data={
            "workflow_id": "ltx_multiframe_anchor_v1_conditioned",
            "workflow_version": "1.0.0",
            "end_anchor_path": str(end),
            "prompt": "prompt text",
            "negative_prompt": "negative text",
            "motion_profile": "balanced",
            "camera_intent": {"preset": "dolly_in", "strength": 0.4},
            "controlnet": {"model": "depth", "weight": 0.9, "guidance_start": 0.1, "guidance_end": 0.9},
            "depth_input": {"mode": "upload", "path": str(depth)},
            "output_route": "Testing",
        },
    )

    assert job_id == "job-video-queued"
    njr = job_service.calls[0][0][0]
    assert njr.config["video_workflow"]["camera_intent"]["preset"] == "dolly_in"
    assert njr.config["video_workflow"]["controlnet"]["weight"] == 0.9
    assert njr.config["video_workflow"]["depth_input"]["path"] == str(depth)
    assert njr.extra_metadata["video_workflow"]["depth_input"]["mode"] == "upload"
