"""Tests for FFmpeg resolution and encoding in VideoCreator and video export."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError
from src.pipeline import video
from src.video.video_export import export_video_gif, export_video_mp4
from tests.helpers.optional_deps import requires_windows


def test_resolve_ffmpeg_executable_uses_env_override(monkeypatch, tmp_path: Path):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")

    monkeypatch.setenv("STABLENEW_FFMPEG_PATH", str(ffmpeg_path))
    monkeypatch.setattr(video.shutil, "which", lambda _: None)

    resolved = video.resolve_ffmpeg_executable()

    assert resolved == ffmpeg_path


@requires_windows
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


def _fake_ffmpeg(monkeypatch, tmp_path: Path) -> tuple[Path, list[list[str]]]:
    """A resolvable fake FFmpeg: ``-version`` passes, every encode is recorded and succeeds."""

    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_bytes(b"")
    calls: list[list[str]] = []
    monkeypatch.setattr(video, "resolve_ffmpeg_executable", lambda: ffmpeg_path)
    monkeypatch.setattr(
        video.subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0)
    )

    def fake_run_ffmpeg(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(video, "run_ffmpeg", fake_run_ffmpeg)
    return ffmpeg_path, calls


def test_create_video_from_images_falls_back_to_copy_when_symlink_denied(
    monkeypatch, tmp_path: Path
):
    _fake_ffmpeg(monkeypatch, tmp_path)
    src_image = tmp_path / "frame_a.png"
    src_image.write_bytes(b"PNG")
    monkeypatch.setattr(Path, "symlink_to", Mock(side_effect=OSError(1314, "privilege not held")))

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "clip.mp4"
    output_path.parent.mkdir(parents=True)

    assert creator.create_video_from_images([src_image], output_path) is True


def test_create_video_from_images_uses_image2_input_and_quality_encode(monkeypatch, tmp_path: Path):
    ffmpeg_path, calls = _fake_ffmpeg(monkeypatch, tmp_path)
    src_image = tmp_path / "frame_a.png"
    src_image.write_bytes(b"PNG")
    monkeypatch.setattr(Path, "symlink_to", Mock(side_effect=OSError(1314, "privilege not held")))

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "clip.mp4"
    output_path.parent.mkdir(parents=True)

    assert creator.create_video_from_images([src_image], output_path, fps=24) is True
    cmd = calls[-1]
    assert cmd[0] == str(ffmpeg_path)
    assert "concat" not in cmd
    assert cmd[cmd.index("-framerate") + 1] == "24"
    assert cmd[cmd.index("-i") + 1].endswith("frame_%06d.png")
    # The legacy quality argument still picks the x264 preset, but quality is CRF, not x264's 23.
    assert cmd[cmd.index("-crf") + 1] == str(video.DEFAULT_ENCODE_SETTINGS.crf)
    assert cmd[cmd.index("-preset") + 1] == "medium"
    for flag in ("-colorspace", "-color_primaries", "-color_trc"):
        assert cmd[cmd.index(flag) + 1] == "bt709"
    assert "out_color_matrix=bt709" in cmd[cmd.index("-vf") + 1]
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"
    assert cmd[cmd.index("-frames:v") + 1] == "1"


def test_create_video_from_images_stages_in_private_folder(monkeypatch, tmp_path: Path):
    _fake_ffmpeg(monkeypatch, tmp_path)
    src_image = tmp_path / "frame_a.png"
    src_image.write_bytes(b"PNG")
    output_dir = tmp_path / "out"
    user_temp = output_dir / "temp"
    user_temp.mkdir(parents=True)
    (user_temp / "keep.txt").write_text("user data", encoding="utf-8")

    creator = video.VideoCreator()
    assert creator.create_video_from_images([src_image], output_dir / "clip.mp4")

    assert (user_temp / "keep.txt").read_text(encoding="utf-8") == "user data"
    assert [p.name for p in output_dir.iterdir()] == ["temp"]


def test_create_video_from_images_limits_to_valid_temp_image_count(monkeypatch, tmp_path: Path):
    _, calls = _fake_ffmpeg(monkeypatch, tmp_path)
    missing_image = tmp_path / "missing.png"
    valid_image = tmp_path / "valid.png"
    valid_image.write_bytes(b"PNG")
    monkeypatch.setattr(Path, "symlink_to", Mock(side_effect=OSError(1314, "denied")))

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "clip.mp4"
    output_path.parent.mkdir(parents=True)

    assert creator.create_video_from_images([missing_image, valid_image], output_path, fps=7)
    ffmpeg_cmd = calls[-1]
    assert ffmpeg_cmd[ffmpeg_cmd.index("-frames:v") + 1] == "1"


def test_create_video_from_images_cancel_removes_partial_output(monkeypatch, tmp_path: Path):
    _fake_ffmpeg(monkeypatch, tmp_path)
    src_image = tmp_path / "frame_a.png"
    src_image.write_bytes(b"PNG")
    output_path = tmp_path / "out" / "clip.mp4"
    output_path.parent.mkdir(parents=True)

    def cancelled_run(cmd, **kwargs):
        output_path.write_bytes(b"partial")
        raise video.VideoEncodeCancelled("FFmpeg encode cancelled")

    monkeypatch.setattr(video, "run_ffmpeg", cancelled_run)

    with pytest.raises(video.VideoEncodeCancelled):
        video.VideoCreator().create_video_from_images([src_image], output_path)
    assert not output_path.exists()


def test_create_slideshow_video_does_not_add_exact_frame_limit(monkeypatch, tmp_path: Path):
    _, calls = _fake_ffmpeg(monkeypatch, tmp_path)
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"PNG")

    creator = video.VideoCreator()
    output_path = tmp_path / "out" / "slideshow.mp4"
    output_path.parent.mkdir(parents=True)

    assert creator.create_slideshow_video([image_path], output_path, fps=7)
    assert "-frames:v" not in calls[-1]
    assert "-crf" in calls[-1]


@pytest.mark.parametrize(
    ("quality", "expected_crf", "expected_preset"),
    [
        ("medium", 16, "medium"),
        ("veryslow", 16, "veryslow"),
        ("draft", 20, "medium"),
        ("archival", 12, "slow"),
        ("not-a-preset", 16, "slow"),
        (None, 16, "slow"),
    ],
)
def test_resolve_encode_settings(quality, expected_crf, expected_preset):
    settings = video.resolve_encode_settings(quality)
    assert (settings.crf, settings.preset) == (expected_crf, expected_preset)


def test_encode_settings_reject_invalid_values():
    with pytest.raises(ValueError):
        video.VideoEncodeSettings(crf=60)
    with pytest.raises(ValueError):
        video.VideoEncodeSettings(preset="warp")


def test_non_crf_codec_gets_no_crf_flag(tmp_path: Path):
    args = video.build_video_encode_args(
        codec="mpeg4",
        settings=video.DEFAULT_ENCODE_SETTINGS,
        output_path=tmp_path / "clip.webm",
    )
    assert "-crf" not in args and "-preset" not in args
    assert "-movflags" not in args


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
        Image.new("RGB", (64, 64), (index * 37 % 256, 50, 120)) for index in range(frame_count)
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


def _probe_stream(ffprobe: str, path: Path) -> dict:
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,color_space,color_primaries,color_transfer,r_frame_rate,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(probe.stdout)["streams"][0]


def test_export_video_mp4_writes_tagged_bt709_stream_at_requested_fps(tmp_path: Path):
    ffprobe = _resolve_ffprobe()
    if ffprobe is None or video.resolve_ffmpeg_executable() is None:
        pytest.skip("FFmpeg/ffprobe is not available")

    frames = [Image.new("RGB", (64, 48), (index * 40 % 256, 90, 160)) for index in range(6)]
    output_path = tmp_path / "tagged.mp4"
    export_video_mp4(frames=frames, output_path=output_path, fps=7)

    stream = _probe_stream(ffprobe, output_path)
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["r_frame_rate"] == "7/1"
    assert (stream["color_space"], stream["color_primaries"], stream["color_transfer"]) == (
        "bt709",
        "bt709",
        "bt709",
    )
    assert (stream["width"], stream["height"]) == (64, 48)
    assert not [p for p in tmp_path.iterdir() if p.name != "tagged.mp4"]


def test_export_video_mp4_trims_odd_dimensions_to_even(tmp_path: Path):
    ffprobe = _resolve_ffprobe()
    if ffprobe is None or video.resolve_ffmpeg_executable() is None:
        pytest.skip("FFmpeg/ffprobe is not available")

    frames = [Image.new("RGB", (65, 49), (30, 60, 90)) for _ in range(2)]
    output_path = tmp_path / "odd.mp4"
    export_video_mp4(frames=frames, output_path=output_path, fps=8)
    stream = _probe_stream(ffprobe, output_path)
    assert (stream["width"], stream["height"]) == (64, 48)


def test_export_video_gif_uses_global_palette_and_loops(tmp_path: Path):
    if video.resolve_ffmpeg_executable() is None:
        pytest.skip("FFmpeg is not available")

    frames = [Image.new("RGB", (32, 32), (index * 60 % 256, 20, 200)) for index in range(4)]
    output_path = tmp_path / "loop.gif"
    export_video_gif(frames=frames, output_path=output_path, fps=8)

    with Image.open(output_path) as gif:
        assert gif.n_frames == 4
        assert gif.info.get("loop") == 0
    assert not [p for p in tmp_path.iterdir() if p.name != "loop.gif"]


def test_export_video_mp4_cancel_raises_and_leaves_no_output(tmp_path: Path):
    if video.resolve_ffmpeg_executable() is None:
        pytest.skip("FFmpeg is not available")

    class _Cancelled:
        def is_cancelled(self) -> bool:
            return True

    frames = [Image.new("RGB", (64, 64), (10, 20, 30)) for _ in range(3)]
    output_path = tmp_path / "cancelled.mp4"
    with pytest.raises(CancellationError):
        export_video_mp4(frames=frames, output_path=output_path, fps=7, cancel_token=_Cancelled())
    assert not output_path.exists()
