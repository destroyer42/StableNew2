"""Batch conversion of a folder of mocap files into verified driving videos (PR-VID-MOTION-356).

An offline asset-management operation, not a generation job: it never builds an NJR, never touches the queue, a runner, Comfy,
Forge or the GPU.  It composes what already exists -- ``scan_inventory`` for the dry run, ``ConversionWorkbench`` (one
contained CPU Blender child per step, the verified publication, the provenance record) for each file, and the Motion Library's
own importer for registration -- and adds only the policy of doing that for many files one at a time:

* a dry run that says what would happen to every file (convert, already converted, duplicate, not eligible and why), the
  destination and a storage estimate with its uncertainty;
* an operator confirmation bound to that exact file count, destination and disk budget;
* sequential execution where one file's failure never blocks the rest, nothing is retried automatically, and a run of
  systemic Blender failures or a low disk stops the batch instead of repeating the same fault;
* restart safety: an identical, still-verified earlier conversion is skipped without starting Blender.

Originals are only ever read; archives are listed, never extracted; a plan is never silently retargeted onto another rig.
"""

from __future__ import annotations

import math
import shutil
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_json
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion import diagnostics as diag
from src.video.motion_conversion import inventory as inv
from src.video.motion_conversion.conversion_service import (
    PROVENANCE_NAME,
    STATUS_CANCELLED,
    STATUS_REUSED,
    ProbeError,
    read_provenance,
    verify_published,
)
from src.video.motion_conversion.workbench import ConversionWorkbench
from src.video.motion_library.store import MotionLibraryStore

REPORT_SCHEMA = "stablenew.motion-batch-report.v1"
REPORTS_DIRNAME = "batch-reports"
CONVERTED_DIRNAME = "converted"
BATCH_TAG = "batch-converted"
#: A mocap take usually begins with a T-pose calibration frame.  The batch never trims it (PR-VID-MOTION-355); it says so.
CALIBRATION_WARNING = (
    "Converted from the start of the take: a first-frame T-pose (calibration) is kept, not trimmed. "
    "Review the result, or set a later Start and convert again."
)

POLICY_AUTO = "auto"
POLICY_SKELETON = "skeleton"
POLICIES = (POLICY_AUTO, POLICY_SKELETON)
POLICY_LABELS = {
    POLICY_AUTO: "Best available per file (character render if it has a skinned mesh, else skeleton)",
    POLICY_SKELETON: "Skeleton render for every file",
}

#: Scan bounds for the dry run.
SCAN_MAX_FILES = 5_000
SCAN_MAX_DEPTH = 8
SCAN_MAX_FILE_BYTES = 256 * 1024 * 1024
SAMPLE_SIZE = 3

DISP_CONVERT = "convert"
DISP_EXISTING = "already_converted"
DISP_DUPLICATE = "duplicate"
DISP_INELIGIBLE = "not_eligible"
DISP_ARCHIVE = "needs_extraction"
DISP_VIDEO = "video"
DISPOSITIONS = (
    DISP_CONVERT,
    DISP_EXISTING,
    DISP_DUPLICATE,
    DISP_INELIGIBLE,
    DISP_ARCHIVE,
    DISP_VIDEO,
)

ITEM_CONVERTED = "converted"
ITEM_REUSED = "reused"
ITEM_EXISTING = "skipped_existing"
ITEM_FAILED = "failed"
ITEM_CANCELLED = "cancelled"
ITEM_NOT_RUN = "not_run"
ITEM_OK = (ITEM_CONVERTED, ITEM_REUSED, ITEM_EXISTING)

KIND_REGISTRATION = "library_registration_failure"
KIND_DISK = diag.KIND_STORAGE

#: Failures that say something is wrong with Blender or the machine rather than with one file.
_SYSTEMIC_NOW = (diag.KIND_LAUNCH, diag.KIND_CAPABILITY)
_SYSTEMIC_REPEATED = (diag.KIND_CRASH, diag.KIND_MEMORY, diag.KIND_TIMEOUT)
MAX_CONSECUTIVE_SYSTEMIC = 5
#: Free space that must remain on the destination drive, and the working space one clip needs while it renders.
MIN_FREE_BYTES = 1024**3
#: Observed bytes per output frame of the lossless H.264 clips when nothing has been converted yet, and the spread kept
#: around any estimate (the true size depends on how much of the frame the figure covers).
DEFAULT_BYTES_PER_FRAME = 8 * 1024
ESTIMATE_LOW = 0.4
ESTIMATE_HIGH = 3.0
PNG_BYTES_PER_PIXEL = 0.35  # compressed, mostly flat frames


class BatchRefused(RuntimeError):
    """The batch was not started; the message says why (a stale or missing confirmation, no Blender, ...)."""


# ------------------------------------------------------------------ settings and inventory


@dataclass(frozen=True)
class BatchSettings:
    """Everything that changes pixels for every file of the batch.  ``frames`` is the longest clip wanted per file."""

    profile_policy: str = POLICY_AUTO
    camera: str = cp.CAMERA_FRONT
    camera_mode: str = cp.CAMERA_STATIC
    root_motion: str = cp.ROOT_PRESERVE
    start_seconds: str = "0"
    frames: int = 17
    width: int = cp.DEFAULT_WIDTH
    height: int = cp.DEFAULT_HEIGHT
    #: Lengths the consuming workflow accepts (empty: the generic rule).  The longest one that fits each file is used.
    legal_frames: tuple[int, ...] = ()
    workflow_spec: Any = field(default=None, compare=False, repr=False)

    def profile_for(self, route: str) -> str:
        if self.profile_policy == POLICY_SKELETON or route != inv.ROUTE_FBX_CHARACTER:
            return cp.PROFILE_SKELETON
        return cp.PROFILE_CHARACTER

    def identity(self) -> dict[str, Any]:
        return {
            "profile_policy": self.profile_policy,
            "camera": self.camera,
            "camera_mode": self.camera_mode,
            "root_motion": self.root_motion,
            "start_seconds": self.start_seconds,
            "frames": self.frames,
            "geometry": f"{self.width}x{self.height}",
        }


@dataclass(frozen=True)
class ExistingConversion:
    directory: str
    profile: str
    camera: str
    camera_mode: str
    root_motion: str
    width: int
    height: int
    frames: int
    start_seconds: Fraction
    video_bytes: int


@dataclass(frozen=True)
class BatchEntry:
    relative_path: str
    path: str
    sha256: str
    kind: str
    route: str
    rig_family: str
    disposition: str
    reason: str
    size_bytes: int = 0
    profile: str = ""
    duplicate_of: str = ""
    existing_dir: str = ""


@dataclass(frozen=True)
class StorageEstimate:
    expected_bytes: int
    low_bytes: int
    high_bytes: int
    #: Working space one clip needs while it renders (deleted afterwards).
    temporary_bytes: int
    basis: str


@dataclass(frozen=True)
class BatchConfirmation:
    """What the operator approved.  A batch starts only when this equals the inventory's own figures."""

    file_count: int
    destination: str
    budget_bytes: int


@dataclass(frozen=True)
class BatchInventory:
    root: str
    destination: str
    settings: BatchSettings
    entries: tuple[BatchEntry, ...]
    estimate: StorageEstimate
    free_bytes: int
    truncated: bool = False
    cancelled: bool = False
    skipped: tuple[str, ...] = ()

    def of(self, disposition: str) -> tuple[BatchEntry, ...]:
        return tuple(e for e in self.entries if e.disposition == disposition)

    @property
    def to_convert(self) -> tuple[BatchEntry, ...]:
        return self.of(DISP_CONVERT)

    @property
    def counts(self) -> dict[str, int]:
        found = Counter(e.disposition for e in self.entries)
        return {name: found.get(name, 0) for name in DISPOSITIONS}

    def confirmation(self) -> BatchConfirmation:
        return BatchConfirmation(
            len(self.to_convert),
            self.destination,
            self.estimate.high_bytes + self.estimate.temporary_bytes,
        )

    def sample(self, size: int = SAMPLE_SIZE) -> tuple[BatchEntry, ...]:
        """A few files of different kinds (route, rig) first, so one sample shows every kind of input at work."""

        chosen: list[BatchEntry] = []
        seen: set[tuple[str, str]] = set()
        for entry in self.to_convert:
            key = (entry.route, entry.rig_family)
            if key not in seen:
                seen.add(key)
                chosen.append(entry)
        for entry in self.to_convert:
            if len(chosen) >= size:
                break
            if entry not in chosen:
                chosen.append(entry)
        return tuple(chosen[:size])


def index_converted(conversions_root: str | Path) -> dict[str, list[ExistingConversion]]:
    """Accepted conversions already published under ``conversions_root``, by the SHA-256 of the original file."""

    found: dict[str, list[ExistingConversion]] = {}
    folder = Path(conversions_root) / CONVERTED_DIRNAME
    try:
        children = sorted(p for p in folder.iterdir() if p.is_dir())
    except OSError:
        return found
    for child in children:
        record = read_provenance(child / PROVENANCE_NAME)
        if record is None or record.get("purpose") != "accepted":
            continue
        try:
            conversion, output = record["conversion"], record["output"]
            window = conversion["frame_window"]
            sha = str(record["source"]["sha256"])
            video = child / str(output["file"])
            found.setdefault(sha, []).append(
                ExistingConversion(
                    str(child),
                    str(conversion["profile"]),
                    str(conversion["camera"]),
                    str(conversion["camera_mode"]),
                    str(conversion["root_motion"]),
                    int(conversion["geometry"]["width"]),
                    int(conversion["geometry"]["height"]),
                    int(window["output_frames"]),
                    Fraction(str(window["start_seconds"])),
                    video.stat().st_size if video.is_file() else 0,
                )
            )
        except (KeyError, TypeError, ValueError, OSError, ZeroDivisionError):
            continue
    return found


def _same_settings(old: ExistingConversion, settings: BatchSettings, profile: str) -> bool:
    try:
        start = Fraction(settings.start_seconds)
    except (ValueError, ZeroDivisionError):
        return False
    return (
        old.profile == profile
        and old.camera == settings.camera
        and old.camera_mode == settings.camera_mode
        and old.root_motion == settings.root_motion
        and (old.width, old.height) == (settings.width, settings.height)
        and old.start_seconds == start
        and old.frames == settings.frames
    )


def find_existing(
    index: Mapping[str, Sequence[ExistingConversion]],
    sha256: str,
    profile: str,
    settings: BatchSettings,
) -> ExistingConversion | None:
    """An earlier conversion of this exact file with these settings whose published video still verifies."""

    for old in index.get(sha256, ()):
        if _same_settings(old, settings, profile) and verify_published(old.directory) == "":
            return old
    return None


def estimate_storage(
    files: int, settings: BatchSettings, index: Mapping[str, Sequence[ExistingConversion]]
) -> StorageEstimate:
    observed = [
        old.video_bytes / old.frames
        for olds in index.values()
        for old in olds
        if old.frames > 0 and old.video_bytes > 0
    ]
    if observed:
        per_frame = sorted(observed)[len(observed) // 2]
        basis = f"median of {len(observed)} clip(s) already converted here"
    else:
        per_frame = float(DEFAULT_BYTES_PER_FRAME)
        basis = "a default per-frame size (nothing converted here yet to measure)"
    expected = int(files * settings.frames * per_frame)
    temporary = int(settings.width * settings.height * PNG_BYTES_PER_PIXEL * settings.frames)
    return StorageEstimate(
        expected, int(expected * ESTIMATE_LOW), int(expected * ESTIMATE_HIGH), temporary, basis
    )


def build_inventory(
    report: inv.InventoryReport,
    *,
    root: Path,
    destination: Path,
    settings: BatchSettings,
    index: Mapping[str, Sequence[ExistingConversion]],
    free_bytes: int,
) -> BatchInventory:
    """Pure: turn a scan into what would happen to each file under ``settings``."""

    entries: list[BatchEntry] = []
    for item in report.entries:
        common: dict[str, Any] = {
            "relative_path": item.relative_path,
            "path": str(root / item.relative_path),
            "sha256": item.sha256,
            "kind": item.kind,
            "route": item.route,
            "rig_family": item.rig_family,
            "size_bytes": item.size_bytes,
        }
        profile = settings.profile_for(item.route)
        if item.kind == inv.KIND_VIDEO:
            entries.append(
                BatchEntry(
                    disposition=DISP_VIDEO,
                    reason="Already a video: import it into the Motion Library directly.",
                    **common,
                )
            )
        elif item.kind in (inv.KIND_ARCHIVE, inv.KIND_ARCHIVE_MEMBER):
            entries.append(
                BatchEntry(
                    disposition=DISP_ARCHIVE,
                    reason="Inside an archive; extract it yourself if you trust it. Nothing is extracted automatically.",
                    **common,
                )
            )
        elif item.kind not in (inv.KIND_FBX, inv.KIND_BVH):
            entries.append(BatchEntry(disposition=DISP_INELIGIBLE, reason=item.reason, **common))
        elif item.duplicate_of:
            entries.append(
                BatchEntry(
                    disposition=DISP_DUPLICATE,
                    reason=f"Same content as {item.duplicate_of}; converted once.",
                    duplicate_of=item.duplicate_of,
                    **common,
                )
            )
        elif item.state != inv.STATE_READY or item.route not in (
            inv.ROUTE_FBX_CHARACTER,
            inv.ROUTE_FBX_SKELETON,
            inv.ROUTE_BVH_SKELETON,
        ):
            entries.append(BatchEntry(disposition=DISP_INELIGIBLE, reason=item.reason, **common))
        else:
            old = find_existing(index, item.sha256, profile, settings)
            if old is not None:
                entries.append(
                    BatchEntry(
                        disposition=DISP_EXISTING,
                        reason="An identical verified conversion already exists.",
                        profile=profile,
                        existing_dir=old.directory,
                        **common,
                    )
                )
            else:
                entries.append(
                    BatchEntry(
                        disposition=DISP_CONVERT,
                        reason=item.reason,
                        profile=profile,
                        **common,
                    )
                )
    pending = sum(1 for e in entries if e.disposition == DISP_CONVERT)
    return BatchInventory(
        root=str(root),
        destination=str(destination),
        settings=settings,
        entries=tuple(entries),
        estimate=estimate_storage(pending, settings, index),
        free_bytes=free_bytes,
        truncated=report.truncated,
        cancelled=report.cancelled,
        skipped=report.skipped,
    )


def scan_for_batch(
    bench: ConversionWorkbench,
    root: str | Path,
    settings: BatchSettings,
    *,
    cancel: threading.Event | None = None,
    free_bytes: Callable[[Path], int] | None = None,
) -> BatchInventory:
    """The dry run: read-only, bounded, hashes files but converts nothing.  The output folder is never scanned."""

    base = Path(root).expanduser().resolve()
    destination = bench.output_root()
    report = inv.scan_inventory(
        base,
        cancel=cancel,
        max_files=SCAN_MAX_FILES,
        max_depth=SCAN_MAX_DEPTH,
        max_file_bytes=SCAN_MAX_FILE_BYTES,
        exclude=[destination],
    )
    index = index_converted(destination)
    measure = free_bytes or _free_bytes
    return build_inventory(
        report,
        root=base,
        destination=destination,
        settings=settings,
        index=index,
        free_bytes=measure(destination),
    )


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return 0


def fit_frames(settings: BatchSettings, probe: cp.AnimationProbe) -> int:
    """The longest legal length not above ``settings.frames`` that the animation can supply from the chosen start."""

    start = cp.parse_rational(settings.start_seconds)
    available = probe.duration_seconds - start
    if available < 0:
        raise cp.ConversionPlanError("The start is after the end of the animation.")
    room = math.floor(available * cp.TARGET_FPS) + 1
    legal = settings.legal_frames or tuple(
        n
        for n in range(cp.GENERIC_FRAME_POLICY["minimum"], cp.GENERIC_FRAME_POLICY["maximum"] + 1)
        if (n - cp.GENERIC_FRAME_POLICY["offset"]) % cp.GENERIC_FRAME_POLICY["step"] == 0
    )
    fitting = [n for n in legal if n <= min(settings.frames, room)]
    if not fitting:
        raise cp.ConversionPlanError(
            f"The animation supplies only {max(room, 0)} frame(s) from that start, fewer than the shortest "
            f"length ({min(legal) if legal else 'n/a'}) the workflow accepts."
        )
    return max(fitting)


# ------------------------------------------------------------------ execution


@dataclass(frozen=True)
class BatchItemResult:
    relative_path: str
    status: str
    kind: str = ""
    reason: str = ""
    profile: str = ""
    frames: int = 0
    directory: str = ""
    output_sha256: str = ""
    diagnostic_path: str = ""
    asset_id: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ITEM_OK


@dataclass(frozen=True)
class BatchProgress:
    index: int
    total: int
    relative_path: str
    last: BatchItemResult | None = None


@dataclass(frozen=True)
class BatchSummary:
    results: tuple[BatchItemResult, ...]
    stopped_reason: str = ""
    started_at: str = ""
    finished_at: str = ""
    report_path: str = ""

    @property
    def counts(self) -> dict[str, int]:
        found = Counter(r.status for r in self.results)
        return {
            name: found.get(name, 0)
            for name in (
                ITEM_CONVERTED,
                ITEM_REUSED,
                ITEM_EXISTING,
                ITEM_FAILED,
                ITEM_CANCELLED,
                ITEM_NOT_RUN,
            )
        }

    @property
    def failures(self) -> tuple[BatchItemResult, ...]:
        return tuple(r for r in self.results if r.status == ITEM_FAILED)

    @property
    def cancelled(self) -> bool:
        return any(r.status == ITEM_CANCELLED for r in self.results)

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": REPORT_SCHEMA,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stopped_reason": self.stopped_reason,
            "counts": self.counts,
            "results": [
                {
                    "file": r.relative_path,
                    "status": r.status,
                    "kind": r.kind,
                    "reason": r.reason,
                    "profile": r.profile,
                    "frames": r.frames,
                    "output_sha256": r.output_sha256,
                    "seconds": round(r.seconds, 1),
                }
                for r in self.results
            ],
        }

    def text(self) -> str:
        counts = self.counts
        lines = [
            f"Converted {counts[ITEM_CONVERTED]}, reused {counts[ITEM_REUSED]}, skipped (already done) "
            f"{counts[ITEM_EXISTING]}, failed {counts[ITEM_FAILED]}, cancelled {counts[ITEM_CANCELLED]}, "
            f"not run {counts[ITEM_NOT_RUN]}."
        ]
        if self.stopped_reason:
            lines.append(f"Stopped: {self.stopped_reason}")
        for result in self.failures:
            label = diag.KIND_LABELS.get(result.kind, result.kind)
            lines.append(f"  FAILED {result.relative_path}: {label}. {result.reason}")
        return "\n".join(lines)


ProgressCallback = Callable[[BatchProgress], None]


class BatchRunner:
    def __init__(
        self,
        bench: ConversionWorkbench,
        store: MotionLibraryStore,
        *,
        free_bytes: Callable[[Path], int] | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._bench = bench
        self._store = store
        self._free = free_bytes or _free_bytes
        self._clock = clock
        self._now = now

    def run(
        self,
        inventory: BatchInventory,
        entries: Sequence[BatchEntry],
        *,
        confirmation: BatchConfirmation,
        cancel: threading.Event | None = None,
        progress: ProgressCallback | None = None,
        include_existing: bool = False,
    ) -> BatchSummary:
        """Convert ``entries`` (a subset of ``inventory.to_convert``, usually the sample then the rest), one at a time.

        ``include_existing`` also makes sure every file with an identical verified earlier conversion is in the Motion
        Library, without starting Blender for it."""

        cancel = cancel or threading.Event()
        if confirmation != inventory.confirmation():
            raise BatchRefused(
                "The confirmation does not match this scan's file count, destination and disk budget; confirm again."
            )
        allowed = {e.relative_path for e in inventory.to_convert}
        foreign = [e.relative_path for e in entries if e.relative_path not in allowed]
        if foreign:
            raise BatchRefused(f"Not part of the confirmed batch: {foreign[0]}")
        if self._bench.blender() is None:
            raise BatchRefused("Choose a Blender executable first.")
        needed = inventory.estimate.high_bytes + inventory.estimate.temporary_bytes + MIN_FREE_BYTES
        if self._free(Path(inventory.destination)) < needed:
            raise BatchRefused(
                "Not enough free space on the destination drive for the approved budget "
                f"({needed // 1024**2} MiB needed including a 1 GiB reserve)."
            )
        self._bench.prepare_batch()
        started = self._now().isoformat()
        results: list[BatchItemResult] = []
        stopped = ""
        systemic_run = 0
        total = len(entries)
        if include_existing:
            for old in inventory.of(DISP_EXISTING):
                if cancel.is_set():
                    break
                results.append(self.register_existing(old, cancel))
        executed_from = len(results)
        for position, entry in enumerate(entries):
            if cancel.is_set():
                stopped = stopped or "Cancelled by the operator."
                break
            if progress is not None:
                progress(
                    BatchProgress(
                        position, total, entry.relative_path, results[-1] if results else None
                    )
                )
            if self._free(Path(inventory.destination)) < MIN_FREE_BYTES:
                stopped = "The destination drive is nearly full."
                break
            result = self._one(entry, inventory.settings, cancel)
            results.append(result)
            if result.status == ITEM_CANCELLED:
                stopped = "Cancelled by the operator."
                break
            systemic_run = systemic_run + 1 if result.kind in _SYSTEMIC_REPEATED else 0
            if result.kind in _SYSTEMIC_NOW:
                stopped = (
                    f"{diag.KIND_LABELS.get(result.kind, result.kind)}; every file would fail the same way. "
                    "Fix it, then run the batch again: finished files are skipped."
                )
                break
            if systemic_run >= MAX_CONSECUTIVE_SYSTEMIC:
                stopped = (
                    f"{systemic_run} files in a row failed the same way "
                    f"({diag.KIND_LABELS.get(result.kind, result.kind)}); stopped instead of repeating it. "
                    "Finished files are skipped on the next run."
                )
                break
        for entry in entries[len(results) - executed_from :]:
            results.append(
                BatchItemResult(entry.relative_path, ITEM_NOT_RUN, reason=stopped or "Not reached.")
            )
        summary = BatchSummary(tuple(results), stopped, started, self._now().isoformat())
        return self._publish_report(inventory, summary)

    # ------------------------------------------------------------------ one file

    def _one(
        self, entry: BatchEntry, settings: BatchSettings, cancel: threading.Event
    ) -> BatchItemResult:
        started = self._clock()

        def done(status: str, **fields: Any) -> BatchItemResult:
            return BatchItemResult(
                entry.relative_path,
                status,
                profile=entry.profile,
                seconds=self._clock() - started,
                **fields,
            )

        def failed(kind: str, reason: str, diagnostic_path: str = "") -> BatchItemResult:
            return done(ITEM_FAILED, kind=kind, reason=reason, diagnostic_path=diagnostic_path)

        bench = self._bench
        try:
            facts = bench.describe_source(entry.path, cancel)  # 1. verify the input's identity
        except InterruptedError:
            return done(ITEM_CANCELLED, kind=diag.KIND_CANCELLED, reason="Cancelled.")
        except OSError as exc:
            return failed(diag.KIND_ASSET, f"The file cannot be read: {exc}")
        if facts.sha256 != entry.sha256:
            return failed(
                diag.KIND_SOURCE, "The file changed since the scan (SHA-256 differs); scan again."
            )
        if not facts.ready or not facts.route:
            return failed(diag.KIND_REFUSED, facts.reason or "This file cannot be converted.")
        profile = settings.profile_for(facts.route)
        if cancel.is_set():
            return done(ITEM_CANCELLED, kind=diag.KIND_CANCELLED, reason="Cancelled.")
        try:
            probe = bench.probe(
                facts, cancel
            )  # 2. inspect the animation (one contained Blender child)
        except ProbeError as exc:
            result = exc.result
            if result is not None and result.status == STATUS_CANCELLED:
                return done(ITEM_CANCELLED, kind=diag.KIND_CANCELLED, reason="Cancelled.")
            return failed(
                result.failure_kind if result is not None else diag.KIND_CRASH,
                str(exc),
                result.diagnostic_path if result is not None else "",
            )
        except Exception as exc:  # noqa: BLE001 - one file's unexpected fault must not end the batch
            return failed(diag.KIND_ASSET, f"{type(exc).__name__}: {exc}")
        try:
            frames = fit_frames(settings, probe)  # 3. an explicit plan (never silently retargeted)
            plan = bench.plan_from_request(
                facts,
                probe,
                settings.workflow_spec,
                {
                    "profile": profile,
                    "camera": settings.camera,
                    "camera_mode": settings.camera_mode,
                    "root_motion": settings.root_motion,
                    "start_seconds": settings.start_seconds,
                    "output_frames": frames,
                    "width": settings.width,
                    "height": settings.height,
                },
                frames,
            )
        except cp.ConversionPlanError as exc:
            return failed(diag.KIND_REFUSED, str(exc))
        calibration = (
            (CALIBRATION_WARNING,) if cp.parse_rational(settings.start_seconds) == 0 else ()
        )
        result = bench.convert(  # 4-8. render, verify, encode, verify, publish atomically
            plan, cancel=cancel, warnings=calibration
        )
        if result.status == STATUS_CANCELLED:
            return done(ITEM_CANCELLED, kind=diag.KIND_CANCELLED, reason="Cancelled.")
        if not result.ok:
            return failed(
                result.failure_kind or diag.KIND_OUTPUT, result.reason, result.diagnostic_path
            )
        outcome = bench.accept(  # 9. register in the existing Motion Library
            self._store,
            result.directory,
            name=f"{Path(entry.relative_path).stem} ({settings.camera.replace('_', '-')})",
            tags=(BATCH_TAG,),
            cancel=cancel,
        )
        if not outcome.ok:
            return failed(
                KIND_REGISTRATION,
                f"Converted but not added to the Motion Library: {outcome.reason}",
            )
        return done(
            ITEM_REUSED if result.status == STATUS_REUSED else ITEM_CONVERTED,
            frames=result.frame_count,
            directory=result.directory,
            output_sha256=result.output_sha256,
            asset_id=outcome.asset_id,
        )

    def register_existing(self, entry: BatchEntry, cancel: threading.Event) -> BatchItemResult:
        """Skip an identical earlier conversion (no Blender), making sure it is in the Motion Library."""

        started = self._clock()
        if verify_published(entry.existing_dir) != "":
            return BatchItemResult(
                entry.relative_path,
                ITEM_FAILED,
                kind=diag.KIND_OUTPUT,
                reason="The earlier conversion no longer verifies.",
            )
        outcome = self._bench.accept(
            self._store,
            entry.existing_dir,
            name=Path(entry.relative_path).stem,
            tags=(BATCH_TAG,),
            cancel=cancel,
        )
        status = ITEM_EXISTING if outcome.ok else ITEM_FAILED
        return BatchItemResult(
            entry.relative_path,
            status,
            kind="" if outcome.ok else KIND_REGISTRATION,
            reason="" if outcome.ok else outcome.reason,
            profile=entry.profile,
            directory=entry.existing_dir,
            asset_id=outcome.asset_id,
            seconds=self._clock() - started,
        )

    # ------------------------------------------------------------------ report

    def _publish_report(self, inventory: BatchInventory, summary: BatchSummary) -> BatchSummary:
        stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
        path = Path(inventory.destination) / REPORTS_DIRNAME / f"batch-{stamp}.json"
        record = summary.to_record()
        record["settings"] = inventory.settings.identity()
        try:
            atomic_write_json(path, record, indent=2, sort_keys=True)
        except OSError:
            return summary
        return BatchSummary(
            summary.results,
            summary.stopped_reason,
            summary.started_at,
            summary.finished_at,
            str(path),
        )


__all__ = [
    "BatchConfirmation",
    "BatchEntry",
    "BatchInventory",
    "BatchItemResult",
    "BatchProgress",
    "BatchRefused",
    "BatchRunner",
    "BatchSettings",
    "BatchSummary",
    "POLICIES",
    "POLICY_LABELS",
    "build_inventory",
    "find_existing",
    "fit_frames",
    "index_converted",
    "scan_for_batch",
]
