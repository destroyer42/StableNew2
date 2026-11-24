"""Harvest Motion: cut a reusable, workflow-independent motion asset out of an existing video (PR-VID-MOTION-400).

``harvest_motion`` is an explicit, offline asset operation.  It reads one original video (never modifies it), resolves
an exact frame window, prepares a verified derivative and catalogs it in the Motion Library.  It builds no NJR, queues
nothing, starts no runtime and uses no GPU.

The preparation reuses the PR-VID-MOTION-210 engine unchanged (probe, exact frame plan, bounded cancellable FFmpeg,
lossless H.264, per-frame ``framemd5`` verification of what was written, atomic content-addressed publication) with a
*harvest contract* instead of a workflow contract: the output length is the window, not a generation length, and
nothing is held or padded.  A workflow-specific preparation (Prepare Motion Source) is a different, later operation on
the finished asset and never alters it.

Order of events, each step bounded and cancellable:

1. hash and probe the original; refuse what cannot be cut exactly (variable frame rate, unknown rate, an empty or
   out-of-range window, a window that is too long);
2. if the library already holds this exact cut of this original and its file verifies, reuse it (no re-encode);
3. prepare the derivative in a private staging folder inside the library root;
4. copy it into the library's ``managed/`` folder (hash-verified, atomic) and record the asset with its
   :class:`HarvestRecord`; one identity per byte content, so a second request for identical bytes reports what it did
   not apply;
5. verify the published file against its SHA-256 and remove the staged copy.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from src.video.driving_video_inspection import (
    STATUS_FAILED,
    DrivingVideoFacts,
    DrivingVideoInspection,
    ProcessRunner,
    inspect_driving_video,
    run_bounded_process,
)
from src.video.motion_library.harvest_window import (
    CadencePlan,
    WindowError,
    parse_rate,
    plan_cadence,
    rate_label,
    resolve_window,
)
from src.video.motion_library.hashing import HashCancelled, sha256_file
from src.video.motion_library.importer import (
    OUTCOME_DUPLICATE,
    OUTCOME_FAILED,
    SUPPORTED_SUFFIXES,
    import_video,
)
from src.video.motion_library.models import (
    ANNOTATION_FIELDS,
    CADENCE_NATIVE,
    CADENCES,
    LINEAGE_NONE,
    LINEAGE_RECORDED,
    LINEAGE_VERIFIED,
    LOCATOR_MANAGED,
    SOURCE_STABLENEW_GENERATED,
    HarvestRecord,
    MotionAsset,
    clean_text,
    normalize_tags,
    utc_now_iso,
)
from src.video.motion_library.store import LibraryError, MotionLibraryStore
from src.video.motion_library.verification import FILE_OK, verify_content
from src.video.motion_source_plan import (
    FPS_CONVERSION_NONE,
    FPS_CONVERSION_WORKFLOW_RATE,
    MotionSourceContract,
    source_rate,
)
from src.video.motion_source_preparation import (
    STATUS_CANCELLED,
    MotionSourceRequest,
    prepare_motion_source,
)

STAGING_DIRNAME = "harvest_staging"
HARVEST_CONTRACT_ID = "stablenew.motion_harvest"
HARVEST_CONTRACT_VERSION = "1"

STATUS_HARVESTED = "harvested"
STATUS_REUSED = "reused"
STATUS_DUPLICATE = "duplicate"
STATUS_REFUSED = "refused"
STATUS_FAILED_HARVEST = "failed"
STATUS_CANCELLED_HARVEST = "cancelled"

#: The harvest-specific cadences' FFmpeg conversion mode (PR-VID-MOTION-210 names).
_CONVERSION = {CADENCE_NATIVE: FPS_CONVERSION_NONE}


@dataclass(frozen=True, slots=True)
class HarvestLineage:
    """The originating job/artifact identity of a source, and how strongly it is established.

    ``state`` is ``verified`` only when the canonical History record names this artifact path *and* its recorded
    SHA-256 equals the bytes about to be cut; ``recorded`` when History names the artifact but recorded no SHA-256;
    ``path_only`` when all that is known is where the file is; ``none`` for nothing.  Identity is never inferred from a
    file name, a folder or a similar prompt."""

    state: str = LINEAGE_NONE
    job_id: str = ""
    artifact_path: str = ""
    artifact_sha256: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class HarvestRequest:
    """One harvest.  ``start``/``end`` are frames or seconds according to ``unit``; ``end`` is exclusive and ``None``
    means "to the end of the video"."""

    source_path: str
    start: float = 0.0
    end: float | None = None
    unit: str = "frames"
    cadence: str = CADENCE_NATIVE
    name: str = ""
    annotations: Mapping[str, Any] = field(default_factory=dict)
    lineage: HarvestLineage = field(default_factory=HarvestLineage)


@dataclass(frozen=True, slots=True)
class HarvestOutcome:
    status: str
    message: str = ""
    code: str = ""
    asset_id: str = ""
    record: HarvestRecord | None = None
    plan: CadencePlan | None = None
    warnings: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in {STATUS_HARVESTED, STATUS_REUSED, STATUS_DUPLICATE}


def harvest_contract(output_frames: int) -> MotionSourceContract:
    """The 210 engine's contract for a harvest: the window is the length; no workflow is involved."""

    return MotionSourceContract(
        workflow_id=HARVEST_CONTRACT_ID,
        workflow_version=HARVEST_CONTRACT_VERSION,
        output_frames=output_frames,
        output_fps=24,
        runtime_revision="",
        consumption_rule="harvest_window",
    )


def harvest_staging_root(store: MotionLibraryStore) -> Path:
    return store.root / STAGING_DIRNAME


def _default_inspect(path: Path, **kwargs: Any) -> DrivingVideoInspection:
    return inspect_driving_video(path, **kwargs)


def _refused(code: str, message: str, started: float, clock: Callable[[], float]) -> HarvestOutcome:
    return HarvestOutcome(
        STATUS_REFUSED, message=message, code=code, elapsed_seconds=max(0.0, clock() - started)
    )


def _source_warnings(facts: DrivingVideoFacts) -> list[str]:
    notes: list[str] = []
    if facts.rotation_quadrants:
        notes.append(
            f"The original is stored rotated by {facts.rotation_quadrants * 90} degrees; the harvested "
            "clip keeps the same orientation metadata, so it displays the same way."
        )
    if facts.sample_aspect_ratio:
        notes.append(
            f"The original reports a non-square pixel aspect ratio ({facts.sample_aspect_ratio}); the harvested "
            "clip keeps the stored pixels and does not carry that ratio."
        )
    return notes


def _merged_annotations(
    request: HarvestRequest, store: MotionLibraryStore, original_sha: str, source: Path
) -> dict[str, Any]:
    """Operator annotations first, then defaults that never override them."""

    given = {
        name: ANNOTATION_FIELDS[name](value)
        for name, value in dict(request.annotations).items()
        if name in ANNOTATION_FIELDS
    }
    parent = store.find_by_sha(original_sha)
    defaults: dict[str, Any] = {
        "display_name": clean_text(request.name, 120) or f"{source.stem} (harvested)",
        "source_reference": clean_text(f"Harvested from {source.name}"),
    }
    if parent is not None:
        # The cut inherits what the library already knows about the original's origin and terms.
        defaults["source_category"] = parent.source_category
        if parent.usage_terms:
            defaults["usage_terms"] = parent.usage_terms
        if parent.source_url:
            defaults["source_url"] = parent.source_url
    if request.lineage.state in {LINEAGE_VERIFIED, LINEAGE_RECORDED} and request.lineage.job_id:
        defaults["source_category"] = SOURCE_STABLENEW_GENERATED
    merged = {**defaults, **given}
    merged["tags"] = normalize_tags([*(given.get("tags") or ()), "harvested"])
    return merged


def harvest_motion(
    store: MotionLibraryStore,
    request: HarvestRequest,
    *,
    cancel: threading.Event | None = None,
    runner: ProcessRunner = run_bounded_process,
    ffmpeg: str | Path | None = None,
    ffprobe: str | Path | None = None,
    inspect: Callable[..., DrivingVideoInspection] = _default_inspect,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = utc_now_iso,
) -> HarvestOutcome:
    """Run one harvest.  Never raises for an expected failure; publishes nothing unless every check passed."""

    started = clock()

    def cancelled() -> HarvestOutcome:
        return HarvestOutcome(
            STATUS_CANCELLED_HARVEST,
            "Harvest was cancelled; nothing was added to the library.",
            "cancelled",
            elapsed_seconds=max(0.0, clock() - started),
        )

    def failed(code: str, message: str) -> HarvestOutcome:
        return HarvestOutcome(
            STATUS_FAILED_HARVEST, message, code, elapsed_seconds=max(0.0, clock() - started)
        )

    if request.cadence not in CADENCES:
        return _refused("cadence_unknown", f"Unknown cadence {request.cadence!r}.", started, clock)
    text = str(request.source_path or "").strip()
    if not text:
        return _refused("file_missing", "No video was chosen to harvest from.", started, clock)
    staged: Path | None = None
    try:
        source = Path(text).expanduser()
        suffix = source.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            return _refused(
                "unsupported_file",
                f"Unsupported video format '{suffix or 'none'}'. Supported: "
                f"{', '.join(sorted(SUPPORTED_SUFFIXES))}.",
                started,
                clock,
            )
        if not source.is_file():
            return _refused("file_missing", f"The video does not exist: {source}", started, clock)
        source = source.resolve()
        try:
            before = source.stat()
            original_sha = sha256_file(source, cancel)
            after = source.stat()
        except HashCancelled:
            return cancelled()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return failed(
                "source_changed",
                "The video changed while it was being read; try again when it is settled.",
            )

        probe = inspect(
            source, runner=runner, ffprobe=ffprobe, ffmpeg=ffmpeg, frame_count=0, cancel=cancel
        )
        if probe.status == STATUS_FAILED or probe.facts is None:
            if cancel is not None and cancel.is_set():
                return cancelled()
            reason = probe.issues[0].message if probe.issues else "The video could not be read."
            return failed("probe_failed", reason)
        facts = probe.facts
        if facts.fps_is_variable_suspected:
            return _refused(
                "variable_frame_rate",
                "This video may be variable frame rate, so a window cannot be cut or retimed exactly "
                "(each frame would be re-stamped at a constant rate). Re-encode it at a constant frame rate "
                "first, then harvest from that file.",
                started,
                clock,
            )
        rate = source_rate(facts)
        try:
            window = resolve_window(
                start=request.start,
                end=request.end,
                unit=request.unit,
                rate=rate,
                frame_count=facts.frame_count,
                count_is_reliable=facts.frame_count_basis == "reported",
            )
            plan = plan_cadence(window.frames, rate, request.cadence)
        except WindowError as exc:
            return _refused(exc.code, exc.message, started, clock)

        skeleton = _record_skeleton(
            request, facts, source, original_sha, window.start_frame, window.end_frame, plan, now()
        )
        existing = store.find_harvest(skeleton)
        if existing is not None:
            return _reuse(store, existing, plan, started, clock, cancel)

        # --- prepare the derivative with the 210 engine (staged, verified, content-addressed) ------------
        if cancel is not None and cancel.is_set():
            return cancelled()
        outcome = prepare_motion_source(
            MotionSourceRequest(
                clip_path=str(source),
                contract=harvest_contract(plan.output_frames),
                start=float(window.start_frame),
                end=float(window.end_frame),
                unit="frames",
                fps_conversion=_CONVERSION.get(request.cadence, FPS_CONVERSION_WORKFLOW_RATE),
            ),
            output_root=harvest_staging_root(store),
            cancel=cancel,
            runner=runner,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            inspect=inspect,
            clock=clock,
            compact_timestamps=True,
        )
        if outcome.record is not None:
            staged = Path(str(outcome.record["derived"]["path"]))
        if outcome.status == STATUS_CANCELLED or (cancel is not None and cancel.is_set()):
            return cancelled()
        if not outcome.prepared or outcome.plan is None or outcome.record is None:
            return failed(
                outcome.code or "preparation_failed",
                outcome.message or "The clip could not be prepared.",
            )
        record = outcome.record
        if str(record["original"]["sha256"]) != original_sha:
            return failed(
                "source_changed", "The video changed while it was being prepared. Nothing was kept."
            )
        if outcome.plan.held_frames or outcome.plan.output_frames != plan.output_frames:
            return failed(
                "window_outside",
                "The video has fewer decodable frames than the window needs (a harvested clip never holds "
                "or pads frames). Shorten the window.",
            )

        derived = record["derived"]
        harvest = _finish_record(skeleton, record, plan, list(_source_warnings(facts)))
        annotations = _merged_annotations(request, store, original_sha, source)
        imported = import_video(
            store,
            Path(str(derived["path"])),
            mode=LOCATOR_MANAGED,
            annotations=annotations,
            harvest=harvest,
            cancel=cancel,
        )
        if imported.status == OUTCOME_FAILED:
            if cancel is not None and cancel.is_set():
                return cancelled()
            return failed("library_failed", imported.reason or "The library could not be updated.")
        asset = store.get(imported.asset_id)
        if asset is None or asset.sha256 != str(derived["sha256"]):
            return failed(
                "verification_failed", "The cataloged clip does not match the prepared clip."
            )
        try:
            check = verify_content(asset, store.asset_path(asset), cancel)
        except LibraryError as exc:
            return failed("verification_failed", str(exc))
        if check.state != FILE_OK:
            return failed(
                "verification_failed",
                f"The library copy could not be verified after publication ({check.message}).",
            )
        if imported.status == OUTCOME_DUPLICATE:
            return HarvestOutcome(
                STATUS_DUPLICATE,
                imported.reason,
                "duplicate",
                imported.asset_id,
                asset.harvest or harvest,
                plan,
                harvest.warnings,
                max(0.0, clock() - started),
            )
        return HarvestOutcome(
            STATUS_HARVESTED,
            f"Harvested '{asset.display_name}': {plan.output_frames} frames "
            f"({plan.duration_seconds:.3f} s) from frames {window.start_frame}-{window.end_frame - 1} "
            f"of the original, which was not modified.",
            "",
            asset.asset_id,
            harvest,
            plan,
            harvest.warnings,
            max(0.0, clock() - started),
        )
    except OSError as exc:
        return failed("io_error", f"The harvest could not use the disk: {exc}")
    except HashCancelled:
        return cancelled()
    finally:
        _remove_staged(staged, harvest_staging_root(store))


def _record_skeleton(
    request: HarvestRequest,
    facts: DrivingVideoFacts,
    source: Path,
    original_sha: str,
    start: int,
    end: int,
    plan: CadencePlan,
    created_at: str,
) -> HarvestRecord:
    lineage = request.lineage
    return HarvestRecord(
        original_sha256=original_sha,
        start_frame=start,
        end_frame=end,
        cadence=request.cadence,
        original_path=str(source),
        original_name=source.name,
        original_frame_rate=facts.fps_rational or "",
        original_frame_count=facts.frame_count,
        original_width=facts.display_width,
        original_height=facts.display_height,
        original_rotation_quadrants=facts.rotation_quadrants,
        requested_start=float(request.start),
        requested_end=None if request.end is None else float(request.end),
        requested_unit="seconds" if request.unit == "seconds" else "frames",
        derivative_frames=plan.output_frames,
        derivative_frame_rate=f"{plan.output_rate.numerator}/{plan.output_rate.denominator}",
        omitted_frames=plan.omitted,
        repeated_frames=plan.repeated,
        lineage_state=lineage.state,
        lineage_job_id=lineage.job_id,
        lineage_artifact_path=lineage.artifact_path,
        lineage_artifact_sha256=lineage.artifact_sha256,
        lineage_note=lineage.note,
        created_at=created_at,
    )


def _finish_record(
    skeleton: HarvestRecord, prepared: Mapping[str, Any], plan: CadencePlan, warnings: list[str]
) -> HarvestRecord:
    """The skeleton plus what the verified preparation actually produced."""

    derived = prepared["derived"]
    processing = prepared["processing"]
    method = "ffmpeg {} lossless ({}), {}".format(
        processing.get("video_codec", "libx264"),
        " ".join(str(item) for item in processing.get("encoder_args", ())),
        processing.get("frame_selection", ""),
    )
    return replace(
        skeleton,
        original_frame_rate=str(
            prepared["original"].get("frame_rate") or skeleton.original_frame_rate
        ),
        derivative_frames=int(derived["frames"]),
        derivative_frame_rate=str(derived["frame_rate"]),
        derivative_width=int(derived["width"]),
        derivative_height=int(derived["height"]),
        frame_digest=str(derived.get("frames_md5_sha256") or ""),
        method=clean_text(method, 300),
        tool_version=clean_text(processing.get("tool_version", ""), 160),
        warnings=tuple(warnings + list(plan.lines)),
    )


def _reuse(
    store: MotionLibraryStore,
    existing: MotionAsset,
    plan: CadencePlan,
    started: float,
    clock: Callable[[], float],
    cancel: threading.Event | None,
) -> HarvestOutcome:
    """This exact cut is already cataloged: use it if its file still verifies, never re-encode."""

    try:
        check = verify_content(existing, store.asset_path(existing), cancel)
    except LibraryError as exc:
        return HarvestOutcome(
            STATUS_FAILED_HARVEST, str(exc), "verification_failed", existing.asset_id
        )
    elapsed = max(0.0, clock() - started)
    if check.state == FILE_OK:
        return HarvestOutcome(
            STATUS_REUSED,
            f"'{existing.display_name}' is already this exact cut of the original; it verified and was reused "
            "without re-encoding.",
            "reused",
            existing.asset_id,
            existing.harvest,
            plan,
            elapsed_seconds=elapsed,
        )
    return HarvestOutcome(
        STATUS_FAILED_HARVEST,
        f"'{existing.display_name}' is already this exact cut, but its file did not verify ({check.message}). "
        "Relink it to a file with the same SHA-256 instead of harvesting again.",
        "existing_unverified",
        existing.asset_id,
        existing.harvest,
        plan,
        elapsed_seconds=elapsed,
    )


def _remove_staged(staged: Path | None, root: Path) -> None:
    """Remove this operation's own staged derivative (never anything outside the staging folder)."""

    if staged is None:
        return
    try:
        if os.path.commonpath([os.path.abspath(staged), os.path.abspath(root)]) != os.path.abspath(
            root
        ):
            return
        staged.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def describe_harvest(record: HarvestRecord, *, original_present: bool | None) -> tuple[str, ...]:
    """Operator-facing lines for a harvested asset (detail pane).  ``original_present`` is None when unchecked."""

    rate = parse_rate(record.original_frame_rate)
    presence = (
        ""
        if original_present is None
        else " (a file exists at the recorded path; it is not re-verified)"
        if original_present
        else " (original NOT found at the recorded path; this clip and its record are unaffected, and it "
        "cannot be re-harvested from that file)"
    )
    cadence = (
        "native cadence (every frame kept)"
        if record.cadence == CADENCE_NATIVE
        else f"normalized to 24 fps ({record.omitted_frames} omitted, {record.repeated_frames} repeated)"
    )
    lines = [
        "HARVESTED clip: a reusable window cut from a longer original.",
        f"Original: {record.original_name or 'unnamed'}{presence}",
        f"Original SHA-256: {record.original_sha256}",
        f"Window: source frames {record.start_frame}-{record.end_frame - 1} "
        f"({record.window_frames} frames, end exclusive {record.end_frame}) at {rate_label(rate)}",
        f"Cadence: {cadence}",
        f"Derivative: {record.derivative_frames or '?'} frames at {record.derivative_frame_rate or '?'}, "
        f"{record.derivative_width or '?'} x {record.derivative_height or '?'}",
    ]
    lineage = {
        LINEAGE_VERIFIED: f"Originating job {record.lineage_job_id}: verified (artifact SHA-256 matches).",
        LINEAGE_RECORDED: f"Originating job {record.lineage_job_id}: recorded by History, bytes not independently "
        "verified.",
        "path_only": "Originating job: not established (path only).",
    }.get(record.lineage_state)
    if lineage:
        lines.append(lineage)
    if record.lineage_note:
        lines.append(f"Lineage note: {record.lineage_note}")
    if record.method:
        lines.append(f"Method: {record.method}")
    lines.extend(f"Note: {warning}" for warning in record.warnings)
    return tuple(lines)


__all__ = [
    "HARVEST_CONTRACT_ID",
    "STAGING_DIRNAME",
    "STATUS_CANCELLED_HARVEST",
    "STATUS_DUPLICATE",
    "STATUS_FAILED_HARVEST",
    "STATUS_HARVESTED",
    "STATUS_REFUSED",
    "STATUS_REUSED",
    "HarvestLineage",
    "HarvestOutcome",
    "HarvestRequest",
    "describe_harvest",
    "harvest_contract",
    "harvest_motion",
    "harvest_staging_root",
]
