"""Read-only inventory of downloaded motion assets (PR-VID-MOTION-354).

Scans one explicitly chosen folder tree, never writes inside it, never extracts an archive (a zip is *listed* from its central
directory only) and never imports an animation file: FBX content is judged by ``fbx_scan``'s header scan, BVH/ASF/AMC by a few
bounded text lines.  Each entry says whether it is importable as video, needs conversion, lacks something, or is unsupported,
with a reason.  The report is plain data; saving it is the caller's job (and must not be inside the scanned root).
"""

from __future__ import annotations

import hashlib
import threading
import zipfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from src.video.motion_conversion.fbx_scan import FbxScan, scan_fbx
from src.video.motion_conversion.rig_compat import identify_rig

SCHEMA = "stablenew.motion-asset-inventory.v1"
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")
MAX_FILES = 20_000
MAX_ARCHIVE_ENTRIES = 5_000
HASH_CHUNK = 1024 * 1024
MAX_TEXT_SNIFF = 4096

KIND_VIDEO = "video"
KIND_FBX = "fbx"
KIND_BVH = "bvh"
KIND_ASF = "asf"
KIND_AMC = "amc"
KIND_ARCHIVE = "archive"
KIND_ARCHIVE_MEMBER = "archive_member"
KIND_OTHER = "other"

ROUTE_NONE = ""
ROUTE_VIDEO = "video"
ROUTE_FBX_CHARACTER = "fbx_character"
ROUTE_FBX_SKELETON = "fbx_skeleton"
ROUTE_BVH_SKELETON = "bvh_skeleton"

STATE_READY = "ready"
STATE_NOT_REQUIRED = "not_required"
STATE_MISSING_DEPENDENCY = "missing_dependency"
STATE_UNSUPPORTED = "unsupported"
STATE_NEEDS_EXTRACTION = "needs_extraction"
STATE_INVALID = "invalid"
STATES = (
    STATE_READY,
    STATE_NOT_REQUIRED,
    STATE_MISSING_DEPENDENCY,
    STATE_UNSUPPORTED,
    STATE_NEEDS_EXTRACTION,
    STATE_INVALID,
)

#: Files that are metadata noise, not assets.
_IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    relative_path: str
    extension: str
    kind: str
    size_bytes: int
    sha256: str
    source_family: str
    source_folder: str
    in_archive: bool
    importable_directly: bool
    conversion_required: bool
    route: str
    state: str
    reason: str
    has_mesh: bool | None = None
    has_skin: bool | None = None
    has_skeleton: bool | None = None
    has_animation: bool | None = None
    missing_skeleton: bool = False
    rig_family: str = ""
    duplicate_of: str = ""
    video: Mapping[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        record = {name: getattr(self, name) for name in self.__slots__}
        record["video"] = dict(self.video) if self.video else None
        return record


@dataclass(frozen=True, slots=True)
class InventoryReport:
    root_label: str
    entries: tuple[InventoryEntry, ...]
    blender_available: bool = False
    truncated: bool = False
    cancelled: bool = False
    skipped: tuple[str, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> dict[str, Any]:
        entries = self.entries
        by_type = Counter(e.extension or "(none)" for e in entries)
        by_family = Counter(e.source_family for e in entries)
        by_state = Counter(e.state for e in entries)
        by_rig = Counter(e.rig_family for e in entries if e.rig_family)
        return {
            "total": len(entries),
            "by_type": dict(sorted(by_type.items())),
            "by_source_family": dict(sorted(by_family.items())),
            "by_rig_family": dict(sorted(by_rig.items())),
            "by_state": {state: by_state.get(state, 0) for state in STATES},
            "duplicate_content": sum(1 for e in entries if e.duplicate_of),
            "conversion_ready": by_state.get(STATE_READY, 0),
            "missing_dependency": by_state.get(STATE_MISSING_DEPENDENCY, 0),
            "unsupported": by_state.get(STATE_UNSUPPORTED, 0),
            "needs_extraction": by_state.get(STATE_NEEDS_EXTRACTION, 0),
            "invalid": by_state.get(STATE_INVALID, 0),
            "blender_available": self.blender_available,
        }

    def representative_sample(self) -> tuple[InventoryEntry, ...]:
        """One deterministic exemplar per distinct capability (kind, state, route, content shape, rig, source family)."""

        chosen: dict[tuple[Any, ...], InventoryEntry] = {}
        for entry in sorted(self.entries, key=lambda e: e.relative_path.lower()):
            if entry.duplicate_of:
                continue
            key = (
                entry.kind,
                entry.state,
                entry.route,
                entry.has_mesh,
                entry.has_skin,
                entry.has_skeleton,
                entry.has_animation,
                entry.rig_family,
                entry.source_family,
            )
            chosen.setdefault(key, entry)
        return tuple(chosen.values())

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "root": self.root_label,
            "summary": self.summary,
            "truncated": self.truncated,
            "cancelled": self.cancelled,
            "skipped": list(self.skipped),
            "representative_sample": [e.relative_path for e in self.representative_sample()],
            "entries": [e.to_record() for e in self.entries],
        }


VideoProbe = Callable[[Path], Mapping[str, Any] | None]


def sha256_file(path: Path, cancel: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
            chunk = handle.read(HASH_CHUNK)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _read_text_head(path: Path) -> str:
    with path.open("rb") as handle:
        return handle.read(MAX_TEXT_SNIFF).decode("utf-8", "replace")


def _classify_bvh(path: Path) -> tuple[str, str, bool | None]:
    head = _read_text_head(path).lstrip("﻿ \t\r\n")
    if not head.upper().startswith("HIERARCHY"):
        return STATE_INVALID, "Not a BVH file (no HIERARCHY header).", None
    if "ROOT" not in head.upper():
        return STATE_INVALID, "The BVH header declares no root joint.", None
    return STATE_READY, "BVH skeleton animation (skeleton-only; rendered as a skeleton).", True


def classify_fbx(scan: FbxScan) -> tuple[str, str, str]:
    """``(state, reason, route)`` from what the node headers say."""

    if scan.error:
        return STATE_INVALID, scan.error, ROUTE_NONE
    if scan.encoding == "ascii":
        return (
            STATE_UNSUPPORTED,
            "ASCII FBX is not inspected without Blender; convert needs an explicit probe.",
            ROUTE_NONE,
        )
    if not scan.has_animation:
        return STATE_UNSUPPORTED, "The FBX holds no animation curves.", ROUTE_NONE
    if scan.has_mesh and scan.has_skin and scan.has_skeleton:
        return (
            STATE_READY,
            "Animated skinned character (mesh, skin, skeleton, animation).",
            ROUTE_FBX_CHARACTER,
        )
    if scan.has_skeleton and not scan.has_mesh:
        return (
            STATE_READY,
            "Skeleton animation without a character mesh (skeleton render, or a verified compatible character).",
            ROUTE_FBX_SKELETON,
        )
    if scan.has_mesh and not scan.has_skeleton:
        return (
            STATE_MISSING_DEPENDENCY,
            "A mesh with animation curves but no skeleton: the motion has no rig to drive.",
            ROUTE_NONE,
        )
    if not scan.has_skeleton:
        return (
            STATE_MISSING_DEPENDENCY,
            "Animation curves without a skeleton or mesh: no rig is declared.",
            ROUTE_NONE,
        )
    return (
        STATE_MISSING_DEPENDENCY,
        "Skeleton present but the skin binding is incomplete.",
        ROUTE_NONE,
    )


def _archive_members(path: Path, relative: str, family: str) -> list[InventoryEntry]:
    """List a zip's members from its central directory.  Nothing is extracted or decompressed."""

    members: list[InventoryEntry] = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, NotImplementedError, RuntimeError) as exc:
        return [
            InventoryEntry(
                relative,
                path.suffix.lower(),
                KIND_ARCHIVE,
                _size(path),
                "",
                family,
                str(PurePosixPath(relative).parent),
                False,
                False,
                False,
                ROUTE_NONE,
                STATE_INVALID,
                f"The archive cannot be read: {exc}",
            )
        ]
    for info in infos[:MAX_ARCHIVE_ENTRIES]:
        if info.is_dir():
            continue
        name = info.filename
        parts = PurePosixPath(name.replace("\\", "/")).parts
        unsafe = (
            name.startswith(("/", "\\"))
            or ".." in parts
            or (len(name) > 1 and name[1] == ":")
            or ((info.external_attr >> 16) & 0o170000) == 0o120000
        )
        suffix = PurePosixPath(name).suffix.lower()
        state = STATE_INVALID if unsafe else STATE_NEEDS_EXTRACTION
        reason = (
            "Unsafe archive member path or link; it will never be extracted."
            if unsafe
            else "Inside an archive: extract explicitly into an empty folder before use."
        )
        members.append(
            InventoryEntry(
                f"{relative}!{name}",
                suffix,
                KIND_ARCHIVE_MEMBER,
                info.file_size,
                "",
                family,
                str(PurePosixPath(relative).parent),
                True,
                False,
                suffix not in VIDEO_SUFFIXES,
                ROUTE_NONE,
                state,
                reason,
            )
        )
    return members


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def scan_inventory(
    root: str | Path,
    *,
    probe_video: VideoProbe | None = None,
    blender_available: bool = False,
    cancel: threading.Event | None = None,
    max_files: int = MAX_FILES,
) -> InventoryReport:
    """Inventory ``root`` (read-only).  ``probe_video`` is the existing bounded inspector, injected."""

    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"The asset folder does not exist: {base}")
    files: list[Path] = []
    skipped: list[str] = []
    truncated = False
    for path in sorted(base.rglob("*"), key=lambda p: str(p).lower()):
        try:
            if path.is_symlink():
                skipped.append(f"{path.relative_to(base).as_posix()} (symbolic link not followed)")
                continue
            if not path.is_file():
                continue
        except OSError:
            continue
        if path.name.lower() in _IGNORED_NAMES:
            continue
        if len(files) >= max_files:
            truncated = True
            break
        files.append(path)

    entries: list[InventoryEntry] = []
    first_by_hash: dict[str, str] = {}
    cancelled = False
    amc_stems = {p.with_suffix("").as_posix().lower() for p in files if p.suffix.lower() == ".amc"}
    asf_stems = {p.with_suffix("").as_posix().lower() for p in files if p.suffix.lower() == ".asf"}
    for path in files:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        relative = path.relative_to(base).as_posix()
        parts = PurePosixPath(relative).parts
        family = parts[0] if len(parts) > 1 else "(root)"
        folder = str(PurePosixPath(relative).parent)
        suffix = path.suffix.lower()
        try:
            digest = sha256_file(path, cancel)
        except InterruptedError:
            cancelled = True
            break
        except OSError as exc:
            entries.append(
                InventoryEntry(
                    relative,
                    suffix,
                    KIND_OTHER,
                    0,
                    "",
                    family,
                    folder,
                    False,
                    False,
                    False,
                    ROUTE_NONE,
                    STATE_INVALID,
                    f"The file cannot be read: {exc}",
                )
            )
            continue
        duplicate_of = first_by_hash.setdefault(digest, relative)
        duplicate_of = "" if duplicate_of == relative else duplicate_of
        size = _size(path)
        common: dict[str, Any] = {
            "relative_path": relative,
            "extension": suffix,
            "size_bytes": size,
            "sha256": digest,
            "source_family": family,
            "source_folder": folder,
            "in_archive": False,
            "duplicate_of": duplicate_of,
        }
        if suffix in VIDEO_SUFFIXES:
            facts = probe_video(path) if probe_video is not None else None
            state, reason = (STATE_NOT_REQUIRED, "Video: importable directly; no conversion.")
            if probe_video is not None and facts is None:
                state, reason = STATE_INVALID, "The video could not be inspected."
            entries.append(
                InventoryEntry(
                    kind=KIND_VIDEO,
                    importable_directly=state == STATE_NOT_REQUIRED,
                    conversion_required=False,
                    route=ROUTE_VIDEO if state == STATE_NOT_REQUIRED else ROUTE_NONE,
                    state=state,
                    reason=reason,
                    video=facts,
                    **common,
                )
            )
        elif suffix == ".fbx":
            scan = scan_fbx(path)
            state, reason, route = classify_fbx(scan)
            rig = identify_rig(scan.bone_names).family if scan.bone_names else ""
            entries.append(
                InventoryEntry(
                    kind=KIND_FBX,
                    importable_directly=False,
                    conversion_required=True,
                    route=route,
                    state=state,
                    reason=reason,
                    has_mesh=scan.has_mesh if not scan.error else None,
                    has_skin=scan.has_skin if not scan.error else None,
                    has_skeleton=scan.has_skeleton if not scan.error else None,
                    has_animation=scan.has_animation if not scan.error else None,
                    missing_skeleton=(not scan.error and not scan.has_skeleton),
                    rig_family=rig,
                    **common,
                )
            )
        elif suffix == ".bvh":
            try:
                state, reason, animated = _classify_bvh(path)
            except OSError as exc:
                state, reason, animated = STATE_INVALID, f"The file cannot be read: {exc}", None
            entries.append(
                InventoryEntry(
                    kind=KIND_BVH,
                    importable_directly=False,
                    conversion_required=True,
                    route=ROUTE_BVH_SKELETON if state == STATE_READY else ROUTE_NONE,
                    state=state,
                    reason=reason,
                    has_mesh=False if state == STATE_READY else None,
                    has_skeleton=animated,
                    has_animation=animated,
                    **common,
                )
            )
        elif suffix in (".asf", ".amc"):
            stem = path.with_suffix("").as_posix().lower()
            paired = (stem in amc_stems) and (stem in asf_stems)
            reason = (
                "ASF/AMC is not supported yet (no verified importer); recorded as a coverage gap."
                + ("" if paired else " The matching ASF/AMC partner file is also missing.")
            )
            entries.append(
                InventoryEntry(
                    kind=KIND_ASF if suffix == ".asf" else KIND_AMC,
                    importable_directly=False,
                    conversion_required=True,
                    route=ROUTE_NONE,
                    state=STATE_UNSUPPORTED if paired else STATE_MISSING_DEPENDENCY,
                    reason=reason,
                    missing_skeleton=suffix == ".amc" and stem not in asf_stems,
                    **common,
                )
            )
        elif suffix in (".zip",):
            archive_entry = InventoryEntry(
                kind=KIND_ARCHIVE,
                importable_directly=False,
                conversion_required=False,
                route=ROUTE_NONE,
                state=STATE_NEEDS_EXTRACTION,
                reason="Archive: listed only; extraction is a separate, explicit step.",
                **common,
            )
            entries.append(archive_entry)
            entries.extend(_archive_members(path, relative, family))
        else:
            entries.append(
                InventoryEntry(
                    kind=KIND_OTHER,
                    importable_directly=False,
                    conversion_required=False,
                    route=ROUTE_NONE,
                    state=STATE_UNSUPPORTED,
                    reason="Not a motion asset type StableNew recognizes.",
                    **common,
                )
            )
    return InventoryReport(
        root_label=base.name,
        entries=tuple(entries),
        blender_available=blender_available,
        truncated=truncated,
        cancelled=cancelled,
        skipped=tuple(skipped[:50]),
    )


def format_report(report: InventoryReport, *, sample_limit: int = 25) -> str:
    """A concise human-readable summary of an inventory."""

    s = report.summary
    lines = [f"Motion asset inventory of '{report.root_label}': {s['total']} item(s)."]
    lines.append("By type: " + ", ".join(f"{k} {v}" for k, v in s["by_type"].items()))
    lines.append(
        "By source family: " + ", ".join(f"{k} {v}" for k, v in s["by_source_family"].items())
    )
    if s["by_rig_family"]:
        lines.append(
            "By rig family: " + ", ".join(f"{k} {v}" for k, v in s["by_rig_family"].items())
        )
    lines.append(
        f"Duplicate content {s['duplicate_content']}; conversion-ready {s['conversion_ready']}; "
        f"missing dependency {s['missing_dependency']}; unsupported {s['unsupported']}; "
        f"awaiting extraction {s['needs_extraction']}; invalid {s['invalid']}."
    )
    lines.append(
        "Blender: " + ("available" if s["blender_available"] else "NOT installed or not selected")
    )
    sample: Sequence[InventoryEntry] = report.representative_sample()
    lines.append(f"Representative sample ({min(len(sample), sample_limit)} of {len(sample)}):")
    for entry in sample[:sample_limit]:
        lines.append(f"  [{entry.state}] {entry.relative_path} - {entry.reason}")
    return "\n".join(lines)
