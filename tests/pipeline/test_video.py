"""Tests for FFmpeg resolution in VideoCreator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.pipeline import video
from src.video.video_export import export_video_mp4


def test_resolve_ffmpeg_executable_uses_env_override(monkeypatch, tmp_path: Path):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")

    monkeypatch.setenv("STABLENEW_FFMPEG_PATH", str(ffmpeg_path))
    monkeypatch.setattr(video.shutil, "which", lambda _: None)

    resolved = video.resolve_ffmpeg_executable()

    assert resolved == ffmpeg_path


def test_resolve_ffmpeg_executable_uses_winget_links_when_path_missing(monkeypatch, tmp_path: Path):
    local_appdata = tmp_path / "localappdata"
    ffmpeg_path = local_appdata / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
    ffmpeg_path.parent.mkdir(parents=True)
    ffmpeg_path.write_bytes(b"")

    monkeypatch.delenv("STABLENEW_FFMPEG_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(video.shutil, "which", lambda _: None)

    resolved = video.resolve_ffmpeg_executable()

    assert resolved == ffmpeg_path


def test_video_creator_uses_resolved_ffmpeg_binary(monkeypatch, tmp_path: Path):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")

    monkeypatch.setattr(video, "resolve_ffmpeg_executable", lambda: ffmpeg_path)
    run = Mock(return_value=subprocess.CompletedProcess([str(ffmpeg_path), "-version"], 0))
    monkeypatch.setattr(video.subprocess, "run", run)

    creator = video.VideoCreator()

    assert creator.ffmpeg_available is True
    assert creator.ffmpeg_executable == ffmpeg_path
    run.assert_called_once()
    assert run.call_args.args[0][0] == str(ffmpeg_path)


def test_create_video_from_images_falls_back_to_copy_when_symlink_denied(
    monkeypatch, tmp_path: Path
):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")
    src_image = tmp_path / "frame_a.png"
    src_image.write_bytes(b"PNG")

    monkeypatch.setattr(video, "resolve_ffmpeg_executable", lambda: ffmpeg_path)

    def fake_run(cmd, **kwargs):
        if len(cmd) > 1 and cmd[1] == "-version":
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(video.subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "symlink_to", Mock(side_effect=OSError(1314, "privilege not held")))

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "clip.mp4"
    output_path.parent.mkdir(parents=True)

    ok = creator.create_video_from_images([src_image], output_path)

    assert ok is True


def test_create_video_from_images_uses_concat_input(monkeypatch, tmp_path: Path):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")
    src_image = tmp_path / "frame_a.png"
    src_image.write_bytes(b"PNG")
    calls: list[list[str]] = []

    monkeypatch.setattr(video, "resolve_ffmpeg_executable", lambda: ffmpeg_path)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if len(cmd) > 1 and cmd[1] == "-version":
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(video.subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "symlink_to", Mock(side_effect=OSError(1314, "privilege not held")))

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "clip.mp4"
    output_path.parent.mkdir(parents=True)

    ok = creator.create_video_from_images([src_image], output_path, fps=24)

    assert ok is True
    ffmpeg_cmd = calls[-1]
    assert ffmpeg_cmd[0] == str(ffmpeg_path)
    assert ffmpeg_cmd[1:5] == ["-f", "concat", "-safe", "0"]
    assert "-r" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-frames:v") + 1] == "1"


def test_create_video_from_images_limits_to_valid_temp_image_count(
    monkeypatch, tmp_path: Path
):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")
    missing_image = tmp_path / "missing.png"
    valid_image = tmp_path / "valid.png"
    valid_image.write_bytes(b"PNG")
    calls: list[list[str]] = []

    monkeypatch.setattr(video, "resolve_ffmpeg_executable", lambda: ffmpeg_path)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if len(cmd) > 1 and cmd[1] == "-version":
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(video.subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "symlink_to", Mock(side_effect=OSError(1314, "denied")))

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "clip.mp4"
    output_path.parent.mkdir(parents=True)

    assert creator.create_video_from_images([missing_image, valid_image], output_path, fps=7)
    ffmpeg_cmd = calls[-1]
    assert ffmpeg_cmd[ffmpeg_cmd.index("-frames:v") + 1] == "1"


def test_create_slideshow_video_does_not_add_exact_frame_limit(monkeypatch, tmp_path: Path):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"PNG")
    calls: list[list[str]] = []

    monkeypatch.setattr(video, "resolve_ffmpeg_executable", lambda: ffmpeg_path)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if len(cmd) > 1 and cmd[1] == "-version":
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(video.subprocess, "run", fake_run)

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "slideshow.mp4"
    output_path.parent.mkdir(parents=True)

    assert creator.create_slideshow_video([image_path], output_path, fps=7)
    assert "-frames:v" not in calls[-1]


def _resolve_ffprobe() -> str | None:
    resolved = shutil.which("ffprobe")
    if resolved:
        return resolved
    env_local_appdata = Path(os.environ.get("LOCALAPPDATA", ""))
    candidate = env_local_appdata / "Microsoft" / "WinGet" / "Links" / "ffprobe.exe"
    return str(candidate) if candidate.is_file() else None


@pytest.mark.parametrize("frame_count", [1, 3, 14])
def test_export_video_mp4_decodes_exact_input_frame_count(tmp_path: Path, frame_count: int):
    ffprobe = _resolve_ffprobe()
    if ffprobe is None:
        pytest.skip("ffprobe is not available")

    frames = [
        Image.new("RGB", (64, 64), (index * 37 % 256, 50, 120))
        for index in range(frame_count)
    ]
    output_path = tmp_path / f"sequence_{frame_count}.mp4"
    assert export_video_mp4(frames=frames, output_path=output_path, fps=7)

    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert int(json.loads(probe.stdout)["streams"][0]["nb_read_frames"]) == frame_count
