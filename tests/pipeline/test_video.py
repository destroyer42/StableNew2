"""Tests for FFmpeg resolution in VideoCreator."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

from src.pipeline import video


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
