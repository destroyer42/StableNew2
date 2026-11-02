"""Explicit, bounded extraction of a motion-asset zip into a new empty folder (PR-VID-MOTION-354).

Never part of an inventory scan.  The destination must be absent or empty; every member name is validated before any byte is
written (no absolute or drive paths, ``..``, device names, alternate streams, links, duplicates); sizes are bounded both by
the declared header and by the bytes actually read (a header can lie); only motion-asset suffixes are extracted.  Any
violation aborts and removes exactly the files and folder this call created.  The archive itself is only opened for reading.
"""

from __future__ import annotations

import hashlib
import os
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_ENTRIES = 2_000
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_ENTRY_BYTES = 1024**3
MAX_COMPRESSION_RATIO = 200
CHUNK = 1024 * 1024
ALLOWED_SUFFIXES = (".fbx", ".bvh", ".asf", ".amc", ".mp4", ".mov", ".webm", ".mkv")
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_BAD_CHARS = set('<>:"|?*') | {chr(i) for i in range(32)}


class ArchiveRefused(ValueError):
    """The archive (or the destination) is unsafe or exceeds a limit; nothing is left behind."""


@dataclass(frozen=True, slots=True)
class ExtractedFile:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    destination: str
    files: tuple[ExtractedFile, ...]
    skipped_unsupported: int


def safe_member_path(name: str) -> PurePosixPath:
    """The validated relative path of a member, or ``ArchiveRefused``."""

    text = name.replace("\\", "/")
    if not text or text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise ArchiveRefused(f"Unsafe member path: {name!r}")
    parts = PurePosixPath(text).parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise ArchiveRefused(f"Unsafe member path: {name!r}")
    for part in parts:
        if any(c in _BAD_CHARS for c in part) or part.endswith((".", " ")):
            raise ArchiveRefused(f"Unsafe member name: {name!r}")
        if part.split(".")[0].lower() in _RESERVED:
            raise ArchiveRefused(f"Reserved device name in member path: {name!r}")
    return PurePosixPath(*parts)


def extract_archive(
    archive_path: str | Path, destination: str | Path, *, cancel: threading.Event | None = None
) -> ExtractionReport:
    source = Path(archive_path)
    target = Path(destination).expanduser().resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ArchiveRefused("Choose a new or empty folder to extract into.")
    created_dir = not target.exists()
    written: list[Path] = []
    try:
        with zipfile.ZipFile(source) as archive:
            infos = [i for i in archive.infolist() if not i.is_dir()]
            if len(infos) > MAX_ENTRIES:
                raise ArchiveRefused(f"The archive has more than {MAX_ENTRIES} files.")
            plan: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            seen: set[str] = set()
            total = 0
            skipped = 0
            for info in infos:
                relative = safe_member_path(info.filename)
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ArchiveRefused(f"Links are not extracted: {info.filename!r}")
                if info.flag_bits & 0x1:
                    raise ArchiveRefused("Encrypted archives are not supported.")
                key = relative.as_posix().lower()
                if key in seen:
                    raise ArchiveRefused(f"Duplicate member name: {info.filename!r}")
                seen.add(key)
                if relative.suffix.lower() not in ALLOWED_SUFFIXES:
                    skipped += 1
                    continue
                if info.file_size > MAX_ENTRY_BYTES:
                    raise ArchiveRefused(f"{info.filename!r} is larger than the per-file limit.")
                if (
                    info.compress_size
                    and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
                ):
                    raise ArchiveRefused(f"{info.filename!r} has an implausible compression ratio.")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ArchiveRefused("The archive expands beyond the total size limit.")
                plan.append((info, relative))
            target.mkdir(parents=True, exist_ok=True)
            files: list[ExtractedFile] = []
            budget = MAX_TOTAL_BYTES
            for info, relative in plan:
                if cancel is not None and cancel.is_set():
                    raise ArchiveRefused("Extraction was cancelled.")
                final = (target / Path(*relative.parts)).resolve()
                if target not in final.parents:
                    raise ArchiveRefused(f"Member escapes the destination: {info.filename!r}")
                final.parent.mkdir(parents=True, exist_ok=True)
                partial = final.with_name(final.name + ".partial")
                digest, size = hashlib.sha256(), 0
                written.append(partial)
                with archive.open(info) as reader, partial.open("wb") as out:
                    while True:
                        chunk = reader.read(CHUNK)
                        if not chunk:
                            break
                        size += len(chunk)
                        budget -= len(chunk)
                        if size > info.file_size or budget < 0:
                            raise ArchiveRefused(
                                f"{info.filename!r} expands beyond its declared size."
                            )
                        digest.update(chunk)
                        out.write(chunk)
                if size != info.file_size:
                    raise ArchiveRefused(f"{info.filename!r} is shorter than its declared size.")
                os.replace(partial, final)
                written[-1] = final
                files.append(ExtractedFile(relative.as_posix(), size, digest.hexdigest()))
            return ExtractionReport(str(target), tuple(files), skipped)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        _cleanup(written, target, created_dir)
        raise ArchiveRefused(f"The archive could not be extracted: {exc}") from exc
    except ArchiveRefused:
        _cleanup(written, target, created_dir)
        raise


def _cleanup(written: list[Path], target: Path, created_dir: bool) -> None:
    """Remove only what this call wrote (and the folder only if it created it and it is now empty of other content)."""

    for path in reversed(written):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    for path in sorted({p.parent for p in written}, key=lambda p: len(p.parts), reverse=True):
        try:
            if target in path.parents:
                path.rmdir()
        except OSError:
            pass
    if created_dir:
        try:
            target.rmdir()
        except OSError:
            pass
