"""Multi-source Video Workflow batch: assess, freeze and atomically admit (PR-VID-BATCH-200).

"Turn these 1-25 images into independent video jobs with one workflow and one set of settings."
The service sits beside ``VideoWorkflowNjrBuilder`` and adds no scheduler, runner, queue, history or
backend:

1. ``assess`` is read-only.  It validates the form, decodes every source, resolves the catalog's
   declared target size and reports the destination, without publishing anything.
2. ``preview`` runs ``assess`` and, only when every source is accepted, freezes one batch through
   the builder's ``freeze_inputs`` / ``build_job`` (this is the step that may publish StableNew-owned
   prepared PNGs).  Nothing is queued.
3. ``admit`` re-verifies every frozen file and crosses ``JobService.submit_njrs`` exactly once, so
   admission stays all-or-none and the repository transaction remains the only lifecycle authority.

The plan is a transient value; no batch lifecycle is persisted.  The provenance descriptor stamped
into each NJR (``stablenew.batch.v1``) numbers sources from ZERO: ``source_index`` is 0-based and
``source_count`` is the number of accepted sources.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.njr_core_v26 import thaw_json
from src.video.video_execution_resolver import VIDEO_EXECUTION_KEY
from src.video.video_workflow_intent import (
    EXPERIMENTAL_OPT_IN_FIELD,
    default_negative_prompt,
    parse_seed_input,
    requested_controls,
)
from src.video.video_workflow_njr_builder import (
    FrozenVideoInputs,
    SharedFrozenInputs,
    VideoWorkflowNjrBuilder,
    sha256_file,
)
from src.video.workflow_frame_count import (
    approximate_seconds,
    frame_count_policy,
    parse_frame_count,
)
from src.video.workflow_source_preparation import (
    prepared_source_destination,
    resolve_declared_target,
)

MAX_BATCH_SOURCES = 25
BATCH_SCHEMA = "stablenew.batch.v1"
BATCH_KIND = "video_workflow"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
FOLDER_SCAN_LIMIT = 1000  # bounds a scan; more than MAX_BATCH_SOURCES is refused anyway
FOLDER_VISIT_LIMIT = 20000  # bounds the directory walk itself (entries visited, matched or not)
LOW_FREE_SPACE_WARNING_BYTES = 10 * 1024**3
_RGB_BYTES_PER_PIXEL = 3  # upper bound for a prepared PNG; the real file is smaller


class BatchRefused(ValueError):
    """The batch cannot be previewed or admitted; no job was submitted."""


# ---------------------------------------------------------------------------- source selection


@dataclass(frozen=True)
class BatchSource:
    """One requested source: its path plus any lineage a caller (Review) already trusts."""

    path: str
    lineage: Mapping[str, str] = field(default_factory=dict)
    # True only for a Review selection: the image's own StableNew job stamp may then be read as
    # lineage (the same stamp Review's reprocess path trusts).  Other origins invent no parent.
    review_origin: bool = False


@dataclass(frozen=True)
class SourceSelection:
    sources: tuple[BatchSource, ...]
    duplicates_omitted: int = 0
    note: str = ""


def canonical_key(path: str | Path) -> str:
    """Identity of a path for duplicate detection (resolved, case-folded on Windows)."""

    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        resolved = Path(path).expanduser().absolute()
    return os.path.normcase(str(resolved))


def select_sources(
    paths: Iterable[str | Path],
    lineage_by_path: Mapping[str, Mapping[str, str]] | None = None,
    *,
    review_origin: bool = False,
) -> SourceSelection:
    """Keep the operator's order, drop duplicate canonical paths and say how many were dropped."""

    seen: set[str] = set()
    kept: list[BatchSource] = []
    omitted = 0
    hints = dict(lineage_by_path or {})
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        key = canonical_key(text)
        if key in seen:
            omitted += 1
            continue
        seen.add(key)
        hint = hints.get(text) or hints.get(str(Path(text).expanduser())) or {}
        kept.append(
            BatchSource(
                path=str(Path(text).expanduser()),
                lineage=dict(hint),
                review_origin=review_origin,
            )
        )
    return SourceSelection(sources=tuple(kept), duplicates_omitted=omitted)


def scan_folder(folder: str | Path, *, recursive: bool = True) -> SourceSelection:
    """Image files in a folder in a deterministic (case-insensitive relative path) order.

    Recursive by default, matching the Review tab's folder selection; the returned note states
    which traversal was used so the operator is never left to guess."""

    root = Path(folder).expanduser()
    if not root.is_dir():
        raise BatchRefused(f"Folder does not exist: {root}")
    iterator = root.rglob("*") if recursive else root.iterdir()
    found: list[Path] = []
    limited = False
    visited = 0
    for item in iterator:
        visited += 1
        try:
            # Cheap suffix test first: a stat per non-image entry is what makes big trees slow.
            if item.suffix.lower() in IMAGE_SUFFIXES and item.is_file():
                found.append(item)
        except OSError:
            continue
        if len(found) >= FOLDER_SCAN_LIMIT or visited >= FOLDER_VISIT_LIMIT:
            limited = True
            break
    found.sort(key=lambda p: (str(p.relative_to(root)).casefold(), str(p.relative_to(root))))
    scope = "including subfolders" if recursive else "top level only, no subfolders"
    selection = select_sources(found)
    count_text = str(len(selection.sources))
    if limited:
        count_text = (
            f"at least {len(selection.sources)} (the scan stopped early; choose a smaller folder)"
        )
    return replace(
        selection,
        note=f"Folder scan ({scope}): {count_text} image file(s) in {root.name or root}.",
    )


# ---------------------------------------------------------------------------- assessment


@dataclass(frozen=True)
class ControlStatus:
    name: str
    accepted: bool


@dataclass(frozen=True)
class SourceAssessment:
    index: int  # position in the requested list (0-based)
    path: str
    name: str
    lineage: Mapping[str, str] = field(default_factory=dict)
    review_origin: bool = False
    reasons: tuple[str, ...] = ()  # blockers; empty means the source itself is acceptable
    width: int | None = None
    height: int | None = None
    orientation: str = ""
    target: tuple[int, int] | None = None
    sha256: str = ""
    preparation: str = "none"  # "none" | "create" | "reuse"
    prepared_path: str = ""

    @property
    def ready(self) -> bool:
        return not self.reasons


@dataclass(frozen=True)
class BatchAssessment:
    workflow_id: str
    workflow_version: str
    backend_id: str
    governance_state: str
    display_name: str
    experimental: bool
    opt_in_granted: bool
    controls: tuple[ControlStatus, ...]
    prompt: str
    negative_prompt: str
    negative_supported: bool
    frame_count: int | None
    fps: int | None
    approximate_seconds: float | None
    seed_policy: str  # "explicit" | "per_source_random" | "not_declared"
    explicit_seed: int | None
    output_route: str
    output_dir: str
    free_bytes: int | None
    form_error: str
    batch_errors: tuple[str, ...]
    destination_error: str
    warnings: tuple[str, ...]
    notes: tuple[str, ...]
    rows: tuple[SourceAssessment, ...]
    duplicates_omitted: int = 0

    @property
    def blocked_rows(self) -> tuple[SourceAssessment, ...]:
        return tuple(row for row in self.rows if not row.ready)

    @property
    def eligible(self) -> bool:
        return not (
            self.form_error
            or self.batch_errors
            or self.destination_error
            or not self.rows
            or self.blocked_rows
        )

    @property
    def problems(self) -> tuple[str, ...]:
        found = [self.form_error, *self.batch_errors, self.destination_error]
        return tuple(text for text in found if text)


@dataclass(frozen=True)
class BatchJobPreview:
    """One frozen job as the operator sees it before queueing."""

    index: int
    path: str
    name: str
    job_id: str
    seed: int | None
    frame_count: int | None
    prepared_path: str
    prepared_sha256: str
    source_sha256: str


@dataclass(frozen=True)
class BatchPlan:
    """A previewed batch.  Executable (``njrs``) only when every source was accepted and frozen."""

    batch_id: str
    assessment: BatchAssessment
    jobs: tuple[BatchJobPreview, ...] = ()
    njrs: tuple[NormalizedJobRecord, ...] = ()
    frozen: tuple[FrozenVideoInputs, ...] = ()
    shared: SharedFrozenInputs | None = None
    requires_opt_in: bool = False
    digest: str = ""

    @property
    def eligible(self) -> bool:
        return (
            self.assessment.eligible
            and bool(self.njrs)
            and len(self.njrs) == len(self.assessment.rows)
        )

    @property
    def job_ids(self) -> tuple[str, ...]:
        return tuple(job.job_id for job in self.jobs)


@dataclass(frozen=True)
class BatchAdmissionResult:
    batch_id: str
    job_ids: tuple[str, ...]
    sources: tuple[str, ...]
    warning: str = ""


def _plan_digest(batch_id: str, jobs: Sequence[BatchJobPreview]) -> str:
    payload = [
        (j.index, j.job_id, j.source_sha256, j.prepared_sha256, j.seed, j.frame_count) for j in jobs
    ]
    text = json.dumps([batch_id, payload], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _nearest_existing(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _is_writable(folder: Path) -> bool:
    """Real probe (a self-deleting temp file): ``os.access`` ignores Windows ACLs."""

    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def _default_free_bytes(path: str) -> int:
    return int(shutil.disk_usage(path).free)


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GiB"


class VideoWorkflowBatchService:
    """Assess, freeze and admit 1..25 sources as independent jobs of one Video Workflow."""

    def __init__(
        self,
        builder: VideoWorkflowNjrBuilder,
        *,
        free_bytes: Callable[[str], int] = _default_free_bytes,
        embedded_job_id: Callable[[Path], str] | None = None,
    ) -> None:
        self._builder = builder
        self._free_bytes = free_bytes
        self._embedded_job_id = embedded_job_id or _read_embedded_job_id
        self._admitted: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ assessment (read-only)

    def assess(
        self,
        form_data: Mapping[str, Any],
        sources: Sequence[BatchSource],
        *,
        duplicates_omitted: int = 0,
    ) -> BatchAssessment:
        form = dict(form_data)
        ok, form_error = self._builder.validate_form_data(form)
        spec: Any = None
        try:
            spec = self._builder.spec_for(form)
        except Exception:
            spec = None  # validate_form_data already carries the operator-readable reason
        output_dir = self._builder.output_dir()
        output_route = str(form.get("output_route") or "").strip()

        batch_errors: list[str] = []
        if not sources:
            batch_errors.append("Select 1 to 25 source images.")
        elif len(sources) > MAX_BATCH_SOURCES:
            extra = len(sources) - MAX_BATCH_SOURCES
            batch_errors.append(
                f"{len(sources)} sources are selected; one batch accepts 1 to {MAX_BATCH_SOURCES}. "
                f"Exclude at least {extra} (nothing was dropped for you)."
            )

        policy = None
        if spec is not None:
            candidate = (getattr(spec, "backend_defaults", None) or {}).get("source_preparation")
            policy = candidate if isinstance(candidate, Mapping) else None

        rows: list[SourceAssessment] = []
        for index, source in enumerate(sources):
            rows.append(self._assess_source(index, source, policy, output_dir))
        rows_t = tuple(rows)

        warnings: list[str] = []
        notes: list[str] = []
        hashes: dict[str, list[int]] = {}
        for row in rows_t:
            if row.sha256:
                hashes.setdefault(row.sha256, []).append(row.index + 1)
        for positions in hashes.values():
            if len(positions) > 1:
                joined = ", ".join(str(p) for p in positions)
                warnings.append(
                    f"Sources {joined} have identical image content; they will produce "
                    "separate jobs with the same input."
                )
        if duplicates_omitted:
            notes.append(f"{duplicates_omitted} duplicate path(s) were omitted from the selection.")

        needed, destination_error, free = self._destination(output_dir, rows_t, warnings)

        controls: tuple[ControlStatus, ...] = ()
        prompt = str(form.get("prompt") or "").strip()
        negative = str(form.get("negative_prompt") or "").strip()
        negative_supported = False
        frame_count: int | None = None
        fps: int | None = None
        seconds: float | None = None
        seed_policy = "not_declared"
        explicit_seed: int | None = None
        opt_in = False
        if spec is not None:
            accepted = set(spec.accepted_controls)
            controls = tuple(
                ControlStatus(name=name, accepted=name in accepted)
                for name in requested_controls(spec, form)
            )
            negative_supported = "negative_prompt" in spec.declared_input_names
            if negative_supported:
                negative = negative or default_negative_prompt(spec)
            else:
                negative = ""
            length = frame_count_policy(spec)
            if length is not None:
                try:
                    frame_count = parse_frame_count(spec, form.get("frame_count"))
                    fps = length["fps"]
                    seconds = approximate_seconds(frame_count, fps)
                except ValueError:
                    pass  # surfaced by validate_form_data as the form error
            if "seed" in spec.declared_input_names:
                try:
                    explicit_seed = parse_seed_input(form.get("seed"))
                except ValueError:
                    explicit_seed = None
                seed_policy = "explicit" if explicit_seed is not None else "per_source_random"
            opt_in = form.get(EXPERIMENTAL_OPT_IN_FIELD) is True
            runtime_policy = (getattr(spec, "backend_defaults", None) or {}).get("runtime_policy")
            if isinstance(runtime_policy, Mapping) and runtime_policy.get(
                "release_owned_runtime_after_job"
            ):
                notes.append(
                    "This workflow releases the StableNew-owned Comfy runtime after each job, "
                    "so each job starts it again."
                )
            if policy is not None and needed:
                notes.append(
                    "Queueing a preview prepares source images: up to "
                    f"{_format_bytes(needed)} of StableNew-owned PNGs under "
                    f"{Path(output_dir) / 'prepared_video_sources'} (existing prepared images are reused)."
                )
        notes.append(
            "Video output size varies with backend, codec, resolution and frame count; "
            "no clip-size forecast is made."
        )
        notes.append(
            "'Eligible to queue' means the software and admission checks pass; it is not a "
            "qualification of this GPU or runtime."
        )
        return BatchAssessment(
            workflow_id=str(getattr(spec, "workflow_id", "") or form.get("workflow_id") or ""),
            workflow_version=str(getattr(spec, "workflow_version", "") or ""),
            backend_id=str(getattr(spec, "backend_id", "") or ""),
            governance_state=str(getattr(spec, "governance_state", "") or ""),
            display_name=str(getattr(spec, "display_name", "") or ""),
            experimental=bool(getattr(spec, "is_experimental", False)),
            opt_in_granted=opt_in,
            controls=controls,
            prompt=prompt,
            negative_prompt=negative,
            negative_supported=negative_supported,
            frame_count=frame_count,
            fps=fps,
            approximate_seconds=seconds,
            seed_policy=seed_policy,
            explicit_seed=explicit_seed,
            output_route=output_route,
            output_dir=output_dir,
            free_bytes=free,
            form_error="" if ok else str(form_error or "The Video Workflow form is invalid."),
            batch_errors=tuple(batch_errors),
            destination_error=destination_error,
            warnings=tuple(warnings),
            notes=tuple(notes),
            rows=rows_t,
            duplicates_omitted=duplicates_omitted,
        )

    def _assess_source(
        self, index: int, source: BatchSource, policy: Mapping[str, Any] | None, output_dir: str
    ) -> SourceAssessment:
        path = Path(source.path).expanduser()
        base = SourceAssessment(
            index=index,
            path=str(path),
            name=path.name,
            lineage=dict(source.lineage),
            review_origin=source.review_origin,
        )
        reasons: list[str] = []
        valid, reason = self._builder.validate_source_image(path)
        if not valid:
            return replace(base, reasons=(reason or f"Source image is missing: {path}",))
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            return replace(
                base,
                reasons=(f"Unsupported source file type '{path.suffix or '(none)'}'.",),
            )
        try:
            with Image.open(path) as opened:
                opened.load()  # decode fully: a truncated file fails here, not mid-queue
                width, height = ImageOps.exif_transpose(opened).size
        except Exception as exc:
            return replace(base, reasons=(f"Unreadable image: {exc}",))
        if width <= 0 or height <= 0:
            return replace(base, reasons=("Image dimensions must be positive.",))
        try:
            digest = sha256_file(path)
        except OSError as exc:
            return replace(base, reasons=(f"Source cannot be read: {exc}",))

        orientation = (
            "landscape" if width > height else ("portrait" if height > width else "square")
        )
        target: tuple[int, int] | None = None
        preparation = "none"
        prepared_path = str(path)
        if policy is not None:
            try:
                orientation, target_dims, _rule = resolve_declared_target(policy, width, height)
                target = (target_dims["width"], target_dims["height"])
                destination = prepared_source_destination(output_dir, digest, target_dims)
                prepared_path = str(destination)
                preparation = "reuse" if destination.exists() else "create"
            except ValueError as exc:
                reasons.append(str(exc))
        return replace(
            base,
            reasons=tuple(reasons),
            width=int(width),
            height=int(height),
            orientation=orientation,
            target=target,
            sha256=digest,
            preparation=preparation,
            prepared_path=prepared_path,
        )

    def _destination(
        self, output_dir: str, rows: Sequence[SourceAssessment], warnings: list[str]
    ) -> tuple[int, str, int | None]:
        """(bytes preparation may need, blocking error, free bytes) for the output volume."""

        needed = 0
        counted: set[str] = set()
        for row in rows:
            if row.preparation == "create" and row.target and row.prepared_path not in counted:
                counted.add(row.prepared_path)
                needed += row.target[0] * row.target[1] * _RGB_BYTES_PER_PIXEL
        root = Path(output_dir).expanduser()
        if root.exists() and not root.is_dir():
            return needed, f"The output location is not a folder: {root}", None
        anchor = _nearest_existing(root)
        if not anchor.is_dir() or not _is_writable(anchor):
            return needed, f"The output location is not writable: {root}", None
        try:
            free = self._free_bytes(str(anchor))
        except OSError as exc:
            warnings.append(f"Free space on the output volume could not be determined: {exc}")
            return needed, "", None
        if needed and free < needed:
            return (
                needed,
                f"Not enough free space to prepare the source images: {_format_bytes(free)} "
                f"free, up to {_format_bytes(needed)} needed.",
                free,
            )
        if free < LOW_FREE_SPACE_WARNING_BYTES:
            warnings.append(
                f"Only {_format_bytes(free)} is free on the output volume; sustained video "
                "generation may run out of space."
            )
        return needed, "", free

    # ------------------------------------------------------------------ preview (prepare + freeze)

    def preview(
        self,
        form_data: Mapping[str, Any],
        sources: Sequence[BatchSource],
        *,
        duplicates_omitted: int = 0,
    ) -> BatchPlan:
        """Assess; when everything is accepted, prepare and freeze one NJR per source."""

        form = dict(form_data)
        assessment = self.assess(form, sources, duplicates_omitted=duplicates_omitted)
        batch_id = uuid.uuid4().hex
        if not assessment.eligible:
            return BatchPlan(batch_id=batch_id, assessment=assessment)

        spec = self._builder.spec_for(form)
        try:
            shared = self._builder.freeze_shared_inputs(form)
        except ValueError as exc:
            return BatchPlan(batch_id=batch_id, assessment=replace(assessment, form_error=str(exc)))

        count = len(assessment.rows)
        rows: list[SourceAssessment] = []
        jobs: list[BatchJobPreview] = []
        njrs: list[NormalizedJobRecord] = []
        frozen_all: list[FrozenVideoInputs] = []
        for row in assessment.rows:
            try:
                frozen = self._builder.freeze_inputs(row.path, form, shared=shared)
                if frozen.source_sha256 != row.sha256:
                    raise ValueError("The source changed while the preview was being built.")
                lineage = self._lineage(row)
                built = self._builder.build_job(
                    form,
                    frozen,
                    batch={
                        "schema": BATCH_SCHEMA,
                        "batch_id": batch_id,
                        "batch_kind": BATCH_KIND,
                        "source_index": row.index,
                        "source_count": count,
                    },
                    lineage=lineage,
                )
            except (ValueError, OSError) as exc:
                rows.append(replace(row, reasons=(str(exc),)))
                continue
            rows.append(row)
            frozen_all.append(frozen)
            njrs.append(built.njr)
            jobs.append(
                BatchJobPreview(
                    index=row.index,
                    path=row.path,
                    name=row.name,
                    job_id=built.njr.job_id,
                    seed=built.seed,
                    frame_count=built.frame_count,
                    prepared_path=frozen.prepared_source_path,
                    prepared_sha256=frozen.prepared_source_sha256,
                    source_sha256=frozen.source_sha256,
                )
            )
        assessment = replace(assessment, rows=tuple(rows))
        if not assessment.eligible:
            # All-or-none: a single source that failed to freeze leaves no executable batch.
            return BatchPlan(batch_id=batch_id, assessment=assessment)
        return BatchPlan(
            batch_id=batch_id,
            assessment=assessment,
            jobs=tuple(jobs),
            njrs=tuple(njrs),
            frozen=tuple(frozen_all),
            shared=shared,
            requires_opt_in=bool(getattr(spec, "is_experimental", False)),
            digest=_plan_digest(batch_id, jobs),
        )

    def _lineage(self, row: SourceAssessment) -> dict[str, str]:
        """Only identifiers a caller supplied or the image itself embeds; never an invented parent."""

        lineage = {k: str(v) for k, v in dict(row.lineage).items() if v}
        if row.review_origin and not lineage.get("source_job_id"):
            try:
                embedded = str(self._embedded_job_id(Path(row.path)) or "").strip()
            except Exception:
                embedded = ""
            if embedded:
                lineage["source_job_id"] = embedded
        return lineage

    # ------------------------------------------------------------------ admission

    def admit(self, plan: BatchPlan, job_service: Any) -> BatchAdmissionResult:
        """Re-verify frozen inputs, then cross ``JobService.submit_njrs`` exactly once."""

        if not plan.eligible:
            raise BatchRefused("This batch preview is not eligible to queue; nothing was queued.")
        if _plan_digest(plan.batch_id, plan.jobs) != plan.digest:
            raise BatchRefused("The batch preview no longer matches its frozen digest.")
        self._check_consistency(plan)
        with self._lock:
            if plan.batch_id in self._admitted:
                raise BatchRefused("This batch was already queued; nothing new was queued.")
            self._admitted.add(plan.batch_id)
        try:
            try:
                for frozen in plan.frozen:
                    self._builder.verify_unchanged(frozen, include_shared=False)
                if plan.shared is not None:
                    self._builder.verify_shared_unchanged(plan.shared)
            except ValueError as exc:
                raise BatchRefused(f"{exc}. Build the preview again; nothing was queued.") from exc
            submit = getattr(job_service, "submit_njrs", None)
            if not callable(submit):
                raise RuntimeError("JobService.submit_njrs is unavailable")
            ids = list(plan.job_ids)
            if _durable_ids(job_service, ids):
                raise BatchRefused(
                    "A job from this batch already exists in the queue; nothing new was queued."
                )
            try:
                submitted = submit(list(plan.njrs), SubmissionPolicy())
            except Exception as exc:
                present = _durable_ids(job_service, ids)
                if present and len(present) == len(ids):
                    # The repository transaction committed; only post-admission work failed.
                    return BatchAdmissionResult(
                        batch_id=plan.batch_id,
                        job_ids=tuple(ids),
                        sources=tuple(row.path for row in plan.assessment.rows),
                        warning=f"Jobs were admitted, but a follow-up step reported: {exc}",
                    )
                if present:
                    raise BatchRefused(
                        f"Admission reported an error and {len(present)} of {len(ids)} jobs "
                        f"are present; check Queue / History: {exc}"
                    ) from exc
                raise BatchRefused(f"Queue admission failed; nothing was queued: {exc}") from exc
            admitted = [str(job_id) for job_id in (submitted or [])]
            if admitted != ids:
                raise BatchRefused(
                    f"Admission returned {len(admitted)} job id(s) for {len(ids)} sources; "
                    "check Queue / History."
                )
            return BatchAdmissionResult(
                batch_id=plan.batch_id,
                job_ids=tuple(admitted),
                sources=tuple(row.path for row in plan.assessment.rows),
            )
        except BaseException:
            with self._lock:
                self._admitted.discard(plan.batch_id)
            raise

    @staticmethod
    def _check_consistency(plan: BatchPlan) -> None:
        """Fail closed unless the NJRs still describe exactly this batch."""

        ids = [njr.job_id for njr in plan.njrs]
        if len(set(ids)) != len(ids):
            raise BatchRefused("Batch jobs must have distinct identities.")
        count = len(plan.njrs)
        for position, njr in enumerate(plan.njrs):
            descriptor = dict(thaw_json(njr.provenance.metadata).get("batch") or {})
            expected = {
                "schema": BATCH_SCHEMA,
                "batch_id": plan.batch_id,
                "batch_kind": BATCH_KIND,
                "source_index": position,
                "source_count": count,
            }
            if descriptor != expected:
                raise BatchRefused(f"Job {position + 1} does not carry this batch's identity.")
            block = njr.config["video_workflow"][VIDEO_EXECUTION_KEY]
            if plan.requires_opt_in and block.get(EXPERIMENTAL_OPT_IN_FIELD) is not True:
                raise BatchRefused("This experimental workflow needs its explicit per-job opt-in.")


def _durable_ids(job_service: Any, ids: Sequence[str]) -> list[str]:
    queue = getattr(job_service, "job_queue", None)
    getter = getattr(queue, "get_job", None)
    if not callable(getter):
        return []
    present: list[str] = []
    for job_id in ids:
        try:
            if getter(job_id) is not None:
                present.append(job_id)
        except Exception:
            continue
    return present


def _read_embedded_job_id(path: Path) -> str:
    from src.utils.image_metadata import ImageMetadataContractV26, read_image_metadata

    return str(read_image_metadata(path).get(ImageMetadataContractV26.KEY_JOB_ID) or "")


__all__ = [
    "BATCH_KIND",
    "BATCH_SCHEMA",
    "FOLDER_SCAN_LIMIT",
    "IMAGE_SUFFIXES",
    "MAX_BATCH_SOURCES",
    "BatchAdmissionResult",
    "BatchAssessment",
    "BatchJobPreview",
    "BatchPlan",
    "BatchRefused",
    "BatchSource",
    "ControlStatus",
    "SourceAssessment",
    "SourceSelection",
    "VideoWorkflowBatchService",
    "canonical_key",
    "scan_folder",
    "select_sources",
]
