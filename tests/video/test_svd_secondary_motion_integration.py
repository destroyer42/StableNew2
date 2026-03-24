from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from src.video.svd_config import SVDConfig
from src.video.svd_models import SVDPreprocessResult
from src.video.svd_runner import SVDRunner


def test_svd_secondary_motion_integration_writes_manifest_and_container_summary(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    prepared_path = tmp_path / "_svd_temp" / "job-1" / "prepared.png"
    output_video = tmp_path / "svd_source.mp4"

    preprocess = SVDPreprocessResult(
        source_path=source_path,
        prepared_path=prepared_path,
        original_width=640,
        original_height=360,
        target_width=1024,
        target_height=576,
        resize_mode="letterbox",
        was_resized=True,
        was_padded=True,
        was_cropped=False,
    )
    secondary_motion_block = {
        "schema": "stablenew.secondary-motion-provenance.v1",
        "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
        "policy": {
            "enabled": True,
            "policy_id": "svd_secondary_motion_v1",
            "backend_mode": "apply_shared_postprocess_candidate",
            "intensity": 0.25,
            "cap_pixels": 12,
        },
        "apply_result": {
            "status": "applied",
            "application_path": "frame_directory_worker",
            "metrics": {"frames_in": 1, "frames_out": 1, "intensity": 0.25, "cap_pixels": 12},
        },
        "summary": {
            "schema": "stablenew.secondary-motion-summary.v1",
            "enabled": True,
            "status": "applied",
            "policy_id": "svd_secondary_motion_v1",
            "application_path": "frame_directory_worker",
            "intent": {"mode": "apply", "intent": "micro_sway"},
            "backend_mode": "apply_shared_postprocess_candidate",
            "skip_reason": "",
            "metrics": {"intensity": 0.25, "cap_pixels": 12},
        },
    }

    monkeypatch.setattr("src.video.svd_runner.prepare_svd_input", lambda **_kwargs: preprocess)
    monkeypatch.setattr(
        "src.video.svd_runner.SVDPostprocessRunner.process_frames",
        lambda self, **kwargs: (kwargs["frames"], {"applied": ["secondary_motion"], "secondary_motion": secondary_motion_block}),
    )
    monkeypatch.setattr("src.video.svd_runner.export_video_mp4", lambda **_kwargs: output_video)
    write_container_metadata = Mock(return_value=True)
    monkeypatch.setattr("src.video.svd_runner.write_video_container_metadata", write_container_metadata)

    class _FakeService:
        def generate_frames(self, **_kwargs):
            return [Image.new("RGB", (32, 32), "white")]

        def _release_runtime_memory(self) -> None:
            return None

    runner = SVDRunner(service=_FakeService(), output_root=tmp_path)

    result = runner.run(source_image_path=source_path, config=SVDConfig(), job_id="job-1")

    assert result.metadata_path is not None
    manifest_payload = json.loads(Path(result.metadata_path).read_text(encoding="utf-8"))
    assert manifest_payload["secondary_motion"]["summary"]["status"] == "applied"
    assert manifest_payload["secondary_motion"]["summary"]["application_path"] == "frame_directory_worker"

    container_payload = write_container_metadata.call_args.args[1]
    assert container_payload["secondary_motion_summary"]["status"] == "applied"
    assert container_payload["secondary_motion_summary"]["policy_id"] == "svd_secondary_motion_v1"