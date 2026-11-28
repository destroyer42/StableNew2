"""VID-FINISH: optional loop and trim of a finished clip (pure options, frame arithmetic and FFmpeg arguments).

The FFmpeg-backed tests skip when FFmpeg is not installed; no GPU, no RIFE.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from src.pipeline.video import VideoEncodeSettings, resolve_ffmpeg_executable
from src.video.clip_finishing import (
    ClipFinishError,
    build_finish_command,
    build_finish_filter,
    check_against_clip,
    finish_video_file,
    frame_plan,
    frozen_finishing,
    normalize_finishing,
)
from src.video.video_export import export_image_sequence_video

needs_ffmpeg = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None, reason="FFmpeg is not installed"
)


# --------------------------------------------------------------------------- options


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"loop_mode": "off", "trim_start_seconds": "", "trim_end_seconds": "", "upscale": False},
        {"loop_mode": "", "trim_start_seconds": "0", "trim_end_seconds": None},
    ],
)
def test_nothing_is_requested_by_default(value) -> None:
    assert normalize_finishing(value) is None


def test_form_text_becomes_typed_values_and_survives_freezing() -> None:
    request = normalize_finishing(
        {"loop_mode": "crossfade", "trim_start_seconds": " 0.5 ", "trim_end_seconds": "3"}
    )
    assert request is not None
    assert (request.trim_start_seconds, request.trim_end_seconds) == (0.5, 3.0)
    assert (request.loop_mode, request.crossfade_seconds, request.upscale) == (
        "crossfade",
        0.5,
        False,
    )

    frozen = frozen_finishing(request)
    assert frozen == {
        "loop_mode": "crossfade",
        "crossfade_seconds": 0.5,
        "trim_start_seconds": 0.5,
        "trim_end_seconds": 3.0,
    }
    assert normalize_finishing(frozen) == request


def test_only_the_chosen_keys_are_frozen() -> None:
    assert frozen_finishing(normalize_finishing({"loop_mode": "ping_pong"})) == {
        "loop_mode": "ping_pong"
    }
    assert frozen_finishing(normalize_finishing({"trim_end_seconds": 2})) == {
        "trim_end_seconds": 2.0
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"loop_mode": "spin"}, "loop"),
        ({"trim_start_seconds": "abc"}, "number"),
        ({"trim_start_seconds": -1}, "negative"),
        ({"trim_start_seconds": float("nan")}, "number"),
        ({"trim_end_seconds": 0}, "after"),
        ({"trim_start_seconds": 2, "trim_end_seconds": 1}, "after"),
        ({"loop_mode": "crossfade", "crossfade_seconds": 0}, "crossfade"),
        ({"loop_mode": "crossfade", "crossfade_seconds": 30}, "crossfade"),
    ],
)
def test_a_bad_request_is_refused_with_a_readable_reason(value, message) -> None:
    with pytest.raises(ClipFinishError, match=message):
        normalize_finishing(value)


# --------------------------------------------------------------------------- frame arithmetic


def test_trim_seconds_become_exact_frames_of_the_clip() -> None:
    plan = frame_plan(
        normalize_finishing({"trim_start_seconds": 0.5, "trim_end_seconds": 1.5}),
        fps=48,
        frame_count=96,
    )
    assert (plan.start_frame, plan.end_frame, plan.output_frame_count) == (24, 72, 48)


def test_ping_pong_does_not_repeat_the_two_turning_frames() -> None:
    plan = frame_plan(normalize_finishing({"loop_mode": "ping_pong"}), fps=24, frame_count=10)
    assert (plan.start_frame, plan.end_frame, plan.output_frame_count) == (0, 10, 18)


def test_crossfade_shortens_the_clip_by_the_blended_frames() -> None:
    request = normalize_finishing({"loop_mode": "crossfade", "crossfade_seconds": 0.25})
    plan = frame_plan(request, fps=24, frame_count=48)
    assert (plan.crossfade_frames, plan.output_frame_count) == (6, 42)


@pytest.mark.parametrize(
    ("value", "frame_count", "message"),
    [
        ({"trim_start_seconds": 2}, 48, "past the end"),
        ({"trim_end_seconds": 3}, 48, "past the end"),
        ({"loop_mode": "ping_pong", "trim_start_seconds": 1.95}, 48, "3 frames"),
        ({"loop_mode": "crossfade", "crossfade_seconds": 1}, 48, "too short"),
    ],
)
def test_a_request_the_clip_cannot_satisfy_is_refused(value, frame_count, message) -> None:
    with pytest.raises(ClipFinishError, match=message):
        check_against_clip(normalize_finishing(value), fps=24, frame_count=frame_count)


# --------------------------------------------------------------------------- FFmpeg arguments


def test_the_trim_filter_cuts_on_frame_numbers_and_restamps_the_clip() -> None:
    request = normalize_finishing({"trim_start_seconds": 1, "trim_end_seconds": 2})
    graph = build_finish_filter(
        frame_plan(request, fps=24, frame_count=96), request.loop_mode, fps=24
    )

    assert graph.startswith("[0:v]trim=start_frame=24:end_frame=48,setpts=PTS-STARTPTS,")
    assert graph.endswith("[out]")
    assert "setpts=N/(24*TB)" in graph
    assert "reverse" not in graph and "blend" not in graph


def test_the_ping_pong_filter_plays_the_interior_backwards() -> None:
    request = normalize_finishing({"loop_mode": "ping_pong"})
    graph = build_finish_filter(
        frame_plan(request, fps=24, frame_count=10), request.loop_mode, fps=24
    )

    assert "split[fwd][back]" in graph
    assert "[back]trim=start_frame=1:end_frame=9,setpts=PTS-STARTPTS,reverse" in graph
    assert "concat=n=2:v=1:a=0" in graph


def test_the_crossfade_filter_blends_the_tail_into_the_head() -> None:
    request = normalize_finishing({"loop_mode": "crossfade", "crossfade_seconds": 0.25})
    graph = build_finish_filter(
        frame_plan(request, fps=24, frame_count=48), request.loop_mode, fps=24
    )

    assert "split=3[a][b][c]" in graph
    assert "[a]trim=start_frame=0:end_frame=6," in graph
    assert "[b]trim=start_frame=6:end_frame=42," in graph
    assert "[c]trim=start_frame=42:end_frame=48," in graph
    assert "blend=all_expr='A*(1-(T*24+1)/7)+B*((T*24+1)/7)'" in graph


def test_the_command_uses_stablenews_one_encoder_and_never_touches_the_source(
    tmp_path: Path,
) -> None:
    request = normalize_finishing({"loop_mode": "ping_pong"})
    plan = frame_plan(request, fps=24, frame_count=10)
    command = build_finish_command(
        "ffmpeg",
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        24,
        plan,
        "ping_pong",
        VideoEncodeSettings(),
    )

    assert command[:2] == ["ffmpeg", "-v"]
    assert command[command.index("-i") + 1] == str(tmp_path / "in.mp4")
    assert command[command.index("-map") + 1] == "[out]"
    assert command[command.index("-crf") + 1] == "16"
    assert command[command.index("-preset") + 1] == "slow"
    assert "-vf" not in command  # the colour filter is the end of the graph
    assert "out_color_matrix=bt709" in command[command.index("-filter_complex") + 1]
    assert command[-1] == str(tmp_path / "out.mp4")


def test_a_failed_encode_raises_and_leaves_no_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "in.mp4"
    source.write_bytes(b"clip")
    target = tmp_path / "out.mp4"

    def _run(command, **_kwargs):
        if "-progress" in command:
            return subprocess.CompletedProcess(command, 0, "frame=10\nprogress=end\n", "")
        target.write_bytes(b"partial")
        return subprocess.CompletedProcess(command, 1, "", "boom")

    monkeypatch.setattr("src.video.clip_finishing.run_ffmpeg", _run)
    monkeypatch.setattr(
        "src.video.clip_finishing.resolve_ffmpeg_executable", lambda: Path("ffmpeg")
    )

    with pytest.raises(ClipFinishError, match="boom"):
        finish_video_file(
            video_path=source,
            output_path=target,
            fps=24,
            request=normalize_finishing({"loop_mode": "ping_pong"}),
        )
    assert source.read_bytes() == b"clip" and not target.exists()


# --------------------------------------------------------------------------- real FFmpeg

SHADES = (20, 60, 100, 140, 180, 220)


def _clip(tmp_path: Path) -> Path:
    frames = []
    for index, shade in enumerate(SHADES):
        path = tmp_path / f"f_{index:03d}.png"
        Image.new("RGB", (32, 32), (shade, shade, shade)).save(path)
        frames.append(path)
    clip = tmp_path / "clip.mp4"
    export_image_sequence_video(
        image_paths=frames, output_path=clip, fps=6, require_all_frames=True
    )
    return clip


def _shades(path: Path, tmp_path: Path) -> list[int]:
    folder = tmp_path / f"decoded_{path.stem}"
    folder.mkdir()
    subprocess.run(
        [
            str(resolve_ffmpeg_executable()),
            "-v",
            "error",
            "-i",
            str(path),
            "-fps_mode",
            "passthrough",
            str(folder / "d_%03d.png"),
        ],
        check=True,
    )
    values = []
    for frame in sorted(folder.glob("d_*.png")):
        with Image.open(frame) as image:
            values.append(image.convert("L").getpixel((16, 16)))
    return values


def _close(actual: list[int], expected: list[float]) -> bool:
    return len(actual) == len(expected) and all(
        abs(a - e) <= 6 for a, e in zip(actual, expected, strict=True)
    )


@needs_ffmpeg
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"trim_start_seconds": 1 / 6, "trim_end_seconds": 4 / 6}, [60, 100, 140]),
        ({"loop_mode": "ping_pong"}, [20, 60, 100, 140, 180, 220, 180, 140, 100, 60]),
        # 2-frame crossfade: frames 2..3 as they are, then 180->20 at 1/3 and 220->60 at 2/3.
        ({"loop_mode": "crossfade", "crossfade_seconds": 2 / 6}, [100, 140, 126.7, 113.3]),
        ({"trim_end_seconds": 3 / 6, "loop_mode": "ping_pong"}, [20, 60, 100, 60]),
    ],
)
def test_the_finished_clip_holds_exactly_the_planned_frames(
    tmp_path: Path, value, expected
) -> None:
    clip = _clip(tmp_path)
    before = clip.read_bytes()

    result = finish_video_file(
        video_path=clip,
        output_path=tmp_path / "finished.mp4",
        fps=6,
        request=normalize_finishing(value),
    )

    assert clip.read_bytes() == before
    assert (result.input_frame_count, result.output_frame_count) == (6, len(expected))
    assert result.fps == 6
    shades = _shades(Path(result.video_path), tmp_path)
    assert _close(shades, expected), shades
