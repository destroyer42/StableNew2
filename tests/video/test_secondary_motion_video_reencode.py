from __future__ import annotations

from pathlib import Path

from src.video.motion.secondary_motion_video_reencode import apply_secondary_motion_to_video


def test_apply_secondary_motion_to_video_promotes_reencoded_artifact(tmp_path: Path, monkeypatch) -> None:
    source_video = tmp_path / "clip.mp4"
    source_video.write_bytes(b"mp4")
    extracted_frame = tmp_path / "extracted_000001.png"
    motion_frame = tmp_path / "motion_000001.png"
    extracted_frame.write_bytes(b"png")
    motion_frame.write_bytes(b"png")
    promoted_paths: dict[str, object] = {}

    monkeypatch.setattr(
        "src.video.motion.secondary_motion_video_reencode._extract_video_frames",
        lambda **_kwargs: [extracted_frame],
    )
    monkeypatch.setattr(
        "src.video.motion.secondary_motion_video_reencode.run_secondary_motion_worker",
        lambda _payload: {
            "status": "applied",
            "policy_id": "workflow_motion_v1",
            "output_paths": [str(motion_frame)],
        },
    )

    def _fake_export(*, image_paths, output_path, fps):
        promoted_paths["image_paths"] = [str(path) for path in image_paths]
        promoted_paths["output_path"] = str(output_path)
        promoted_paths["fps"] = fps
        output_path.write_bytes(b"mp4")

    monkeypatch.setattr(
        "src.video.motion.secondary_motion_video_reencode.export_image_sequence_video",
        _fake_export,
    )

    result = apply_secondary_motion_to_video(
        video_path=source_video,
        output_dir=tmp_path,
        runtime_block={
            "enabled": True,
            "policy_id": "workflow_motion_v1",
            "backend_mode": "apply_shared_postprocess_candidate",
            "seed": 7,
            "regions": ["hair"],
            "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
            "policy": {
                "enabled": True,
                "policy_id": "workflow_motion_v1",
                "backend_mode": "apply_shared_postprocess_candidate",
            },
        },
        fps=12,
    )

    assert result["primary_path"] == str(tmp_path / "clip_secondary_motion.mp4")
    assert result["source_video_path"] == str(source_video)
    assert result["secondary_motion_summary"]["status"] == "applied"
    assert result["secondary_motion_summary"]["application_path"] == "video_reencode_worker"
    assert result["secondary_motion"]["apply_result"]["source_video_path"] == str(source_video)
    assert result["secondary_motion"]["apply_result"]["reencoded_video_path"] == str(
        tmp_path / "clip_secondary_motion.mp4"
    )
    assert promoted_paths == {
        "image_paths": [str(motion_frame)],
        "output_path": str(tmp_path / "clip_secondary_motion.mp4"),
        "fps": 12,
    }


def test_apply_secondary_motion_to_video_records_unavailable_when_ffmpeg_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_video = tmp_path / "clip.mp4"
    source_video.write_bytes(b"mp4")

    monkeypatch.setattr(
        "src.video.motion.secondary_motion_video_reencode.resolve_ffmpeg_executable",
        lambda: None,
    )

    result = apply_secondary_motion_to_video(
        video_path=source_video,
        output_dir=tmp_path,
        runtime_block={
            "enabled": True,
            "policy_id": "workflow_motion_v1",
            "backend_mode": "apply_shared_postprocess_candidate",
            "intent": {"enabled": True, "mode": "apply", "intent": "micro_sway"},
            "policy": {
                "enabled": True,
                "policy_id": "workflow_motion_v1",
                "backend_mode": "apply_shared_postprocess_candidate",
            },
        },
        fps=8,
    )

    assert result["primary_path"] == str(source_video)
    assert result["video_path"] == str(source_video)
    assert result["secondary_motion_summary"]["status"] == "unavailable"
    assert result["secondary_motion_summary"]["skip_reason"] == "ffmpeg_unavailable"
    assert result["secondary_motion_summary"]["application_path"] == "video_reencode_worker"
    assert result["secondary_motion"]["apply_result"]["source_video_path"] == str(source_video)