"""Import local videos and completed StableNew clips into the Motion Library (PR-VID-MOTION-LIB-353).

Every entry point is an explicit operator action and none of them can queue work: they read one file (or
one selected folder, non-recursively), hash it in bounded chunks, inspect it with the existing bounded
FFprobe/FFmpeg helpers, and add a catalog record.  The original is only ever opened for reading; a
managed copy is made only when the operator asks for one.

Outcomes are values, not exceptions: a bad file produces a ``failed`` outcome with a reason and the
next file is still attempted.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.video.driving_video_inspection import (
    STATUS_FAILED,
    DrivingVideoInspection,
    inspect_driving_video,
)
from src.video.motion_library.hashing import HashCancelled, sha256_file
from src.video.motion_library.models import (
    ANNOTATION_FIELDS,
    LOCATOR_LINKED,
    LOCATOR_MANAGED,
    LOCATOR_MODES,
    SOURCE_STABLENEW_GENERATED,
    AssetLocator,
    GeneratedOrigin,
    MotionAsset,
    clean_text,
    utc_now_iso,
)
from src.video.motion_library.store import (
    DuplicateAssetError,
    LibraryError,
    MotionLibraryStore,
    SourceChangedError,
)
from src.video.recent_video_outputs import recent_output_from_entry
from src.video.video_artifact_helpers import video_bundle_from_result

#: Same set the Video Workflow accepts for a driving clip (checked by a test against the NJR builder).
SUPPORTED_SUFFIXES = frozenset({".mp4", ".webm", ".mov", ".mkv"})
#: Video containers that are recognised and refused with a reason, rather than silently ignored.
KNOWN_UNSUPPORTED_SUFFIXES = frozenset(
    {".avi", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".gif"}
)
MAX_FOLDER_FILES = 200

OUTCOME_IMPORTED = "imported"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_FAILED = "failed"

Inspector = Callable[[Path, threading.Event | None], DrivingVideoInspection]


def _default_inspector(path: Path, cancel: threading.Event | None) -> DrivingVideoInspection:
    return inspect_driving_video(path, cancel=cancel)


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    path: str
    status: str
    asset_id: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status != OUTCOME_FAILED


@dataclass(frozen=True, slots=True)
class FolderImportReport:
    folder: str
    outcomes: tuple[ImportOutcome, ...]
    ignored_non_video: int = 0
    truncated: bool = False
    cancelled: bool = False

    @property
    def imported(self) -> int:
        return sum(1 for o in self.outcomes if o.status == OUTCOME_IMPORTED)

    @property
    def duplicates(self) -> int:
        return sum(1 for o in self.outcomes if o.status == OUTCOME_DUPLICATE)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == OUTCOME_FAILED)

    def summary(self) -> str:
        parts = [
            f"{self.imported} imported",
            f"{self.duplicates} already present",
            f"{self.failed} failed",
        ]
        if self.ignored_non_video:
            parts.append(f"{self.ignored_non_video} non-video file(s) ignored")
        if self.truncated:
            parts.append(f"stopped after {MAX_FOLDER_FILES} files")
        if self.cancelled:
            parts.append("cancelled")
        return ", ".join(parts) + "."


def _failed(path: str | Path, reason: str) -> ImportOutcome:
    return ImportOutcome(path=str(path), status=OUTCOME_FAILED, reason=reason)


def _annotations(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    values = dict(raw or {})
    unknown = sorted(set(values) - set(ANNOTATION_FIELDS))
    if unknown:
        raise ValueError(f"Unknown annotation field(s): {', '.join(unknown)}.")
    return {name: ANNOTATION_FIELDS[name](value) for name, value in values.items()}


def _inspection_reason(inspection: DrivingVideoInspection) -> str:
    if inspection.issues:
        return inspection.issues[0].message
    return "The video could not be inspected."


def import_video(
    store: MotionLibraryStore,
    path: str | Path,
    *,
    mode: str = LOCATOR_LINKED,
    annotations: Mapping[str, Any] | None = None,
    origin: GeneratedOrigin | None = None,
    inspect: Inspector = _default_inspector,
    cancel: threading.Event | None = None,
    clock: Callable[[], str] = utc_now_iso,
) -> ImportOutcome:
    """Add one video.  ``mode`` ``linked`` references the file where it is; ``managed`` also copies it
    into the library after the copy hashes to the verified SHA-256."""

    text = str(path or "").strip()
    if not text:
        return _failed("", "No video file was chosen.")
    if mode not in LOCATOR_MODES:
        return _failed(text, "Unknown import mode.")
    try:
        edits = _annotations(annotations)
    except ValueError as exc:
        return _failed(text, str(exc))
    try:
        source = Path(text).expanduser()
        suffix = source.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            allowed = ", ".join(sorted(SUPPORTED_SUFFIXES))
            return _failed(
                source, f"Unsupported video format '{suffix or 'none'}'. Supported: {allowed}."
            )
        if not source.is_file():
            return _failed(source, "The file does not exist.")
        source = source.resolve()
        before = source.stat()
        digest = sha256_file(source, cancel)
        after = source.stat()
    except HashCancelled:
        return _failed(text, "Import was cancelled.")
    except OSError as exc:
        return _failed(text, f"The file cannot be read: {exc}")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return _failed(
            source, "The file changed while it was being read; try again when it is settled."
        )

    existing = store.find_by_sha(digest)
    if existing is not None:
        return _record_duplicate(store, existing, source, edits, origin)

    inspection = inspect(source, cancel)
    if inspection.status == STATUS_FAILED or inspection.facts is None:
        return _failed(source, _inspection_reason(inspection))
    facts = inspection.facts
    thumbnail = ""
    frames = inspection.frames
    if frames:
        chosen = frames[1] if len(frames) > 1 else frames[0]
        try:
            thumbnail = store.store_thumbnail(digest, chosen.png_bytes)
        except OSError:
            thumbnail = ""  # a missing thumbnail never blocks an import

    managed_name = ""
    try:
        if mode == LOCATOR_MANAGED:
            managed_name, size, mtime_ns = store.copy_into_managed(
                source, expected_sha256=digest, suffix=suffix, cancel=cancel
            )
            locator = AssetLocator(LOCATOR_MANAGED, managed_name, size, mtime_ns)
        else:
            locator = AssetLocator(LOCATOR_LINKED, str(source), after.st_size, after.st_mtime_ns)
        fields: dict[str, Any] = {
            "display_name": clean_text(source.stem, 120) or digest[:12],
            "source_reference": source.name,
        }
        if origin is not None:
            fields["source_category"] = SOURCE_STABLENEW_GENERATED
        fields.update(edits)
        asset = MotionAsset(
            asset_id=store.new_id(),
            sha256=digest,
            locator=locator,
            duration_seconds=facts.duration_seconds,
            width=facts.display_width,
            height=facts.display_height,
            fps=facts.reported_fps,
            frame_count=facts.frame_count,
            thumbnail=thumbnail,
            imported_at=clock(),
            origin=origin,
            **fields,
        )
        store.add(asset)
    except DuplicateAssetError as exc:
        _discard_new_copy(store, managed_name)
        existing = store.get(exc.existing_id)
        if existing is not None:
            return _record_duplicate(store, existing, source, edits, origin)
        return _failed(source, "These bytes are already in the library.")
    except HashCancelled:
        _discard_new_copy(store, managed_name)
        return _failed(source, "Import was cancelled.")
    except SourceChangedError as exc:
        return _failed(source, str(exc))
    except (LibraryError, OSError) as exc:
        _discard_new_copy(store, managed_name)
        return _failed(source, f"The library could not be updated: {exc}")
    return ImportOutcome(path=str(source), status=OUTCOME_IMPORTED, asset_id=asset.asset_id)


def _discard_new_copy(store: MotionLibraryStore, name: str) -> None:
    """Remove a managed copy this import created when its catalog record was never written."""

    if not name or any(a.locator.path == name for a in store.assets()):
        return
    try:
        (store.managed_dir / name).unlink()
    except OSError:
        pass


def _record_duplicate(
    store: MotionLibraryStore,
    existing: MotionAsset,
    source: Path,
    edits: Mapping[str, Any],
    origin: GeneratedOrigin | None = None,
) -> ImportOutcome:
    try:
        store.record_duplicate(
            existing.asset_id,
            path=str(source),
            name=source.stem,
            source_reference=str(edits.get("source_reference") or source.name),
            tags=edits.get("tags") or (),
        )
        if origin is not None:
            store.attach_origin(existing.asset_id, origin)
    except (LibraryError, OSError) as exc:
        return _failed(source, f"Already in the library, but the alias could not be saved: {exc}")
    return ImportOutcome(
        path=str(source),
        status=OUTCOME_DUPLICATE,
        asset_id=existing.asset_id,
        reason=f"Same bytes as '{existing.display_name}'; the extra path and tags were kept on it.",
    )


def import_folder(
    store: MotionLibraryStore,
    folder: str | Path,
    *,
    mode: str = LOCATOR_LINKED,
    annotations: Mapping[str, Any] | None = None,
    max_files: int = MAX_FOLDER_FILES,
    inspect: Inspector = _default_inspector,
    cancel: threading.Event | None = None,
    on_progress: Callable[[ImportOutcome], None] | None = None,
) -> FolderImportReport:
    """Import the video files directly inside ``folder`` (never its sub-folders, never symbolic links)."""

    root = Path(str(folder or "")).expanduser()
    try:
        with os.scandir(root) as listing:
            entries = sorted(listing, key=lambda e: e.name.lower())
    except OSError as exc:
        return FolderImportReport(str(root), (_failed(root, f"The folder cannot be read: {exc}"),))
    # A per-file display name would be wrong for a batch; the file stem is used for each.
    shared = {k: v for k, v in dict(annotations or {}).items() if k != "display_name"}
    outcomes: list[ImportOutcome] = []
    ignored = 0
    truncated = False
    cancelled = False
    attempted = 0

    def record(outcome: ImportOutcome) -> None:
        outcomes.append(outcome)
        if on_progress is not None:
            on_progress(outcome)

    for entry in entries:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        suffix = Path(entry.name).suffix.lower()
        try:
            is_link = entry.is_symlink()
            is_file = entry.is_file(follow_symlinks=False)
        except OSError:
            continue
        if entry.name.startswith(".") or (not is_file and not is_link):
            ignored += 1
            continue
        if suffix not in SUPPORTED_SUFFIXES and suffix not in KNOWN_UNSUPPORTED_SUFFIXES:
            ignored += 1
            continue
        if is_link:
            record(_failed(entry.path, "Symbolic links are not followed; choose the real file."))
            continue
        if suffix in KNOWN_UNSUPPORTED_SUFFIXES:
            record(
                _failed(
                    entry.path,
                    f"Unsupported video format '{suffix}'. Convert it to .mp4 first "
                    "(see the Motion Library guide).",
                )
            )
            continue
        if attempted >= max_files:
            truncated = True
            break
        attempted += 1
        record(
            import_video(
                store, entry.path, mode=mode, annotations=shared, inspect=inspect, cancel=cancel
            )
        )
    return FolderImportReport(str(root), tuple(outcomes), ignored, truncated, cancelled)


# --- completed StableNew clips ------------------------------------------------------------------


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _history_video_path(bundle: Mapping[str, Any]) -> tuple[str | None, str]:
    """The one recorded video of a job, or a reason.  Several distinct candidates without a named
    primary are ambiguous and are refused rather than guessed."""

    primary = str(bundle.get("primary_path") or "").strip()
    if primary:
        candidates = [primary]
    else:
        listed = bundle.get("video_paths")
        candidates = [str(p) for p in listed if p] if isinstance(listed, list) else []
        candidates = list(dict.fromkeys(candidates))
    if not candidates:
        if bundle.get("frame_paths"):
            return None, "The job exported a frame sequence, not a video file."
        return None, "The job recorded no video output."
    if len(candidates) > 1:
        return (
            None,
            "The job recorded several videos and none is named primary; choose the file by import.",
        )
    suffix = Path(candidates[0]).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return (
            None,
            f"The recorded output is not a supported video file ({suffix or 'no extension'}).",
        )
    return candidates[0], ""


def import_history_video(
    store: MotionLibraryStore,
    entry: JobHistoryEntry | None,
    *,
    mode: str = LOCATOR_LINKED,
    annotations: Mapping[str, Any] | None = None,
    motion_label: str = "",
    motion_achieved: bool | None = None,
    good_for_motion: bool | None = None,
    known_artifacts: str = "",
    reuse_conditions: str = "",
    inspect: Inspector = _default_inspector,
    cancel: threading.Event | None = None,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> ImportOutcome:
    """Keep the recorded video of one *completed* job as a motion reference (explicit action only).

    The canonical history entry is re-read here, the recorded artifact is verified on disk and hashed, and
    the job id plus the frozen generation facts are kept as provenance.  It is a reference, not a replay and
    not a copy of job history."""

    if entry is None:
        return _failed("", "That job was not found in History.")
    label = f"job {entry.job_id}"
    if entry.status is not JobStatus.COMPLETED:
        return _failed(label, "Only a completed job can be added to the Motion Library.")
    result = entry.result if isinstance(entry.result, dict) else {}
    if result.get("error"):
        return _failed(label, "The job recorded an error, so its output is not offered.")
    bundle = video_bundle_from_result(result)
    if bundle is None:
        return _failed(label, "The job recorded no video output.")
    path, reason = _history_video_path(bundle)
    if path is None:
        return _failed(label, reason)
    try:
        present = is_file(path)
    except (OSError, ValueError):
        present = False
    if not present:
        return _failed(label, "The recorded video file is missing or was moved.")
    recent = recent_output_from_entry(entry, is_file=is_file)
    if recent is None:
        return _failed(label, "The job's recorded video could not be read.")

    snapshot = _mapping(entry.snapshot)
    workload = _mapping(_mapping(_mapping(snapshot.get("normalized_job"))).get("workload"))
    block = _mapping(_mapping(workload.get("config")).get("video_workflow"))
    subject = _mapping(recent.visibility_subject)
    try:
        digest = sha256_file(path, cancel)
    except HashCancelled:
        return _failed(label, "Import was cancelled.")
    except OSError as exc:
        return _failed(label, f"The recorded video cannot be read: {exc}")
    recorded_sha = str(bundle.get("sha256") or "").lower()
    if recorded_sha and recorded_sha != digest:
        return _failed(label, "The recorded video no longer matches the SHA-256 the job recorded.")
    origin = GeneratedOrigin(
        job_id=entry.job_id,
        artifact_path=str(path),
        artifact_sha256=digest,
        workflow_id=clean_text(block.get("workflow_id"), 120),
        workflow_version=clean_text(block.get("workflow_version"), 60),
        backend_id=recent.backend_id,
        seed=recent.seed,
        source_image_path=recent.source_image_path,
        source_image_sha256=str(
            _mapping(block.get("source_preparation")).get("original_sha256") or ""
        ),
        prompt=str(subject.get("prompt") or ""),
        negative_prompt=str(subject.get("negative_prompt") or ""),
        motion_label=clean_text(motion_label, 120),
        motion_achieved=motion_achieved,
        known_artifacts=known_artifacts,
        reuse_conditions=reuse_conditions,
    )
    fields: dict[str, Any] = {
        "source_category": SOURCE_STABLENEW_GENERATED,
        "source_reference": f"StableNew job {entry.job_id}",
        "display_name": clean_text(motion_label, 120) or Path(path).stem,
    }
    if good_for_motion is not None:
        fields["good_for_motion"] = good_for_motion
    fields.update(dict(annotations or {}))
    return import_video(
        store,
        path,
        mode=mode,
        annotations=fields,
        origin=origin,
        inspect=inspect,
        cancel=cancel,
    )


__all__ = [
    "KNOWN_UNSUPPORTED_SUFFIXES",
    "MAX_FOLDER_FILES",
    "OUTCOME_DUPLICATE",
    "OUTCOME_FAILED",
    "OUTCOME_IMPORTED",
    "SUPPORTED_SUFFIXES",
    "FolderImportReport",
    "ImportOutcome",
    "import_folder",
    "import_history_video",
    "import_video",
]
