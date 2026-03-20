from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image

from src.video import container_metadata


def test_write_video_container_metadata_uses_standard_ffmpeg_tags(
    monkeypatch,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"mp4")
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")
    calls: list[list[str]] = []

    monkeypatch.setattr(container_metadata, "resolve_ffmpeg_executable", lambda: ffmpeg_path)

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        Path(cmd[-1]).write_bytes(b"mp4-with-meta")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(container_metadata.subprocess, "run", _fake_run)

    ok = container_metadata.write_video_container_metadata(
        video_path,
        {
            "stage": "video_workflow",
            "backend_id": "comfy",
            "job_id": "job-123",
            "run_id": "run-123",
            "prompt": "cinematic dolly shot",
            "negative_prompt": "blurry",
            "workflow_id": "ltx_multiframe_anchor_v1",
            "config": {"fps": 16, "strength": 0.45},
            "manifest_path": str(tmp_path / "manifests" / "clip.json"),
        },
    )

    assert ok is True
    ffmpeg_cmd = calls[-1]
    assert ffmpeg_cmd[0] == str(ffmpeg_path)
    assert "-codec" in ffmpeg_cmd
    assert "copy" in ffmpeg_cmd
    metadata_args = [
        ffmpeg_cmd[index + 1]
        for index, value in enumerate(ffmpeg_cmd[:-1])
        if value == "-metadata"
    ]
    assert any(item.startswith("title=clip") for item in metadata_args)
    assert any(item.startswith("software=StableNew") for item in metadata_args)
    assert any(item.startswith("comment=video_workflow | comfy") for item in metadata_args)
    description = next(item[len("description=") :] for item in metadata_args if item.startswith("description="))
    description_payload = json.loads(description)
    assert description_payload["schema"] == container_metadata.VIDEO_CONTAINER_METADATA_SCHEMA
    assert description_payload["workflow_id"] == "ltx_multiframe_anchor_v1"
    assert description_payload["config"]["fps"] == 16


def test_read_video_container_metadata_uses_ffprobe_tags(monkeypatch, tmp_path: Path) -> None:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"mp4")
    ffprobe_path = tmp_path / "ffprobe.exe"
    ffprobe_path.write_bytes(b"")

    monkeypatch.setattr(container_metadata, "_resolve_ffprobe_executable", lambda: ffprobe_path)
    monkeypatch.setattr(
        container_metadata.subprocess,
        "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps(
                {
                    "format": {
                        "tags": {
                            "title": "clip",
                            "software": "StableNew",
                            "comment": "video_workflow | comfy",
                        }
                    }
                }
            ),
            "",
        ),
    )

    tags = container_metadata.read_video_container_metadata(video_path)

    assert tags["title"] == "clip"
    assert tags["software"] == "StableNew"
    assert tags["comment"] == "video_workflow | comfy"


def test_write_and_read_gif_container_metadata(tmp_path: Path) -> None:
    gif_path = tmp_path / "clip.gif"
    frame0 = Image.new("RGB", (8, 8), "red")
    frame1 = Image.new("RGB", (8, 8), "blue")
    frame0.save(gif_path, format="GIF", save_all=True, append_images=[frame1], duration=80, loop=0)

    ok = container_metadata.write_video_container_metadata(
        gif_path,
        {
            "stage": "assembled_video",
            "backend_id": "stablenew",
            "prompt": "looping hero shot",
            "config": {"fps": 12},
        },
    )

    assert ok is True
    tags = container_metadata.read_video_container_metadata(gif_path)
    payload = json.loads(tags["comment"])
    assert payload["schema"] == container_metadata.VIDEO_CONTAINER_METADATA_SCHEMA
    assert payload["stage"] == "assembled_video"
    assert payload["config"]["fps"] == 12
