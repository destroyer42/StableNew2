"""PR-VID-STORY-380: the sequence executor running a storyboard take (policy v2).

A take with a lead-in checks its parent cut before anything is dispatched. It writes its own cut manifest after every
committed segment, and at assembly it puts the lead-in first, so the handoff frame appears once in the stitched movie.
The fake segment callbacks write small real PNGs, and the parent cut is a real manifest over real PNGs. No GPU, runtime
or network is used.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.controller.runtime_state import CancellationError
from src.pipeline.video_sequence_executor import (
    CUT_MANIFEST_FILE_NAME,
    SegmentRun,
    SequenceOutcome,
    sequence_artifact_payload,
)
from src.video.sequence_ledger import (
    LEDGER_FILE_NAME,
    STATE_CANCELLED,
    STATE_FAILED,
    SequenceLedger,
    read_ledger,
    sha256_of,
)
from src.video.sequence_plan import (
    ROOT_PARENT,
    SEQUENCE_POLICY_VERSION_V2,
    STAGE_VIDEO_WORKFLOW,
    SegmentSpec,
    SequencePlan,
    SequencePlanError,
    StoryboardLeadIn,
    StoryboardPlanLink,
)
from src.video.storyboard_cut import (
    BASIS_DECODED,
    BASIS_NATIVE,
    CutFrame,
    CutManifest,
    CutManifestError,
    CutRange,
    read_cut_manifest,
    write_cut_manifest,
)
from tests.video.test_pr_vid_seq_330_executor import (
    Segments,
    _decoder,
    _executor,
    _fake_assemble,
    _plan,
    _png,
    _resume_block,
    _segment,
    _source,
)

SIZE = (32, 32)  # what ``Segments`` writes
FPS = 24
PARENT_FRAMES = 8


@dataclass(frozen=True)
class LeadIn:
    link: StoryboardLeadIn
    #: The K lead-in frames of the parent cut, in order (the last one is the handoff frame).
    frame_paths: list[Path]


def _parent_cut(tmp_path: Path, *, k: int) -> LeadIn:
    """An 8-frame parent cut (decoded basis) at 32x32 and 24 fps; the lead-in is its first ``k`` frames."""

    folder = tmp_path / "parent_cut"
    paths = [
        _png(folder / f"frame_{index:04d}.png", 200 + index).resolve()
        for index in range(PARENT_FRAMES)
    ]
    manifest = CutManifest(
        fps=FPS,
        width=SIZE[0],
        height=SIZE[1],
        frames=tuple(CutFrame(path=str(path), sha256=sha256_of(path)) for path in paths),
        ranges=(CutRange(ROOT_PARENT, 0, PARENT_FRAMES - 1, BASIS_DECODED, 0),),
        lead_in_frames=0,
        job_id=None,
    )
    written = write_cut_manifest(folder / "cut.json", manifest)
    handoff = paths[k - 1]
    link = StoryboardLeadIn(
        manifest_path=written.path,
        manifest_sha256=written.sha256,
        frame_count=k,
        handoff_path=str(handoff),
        handoff_sha256=sha256_of(handoff),
    )
    return LeadIn(link=link, frame_paths=paths[:k])


def _take_ids(segments: int) -> tuple[str, ...]:
    return tuple(f"t{position + 1}" for position in range(segments))


def _v2_plan_with_lead_in(tmp_path: Path, *, k: int, segments: int) -> tuple[SequencePlan, LeadIn]:
    lead_in = _parent_cut(tmp_path, k=k)
    plan = SequencePlan(
        sequence_id="take-test",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=FPS,
        segments=tuple(_segment(position, overlap_frames=1) for position in range(segments)),
        source={"path": lead_in.link.handoff_path, "sha256": lead_in.link.handoff_sha256},
        target_width=SIZE[0],
        target_height=SIZE[1],
        policy_version=SEQUENCE_POLICY_VERSION_V2,
        storyboard=StoryboardPlanLink(
            storyboard_id="sb-1",
            parent_id=ROOT_PARENT,
            take_ids=_take_ids(segments),
            handoff_index=k - 1,
            lead_in=lead_in.link,
        ),
    )
    assert plan.validate() == []
    return plan, lead_in


def _v2_plan_without_lead_in(tmp_path: Path, *, segments: int) -> SequencePlan:
    """A take from a still root: v2, no lead-in, no frozen target size, its source an ordinary image."""

    source = Path(_source(tmp_path))
    plan = SequencePlan(
        sequence_id="still-take",
        stage=STAGE_VIDEO_WORKFLOW,
        fps=FPS,
        segments=tuple(
            _segment(position, overlap_frames=0 if position == 0 else 1)
            for position in range(segments)
        ),
        source={"path": str(source), "sha256": sha256_of(source)},
        policy_version=SEQUENCE_POLICY_VERSION_V2,
        storyboard=StoryboardPlanLink(
            storyboard_id="sb-1",
            parent_id=ROOT_PARENT,
            take_ids=_take_ids(segments),
            handoff_index=None,
        ),
    )
    assert plan.validate() == []
    return plan


class Recording(Segments):
    """``Segments`` that also logs each dispatch to disk and what the take's cut manifest held at that moment."""

    def __init__(
        self,
        run_dir: Path,
        *,
        last_index: int,
        before_assembly: Callable[[], None] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(run_dir, **kw)
        self.last_index = last_index
        self.before_assembly = before_assembly
        self.owners_at_dispatch: list[list[str] | None] = []
        self.ledger_names_the_manifest: list[bool] = []

    def __call__(self, segment: SegmentSpec, input_path: str, hold: bool) -> SegmentRun:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "dispatch.log").open("a", encoding="utf-8") as log:
            log.write(f"{segment.index}\n")
        manifest_path = self.run_dir / CUT_MANIFEST_FILE_NAME
        if manifest_path.is_file():
            manifest = read_cut_manifest(manifest_path)
            self.owners_at_dispatch.append([item.owner for item in manifest.segment_ranges()])
            recorded = read_ledger(self.run_dir / LEDGER_FILE_NAME).cut_manifest
            self.ledger_names_the_manifest.append(
                recorded is not None and recorded["sha256"] == sha256_of(manifest_path)
            )
        else:
            self.owners_at_dispatch.append(None)
        run = super().__call__(segment, input_path, hold)
        if segment.index == self.last_index and self.before_assembly is not None:
            self.before_assembly()
        return run


@dataclass
class Calls:
    segments: Recording
    assembled_frames: list[Path] | None = None
    raised_message: str | None = None


def _calls(
    base: Path,
    plan: SequencePlan,
    *,
    fail_on: int | None = None,
    before_assembly: Callable[[], None] | None = None,
    mode: str = "frames_out",
) -> Calls:
    return Calls(
        segments=Recording(
            base / "run",
            last_index=len(plan.segments) - 1,
            before_assembly=before_assembly,
            fail_on=fail_on,
            mode=mode,
        )
    )


def _execute(
    base: Path,
    plan: SequencePlan,
    calls: Calls,
    *,
    cancel_in_assembly: bool = False,
    resume: dict[str, Any] | None = None,
    **kw: Any,
) -> SequenceOutcome:
    def assemble(
        frames: Any, plan_: SequencePlan, *, run_dir: Path, job_id: str, cancel_token: Any = None
    ) -> Any:
        if cancel_in_assembly:
            raise CancellationError("the assembly was cancelled")
        calls.assembled_frames = [Path(frame) for frame in frames]
        return _fake_assemble(frames, plan_, run_dir=run_dir, job_id=job_id)

    assert plan.source is not None
    return _executor(base / "run", plan, calls.segments, assemble=assemble, **kw).execute(
        source_image_path=str(plan.source["path"]), resume=resume
    )


def _run(
    base: Path,
    plan: SequencePlan,
    *,
    fail_on: int | None = None,
    cancel_in_assembly: bool = False,
    resume: dict[str, Any] | None = None,
    mode: str = "frames_out",
    **kw: Any,
) -> tuple[Calls, SequenceOutcome]:
    calls = _calls(base, plan, fail_on=fail_on, mode=mode)
    outcome = _execute(
        base, plan, calls, cancel_in_assembly=cancel_in_assembly, resume=resume, **kw
    )
    return calls, outcome


def _run_with_hook(base: Path, plan: SequencePlan, *, before_assembly: Callable[[], None]) -> Calls:
    calls = _calls(base, plan, before_assembly=before_assembly)
    try:
        _execute(base, plan, calls)
    except SequencePlanError as exc:
        calls.raised_message = str(exc)
    return calls


def _ledger(base: Path) -> SequenceLedger:
    return read_ledger(base / "run" / LEDGER_FILE_NAME)


def _segments_dispatched(base: Path) -> int:
    log = base / "run" / "dispatch.log"
    return len(log.read_text(encoding="utf-8").split()) if log.is_file() else 0


def _touch_manifest(lead_in: LeadIn) -> None:
    """Still a valid manifest, but no longer the bytes that were pinned."""

    path = Path(lead_in.link.manifest_path)
    path.write_bytes(path.read_bytes() + b"\n")


def _overwrite_png(path: Path) -> None:
    """Same size, different pixels: only the hash tells it apart."""

    _png(path, 13)


def _failed_parent_run(tmp_path: Path, plan: SequencePlan, *, fail_on: int) -> tuple[Path, str]:
    parent = tmp_path / "parent"
    with pytest.raises(RuntimeError, match="segment failed"):
        _run(parent, plan, fail_on=fail_on)
    ledger_path = parent / "run" / LEDGER_FILE_NAME
    return ledger_path, sha256_of(ledger_path)


def _run_v1(tmp_path: Path) -> tuple[SequenceOutcome, SequencePlan]:
    plan = _plan(2)
    run_dir = tmp_path / "run"
    outcome = _executor(run_dir, plan, Segments(run_dir)).execute(
        source_image_path=_source(tmp_path)
    )
    return outcome, plan


# ---------------------------------------------------------------------------------------- lead-in at assembly


def test_lead_in_is_prepended_and_the_handoff_appears_once(tmp_path: Path) -> None:
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    calls, outcome = _run(tmp_path, plan)
    frames = calls.assembled_frames
    assert frames is not None
    assert frames[:5] == lead_in.frame_paths and len(frames) == 5 + (
        plan.segments[0].frame_count - 1
    )
    assert frames.count(lead_in.frame_paths[4]) == 1
    # Segment 0's first generated frame re-renders the handoff frame and is the one dropped.
    assert frames[5:] == [Path(record.path) for record in outcome.ledger.segments[0].frames[1:]]
    assert outcome.ledger.assembly is not None
    assert outcome.ledger.assembly["segments"][0] == {"segment": "lead_in", "frames_used": 5}
    assert outcome.ledger.assembly["segments"][1]["frames_dropped"] == 1


def test_a_changed_lead_in_frame_stops_before_encoding(tmp_path: Path) -> None:
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    calls = _run_with_hook(
        tmp_path, plan, before_assembly=lambda: _overwrite_png(lead_in.frame_paths[2])
    )
    assert calls.raised_message is not None
    assert (
        calls.raised_message.startswith("lead-in frame 3 changed")
        and calls.assembled_frames is None
    )
    assert _ledger(tmp_path).state == STATE_FAILED


# ---------------------------------------------------------------------------------------- the take's cut manifest


def test_cut_manifest_is_written_after_every_committed_segment(tmp_path: Path) -> None:
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=3)
    calls = _calls(tmp_path, plan, fail_on=2)
    with pytest.raises(RuntimeError):
        _execute(tmp_path, plan, calls)
    manifest = read_cut_manifest(tmp_path / "run" / CUT_MANIFEST_FILE_NAME)
    assert [r.owner for r in manifest.segment_ranges()] == ["t1", "t2"]
    assert _ledger(tmp_path).cut_manifest["sha256"] == sha256_of(  # type: ignore[index]
        tmp_path / "run" / CUT_MANIFEST_FILE_NAME
    )
    # Segment n is dispatched only after the manifest names segments 0..n-1 and the persisted ledger names it.
    assert calls.segments.owners_at_dispatch == [None, ["t1"], ["t1", "t2"]]
    assert calls.segments.ledger_names_the_manifest == [True, True]
    # The lead-in (the parent's ranges cut at K), then each segment's frames after its one-frame overlap.
    assert manifest.lead_in_frames == 5 and len(manifest.frames) == 5 + 4 + 4
    assert [frame.path for frame in manifest.frames[:5]] == [str(p) for p in lead_in.frame_paths]
    assert [(r.owner, r.start, r.end, r.basis, r.trimmed) for r in manifest.ranges] == [
        (ROOT_PARENT, 0, 4, BASIS_DECODED, 0),
        ("t1", 5, 8, BASIS_NATIVE, 1),
        ("t2", 9, 12, BASIS_NATIVE, 1),
    ]
    assert (manifest.fps, manifest.width, manifest.height, manifest.job_id) == (
        FPS,
        *SIZE,
        "job-1",
    )


def test_cancel_during_assembly_leaves_a_complete_cut_manifest(tmp_path: Path) -> None:
    plan, _ = _v2_plan_with_lead_in(tmp_path, k=5, segments=2)
    with pytest.raises(CancellationError):
        _run(tmp_path, plan, cancel_in_assembly=True)
    manifest = read_cut_manifest(tmp_path / "run" / CUT_MANIFEST_FILE_NAME)
    assert [r.owner for r in manifest.segment_ranges()] == ["t1", "t2"]
    ledger = _ledger(tmp_path)
    assert ledger.state == STATE_CANCELLED and ledger.assembly is None
    assert ledger.cut_manifest == {
        "path": str((tmp_path / "run" / CUT_MANIFEST_FILE_NAME).resolve()),
        "sha256": sha256_of(tmp_path / "run" / CUT_MANIFEST_FILE_NAME),
    }


def test_decoded_segment_frames_are_recorded_with_the_decoded_basis(tmp_path: Path) -> None:
    plan, _ = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    _run(tmp_path, plan, mode="decoded", decode_clip=_decoder(tmp_path))
    manifest = read_cut_manifest(tmp_path / "run" / CUT_MANIFEST_FILE_NAME)
    assert [(r.owner, r.basis) for r in manifest.segment_ranges()] == [("t1", BASIS_DECODED)]


def test_a_take_without_a_lead_in_still_writes_its_cut_manifest(tmp_path: Path) -> None:
    plan = _v2_plan_without_lead_in(tmp_path, segments=2)
    calls, outcome = _run(tmp_path, plan)
    manifest = read_cut_manifest(tmp_path / "run" / CUT_MANIFEST_FILE_NAME)
    assert manifest.lead_in_frames == 0
    assert [(r.owner, r.start, r.end, r.trimmed) for r in manifest.ranges] == [
        ("t1", 0, 4, 0),
        ("t2", 5, 8, 1),
    ]
    # No frozen target size: the cut takes the first committed frame's pixel size.
    assert (manifest.width, manifest.height) == SIZE
    # Nothing is put before segment 0 when there is no lead-in.
    assert calls.assembled_frames is not None and len(calls.assembled_frames) == 5 + 4
    assert [item["segment"] for item in outcome.ledger.assembly["segments"]] == [0, 1]  # type: ignore[index]


# ---------------------------------------------------------------------------------------- verification at the start


def test_a_changed_parent_manifest_stops_before_dispatch(tmp_path: Path) -> None:
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    _touch_manifest(lead_in)
    with pytest.raises(SequencePlanError, match="cut manifest changed"):
        _run(tmp_path, plan)
    assert _segments_dispatched(tmp_path) == 0
    assert not (tmp_path / "run" / CUT_MANIFEST_FILE_NAME).exists()


def test_a_replay_refuses_a_changed_parent_manifest_before_dispatch(tmp_path: Path) -> None:
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    _, original = _run(tmp_path / "original", plan)
    _touch_manifest(lead_in)
    reference = {
        "parent_job_id": "job-1",
        "parent_ledger_path": str(original.ledger_path),
        "parent_ledger_sha256": original.ledger_sha256,
    }
    with pytest.raises(CutManifestError, match="cut manifest changed"):
        _run(tmp_path / "replay", plan, replay_reference=reference)
    assert _segments_dispatched(tmp_path / "replay") == 0


# ---------------------------------------------------------------------------------------- resume


def test_resume_reverifies_the_lead_in_and_rewrites_the_manifest_for_the_prefix(
    tmp_path: Path,
) -> None:
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=3)
    ledger_path, sha = _failed_parent_run(tmp_path, plan, fail_on=2)
    calls, outcome = _run(
        tmp_path / "child", plan, resume=_resume_block(plan, ledger_path, sha, start=2)
    )
    manifest = read_cut_manifest(tmp_path / "child" / "run" / CUT_MANIFEST_FILE_NAME)
    assert [r.owner for r in manifest.segment_ranges()] == ["t1", "t2", "t3"]
    # Before segment 2 ran, the child's own manifest already held the verified prefix.
    assert calls.segments.owners_at_dispatch == [["t1", "t2"]]
    assert calls.segments.ledger_names_the_manifest == [True]
    # The lead-in is referenced, never copied; the prefix's frames are the child's verified copies.
    assert [frame.path for frame in manifest.frames[:5]] == [str(p) for p in lead_in.frame_paths]
    child_run = (tmp_path / "child" / "run").resolve()
    assert all(Path(frame.path).is_relative_to(child_run) for frame in manifest.frames[5:])
    assert outcome.ledger.cut_manifest is not None
    assert outcome.ledger.cut_manifest["path"] == str(child_run / CUT_MANIFEST_FILE_NAME)


def test_resume_refuses_a_changed_handoff_frame_before_dispatch(tmp_path: Path) -> None:
    plan, lead_in = _v2_plan_with_lead_in(tmp_path, k=5, segments=3)
    ledger_path, sha = _failed_parent_run(tmp_path, plan, fail_on=2)
    _overwrite_png(lead_in.frame_paths[-1])
    with pytest.raises(SequencePlanError, match="handoff frame changed"):
        _run(tmp_path / "child", plan, resume=_resume_block(plan, ledger_path, sha, start=2))
    assert _segments_dispatched(tmp_path / "child") == 0
    assert not (tmp_path / "child" / "run" / CUT_MANIFEST_FILE_NAME).exists()


# ---------------------------------------------------------------------------------------- ledger and artifact shape


def test_v2_ledgers_and_artifacts_record_the_cut_manifest(tmp_path: Path) -> None:
    plan, _ = _v2_plan_with_lead_in(tmp_path, k=5, segments=1)
    _, outcome = _run(tmp_path, plan)
    expected = {
        "path": str((tmp_path / "run" / CUT_MANIFEST_FILE_NAME).resolve()),
        "sha256": sha256_of(tmp_path / "run" / CUT_MANIFEST_FILE_NAME),
    }
    assert read_ledger(outcome.ledger_path, expected_sha256=outcome.ledger_sha256).cut_manifest == (
        expected
    )
    assert sequence_artifact_payload(outcome, plan)["cut_manifest"] == expected


def test_v1_ledgers_and_artifacts_keep_their_shape(tmp_path: Path) -> None:
    outcome, plan = _run_v1(tmp_path)
    assert "cut_manifest" not in outcome.ledger.to_dict()
    assert "cut_manifest" not in sequence_artifact_payload(outcome, plan)
    assert set(outcome.ledger.to_dict()) == {
        "schema",
        "policy_version",
        "sequence_id",
        "job_id",
        "plan_sha256",
        "state",
        "error",
        "total_segments",
        "completed_prefix",
        "next_segment",
        "segments",
        "parent",
        "assembly",
        "runtime_release",
        "replay",
    }
    assert set(sequence_artifact_payload(outcome, plan)) == {
        "sequence_id",
        "job_id",
        "plan_sha256",
        "total_segments",
        "completed_segments",
        "is_complete",
        "sequence_manifest_path",
        "ledger_path",
        "ledger_sha256",
        "ledger_state",
        "segment_provenance",
        "all_output_paths",
        "assembled_video",
        "runtime_release",
        "replay",
    }
    assert not (tmp_path / "run" / CUT_MANIFEST_FILE_NAME).exists()
    assert read_ledger(outcome.ledger_path).cut_manifest is None
