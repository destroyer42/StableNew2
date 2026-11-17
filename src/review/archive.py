"""Reversible archive for Review's Discard (PR-REVIEW-ARCHIVE-623).

Discard moves an image into one central folder, ``<output root>/_archive/``, and Restore moves it back. Nothing here
deletes, overwrites or copies-then-removes a file: every move is a same-volume ``rename_without_replace`` followed by a
SHA-256 check, and every refusal leaves the file exactly where it was. There is no ledger and no store: the archive
path is a pure function of the original path (and the original path is derivable from the archive path), so any
reader can ask "was this archived?" by looking at the file system.

Location rule:

* a file under the output root keeps its relative path: ``_archive/<relative path>``;
* a file outside it goes to ``_archive/_external/<drive letter>/<path without the drive>`` (UNC paths under
  ``_external/_unc/<server>/<share>/...``, POSIX paths under ``_external/_posix/...``).

A different file already at the target keeps both: the incoming one is named ``<stem>.<first 8 of sha256><suffix>``. An
identical file already there leaves the source in place and says so. A ``<image>.review.json`` sidecar travels with its
image; manifests stay where they are.

Everything here is blocking file work: call it from a worker, never from Tk. Status text is safe to display (it never
contains prompt text or file names).
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import time
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.photo_optimize.paths import canonical_path, io_path, rename_without_replace
from src.state.output_routing import (
    ARCHIVE_DIR_NAME,
    get_output_root,
    is_photo_optimize_workspace,
)
from src.utils.image_metadata import build_review_sidecar_path

EXTERNAL_DIR = "_external"
UNC_DIR = "_unc"
POSIX_DIR = "_posix"

#: What readers say when a recorded file is absent but its archived copy exists.
ARCHIVED_MESSAGE = "archived by Review; Restore to use it"

# Refusal / failure codes (machine-readable; the matching text is in ``_REASONS``).
DIFFERENT_VOLUME = "different_volume"
QUEUED_JOB = "queued_job"
QUEUE_UNKNOWN = "queue_unknown"
PROTECTED_STORE = "protected_store"
LINK = "link"
ALREADY_ARCHIVED = "already_archived"
UNREADABLE = "unreadable"
MISSING = "missing"
NOT_A_FILE = "not_a_file"
TARGET_CONFLICT = "target_conflict"
OCCUPIED = "occupied"
CHANGED = "changed_during_move"
MOVE_FAILED = "move_failed"
NOT_ARCHIVED = "not_archived"

_REASONS = {
    DIFFERENT_VOLUME: "The archive is on a different drive than this file; it was not moved.",
    QUEUED_JOB: "A queued or running job uses this file as an input; it was not moved.",
    QUEUE_UNKNOWN: "The job queue could not be read, so this file was not moved.",
    PROTECTED_STORE: "This file belongs to Photo Optimize or Learning; it was not moved.",
    LINK: "The file or a folder on its path is a link or junction; it was not moved.",
    ALREADY_ARCHIVED: "This file is already in the archive.",
    UNREADABLE: "The file could not be read to verify it; it was not moved.",
    MISSING: "The file no longer exists at this location.",
    NOT_A_FILE: "This is not a regular file; it was not moved.",
    TARGET_CONFLICT: "A different file with the same name is already in the archive; it was not moved.",
    OCCUPIED: "A different file now exists at the original location.",
    CHANGED: "The file changed while it was being moved; the move was undone.",
    MOVE_FAILED: "The file could not be moved (it may be in use); it was left in place.",
    NOT_ARCHIVED: "This file is not in the archive.",
}

_RETRY_WINERRORS = frozenset({5, 32, 33})
_EXDEV_WINERROR = 17
_HASH_CHUNK = 1024 * 1024


def reason_text(code: str) -> str:
    return _REASONS.get(code, "The file was not moved.")


# -- paths ---------------------------------------------------------------------------------------------------------


def _abs(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.normpath(str(canonical_path(Path(path)))))


def _norm(path: Path | str) -> str:
    return os.path.normcase(str(path))


def _relative_parts(path: Path, root: Path) -> tuple[str, ...] | None:
    """``path`` below ``root`` (case-insensitive where the platform is), or ``None`` when it is not below it."""

    parts, base = path.parts, root.parts
    if len(parts) <= len(base):
        return None
    if tuple(_norm(part) for part in parts[: len(base)]) != tuple(_norm(part) for part in base):
        return None
    return tuple(parts[len(base) :])


def archive_root(output_root: str | os.PathLike[str]) -> Path:
    """``<output root>/_archive`` for an output root (already normalized by ``get_output_root``)."""

    return _abs(output_root) / ARCHIVE_DIR_NAME


def configured_output_root(config_manager: Any = None) -> Path:
    """The output root as the rest of the application resolves it (``output_dir`` setting, route folders stripped)."""

    configured = None
    getter = getattr(config_manager, "get_setting", None)
    if callable(getter):
        try:
            configured = getter("output_dir", None)
        except Exception:  # noqa: BLE001 - an unreadable setting only means the default root is used
            configured = None
    return _abs(get_output_root(configured or "output", create=False))


def is_under_archive(path: str | os.PathLike[str], output_root: str | os.PathLike[str]) -> bool:
    return _relative_parts(_abs(path), archive_root(output_root)) is not None


def _external_parts(path: Path) -> tuple[str, ...]:
    drive = path.drive
    rest = path.parts[1:]
    if drive.startswith("\\\\"):
        server, _, share = drive.lstrip("\\").partition("\\")
        return (UNC_DIR, server, share, *rest)
    if drive:
        return (drive.rstrip(":"), *rest)
    return (POSIX_DIR, *rest)


def mirror_target(path: str | os.PathLike[str], output_root: str | os.PathLike[str]) -> Path:
    """Where ``path`` lives in the archive when it is archived under its own name."""

    source, root = _abs(path), _abs(output_root)
    relative = _relative_parts(source, root)
    base = archive_root(root)
    if relative is not None:
        return base.joinpath(*relative)
    return base.joinpath(EXTERNAL_DIR, *_external_parts(source))


def original_of(
    archived: str | os.PathLike[str], output_root: str | os.PathLike[str]
) -> Path | None:
    """The original location an archive path stands for (``None`` when it is not inside the archive)."""

    relative = _relative_parts(_abs(archived), archive_root(output_root))
    if relative is None:
        return None
    if relative[0] != EXTERNAL_DIR:
        return _abs(output_root).joinpath(*relative)
    rest = relative[1:]
    if not rest:
        return None
    if rest[0] == UNC_DIR and len(rest) >= 3:
        return Path("\\\\" + "\\".join(rest[1:]))
    if rest[0] == POSIX_DIR:
        return Path(os.sep + os.sep.join(rest[1:]))
    if len(rest[0]) == 1:
        return Path(f"{rest[0]}:{os.sep}").joinpath(*rest[1:])
    return None


def _suffixed(target: Path, digest: str) -> Path:
    return target.with_name(f"{target.stem}.{digest[:8]}{target.suffix}")


# -- file facts ----------------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(io_path(path), "rb") as stream:
            while chunk := stream.read(_HASH_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _is_link(path: Path) -> bool:
    """A symbolic link, junction or any other reparse point (never followed)."""

    try:
        info = os.lstat(io_path(path))
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _is_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(io_path(path)).st_mode)
    except OSError:
        return False


def _exists(path: Path) -> bool:
    try:
        os.lstat(io_path(path))
    except OSError:
        return False
    return True


def _volume_of(path: Path) -> object:
    """Identity of the volume holding ``path`` (or its nearest existing ancestor)."""

    probe = path
    while True:
        try:
            return os.stat(io_path(probe)).st_dev
        except OSError:
            if probe.parent == probe:
                return None
            probe = probe.parent


def _chain(path: Path, top: Path) -> Iterator[Path]:
    """``top`` and every folder below it down to ``path`` itself (``path`` must be at or below ``top``)."""

    relative = _relative_parts(path, top) or ()
    current = top
    yield current
    for part in relative:
        current = current / part
        yield current


def _link_on_path(path: Path, top: Path | None) -> bool:
    """A link anywhere from ``top`` (inclusive) to ``path``; with no ``top``, every ancestor up to the anchor."""

    if top is None:
        candidates = [path, *path.parents]
    else:
        candidates = list(_chain(path, top))
    return any(_is_link(candidate) for candidate in candidates)


# -- queue ---------------------------------------------------------------------------------------------------------


def _job_record(job: Any) -> Any:
    record = getattr(job, "_normalized_record", None)
    if record is not None:
        return record
    snapshot = getattr(job, "snapshot", None) or getattr(job, "config_snapshot", None)
    if isinstance(snapshot, dict):
        from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

        return normalized_job_from_snapshot(snapshot)
    return None


def job_queue_of(controller: Any) -> Any:
    """The controller's job queue (the authority that knows queued and running jobs), or ``None`` when absent."""

    for source in (controller, getattr(controller, "pipeline_controller", None)):
        job_service = getattr(source, "job_service", None)
        getter = getattr(source, "get_job_service", None)
        if job_service is None and callable(getter):
            try:
                job_service = getter()
            except Exception:  # noqa: BLE001 - "no queue found" is handled by the caller (it refuses the move)
                job_service = None
        queue = getattr(job_service, "job_queue", None)
        if queue is not None:
            return queue
    return None


def active_input_paths(job_queue: Any) -> set[str]:
    """Normalized paths of every file a queued or running job froze as an input (raises when it cannot tell)."""

    from src.pipeline.replay_input_verification import frozen_input_checks

    found: set[str] = set()
    for job in job_queue.list_active_jobs_ordered():
        record = _job_record(job)
        if record is None:
            raise ValueError("an active job has no readable record")
        for check in frozen_input_checks(record):
            found.add(_norm(_abs(check.path)))
        for path in getattr(record, "input_image_paths", ()) or ():
            found.add(_norm(_abs(str(path))))
    return found


# -- planning ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArchivePlan:
    """What ``apply_archive`` would do; building one never writes anything."""

    source: Path
    digest: str = ""
    target: Path | None = None
    refusal: str = ""
    #: An identical file is already at the target: the source stays and the duplicate is reported.
    duplicate: bool = False
    #: The target carries the digest suffix because a different file holds the plain name.
    renamed: bool = False
    #: The archive root the target lives under (folders are created below it, never above it).
    base: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.refusal

    @property
    def reason(self) -> str:
        return reason_text(self.refusal) if self.refusal else ""


@dataclass(frozen=True)
class ArchiveOutcome:
    """The result of a move. ``status`` is ``moved``, ``duplicate``, ``refused``, ``failed`` or ``noop``."""

    status: str
    source: Path
    target: Path | None = None
    digest: str = ""
    code: str = ""
    message: str = ""
    sidecar_moved: bool = False
    #: Restore only: a free name the operator may accept when the original location is taken.
    alternative: Path | None = None

    @property
    def moved(self) -> bool:
        return self.status == "moved"


def _refused(plan: ArchivePlan, code: str, digest: str = "") -> ArchivePlan:
    return ArchivePlan(plan.source, digest or plan.digest, None, refusal=code, base=plan.base)


def default_protected_roots() -> tuple[Path, ...]:
    from src.learning.learning_paths import get_discovered_experiments_root

    return (_abs(get_discovered_experiments_root(create=False)),)


def plan_archive(
    source: str | os.PathLike[str],
    *,
    output_root: str | os.PathLike[str],
    active_inputs: Callable[[], Collection[str]] | None = None,
    protected_roots: Collection[Path] | None = None,
    volume_of: Callable[[Path], object] = _volume_of,
    sha256: Callable[[Path], str | None] = _sha256,
) -> ArchivePlan:
    """Decide where ``source`` would go, or why it must stay (read-only: the file is hashed, never touched)."""

    path, root = _abs(source), _abs(output_root)
    base = archive_root(root)
    plan = ArchivePlan(path, base=base)
    if _relative_parts(path, base) is not None:
        return _refused(plan, ALREADY_ARCHIVED)
    roots = default_protected_roots() if protected_roots is None else protected_roots
    if is_photo_optimize_workspace(path) or any(
        _relative_parts(path, _abs(item)) is not None for item in roots
    ):
        return _refused(plan, PROTECTED_STORE)
    if not _exists(path):
        found = archived_location(path, output_root=root)
        return _refused(plan, ALREADY_ARCHIVED if found is not None else MISSING)
    if _is_link(path) or not _is_file(path):
        return _refused(plan, LINK if _is_link(path) else NOT_A_FILE)
    inside = _relative_parts(path, root) is not None
    if _link_on_path(path.parent, root if inside else None) or _link_on_path(base, root):
        return _refused(plan, LINK)
    if volume_of(path) != volume_of(base):
        return _refused(plan, DIFFERENT_VOLUME)
    if active_inputs is not None:
        try:
            busy = _norm(path) in {_norm(item) for item in active_inputs()}
        except Exception:  # noqa: BLE001 - an unreadable queue must not let a possibly-used file move
            return _refused(plan, QUEUE_UNKNOWN)
        if busy:
            return _refused(plan, QUEUED_JOB)
    digest = sha256(path)
    if not digest:
        return _refused(plan, UNREADABLE)
    target = mirror_target(path, root)
    if _link_on_path(target.parent, base):
        return _refused(plan, LINK, digest)
    renamed = False
    if _exists(target):
        if sha256(target) == digest:
            return ArchivePlan(path, digest, target, duplicate=True, base=base)
        target, renamed = _suffixed(target, digest), True
        if _exists(target):
            if sha256(target) == digest:
                return ArchivePlan(path, digest, target, duplicate=True, renamed=True, base=base)
            return _refused(plan, TARGET_CONFLICT, digest)
    return ArchivePlan(path, digest, target, renamed=renamed, base=base)


def archived_location(
    original: str | os.PathLike[str],
    *,
    output_root: str | os.PathLike[str] | None = None,
    digest: str | None = None,
) -> Path | None:
    """The archived copy of ``original`` when one exists, else ``None`` (read-only; never reads the file's bytes).

    With ``output_root`` the archive is that root's. Without it every ancestor of ``original`` that has an
    ``_archive`` folder is tried, so a reader that only knows a recorded path still finds its archive. With a
    ``digest`` the digest-suffixed name (used when two different files share a path) is looked for too.
    """

    path = _abs(original)
    if output_root is not None:
        roots = [_abs(output_root)]
    else:
        roots = [parent for parent in path.parents if (parent / ARCHIVE_DIR_NAME).is_dir()]
    for root in roots:
        target = mirror_target(path, root)
        if _is_file(target) and (not digest or _sha256(target) == digest):
            return target
        if digest:
            alternate = _suffixed(target, digest)
            if _is_file(alternate):
                return alternate
    return None


def archived_reason(original: str | os.PathLike[str] | None) -> str | None:
    """``ARCHIVED_MESSAGE`` when ``original`` is absent and its archived copy exists, else ``None`` (for readers)."""

    if not original or not str(original).strip():
        return None
    try:
        if _exists(_abs(original)):
            return None
        return ARCHIVED_MESSAGE if archived_location(original) is not None else None
    except (OSError, ValueError):
        return None


# -- applying ------------------------------------------------------------------------------------------------------


def _is_exdev(error: OSError) -> bool:
    return error.errno == errno.EXDEV or getattr(error, "winerror", None) == _EXDEV_WINERROR


def _ensure_dirs(top: Path, parent: Path) -> None:
    """Create ``parent`` (and missing ancestors) below ``top``, refusing a link at any level."""

    for folder in _chain(parent, top):
        if _is_link(folder):
            raise PermissionError(errno.EPERM, "link in archive path")
    os.makedirs(io_path(parent), exist_ok=True)
    for folder in _chain(parent, top):
        if _is_link(folder):
            raise PermissionError(errno.EPERM, "link in archive path")


def _rename(
    source: Path,
    target: Path,
    rename: Callable[[Path, Path], None],
    sleep: Callable[[float], None],
) -> None:
    """One no-replace rename, retried a few times for the transient errors a file in use raises on Windows."""

    for attempt in range(3):
        try:
            rename(source, target)
            return
        except OSError as error:
            transient = getattr(error, "winerror", None) in _RETRY_WINERRORS
            if not transient or attempt == 2:
                raise
            sleep(0.1)


def _move(
    source: Path,
    target: Path,
    digest: str,
    *,
    top: Path | None,
    rename: Callable[[Path, Path], None],
    sha256: Callable[[Path], str | None],
    sleep: Callable[[float], None],
) -> tuple[str, str]:
    """Move one file; returns ``("moved", "")`` or ``(status, code)`` with the file untouched or put back."""

    try:
        if top is not None:
            _ensure_dirs(top, target.parent)
        else:
            os.makedirs(io_path(target.parent), exist_ok=True)
    except OSError:
        return "failed", MOVE_FAILED
    try:
        _rename(source, target, rename, sleep)
    except FileExistsError:
        return "refused", TARGET_CONFLICT
    except FileNotFoundError:
        return "failed", MISSING
    except OSError as error:
        return ("refused", DIFFERENT_VOLUME) if _is_exdev(error) else ("failed", MOVE_FAILED)
    if sha256(target) == digest:
        return "moved", ""
    try:
        rename(target, source)
    except OSError:
        return "failed", CHANGED  # both copies are reported by location; nothing is removed
    return "failed", CHANGED


def _move_sidecar(
    source: Path,
    target: Path,
    rename: Callable[[Path, Path], None],
    sleep: Callable[[float], None],
) -> bool:
    """Carry ``<image>.review.json`` along; a sidecar that cannot move stays where it is (never replaced)."""

    old, new = build_review_sidecar_path(source), build_review_sidecar_path(target)
    if not _is_file(old) or _exists(new):
        return False
    try:
        _rename(old, new, rename, sleep)
    except OSError:
        return False
    return True


def apply_archive(
    plan: ArchivePlan,
    *,
    rename: Callable[[Path, Path], None] = rename_without_replace,
    sha256: Callable[[Path], str | None] = _sha256,
    sleep: Callable[[float], None] = time.sleep,
) -> ArchiveOutcome:
    """Carry out a plan. The file ends either at its archive path (verified) or exactly where it was."""

    if plan.refusal:
        return ArchiveOutcome("refused", plan.source, None, plan.digest, plan.refusal, plan.reason)
    assert plan.target is not None
    if plan.duplicate:
        return ArchiveOutcome(
            "duplicate",
            plan.source,
            plan.target,
            plan.digest,
            message="An identical file is already in the archive; this one was left in place.",
        )
    status, code = _move(
        plan.source,
        plan.target,
        plan.digest,
        top=plan.base,
        rename=rename,
        sha256=sha256,
        sleep=sleep,
    )
    if status != "moved":
        return ArchiveOutcome(
            status, plan.source, plan.target, plan.digest, code, reason_text(code)
        )
    carried = _move_sidecar(plan.source, plan.target, rename, sleep)
    return ArchiveOutcome("moved", plan.source, plan.target, plan.digest, sidecar_moved=carried)


# -- restoring -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RestorePlan:
    """Where an archived image would go back to; building one never writes anything."""

    original: Path
    archived: Path | None = None
    digest: str = ""
    refusal: str = ""
    #: The original path already holds an identical file: nothing to move, the archived copy is left in place.
    duplicate: bool = False
    #: The original path is back already (nothing archived): nothing to do.
    in_place: bool = False
    alternative: Path | None = None

    @property
    def reason(self) -> str:
        return reason_text(self.refusal) if self.refusal else ""


def free_name(original: Path, digest: str) -> Path:
    """A name next to ``original`` that does not exist yet (``<stem>.restored-<8 of sha256><suffix>``)."""

    candidate = original.with_name(f"{original.stem}.restored-{digest[:8]}{original.suffix}")
    index = 2
    while _exists(candidate):
        candidate = original.with_name(
            f"{original.stem}.restored-{digest[:8]}-{index}{original.suffix}"
        )
        index += 1
    return candidate


def plan_restore(
    original: str | os.PathLike[str],
    *,
    output_root: str | os.PathLike[str],
    digest: str | None = None,
    volume_of: Callable[[Path], object] = _volume_of,
    sha256: Callable[[Path], str | None] = _sha256,
) -> RestorePlan:
    """Where the archived copy of ``original`` would be put back (read-only)."""

    path, root = _abs(original), _abs(output_root)
    archived = archived_location(path, output_root=root, digest=digest)
    if archived is None:
        if _exists(path):
            return RestorePlan(path, in_place=True)
        return RestorePlan(path, refusal=MISSING)
    actual = sha256(archived)
    if not actual:
        return RestorePlan(path, archived, refusal=UNREADABLE)
    if _link_on_path(archived.parent, archive_root(root)) or _link_on_path(
        path.parent, root if _relative_parts(path, root) is not None else None
    ):
        return RestorePlan(path, archived, actual, refusal=LINK)
    if volume_of(archived) != volume_of(path.parent):
        return RestorePlan(path, archived, actual, refusal=DIFFERENT_VOLUME)
    if _exists(path):
        if sha256(path) == actual:
            return RestorePlan(path, archived, actual, duplicate=True)
        return RestorePlan(
            path, archived, actual, refusal=OCCUPIED, alternative=free_name(path, actual)
        )
    return RestorePlan(path, archived, actual)


def apply_restore(
    plan: RestorePlan,
    *,
    use_alternative: bool = False,
    rename: Callable[[Path, Path], None] = rename_without_replace,
    sha256: Callable[[Path], str | None] = _sha256,
    sleep: Callable[[float], None] = time.sleep,
) -> ArchiveOutcome:
    """Put the archived file back, never replacing anything. ``use_alternative`` takes the offered free name."""

    if plan.in_place:
        return ArchiveOutcome("noop", plan.original, plan.original)
    if plan.duplicate:
        return ArchiveOutcome(
            "duplicate",
            plan.original,
            plan.archived,
            plan.digest,
            message="An identical file is already at the original location; the archived copy was kept.",
        )
    occupied = plan.refusal == OCCUPIED
    if plan.refusal and not (occupied and use_alternative and plan.alternative is not None):
        return ArchiveOutcome(
            "refused",
            plan.original,
            plan.archived,
            plan.digest,
            plan.refusal,
            plan.reason,
            alternative=plan.alternative,
        )
    assert plan.archived is not None
    target = plan.alternative if occupied else plan.original
    assert target is not None
    status, code = _move(
        plan.archived,
        target,
        plan.digest,
        top=None,
        rename=rename,
        sha256=sha256,
        sleep=sleep,
    )
    if code == TARGET_CONFLICT:
        code = OCCUPIED
    if status != "moved":
        return ArchiveOutcome(
            status, plan.original, plan.archived, plan.digest, code, reason_text(code)
        )
    carried = _move_sidecar(plan.archived, target, rename, sleep)
    return ArchiveOutcome("moved", plan.original, target, plan.digest, sidecar_moved=carried)


def archive_file(
    source: str | os.PathLike[str],
    *,
    output_root: str | os.PathLike[str],
    active_inputs: Callable[[], Collection[str]] | None = None,
    protected_roots: Collection[Path] | None = None,
) -> ArchiveOutcome:
    """Plan and apply in one call (the worker's entry point)."""

    return apply_archive(
        plan_archive(
            source,
            output_root=output_root,
            active_inputs=active_inputs,
            protected_roots=protected_roots,
        )
    )


def restore_file(
    original: str | os.PathLike[str],
    *,
    output_root: str | os.PathLike[str],
    digest: str | None = None,
    use_alternative: bool = False,
) -> ArchiveOutcome:
    return apply_restore(
        plan_restore(original, output_root=output_root, digest=digest),
        use_alternative=use_alternative,
    )


__all__ = [
    "ARCHIVED_MESSAGE",
    "ArchiveOutcome",
    "ArchivePlan",
    "RestorePlan",
    "active_input_paths",
    "apply_archive",
    "apply_restore",
    "archive_file",
    "archive_root",
    "archived_location",
    "archived_reason",
    "configured_output_root",
    "free_name",
    "is_under_archive",
    "job_queue_of",
    "mirror_target",
    "original_of",
    "plan_archive",
    "plan_restore",
    "reason_text",
    "restore_file",
]
