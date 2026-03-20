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
    assert request.prompt_pack_id == "video_workflow"
    assert "video_workflow" in request.tags
