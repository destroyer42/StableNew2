"""VID-FRAME: a sequence or Storyboard take smooths the assembled cut, never its segments. No RIFE or FFmpeg."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.video import video_interpolation
from src.video.svd_errors import SVDPostprocessError
from src.video.video_interpolation import (
    VideoInterpolationRequest,
    VideoInterpolationResult,
    interpolate_cut_frames,
)
from tests.video.test_pr_vid_seq_330_executor import Segments, _executor, _plan, _source


def _frames(folder: Path, count: int) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for number in range(count):
        path = folder / f"in_{number:05d}.png"
        Image.new("RGB", (4, 4), (number % 256, number // 256, 0)).save(path)
        paths.append(path)
    return paths


def test_a_long_cut_is_interpolated_in_overlapping_chunks_into_one_clip(
    tmp_path, monkeypatch
) -> None:
    chunks: list[int] = []
    encoded: dict[str, Any] = {}

    def process(self, *, frames, config, work_dir):
        chunks.append(len(frames))
        # RIFE: every input, its in-between, and the last input held for the tail.
        smoothed = [item for frame in frames for item in (frame, frame.copy())]
        return smoothed, {"interpolation": {"model": "fake"}}

    def export(*, image_paths, output_path, fps, **_kwargs):
        encoded["firsts"] = [Image.open(path).getpixel((0, 0)) for path in image_paths[::2]]
        encoded["count"], encoded["fps"] = len(image_paths), fps
        Path(output_path).write_bytes(b"mp4")
        return Path(output_path)

    monkeypatch.setattr(video_interpolation.SVDPostprocessRunner, "process_frames", process)
    monkeypatch.setattr(
        video_interpolation, "validate_svd_postprocess_config", lambda _c: (True, None)
    )
    monkeypatch.setattr(video_interpolation, "export_image_sequence_video", export)
    monkeypatch.setattr(video_interpolation, "CUT_CHUNK_FRAMES", 100)

    result = interpolate_cut_frames(
        frame_paths=_frames(tmp_path / "in", 450),
        output_path=tmp_path / "walk_smooth.mp4",
        source_fps=16,
        request=VideoInterpolationRequest(multiplier=2),
    )

    assert chunks == [101, 101, 101, 101, 50]  # one frame of overlap, no 400-frame cap
    assert encoded["count"] == 900 and encoded["fps"] == 32
    assert encoded["firsts"] == [
        (n % 256, n // 256, 0) for n in range(450)
    ]  # each input once, in order
    assert (result.input_frame_count, result.output_frame_count, result.output_fps) == (
        450,
        900,
        32,
    )
    assert not (tmp_path / "walk_smooth_work").exists()


def test_a_sequence_smooths_only_its_assembled_cut(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    tags: list[tuple[str, Any]] = []

    def interpolate(*, frame_paths, output_path, source_fps, request, cancel_token=None):
        calls.append(
            {"frames": len(frame_paths), "fps": source_fps, "multiplier": request.multiplier}
        )
        Path(output_path).write_bytes(b"smooth movie")
        return VideoInterpolationResult(
            "frames",
            str(output_path),
            len(frame_paths),
            2 * len(frame_paths),
            source_fps,
            2 * source_fps,
            2,
        )

    monkeypatch.setattr(
        "src.pipeline.video_sequence_executor.write_video_container_metadata",
        lambda path, payload: tags.append((Path(path).name, payload.get("output_role"))),
    )
    plan = _plan(2)
    segments = Segments(tmp_path)

    outcome = _executor(
        tmp_path,
        plan,
        segments,
        smoothing={"enabled": True, "multiplier": 2},
        interpolate=interpolate,
    ).execute(source_image_path=_source(tmp_path))

    movie = outcome.ledger.assembly
    assert len(calls) == 1 and calls[0]["fps"] == plan.fps and calls[0]["multiplier"] == 2
    assert outcome.assembled_path == movie["output_path"] and movie["output_path"].endswith(
        "_smooth.mp4"
    )
    assert movie["fps"] == 2 * plan.fps and movie["total_frames"] == 2 * calls[0]["frames"]
    assert movie["native"]["fps"] == plan.fps and Path(movie["native"]["output_path"]).is_file()
    assert dict(tags) == {
        Path(movie["output_path"]).name: "primary",
        Path(movie["native"]["output_path"]).name: "retained_source",
    }


def test_a_failed_smoothing_keeps_the_finished_movie_and_says_why(tmp_path) -> None:
    def broken(**_kwargs):
        raise SVDPostprocessError("no model folder")

    outcome = _executor(
        tmp_path, _plan(2), Segments(tmp_path), smoothing={"enabled": True}, interpolate=broken
    ).execute(source_image_path=_source(tmp_path))

    assert Path(outcome.assembled_path).is_file()
    assert "no model folder" in outcome.ledger.assembly["interpolation_error"]


def test_a_sequence_without_smoothing_is_unchanged(tmp_path) -> None:
    outcome = _executor(tmp_path, _plan(2), Segments(tmp_path)).execute(
        source_image_path=_source(tmp_path)
    )

    assert (
        "native" not in outcome.ledger.assembly and "interpolation" not in outcome.ledger.assembly
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_the_sequence_job_freezes_cut_smoothing_apart_from_segment_smoothing(
    tmp_path, monkeypatch, enabled
) -> None:
    from src.video import video_workflow_njr_builder
    from src.video.sequence_job_build import build_sequence_njr
    from tests.helpers.storyboard_380 import REG, a14b_settings, builder, png

    rife = tmp_path / "rife-ncnn-vulkan.exe"
    rife.write_bytes(b"x")
    monkeypatch.setattr(video_workflow_njr_builder, "find_rife_executable", lambda _p=None: rife)
    monkeypatch.setattr(video_interpolation, "find_rife_executable", lambda _p=None: rife)
    form = a14b_settings(frame_count=17)
    if enabled:
        form["interpolation"] = {"enabled": True}

    built = build_sequence_njr(
        njr_builder=builder(tmp_path),
        registry=REG,
        source_image_path=str(png(tmp_path / "s.png", (832, 480), (1, 2, 3))),
        form_data=form,
        sequence_intent={"segments": [{"prompt": p, "frame_count": 17} for p in ("a", "b")]},
    )

    stage = dict(built.njr.stage_chain[0].extra)
    assert "interpolation" not in stage
    assert (stage.get("cut_interpolation") or {}).get("multiplier") == (2 if enabled else None)
