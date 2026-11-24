"""PR-VID-MOTION-400: harvesting a reusable motion asset from an existing video.

Real FFmpeg fixtures are generated into ``tmp_path`` (deterministic CPU work, a few KB each); tests are skipped when
FFmpeg is absent.  Expected frames are decoded here independently with ``framemd5`` -- the code under test is never
asked to certify itself.  Nothing here starts a runtime, queues a job or touches the network.
"""

from __future__ import annotations

import dataclasses
import hashlib
import subprocess
import threading
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.driving_video_inspection import inspect_driving_video, run_bounded_process
from src.video.motion_library import harvest as harvest_module
from src.video.motion_library.harvest import (
    STATUS_CANCELLED_HARVEST,
    STATUS_DUPLICATE,
    STATUS_FAILED_HARVEST,
    STATUS_HARVESTED,
    STATUS_REFUSED,
    STATUS_REUSED,
    HarvestLineage,
    HarvestRequest,
    harvest_motion,
    harvest_staging_root,
)
from src.video.motion_library.harvest_window import normalized_offsets
from src.video.motion_library.models import CADENCE_NORMALIZED_24
from src.video.motion_library.store import MotionLibraryStore
from src.video.motion_library.verification import FILE_CHANGED, FILE_OK, verify_content

FFMPEG = resolve_ffmpeg_executable()
FFPROBE = resolve_ffprobe_executable()
pytestmark = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="FFmpeg/FFprobe are not installed"
)


def _run(*args: object) -> None:
    subprocess.run([str(a) for a in args], check=True, capture_output=True, timeout=120)


def _clip(
    tmp_path: Path,
    name: str = "clip.mp4",
    *,
    rate: str = "30",
    frames: int = 60,
    size: str = "64x48",
) -> Path:
    path = tmp_path / name
    _run(
        FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}",
        "-frames:v", frames, "-pix_fmt", "yuv420p", "-c:v", "libx264", path,
    )  # fmt: skip
    return path


def _static_clip(tmp_path: Path, name: str = "static.mp4", frames: int = 60) -> Path:
    path = tmp_path / name
    _run(
        FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:size=64x48:rate=30",
        "-frames:v", frames, "-pix_fmt", "yuv420p", "-c:v", "libx264", path,
    )  # fmt: skip
    return path


def _digests(path: Path) -> list[str]:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", "-nostdin", "-noautorotate", "-i", str(path), "-map", "0:v:0", "-an",
         "-fps_mode", "passthrough", "-pix_fmt", "yuv420p", "-f", "framemd5", "-"],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in result.stdout.decode().splitlines()
        if line and not line.startswith("#")
    ]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> MotionLibraryStore:
    return MotionLibraryStore(tmp_path / "library")


def _harvest(store: MotionLibraryStore, clip: Path, **kw: Any):
    request = HarvestRequest(source_path=str(clip), **kw)
    return harvest_motion(store, request)


def _derivative(store: MotionLibraryStore, asset_id: str) -> Path:
    asset = store.require(asset_id)
    return store.asset_path(asset)


# ------------------------------------------------------------------------------ exact frames


@pytest.mark.parametrize(
    ("rate", "frames"), [("16", 40), ("24", 48), ("30", 60), ("60", 90), ("30000/1001", 60)]
)
def test_native_cadence_keeps_exactly_the_selected_frames_at_every_rate(
    tmp_path: Path, store: MotionLibraryStore, rate: str, frames: int
) -> None:
    clip = _clip(tmp_path, rate=rate, frames=frames)
    before = _sha(clip)
    source = _digests(clip)

    outcome = _harvest(store, clip, start=5, end=29, unit="frames", name="mid")

    assert outcome.status == STATUS_HARVESTED, outcome.message
    asset = store.require(outcome.asset_id)
    assert _digests(_derivative(store, outcome.asset_id)) == source[5:29]
    assert asset.frame_count == 24
    assert asset.harvest is not None
    assert (asset.harvest.start_frame, asset.harvest.end_frame) == (5, 29)
    assert asset.harvest.original_sha256 == before
    assert asset.sha256 != before  # derivative and original identities stay distinct
    assert asset.harvest.derivative_frame_rate == asset.harvest.original_frame_rate.replace(
        "30/1", "30/1"
    )
    assert _sha(clip) == before  # the original is never modified
    assert not list(harvest_staging_root(store).rglob("*.mp4"))  # staging is cleaned


def test_a_window_is_not_constrained_by_any_workflow_length(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path, rate="30", frames=300)
    outcome = _harvest(store, clip, start=0, end=150, unit="frames")  # five seconds, 150 frames
    assert outcome.status == STATUS_HARVESTED, outcome.message
    assert store.require(outcome.asset_id).frame_count == 150  # not a 4n+1 generation length


def test_normalized_cadence_is_explicit_24_fps_with_verified_frames(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path, rate="60", frames=120)
    source = _digests(clip)
    outcome = _harvest(
        store, clip, start=0, end=60, unit="frames", cadence=CADENCE_NORMALIZED_24, name="n24"
    )
    assert outcome.status == STATUS_HARVESTED, outcome.message
    offsets = normalized_offsets(60, Fraction(60))
    assert len(offsets) == 24
    assert _digests(_derivative(store, outcome.asset_id)) == [source[i] for i in offsets]
    record = store.require(outcome.asset_id).harvest
    assert record is not None
    assert record.cadence == CADENCE_NORMALIZED_24
    assert record.derivative_frame_rate == "24/1"
    assert record.omitted_frames == 36 and record.repeated_frames == 0


def test_seconds_are_placed_on_an_exact_fractional_timeline(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path, rate="30000/1001", frames=90)
    outcome = _harvest(store, clip, start=1.0, end=2.0, unit="seconds")
    assert outcome.status == STATUS_HARVESTED, outcome.message
    record = store.require(outcome.asset_id).harvest
    assert record is not None
    # 1.0 s * 30000/1001 = 29.97 -> frame 30; 2.0 s -> 59.94 -> frame 60 (nearest, exact arithmetic)
    assert (record.start_frame, record.end_frame) == (30, 60)
    assert (record.requested_start, record.requested_end, record.requested_unit) == (
        1.0,
        2.0,
        "seconds",
    )
    assert _digests(_derivative(store, outcome.asset_id)) == _digests(clip)[30:60]


# ------------------------------------------------------------------------------ several windows, reuse


def test_several_named_windows_come_from_one_unchanged_original(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path, frames=90)
    before = _sha(clip)
    names = {
        "stand_up_front_static": (0, 20),
        "turn_left_three_quarter": (20, 50),
        "wave": (50, 90),
    }
    ids = {}
    for name, (start, end) in names.items():
        outcome = _harvest(store, clip, start=start, end=end, unit="frames", name=name)
        assert outcome.status == STATUS_HARVESTED, outcome.message
        ids[name] = outcome.asset_id
    assert len(set(ids.values())) == 3
    assert {store.require(i).display_name for i in ids.values()} == set(names)
    assert {store.require(i).harvest.original_sha256 for i in ids.values()} == {before}  # type: ignore[union-attr]
    assert len(store.harvests_of(before)) == 3
    assert _sha(clip) == before


def test_the_same_cut_is_reused_without_re_encoding(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path)
    first = _harvest(store, clip, start=0, end=30, unit="frames", name="one")
    calls: list[Sequence[str]] = []

    def runner(command: Sequence[str], **kwargs: Any):
        calls.append(command)
        return run_bounded_process(command, **kwargs)

    again = harvest_motion(
        store,
        HarvestRequest(str(clip), start=0, end=30, unit="frames", name="a different name"),
        runner=runner,
    )
    assert again.status == STATUS_REUSED
    assert again.asset_id == first.asset_id
    assert len(store) == 1
    assert store.require(first.asset_id).display_name == "one"
    # only the probe ran; nothing was decoded or encoded for the reuse
    assert all("framemd5" not in " ".join(c) and "libx264" not in " ".join(c) for c in calls)


def test_identical_bytes_keep_one_identity_and_report_what_was_not_applied(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _static_clip(tmp_path)
    first = _harvest(store, clip, start=0, end=20, unit="frames", name="red a")
    second = _harvest(
        store,
        clip,
        start=10,
        end=30,
        unit="frames",
        name="red b",
        annotations={"framing": "full_body", "tags": ["extra"]},
    )
    assert first.status == STATUS_HARVESTED
    assert second.status == STATUS_DUPLICATE, second.message
    assert second.asset_id == first.asset_id and len(store) == 1
    assert "framing" in second.message and "not applied" in second.message
    assert "extra" in store.require(first.asset_id).tags  # tags are merged, never lost
    assert store.require(first.asset_id).harvest.start_frame == 0  # type: ignore[union-attr]  # first record kept


# ------------------------------------------------------------------------------ refusals


def test_refusals_are_readable_and_publish_nothing(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path, frames=30)
    cases = [
        ({"source_path": str(tmp_path / "missing.mp4"), "start": 0, "end": 5}, "does not exist"),
        (
            {"source_path": str(tmp_path / "x.avi"), "start": 0, "end": 5},
            "Unsupported video format",
        ),
        ({"source_path": str(clip), "start": 10, "end": 10}, "empty"),
        ({"source_path": str(clip), "start": 20, "end": 10}, "empty"),
        ({"source_path": str(clip), "start": 0, "end": 31}, "30 frames"),
        ({"source_path": str(clip), "start": 40, "end": 50}, "30 frames"),
        ({"source_path": str(clip), "start": 0.5, "end": 3, "unit": "frames"}, "whole number"),
        ({"source_path": str(clip), "start": 0, "end": 5, "cadence": "warp"}, "Unknown cadence"),
        ({"source_path": "", "start": 0, "end": 5}, "No video"),
    ]
    for kwargs, expected in cases:
        kwargs.setdefault("unit", "frames")
        outcome = harvest_motion(store, HarvestRequest(**kwargs))
        assert outcome.status == STATUS_REFUSED, (kwargs, outcome)
        assert expected in outcome.message, (kwargs, outcome.message)
    assert len(store) == 0
    assert not (store.managed_dir.exists() and any(store.managed_dir.iterdir()))


def test_variable_frame_rate_is_refused_not_silently_retimed(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path)

    def vfr_inspect(path: Path, **kwargs: Any):
        real = inspect_driving_video(path, **kwargs)
        assert real.facts is not None
        return dataclasses.replace(
            real, facts=dataclasses.replace(real.facts, fps_is_variable_suspected=True)
        )

    outcome = harvest_motion(
        store, HarvestRequest(str(clip), start=0, end=10, unit="frames"), inspect=vfr_inspect
    )
    assert outcome.status == STATUS_REFUSED and outcome.code == "variable_frame_rate"
    assert "constant frame rate" in outcome.message
    assert len(store) == 0


def test_end_of_the_source_can_be_requested_without_a_number(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path, frames=45)
    outcome = _harvest(store, clip, start=15, end=None, unit="frames")
    assert outcome.status == STATUS_HARVESTED, outcome.message
    assert _digests(_derivative(store, outcome.asset_id)) == _digests(clip)[15:45]


# ------------------------------------------------------------------------------ cancellation and failure


def test_a_cancel_before_work_publishes_nothing(tmp_path: Path, store: MotionLibraryStore) -> None:
    clip = _clip(tmp_path)
    cancel = threading.Event()
    cancel.set()
    outcome = harvest_motion(
        store, HarvestRequest(str(clip), start=0, end=20, unit="frames"), cancel=cancel
    )
    assert outcome.status == STATUS_CANCELLED_HARVEST
    assert len(store) == 0
    assert not list(store.root.rglob("*.mp4"))


def test_a_cancel_during_encoding_leaves_no_partial_asset_or_staged_file(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path)
    cancel = threading.Event()
    seen = {"encodes": 0}

    def runner(command: Sequence[str], **kwargs: Any):
        if "libx264" in " ".join(command):
            seen["encodes"] += 1
            cancel.set()  # the operator cancels as the encode starts; the real runner honours it
        return run_bounded_process(command, **kwargs)

    outcome = harvest_motion(
        store,
        HarvestRequest(str(clip), start=0, end=20, unit="frames"),
        cancel=cancel,
        runner=runner,
    )
    assert seen["encodes"] == 1
    assert outcome.status == STATUS_CANCELLED_HARVEST
    assert len(store) == 0
    assert not list(store.root.rglob("*.mp4")) and not list(store.root.rglob("*.partial"))
    assert not list(store.root.rglob(".preparing-*"))


def test_a_manifest_write_failure_leaves_no_asset_copy_or_staged_file(
    tmp_path: Path, store: MotionLibraryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    clip = _clip(tmp_path)
    monkeypatch.setattr(
        "src.video.motion_library.store.atomic_write_json",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    outcome = _harvest(store, clip, start=0, end=20, unit="frames")
    assert outcome.status == STATUS_FAILED_HARVEST and outcome.code == "library_failed"
    assert "disk full" in outcome.message
    assert len(store) == 0
    assert not list(store.managed_dir.glob("*")) if store.managed_dir.exists() else True
    assert not list(harvest_staging_root(store).rglob("*.mp4"))
    assert not store.manifest_path.exists()  # nothing was written; a later write still works
    monkeypatch.undo()
    assert _harvest(store, clip, start=0, end=20, unit="frames").status == STATUS_HARVESTED


# ------------------------------------------------------------------------------ identity after harvest


def test_the_derivative_verifies_without_its_original_and_a_changed_file_is_rejected(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path)
    outcome = _harvest(store, clip, start=0, end=20, unit="frames")
    asset = store.require(outcome.asset_id)
    clip.unlink()  # the historical parent is gone
    path = store.asset_path(asset)
    assert verify_content(asset, path).state == FILE_OK
    assert MotionLibraryStore(store.root).require(asset.asset_id).harvest == asset.harvest
    path.write_bytes(path.read_bytes() + b"x")  # an altered derivative
    assert verify_content(asset, path).state == FILE_CHANGED


def test_lineage_is_recorded_only_as_given_and_inherits_library_terms(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    clip = _clip(tmp_path)
    lineage = HarvestLineage(
        "verified", "job-7", str(clip), _sha(clip), "History names this artifact."
    )
    outcome = harvest_motion(
        store,
        HarvestRequest(str(clip), start=0, end=20, unit="frames", lineage=lineage),
    )
    asset = store.require(outcome.asset_id)
    assert asset.harvest is not None
    assert (asset.harvest.lineage_state, asset.harvest.lineage_job_id) == ("verified", "job-7")
    assert asset.source_category == "stablenew_generated"
    assert asset.origin is None  # the derivative is not itself a generated artifact
    plain = _harvest(store, clip, start=20, end=40, unit="frames")
    assert store.require(plain.asset_id).harvest.lineage_state == "none"  # type: ignore[union-attr]


def test_orientation_metadata_survives_harvest(tmp_path: Path, store: MotionLibraryStore) -> None:
    base = _clip(tmp_path, "base.mp4", frames=40)
    clip = tmp_path / "rotated.mp4"
    _run(FFMPEG, "-v", "error", "-y", "-display_rotation:v:0", "90", "-i", base, "-c", "copy", clip)
    probe = inspect_driving_video(clip, frame_count=0)
    assert probe.facts is not None and probe.facts.rotation_quadrants % 2 == 1
    outcome = _harvest(store, clip, start=0, end=20, unit="frames")
    assert outcome.status == STATUS_HARVESTED, outcome.message
    derived = inspect_driving_video(_derivative(store, outcome.asset_id), frame_count=0)
    assert derived.facts is not None
    assert derived.facts.rotation_quadrants == probe.facts.rotation_quadrants
    assert (derived.facts.display_width, derived.facts.display_height) == (
        probe.facts.display_width,
        probe.facts.display_height,
    )


def test_harvesting_never_starts_a_runtime_or_a_job(
    tmp_path: Path, store: MotionLibraryStore
) -> None:
    """The module imports no queue, job service, runner or Comfy client of its own."""

    source = Path(harvest_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "JobService",
        "submit_njrs",
        "PipelineRunner",
        "comfy_process_manager",
        "requests",
        "socket",
    ):
        assert forbidden not in source
    clip = _clip(tmp_path)
    assert _harvest(store, clip, start=0, end=10, unit="frames").status == STATUS_HARVESTED
