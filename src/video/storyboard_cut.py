"""The cut manifest of a stitched storyboard cut (PR-VID-STORY-380).

A cut is an ordered list of PNG frames. The manifest records each frame's path and SHA-256, the cut's fps and size, and
ranges saying which node (the root clip or a take) owns which frames. The sequence executor writes one next to a job's
output; admission and the Storyboard tab read it. A take that continues from a frame of a parent cut records a
:class:`~src.video.sequence_plan.StoryboardLeadIn`: the parent manifest's hash, the lead-in length K (the parent's
frames up to and including the handoff frame), and the handoff frame's path and hash.

Frame numbers in messages are 1-based (what the operator sees); every index in the data model is 0-based.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from src.utils.atomic_io import atomic_write_json
from src.video.sequence_ledger import (
    BASIS_DECODED,
    BASIS_NATIVE,
    FRAME_BASES,
    FileHasher,
    FileRecord,
    sha256_of,
)
from src.video.sequence_plan import SequencePlanError, StoryboardLeadIn

CUT_MANIFEST_SCHEMA: Final = "stablenew.storyboard_cut.v1"

MIN_FPS: Final = 1
MAX_FPS: Final = 120

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

MANIFEST_KEYS: Final = frozenset(
    {"schema", "fps", "width", "height", "frames", "ranges", "lead_in_frames", "job_id"}
)
FRAME_KEYS: Final = frozenset({"path", "sha256"})
RANGE_KEYS: Final = frozenset({"owner", "start", "end", "basis", "trimmed"})


class CutManifestError(SequencePlanError):
    """A cut manifest is missing, malformed, changed, or does not fit the plan that continues from it."""


def _unknown(kind: str, data: Mapping[str, Any], allowed: frozenset[str]) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise CutManifestError(
            f"unknown {kind} field(s) {', '.join(repr(key) for key in extra)}; "
            f"only {', '.join(sorted(allowed))} may be set"
        )


def _int(kind: str, name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CutManifestError(
            f"the cut manifest {kind} {name} must be a whole number, got {value!r}"
        )
    return value


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


@dataclass(frozen=True, slots=True)
class CutFrame:
    path: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CutFrame:
        if not isinstance(data, Mapping):
            raise CutManifestError("a cut manifest frame must be an object")
        _unknown("frame", data, FRAME_KEYS)
        try:
            return cls(path=str(data["path"]), sha256=str(data["sha256"]))
        except KeyError as exc:
            raise CutManifestError(f"a cut manifest frame is missing {exc}") from exc


@dataclass(frozen=True, slots=True)
class CutRange:
    """Frames ``start..end`` (inclusive, 0-based) belong to ``owner``."""

    owner: str
    start: int
    end: int
    basis: str
    #: Leading generated frames dropped before this range: 1 for a take after its overlap, 0 for the root.
    trimmed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "start": self.start,
            "end": self.end,
            "basis": self.basis,
            "trimmed": self.trimmed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CutRange:
        if not isinstance(data, Mapping):
            raise CutManifestError("a cut manifest range must be an object")
        _unknown("range", data, RANGE_KEYS)
        try:
            return cls(
                owner=str(data["owner"]),
                start=_int("range", "start", data["start"]),
                end=_int("range", "end", data["end"]),
                basis=str(data["basis"]),
                trimmed=_int("range", "trimmed", data.get("trimmed", 0)),
            )
        except KeyError as exc:
            raise CutManifestError(f"a cut manifest range is missing {exc}") from exc


@dataclass(frozen=True, slots=True)
class CutManifest:
    fps: int
    width: int
    height: int
    frames: tuple[CutFrame, ...]
    ranges: tuple[CutRange, ...]
    #: How many leading frames are the lead-in carried from a parent cut (0 for a root cut).
    lead_in_frames: int
    job_id: str | None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not MIN_FPS <= self.fps <= MAX_FPS:
            errors.append(f"the cut manifest fps must be {MIN_FPS}-{MAX_FPS}, got {self.fps}")
        if self.width <= 0 or self.height <= 0:
            errors.append(f"the cut manifest size must be positive, got {self.width}x{self.height}")
        if not self.frames:
            errors.append("the cut manifest has no frames")
        if not 0 <= self.lead_in_frames <= len(self.frames):
            errors.append(
                f"the cut manifest lead_in_frames ({self.lead_in_frames}) must be between 0 and "
                f"its {len(self.frames)} frame(s)"
            )
        for position, frame in enumerate(self.frames):
            if not _SHA256.match(frame.sha256):
                errors.append(f"cut frame {position + 1} has a malformed SHA-256: {frame.path}")
        expected_start = 0
        covered = True
        for position, cut_range in enumerate(self.ranges):
            label = f"cut range {position + 1} ({cut_range.owner!r})"
            if cut_range.basis not in FRAME_BASES:
                errors.append(f"{label} has an unknown basis {cut_range.basis!r}")
            if cut_range.trimmed < 0:
                errors.append(f"{label} trimmed must not be negative")
            if cut_range.start != expected_start or cut_range.end < cut_range.start:
                covered = False
            expected_start = cut_range.end + 1
        if not self.ranges or not covered or expected_start != len(self.frames):
            errors.append(
                f"the cut ranges must cover every frame, in order, from frame 1 to frame "
                f"{len(self.frames)} with no gap or overlap"
            )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CUT_MANIFEST_SCHEMA,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "lead_in_frames": self.lead_in_frames,
            "job_id": self.job_id,
            "frames": [frame.to_dict() for frame in self.frames],
            "ranges": [cut_range.to_dict() for cut_range in self.ranges],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CutManifest:
        if not isinstance(data, Mapping):
            raise CutManifestError("the cut manifest must be a JSON object")
        _unknown("cut manifest", data, MANIFEST_KEYS)
        if data.get("schema") != CUT_MANIFEST_SCHEMA:
            raise CutManifestError(
                f"the cut manifest schema must be {CUT_MANIFEST_SCHEMA}, got {data.get('schema')!r}"
            )
        frames = data.get("frames")
        ranges = data.get("ranges")
        if not isinstance(frames, (list, tuple)) or not isinstance(ranges, (list, tuple)):
            raise CutManifestError("the cut manifest frames and ranges must be lists")
        job_id = data.get("job_id")
        try:
            return cls(
                fps=_int("manifest", "fps", data["fps"]),
                width=_int("manifest", "width", data["width"]),
                height=_int("manifest", "height", data["height"]),
                frames=tuple(CutFrame.from_dict(item) for item in frames),
                ranges=tuple(CutRange.from_dict(item) for item in ranges),
                lead_in_frames=_int("manifest", "lead_in_frames", data.get("lead_in_frames", 0)),
                job_id=None if job_id is None else str(job_id),
            )
        except KeyError as exc:
            raise CutManifestError(f"the cut manifest is missing {exc}") from exc

    def owner_of(self, index: int) -> CutRange:
        """The range that owns the 0-based frame ``index``."""

        for cut_range in self.ranges:
            if cut_range.start <= index <= cut_range.end:
                return cut_range
        raise CutManifestError(f"no cut range owns frame {index + 1}")

    def segment_ranges(self) -> tuple[CutRange, ...]:
        """The ranges this cut's own job produced: those starting at or after the lead-in, in order."""

        return tuple(item for item in self.ranges if item.start >= self.lead_in_frames)

    def prefix(self, count: int) -> CutManifest:
        """The first ``count`` frames, with the ranges (and the lead-in length) cut to fit."""

        if not 0 <= count <= len(self.frames):
            raise CutManifestError(
                f"a prefix of {count} frame(s) is outside this {len(self.frames)}-frame cut"
            )
        kept = tuple(
            CutRange(item.owner, item.start, min(item.end, count - 1), item.basis, item.trimmed)
            for item in self.ranges
            if item.start < count
        )
        return CutManifest(
            fps=self.fps,
            width=self.width,
            height=self.height,
            frames=self.frames[:count],
            ranges=kept,
            lead_in_frames=min(self.lead_in_frames, count),
            job_id=self.job_id,
        )


def write_cut_manifest(path: Path, manifest: CutManifest) -> CutFrame:
    """Write atomically and return the path and the SHA-256 of the file as written (what a plan pins)."""

    errors = manifest.validate()
    if errors:
        raise CutManifestError(f"the cut manifest is not valid: {'; '.join(errors)}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, manifest.to_dict(), indent=2)
    return CutFrame(path=str(target), sha256=sha256_of(target))


def read_cut_manifest(path: str | Path, *, expected_sha256: str | None = None) -> CutManifest:
    """Load a manifest; with ``expected_sha256`` the file must be byte-identical to what was recorded."""

    target = Path(path)
    if not target.is_file():
        raise CutManifestError(f"the cut manifest is missing: {target}")
    if expected_sha256 is not None and sha256_of(target) != expected_sha256:
        raise CutManifestError(f"the cut manifest changed since it was recorded: {target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CutManifestError(f"the cut manifest cannot be read: {target}: {exc}") from exc
    manifest = CutManifest.from_dict(data)
    errors = manifest.validate()
    if errors:
        raise CutManifestError(f"the cut manifest {target} is not valid: {'; '.join(errors)}")
    return manifest


def _hash(path: str | Path, hash_file: FileHasher, what: str) -> str:
    try:
        return hash_file(path)
    except OSError as exc:
        raise CutManifestError(f"{what} cannot be read: {path}: {exc}") from exc


def _check_lead_in_length(lead_in: StoryboardLeadIn, manifest: CutManifest) -> None:
    if not 1 <= lead_in.frame_count <= len(manifest.frames):
        raise CutManifestError(
            f"the lead-in length must be 1 to {len(manifest.frames)} frame(s) (the parent cut's "
            f"frames), got {lead_in.frame_count}: {lead_in.manifest_path}"
        )


def _check_frame_present(frame: CutFrame, number: int) -> None:
    if not Path(frame.path).is_file():
        raise CutManifestError(f"a lead-in frame is missing (frame {number}): {frame.path}")


def verify_lead_in(
    lead_in: StoryboardLeadIn,
    *,
    target_size: tuple[int, int],
    fps: int,
    hash_file: FileHasher,
) -> CutManifest:
    """Admission checks of a storyboard lead-in; returns the parsed parent manifest (whole, not truncated).

    Hashes the manifest file and the handoff PNG and confirms every lead-in frame exists. It does not hash every frame:
    the executor does that (:func:`lead_in_frames`) right before assembly.
    """

    manifest = read_cut_manifest(lead_in.manifest_path, expected_sha256=lead_in.manifest_sha256)
    _check_lead_in_length(lead_in, manifest)
    handoff = manifest.frames[lead_in.frame_count - 1]
    if (
        not _same_path(handoff.path, lead_in.handoff_path)
        or handoff.sha256 != lead_in.handoff_sha256
    ):
        raise CutManifestError(
            f"the handoff frame is not frame K ({lead_in.frame_count}) of the parent cut: "
            f"{lead_in.handoff_path}"
        )
    _check_frame_present(handoff, lead_in.frame_count)
    if _hash(handoff.path, hash_file, "the handoff frame") != lead_in.handoff_sha256:
        raise CutManifestError(f"the handoff frame changed since it was recorded: {handoff.path}")
    width, height = target_size
    if (manifest.width, manifest.height) != (width, height):
        raise CutManifestError(
            f"the parent cut is {manifest.width}x{manifest.height}, which is not the target size "
            f"{width}x{height}"
        )
    if manifest.fps != fps:
        raise CutManifestError(f"the parent cut plays at {manifest.fps} fps, not {fps} fps")
    for position, frame in enumerate(manifest.frames[: lead_in.frame_count]):
        _check_frame_present(frame, position + 1)
    return manifest


def lead_in_frames(lead_in: StoryboardLeadIn, *, hash_file: FileHasher) -> list[Path]:
    """The K lead-in frame paths, each re-hashed against the manifest (the executor, before assembly)."""

    manifest = read_cut_manifest(lead_in.manifest_path, expected_sha256=lead_in.manifest_sha256)
    _check_lead_in_length(lead_in, manifest)
    paths: list[Path] = []
    for position, frame in enumerate(manifest.frames[: lead_in.frame_count]):
        _check_frame_present(frame, position + 1)
        if _hash(frame.path, hash_file, f"lead-in frame {position + 1}") != frame.sha256:
            raise CutManifestError(f"lead-in frame {position + 1} changed: {frame.path}")
        paths.append(Path(frame.path))
    return paths


def take_manifest(
    *,
    lead_in: CutManifest | None,
    segments: Sequence[tuple[str, Sequence[FileRecord], int, str]],
    fps: int,
    width: int,
    height: int,
    job_id: str,
) -> CutManifest:
    """Append each segment's kept frames (its overlap dropped) to the lead-in as one range.

    ``segments`` are ``(owner, frames, overlap_frames, basis)``. The first ``overlap_frames`` of a segment's frames
    repeat the frame before them and are not part of the cut; the range records them as ``trimmed``.
    """

    if lead_in is not None and (lead_in.fps, lead_in.width, lead_in.height) != (fps, width, height):
        raise CutManifestError(
            f"the lead-in is {lead_in.width}x{lead_in.height} at {lead_in.fps} fps, not "
            f"{width}x{height} at {fps} fps"
        )
    frames: list[CutFrame] = list(lead_in.frames) if lead_in is not None else []
    ranges: list[CutRange] = list(lead_in.ranges) if lead_in is not None else []
    lead_in_count = len(frames)
    for owner, records, overlap, basis in segments:
        if not 0 <= overlap < len(records):
            raise CutManifestError(
                f"segment {owner!r} has {len(records)} frame(s) and cannot drop an overlap of {overlap}"
            )
        start = len(frames)
        frames.extend(
            CutFrame(path=record.path, sha256=record.sha256) for record in records[overlap:]
        )
        ranges.append(CutRange(owner, start, len(frames) - 1, basis, overlap))
    manifest = CutManifest(
        fps=fps,
        width=width,
        height=height,
        frames=tuple(frames),
        ranges=tuple(ranges),
        lead_in_frames=lead_in_count,
        job_id=job_id,
    )
    errors = manifest.validate()
    if errors:
        raise CutManifestError(f"the cut manifest is not valid: {'; '.join(errors)}")
    return manifest


__all__ = [
    "BASIS_DECODED",
    "BASIS_NATIVE",
    "CUT_MANIFEST_SCHEMA",
    "CutFrame",
    "CutManifest",
    "CutManifestError",
    "CutRange",
    "lead_in_frames",
    "read_cut_manifest",
    "take_manifest",
    "verify_lead_in",
    "write_cut_manifest",
]
