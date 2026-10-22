"""PR-VID-SEQ-330-CORE: the sequence executor, its ledger, warm-runtime ownership, resume, frames and assembly.

Fake segment callbacks write small real PNGs; no GPU, runtime or network. FFmpeg tests skip when FFmpeg is absent.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.video import resolve_ffmpeg_executable
from src.pipeline.video_sequence_executor import (
    ALLOWED_OVERRIDES,
    SegmentRun,
    VideoSequenceExecutor,
    apply_stage_overrides,
    segment_overrides,
)
from src.video.sequence_assembly import SequenceAssemblyError, assemble_sequence_frames
from src.video.sequence_frames import (
    SequenceFrameError,
    collect_segment_artifacts,
    color_match_luts,
    match_segment_colors,
    trim_overlap,
)
from src.video.sequence_ledger import (
    BASIS_DECODED,
    BASIS_NATIVE,
    LEDGER_FILE_NAME,
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTERRUPTED,
    read_ledger,
    sha256_of,
    verify_segment_files,
)
from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ANCHOR_PROVIDED,
    ANCHOR_SOURCE,
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SegmentSpec,
    SequenceAssembly,
    SequenceColorMatch,
    SequencePlan,
    SequencePlanError,
)
from src.video.sequence_resume import SequenceResumeError, resume_problems

needs_ffmpeg = pytest.mark.skipif(
    resolve_ffmpeg_executable() is None, reason="FFmpeg is not installed"
)
WORKFLOW = "wan22_ti2v_5b_i2v_v1"


def _png(path: Path, shade: int, size: tuple[int, int] = (32, 32)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (shade % 256, (shade * 3) % 256, 40)).save(path)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _segment(index: int, **kw: Any) -> SegmentSpec:
    base: dict[str, Any] = {
        "index": index,
        "seed": 100 + index,
        "frame_count": 5,
        "anchor_policy": ANCHOR_SOURCE if index == 0 else ANCHOR_CARRY,
        "workflow_id": WORKFLOW,
        "workflow_version": "1.3.0",
    }
    base.update(kw)
    return SegmentSpec(**base)


def _plan(count: int = 3, *, stage: str = STAGE_VIDEO_WORKFLOW, **kw: Any) -> SequencePlan:
    segments = (
        tuple(_segment(i) for i in range(count))
        if stage == STAGE_VIDEO_WORKFLOW
        else tuple(
            SegmentSpec(
                index=i,
                seed=500 + i,
                frame_count=5,
                anchor_policy=ANCHOR_SOURCE if i == 0 else ANCHOR_CARRY,
            )
            for i in range(count)
        )
    )
    return SequencePlan(sequence_id="seq-test", stage=stage, fps=24, segments=segments, **kw)


class Segments:
    """A scripted segment callback that writes real frames and records how it was called."""

    def __init__(
        self,
        run_dir: Path,
        *,
        fail_on: int | None = None,
        exc: BaseException | None = None,
        mode: str = "frames_out",
    ) -> None:
        self.run_dir = run_dir
        self.fail_on = fail_on
        self.exc = exc or RuntimeError("segment failed")
        self.mode = mode
        self.calls: list[tuple[SegmentSpec, str, bool]] = []
        self.ledger_sizes: list[int] = []
        self.input_hashes: list[str] = []

    def __call__(self, segment: SegmentSpec, input_path: str, hold: bool) -> SegmentRun:
        ledger_file = self.run_dir / LEDGER_FILE_NAME
        self.ledger_sizes.append(
            len(read_ledger(ledger_file).segments) if ledger_file.is_file() else -1
        )
        self.input_hashes.append(_sha(Path(input_path)))
        self.calls.append((segment, input_path, hold))
        if self.fail_on == segment.index:
            raise self.exc
        frames = [
            _png(self.run_dir / f"seg{segment.index}_{n:05d}_.png", segment.seed + n * 11)
            for n in range(1, segment.frame_count + 1)
        ]
        clip = self.run_dir / f"seg{segment.index}.mp4"
        clip.write_bytes(f"clip-{segment.index}".encode())
        raw: dict[str, Any] = {"frame_paths": [str(p) for p in frames], "video_path": str(clip)}
        if self.mode == "frames_out":
            raw["frames_out"] = {
                "last_frame_path": str(frames[-1]),
                "last_frame_sha256": _sha(frames[-1]),
                "frame_count": len(frames),
            }
        elif self.mode == "svd":
            native = _png(
                self.run_dir / "sequence" / "native" / f"seg_{segment.index:02d}_native_last.png",
                250,
            )
            raw["native_final_frame"] = {
                "path": str(native),
                "sha256": _sha(native),
                "frame_index": segment.frame_count - 1,
            }
        elif self.mode == "decoded":
            raw.pop("frame_paths")
        return SegmentRun(raw_result=raw, output_paths=(str(clip),))


def _decoder(run_dir: Path, count: int | None = None):
    def decode(clip: Path, out_dir: Path, _cancel: CancelToken | None) -> list[Path]:
        n = 5 if count is None else count
        return [_png(out_dir / f"d_{i:06d}.png", 90 + i) for i in range(1, n + 1)]

    return decode


def _fake_assemble(frames, plan, *, run_dir, job_id, cancel_token=None):
    out = Path(run_dir) / f"{plan.assembly.clip_name}.mp4"
    out.write_bytes(b"movie")
    manifest = Path(run_dir) / "manifests" / "asm.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"frames": [str(f) for f in frames]}), encoding="utf-8")
    return SimpleNamespace(
        output_path=out,
        manifest_path=manifest,
        output_sha256=_sha(out),
        timeline=SimpleNamespace(total_frames=len(frames), fps=plan.fps),
    )


class Release:
    def __init__(self, *, boom: bool = False) -> None:
        self.count = 0
        self.boom = boom

    def __call__(self) -> dict[str, Any]:
        self.count += 1
        if self.boom:
            raise OSError("process manager exploded")
        return {"released": True, "ownership": "stablenew"}


def _executor(
    tmp_path: Path, plan: SequencePlan, segments: Segments, **kw: Any
) -> VideoSequenceExecutor:
    kw.setdefault("assemble", _fake_assemble)
    return VideoSequenceExecutor(
        plan=plan, job_id="job-1", run_dir=tmp_path, run_segment=segments, **kw
    )


def _source(tmp_path: Path) -> str:
    return str(_png(tmp_path / "src" / "source.png", 7))


# ---------------------------------------------------------------------------------------- carry-forward


def test_each_segment_starts_from_the_exact_last_frame_png_of_the_one_before(
    tmp_path: Path,
) -> None:
    segments = Segments(tmp_path)
    outcome = _executor(tmp_path, _plan(3), segments).execute(source_image_path=_source(tmp_path))

    assert [Path(call[1]).suffix for call in segments.calls] == [".png"] * 3
    assert segments.calls[0][1].endswith("source.png")
    ledger = outcome.ledger
    for position in (1, 2):
        carried = Path(segments.calls[position][1])
        previous = ledger.segments[position - 1]
        assert carried == Path(previous.final_frame.file.path)
        assert (
            carried.suffix == ".png"
            and segments.input_hashes[position] == previous.final_frame.file.sha256
        )
        assert previous.final_frame.file.sha256 == _sha(
            Path(previous.frames[-1].path)
        )  # byte-identical to the frame
        assert previous.final_frame.basis == BASIS_NATIVE


def test_per_segment_seeds_counts_and_workflows_reach_the_backend_seam(tmp_path: Path) -> None:
    plan = SequencePlan(
        sequence_id="mix",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=(
            _segment(0, seed=11, frame_count=5, workflow_version="1.2.0"),
            _segment(1, seed=22, frame_count=9, workflow_version="1.3.0", prompt="walks"),
            _segment(2, seed=33, frame_count=5, workflow_version="1.3.0"),
        ),
    )
    segments = Segments(tmp_path)
    _executor(tmp_path, plan, segments).execute(source_image_path=_source(tmp_path))

    seen = [
        (c[0].seed, c[0].frame_count, c[0].workflow_version, c[0].prompt) for c in segments.calls
    ]
    assert seen == [(11, 5, "1.2.0", ""), (22, 9, "1.3.0", "walks"), (33, 5, "1.3.0", "")]
    overrides = [segment_overrides(plan, call[0]) for call in segments.calls]
    assert [o["seed"] for o in overrides] == [11, 22, 33]
    assert [o["frame_count"] for o in overrides] == [5, 9, 5]
    assert [o["workflow_version"] for o in overrides] == ["1.2.0", "1.3.0", "1.3.0"]
    assert [o["video_execution"]["workflow_version"] for o in overrides] == [
        "1.2.0",
        "1.3.0",
        "1.3.0",
    ]


def test_the_override_seam_is_allow_listed_and_never_mutates_the_frozen_config() -> None:
    frozen = {
        "seed": 1,
        "frame_count": 49,
        "workflow_id": WORKFLOW,
        "video_execution": {"workflow_id": WORKFLOW},
    }
    merged = apply_stage_overrides(
        frozen,
        {"seed": 9, "video_execution": {"workflow_version": "1.3.0"}},
        stage=STAGE_VIDEO_WORKFLOW,
    )

    assert merged["seed"] == 9 and merged["video_execution"] == {
        "workflow_id": WORKFLOW,
        "workflow_version": "1.3.0",
    }
    assert frozen == {
        "seed": 1,
        "frame_count": 49,
        "workflow_id": WORKFLOW,
        "video_execution": {"workflow_id": WORKFLOW},
    }
    with pytest.raises(SequencePlanError, match="pose_video_path"):
        apply_stage_overrides(frozen, {"pose_video_path": "x"}, stage=STAGE_VIDEO_WORKFLOW)
    with pytest.raises(SequencePlanError, match="not allowed"):
        apply_stage_overrides({}, {"inference": {"model_id": "other"}}, stage=STAGE_SVD_NATIVE)
    assert "inference.seed" in ALLOWED_OVERRIDES[STAGE_SVD_NATIVE]
    svd = apply_stage_overrides(
        {"inference": {"seed": 1, "num_frames": 25, "fps": 6}, "output": {"save_frames": False}},
        segment_overrides(
            _plan(2, stage=STAGE_SVD_NATIVE), _plan(2, stage=STAGE_SVD_NATIVE).segments[1]
        ),
        stage=STAGE_SVD_NATIVE,
    )
    assert (
        svd["inference"] == {"seed": 501, "num_frames": 5, "fps": 6}
        and svd["output"]["save_frames"] is True
    )


# ---------------------------------------------------------------------------------------- the ledger


def test_the_ledger_is_written_before_the_next_segment_dispatches(tmp_path: Path) -> None:
    segments = Segments(tmp_path)
    _executor(tmp_path, _plan(3), segments).execute(source_image_path=_source(tmp_path))

    assert segments.ledger_sizes == [0, 1, 2]  # segment n saw segments 0..n-1 already recorded


def test_ledger_records_hashes_final_frame_identity_and_processing(tmp_path: Path) -> None:
    segments = Segments(tmp_path)
    outcome = _executor(tmp_path, _plan(2), segments).execute(source_image_path=_source(tmp_path))

    ledger = read_ledger(outcome.ledger_path, expected_sha256=outcome.ledger_sha256)
    assert ledger.state == STATE_COMPLETED and ledger.plan_sha256 == _plan(2).plan_sha256()
    first = ledger.segments[0]
    assert (first.seed, first.expected_frame_count, first.frame_count) == (100, 5, 5)
    assert first.clip is not None and first.clip.sha256 == _sha(Path(first.clip.path))
    assert all(record.sha256 == _sha(Path(record.path)) for record in first.frames)
    assert (
        first.processing["backend"] == "comfy"
        and first.processing["frame_count_matches_plan"] is True
    )
    assert verify_segment_files(ledger.segments) == []


def test_a_failed_segment_preserves_a_valid_completed_prefix(tmp_path: Path) -> None:
    segments = Segments(tmp_path, fail_on=2)
    with pytest.raises(RuntimeError, match="segment failed"):
        _executor(tmp_path, _plan(4), segments).execute(source_image_path=_source(tmp_path))

    ledger = read_ledger(tmp_path / LEDGER_FILE_NAME)
    assert ledger.state == STATE_FAILED and "segment failed" in ledger.error
    assert [s.index for s in ledger.segments] == [0, 1]
    assert verify_segment_files(ledger.segments) == []
    assert len(segments.calls) == 3  # the failing segment dispatched; the fourth never did


def test_a_frames_out_count_that_differs_from_the_plan_blocks_continuation(tmp_path: Path) -> None:
    class Short(Segments):
        def __call__(self, segment, input_path, hold):
            run = super().__call__(segment, input_path, hold)
            raw = dict(run.raw_result)
            raw["frame_paths"] = raw["frame_paths"][:-1]
            raw["frames_out"] = {
                **raw["frames_out"],
                "last_frame_path": raw["frame_paths"][-1],
                "last_frame_sha256": _sha(Path(raw["frame_paths"][-1])),
            }
            return SegmentRun(raw, run.output_paths)

    short = Short(tmp_path)
    with pytest.raises(
        SequenceFrameError, match="saved 4 frames but the segment was admitted with 5"
    ):
        _executor(tmp_path, _plan(2), short).execute(source_image_path=_source(tmp_path))

    ledger = read_ledger(tmp_path / LEDGER_FILE_NAME)
    assert ledger.state == STATE_FAILED and ledger.segments == []  # nothing short is ever committed
    assert len(short.calls) == 1  # and no later segment is conditioned on it
    assert not (
        tmp_path / "sequence" / "anchors" / "seg_00_last.png"
    ).exists()  # its staging is cleaned up


# ---------------------------------------------------------------------------------------- runtime ownership


def test_the_runtime_is_held_for_every_segment_and_released_once_on_success(tmp_path: Path) -> None:
    segments, release = Segments(tmp_path), Release()
    outcome = _executor(tmp_path, _plan(3), segments, release_runtime=release).execute(
        source_image_path=_source(tmp_path)
    )

    assert [call[2] for call in segments.calls] == [True, True, True]
    assert release.count == 1
    assert outcome.ledger.runtime_release == {"released": True, "ownership": "stablenew"}
    assert read_ledger(outcome.ledger_path, expected_sha256=outcome.ledger_sha256).runtime_release


@pytest.mark.parametrize(
    ("exc", "state"),
    [
        (RuntimeError("boom"), STATE_FAILED),
        (CancellationError("cancelled"), STATE_CANCELLED),
        (KeyboardInterrupt(), STATE_INTERRUPTED),
    ],
)
def test_one_release_attempt_on_failure_cancel_and_base_exception(
    tmp_path: Path, exc: BaseException, state: str
) -> None:
    segments, release = Segments(tmp_path, fail_on=1, exc=exc), Release()

    with pytest.raises(type(exc)):
        _executor(tmp_path, _plan(3), segments, release_runtime=release).execute(
            source_image_path=_source(tmp_path)
        )

    assert release.count == 1
    ledger = read_ledger(tmp_path / LEDGER_FILE_NAME)
    assert ledger.state == state and [s.index for s in ledger.segments] == [0]


def test_cancel_between_segments_stops_dispatch_and_still_releases_once(tmp_path: Path) -> None:
    token, release = CancelToken(), Release()
    segments = Segments(tmp_path)
    original = segments.__call__

    def cancelling(segment, input_path, hold):
        run = original(segment, input_path, hold)
        token.cancel()
        return run

    executor = VideoSequenceExecutor(
        plan=_plan(3),
        job_id="j",
        run_dir=tmp_path,
        run_segment=cancelling,
        release_runtime=release,
        cancel_token=token,
        assemble=_fake_assemble,
    )
    with pytest.raises(CancellationError):
        executor.execute(source_image_path=_source(tmp_path))

    assert len(segments.calls) == 1 and release.count == 1
    assert read_ledger(tmp_path / LEDGER_FILE_NAME).state == STATE_CANCELLED


def test_a_failing_release_never_masks_the_sequences_own_error(tmp_path: Path) -> None:
    segments, release = Segments(tmp_path, fail_on=0), Release(boom=True)

    with pytest.raises(RuntimeError, match="segment failed"):
        _executor(tmp_path, _plan(2), segments, release_runtime=release).execute(
            source_image_path=_source(tmp_path)
        )

    assert release.count == 1
    assert read_ledger(tmp_path / LEDGER_FILE_NAME).runtime_release == {
        "released": False,
        "error": "release raised OSError: process manager exploded",
    }


def test_no_release_callback_means_nothing_is_touched(tmp_path: Path) -> None:
    outcome = _executor(tmp_path, _plan(2), Segments(tmp_path)).execute(
        source_image_path=_source(tmp_path)
    )

    assert outcome.ledger.runtime_release is None


# ---------------------------------------------------------------------------------------- final-frame basis


def test_native_svd_uses_the_pre_postprocess_frame_not_the_exported_one(tmp_path: Path) -> None:
    segments = Segments(tmp_path, mode="svd")
    outcome = _executor(tmp_path, _plan(2, stage=STAGE_SVD_NATIVE), segments).execute(
        source_image_path=_source(tmp_path)
    )

    final = outcome.ledger.segments[0].final_frame
    native = tmp_path / "sequence" / "native" / "seg_00_native_last.png"
    assert final.basis == BASIS_NATIVE and final.detail["origin"] == "svd_native_pre_postprocess"
    assert final.file.sha256 == _sha(native)
    assert final.file.sha256 != _sha(
        Path(outcome.ledger.segments[0].frames[-1].path)
    )  # not the exported last frame
    assert segments.input_hashes[1] == _sha(native)


def test_frames_out_uses_the_original_png_and_checks_the_backends_own_hash(tmp_path: Path) -> None:
    frames = [_png(tmp_path / f"f_{n:05d}_.png", n * 9) for n in (1, 2, 3)]
    raw = {
        "frame_paths": [str(p) for p in reversed(frames)],  # unordered on purpose
        "frames_out": {"last_frame_path": str(frames[-1]), "last_frame_sha256": _sha(frames[-1])},
    }

    artifacts = collect_segment_artifacts(
        raw, segment_index=0, expected_frame_count=3, run_dir=tmp_path
    )

    assert [p.name for p in artifacts.frames] == ["f_00001_.png", "f_00002_.png", "f_00003_.png"]
    assert artifacts.final_frame.basis == BASIS_NATIVE
    assert artifacts.final_frame.file.sha256 == _sha(frames[-1])
    assert artifacts.final_frame.file.path.endswith("seg_00_last.png")

    raw["frames_out"]["last_frame_sha256"] = "0" * 64
    with pytest.raises(SequenceFrameError, match="does not match the hash its backend recorded"):
        collect_segment_artifacts(raw, segment_index=0, expected_frame_count=3, run_dir=tmp_path)


def test_a_decoded_fallback_is_named_and_validated(tmp_path: Path) -> None:
    segments = Segments(tmp_path, mode="decoded")
    outcome = _executor(tmp_path, _plan(2), segments, decode_clip=_decoder(tmp_path)).execute(
        source_image_path=_source(tmp_path)
    )

    final = outcome.ledger.segments[0].final_frame
    assert final.basis == BASIS_DECODED
    assert final.detail["decoded_frame_count"] == final.detail["expected_frame_count"] == 5
    assert final.detail["clip_sha256"] == _sha(tmp_path / "seg0.mp4")
    assert final.file.path.endswith(".png") and Path(segments.calls[1][1]).suffix == ".png"

    with pytest.raises(SequenceFrameError, match="decoded fallback is refused"):
        _executor(
            tmp_path / "bad",
            _plan(2),
            Segments(tmp_path / "bad", mode="decoded"),
            decode_clip=_decoder(tmp_path, count=4),
        ).execute(source_image_path=_source(tmp_path))


def test_a_segment_with_neither_frames_nor_clip_cannot_provide_an_anchor(tmp_path: Path) -> None:
    with pytest.raises(SequenceFrameError, match="neither frames nor a clip"):
        collect_segment_artifacts({}, segment_index=1, expected_frame_count=5, run_dir=tmp_path)


# ---------------------------------------------------------------------------------------- authored anchors


def test_a_provided_anchor_is_verified_before_any_dispatch_and_again_before_its_segment(
    tmp_path: Path,
) -> None:
    anchor = _png(tmp_path / "anchors" / "authored.png", 77)
    plan = SequencePlan(
        sequence_id="prov",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=(
            _segment(0),
            _segment(
                1,
                anchor_policy=ANCHOR_PROVIDED,
                anchor_path=str(anchor),
                anchor_sha256=_sha(anchor),
            ),
        ),
    )
    segments = Segments(tmp_path)
    _executor(tmp_path, plan, segments).execute(source_image_path=_source(tmp_path))
    assert segments.calls[1][1] == str(anchor)

    anchor.write_bytes(anchor.read_bytes() + b"x")  # changed after admission
    again = Segments(tmp_path / "again")
    with pytest.raises(SequencePlanError, match="changed since it was queued"):
        _executor(tmp_path / "again", plan, again).execute(source_image_path=_source(tmp_path))
    assert again.calls == []  # refused before the first dispatch

    anchor.unlink()
    with pytest.raises(SequencePlanError, match="anchor is missing"):
        _executor(tmp_path / "gone", plan, Segments(tmp_path / "gone")).execute(
            source_image_path=_source(tmp_path)
        )


def test_a_tampered_carried_frame_stops_the_next_dispatch(tmp_path: Path) -> None:
    run = Segments(tmp_path)
    executor = _executor(tmp_path, _plan(3), run)
    original_persist = executor._persist

    def persist_then_corrupt() -> None:
        original_persist()
        done = executor._ledger.segments
        if len(done) == 1:  # between "segment 0 recorded" and "segment 1 dispatched"
            Path(done[0].final_frame.file.path).write_bytes(b"corrupted")

    executor._persist = persist_then_corrupt  # type: ignore[method-assign]

    with pytest.raises(SequencePlanError, match="carried frame of segment 0 is missing or changed"):
        executor.execute(source_image_path=_source(tmp_path))

    assert len(run.calls) == 1  # segment 1 never dispatched


# ---------------------------------------------------------------------------------------- resume


def _failed_parent(tmp_path: Path, plan: SequencePlan, *, fail_on: int = 2) -> tuple[Path, str]:
    parent_dir = tmp_path / "parent"
    with pytest.raises(RuntimeError):
        _executor(parent_dir, plan, Segments(parent_dir, fail_on=fail_on)).execute(
            source_image_path=_source(tmp_path)
        )
    ledger_path = parent_dir / LEDGER_FILE_NAME
    return ledger_path, sha256_of(ledger_path)


def _resume_block(plan: SequencePlan, ledger_path: Path, sha: str, start: int) -> dict[str, Any]:
    return {
        "parent_job_id": "job-1",
        "parent_ledger_path": str(ledger_path),
        "parent_ledger_sha256": sha,
        "plan_sha256": plan.plan_sha256(),
        "from_segment": start,
    }


def test_resume_verifies_and_copies_the_prefix_and_runs_only_the_suffix(tmp_path: Path) -> None:
    plan = _plan(4)
    ledger_path, sha = _failed_parent(tmp_path, plan, fail_on=2)
    child_dir = tmp_path / "child"
    segments = Segments(child_dir)

    outcome = _executor(child_dir, plan, segments).execute(
        source_image_path=_source(tmp_path), resume=_resume_block(plan, ledger_path, sha, 2)
    )

    assert [call[0].index for call in segments.calls] == [2, 3]  # only the unfinished suffix ran
    ledger = outcome.ledger
    assert ledger.state == STATE_COMPLETED and [s.index for s in ledger.segments] == [0, 1, 2, 3]
    assert ledger.parent == {
        "job_id": "job-1",
        "ledger_sha256": sha,
        "resumed_from_segment": 2,
        "reused_segments": [0, 1],
    }
    assert [s.origin for s in ledger.segments] == ["reused", "reused", "generated", "generated"]
    for prefix in ledger.segments[
        :2
    ]:  # copied into the child run, never pointing back at the parent
        for record in prefix.artifact_files():
            assert (
                str(child_dir) in record.path
                and "parent" not in Path(record.path).relative_to(child_dir).parts
            )
            assert _sha(Path(record.path)) == record.sha256
    parent = read_ledger(ledger_path)
    assert Path(segments.calls[0][1]) == Path(
        ledger.segments[1].final_frame.file.path
    )  # the copied last frame
    assert segments.input_hashes[0] == parent.segments[1].final_frame.file.sha256
    assert (
        tmp_path / "parent" / LEDGER_FILE_NAME
    ).read_bytes() == ledger_path.read_bytes()  # parent untouched


@pytest.mark.parametrize(
    "what", ["tampered", "missing", "other_plan", "bad_start", "ledger_changed"]
)
def test_resume_refuses_tampered_missing_or_incompatible_artifacts_before_dispatch(
    tmp_path: Path, what: str
) -> None:
    plan = _plan(4)
    ledger_path, sha = _failed_parent(tmp_path, plan, fail_on=2)
    parent = read_ledger(ledger_path)
    start = 2
    run_plan = plan
    if what == "tampered":
        Path(parent.segments[1].frames[0].path).write_bytes(b"altered")
    elif what == "missing":
        Path(parent.segments[0].final_frame.file.path).unlink()
    elif what == "other_plan":
        run_plan = replace(plan, segments=(*plan.segments[:3], replace(plan.segments[3], seed=999)))
    elif what == "bad_start":
        start = 3  # the parent only finished two segments
    elif what == "ledger_changed":
        ledger_path.write_text(ledger_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    child_dir = tmp_path / "child"
    segments = Segments(child_dir)

    with pytest.raises(SequenceResumeError):
        _executor(child_dir, run_plan, segments).execute(
            source_image_path=_source(tmp_path),
            resume=_resume_block(run_plan, ledger_path, sha, start),
        )

    assert segments.calls == []  # nothing was dispatched


def test_resume_problems_names_each_incompatibility() -> None:
    plan = _plan(3)
    assert resume_problems(plan, _empty_ledger(plan), 0) and resume_problems(
        plan, _empty_ledger(plan), 3
    )


def _empty_ledger(plan: SequencePlan):
    from src.video.sequence_ledger import SequenceLedger

    return SequenceLedger(
        sequence_id=plan.sequence_id,
        job_id="j",
        plan_sha256=plan.plan_sha256(),
        total_segments=len(plan.segments),
    )


# ---------------------------------------------------------------------------------------- assembly


def test_assembly_is_given_the_frames_in_segment_order_with_overlap_dropped(tmp_path: Path) -> None:
    plan = SequencePlan(
        sequence_id="ov",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=(_segment(0), _segment(1, overlap_frames=1), _segment(2, overlap_frames=2)),
    )
    captured: list[list[Path]] = []

    def capture(frames, plan_, *, run_dir, job_id, cancel_token=None):
        captured.append([Path(f) for f in frames])
        return _fake_assemble(frames, plan_, run_dir=run_dir, job_id=job_id)

    outcome = _executor(tmp_path, plan, Segments(tmp_path), assemble=capture).execute(
        source_image_path=_source(tmp_path)
    )

    names = [p.name for p in captured[0]]
    assert names == (
        [f"seg0_{n:05d}_.png" for n in range(1, 6)]
        + [f"seg1_{n:05d}_.png" for n in range(2, 6)]  # first frame dropped
        + [f"seg2_{n:05d}_.png" for n in range(3, 6)]  # first two dropped
    )
    assert outcome.ledger.assembly["segments"] == [
        {
            "segment": 0,
            "origin": "generated",
            "frames_used": 5,
            "frames_dropped": 0,
            "color_matched": False,
        },
        {
            "segment": 1,
            "origin": "generated",
            "frames_used": 4,
            "frames_dropped": 1,
            "color_matched": False,
        },
        {
            "segment": 2,
            "origin": "generated",
            "frames_used": 3,
            "frames_dropped": 2,
            "color_matched": False,
        },
    ]
    assert outcome.assembled_path and outcome.output_paths[0] == outcome.assembled_path
    assert outcome.ledger.assembly["output_sha256"] == _sha(Path(outcome.assembled_path))


def test_assembly_off_leaves_only_the_segments(tmp_path: Path) -> None:
    plan = _plan(2, assembly=SequenceAssembly(enabled=False))

    outcome = _executor(tmp_path, plan, Segments(tmp_path)).execute(
        source_image_path=_source(tmp_path)
    )

    assert outcome.assembled_path is None and outcome.ledger.assembly is None
    assert len(outcome.output_paths) == 2


def test_trim_overlap_preserves_order_and_refuses_an_empty_segment() -> None:
    assert trim_overlap([1, 2, 3, 4], 0) == [1, 2, 3, 4]
    assert trim_overlap([1, 2, 3, 4], 3) == [4]
    with pytest.raises(SequenceFrameError):
        trim_overlap([1, 2], 2)
    with pytest.raises(SequenceFrameError):
        trim_overlap([1, 2], -1)


@needs_ffmpeg
def test_the_asm_332_engine_assembles_a_frame_exact_movie_with_lineage(tmp_path: Path) -> None:
    plan = SequencePlan(
        sequence_id="real",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=(_segment(0, frame_count=6), _segment(1, frame_count=6, overlap_frames=2)),
        assembly=SequenceAssembly(clip_name="real_movie", quality="draft"),
    )
    segments = Segments(tmp_path)

    outcome = VideoSequenceExecutor(
        plan=plan, job_id="job-real", run_dir=tmp_path, run_segment=segments
    ).execute(source_image_path=_source(tmp_path))

    movie = Path(outcome.assembled_path)
    assert movie.is_file() and movie.name == "real_movie.mp4"
    from src.video.sequence_frames import decode_clip_to_frames

    decoded = decode_clip_to_frames(movie, tmp_path / "check")
    assert len(decoded) == 6 + 4  # segment 1 lost its two overlap frames
    manifest = json.loads(Path(outcome.assembly_manifest_path).read_text(encoding="utf-8"))
    assert manifest["total_frames"] == 10 and manifest["output_sha256"] == _sha(movie)
    assert [Path(c["path"]).name for c in manifest["spec"]["clips"]][:2] == [
        "seg0_00001_.png",
        "seg0_00002_.png",
    ]
    assert outcome.ledger.assembly["output_sha256"] == _sha(movie)


@needs_ffmpeg
def test_cancelling_the_assembly_raises_and_leaves_no_partial_movie(tmp_path: Path) -> None:
    frames = [_png(tmp_path / f"f{n}.png", n * 5) for n in range(6)]
    token = CancelToken()
    token.cancel()

    with pytest.raises(CancellationError):
        assemble_sequence_frames(
            frames, _plan(2), run_dir=tmp_path / "out", job_id="j", cancel_token=token
        )

    assert not list((tmp_path / "out").glob("*.mp4")) and not list(
        (tmp_path / "out").glob("*.assembling*")
    )
    with pytest.raises(SequenceAssemblyError, match="no frames"):
        assemble_sequence_frames([], _plan(2), run_dir=tmp_path / "out", job_id="j")


# ---------------------------------------------------------------------------------------- opt-in colour matching


def test_colour_matching_is_off_by_default_and_never_alters_originals(tmp_path: Path) -> None:
    captured: list[list[Path]] = []

    def capture(frames, plan_, *, run_dir, job_id, cancel_token=None):
        captured.append([Path(f) for f in frames])
        return _fake_assemble(frames, plan_, run_dir=run_dir, job_id=job_id)

    outcome = _executor(tmp_path, _plan(2), Segments(tmp_path), assemble=capture).execute(
        source_image_path=_source(tmp_path)
    )

    assert _plan(2).color_match.enabled is False
    assert all("color_matched" not in str(p) for p in captured[0])
    assert all(segment.color_matched == () for segment in outcome.ledger.segments)


def test_colour_matching_is_deterministic_assembly_only_and_leaves_anchors_alone(
    tmp_path: Path,
) -> None:
    plan = _plan(2, color_match=SequenceColorMatch(enabled=True))
    captured: list[list[Path]] = []

    def capture(frames, plan_, *, run_dir, job_id, cancel_token=None):
        captured.append([Path(f) for f in frames])
        return _fake_assemble(frames, plan_, run_dir=run_dir, job_id=job_id)

    outcome = _executor(tmp_path, plan, Segments(tmp_path), assemble=capture).execute(
        source_image_path=_source(tmp_path)
    )

    names = [p.parent.name for p in captured[0]]
    assert (
        names[:5] == [tmp_path.name] * 5
    )  # segment 0 is the reference: its originals are assembled untouched
    assert all(name == "seg_01" for name in names[5:])  # later segments are matched copies
    seg1 = outcome.ledger.segments[1]
    assert len(seg1.color_matched) == 5
    for matched, original in zip(seg1.color_matched, seg1.frames, strict=True):
        assert matched.sha256 == _sha(Path(matched.path)) and matched.sha256 != original.sha256
        assert _sha(Path(original.path)) == original.sha256  # the original frame is unchanged
    assert outcome.ledger.segments[1].final_frame.file.sha256 == _sha(
        Path(seg1.frames[-1].path)
    )  # anchor = original
    assert outcome.ledger.assembly["color_match_reference"].endswith("seg0_00001_.png")

    again = tmp_path / "again"
    twin = _executor(again, plan, Segments(again), assemble=capture).execute(
        source_image_path=_source(tmp_path)
    )
    assert [r.sha256 for r in twin.ledger.segments[1].color_matched] == [
        r.sha256 for r in seg1.color_matched
    ]


def test_the_colour_lut_is_integer_exact_and_matches_a_known_histogram() -> None:
    import numpy as np

    source = np.zeros((3, 256), dtype=np.int64)
    reference = np.zeros((3, 256), dtype=np.int64)
    source[:, 10] = 50
    source[:, 20] = 50
    reference[:, 100] = 50
    reference[:, 200] = 50

    luts = color_match_luts(source, reference)

    assert (
        luts[0][10] == 100 and luts[0][20] == 200
    )  # equal cumulative shares map onto the reference's values
    assert luts.shape == (3, 256) and luts.dtype == np.uint8
    with pytest.raises(SequenceFrameError, match="empty"):
        color_match_luts(np.zeros((3, 256), dtype=np.int64), reference)


def test_match_segment_colors_writes_new_files_in_order(tmp_path: Path) -> None:
    frames = [_png(tmp_path / f"s{n}.png", 30 + n) for n in range(3)]
    reference = _png(tmp_path / "ref.png", 200)

    records = match_segment_colors(frames, reference, tmp_path / "matched")

    assert [Path(r.path).name for r in records] == ["m_000000.png", "m_000001.png", "m_000002.png"]
    assert all(Path(r.path).is_file() for r in records)
    assert match_segment_colors([], reference, tmp_path / "none") == []
    shutil.rmtree(tmp_path / "matched")


def test_the_sequence_artifact_stays_readable_by_the_historical_reader(tmp_path: Path) -> None:
    from src.pipeline.video_sequence_executor import sequence_artifact_payload
    from src.video.assembly_models import AssembledSequenceInput

    plan = _plan(2)
    outcome = _executor(tmp_path, plan, Segments(tmp_path)).execute(
        source_image_path=_source(tmp_path)
    )

    source = AssembledSequenceInput.from_sequence_artifact(sequence_artifact_payload(outcome, plan))

    assert source.source_kind == "sequence" and source.source_id == "seq-test"
    assert source.manifest_path == str(outcome.ledger_path)
    assert source.source_paths[0] == outcome.assembled_path and len(source.source_paths) == 3
    assert [segment.segment_index for segment in source.segment_sources] == [0, 1]
