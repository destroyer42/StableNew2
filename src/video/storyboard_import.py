"""Start a Storyboard from an MP4 file the operator picked (PR-VID-STORY-IMPORT).

Tk-free and worker-safe. The operator chooses a file, never a job id:

* **Known StableNew clip.** The file's resolved path is one the job repository recorded as an output of exactly one
  completed job. Lineage is never inferred from a file name or a partial path. That job's own verified root
  preparation (``prepare_clip_root``: native generated frames, smoothing note, hash checks, workflow governance) is used
  unchanged; if it refuses, the refusal is reported and importing the encoded file as media is a separate, explicit
  choice. More than one job recording the same path is ambiguous and is never guessed.
* **External MP4.** Everything else: another application's clip, or one moved out of the output folder. The file is
  inspected with the existing probe (``inspect_driving_video``), compared with the approved workflow's declared frame rate
  and target size, decoded once with the existing bounded decoder, and published through the same staging folder as every
  root: ``storyboards/<id>/root/`` holds the decoded (``basis: decoded``) frames, ``root_cut.json`` and
  ``import_record.json`` (source identity, probe facts, conversion parameters). The cut manifest carries no job id; no
  job, history or generation setting is invented.

A size or timing difference is never fixed silently. :func:`assess_clip` names the conversion (a centred cover resize, the
catalog's own preparation; keeping every Nth frame; relabelling a rate that is within 0.2 percent), and the root is only
made when the operator accepted it. Frames are never stretched, blended or invented, and the source file is only read.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Final, Literal

from src.controller.runtime_state import CancellationError, CancelToken
from src.queue.job_model import JobStatus
from src.utils.atomic_io import atomic_write_json
from src.video.driving_video_inspection import (
    STATUS_FAILED,
    DrivingVideoFacts,
    DrivingVideoInspection,
    inspect_driving_video,
)
from src.video.sequence_frames import (
    MAX_DECODED_FRAMES,
    ClipDecoder,
    SequenceFrameError,
    decode_clip_to_frames,
    require_png,
)
from src.video.sequence_ledger import BASIS_DECODED, FileHasher, sha256_of
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_cut import CutFrame, CutManifest, CutRange
from src.video.storyboard_cuts import read_job
from src.video.storyboard_root import (
    PreparedRoot,
    StoryboardRootError,
    prepare_clip_root,
    publish_root,
    resolve_root_workflow,
    root_target,
)
from src.video.storyboard_tree import TreeRoot
from src.video.workflow_source_preparation import (
    cover_crop_box,
    resolve_declared_target,
    transform_declared_workflow_source,
)

IMPORT_RECORD_NAME: Final = "import_record.json"
IMPORT_RECORD_SCHEMA: Final = "stablenew.storyboard-import.v1"
FRAMES_FOLDER: Final = "frames"
#: How many of the newest completed jobs are searched for a recorded output path. Older clips import as external media.
KNOWN_CLIP_WINDOW: Final = 1000
#: A file rate within this fraction of the workflow's rate (after keeping every Nth frame) may be relabelled, with consent.
RETIME_TOLERANCE: Final = 0.002
MAX_KEEP_EVERY: Final = 8
_TITLE_LIMIT: Final = 200
_OUTPUT_KEYS: Final = ("output_paths", "video_paths", "all_output_paths")
_PRIMARY_KEYS: Final = ("primary_path", "path", "video_path")
_ARTIFACT_KEYS: Final = ("video_workflow_artifact", "video_primary_artifact", "sequence_artifact")


class ClipImportError(StoryboardRootError):
    """The picked file cannot become a storyboard root; nothing was published."""


class ConversionNotAccepted(ClipImportError):
    """The clip needs a conversion the operator has not accepted yet; the message is the proposal."""


class KnownClipRefused(StoryboardRootError):
    """StableNew knows the clip's job but that job's original frames cannot be used; importing the MP4 as media is a choice."""

    def __init__(self, job_id: str, reason: str) -> None:
        self.job_id = job_id
        self.reason = reason
        super().__init__(
            f"StableNew job {job_id} made this clip, but its generated frames cannot be used: {reason} "
            "You can import the encoded MP4 itself as media instead; that keeps no job provenance."
        )


class AmbiguousKnownClip(StoryboardRootError):
    """Several jobs recorded this file as an output; no lineage is guessed."""

    def __init__(self, job_ids: tuple[str, ...]) -> None:
        self.job_ids = job_ids
        super().__init__(
            f"{len(job_ids)} StableNew jobs recorded this file as an output ({', '.join(job_ids[:4])}"
            f"{'…' if len(job_ids) > 4 else ''}), so its origin is ambiguous. "
            "Import the encoded MP4 as media, or start from the job you mean."
        )


# ----------------------------------------------------------------------------------------- small helpers


def default_clip_folder(output_root: str | Path | None) -> str:
    """Where the MP4 browser opens: ``<output root>/movie_clips``, else the output root, else the home folder."""

    candidates: list[Path] = []
    if output_root:
        root = Path(output_root).expanduser()
        candidates += [root / "movie_clips", root]
    candidates.append(Path.home())
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return str(candidate.resolve())
        except OSError:
            continue
    return str(Path.home())


def suggest_title(path: str | Path) -> str:
    """A storyboard title from the file name: the stem, with separators turned into spaces."""

    stem = Path(str(path)).stem
    text = " ".join(re.sub(r"[_\-.]+", " ", stem).split())
    return (text or "Imported clip")[:_TITLE_LIMIT]


def _same_file(left: str, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _source_file(path: str | Path) -> Path:
    text = str(path or "").strip()
    if not text:
        raise ClipImportError("No video clip is selected.")
    try:
        source = Path(text).expanduser().resolve()
        if source.suffix.lower() != ".mp4":
            raise ClipImportError(
                f"{source.name} is not an MP4 file; choose a file ending in .mp4."
            )
        if not source.is_file():
            raise ClipImportError(f"The clip does not exist or was moved: {source}")
        if source.stat().st_size <= 0:
            raise ClipImportError(f"{source.name} is empty.")
    except OSError as exc:
        raise ClipImportError(f"The clip cannot be accessed: {exc}") from exc
    return source


# ----------------------------------------------------------------------------------------- inspection


@dataclass(frozen=True, slots=True)
class ClipFacts:
    """What was found out about the file: its identity, and what it reports about itself."""

    path: str
    filename: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    fps: float | None
    fps_rational: str
    fps_variable: bool
    duration_seconds: float | None
    frame_count: int | None
    frame_count_basis: str
    codec: str
    square_pixels: bool

    def lines(self) -> tuple[str, ...]:
        rate = "unknown" if self.fps is None else f"{_number(self.fps)} fps"
        duration = "unknown" if self.duration_seconds is None else f"{self.duration_seconds:.2f} s"
        if self.frame_count is None:
            frames = "unknown"
        else:
            suffix = "" if self.frame_count_basis == "reported" else " (estimated)"
            frames = f"{self.frame_count}{suffix}"
        return (
            f"File: {self.filename}",
            f"Size: {self.width}×{self.height} · {rate} · {duration} · {frames} frames · {self.codec}",
        )

    def record(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "fps_rational": self.fps_rational,
            "fps_variable_suspected": self.fps_variable,
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "frame_count_basis": self.frame_count_basis,
            "codec": self.codec,
        }


Inspector = Callable[..., DrivingVideoInspection]


def inspect_clip(
    path: str | Path,
    *,
    hash_file: FileHasher = sha256_of,
    inspector: Inspector = inspect_driving_video,
) -> ClipFacts:
    """Probe and hash ``path`` (read only). Missing, empty, non-MP4 or unreadable files are refused with the reason."""

    source = _source_file(path)
    inspection = inspector(source, frame_count=0)
    facts: DrivingVideoFacts | None = inspection.facts
    if inspection.status == STATUS_FAILED or facts is None:
        reason = "; ".join(issue.message for issue in inspection.issues) or "it could not be read"
        raise ClipImportError(f"{source.name} cannot be inspected: {reason}")
    try:
        digest = hash_file(source)
        size = source.stat().st_size
    except OSError as exc:
        raise ClipImportError(f"{source.name} cannot be read: {exc}") from exc
    return ClipFacts(
        path=str(source),
        filename=source.name,
        size_bytes=size,
        sha256=digest,
        width=facts.display_width,
        height=facts.display_height,
        fps=facts.reported_fps,
        fps_rational=facts.fps_rational,
        fps_variable=facts.fps_is_variable_suspected,
        duration_seconds=facts.duration_seconds,
        frame_count=facts.frame_count,
        frame_count_basis=facts.frame_count_basis,
        codec=facts.codec_name,
        square_pixels=facts.sample_aspect_ratio in ("", "1:1", "0:1"),
    )


# ----------------------------------------------------------------------------------------- known StableNew clips


@dataclass(frozen=True, slots=True)
class KnownClip:
    status: Literal["none", "unique", "ambiguous"]
    job_ids: tuple[str, ...] = ()
    detail: str = ""

    @property
    def job_id(self) -> str | None:
        return self.job_ids[0] if self.status == "unique" else None


def _recorded_paths(result: Any) -> list[str]:
    metadata = result.get("metadata") if isinstance(result, Mapping) else None
    if isinstance(metadata, list):
        metadata = next((item for item in reversed(metadata) if isinstance(item, Mapping)), None)
    if not isinstance(metadata, Mapping):
        return []
    found: list[str] = []
    for key in _ARTIFACT_KEYS:
        artifact = metadata.get(key)
        if not isinstance(artifact, Mapping):
            continue
        for name in _OUTPUT_KEYS:
            found += [str(item) for item in artifact.get(name) or () if item]
        found += [str(artifact[name]) for name in _PRIMARY_KEYS if artifact.get(name)]
        assembled = artifact.get("assembled_video")
        if isinstance(assembled, Mapping):
            found += [str(assembled[name]) for name in _PRIMARY_KEYS if assembled.get(name)]
    return found


def resolve_known_clip(
    path: str | Path, *, repository: Any, window: int = KNOWN_CLIP_WINDOW
) -> KnownClip:
    """The completed job(s) whose recorded output is this very file (same resolved path, never a name match)."""

    lister = getattr(repository, "list_recent_jobs", None)
    if not callable(lister):
        return KnownClip("none", detail="The job history is not available to check.")
    source = Path(path)
    try:
        entries = list(lister(statuses={JobStatus.COMPLETED}, limit=window) or ())
    except (OSError, ValueError, RuntimeError) as exc:
        return KnownClip("none", detail=f"The job history could not be searched: {exc}")
    matches: list[str] = []
    for entry in entries:
        job_id = str(getattr(entry, "job_id", "") or "")
        result = getattr(entry, "result", None)
        if result is None and job_id:
            result = getattr(read_job(repository, job_id), "result", None)
        if job_id and any(_same_file(text, source) for text in _recorded_paths(result)):
            matches.append(job_id)
    unique = tuple(dict.fromkeys(matches))
    if not unique:
        return KnownClip(
            "none", detail=f"No StableNew job among the newest {window} recorded this file."
        )
    return KnownClip("unique" if len(unique) == 1 else "ambiguous", unique)


# ----------------------------------------------------------------------------------------- compatibility


@dataclass(frozen=True, slots=True)
class ClipConversion:
    """What preparing the clip for the workflow changes; shown to the operator and recorded."""

    source_size: tuple[int, int]
    target_size: tuple[int, int]
    discarded_fraction: float
    keep_every: int
    source_fps: float | None
    target_fps: int
    retimed: bool

    @property
    def resizes(self) -> bool:
        return self.source_size != self.target_size

    @property
    def needed(self) -> bool:
        return self.resizes or self.keep_every > 1 or self.retimed

    def lines(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.resizes:
            (sw, sh), (tw, th) = self.source_size, self.target_size
            how = "enlarged" if tw * th > sw * sh else "reduced"
            out.append(
                f"Resize: {sw}×{sh} → {tw}×{th}, scaled to cover then centre-cropped (never stretched); "
                f"{self.discarded_fraction * 100:.0f}% of the picture is cropped away and the frames are {how} (Lanczos)."
            )
        if self.keep_every > 1:
            out.append(
                f"Frame rate: keep every {self.keep_every}{_ordinal(self.keep_every)} frame "
                f"({_number(self.source_fps or 0)} → {self.target_fps} fps); the other frames are dropped, "
                "never blended or invented."
            )
        if self.retimed:
            out.append(
                f"Timing: the {_number((self.source_fps or 0) / self.keep_every)} fps clip is treated as "
                f"{self.target_fps} fps; the frames are unchanged and play within 0.2% of their original speed."
            )
        return tuple(out)

    def record(self) -> dict[str, Any]:
        return {
            "resize": None
            if not self.resizes
            else {
                "policy": "cover_resize_center_crop",
                "from": list(self.source_size),
                "to": list(self.target_size),
                "discarded_fraction": round(self.discarded_fraction, 6),
            },
            "keep_every": self.keep_every,
            "retimed": self.retimed,
            "source_fps": self.source_fps,
            "target_fps": self.target_fps,
        }


def _ordinal(number: int) -> str:
    return "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")


@dataclass(frozen=True, slots=True)
class ClipCompatibility:
    workflow_id: str
    workflow_version: str
    target_size: tuple[int, int] | None
    fps: int | None
    kept_frames: int | None
    conversion: ClipConversion | None
    blockers: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return not self.blockers

    @property
    def needs_conversion(self) -> bool:
        return self.conversion is not None and self.conversion.needed

    def lines(self) -> tuple[str, ...]:
        if self.blockers:
            return tuple(f"Cannot be used: {text}" for text in self.blockers)
        name = f"{self.workflow_id} {self.workflow_version}".strip()
        if not self.needs_conversion or self.conversion is None:
            return (f"Compatible with {name}: no conversion is needed.",)
        return (
            f"{name} needs this conversion (the original file is not changed):",
            *self.conversion.lines(),
        )


def _rate_match(fps: float, rational: str, step: int, target: int) -> str:
    """``exact``, ``near`` or ``no``: does keeping every ``step``-th frame of ``fps`` play at ``target``?"""

    try:
        exact = Fraction(rational) / step == target if rational else False
    except (ValueError, ZeroDivisionError):
        exact = False
    effective = fps / step
    if exact or abs(effective - target) <= 1e-6 * target:
        return "exact"
    return "near" if abs(effective / target - 1) <= RETIME_TOLERANCE else "no"


def assess_clip(facts: ClipFacts, settings: Mapping[str, Any], registry: Any) -> ClipCompatibility:
    """Can this clip be a root for the chosen workflow, and what would preparing it change? (read only)"""

    try:
        spec, policy, _kept = resolve_root_workflow(settings, registry, subject="an imported clip")
    except (StoryboardRootError, ValueError) as exc:
        return ClipCompatibility("", "", None, None, None, None, (str(exc),))
    blank = ClipCompatibility(
        str(spec.workflow_id), str(spec.workflow_version), None, int(policy["fps"]), None, None, ()
    )
    blockers: list[str] = []
    preparation = (getattr(spec, "backend_defaults", None) or {}).get("source_preparation")
    target: tuple[int, int] | None = None
    if isinstance(preparation, Mapping):
        try:
            _orientation, size, _rule = resolve_declared_target(
                preparation, facts.width, facts.height
            )
            target = (int(size["width"]), int(size["height"]))
        except ValueError as exc:
            blockers.append(str(exc))
    else:
        blockers.append(
            f"{blank.workflow_id} declares no frame size to continue from, so a clip cannot lead into it"
        )
    if not facts.square_pixels:
        blockers.append(
            "the pixels are not square, so the frames cannot be imported without distorting them"
        )
    if facts.fps_variable:
        blockers.append("the frame rate varies, so the frames are not evenly timed")
    keep_every, retimed = 1, False
    if facts.fps is None:
        blockers.append("the file does not report a frame rate")
    elif not facts.fps_variable:
        for step in range(1, MAX_KEEP_EVERY + 1):
            match = _rate_match(facts.fps, facts.fps_rational, step, blank.fps or 1)
            if match != "no":
                keep_every, retimed = step, match == "near"
                break
        else:
            blockers.append(
                f"it plays at {_number(facts.fps)} fps but {blank.workflow_id} plays at {blank.fps} fps; "
                "matching it would need invented or repeated frames, which an import never creates. Re-encode "
                f"the clip at {blank.fps} fps (or a whole multiple) or pick a workflow with this frame rate"
            )
    count = facts.frame_count
    kept_frames = None if count is None else math.ceil(count / keep_every)
    if count is not None and count > MAX_DECODED_FRAMES:
        blockers.append(
            f"it has {count} frames; an import handles at most {MAX_DECODED_FRAMES}. Trim the clip first"
        )
    elif kept_frames is not None and kept_frames < 2:
        blockers.append("it has fewer than two usable frames")
    conversion = None
    if target is not None and blank.fps is not None:
        box = cover_crop_box((facts.width, facts.height), target)
        kept_area = (box[2] - box[0]) * (box[3] - box[1]) / (facts.width * facts.height)
        conversion = ClipConversion(
            source_size=(facts.width, facts.height),
            target_size=target,
            discarded_fraction=max(0.0, 1.0 - min(1.0, kept_area)),
            keep_every=keep_every,
            source_fps=facts.fps,
            target_fps=blank.fps,
            retimed=retimed,
        )
    return ClipCompatibility(
        blank.workflow_id,
        blank.workflow_version,
        target,
        blank.fps,
        kept_frames,
        conversion,
        tuple(dict.fromkeys(blockers)),
    )


# ----------------------------------------------------------------------------------------- the plan the operator sees


@dataclass(frozen=True, slots=True)
class ClipImportPlan:
    """Everything the dialog shows before anything is created."""

    facts: ClipFacts
    known: KnownClip
    compatibility: ClipCompatibility | None
    title: str

    @property
    def route(self) -> Literal["job", "external", "choose"]:
        if self.known.status == "unique":
            return "job"
        return "choose" if self.known.status == "ambiguous" else "external"

    @property
    def needs_conversion(self) -> bool:
        return self.compatibility is not None and self.compatibility.needs_conversion

    def lines(self) -> tuple[str, ...]:
        out = list(self.facts.lines())
        if self.known.status == "unique":
            out.append(
                f"Source: a StableNew clip (job {self.known.job_id}). Its original job, workflow and generated "
                "frames are used."
            )
        elif self.known.status == "ambiguous":
            out.append(
                f"Source: {len(self.known.job_ids)} StableNew jobs recorded this file, so its origin is ambiguous."
            )
        else:
            out.append(
                "Source: external MP4 (no StableNew job). Its frames are decoded from the file."
            )
        if self.compatibility is not None and self.route != "job":
            out.extend(self.compatibility.lines())
        return tuple(out)


# ----------------------------------------------------------------------------------------- preparing the root


def _cancelled(token: CancelToken | None) -> None:
    if token is not None and token.is_cancelled():
        raise CancellationError("clip import cancelled")


def _prepare_external(
    facts: ClipFacts,
    compat: ClipCompatibility,
    preparation: Mapping[str, Any],
    *,
    staging: Path,
    folder: Path,
    known_note: str,
    hash_file: FileHasher,
    decode_clip: ClipDecoder,
    cancel_token: CancelToken | None,
) -> CutManifest:
    source = Path(facts.path)
    conversion = compat.conversion
    if conversion is None or compat.fps is None or compat.target_size is None:
        raise ClipImportError("the clip's conversion could not be determined")
    decoded_dir = staging / "decoded"
    try:
        decoded = decode_clip(source, decoded_dir, cancel_token)
    except SequenceFrameError as exc:
        raise ClipImportError(f"{facts.filename} cannot be decoded: {exc}") from exc
    if facts.frame_count_basis == "reported" and facts.frame_count != len(decoded):
        raise ClipImportError(
            f"decoding {facts.filename} gave {len(decoded)} frames but the file reports {facts.frame_count}; "
            "the decoded frames are refused rather than trusted"
        )
    try:
        first = require_png(Path(decoded[0]), label="the clip's first decoded frame")
    except SequenceFrameError as exc:
        raise ClipImportError(str(exc)) from exc
    if first != (facts.width, facts.height):
        raise ClipImportError(
            f"the decoded frames are {first[0]}×{first[1]} but the file reports {facts.width}×{facts.height}; "
            "the clip is refused rather than distorted"
        )
    chosen = list(decoded[:: conversion.keep_every])
    if len(chosen) < 2:
        raise ClipImportError("the clip has fewer than two usable frames")
    frames_dir = staging / FRAMES_FOLDER
    frames_dir.mkdir()
    cut_frames: list[CutFrame] = []
    for number, frame in enumerate(chosen, start=1):
        _cancelled(cancel_token)
        target = frames_dir / f"f_{number:06d}.png"
        if conversion.resizes:
            try:
                transform_declared_workflow_source(
                    source_path=frame, policy=preparation
                ).image.save(target, format="PNG")
            except (ValueError, OSError) as exc:
                raise ClipImportError(f"frame {number} could not be prepared: {exc}") from exc
        else:
            os.replace(frame, target)
        try:
            digest = hash_file(target)
        except OSError as exc:
            raise ClipImportError(f"frame {number} cannot be read: {target}: {exc}") from exc
        cut_frames.append(CutFrame(path=str(folder / FRAMES_FOLDER / target.name), sha256=digest))
    shutil.rmtree(decoded_dir, ignore_errors=True)
    width, height = compat.target_size if conversion.resizes else (facts.width, facts.height)
    if (width, height) != compat.target_size:
        raise ClipImportError("the prepared frames are not the workflow's frame size")
    try:
        if hash_file(source) != facts.sha256:
            raise ClipImportError(f"{facts.filename} changed while it was being imported")
    except OSError as exc:
        raise ClipImportError(f"{facts.filename} cannot be read: {exc}") from exc
    record = {
        "schema": IMPORT_RECORD_SCHEMA,
        "source": facts.record(),
        "known_stablenew_job": known_note or None,
        "workflow": {
            "workflow_id": compat.workflow_id,
            "workflow_version": compat.workflow_version,
            "fps": compat.fps,
            "target_size": list(compat.target_size),
        },
        "conversion": conversion.record(),
        "decode": {
            "tool": "ffmpeg",
            "fps_mode": "passthrough",
            "frames_decoded": len(decoded),
            "frames_kept": len(cut_frames),
            "basis": BASIS_DECODED,
        },
        "frames_sha256": [frame.sha256 for frame in cut_frames],
    }
    atomic_write_json(staging / IMPORT_RECORD_NAME, record, indent=2)
    return CutManifest(
        fps=compat.fps,
        width=width,
        height=height,
        frames=tuple(cut_frames),
        ranges=(CutRange(ROOT_PARENT, 0, len(cut_frames) - 1, BASIS_DECODED, 0),),
        lead_in_frames=0,
        job_id=None,
    )


def prepare_external_clip_root(
    facts: ClipFacts,
    *,
    settings: Mapping[str, Any],
    registry: Any,
    storyboard_id: str,
    output_root: str | Path,
    accept_conversion: bool,
    known_note: str = "",
    hash_file: FileHasher = sha256_of,
    decode_clip: ClipDecoder = decode_clip_to_frames,
    cancel_token: CancelToken | None = None,
) -> PreparedRoot:
    """Make the inspected file storyboard ``storyboard_id``'s root with no job behind it (see the module docstring).

    Raises :class:`ClipImportError` (or its :class:`ConversionNotAccepted` subclass whose message is the proposal);
    nothing is left under ``<output_root>/storyboards/<storyboard_id>`` when it does."""

    compat = assess_clip(facts, settings, registry)
    if compat.blockers:
        raise ClipImportError(
            f"{facts.filename} cannot be used with {compat.workflow_id or 'this workflow'}: "
            + "; ".join(compat.blockers)
        )
    if compat.needs_conversion and not accept_conversion:
        raise ConversionNotAccepted(
            "This clip needs a conversion before it can be used. " + " ".join(compat.lines()[1:])
        )
    spec, _policy, kept = resolve_root_workflow(settings, registry, subject="an imported clip")
    preparation = spec.backend_defaults["source_preparation"]
    folder = root_target(output_root, storyboard_id)
    fingerprint: dict[str, str] = {}

    def build(staging: Path, final: Path) -> CutManifest:
        manifest = _prepare_external(
            facts,
            compat,
            preparation,
            staging=staging,
            folder=final,
            known_note=known_note,
            hash_file=hash_file,
            decode_clip=decode_clip,
            cancel_token=cancel_token,
        )
        fingerprint["record"] = hash_file(staging / IMPORT_RECORD_NAME)
        return manifest

    pinned, manifest = publish_root(folder, build)
    record_path = folder / IMPORT_RECORD_NAME
    return PreparedRoot(
        kind="clip",
        job_id=None,
        image_path=None,
        image_sha256=None,
        manifest=pinned,
        settings=kept,
        fps=int(compat.fps or manifest.fps),
        width=manifest.width,
        height=manifest.height,
        smoothing=None,
        external={
            "origin": "external",
            "source_path": facts.path,
            "source_sha256": facts.sha256,
            "source_record_path": str(record_path),
            "source_record_sha256": fingerprint["record"],
        },
    )


class ClipImporter:
    """The worker-side entry the Storyboard service uses; every collaborator is injectable."""

    def __init__(
        self,
        *,
        repository: Callable[[], Any],
        registry: Any,
        output_root: Callable[[], str],
        hash_file: FileHasher = sha256_of,
        decode_clip: ClipDecoder = decode_clip_to_frames,
        inspector: Inspector = inspect_driving_video,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._output_root = output_root
        self._hash = hash_file
        self._decode = decode_clip
        self._inspector = inspector

    def inspect(self, path: str | Path, settings: Mapping[str, Any]) -> ClipImportPlan:
        facts = inspect_clip(path, hash_file=self._hash, inspector=self._inspector)
        known = resolve_known_clip(facts.path, repository=self._repository())
        # Always assessed: it is what applies if the operator imports a known clip as media instead.
        compat = assess_clip(facts, settings, self._registry)
        return ClipImportPlan(facts, known, compat, suggest_title(facts.path))

    def prepare(
        self,
        path: str | Path,
        settings: Mapping[str, Any],
        storyboard_id: str,
        *,
        expected_sha256: str | None = None,
        accept_conversion: bool = False,
        import_as_media: bool = False,
        cancel_token: CancelToken | None = None,
    ) -> PreparedRoot:
        facts = inspect_clip(path, hash_file=self._hash, inspector=self._inspector)
        if expected_sha256 and facts.sha256 != expected_sha256:
            raise ClipImportError(
                f"{facts.filename} changed since it was inspected; choose it again to review it."
            )
        repository = self._repository()
        known = resolve_known_clip(facts.path, repository=repository)
        note = ""
        if known.status != "none" and not import_as_media:
            if known.status == "ambiguous":
                raise AmbiguousKnownClip(known.job_ids)
            try:
                return prepare_clip_root(
                    repository=repository,
                    job_id=str(known.job_id),
                    storyboard_id=storyboard_id,
                    output_root=self._output_root(),
                    registry=self._registry,
                    hash_file=self._hash,
                    decode_clip=self._decode,
                    cancel_token=cancel_token,
                )
            except StoryboardRootError as exc:
                raise KnownClipRefused(str(known.job_id), str(exc)) from exc
        if known.status != "none":
            note = (
                f"StableNew job(s) {', '.join(known.job_ids)} recorded this file; the operator imported the "
                "encoded MP4 as media instead of continuing the job."
            )
        return prepare_external_clip_root(
            facts,
            settings=settings,
            registry=self._registry,
            storyboard_id=storyboard_id,
            output_root=self._output_root(),
            accept_conversion=accept_conversion,
            known_note=note,
            hash_file=self._hash,
            decode_clip=self._decode,
            cancel_token=cancel_token,
        )


# ----------------------------------------------------------------------------------------- reading an imported root back


def source_text(root: TreeRoot) -> str:
    """One line saying where a root's frames came from (empty for a job or image root)."""

    if root.origin != "external":
        return ""
    name = Path(root.source_path).name or root.source_path
    return (
        f"Imported MP4 {name}: its frames were decoded from the file (not native generated frames) and "
        "no StableNew job is behind them."
    )


def read_import_record(root: TreeRoot) -> dict[str, Any]:
    """The pinned ``import_record.json`` of an imported root; refused when it is missing or changed."""

    if root.origin != "external":
        raise ClipImportError("this storyboard was not made from an imported clip")
    path = Path(root.source_record_path)
    try:
        if sha256_of(path) != root.source_record_sha256:
            raise ClipImportError(f"the import record changed since it was written: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClipImportError(f"the import record cannot be read: {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != IMPORT_RECORD_SCHEMA:
        raise ClipImportError(f"the import record is not a {IMPORT_RECORD_SCHEMA} file: {path}")
    return data


__all__ = [
    "FRAMES_FOLDER",
    "IMPORT_RECORD_NAME",
    "IMPORT_RECORD_SCHEMA",
    "KNOWN_CLIP_WINDOW",
    "AmbiguousKnownClip",
    "ClipCompatibility",
    "ClipConversion",
    "ClipFacts",
    "ClipImportError",
    "ClipImportPlan",
    "ClipImporter",
    "ConversionNotAccepted",
    "KnownClip",
    "KnownClipRefused",
    "assess_clip",
    "default_clip_folder",
    "inspect_clip",
    "prepare_external_clip_root",
    "read_import_record",
    "resolve_known_clip",
    "source_text",
    "suggest_title",
]
