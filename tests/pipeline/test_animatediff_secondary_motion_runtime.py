from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from src.pipeline.executor import Pipeline
from src.pipeline.animatediff_models import AnimateDiffCapability


_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRX0AAAAASUVORK5CYII="
)


def test_run_animatediff_stage_records_unavailable_secondary_motion_and_uses_original_frames(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = Mock()
    client.get_animatediff_capability.return_value = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sd_v15_v2.ckpt"],
    )
    client.img2img.return_value = {
        "images": [_TINY_PNG_BASE64, _TINY_PNG_BASE64],
        "info": json.dumps(
            {
                "seed": 123,
                "subseed": 456,
                "extra_generation_params": {"AnimateDiff": {"fps": 12}},
            }
        ),
    }

    pipeline = Pipeline(client, Mock())
    pipeline._ensure_webui_true_ready = lambda: None
    pipeline._check_webui_health_before_stage = lambda stage: None
    pipeline._load_image_base64 = lambda path: _TINY_PNG_BASE64

    encoded_paths: list[str] = []
    container_payloads: list[dict[str, object]] = []

    def _fake_create_video(self, image_paths, output_path, fps=24, codec="libx264", quality="medium"):
        encoded_paths[:] = [str(path) for path in image_paths]
        output_path.write_bytes(b"video")
        return True

    def _raise_motion_failure(*, runtime_block, input_dir, output_dir):
        raise RuntimeError("motion unavailable")

    monkeypatch.setattr("src.pipeline.executor._apply_secondary_motion_frame_directory", _raise_motion_failure)
    monkeypatch.setattr("src.pipeline.executor.VideoCreator.create_video_from_images", _fake_create_video)
    monkeypatch.setattr(
        "src.pipeline.executor.write_video_container_metadata",
        lambda _path, payload: container_payloads.append(dict(payload)) or True,
    )

    result = pipeline.run_animatediff_stage(
        input_image_path=tmp_path / "seed.png",
        prompt="animate this",
        negative_prompt="",
        config={
            "enabled": True,
            "motion_module": "mm_sd_v15_v2.ckpt",
            "fps": 12,
            "secondary_motion": {
                "enabled": True,
                "policy_id": "animatediff_motion_v1",
                "backend_mode": "apply_shared_postprocess_candidate",
                "seed": 7,
                "regions": ["hair"],
                "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
                "policy": {
                    "enabled": True,
                    "policy_id": "animatediff_motion_v1",
                    "backend_mode": "apply_shared_postprocess_candidate",
                },
            },
        },
        output_dir=tmp_path,
        image_name="animatediff_motion_unavailable",
    )

    assert result is not None
    assert result["secondary_motion"]["summary"]["status"] == "unavailable"
    assert result["secondary_motion"]["summary"]["skip_reason"] == "worker_failed"
    assert result["secondary_motion_summary"]["status"] == "unavailable"
    assert result["secondary_motion_summary"]["application_path"] == "frame_directory_worker"
    assert encoded_paths == [
        str(tmp_path / "animatediff_motion_unavailable_frames" / "frame_000000.png"),
        str(tmp_path / "animatediff_motion_unavailable_frames" / "frame_000001.png"),
    ]
    assert container_payloads[0]["secondary_motion_summary"]["status"] == "unavailable"
