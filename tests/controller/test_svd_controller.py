from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from src.controller.svd_controller import SVDController
from src.pipeline.job_requests_v2 import PipelineRunRequest
from src.video.svd_config import SVDConfig


def test_submit_svd_job_enqueues_svd_native_njr(tmp_path) -> None:
    captured = {}
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")

    def _enqueue_njrs(njrs, request: PipelineRunRequest):
        captured["njrs"] = njrs
        captured["request"] = request
        return ["job-svd-001"]

    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(enqueue_njrs=_enqueue_njrs),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())

    job_id = controller.submit_svd_job(
        source_image_path=source_path,
        config=SVDConfig(),
    )

    assert job_id == "job-svd-001"
    njr = captured["njrs"][0]
    assert njr.start_stage == "svd_native"
    assert njr.input_image_paths == [str(source_path)]
    assert [stage.stage_type for stage in njr.stage_chain] == ["svd_native"]
    request = captured["request"]
    assert request.prompt_pack_id == "svd_native"
    assert request.requested_job_label == "SVD Img2Vid"
