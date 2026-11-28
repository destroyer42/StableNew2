"""Storyboard root preparation (PR-VID-STORY-380, spec 7.3).

A storyboard starts from a finished StableNew Comfy clip job or from a still image. A clip root becomes a hash-pinned
cut manifest of the job's real generated frames, with one ``root`` range, at ``<output root>/storyboards/<storyboard
id>/root/root_cut.json``. What the frames are depends on the job:

* a storyboard take (sequence policy v2): its own cut manifest, re-ranged as one ``root`` range;
* a v1 sequence: its ledger's frames after the overlap trim, or the colour-matched copies where colour matching ran
  (exactly the frames it encoded);
* a frames-out single clip: the PNGs Comfy saved, referenced where they are (never copied) and cross-checked against
  the ``frames_out`` record of the backend manifest;
* an encoded-only clip (TI2V-5B 1.2.0): Comfy's own unsmoothed file decoded once into the root folder (basis
  ``decoded``).

A clip that was smoothed (RIFE) enters as its generated frames at the workflow's own fps, never the invented
in-betweens, and the root carries a :class:`SmoothingNote`. A root inherits only :data:`ROOT_SETTING_KEYS` from the job;
smoothing, the seed and the experimental opt-in never pass to a take.

Nothing durable is published until preparation succeeds: everything is built in a temporary sibling folder that is
renamed to ``root/`` at the end, and a storyboard that already has a root is refused rather than overwritten.
``registry`` is the workflow registry port the app hands to admission (``get(workflow_id, version)``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.njr_core_v26 import thaw_json
from src.video.frame_retention import frames_were_removed
from src.video.frames_out import frames_output_fps, natural_frame_order
from src.video.sequence_admission import read_still_size, workflow_segment_errors
from src.video.sequence_frames import (
    ClipDecoder,
    SequenceFrameError,
    decode_clip_to_frames,
    require_png,
    trim_overlap,
)
from src.video.sequence_ledger import (
    LEDGER_FILE_NAME,
    FileHasher,
    FileRecord,
    SequenceLedger,
    SequenceLedgerError,
    read_ledger,
    sha256_of,
)
from src.video.sequence_locator import locate_ledger
from src.video.sequence_plan import (
    ROOT_PARENT,
    STAGE_SVD_NATIVE,
    STAGE_VIDEO_WORKFLOW,
    SequencePlan,
    SequencePlanError,
)
from src.video.sequence_resume import (
    PLAN_KEY,
    SequenceResumeError,
    find_ledger_path,
    plan_from_njr,
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
from src.video.workflow_frame_count import frame_count_policy, parse_frame_count

ROOT_SETTING_KEYS: Final = frozenset(
    {
        "workflow_id",
        "workflow_version",
        "frame_count",
        "negative_prompt",
        "motion_profile",
        "output_route",
    }
)
STORYBOARDS_FOLDER: Final = "storyboards"
ROOT_FOLDER: Final = "root"
ROOT_CUT_FILE_NAME: Final = "root_cut.json"
SMOOTHED_ONLY: Final = (
    "Only the smoothed video is left; its in-between frames were invented, so it cannot be "
    "continued exactly"
)
#: A storyboard id names a folder, so it is a plain name: no separators, no dots, nothing that leaves the folder.
_STORYBOARD_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_VIDEO_SUFFIXES: Final = frozenset({".mp4", ".mov", ".webm", ".mkv"})
#: The stage-config keys a root reads straight from the job's ``video_workflow`` stage (``output_route`` lives in the
#: NJR's ``pipeline`` config, where ``VideoWorkflowNjrBuilder.build_job`` writes it).
_STAGE_SETTING_KEYS: Final = (
    "workflow_id",
    "workflow_version",
    "frame_count",
    "negative_prompt",
    "motion_profile",
)


class StoryboardRootError(ValueError):
    """The clip or image cannot be a storyboard root; nothing was published."""


@dataclass(frozen=True, slots=True)
class SmoothingNote:
    """The root clip was smoothed; the storyboard uses its generated frames at the workflow's fps."""

    smoothed_fps: int
    fps: int
    frame_count: int

    def text(self) -> str:
        return (
            f"This clip was smoothed to {self.smoothed_fps} fps. The storyboard uses its "
            f"{self.frame_count} generated frames at {self.fps} fps."
        )


@dataclass(frozen=True, slots=True)
class PreparedRoot:
    kind: Literal["clip", "image"]
    job_id: str | None
    image_path: str | None
    image_sha256: str | None
    #: Path and SHA-256 of the root cut manifest (``None`` for an image root).
    manifest: CutFrame | None
    #: Only :data:`ROOT_SETTING_KEYS`.
    settings: Mapping[str, Any]
    fps: int
    width: int
    height: int
    smoothing: SmoothingNote | None
    #: The ``TreeRoot`` source fields of an imported external clip (``origin`` and the source/record identities);
    #: ``None`` for every root made from a job or a still image.
    external: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class _ClipJob:
    job_id: str
    njr: Any
    result: Any
    stage: dict[str, Any]
    spec: Any
    fps: int


#: ``(staging folder, final root folder) -> manifest``; frame paths always name the final folder.
RootBuild = Callable[[Path, Path], CutManifest]


# ----------------------------------------------------------------------------------------- small helpers


def _check_cancel(cancel_token: CancelToken | None) -> None:
    if cancel_token is not None and cancel_token.is_cancelled():
        raise CancellationError("storyboard root preparation cancelled")


def _lookup_text(exc: KeyError) -> str:
    # A KeyError's str() quotes its message; the registry's lookup error carries a readable one.
    return str(exc.args[0]) if exc.args else str(exc)


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def _metadata(result: Any) -> Mapping[str, Any]:
    """The run metadata of a persisted job result (a mapping, or the last mapping of a list)."""

    metadata = result.get("metadata") if isinstance(result, Mapping) else None
    if isinstance(metadata, Mapping):
        return metadata
    if isinstance(metadata, list):
        for item in reversed(metadata):
            if isinstance(item, Mapping):
                return item
    return {}


def _hash(path: str, hash_file: FileHasher, number: int) -> str:
    try:
        return hash_file(path)
    except OSError as exc:
        raise StoryboardRootError(f"frame {number} cannot be read: {path}: {exc}") from exc


def _missing(path: str, number: int) -> StoryboardRootError:
    return StoryboardRootError(f"a generated frame is missing (frame {number}): {path}")


def _verified(
    recorded: Sequence[tuple[str, str]], *, hash_file: FileHasher, cancel_token: CancelToken | None
) -> tuple[CutFrame, ...]:
    """Each ``(path, sha256)`` re-hashed; the first missing or changed frame is refused by name."""

    frames: list[CutFrame] = []
    for number, (path, expected) in enumerate(recorded, start=1):
        _check_cancel(cancel_token)
        if not Path(path).is_file():
            raise _missing(path, number)
        if _hash(path, hash_file, number) != expected:
            raise StoryboardRootError(f"frame {number} changed since it was recorded: {path}")
        frames.append(CutFrame(path=path, sha256=expected))
    return tuple(frames)


def _png_size(path: str) -> tuple[int, int]:
    try:
        return require_png(Path(path), label="the root's first frame")
    except SequenceFrameError as exc:
        raise StoryboardRootError(str(exc)) from exc


def _root_manifest(
    frames: tuple[CutFrame, ...], *, basis: str, fps: int, size: tuple[int, int], job_id: str
) -> CutManifest:
    return CutManifest(
        fps=fps,
        width=size[0],
        height=size[1],
        frames=frames,
        ranges=(CutRange(ROOT_PARENT, 0, len(frames) - 1, basis, 0),),
        lead_in_frames=0,
        job_id=job_id,
    )


# ----------------------------------------------------------------------------------------- publishing


def root_target(output_root: str | Path, storyboard_id: str) -> Path:
    if not isinstance(storyboard_id, str) or not _STORYBOARD_ID.fullmatch(storyboard_id):
        raise StoryboardRootError(
            f"the storyboard id {storyboard_id!r} must be 1-64 letters, digits, '-' or '_'"
        )
    folder = (
        Path(output_root).expanduser().resolve() / STORYBOARDS_FOLDER / storyboard_id / ROOT_FOLDER
    )
    if folder.exists():
        raise StoryboardRootError(
            f"storyboard {storyboard_id} already has a root; a storyboard's root is never replaced: {folder}"
        )
    return folder


def publish_root(folder: Path, build: RootBuild) -> tuple[CutFrame, CutManifest]:
    """Build in a temporary sibling folder and rename it to ``root/`` only when everything succeeded."""

    parent = folder.parent
    created = [path for path in (parent.parent, parent) if not path.exists()]
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{ROOT_FOLDER}.tmp-", dir=parent))
    published = False
    try:
        manifest = build(staging, folder)
        try:
            written = write_cut_manifest(staging / ROOT_CUT_FILE_NAME, manifest)
        except CutManifestError as exc:
            raise StoryboardRootError(f"the root cut manifest cannot be written: {exc}") from exc
        if folder.exists():
            raise StoryboardRootError(
                f"storyboard {parent.name} already has a root; a storyboard's root is never replaced: {folder}"
            )
        try:
            staging.rename(folder)
        except OSError as exc:
            raise StoryboardRootError(
                f"the storyboard root could not be put in place: {folder}: {exc}"
            ) from exc
        published = True
        return CutFrame(path=str(folder / ROOT_CUT_FILE_NAME), sha256=written.sha256), manifest
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)
            for path in reversed(created):  # only folders this call made, and only while empty
                with suppress(OSError):
                    path.rmdir()


# ----------------------------------------------------------------------------------------- the job


def _load_clip_job(repository: Any, job_id: str, registry: Any) -> _ClipJob:
    job = repository.get_job_model(job_id)
    if job is None:
        raise StoryboardRootError(f"Job {job_id} was not found")
    status = str(getattr(job.status, "value", job.status))
    if status != "completed":
        raise StoryboardRootError(
            f"Job {job_id} has not completed (it is {status}); a storyboard starts from a finished clip"
        )
    njr = getattr(job, "_normalized_record", None)
    if njr is None:
        raise StoryboardRootError(
            f"Job {job_id} has no frozen job record to start a storyboard from"
        )
    stages = {stage.stage_type: stage for stage in njr.stage_chain}
    if STAGE_VIDEO_WORKFLOW not in stages:
        if STAGE_SVD_NATIVE in stages:
            raise StoryboardRootError(
                f"Job {job_id} is a native SVD clip; a storyboard starts only from a Comfy video workflow clip"
            )
        raise StoryboardRootError(f"Job {job_id} is not a Comfy video workflow clip")
    stage: dict[str, Any] = thaw_json(stages[STAGE_VIDEO_WORKFLOW].extra)
    workflow_id = str(stage.get("workflow_id") or "")
    workflow_version = str(stage.get("workflow_version") or "") or None
    name = f"{workflow_id} {workflow_version or ''}".strip()
    problems: list[str] = []
    if stage.get("pose_video_path"):
        problems.append(f"{name} follows a driving video, which a storyboard take cannot supply")
    spec: Any = None
    try:
        spec = registry.get(workflow_id, workflow_version)
    except KeyError as exc:
        problems.append(_lookup_text(exc))
    policy = None if spec is None else frame_count_policy(spec)
    if spec is not None:
        execution = stage.get("video_execution")
        opt_in = isinstance(execution, Mapping) and execution.get("experimental_opt_in") is True
        frame_count: Any = stage.get("frame_count")  # validated by parse_frame_count inside
        problems.extend(
            workflow_segment_errors(
                spec,
                spec,
                frame_count,
                0 if policy is None else int(policy["fps"]),
                experimental_opt_in=opt_in,
            )
        )
    if problems or policy is None:
        raise StoryboardRootError(
            f"Job {job_id} cannot start a storyboard: {'; '.join(dict.fromkeys(problems))}"
        )
    return _ClipJob(job_id, njr, job.result, stage, spec, int(policy["fps"]))


def check_clip_job(repository: Any, job_id: str, registry: Any) -> None:
    """Whether the finished job ``job_id`` can start a storyboard; reads only. Raises :class:`StoryboardRootError`."""

    _load_clip_job(repository, job_id, registry)


def recorded_clip_frames(repository: Any, job_id: str) -> tuple[str, ...]:
    """The generated frames a single clip job recorded, in order, when every one is still on disk; else empty."""

    job = repository.get_job_model(job_id)
    artifact = _metadata(getattr(job, "result", None)).get("video_workflow_artifact")
    if not isinstance(artifact, Mapping):
        return ()
    paths = [str(path) for path in natural_frame_order(artifact.get("frame_paths") or ())]
    return tuple(paths) if paths and all(Path(path).is_file() for path in paths) else ()


def clip_last_frame(
    repository: Any,
    job_id: str,
    folder: str | Path,
    *,
    decode_clip: ClipDecoder = decode_clip_to_frames,
) -> str:
    """The last generated frame of a clip job, for engines that cannot make Storyboard takes (V1-6).

    A recorded frame is used where it is; otherwise the job's un-smoothed clip is decoded and its last frame is kept
    as ``<folder>/last_frame.png``. Never the thumbnail. Raises :class:`StoryboardRootError` when neither exists.
    """

    frames = recorded_clip_frames(repository, job_id)
    if frames:
        return frames[-1]
    job = repository.get_job_model(job_id)
    artifact = _metadata(getattr(job, "result", None)).get("video_workflow_artifact")
    if not isinstance(artifact, Mapping):
        raise StoryboardRootError(f"Job {job_id} recorded no video workflow output")
    manifests = [str(item) for item in artifact.get("manifest_paths") or () if item]
    interpolation: Mapping[str, Any] | None = None
    if manifests and Path(manifests[0]).is_file():
        try:
            backend = json.loads(Path(manifests[0]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StoryboardRootError(f"the backend manifest cannot be read: {exc}") from exc
        value = backend.get("interpolation") if isinstance(backend, Mapping) else None
        interpolation = value if isinstance(value, Mapping) else None
    clip = _unsmoothed_clip(artifact, interpolation)
    if clip is None or not clip.is_file():
        raise StoryboardRootError(f"the clip of job {job_id} is missing: {clip}")
    target = Path(folder) / "last_frame.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as scratch:
        try:
            decoded = decode_clip(clip, Path(scratch) / "frames", None)
        except SequenceFrameError as exc:
            raise StoryboardRootError(f"Job {job_id}: {exc}") from exc
        if not decoded:
            raise StoryboardRootError(f"decoding {clip.name} gave no frames")
        shutil.copyfile(decoded[-1], target)
    return str(target)


def _clip_settings(job: _ClipJob) -> dict[str, Any]:
    settings: dict[str, Any] = {
        key: job.stage[key] for key in _STAGE_SETTING_KEYS if key in job.stage
    }
    pipeline = thaw_json(getattr(job.njr, "config", None) or {}).get("pipeline")
    if isinstance(pipeline, Mapping) and pipeline.get("output_route"):
        settings["output_route"] = str(pipeline["output_route"])
    return settings


# ----------------------------------------------------------------------------------------- sequences and takes


def _plan(job: _ClipJob) -> SequencePlan:
    try:
        return plan_from_njr(job.njr, STAGE_VIDEO_WORKFLOW)
    except SequenceResumeError as exc:
        raise StoryboardRootError(f"Job {job.job_id}: {exc}") from exc


def _ledger(job: _ClipJob, output_root: Path) -> SequenceLedger:
    path = find_ledger_path(job.result) or locate_ledger(job.job_id, [output_root])
    if not path:
        raise StoryboardRootError(
            f"the sequence checkpoint ({LEDGER_FILE_NAME}) of job {job.job_id} was not found"
        )
    try:
        ledger = read_ledger(Path(path))
    except SequenceLedgerError as exc:
        raise StoryboardRootError(f"Job {job.job_id}: {exc}") from exc
    if ledger.job_id != job.job_id:
        raise StoryboardRootError(
            f"the checkpoint {path} belongs to job {ledger.job_id}, not {job.job_id}"
        )
    if ledger.next_segment is not None:
        raise StoryboardRootError(
            f"the sequence of job {job.job_id} finished only {ledger.completed_prefix} of its "
            f"{ledger.total_segments} segments"
        )
    return ledger


def _take_root(
    job: _ClipJob, output_root: Path, *, hash_file: FileHasher, cancel_token: CancelToken | None
) -> CutManifest:
    artifact = _metadata(job.result).get("sequence_artifact")
    reference = artifact.get("cut_manifest") if isinstance(artifact, Mapping) else None
    if not reference:
        reference = _ledger(job, output_root).cut_manifest
    if (
        not isinstance(reference, Mapping)
        or not reference.get("path")
        or not reference.get("sha256")
    ):
        raise StoryboardRootError(f"the storyboard take {job.job_id} recorded no cut manifest")
    try:
        cut = read_cut_manifest(str(reference["path"]), expected_sha256=str(reference["sha256"]))
    except CutManifestError as exc:
        raise StoryboardRootError(f"Job {job.job_id}: {exc}") from exc
    if cut.fps != job.fps:
        raise StoryboardRootError(
            f"the cut of job {job.job_id} plays at {cut.fps} fps, not its workflow's {job.fps} fps"
        )
    frames = _verified(
        [(frame.path, frame.sha256) for frame in cut.frames],
        hash_file=hash_file,
        cancel_token=cancel_token,
    )
    basis = (
        BASIS_DECODED if any(item.basis == BASIS_DECODED for item in cut.ranges) else BASIS_NATIVE
    )
    return _root_manifest(
        frames, basis=basis, fps=job.fps, size=(cut.width, cut.height), job_id=job.job_id
    )


def _sequence_root(
    job: _ClipJob, output_root: Path, *, hash_file: FileHasher, cancel_token: CancelToken | None
) -> CutManifest:
    ledger = _ledger(job, output_root)
    used: list[FileRecord] = []
    for segment in ledger.segments:
        # Colour-matched copies are made after the trim, from exactly the frames the assembly encodes.
        if segment.color_matched:
            used.extend(segment.color_matched)
            continue
        try:
            used.extend(trim_overlap(segment.frames, segment.overlap_frames))
        except SequenceFrameError as exc:
            raise StoryboardRootError(
                f"segment {segment.index} of job {job.job_id}: {exc}"
            ) from exc
    if not used:
        raise StoryboardRootError(f"the sequence of job {job.job_id} recorded no frames")
    frames = _verified(
        [(record.path, record.sha256) for record in used],
        hash_file=hash_file,
        cancel_token=cancel_token,
    )
    decoded = any(segment.final_frame.basis == BASIS_DECODED for segment in ledger.segments)
    return _root_manifest(
        frames,
        basis=BASIS_DECODED if decoded else BASIS_NATIVE,
        fps=job.fps,
        size=_png_size(frames[0].path),
        job_id=job.job_id,
    )


# ----------------------------------------------------------------------------------------- single clips


def _backend_manifest(job: _ClipJob, artifact: Mapping[str, Any]) -> Mapping[str, Any]:
    paths = [str(item) for item in artifact.get("manifest_paths") or () if item]
    if not paths:
        raise StoryboardRootError(
            f"Job {job.job_id} recorded no backend manifest, so its frames cannot be checked"
        )
    path = Path(paths[0])
    if not path.is_file():
        raise StoryboardRootError(f"the backend manifest of job {job.job_id} is missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoryboardRootError(f"the backend manifest {path} cannot be read: {exc}") from exc
    if not isinstance(data, Mapping):
        raise StoryboardRootError(f"the backend manifest {path} is not a JSON object")
    return data


def _unsmoothed_clip(
    artifact: Mapping[str, Any], interpolation: Mapping[str, Any] | None
) -> Path | None:
    """Comfy's (or StableNew's) own clip: the primary output, or when smoothed the output that is not the RIFE clip."""

    candidates = [
        str(item)
        for key in ("output_paths", "video_paths")
        for item in artifact.get(key) or ()
        if item
    ]
    primary = str(artifact.get("primary_path") or "")
    if interpolation is None:
        chosen = primary or next(iter(candidates), "")
        return Path(chosen) if chosen else None
    smoothed = [text for text in (primary, str(interpolation.get("video_path") or "")) if text]
    for candidate in candidates:
        if Path(candidate).suffix.lower() in _VIDEO_SUFFIXES and not any(
            _same_path(candidate, text) for text in smoothed
        ):
            return Path(candidate)
    return None


def _removed_by_retention(artifact: Mapping[str, Any], clip: Path) -> bool:
    paths = [Path(str(item)) for item in artifact.get("frame_paths") or () if item]
    return (
        clip.is_file()
        and bool(paths)
        and frames_were_removed(paths[0].parent)
        and not all(path.is_file() for path in paths)
    )


def _recorded_digest(job: _ClipJob, record: Mapping[str, Any]) -> tuple[str, list[str]]:
    """The backend's ``frame_sha256_digest`` and per-frame hashes (the manifest file holds the full record)."""

    per_frame = [str(item) for item in record.get("frame_sha256") or ()]
    digest = str(record.get("frame_sha256_digest") or "")
    if not digest and per_frame:
        digest = hashlib.sha256(",".join(per_frame).encode("ascii")).hexdigest()
    if not digest:
        raise StoryboardRootError(f"the backend recorded no frame hashes for job {job.job_id}")
    return digest, per_frame


def _frames_out_root(
    job: _ClipJob,
    artifact: Mapping[str, Any],
    backend: Mapping[str, Any],
    unsmoothed: Path | None,
    *,
    smoothed: bool,
    hash_file: FileHasher,
    cancel_token: CancelToken | None,
) -> CutManifest:
    paths = [str(path.resolve()) for path in natural_frame_order(artifact.get("frame_paths") or ())]
    missing = next(
        (number for number, path in enumerate(paths, 1) if not Path(path).is_file()), None
    )
    if not paths or missing is not None:
        if smoothed and (unsmoothed is None or not unsmoothed.is_file()):
            raise StoryboardRootError(SMOOTHED_ONLY)
        if missing is None:
            raise StoryboardRootError(f"Job {job.job_id} recorded no generated frames")
        raise _missing(paths[missing - 1], missing)
    record = backend.get("frames_out")
    if not isinstance(record, Mapping):
        raise StoryboardRootError(
            f"the backend manifest of job {job.job_id} has no frames_out record, so its frames cannot be checked"
        )
    if record.get("frame_count") != len(paths):
        raise StoryboardRootError(
            f"Job {job.job_id} lists {len(paths)} frames but the backend recorded {record.get('frame_count')}"
        )
    digest, per_frame = _recorded_digest(job, record)
    hashes: list[str] = []
    for number, path in enumerate(paths, start=1):
        _check_cancel(cancel_token)
        hashes.append(_hash(path, hash_file, number))
    if hashlib.sha256(",".join(hashes).encode("ascii")).hexdigest() != digest:
        where = next(
            (
                f"frame {number}: {path}"
                for number, (path, actual, wanted) in enumerate(
                    zip(paths, hashes, per_frame, strict=False), start=1
                )
                if actual != wanted
            ),
            str(Path(paths[0]).parent),
        )
        raise StoryboardRootError(
            f"the saved frames of job {job.job_id} do not match the hashes the backend recorded ({where})"
        )
    frames = tuple(CutFrame(path=path, sha256=sha) for path, sha in zip(paths, hashes, strict=True))
    return _root_manifest(
        frames, basis=BASIS_NATIVE, fps=job.fps, size=_png_size(paths[0]), job_id=job.job_id
    )


def _decoded_root(
    job: _ClipJob,
    clip: Path,
    staging: Path,
    folder: Path,
    *,
    decode_clip: ClipDecoder,
    hash_file: FileHasher,
    cancel_token: CancelToken | None,
) -> CutManifest:
    _check_cancel(cancel_token)
    try:
        decoded = decode_clip(clip, staging, cancel_token)
    except SequenceFrameError as exc:
        raise StoryboardRootError(f"Job {job.job_id}: {exc}") from exc
    expected = int(job.stage.get("frame_count") or 0)
    if not decoded or (expected and len(decoded) != expected):
        raise StoryboardRootError(
            f"decoding {clip.name} gave {len(decoded)} frames but the job generated {expected}; "
            "the decoded root is refused rather than trusted"
        )
    frames: list[CutFrame] = []
    for number, path in enumerate(decoded, start=1):
        _check_cancel(cancel_token)
        try:
            relative = Path(path).resolve().relative_to(staging.resolve())
        except ValueError as exc:
            raise StoryboardRootError(
                f"decoded frame {number} was written outside the root folder: {path}"
            ) from exc
        frames.append(
            CutFrame(path=str(folder / relative), sha256=_hash(str(path), hash_file, number))
        )
    return _root_manifest(
        tuple(frames),
        basis=BASIS_DECODED,
        fps=job.fps,
        size=_png_size(str(decoded[0])),
        job_id=job.job_id,
    )


# ----------------------------------------------------------------------------------------- entry points


def prepare_clip_root(
    *,
    repository: Any,
    job_id: str,
    storyboard_id: str,
    output_root: str | Path,
    registry: Any,
    hash_file: FileHasher = sha256_of,
    decode_clip: ClipDecoder = decode_clip_to_frames,
    cancel_token: CancelToken | None = None,
) -> PreparedRoot:
    """Turn the finished clip job ``job_id`` into storyboard ``storyboard_id``'s root (see the module docstring).

    Raises :class:`StoryboardRootError` with a readable reason (and ``CancellationError`` when cancelled); in either
    case nothing is left under ``<output_root>/storyboards/<storyboard_id>``.
    """

    folder = root_target(output_root, storyboard_id)
    output = Path(output_root).expanduser().resolve()
    job = _load_clip_job(repository, job_id, registry)
    settings = _clip_settings(job)
    smoothed_fps: int | None = None
    build: RootBuild
    if job.stage.get(PLAN_KEY):
        root_of = _take_root if _plan(job).storyboard is not None else _sequence_root

        def build_sequence(staging: Path, final: Path) -> CutManifest:
            return root_of(job, output, hash_file=hash_file, cancel_token=cancel_token)

        build = build_sequence
    else:
        artifact = _metadata(job.result).get("video_workflow_artifact")
        if not isinstance(artifact, Mapping):
            raise StoryboardRootError(f"Job {job_id} recorded no video workflow output")
        backend = _backend_manifest(job, artifact)
        interpolation = backend.get("interpolation")
        smoothing = interpolation if isinstance(interpolation, Mapping) else None
        if smoothing is not None:
            smoothed_fps = int(smoothing.get("output_fps") or 0)
        unsmoothed = _unsmoothed_clip(artifact, smoothing)
        if frames_output_fps(job.spec) is not None:

            def build_frames_out(staging: Path, final: Path) -> CutManifest:
                if unsmoothed is not None and _removed_by_retention(artifact, unsmoothed):
                    # VID-FRAME: the PNGs were removed after the clip was made; decode its own clip instead.
                    return _decoded_root(
                        job,
                        unsmoothed,
                        staging,
                        final,
                        decode_clip=decode_clip,
                        hash_file=hash_file,
                        cancel_token=cancel_token,
                    )
                return _frames_out_root(
                    job,
                    artifact,
                    backend,
                    unsmoothed,
                    smoothed=smoothing is not None,
                    hash_file=hash_file,
                    cancel_token=cancel_token,
                )

            build = build_frames_out
        else:
            if unsmoothed is None or not unsmoothed.is_file():
                if smoothing is not None:
                    raise StoryboardRootError(SMOOTHED_ONLY)
                raise StoryboardRootError(f"the clip of job {job_id} is missing: {unsmoothed}")
            clip = unsmoothed

            def build_decoded(staging: Path, final: Path) -> CutManifest:
                return _decoded_root(
                    job,
                    clip,
                    staging,
                    final,
                    decode_clip=decode_clip,
                    hash_file=hash_file,
                    cancel_token=cancel_token,
                )

            build = build_decoded
    pinned, manifest = publish_root(folder, build)
    return PreparedRoot(
        kind="clip",
        job_id=job_id,
        image_path=None,
        image_sha256=None,
        manifest=pinned,
        settings=settings,
        fps=job.fps,
        width=manifest.width,
        height=manifest.height,
        smoothing=None
        if smoothed_fps is None
        else SmoothingNote(
            smoothed_fps=smoothed_fps, fps=job.fps, frame_count=len(manifest.frames)
        ),
    )


def resolve_root_workflow(
    settings: Mapping[str, Any], registry: Any, *, subject: str
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    """The approved prompt-directed workflow an image or imported clip root makes its takes with.

    Returns ``(spec, frame-count policy, kept settings)``; only the settings a root inherits are kept and the
    experimental opt-in is never honoured here. A missing, unknown, experimental, disabled or non-sequence workflow
    is refused by name with the registry's own reasons."""

    workflow_id = str(settings.get("workflow_id") or "").strip()
    if not workflow_id:
        raise StoryboardRootError(f"{subject} needs a workflow to make its takes")
    version = str(settings.get("workflow_version") or "").strip() or None
    try:
        spec = registry.get(workflow_id, version)
    except KeyError as exc:
        raise StoryboardRootError(_lookup_text(exc)) from exc
    policy = frame_count_policy(spec)
    frame_count: Any = settings.get("frame_count")  # empty means the workflow's default
    problems = workflow_segment_errors(
        spec, spec, frame_count, 0 if policy is None else int(policy["fps"])
    )
    if problems or policy is None:
        raise StoryboardRootError(
            f"{workflow_id} cannot make storyboard takes: {'; '.join(dict.fromkeys(problems))}"
        )
    kept: dict[str, Any] = {
        "workflow_id": spec.workflow_id,
        "workflow_version": spec.workflow_version,
        "frame_count": parse_frame_count(spec, settings.get("frame_count")),
    }
    kept.update(
        {
            key: settings[key]
            for key in ("negative_prompt", "motion_profile", "output_route")
            if key in settings
        }
    )
    return spec, policy, kept


def prepare_image_root(
    *, image_path: str | Path, settings: Mapping[str, Any], registry: Any
) -> PreparedRoot:
    """A still image root: the operator's approved prompt-directed workflow and its settings, chosen once.

    Only :data:`ROOT_SETTING_KEYS` are kept; the experimental opt-in is never honoured here (a still root runs an
    approved workflow). The first takes have no lead-in, so nothing is written.
    """

    spec, policy, kept = resolve_root_workflow(
        settings, registry, subject="a storyboard from a still image"
    )
    path = Path(image_path).expanduser().resolve()
    try:
        width, height = read_still_size(path, label="the storyboard's still image")
    except SequencePlanError as exc:
        raise StoryboardRootError(str(exc)) from exc
    return PreparedRoot(
        kind="image",
        job_id=None,
        image_path=str(path),
        image_sha256=sha256_of(path),
        manifest=None,
        settings=kept,
        fps=int(policy["fps"]),
        width=width,
        height=height,
        smoothing=None,
    )


__all__ = [
    "ROOT_CUT_FILE_NAME",
    "ROOT_FOLDER",
    "ROOT_SETTING_KEYS",
    "SMOOTHED_ONLY",
    "STORYBOARDS_FOLDER",
    "PreparedRoot",
    "SmoothingNote",
    "RootBuild",
    "StoryboardRootError",
    "check_clip_job",
    "clip_last_frame",
    "recorded_clip_frames",
    "prepare_clip_root",
    "prepare_image_root",
    "publish_root",
    "resolve_root_workflow",
    "root_target",
]
