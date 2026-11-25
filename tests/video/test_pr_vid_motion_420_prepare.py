"""PR-VID-MOTION-420: aligned preparation with real FFmpeg on disposable clips (CPU only).

Expected positions are computed from the transform's own arithmetic and from an *independent* decode of the
original clip; the published derivative is decoded here with FFmpeg, never through the code under test.
"""

from __future__ import annotations

import dataclasses
import hashlib
import subprocess
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from src.video import motion_alignment_preparation as mp
from src.video.driving_video_inspection import run_bounded_process
from src.video.motion_alignment import AlignmentIntent, FrameSize, resolve_alignment
from src.video.motion_alignment_preparation import (
    ALIGNED_SCHEMA,
    AlignedMotionRequest,
    prepare_aligned_motion_source,
    preview_alignment,
    temporal_plan_sha256,
)
from src.video.motion_source_plan import SCHEMA as PLAIN_SCHEMA
from src.video.motion_source_preparation import (
    MotionSourceRequest,
    prepare_motion_source,
)
from src.video.workflow_source_preparation import prepare_declared_workflow_source
from tests.video.motion_420_support import (
    FFMPEG,
    SOURCE_POLICY,
    contract,
    decode_rgb_frames,
    moving_square_clip,
    needs_ffmpeg,
    source_image,
    subject_centroid,
)

pytestmark = needs_ffmpeg
PORTRAIT = FrameSize(480, 832)
DRIVER = FrameSize(270, 480)


def _request(clip: Path, image: Path, intent: AlignmentIntent, **kw: Any) -> AlignedMotionRequest:
    kw.setdefault("unit", "frames")
    frames = kw.pop("frames", 17)
    return AlignedMotionRequest(
        str(clip), contract(frames), str(image), SOURCE_POLICY, intent, **kw
    )


def _prepare(tmp_path: Path, clip: Path, image: Path, intent: AlignmentIntent, **kw: Any):
    return prepare_aligned_motion_source(
        _request(clip, image, intent, **kw), output_root=tmp_path / "out"
    )


def _published(tmp_path: Path) -> list[str]:
    folder = tmp_path / "out" / "prepared_driving_videos"
    return sorted(item.name for item in folder.iterdir()) if folder.exists() else []


def _square_centre(index: int, *, start=(40, 100), step=(6, 0), edge=24) -> tuple[float, float]:
    return (start[0] + step[0] * index + edge / 2, start[1] + step[1] * index + edge / 2)


@pytest.fixture
def media(tmp_path: Path) -> tuple[Path, Path]:
    return moving_square_clip(tmp_path), source_image(tmp_path / "src.png")


# ------------------------------------------------------------------------------ what is published


def test_the_published_derivative_is_verified_rgb_at_the_target_size(tmp_path, media):
    clip, image = media
    intent = AlignmentIntent(scale=0.8, translate_x=30, translate_y=-20)
    outcome = _prepare(tmp_path, clip, image, intent)
    assert outcome.prepared, (outcome.code, outcome.message)
    record = outcome.record
    assert record["schema"] == ALIGNED_SCHEMA != PLAIN_SCHEMA
    derived, original = record["derived"], record["original"]
    assert (derived["width"], derived["height"], derived["frames"]) == (480, 832, 17)
    assert derived["rotation_quadrants"] == 0 and derived["frame_rate"] == "24/1"
    assert derived["sha256"] != original["sha256"]  # the derivative is not the library clip
    assert Path(derived["path"]).name == f"{derived['sha256']}.mp4"
    assert hashlib.sha256(Path(derived["path"]).read_bytes()).hexdigest() == derived["sha256"]
    assert hashlib.sha256(clip.read_bytes()).hexdigest() == original["sha256"]  # original untouched
    processing = record["processing"]
    assert processing["lossless"] is False and processing["lossless_encoding"] is True
    assert processing["source_frame_identity"] == "transformed"
    assert "not" not in processing["verification"].split("equals")[0]
    assert _published(tmp_path) == [f"{derived['sha256']}.mp4"]  # no temporary file survives
    frames = decode_rgb_frames(Path(derived["path"]))
    assert len(frames) == 17 and frames[0].shape == (832, 480, 3)


def test_the_record_binds_original_driver_source_image_plan_and_transform(tmp_path, media):
    clip, image = media
    outcome = _prepare(tmp_path, clip, image, AlignmentIntent(scale=1.1, translate_x=5.0))
    record = outcome.record
    alignment = record["alignment"]
    assert alignment["driver_original_sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert alignment["temporal_plan_sha256"] == temporal_plan_sha256(record)
    assert (
        alignment["transform_sha256"]
        and alignment["coordinate_system"] == "stablenew.alignment-frame.v1"
    )
    assert (
        alignment["fill"]["policy"] == "constant_gray_128" and alignment["resampling"] == "lanczos"
    )
    source = alignment["source_image"]
    assert source["original_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    # the prepared reference identity equals the PNG the queue-time preparation would publish
    published = prepare_declared_workflow_source(
        source_path=image, output_root=tmp_path / "ref", policy=SOURCE_POLICY
    )
    assert (
        source["prepared_sha256"]
        == hashlib.sha256(Path(published.prepared_image_path).read_bytes()).hexdigest()
    )
    assert (source["width"], source["height"]) == (480, 832)
    assert record["contract"]["workflow_id"] == "wan_animate2_drive_i2v_v1"


def test_an_unaligned_preparation_is_unchanged_and_never_confused_with_an_aligned_one(
    tmp_path, media
):
    clip, image = media
    plain = prepare_motion_source(
        MotionSourceRequest(str(clip), contract(), unit="frames"), output_root=tmp_path / "out"
    )
    aligned = _prepare(tmp_path, clip, image, AlignmentIntent())
    assert plain.record["schema"] == PLAIN_SCHEMA and "alignment" not in plain.record
    assert aligned.record["schema"] == ALIGNED_SCHEMA
    assert plain.record["derived"]["sha256"] != aligned.record["derived"]["sha256"]
    assert (
        plain.record["processing"]["lossless"] is True
    )  # the exact-frame contract keeps its meaning
    assert temporal_plan_sha256(plain.record) == temporal_plan_sha256(aligned.record)


# ------------------------------------------------------------------------------ trajectory


def test_one_constant_transform_places_the_subject_at_every_frame(tmp_path, media):
    clip, image = media
    intent = AlignmentIntent(scale=0.8, translate_x=30, translate_y=-20)
    record = _prepare(tmp_path, clip, image, intent).record
    resolved = resolve_alignment(intent, driver=DRIVER, target=PORTRAIT)
    frames = decode_rgb_frames(Path(record["derived"]["path"]))
    positions = [subject_centroid(frame) for frame in frames]
    assert all(p is not None for p in positions)
    for index in (0, 5, 11, 16):
        want = resolved.to_target(_square_centre(index))
        assert positions[index] == pytest.approx(want, abs=1.5), index
    # the frame order is the source order and displacement is scaled by exactly the effective scale
    deltas = [b[0] - a[0] for a, b in zip(positions, positions[1:], strict=False)]
    assert all(d > 0 for d in deltas)
    assert np.mean(deltas) == pytest.approx(6 * resolved.effective_scale, abs=0.4)
    assert max(deltas) - min(deltas) < 1.5  # no frame-dependent centring or rescaling


def test_the_subject_is_never_re_centred_per_frame(tmp_path):
    clip = moving_square_clip(tmp_path, step=(8, 3), frames=20)
    image = source_image(tmp_path / "src.png")
    record = _prepare(tmp_path, clip, image, AlignmentIntent(scale=1.2, translate_x=-10)).record
    frames = decode_rgb_frames(Path(record["derived"]["path"]))
    first, last = subject_centroid(frames[0]), subject_centroid(frames[16])
    resolved = resolve_alignment(
        AlignmentIntent(scale=1.2, translate_x=-10), driver=DRIVER, target=PORTRAIT
    )
    travelled = (last[0] - first[0], last[1] - first[1])
    assert travelled[0] == pytest.approx(16 * 8 * resolved.effective_scale, abs=2.0)
    assert travelled[1] == pytest.approx(16 * 3 * resolved.effective_scale, abs=2.0)


def test_mirroring_reverses_the_direction_of_travel_and_is_never_automatic(tmp_path, media):
    clip, image = media
    plain = _prepare(tmp_path, clip, image, AlignmentIntent()).record
    mirrored = _prepare(tmp_path, clip, image, AlignmentIntent(mirror=True)).record
    a = [subject_centroid(f) for f in decode_rgb_frames(Path(plain["derived"]["path"]))]
    b = [subject_centroid(f) for f in decode_rgb_frames(Path(mirrored["derived"]["path"]))]
    assert a[16][0] > a[0][0] and b[16][0] < b[0][0]  # +x travel became -x travel
    assert b[0][0] == pytest.approx(480 - a[0][0], abs=1.5)
    assert (
        plain["alignment"]["intent"]["mirror"] is False
        and mirrored["alignment"]["intent"]["mirror"] is True
    )


def test_the_plan_alone_decides_which_source_frame_becomes_each_frame(tmp_path):
    clip = moving_square_clip(tmp_path, rate="30", frames=40)
    image = source_image(tmp_path / "src.png")
    record = _prepare(
        tmp_path, clip, image, AlignmentIntent(), start=5, fps_conversion="workflow_rate"
    ).record
    indices = record["plan"]["source_indices"]
    assert indices[:6] == [
        5,
        6,
        8,
        9,
        10,
        11,
    ]  # floor(1.25 j + 1/2): 30 fps -> 24 fps omits source frame 7
    resolved = resolve_alignment(AlignmentIntent(), driver=DRIVER, target=PORTRAIT)
    frames = decode_rgb_frames(Path(record["derived"]["path"]))
    for slot in (0, 4, 9):
        want = resolved.to_target(_square_centre(indices[slot]))
        assert subject_centroid(frames[slot]) == pytest.approx(want, abs=1.5)
    assert record["derived"]["frame_rate"] == "24/1"


def test_a_short_clip_holds_its_last_frame_exactly_as_the_plan_says(tmp_path):
    clip = moving_square_clip(tmp_path, frames=10)
    image = source_image(tmp_path / "src.png")
    record = _prepare(tmp_path, clip, image, AlignmentIntent(scale=0.9)).record
    assert record["plan"]["held_frames"] == 7 and record["plan"]["source_indices"][-1] == 9
    frames = decode_rgb_frames(Path(record["derived"]["path"]))
    assert all(
        np.array_equal(frames[9], frame) for frame in frames[10:]
    )  # the hold is a repeat, not a drift


def test_a_landscape_driver_and_an_oriented_source_use_display_geometry(tmp_path):
    clip = moving_square_clip(tmp_path, size=(480, 270), start=(180, 100), step=(8, 0))
    image = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # stored 416x240, displayed 240x416 (portrait)
    Image.new("RGB", (416, 240), (60, 100, 140)).save(image, exif=exif)
    record = _prepare(tmp_path, clip, image, AlignmentIntent(translate_x=-20)).record
    assert record["alignment"]["source_image"]["orientation"] == "portrait"
    assert (record["derived"]["width"], record["derived"]["height"]) == (480, 832)
    assert (record["original"]["width"], record["original"]["height"]) == (480, 270)
    resolved = resolve_alignment(
        AlignmentIntent(translate_x=-20), driver=FrameSize(480, 270), target=PORTRAIT
    )
    frames = decode_rgb_frames(Path(record["derived"]["path"]))
    for index in (0, 8):
        want = resolved.to_target((180 + 8 * index + 12, 100 + 12))
        got = subject_centroid(frames[index])
        assert got is not None and got == pytest.approx(want, abs=1.5)


def test_a_rotated_driving_clip_is_aligned_in_display_orientation(tmp_path):
    plain = moving_square_clip(
        tmp_path, "upright.mp4", size=(480, 270), start=(60, 60), step=(8, 0)
    )
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-display_rotation:v:0", "90", "-i", str(plain),
         "-c", "copy", str(rotated)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    image = source_image(tmp_path / "src.png")
    record = _prepare(tmp_path, rotated, image, AlignmentIntent(scale=0.9)).record
    assert record["original"]["rotation_quadrants"] in (1, 3)
    assert (record["original"]["width"], record["original"]["height"]) == (270, 480)  # display
    independent = decode_rgb_frames(rotated)  # FFmpeg's own display-oriented decode
    resolved = resolve_alignment(
        AlignmentIntent(scale=0.9), driver=FrameSize(270, 480), target=PORTRAIT
    )
    out = decode_rgb_frames(Path(record["derived"]["path"]))
    for index in (0, 6, 12):
        seen = subject_centroid(independent[index])
        want = resolved.to_target(seen)
        assert subject_centroid(out[index]) == pytest.approx(want, abs=1.5)
    assert record["derived"]["rotation_quadrants"] == 0  # the rotation is baked into the pixels


# ------------------------------------------------------------------------------ preview agreement


def test_a_preview_is_the_published_frame_and_publishes_nothing(tmp_path, media):
    clip, image = media
    intent = AlignmentIntent(scale=0.85, translate_x=12, translate_y=30)
    request = _request(clip, image, intent)
    preview = preview_alignment(request, [0, 8, 16], output_root=tmp_path / "out")
    assert preview.ok, preview.message
    assert [f.output_index for f in preview.frames] == [0, 8, 16]
    assert _published(tmp_path) == []  # no file, no temporary directory
    published = decode_rgb_frames(
        Path(
            prepare_aligned_motion_source(request, output_root=tmp_path / "out").record["derived"][
                "path"
            ]
        )
    )
    import io

    for frame in preview.frames:
        shown = np.asarray(Image.open(io.BytesIO(frame.aligned_png)).convert("RGB"))
        assert np.array_equal(
            shown, published[frame.output_index]
        )  # preview == publication, pixel for pixel
        base = np.asarray(Image.open(io.BytesIO(frame.baseline_png)).convert("RGB"))
        assert base.shape == shown.shape and not np.array_equal(base, shown)
    assert preview.target == PORTRAIT and preview.driver == DRIVER
    assert any("Alignment:" in line for line in preview.explanation)


# ------------------------------------------------------------------------------ reuse and hygiene


def test_a_second_identical_preparation_reuses_the_published_file(tmp_path, media):
    clip, image = media
    intent = AlignmentIntent(scale=0.9, translate_x=4)
    first = _prepare(tmp_path, clip, image, intent)
    path = Path(first.record["derived"]["path"])
    stamp = path.stat().st_mtime_ns
    second = _prepare(tmp_path, clip, image, intent)
    assert second.record["derived"]["sha256"] == first.record["derived"]["sha256"]
    assert path.stat().st_mtime_ns == stamp and _published(tmp_path) == [path.name]
    other = _prepare(tmp_path, clip, image, AlignmentIntent(scale=0.9, translate_x=5))
    assert other.record["derived"]["sha256"] != first.record["derived"]["sha256"]
    assert len(_published(tmp_path)) == 2  # an earlier preparation is never deleted or overwritten


def test_a_changed_source_image_gives_a_different_aligned_clip_and_binding(tmp_path, media):
    clip, image = media
    intent = AlignmentIntent(scale=0.9)
    first = _prepare(tmp_path, clip, image, intent).record
    other = source_image(tmp_path / "other.png", color=(5, 5, 5))
    second = _prepare(tmp_path, clip, other, intent).record
    assert (
        first["alignment"]["source_image"]["original_sha256"]
        != second["alignment"]["source_image"]["original_sha256"]
    )
    assert first["alignment"]["transform_sha256"] == second["alignment"]["transform_sha256"]


# ------------------------------------------------------------------------------ refusals and failures


def test_failures_publish_nothing_and_leave_no_temporary_files(tmp_path, media):
    clip, image = media
    missing = _prepare(tmp_path, tmp_path / "nope.mp4", image, AlignmentIntent())
    assert missing.code == "file_missing" and not missing.prepared
    wrong = tmp_path / "clip.txt"
    wrong.write_text("x")
    assert _prepare(tmp_path, wrong, image, AlignmentIntent()).code == "unsupported_file"
    no_source = _prepare(tmp_path, clip, tmp_path / "nothing.png", AlignmentIntent())
    assert no_source.code == "source_unavailable"
    bad_value = _prepare(tmp_path, clip, image, AlignmentIntent(scale=9.0))
    assert bad_value.code == "scale_out_of_range" and "outside the supported" in bad_value.message
    off = _prepare(tmp_path, clip, image, AlignmentIntent(scale=0.25, translate_x=480.0))
    assert off.code == "no_overlap"
    assert _published(tmp_path) == []


def test_oversize_and_unsupported_inputs_are_refused_not_degraded(tmp_path, media, monkeypatch):
    clip, image = media
    monkeypatch.setattr(mp, "MAX_ALIGN_FRAME_PIXELS", 1000)
    assert _prepare(tmp_path, clip, image, AlignmentIntent()).code == "frame_too_large"
    monkeypatch.undo()
    monkeypatch.setattr(mp, "MAX_UNIQUE_SOURCE_FRAMES", 3)
    assert _prepare(tmp_path, clip, image, AlignmentIntent()).code == "too_many_frames"
    monkeypatch.undo()
    gray = tmp_path / "gray.mp4"
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-i", str(clip), "-pix_fmt", "rgb24", "-c:v", "libx264rgb", str(gray)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    assert _prepare(tmp_path, gray, image, AlignmentIntent()).code == "unsupported_pixel_format"
    assert _published(tmp_path) == []


def test_a_cancelled_preparation_keeps_nothing(tmp_path, media):
    clip, image = media
    cancel = threading.Event()
    cancel.set()
    outcome = prepare_aligned_motion_source(
        _request(clip, image, AlignmentIntent()), output_root=tmp_path / "out", cancel=cancel
    )
    assert outcome.status == "cancelled" and _published(tmp_path) == []

    midway = threading.Event()

    def runner(command, **kwargs):
        if "-f" in command and command[command.index("-f") + 1] == "mp4":  # the encode step
            midway.set()
            kwargs["cancel"].set()
        return run_bounded_process(command, **kwargs)

    cancel = threading.Event()
    outcome = prepare_aligned_motion_source(
        _request(clip, image, AlignmentIntent()),
        output_root=tmp_path / "out",
        cancel=cancel,
        runner=lambda command, **kw: runner(command, **{**kw, "cancel": cancel}),
    )
    assert midway.is_set() and outcome.status == "cancelled" and _published(tmp_path) == []


def test_a_frame_that_does_not_match_the_declared_transform_is_never_published(tmp_path, media):
    clip, image = media

    def corrupting(command, **kwargs):
        outcome = run_bounded_process(command, **kwargs)
        is_verify = "framemd5" in command and ".preparing-" in " ".join(command)
        if is_verify:
            lines = outcome.stdout.decode().splitlines()
            first = next(i for i, line in enumerate(lines) if line and not line.startswith("#"))
            head, _, digest = lines[first].rpartition(",")
            lines[first] = f"{head}, {'0' * 32 if digest.strip() != '0' * 32 else '1' * 32}"
            return dataclasses.replace(outcome, stdout="\n".join(lines).encode())
        return outcome

    outcome = prepare_aligned_motion_source(
        _request(clip, image, AlignmentIntent(scale=0.9)),
        output_root=tmp_path / "out",
        runner=corrupting,
    )
    assert outcome.code == "verification_failed" and not outcome.prepared
    assert _published(tmp_path) == []


def test_an_atomic_publication_failure_leaves_no_file_and_no_temporary(
    tmp_path, media, monkeypatch
):
    clip, image = media

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mp.os, "replace", boom)
    outcome = _prepare(tmp_path, clip, image, AlignmentIntent(scale=0.9))
    assert outcome.code == "io_error" and not outcome.prepared
    assert _published(tmp_path) == []


def test_a_changed_driving_clip_during_preparation_is_detected(tmp_path, media):
    clip, image = media

    def touching(command, **kwargs):
        outcome = run_bounded_process(command, **kwargs)
        if "framemd5" in command and ".preparing-" in " ".join(command):
            clip.write_bytes(clip.read_bytes() + b"\x00")  # the original is edited mid-run
        return outcome

    outcome = prepare_aligned_motion_source(
        _request(clip, image, AlignmentIntent(scale=0.9)),
        output_root=tmp_path / "out",
        runner=touching,
    )
    assert outcome.code == "source_changed" and _published(tmp_path) == []


def test_alignment_never_starts_a_runtime_or_queues_anything():
    source = open(mp.__file__, encoding="utf-8").read()
    for forbidden in (
        "src.queue",
        "src.gui",
        "JobService",
        "submit_njrs",
        "ComfyProcess",
        "requests",
    ):
        assert forbidden not in source


def test_a_preview_holds_a_bounded_number_of_decoded_frames_and_keeps_both_ends(
    tmp_path, monkeypatch
):
    clip = moving_square_clip(tmp_path)
    image = source_image(tmp_path / "src.png")
    request = _request(clip, image, AlignmentIntent())
    every = list(range(17))
    monkeypatch.setattr(mp, "PREVIEW_PIXEL_BUDGET", 270 * 480 * 4)  # room for four decoded frames
    loaded = mp.load_preview_source(request, every, output_root=tmp_path / "out")
    assert loaded.ok and sorted(loaded.frames) == [
        0,
        5,
        11,
        16,
    ]  # first and last kept, the rest spaced
    assert mp._thin(list(range(100)), 1) == [0] and mp._thin([3, 4], 5) == [3, 4]
    assert _published(tmp_path) == []
