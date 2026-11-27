"""V1-3 (follow a driver): the length a driver allows, and the scaled-down, uploadable prepared copy.

Pure functions and a recording FFmpeg runner: nothing is decoded and FFmpeg is not needed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.utils.managed_process import ProcessOutcome
from src.video import motion_source_preparation as prep
from src.video.driver_intent import (
    driver_cover_size,
    driver_seconds,
    plan_driver_clip,
    working_cover,
)
from src.video.driving_video_inspection import DrivingVideoFacts, DrivingVideoInspection
from src.video.motion_intent import LengthPolicy
from src.video.motion_source_plan import FPS_CONVERSION_NONE, MotionSourceContract

# Wan-Animate-2: 17-81 frames of 4n+1 at 24 fps (about 0.7 to 3.4 s).
ANIMATE = LengthPolicy(minimum=17, maximum=81, step=4, offset=1, fps=24, default=41)
SOURCE_POLICY = {
    "portrait_target": {"width": 480, "height": 832},
    "landscape_target": {"width": 832, "height": 480},
    "square_orientation": "portrait",
}


@pytest.mark.parametrize(
    ("requested", "window", "frames", "line"),
    [
        (None, 4.0, 81, "Driver 4.0 s · clip 3.4 s (the engine's longest)"),
        (None, 3.375, 81, "Driver 3.4 s · clip 3.4 s"),  # exactly fits
        (None, 2.0, 45, "Driver 2.0 s · clip 1.9 s"),  # the whole movement, never past its end
        (2.0, 4.0, 49, "Driver 4.0 s · clip 2.0 s"),
        (3.0, 1.0, 21, "Driver 1.0 s · clip 0.9 s (the driver ends there)"),
        (None, None, 41, "clip 1.7 s"),  # unreadable driver: the engine's default
    ],
)
def test_the_driver_and_the_requested_seconds_give_a_length_that_fits(
    requested, window, frames, line
):
    plan = plan_driver_clip(requested, ANIMATE, window)
    assert plan.frames == frames
    assert plan.line == line
    assert "frame" not in plan.line  # the panel never shows frame counts


def test_a_driver_shorter_than_the_engines_minimum_says_it_holds_the_last_frame():
    plan = plan_driver_clip(None, ANIMATE, 0.3)
    assert plan.frames == 17 and "its last frame is held" in plan.line


@pytest.mark.parametrize(
    ("facts", "seconds"),
    [
        (SimpleNamespace(reported_frame_count=120, reported_fps=30.0, duration_seconds=4.2), 4.0),
        (SimpleNamespace(reported_frame_count=None, reported_fps=30.0, duration_seconds=2.5), 2.5),
        (
            SimpleNamespace(reported_frame_count=None, reported_fps=None, duration_seconds=None),
            None,
        ),
        (None, None),
    ],
)
def test_driver_seconds_prefers_the_reported_frames(facts, seconds):
    assert driver_seconds(facts) == seconds


@pytest.mark.parametrize(
    ("size", "rotation", "cover", "expected"),
    [
        ((3840, 2160), 0, (480, 832), (1480, 832)),  # 4K driver, portrait clip
        ((1080, 1920), 0, (480, 832), (480, 854)),  # portrait phone clip
        ((1920, 1080), 0, (832, 480), (854, 480)),
        ((1920, 1080), 1, (480, 832), (854, 480)),  # stored landscape, shown portrait
        ((640, 360), 0, (832, 480), None),  # already smaller: never enlarged
        ((480, 832), 0, (480, 832), None),
    ],
)
def test_a_large_driver_is_scaled_to_the_smallest_same_aspect_size_covering_the_frame(
    size, rotation, cover, expected
):
    assert driver_cover_size(*size, rotation, cover) == expected


@pytest.mark.parametrize(
    ("orientation", "cover"),
    [
        ("portrait", (480, 832)),
        ("landscape", (832, 480)),
        ("square", (480, 832)),
        ("", (832, 832)),  # several sources, or none yet: large enough for either
    ],
)
def test_the_working_frame_follows_the_source_orientation(orientation, cover):
    assert working_cover(SOURCE_POLICY, orientation) == cover


def test_no_declared_targets_means_no_scaling():
    assert working_cover({}, "portrait") is None
    assert working_cover(None) is None


# ---------------------------------------------------------------- preparation with a cover


def _facts(width: int, height: int, frames: int = 60) -> DrivingVideoFacts:
    return DrivingVideoFacts(
        container_format="mov,mp4", codec_name="h264", pixel_format="yuv420p", coded_width=width,
        coded_height=height, rotation_quadrants=0, display_width=width, display_height=height,
        sample_aspect_ratio="", reported_fps=30.0, fps_basis="average", fps_is_variable_suspected=False,
        reported_frame_count=frames, estimated_frame_count=None, frame_count_basis="reported",
        duration_seconds=frames / 30, duration_basis="stream", fps_rational="30/1",
    )  # fmt: skip


def _md5(count: int) -> bytes:
    import hashlib

    rows = [
        f"0, {i}, {i}, 1, 100, {hashlib.md5(str(i).encode()).hexdigest()}" for i in range(count)
    ]
    return ("\n".join(rows) + "\n").encode()


def _prepare(tmp_path: Path, *, cover, encoded_bytes: int = 64, derived=(1480, 832)):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"four k clip")
    commands: list[str] = []

    def runner(command, *, timeout_seconds, max_stdout_bytes, cancel=None):
        text = " ".join(command)
        commands.append(text)
        if "-version" in command:
            return ProcessOutcome(returncode=0, stdout=b"ffmpeg test")
        if command[-1] == "-":
            return ProcessOutcome(returncode=0, stdout=_md5(60 if "select" in text else 17))
        Path(command[-1]).write_bytes(b"x" * encoded_bytes)
        return ProcessOutcome(returncode=0)

    def inspect(path, **_kwargs):
        facts = _facts(3840, 2160) if Path(path) == clip else _facts(*derived, frames=17)
        return DrivingVideoInspection(
            path=str(path), status="ok", facts=facts, frames=(), issues=()
        )

    outcome = prep.prepare_motion_source(
        prep.MotionSourceRequest(
            str(clip),
            MotionSourceContract("wan_animate2_drive_i2v_v1", "1.3.0", 17, 24, "rev", "rule"),
            fps_conversion=FPS_CONVERSION_NONE,
            cover=cover,
        ),
        output_root=tmp_path / "out",
        runner=runner,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        inspect=inspect,
    )
    return outcome, commands


def test_a_cover_scales_every_pass_with_the_nodes_area_filter_and_records_it(tmp_path):
    outcome, commands = _prepare(tmp_path, cover=(480, 832))
    assert outcome.status == prep.STATUS_PREPARED, outcome.message
    scaled = [command for command in commands if "scale=" in command]
    assert len(scaled) == 2  # the window fingerprint and the encode use the same frames
    assert all("scale=1480:832:flags=area" in command for command in scaled)
    processing = outcome.record["processing"]
    assert processing["lossless"] is False
    assert processing["resize"] == {
        "width": 1480,
        "height": 832,
        "filter": "area",
        "policy": "driver-cover",
    }
    assert "Scaled 3840x2160 to 1480x832" in outcome.message


def test_without_a_cover_the_clip_keeps_its_size(tmp_path):
    outcome, commands = _prepare(tmp_path, cover=None, derived=(3840, 2160))
    assert outcome.status == prep.STATUS_PREPARED, outcome.message
    assert not any("scale=" in command for command in commands)
    assert outcome.record["processing"]["resize"] is None


def test_a_prepared_driver_too_large_to_upload_is_refused_with_the_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(prep, "MAX_UPLOADABLE_BYTES", 1000)
    outcome, _commands = _prepare(tmp_path, cover=(480, 832), encoded_bytes=2000)
    assert outcome.status == prep.STATUS_FAILED_PREPARATION
    assert outcome.code == "output_too_large_to_upload"
    assert "ComfyUI accepts" in outcome.message
    assert not list((tmp_path / "out").rglob("*.mp4"))  # nothing kept
