"""PR-VID-SEQ-330-CORE: checkpoint integrity, strict resume refusals, replay comparison and assembly verification.

Fake segment callbacks write small real PNGs; no GPU, runtime or network. Complements the executor suite with the
failure and tamper cases of the durable ledger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.ports.default_runtime_ports import DefaultWorkflowRegistryPort
from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.video_sequence_executor import SegmentRun, VideoSequenceExecutor
from src.video.sequence_admission import freeze_sequence_plan, verify_plan_source
from src.video.sequence_assembly import SequenceAssemblyError, assemble_sequence_frames
from src.video.sequence_frames import SequenceFrameError, collect_segment_artifacts
from src.video.sequence_ledger import (
    LEDGER_FILE_NAME,
    LEDGER_SCHEMA,
    STATE_CANCELLED,
    STATE_FAILED,
    STATE_INTERRUPTED,
    SequenceLedgerError,
    read_ledger,
    sha256_of,
)
from src.video.sequence_plan import (
    ANCHOR_CARRY,
    ANCHOR_PROVIDED,
    ANCHOR_SOURCE,
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SequenceColorMatch,
    SequencePlan,
    SequencePlanError,
)
from src.video.sequence_resume import SequenceResumeError
from src.video.svd_config import SVDConfig
from src.video.svd_sequence_admission import freeze_svd_sequence_plan
from src.video.workflow_registry import build_default_workflow_registry
from tests.video.test_pr_vid_seq_330_executor import (
    Segments,
    _executor,
    _failed_parent,
    _fake_assemble,
    _plan,
    _png,
    _resume_block,
    _segment,
    _sha,
    _source,
)

WORKFLOW = "wan22_ti2v_5b_i2v_v1"


# ---------------------------------------------------------------------------------------- ledger content


def test_the_ledger_records_each_segments_input_anchor_manifest_and_position(
    tmp_path: Path,
) -> None:
    anchor = _png(tmp_path / "authored.png", 77)
    plan = SequencePlan(
        sequence_id="anchors",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=(
            _segment(0),
            _segment(1),
            _segment(
                2,
                anchor_policy=ANCHOR_PROVIDED,
                anchor_path=str(anchor),
                anchor_sha256=_sha(anchor),
            ),
        ),
    )

    class WithManifest(Segments):
        def __call__(self, segment, input_path, hold):
            run = super().__call__(segment, input_path, hold)
            manifest = self.run_dir / "manifests" / f"seg{segment.index}.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"segment": segment.index}), encoding="utf-8")
            return SegmentRun({**run.raw_result, "manifest_path": str(manifest)}, run.output_paths)

    source = _source(tmp_path)
    outcome = _executor(tmp_path, plan, WithManifest(tmp_path)).execute(source_image_path=source)

    ledger = read_ledger(outcome.ledger_path)
    first, carried, authored = ledger.segments
    assert (first.input_anchor.policy, first.input_anchor.basis) == (ANCHOR_SOURCE, "source")
    assert first.input_anchor.file.sha256 == _sha(Path(source))
    assert (carried.input_anchor.policy, carried.input_anchor.basis) == (ANCHOR_CARRY, "native")
    assert carried.input_anchor.from_segment == 0
    assert carried.input_anchor.file.sha256 == first.final_frame.file.sha256
    assert (authored.input_anchor.policy, authored.input_anchor.basis) == (
        ANCHOR_PROVIDED,
        "provided",
    )
    assert authored.input_anchor.file.sha256 == _sha(anchor)
    assert all(
        s.manifest is not None and s.manifest.sha256 == _sha(Path(s.manifest.path))
        for s in ledger.segments
    )
    assert all(  # the facts an assembly needs: the frame size and the rate every segment plays at
        s.final_frame.detail["size"] == [32, 32] and s.processing["fps"] == plan.fps
        for s in ledger.segments
    )
    assert (ledger.total_segments, ledger.completed_prefix, ledger.next_segment) == (3, 3, None)
    assert ledger.policy_version == plan.policy_version and ledger.schema == LEDGER_SCHEMA


def test_a_partial_ledger_says_where_to_resume_and_cannot_lie_about_it(tmp_path: Path) -> None:
    ledger_path, _sha_value = _failed_parent(tmp_path, _plan(4), fail_on=2)
    data = json.loads(ledger_path.read_text(encoding="utf-8"))

    assert (data["completed_prefix"], data["next_segment"], data["state"]) == (2, 2, "failed")
    data["completed_prefix"] = 3  # claims a segment that is not listed
    ledger_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SequenceLedgerError, match="completed prefix does not match"):
        read_ledger(ledger_path)
    data["completed_prefix"] = 2
    data["segments"] = [data["segments"][1]]  # a gap: the listed segment is not segment 0
    ledger_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SequenceLedgerError, match="contiguous prefix"):
        read_ledger(ledger_path)


@pytest.mark.parametrize(
    ("exc", "state"),
    [
        (KeyboardInterrupt(), STATE_INTERRUPTED),
        (SystemExit(1), STATE_INTERRUPTED),
        (CancellationError("stop"), STATE_CANCELLED),
        (ValueError("bad"), STATE_FAILED),
    ],
)
def test_the_terminal_state_distinguishes_interrupted_cancelled_and_failed(
    tmp_path: Path, exc: BaseException, state: str
) -> None:
    with pytest.raises(type(exc)):
        _executor(tmp_path, _plan(2), Segments(tmp_path, fail_on=0, exc=exc)).execute(
            source_image_path=_source(tmp_path)
        )

    assert read_ledger(tmp_path / LEDGER_FILE_NAME).state == state


def test_a_ledger_write_failure_stops_the_sequence_before_the_next_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.pipeline.video_sequence_executor as module

    real = module.write_ledger
    writes: list[int] = []

    def flaky(path: Path, ledger: Any) -> str:
        writes.append(len(ledger.segments))
        if ledger.segments:
            raise OSError("disk full")  # every write that would commit segment 0
        return real(path, ledger)

    monkeypatch.setattr(module, "write_ledger", flaky)
    segments = Segments(tmp_path)

    with pytest.raises(OSError, match="disk full"):
        _executor(tmp_path, _plan(3), segments).execute(source_image_path=_source(tmp_path))

    assert [c[0].index for c in segments.calls] == [0]  # segment 1 never dispatched
    on_disk = read_ledger(tmp_path / LEDGER_FILE_NAME)
    assert on_disk.completed_prefix == 0  # and the file never claimed the uncommitted segment


def test_a_segment_that_finishes_just_as_a_cancel_arrives_is_still_committed(
    tmp_path: Path,
) -> None:
    token = CancelToken()
    segments = Segments(tmp_path)
    original = segments.__call__

    def cancel_during_the_last_instant(segment, input_path, hold):
        run = original(segment, input_path, hold)
        token.cancel()
        return run

    executor = VideoSequenceExecutor(
        plan=_plan(3),
        job_id="job-1",
        run_dir=tmp_path,
        run_segment=cancel_during_the_last_instant,
        cancel_token=token,
        assemble=_fake_assemble,
    )

    with pytest.raises(CancellationError):
        executor.execute(source_image_path=_source(tmp_path))

    ledger = read_ledger(tmp_path / LEDGER_FILE_NAME)
    assert ledger.state == STATE_CANCELLED and [s.index for s in ledger.segments] == [0]
    assert len(segments.calls) == 1  # nothing further dispatched after the cancel


def test_a_failing_segment_leaves_completed_artifacts_and_removes_only_its_own_staging(
    tmp_path: Path,
) -> None:
    class Late(Segments):
        def __call__(self, segment, input_path, hold):
            run = super().__call__(segment, input_path, hold)
            if segment.index == 1:  # produces frames, then is found unusable (a short run)
                raw = dict(run.raw_result)
                raw["frame_paths"] = raw["frame_paths"][:-1]
                raw["frames_out"] = {
                    **raw["frames_out"],
                    "last_frame_path": raw["frame_paths"][-1],
                    "last_frame_sha256": _sha(Path(raw["frame_paths"][-1])),
                }
                return SegmentRun(raw, run.output_paths)
            return run

    with pytest.raises(SequenceFrameError):
        _executor(tmp_path, _plan(3), Late(tmp_path)).execute(source_image_path=_source(tmp_path))

    ledger = read_ledger(tmp_path / LEDGER_FILE_NAME)
    assert [s.index for s in ledger.segments] == [0]
    assert (
        tmp_path / "sequence" / "anchors" / "seg_00_last.png"
    ).is_file()  # the committed one stays
    assert not (tmp_path / "sequence" / "anchors" / "seg_01_last.png").exists()
    assert (
        tmp_path / "seg0_00001_.png"
    ).is_file()  # backend-owned outputs of a finished segment stay


# ---------------------------------------------------------------------------------------- source integrity


def test_the_frozen_source_must_still_be_the_image_that_was_queued(tmp_path: Path) -> None:
    source = Path(_source(tmp_path))
    plan = replace(_plan(2), source={"path": str(source), "sha256": _sha(source)})

    verify_plan_source(plan, source)  # unchanged: fine
    segments = Segments(tmp_path)
    _executor(tmp_path, plan, segments).execute(source_image_path=str(source))
    assert len(segments.calls) == 2

    source.write_bytes(source.read_bytes() + b"x")
    again = Segments(tmp_path / "again")
    with pytest.raises(SequencePlanError, match="source image changed since it was queued"):
        _executor(tmp_path / "again", plan, again).execute(source_image_path=str(source))
    assert again.calls == []
    source.unlink()
    with pytest.raises(SequencePlanError, match="source image is missing"):
        verify_plan_source(plan, source)


def test_a_corrupt_authored_anchor_is_refused_before_its_segment_dispatches(tmp_path: Path) -> None:
    anchor = _png(tmp_path / "authored.png", 33)
    plan = SequencePlan(
        sequence_id="corrupt",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=24,
        segments=(
            _segment(0),
            _segment(1, anchor_policy=ANCHOR_PROVIDED, anchor_path=str(anchor), anchor_sha256=""),
        ),
    )
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"\x00not an image")
    plan = replace(
        plan,
        segments=(
            plan.segments[0],
            replace(plan.segments[1], anchor_path=str(corrupt), anchor_sha256=_sha(corrupt)),
        ),
    )
    segments = Segments(tmp_path)

    with pytest.raises(SequencePlanError, match="not a readable image"):
        _executor(tmp_path, plan, segments).execute(source_image_path=_source(tmp_path))

    assert [c[0].index for c in segments.calls] == [0]  # segment 1 was never handed a non-image


# ---------------------------------------------------------------------------------------- frame integrity


def test_a_frames_out_frame_that_no_longer_matches_its_recorded_hash_never_becomes_an_anchor(
    tmp_path: Path,
) -> None:
    frames = [_png(tmp_path / f"f_{n:05d}_.png", n * 9) for n in (1, 2, 3)]
    digests = [_sha(f) for f in frames]
    raw = {
        "frame_paths": [str(f) for f in frames],
        "frames_out": {
            "last_frame_path": str(frames[-1]),
            "last_frame_sha256": digests[-1],
            "frame_sha256": digests,
        },
    }
    assert collect_segment_artifacts(raw, segment_index=0, expected_frame_count=3, run_dir=tmp_path)

    raw["frames_out"]["frame_sha256"] = [digests[0], "0" * 64, digests[2]]
    with pytest.raises(SequenceFrameError, match="no longer matches the hash the backend recorded"):
        collect_segment_artifacts(raw, segment_index=0, expected_frame_count=3, run_dir=tmp_path)


def test_a_missing_or_corrupt_final_frame_is_refused(tmp_path: Path) -> None:
    frames = [_png(tmp_path / f"f_{n:05d}_.png", n * 9) for n in (1, 2)]
    raw = {
        "frame_paths": [str(f) for f in frames],
        "frames_out": {"last_frame_path": str(frames[-1]), "last_frame_sha256": _sha(frames[-1])},
    }
    frames[-1].write_bytes(b"this is not a png")
    raw["frames_out"]["last_frame_sha256"] = _sha(
        frames[-1]
    )  # the hash agrees; the image is still corrupt
    with pytest.raises(SequenceFrameError, match="not a readable image"):
        collect_segment_artifacts(raw, segment_index=0, expected_frame_count=2, run_dir=tmp_path)

    frames[-1].unlink()
    with pytest.raises(SequenceFrameError, match="missing"):
        collect_segment_artifacts(raw, segment_index=0, expected_frame_count=2, run_dir=tmp_path)


def test_a_jpeg_is_not_a_png_anchor(tmp_path: Path) -> None:
    frames = [_png(tmp_path / f"f_{n:05d}_.png", n * 9) for n in (1, 2)]
    Image.new("RGB", (8, 8), (1, 2, 3)).save(
        frames[-1], format="JPEG"
    )  # right suffix, wrong format
    raw = {
        "frame_paths": [str(f) for f in frames],
        "frames_out": {"last_frame_path": str(frames[-1]), "last_frame_sha256": _sha(frames[-1])},
    }

    with pytest.raises(SequenceFrameError, match="not a PNG still"):
        collect_segment_artifacts(raw, segment_index=0, expected_frame_count=2, run_dir=tmp_path)


def test_native_svd_must_have_generated_exactly_the_admitted_frame_count(tmp_path: Path) -> None:
    native = _png(tmp_path / "native.png", 5)
    frames = [_png(tmp_path / f"e_{n}.png", n) for n in range(3)]
    raw = {
        "frame_paths": [str(f) for f in frames],
        "native_final_frame": {"path": str(native), "sha256": _sha(native), "frame_index": 2},
    }

    assert collect_segment_artifacts(raw, segment_index=0, expected_frame_count=3, run_dir=tmp_path)
    with pytest.raises(
        SequenceFrameError, match="generated 3 frames but the segment was admitted with 5"
    ):
        collect_segment_artifacts(raw, segment_index=0, expected_frame_count=5, run_dir=tmp_path)


# ---------------------------------------------------------------------------------------- strict resume


def _edit_ledger(path: Path, edit: Any) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return sha256_of(path)


def _try_resume(
    tmp_path: Path, plan: SequencePlan, ledger_path: Path, sha: str, **block: Any
) -> Segments:
    child_dir = tmp_path / "child"
    segments = Segments(child_dir)
    resume = {**_resume_block(plan, ledger_path, sha, 2), **block}
    with pytest.raises(SequenceResumeError):
        _executor(child_dir, plan, segments).execute(
            source_image_path=_source(tmp_path), resume=resume
        )
    return segments


def test_a_checkpoint_of_another_job_is_refused(tmp_path: Path) -> None:
    plan = _plan(4)
    ledger_path, sha = _failed_parent(tmp_path, plan, fail_on=2)

    segments = _try_resume(tmp_path, plan, ledger_path, sha, parent_job_id="some-other-job")

    assert segments.calls == []


def test_a_ledger_that_names_files_outside_its_own_run_folder_is_refused(tmp_path: Path) -> None:
    plan = _plan(4)
    ledger_path, _ = _failed_parent(tmp_path, plan, fail_on=2)
    outside = tmp_path / "elsewhere" / "frame.png"
    outside.parent.mkdir()
    outside.write_bytes(Path(read_ledger(ledger_path).segments[0].frames[0].path).read_bytes())

    def point_outside(data: dict[str, Any]) -> None:
        record = data["segments"][0]["frames"][0]
        record.update(path=str(outside), sha256=_sha(outside), bytes=outside.stat().st_size)

    sha = _edit_ledger(ledger_path, point_outside)

    segments = _try_resume(tmp_path, plan, ledger_path, sha)

    assert segments.calls == []  # a hash-consistent ledger still may not reach outside its run


def test_a_final_frame_that_is_not_a_png_is_refused_even_when_its_hash_matches(
    tmp_path: Path,
) -> None:
    plan = _plan(4)
    ledger_path, _ = _failed_parent(tmp_path, plan, fail_on=2)
    final = Path(read_ledger(ledger_path).segments[1].final_frame.file.path)
    Image.new("RGB", (8, 8)).save(final, format="JPEG")

    def rehash(data: dict[str, Any]) -> None:
        record = data["segments"][1]["final_frame"]["file"]
        record.update(sha256=_sha(final), bytes=final.stat().st_size)

    sha = _edit_ledger(ledger_path, rehash)

    segments = _try_resume(tmp_path, plan, ledger_path, sha)

    assert segments.calls == []


def test_a_resume_for_a_different_plan_digest_is_refused(tmp_path: Path) -> None:
    plan = _plan(4)
    ledger_path, sha = _failed_parent(tmp_path, plan, fail_on=2)

    segments = _try_resume(tmp_path, plan, ledger_path, sha, plan_sha256="0" * 64)

    assert segments.calls == []


def test_a_tampered_clip_or_manifest_of_the_prefix_is_refused(tmp_path: Path) -> None:
    plan = _plan(4)
    ledger_path, sha = _failed_parent(tmp_path, plan, fail_on=2)
    Path(read_ledger(ledger_path).segments[0].clip.path).write_bytes(b"swapped clip")

    segments = _try_resume(tmp_path, plan, ledger_path, sha)

    assert segments.calls == []


def test_a_resume_revalidates_at_execution_not_only_at_admission(tmp_path: Path) -> None:
    plan = _plan(4)
    ledger_path, sha = _failed_parent(tmp_path, plan, fail_on=2)
    # Admission (build_resume_njr) saw a good checkpoint; the file changes before the child runs.
    Path(read_ledger(ledger_path).segments[1].frames[2].path).write_bytes(b"changed in between")

    segments = _try_resume(tmp_path, plan, ledger_path, sha)

    assert segments.calls == []


# ---------------------------------------------------------------------------------------- replay comparison


def _replay_block(ledger_path: Path) -> dict[str, str]:
    return {
        "parent_job_id": "job-1",
        "parent_ledger_path": str(ledger_path),
        "parent_ledger_sha256": sha256_of(ledger_path),
    }


def test_a_full_replay_records_which_final_frames_diverged_and_never_fails_on_it(
    tmp_path: Path,
) -> None:
    plan = _plan(3)
    original = _executor(tmp_path / "original", plan, Segments(tmp_path / "original")).execute(
        source_image_path=_source(tmp_path)
    )

    class Drifting(Segments):
        """Segment 1 comes out slightly different on the second run (a GPU is not bit-exact)."""

        def __call__(self, segment, input_path, hold):
            run = super().__call__(segment, input_path, hold)
            if segment.index == 1:
                last = Path(run.raw_result["frame_paths"][-1])
                _png(last, 222)
                raw = dict(run.raw_result)
                raw["frames_out"] = {**raw["frames_out"], "last_frame_sha256": _sha(last)}
                return SegmentRun(raw, run.output_paths)
            return run

    replay_dir = tmp_path / "replay"
    outcome = VideoSequenceExecutor(
        plan=plan,
        job_id="job-2",
        run_dir=replay_dir,
        run_segment=Drifting(replay_dir),
        assemble=_fake_assemble,
        replay_reference=_replay_block(original.ledger_path),
    ).execute(source_image_path=_source(tmp_path))

    replay = outcome.ledger.replay
    assert replay["status"] == "comparing" and replay["compared_segments"] == [0, 1, 2]
    assert replay["diverged_segments"] == [1]
    assert replay["segment_final_frames"]["0"]["identical"] is True
    assert replay["segment_final_frames"]["1"]["identical"] is False
    assert "not guaranteed to be byte-identical" in replay["note"]
    assert [s.origin for s in outcome.ledger.segments] == ["generated"] * 3  # nothing reused


def test_an_unavailable_or_foreign_replay_reference_is_recorded_not_fatal(tmp_path: Path) -> None:
    plan = _plan(2)
    original = _executor(tmp_path / "o", plan, Segments(tmp_path / "o")).execute(
        source_image_path=_source(tmp_path)
    )
    missing = {**_replay_block(original.ledger_path), "parent_ledger_sha256": "0" * 64}

    outcome = VideoSequenceExecutor(
        plan=plan,
        job_id="job-2",
        run_dir=tmp_path / "r1",
        run_segment=Segments(tmp_path / "r1"),
        assemble=_fake_assemble,
        replay_reference=missing,
    ).execute(source_image_path=_source(tmp_path))
    assert outcome.ledger.replay["status"] == "reference_unavailable"

    other_plan = replace(plan, segments=(*plan.segments[:1], replace(plan.segments[1], seed=999)))
    outcome = VideoSequenceExecutor(
        plan=other_plan,
        job_id="job-3",
        run_dir=tmp_path / "r2",
        run_segment=Segments(tmp_path / "r2"),
        assemble=_fake_assemble,
        replay_reference=_replay_block(original.ledger_path),
    ).execute(source_image_path=_source(tmp_path))
    assert outcome.ledger.replay["status"] == "not_comparable"


# ---------------------------------------------------------------------------------------- colour provenance


def test_colour_provenance_names_the_algorithm_reference_and_which_segments_changed(
    tmp_path: Path,
) -> None:
    plan = _plan(3, color_match=SequenceColorMatch(enabled=True))

    outcome = _executor(tmp_path, plan, Segments(tmp_path)).execute(
        source_image_path=_source(tmp_path)
    )

    recorded = [s.color_match for s in outcome.ledger.segments]
    reference = outcome.ledger.segments[0].frames[0].sha256
    assert [r["transformed"] for r in recorded] == [False, True, True]
    assert all(r["algorithm"] == plan.color_match.algorithm for r in recorded)
    assert all(r["reference_sha256"] == reference for r in recorded)  # segment 0's first frame
    # Original frames and their hashes are not rewritten; the derived frames are separate, verified artifacts.
    for segment in outcome.ledger.segments[1:]:
        assert len(segment.color_matched) == len(segment.frames)
        assert {m.path for m in segment.color_matched}.isdisjoint({f.path for f in segment.frames})
    # The final-frame digest in the ledger is the ORIGINAL layer (what the next segment was conditioned on).
    assert (
        outcome.ledger.segments[1].final_frame.file.sha256
        == outcome.ledger.segments[1].frames[-1].sha256
    )


def test_colour_matching_off_records_no_transformation(tmp_path: Path) -> None:
    outcome = _executor(tmp_path, _plan(2), Segments(tmp_path)).execute(
        source_image_path=_source(tmp_path)
    )

    assert all(s.color_match is None and s.color_matched == () for s in outcome.ledger.segments)


# ---------------------------------------------------------------------------------------- assembly verification


def test_the_assembly_refuses_frames_of_mixed_sizes(tmp_path: Path) -> None:
    plan = _plan(2)
    frames = [_png(tmp_path / "a.png", 1, (32, 32)), _png(tmp_path / "b.png", 2, (64, 32))]

    with pytest.raises(SequenceAssemblyError, match="not all one size"):
        assemble_sequence_frames(frames, plan, run_dir=tmp_path / "out", job_id="j")


def test_an_assembly_failure_fails_the_sequence_rather_than_report_a_missing_movie(
    tmp_path: Path,
) -> None:
    def broken(frames, plan_, *, run_dir, job_id, cancel_token=None):
        raise SequenceAssemblyError("FFmpeg exited with 1")

    segments = Segments(tmp_path)
    with pytest.raises(SequenceAssemblyError, match="FFmpeg exited"):
        _executor(tmp_path, _plan(2), segments, assemble=broken).execute(
            source_image_path=_source(tmp_path)
        )

    ledger = read_ledger(tmp_path / LEDGER_FILE_NAME)
    assert ledger.state == STATE_FAILED and ledger.assembly is None
    assert ledger.completed_prefix == 2  # the segments are kept for a resume or a re-assembly


def test_an_assembly_whose_timeline_disagrees_with_the_frames_is_refused_and_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.video.sequence_assembly as module

    frames = [_png(tmp_path / f"f{n}.png", n * 7, (32, 32)) for n in range(4)]
    movie = tmp_path / "out" / "bad.mp4"
    movie.parent.mkdir()
    movie.write_bytes(b"movie")

    def lying_engine(spec, **_kw):
        return SimpleNamespace(
            output_path=movie,
            manifest_path=tmp_path / "m.json",
            output_sha256="0" * 64,
            timeline=SimpleNamespace(total_frames=3, fps=spec.fps),
        )

    monkeypatch.setattr(module, "run_movie_assembly", lying_engine)

    with pytest.raises(SequenceAssemblyError, match="does not match the 4 frames"):
        assemble_sequence_frames(frames, _plan(2), run_dir=tmp_path / "out", job_id="j")
    assert not movie.exists()


# ---------------------------------------------------------------------------------------- admission details


def test_an_experimental_workflow_runs_in_a_sequence_only_with_the_jobs_own_opt_in() -> None:
    registry = DefaultWorkflowRegistryPort(
        build_default_workflow_registry()
    )  # what the controller uses
    intent = {
        "segments": [{"frame_count": 49}, {"frame_count": 49, "workflow_version": "1.1.0"}]
    }  # 1.1.0 is the experimental revision of the same workflow
    common: dict[str, Any] = {
        "stage": STAGE_VIDEO_WORKFLOW,
        "fps": 24,
        "base_prompt": "x",
        "base_workflow": (WORKFLOW, "1.3.0"),
        "registry": registry,
        "target_size": (480, 832),
    }

    with pytest.raises(SequencePlanError, match="experimental and this job has not opted in"):
        freeze_sequence_plan(intent, **common)
    plan = freeze_sequence_plan(intent, experimental_opt_in=True, **common)

    assert plan.experimental_opt_in is True  # recorded in the frozen plan, never a global switch
    assert [s.workflow_version for s in plan.segments] == ["1.3.0", "1.1.0"]


def test_a_native_svd_plan_freezes_its_model_and_its_source_hash(tmp_path: Path) -> None:
    source = _png(tmp_path / "svd_source.png", 4, (1024, 576))
    config = SVDConfig()

    plan = freeze_svd_sequence_plan(
        {"segments": [{"frame_count": 4, "seed": 1}, {"frame_count": 4, "seed": 2}]},
        config=config,
        source_image_path=source,
    )

    assert plan.stage == STAGE_SVD_NATIVE and plan.backend == "svd_native"
    assert plan.model_id == str(config.inference.model_id)
    assert plan.source == {
        "path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    assert plan.to_dict()["plan_digest"] == plan.plan_sha256()


def test_a_relative_run_folder_still_hands_backends_and_records_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first physical run: ComfyUI refused a carried anchor that was passed as a relative path.
    monkeypatch.chdir(tmp_path)
    segments = Segments(Path("relative_run"))

    outcome = _executor(Path("relative_run"), _plan(2), segments).execute(
        source_image_path=_source(tmp_path)
    )

    assert all(Path(call[1]).is_absolute() for call in segments.calls)
    ledger = read_ledger(outcome.ledger_path)
    assert Path(outcome.ledger_path).is_absolute()
    assert all(
        Path(record.path).is_absolute()
        for segment in ledger.segments
        for record in segment.artifact_files()
    )


def test_a_sequence_whose_only_missing_step_is_the_assembly_resumes_without_regenerating(
    tmp_path: Path,
) -> None:
    plan = _plan(2)

    def broken(frames, plan_, *, run_dir, job_id, cancel_token=None):
        raise SequenceAssemblyError("FFmpeg exited with 1")

    parent_dir = tmp_path / "parent"
    with pytest.raises(SequenceAssemblyError):
        _executor(parent_dir, plan, Segments(parent_dir), assemble=broken).execute(
            source_image_path=_source(tmp_path)
        )
    ledger_path = parent_dir / LEDGER_FILE_NAME
    parent = read_ledger(ledger_path)
    assert (parent.completed_prefix, parent.next_segment, parent.assembly) == (2, None, None)

    child_dir = tmp_path / "child"
    segments = Segments(child_dir)
    outcome = _executor(child_dir, plan, segments).execute(
        source_image_path=_source(tmp_path),
        resume=_resume_block(plan, ledger_path, sha256_of(ledger_path), 2),
    )

    assert segments.calls == []  # nothing was regenerated
    assert outcome.assembled_path is not None
    assert [s.origin for s in outcome.ledger.segments] == ["reused", "reused"]
