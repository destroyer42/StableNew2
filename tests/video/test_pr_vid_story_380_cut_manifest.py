"""PR-VID-STORY-380: the cut manifest model and the lead-in verification."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from src.video.sequence_ledger import FileRecord, sha256_of
from src.video.sequence_plan import SequencePlanError, StoryboardLeadIn
from src.video.storyboard_cut import (
    CUT_MANIFEST_SCHEMA,
    CutFrame,
    CutManifest,
    CutManifestError,
    CutRange,
    lead_in_frames,
    read_cut_manifest,
    take_manifest,
    verify_lead_in,
    write_cut_manifest,
)


def _png(folder: Path, name: str, payload: bytes) -> CutFrame:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(payload)
    return CutFrame(path=str(path), sha256=sha256_of(path))


def _manifest(
    tmp_path: Path,
    *,
    frames: int,
    ranges: list[tuple[str, int, int]],
    fps: int = 16,
    size: tuple[int, int] = (32, 32),
    lead_in: int = 0,
) -> CutManifest:
    cut_frames = tuple(
        _png(tmp_path / "frames", f"f{index:03d}.png", f"frame-{index}".encode())
        for index in range(frames)
    )
    cut_ranges = tuple(
        CutRange(owner, start, end, "native", 0 if owner == "root" else 1)
        for owner, start, end in ranges
    )
    return CutManifest(
        fps=fps,
        width=size[0],
        height=size[1],
        frames=cut_frames,
        ranges=cut_ranges,
        lead_in_frames=lead_in,
        job_id="job-1",
    )


def _records(tmp_path: Path, count: int) -> list[FileRecord]:
    folder = tmp_path / "seg"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for index in range(count):
        path = folder / f"s{index:03d}.png"
        path.write_bytes(f"seg-{index}".encode())
        records.append(FileRecord.of(path))
    return records


def _lead_in(
    tmp_path: Path,
    *,
    k: int,
    frames: int = 5,
    fps: int = 16,
    size: tuple[int, int] = (832, 480),
) -> StoryboardLeadIn:
    manifest = _manifest(
        tmp_path, frames=frames, ranges=[("root", 0, frames - 1)], fps=fps, size=size
    )
    written = write_cut_manifest(tmp_path / "cut.json", manifest)
    handoff = manifest.frames[k - 1]
    return StoryboardLeadIn(
        manifest_path=written.path,
        manifest_sha256=written.sha256,
        frame_count=k,
        handoff_path=handoff.path,
        handoff_sha256=handoff.sha256,
    )


def _broken_lead_in(tmp_path: Path, breakage: str) -> tuple[StoryboardLeadIn, tuple[int, int], int]:
    lead_in = _lead_in(tmp_path, k=3)
    target, fps = (832, 480), 16
    if breakage == "manifest_hash":
        lead_in = dataclasses.replace(lead_in, manifest_sha256="0" * 64)
    elif breakage == "k_zero":
        lead_in = dataclasses.replace(lead_in, frame_count=0)
    elif breakage == "k_too_big":
        lead_in = dataclasses.replace(lead_in, frame_count=6)
    elif breakage == "handoff_not_last":
        lead_in = dataclasses.replace(lead_in, frame_count=2)
    elif breakage == "handoff_changed":
        Path(lead_in.handoff_path).write_bytes(b"different")
    elif breakage == "size":
        lead_in = _lead_in(tmp_path / "other", k=3, size=(640, 480))
    elif breakage == "fps":
        lead_in = _lead_in(tmp_path / "other", k=3, fps=24)
    elif breakage == "frame_missing":
        manifest = read_cut_manifest(lead_in.manifest_path)
        Path(manifest.frames[0].path).unlink()
    else:  # pragma: no cover
        raise AssertionError(breakage)
    return lead_in, target, fps


def test_round_trip_and_hash(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, frames=5, ranges=[("root", 0, 4)])
    written = write_cut_manifest(tmp_path / "cut.json", manifest)
    assert read_cut_manifest(written.path, expected_sha256=written.sha256) == manifest
    assert (
        json.loads(Path(written.path).read_text(encoding="utf-8"))["schema"] == CUT_MANIFEST_SCHEMA
    )


def test_ranges_must_cover_every_frame_in_order(tmp_path: Path) -> None:
    gap = _manifest(tmp_path, frames=5, ranges=[("root", 0, 2), ("t1", 4, 4)])
    assert any("cover every frame" in error for error in gap.validate())
    short = _manifest(tmp_path, frames=5, ranges=[("root", 0, 3)])
    assert any("cover every frame" in error for error in short.validate())
    good = _manifest(tmp_path, frames=5, ranges=[("root", 0, 2), ("t1", 3, 4)])
    assert good.validate() == []


def test_validate_reports_bad_fps_size_basis_and_hash(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, frames=2, ranges=[("root", 0, 1)], fps=0, size=(0, 32))
    bad = dataclasses.replace(
        manifest,
        frames=(CutFrame("a.png", "nothex"), manifest.frames[1]),
        ranges=(CutRange("root", 0, 1, "guessed", 0),),
        lead_in_frames=3,
    )
    errors = " | ".join(bad.validate())
    assert "fps must be 1-120" in errors
    assert "size must be positive" in errors
    assert "lead_in_frames" in errors
    assert "cut frame 1 has a malformed SHA-256" in errors
    assert "unknown basis" in errors
    assert any("no frames" in e for e in dataclasses.replace(manifest, frames=()).validate())


def test_owner_of_and_prefix(tmp_path: Path) -> None:
    m = _manifest(tmp_path, frames=6, ranges=[("root", 0, 2), ("t1", 3, 5)])
    assert m.owner_of(4).owner == "t1"
    assert m.prefix(4).ranges == (
        CutRange("root", 0, 2, "native", 0),
        CutRange("t1", 3, 3, "native", 1),
    )
    with pytest.raises(CutManifestError):
        m.owner_of(9)
    with pytest.raises(CutManifestError):
        m.prefix(7)


def test_read_refuses_a_changed_file(tmp_path: Path) -> None:
    written = write_cut_manifest(
        tmp_path / "cut.json", _manifest(tmp_path, frames=2, ranges=[("root", 0, 1)])
    )
    with pytest.raises(CutManifestError, match="changed since it was recorded") as excinfo:
        read_cut_manifest(written.path, expected_sha256="0" * 64)
    assert "cut manifest changed" in str(excinfo.value)
    assert written.path in str(excinfo.value)


def test_error_is_a_sequence_plan_error() -> None:
    assert issubclass(CutManifestError, SequencePlanError)
    assert issubclass(CutManifestError, ValueError)


def test_read_refuses_missing_unknown_key_and_wrong_schema(tmp_path: Path) -> None:
    with pytest.raises(CutManifestError, match="missing"):
        read_cut_manifest(tmp_path / "nope.json")
    written = write_cut_manifest(
        tmp_path / "cut.json", _manifest(tmp_path, frames=2, ranges=[("root", 0, 1)])
    )
    data = json.loads(Path(written.path).read_text(encoding="utf-8"))
    (tmp_path / "extra.json").write_text(json.dumps({**data, "bonus": 1}), encoding="utf-8")
    with pytest.raises(CutManifestError, match="unknown cut manifest field"):
        read_cut_manifest(tmp_path / "extra.json")
    (tmp_path / "schema.json").write_text(
        json.dumps({**data, "schema": "other.v9"}), encoding="utf-8"
    )
    with pytest.raises(CutManifestError, match="schema"):
        read_cut_manifest(tmp_path / "schema.json")
    (tmp_path / "junk.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CutManifestError, match="cannot be read"):
        read_cut_manifest(tmp_path / "junk.json")


def test_write_refuses_an_invalid_manifest(tmp_path: Path) -> None:
    gap = _manifest(tmp_path, frames=5, ranges=[("root", 0, 2), ("t1", 4, 4)])
    with pytest.raises(CutManifestError, match="cover every frame"):
        write_cut_manifest(tmp_path / "cut.json", gap)
    assert not (tmp_path / "cut.json").exists()


@pytest.mark.parametrize(
    "breakage, message",
    [
        ("manifest_hash", "cut manifest changed"),
        ("k_zero", "lead-in length must be 1"),
        ("k_too_big", "lead-in length must be 1"),
        ("handoff_not_last", "handoff frame is not frame K"),
        ("handoff_changed", "handoff frame changed"),
        ("size", "not the target size 832x480"),
        ("fps", "plays at 24 fps, not 16"),
        ("frame_missing", "lead-in frame is missing"),
    ],
)
def test_verify_lead_in_refusals(tmp_path: Path, breakage: str, message: str) -> None:
    lead_in, target, fps = _broken_lead_in(tmp_path, breakage)
    with pytest.raises(CutManifestError, match=message):
        verify_lead_in(lead_in, target_size=target, fps=fps, hash_file=sha256_of)


def test_verify_lead_in_accepts_and_returns_the_whole_manifest(tmp_path: Path) -> None:
    lead_in = _lead_in(tmp_path, k=3)
    manifest = verify_lead_in(lead_in, target_size=(832, 480), fps=16, hash_file=sha256_of)
    assert len(manifest.frames) == 5


def test_verify_lead_in_does_not_hash_every_frame(tmp_path: Path) -> None:
    lead_in = _lead_in(tmp_path, k=3)
    hashed: list[str] = []

    def counting(path: str | Path) -> str:
        hashed.append(str(path))
        return sha256_of(path)

    verify_lead_in(lead_in, target_size=(832, 480), fps=16, hash_file=counting)
    assert hashed == [lead_in.handoff_path]


def test_verify_lead_in_compares_handoff_path_after_normalising(tmp_path: Path) -> None:
    lead_in = _lead_in(tmp_path, k=3)
    spelled = str(
        Path(lead_in.handoff_path).parent
        / ".."
        / Path(lead_in.handoff_path).parent.name
        / Path(lead_in.handoff_path).name
    )
    verify_lead_in(
        dataclasses.replace(lead_in, handoff_path=spelled),
        target_size=(832, 480),
        fps=16,
        hash_file=sha256_of,
    )


def test_lead_in_frames_rehashes_every_frame(tmp_path: Path) -> None:
    lead_in = _lead_in(tmp_path, k=3)
    manifest = read_cut_manifest(lead_in.manifest_path)
    assert lead_in_frames(lead_in, hash_file=sha256_of) == [
        Path(frame.path) for frame in manifest.frames[:3]
    ]
    Path(manifest.frames[1].path).write_bytes(b"overwritten")
    with pytest.raises(CutManifestError, match="lead-in frame 2 changed"):
        lead_in_frames(lead_in, hash_file=sha256_of)


def test_take_manifest_drops_overlap_and_labels_takes(tmp_path: Path) -> None:
    parent = _manifest(tmp_path, frames=4, ranges=[("root", 0, 3)]).prefix(3)
    seg = _records(tmp_path, 5)
    m = take_manifest(
        lead_in=parent, segments=[("t1", seg, 1, "native")], fps=16, width=32, height=32, job_id="j"
    )
    assert len(m.frames) == 3 + 4 and m.lead_in_frames == 3
    assert m.segment_ranges() == (CutRange("t1", 3, 6, "native", 1),)
    assert m.ranges[0] == CutRange("root", 0, 2, "native", 0)
    assert m.frames[3].path == seg[1].path
    assert m.validate() == []
    assert m.job_id == "j"


def test_take_manifest_for_a_root_and_for_two_segments(tmp_path: Path) -> None:
    first, second = _records(tmp_path / "a", 4), _records(tmp_path / "b", 4)
    m = take_manifest(
        lead_in=None,
        segments=[("root", first, 0, "native"), ("root-2", second, 1, "decoded")],
        fps=16,
        width=32,
        height=32,
        job_id="j",
    )
    assert m.lead_in_frames == 0
    assert m.ranges == (
        CutRange("root", 0, 3, "native", 0),
        CutRange("root-2", 4, 6, "decoded", 1),
    )
    assert len(m.segment_ranges()) == 2


def test_take_manifest_refuses_a_mismatched_lead_in_and_an_impossible_overlap(
    tmp_path: Path,
) -> None:
    parent = _manifest(tmp_path, frames=3, ranges=[("root", 0, 2)])
    seg = _records(tmp_path, 2)
    with pytest.raises(CutManifestError, match="not 64x64"):
        take_manifest(
            lead_in=parent,
            segments=[("t1", seg, 1, "native")],
            fps=16,
            width=64,
            height=64,
            job_id="j",
        )
    with pytest.raises(CutManifestError, match="cannot drop an overlap"):
        take_manifest(
            lead_in=parent,
            segments=[("t1", seg, 2, "native")],
            fps=16,
            width=32,
            height=32,
            job_id="j",
        )
