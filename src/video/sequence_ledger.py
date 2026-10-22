"""The durable, per-segment ledger of a sequence job (PR-VID-SEQ-330-CORE).

``sequence_state.json`` sits in the run directory and is rewritten atomically after every completed segment, before
the next one dispatches. A loss, a cancel or a crash during segment *n* therefore leaves segments ``0..n-1`` recorded
with their files and SHA-256s, and nothing about segment *n* that could be mistaken for finished work.

The ledger records, per completed segment: its frozen seed and counts, the image it was conditioned on, the artifacts
it produced (hashed, including the backend's own manifest), the exact final frame and how that frame was obtained
(``native`` or ``decoded``), how the clip was processed, and whether the segment was generated here or reused from a
verified parent checkpoint. It is evidence and a resume source only: SQLite keeps every job lifecycle fact, and a
resume is a new job that re-verifies every hash here before it dispatches anything.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from src.utils.atomic_io import atomic_write_json

LEDGER_SCHEMA: Final = "stablenew.video_sequence_ledger.v1"
LEDGER_FILE_NAME: Final = "sequence_state.json"

STATE_RUNNING: Final = "running"
STATE_COMPLETED: Final = "completed"
STATE_FAILED: Final = "failed"
STATE_CANCELLED: Final = "cancelled"
#: The process was interrupted (KeyboardInterrupt, SystemExit) rather than the job failing or being cancelled.
STATE_INTERRUPTED: Final = "interrupted"
LEDGER_STATES: Final = (
    STATE_RUNNING,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_CANCELLED,
    STATE_INTERRUPTED,
)

#: The final frame is a frame the backend produced before any encode or smoothing.
BASIS_NATIVE: Final = "native"
#: The final frame was decoded back out of an encoded clip (the workflow offers no frames): named, never silent.
BASIS_DECODED: Final = "decoded"
FRAME_BASES: Final = (BASIS_NATIVE, BASIS_DECODED)
#: What a segment was conditioned on: the job's own source, an authored image, or a previous segment's final frame.
ANCHOR_BASES: Final = ("source", "provided", BASIS_NATIVE, BASIS_DECODED)

ORIGIN_GENERATED: Final = "generated"
ORIGIN_REUSED: Final = "reused"

FileHasher = Callable[[str | Path], str]


class SequenceLedgerError(ValueError):
    """The ledger is missing, malformed or does not describe what it claims."""


def sha256_of(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    sha256: str
    bytes: int

    @classmethod
    def of(cls, path: str | Path, *, hash_file: FileHasher = sha256_of) -> FileRecord:
        target = Path(path)
        return cls(path=str(target), sha256=hash_file(target), bytes=target.stat().st_size)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FileRecord:
        try:
            return cls(path=str(data["path"]), sha256=str(data["sha256"]), bytes=int(data["bytes"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise SequenceLedgerError(f"a ledger file record is malformed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FinalFrame:
    file: FileRecord
    basis: str
    #: How the basis was reached and validated (for ``decoded``: the decoded count, expected count, clip identity).
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file.to_dict(), "basis": self.basis, "detail": dict(self.detail)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FinalFrame:
        basis = str(data.get("basis") or "")
        if basis not in FRAME_BASES:
            raise SequenceLedgerError(f"a ledger final frame has an unknown basis {basis!r}")
        return cls(
            file=FileRecord.from_dict(data.get("file") or {}),
            basis=basis,
            detail=dict(data.get("detail") or {}),
        )


@dataclass(frozen=True, slots=True)
class InputAnchor:
    """The image a segment was conditioned on, exactly as it was handed to the backend."""

    policy: str
    basis: str
    file: FileRecord
    #: For a carried anchor, the segment whose final frame it is.
    from_segment: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "basis": self.basis,
            "file": self.file.to_dict(),
            "from_segment": self.from_segment,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InputAnchor:
        basis = str(data.get("basis") or "")
        if basis not in ANCHOR_BASES:
            raise SequenceLedgerError(f"a ledger input anchor has an unknown basis {basis!r}")
        origin = data.get("from_segment")
        return cls(
            policy=str(data.get("policy") or ""),
            basis=basis,
            file=FileRecord.from_dict(data.get("file") or {}),
            from_segment=None if origin is None else int(origin),
        )


@dataclass(frozen=True, slots=True)
class LedgerSegment:
    index: int
    seed: int
    expected_frame_count: int
    frame_count: int
    final_frame: FinalFrame
    frames: tuple[FileRecord, ...]
    workflow_id: str | None = None
    workflow_version: str | None = None
    clip: FileRecord | None = None
    #: The backend's own manifest for this segment (``None`` when the backend wrote none).
    manifest: FileRecord | None = None
    input_anchor: InputAnchor | None = None
    #: Leading frames the assembly drops from this segment.
    overlap_frames: int = 0
    #: Frames the assembly actually used for this segment when colour matching was on (originals stay in ``frames``).
    color_matched: tuple[FileRecord, ...] = ()
    #: Algorithm, reference frame hash and whether this segment's frames were transformed (``None`` until assembly).
    color_match: Mapping[str, Any] | None = None
    processing: Mapping[str, Any] = field(default_factory=dict)
    origin: str = ORIGIN_GENERATED

    def artifact_files(self) -> list[FileRecord]:
        """Every file this segment owns, for verification and for copying into a resumed run."""

        files = [self.final_frame.file, *self.frames, *self.color_matched]
        if self.clip is not None:
            files.append(self.clip)
        if self.manifest is not None:
            files.append(self.manifest)
        return files

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "origin": self.origin,
            "seed": self.seed,
            "expected_frame_count": self.expected_frame_count,
            "frame_count": self.frame_count,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "input_anchor": None if self.input_anchor is None else self.input_anchor.to_dict(),
            "clip": None if self.clip is None else self.clip.to_dict(),
            "manifest": None if self.manifest is None else self.manifest.to_dict(),
            "final_frame": self.final_frame.to_dict(),
            "overlap_frames": self.overlap_frames,
            "frames": [item.to_dict() for item in self.frames],
            "color_matched": [item.to_dict() for item in self.color_matched],
            "color_match": None if self.color_match is None else dict(self.color_match),
            "processing": dict(self.processing),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LedgerSegment:
        try:
            clip = data.get("clip")
            manifest = data.get("manifest")
            anchor = data.get("input_anchor")
            origin = str(data.get("origin") or ORIGIN_GENERATED)
            if origin not in (ORIGIN_GENERATED, ORIGIN_REUSED):
                raise SequenceLedgerError(f"a ledger segment has an unknown origin {origin!r}")
            return cls(
                index=int(data["index"]),
                seed=int(data["seed"]),
                expected_frame_count=int(data["expected_frame_count"]),
                frame_count=int(data["frame_count"]),
                workflow_id=data.get("workflow_id"),
                workflow_version=data.get("workflow_version"),
                clip=None if not clip else FileRecord.from_dict(clip),
                manifest=None if not manifest else FileRecord.from_dict(manifest),
                input_anchor=None if not anchor else InputAnchor.from_dict(anchor),
                final_frame=FinalFrame.from_dict(data.get("final_frame") or {}),
                overlap_frames=int(data.get("overlap_frames") or 0),
                frames=tuple(FileRecord.from_dict(item) for item in data.get("frames") or ()),
                color_matched=tuple(
                    FileRecord.from_dict(item) for item in data.get("color_matched") or ()
                ),
                color_match=None if not data.get("color_match") else dict(data["color_match"]),
                processing=dict(data.get("processing") or {}),
                origin=origin,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, SequenceLedgerError):
                raise
            raise SequenceLedgerError(f"a ledger segment is malformed: {exc}") from exc


@dataclass(slots=True)
class SequenceLedger:
    sequence_id: str
    job_id: str
    plan_sha256: str
    #: How many segments the plan has, so the ledger alone says what is left (``next_segment``).
    total_segments: int
    policy_version: str = ""
    state: str = STATE_RUNNING
    error: str = ""
    segments: list[LedgerSegment] = field(default_factory=list)
    #: Set on a resumed run: the parent job and the parent ledger's hash the prefix was verified against.
    parent: Mapping[str, Any] | None = None
    assembly: Mapping[str, Any] | None = None
    #: The one sequence-end release attempt of a StableNew-owned runtime (what it did, never an adopted process).
    runtime_release: Mapping[str, Any] | None = None
    #: Set on a full replay: how each recomputed final frame compares with the original run's (divergence is recorded,
    #: never a failure: a GPU re-run is not guaranteed to be byte-identical).
    replay: Mapping[str, Any] | None = None
    schema: str = LEDGER_SCHEMA

    @property
    def completed_prefix(self) -> int:
        """How many leading segments are complete (the ledger only ever holds a contiguous prefix)."""

        return len(self.segments)

    @property
    def next_segment(self) -> int | None:
        """The first segment that has not completed, or ``None`` when every segment has."""

        return None if self.completed_prefix >= self.total_segments else self.completed_prefix

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "policy_version": self.policy_version,
            "sequence_id": self.sequence_id,
            "job_id": self.job_id,
            "plan_sha256": self.plan_sha256,
            "state": self.state,
            "error": self.error,
            "total_segments": self.total_segments,
            "completed_prefix": self.completed_prefix,
            "next_segment": self.next_segment,
            "segments": [segment.to_dict() for segment in self.segments],
            "parent": None if self.parent is None else dict(self.parent),
            "assembly": None if self.assembly is None else dict(self.assembly),
            "runtime_release": None if self.runtime_release is None else dict(self.runtime_release),
            "replay": None if self.replay is None else dict(self.replay),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SequenceLedger:
        if not isinstance(data, Mapping) or data.get("schema") != LEDGER_SCHEMA:
            raise SequenceLedgerError("this is not a StableNew sequence ledger")
        state = str(data.get("state") or "")
        if state not in LEDGER_STATES:
            raise SequenceLedgerError(f"the ledger has an unknown state {state!r}")
        try:
            ledger = cls(
                sequence_id=str(data["sequence_id"]),
                job_id=str(data["job_id"]),
                plan_sha256=str(data["plan_sha256"]),
                total_segments=int(data["total_segments"]),
                policy_version=str(data.get("policy_version") or ""),
                state=state,
                error=str(data.get("error") or ""),
                segments=[LedgerSegment.from_dict(item) for item in data.get("segments") or ()],
                parent=dict(data["parent"]) if data.get("parent") else None,
                assembly=dict(data["assembly"]) if data.get("assembly") else None,
                runtime_release=dict(data["runtime_release"])
                if data.get("runtime_release")
                else None,
                replay=dict(data["replay"]) if data.get("replay") else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, SequenceLedgerError):
                raise
            raise SequenceLedgerError(f"the ledger is malformed: {exc}") from exc
        for position, segment in enumerate(ledger.segments):
            if segment.index != position:
                raise SequenceLedgerError(
                    f"the ledger's segments are not a contiguous prefix (entry {position} is segment {segment.index})"
                )
        if ledger.completed_prefix > ledger.total_segments:
            raise SequenceLedgerError("the ledger holds more segments than its plan has")
        if (data.get("completed_prefix"), data.get("next_segment")) != (
            ledger.completed_prefix,
            ledger.next_segment,
        ):
            raise SequenceLedgerError(
                "the ledger's completed prefix does not match the segments it lists"
            )
        return ledger


def write_ledger(path: Path, ledger: SequenceLedger) -> str:
    """Write atomically and return the SHA-256 of the file as written (what a resume pins)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, ledger.to_dict(), indent=2)
    return sha256_of(path)


def read_ledger(path: Path, *, expected_sha256: str | None = None) -> SequenceLedger:
    """Load a ledger; with ``expected_sha256`` the file must be byte-identical to what was pinned."""

    if not path.is_file():
        raise SequenceLedgerError(f"the sequence ledger is missing: {path}")
    if expected_sha256 is not None and sha256_of(path) != expected_sha256:
        raise SequenceLedgerError(f"the sequence ledger changed since it was recorded: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SequenceLedgerError(f"the sequence ledger cannot be read: {exc}") from exc
    return SequenceLedger.from_dict(data)


def verify_segment_files(
    segments: Sequence[LedgerSegment], *, hash_file: FileHasher = sha256_of
) -> list[str]:
    """Every missing, resized or changed file among ``segments`` (empty when all are exactly as recorded)."""

    problems: list[str] = []
    for segment in segments:
        for record in segment.artifact_files():
            target = Path(record.path)
            if not target.is_file():
                problems.append(f"segment {segment.index}: {target.name} is missing")
            elif target.stat().st_size != record.bytes or hash_file(target) != record.sha256:
                problems.append(
                    f"segment {segment.index}: {target.name} changed since it was recorded"
                )
    return problems


__all__ = [
    "ANCHOR_BASES",
    "BASIS_DECODED",
    "BASIS_NATIVE",
    "FRAME_BASES",
    "LEDGER_FILE_NAME",
    "LEDGER_SCHEMA",
    "ORIGIN_GENERATED",
    "ORIGIN_REUSED",
    "STATE_CANCELLED",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_INTERRUPTED",
    "STATE_RUNNING",
    "FileRecord",
    "FinalFrame",
    "InputAnchor",
    "LedgerSegment",
    "SequenceLedger",
    "SequenceLedgerError",
    "read_ledger",
    "sha256_of",
    "verify_segment_files",
    "write_ledger",
]
