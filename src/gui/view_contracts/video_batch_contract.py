"""Toolkit-neutral state for the Video Workflow multi-source batch section (PR-VID-BATCH-200).

The session holds only transient, unsaved state: the requested source list, how it was chosen and
the most recent preview.  It owns no batch authority: assessing, preparing and queueing are
delegated to injected callables (the Video Workflow controller), and it never builds a backend
payload, touches the queue or names a workflow/model.

Previewing hashes and decodes files, prepares source images and builds NJRs, and queueing
re-verifies frozen files, so neither runs inline on the Tk thread.  Each is split into
``begin_*`` (UI thread: claims the busy state and snapshots plain inputs), ``run_*`` (worker
thread: touches no session state) and ``finish_*`` (UI thread: applies the result unless a newer
edit made it stale), exactly like ``VideoExperimentSession``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.gui.view_contracts.video_experiment_contract import WorkOutcome

MAX_BATCH_SOURCES = 25  # mirrors the service limit; the service remains the authority


@dataclass(frozen=True)
class BatchRowView:
    index: int
    name: str
    path: str
    status: str  # "pending" | "ready" | "frozen" | "blocked"
    detail: str

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"


@dataclass(frozen=True)
class BatchPreviewView:
    batch_id: str
    eligible: bool
    frozen: bool
    headline: str
    rows: tuple[BatchRowView, ...]
    summary: tuple[tuple[str, str], ...]
    problems: tuple[str, ...]
    warnings: tuple[str, ...]
    notes: tuple[str, ...]
    blocked_indices: tuple[int, ...]


@dataclass(frozen=True)
class BatchPreviewWork:
    token: int
    sources: tuple[Any, ...]
    duplicates_omitted: int
    form_data: dict[str, Any]
    fingerprint: str


@dataclass(frozen=True)
class BatchQueueWork:
    plan: Any


@dataclass(frozen=True)
class FolderScanWork:
    folder: str
    recursive: bool


def _dims(row: Any) -> str:
    if row.width and row.height:
        return f"{row.width}x{row.height} {row.orientation}"
    return "size unknown"


def _row_view(row: Any, job: Any | None) -> BatchRowView:
    if row.reasons:
        return BatchRowView(row.index, row.name, row.path, "blocked", "; ".join(row.reasons))
    detail = _dims(row)
    if row.target:
        action = {"create": "prepared image will be created", "reuse": "prepared image reused"}.get(
            row.preparation, ""
        )
        detail += f" -> {row.target[0]}x{row.target[1]}" + (f" ({action})" if action else "")
    if job is None:
        return BatchRowView(row.index, row.name, row.path, "ready", detail)
    seed = "n/a" if job.seed is None else str(job.seed)
    return BatchRowView(
        row.index, row.name, row.path, "frozen", f"{detail}; seed {seed}; job {job.job_id[:8]}"
    )


def _summary(assessment: Any, batch_id: str, frozen: bool) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    if assessment.workflow_id:
        name = assessment.display_name or assessment.workflow_id
        rows.append(
            ("Workflow", f"{name} ({assessment.workflow_id}@{assessment.workflow_version})")
        )
        rows.append(
            ("Backend", f"{assessment.backend_id}; governance {assessment.governance_state}")
        )
        if assessment.experimental:
            rows.append(
                (
                    "Experimental opt-in",
                    "granted for these jobs" if assessment.opt_in_granted else "NOT granted",
                )
            )
    if assessment.controls:
        rows.append(
            (
                "Controls",
                ", ".join(
                    c.name if c.accepted else f"{c.name} (NOT accepted)"
                    for c in assessment.controls
                ),
            )
        )
    if assessment.prompt:
        rows.append(("Prompt", assessment.prompt))
    if assessment.negative_supported and assessment.negative_prompt:
        rows.append(("Negative", assessment.negative_prompt))
    if assessment.frame_count is not None:
        rows.append(
            (
                "Length",
                f"{assessment.frame_count} frames (~{assessment.approximate_seconds} s at "
                f"{assessment.fps} fps)",
            )
        )
    seed_text = {
        "explicit": f"{assessment.explicit_seed} (the same for every job)",
        "per_source_random": (
            "a concrete seed per source, frozen when the preview is prepared"
            if not frozen
            else "a concrete seed per source (shown per job)"
        ),
        "not_declared": "not used by this workflow",
    }[assessment.seed_policy]
    rows.append(("Seeds", seed_text))
    if assessment.output_route:
        rows.append(("Output route", assessment.output_route))
    rows.append(("Output folder", assessment.output_dir))
    if assessment.free_bytes is not None:
        rows.append(("Free space", f"{assessment.free_bytes / 1024**3:.1f} GiB"))
    rows.append(("Sources", str(len(assessment.rows))))
    if frozen:
        rows.append(("Batch", batch_id))
    return tuple(rows)


def build_preview_view(plan: Any) -> BatchPreviewView:
    assessment = plan.assessment
    jobs = {job.index: job for job in plan.jobs}
    rows = tuple(_row_view(row, jobs.get(row.index)) for row in assessment.rows)
    blocked = tuple(view.index for view in rows if view.blocked)
    frozen = bool(plan.njrs)
    count = len(assessment.rows)
    if plan.eligible:
        headline = (
            f"Eligible to queue: {count} independent video job(s) "
            "(software and admission checks only)."
        )
    elif blocked:
        headline = (
            f"Blocked: {len(blocked)} of {count} source(s) need attention. Nothing can be queued "
            "until they are excluded and a fresh preview is built."
        )
    elif assessment.problems:
        headline = "Blocked: " + assessment.problems[0]
    else:
        headline = "Not eligible to queue."
    return BatchPreviewView(
        batch_id=plan.batch_id,
        eligible=plan.eligible,
        frozen=frozen,
        headline=headline,
        rows=rows,
        summary=_summary(assessment, plan.batch_id, frozen),
        problems=tuple(assessment.problems),
        warnings=tuple(assessment.warnings),
        notes=tuple(assessment.notes),
        blocked_indices=blocked,
    )


class VideoBatchSession:
    """View-model for one Video Workflow tab's multi-source section."""

    def __init__(
        self,
        *,
        build_preview: Callable[..., Any],
        submit_plan: Callable[[Any], Any],
        select_sources: Callable[..., Any],
        scan_folder: Callable[..., Any],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._build_preview = build_preview
        self._submit_plan = submit_plan
        self._select_sources = select_sources
        self._scan_folder = scan_folder
        self._on_change = on_change
        self.sources: list[Any] = []
        self.duplicates_omitted = 0
        self.origin = ""  # "files" | "folder" | "review" | ""
        self.note = ""
        self.message = ""
        self.preview: BatchPreviewView | None = None
        self.busy: str | None = None  # "preview" | "queue" while a worker is outstanding
        self.last_result: Any = None
        self._plan: Any = None
        self._fingerprint = ""
        self._token = 0

    # ------------------------------------------------------------------ source list

    @property
    def active(self) -> bool:
        """Batch mode: at least one source was chosen; otherwise the single-image path rules."""

        return bool(self.sources)

    @property
    def count(self) -> int:
        return len(self.sources)

    @property
    def over_limit(self) -> bool:
        return self.count > MAX_BATCH_SOURCES

    @property
    def source_text(self) -> str:
        if not self.sources:
            return "Single image mode: the Source Image above is queued as one job."
        origin = {"files": "selected files", "folder": "folder", "review": "Review selection"}.get(
            self.origin, "selection"
        )
        text = f"Batch mode: {self.count} source image(s) from {origin}."
        if self.duplicates_omitted:
            text += f" {self.duplicates_omitted} duplicate path(s) omitted."
        if self.over_limit:
            text += (
                f" Exclude at least {self.count - MAX_BATCH_SOURCES} - one batch accepts "
                f"1 to {MAX_BATCH_SOURCES}; nothing is dropped for you."
            )
        return text

    def choose_files(self, paths: Sequence[str]) -> bool:
        return self._apply(self._select_sources(list(paths)), "files")

    def begin_scan(self, folder: str, *, recursive: bool = True) -> FolderScanWork | None:
        """UI thread: claim the busy state for a folder walk (which can be slow on big trees)."""

        if self.busy:
            self._set_message(f"{self.busy_text} Wait for it to finish.")
            return None
        self.busy = "scan"
        self._set_message("")
        return FolderScanWork(folder=str(folder), recursive=bool(recursive))

    def run_scan(self, work: FolderScanWork) -> WorkOutcome:
        """Worker thread: walks the folder; touches no session or Tk state."""

        try:
            return WorkOutcome(value=self._scan_folder(work.folder, recursive=work.recursive))
        except Exception as exc:
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def finish_scan(self, work: FolderScanWork, outcome: WorkOutcome) -> bool:
        """UI thread: adopt the scanned list (a refused or empty scan leaves the list unchanged)."""

        self.busy = None
        if outcome.error:
            self._set_message(outcome.error)
            return False
        return self._apply(outcome.value, "folder")

    def choose_folder(self, folder: str, *, recursive: bool = True) -> bool:
        """Synchronous composition of the scan steps (the Tk panel runs them off-thread)."""

        work = self.begin_scan(folder, recursive=recursive)
        if work is None:
            return False
        return self.finish_scan(work, self.run_scan(work))

    def choose_review(
        self, paths: Sequence[str], lineage_by_path: Mapping[str, Mapping[str, str]] | None = None
    ) -> bool:
        selection = self._select_sources(list(paths), lineage_by_path, review_origin=True)
        return self._apply(selection, "review")

    def exclude(self, indices: Sequence[int]) -> int:
        """Remove sources by position; the preview must then be rebuilt."""

        wanted = {int(i) for i in indices if 0 <= int(i) < len(self.sources)}
        if not wanted or self.busy:
            return 0
        self.sources = [s for i, s in enumerate(self.sources) if i not in wanted]
        self._clear_preview(
            f"Excluded {len(wanted)} source(s); build a fresh preview of the revised list."
            if self.sources
            else "All sources were excluded; back to single image mode."
        )
        if not self.sources:
            self.origin = ""
            self.note = ""
            self.duplicates_omitted = 0
        return len(wanted)

    def exclude_blocked(self) -> int:
        if self.preview is None:
            return 0
        return self.exclude(self.preview.blocked_indices)

    def clear(self) -> None:
        if self.busy:
            return
        self.sources = []
        self.origin = ""
        self.note = ""
        self.duplicates_omitted = 0
        self.last_result = None
        self._clear_preview("Batch cleared; single image mode.")

    def _apply(self, selection: Any, origin: str) -> bool:
        if self.busy:
            self._set_message(f"{self.busy_text} Wait for it to finish.")
            return False
        if not selection.sources:
            self._set_message("No usable images were found; the source list is unchanged.")
            return False
        self.sources = list(selection.sources)
        self.duplicates_omitted = int(selection.duplicates_omitted)
        self.origin = origin
        self.note = str(selection.note or "")
        self.last_result = None
        text = f"{len(self.sources)} source image(s) ready to preview."
        if self.note:
            text = f"{self.note} {text}"
        self._clear_preview(text)
        return True

    # ------------------------------------------------------------------ preview / queue

    @property
    def preview_valid(self) -> bool:
        return self._plan is not None and bool(self._plan.eligible)

    @property
    def busy_text(self) -> str:
        return {
            "preview": "Preparing sources and building the preview...",
            "queue": "Verifying files and queueing the batch...",
            "scan": "Scanning the folder...",
        }.get(self.busy or "", "")

    @property
    def status_text(self) -> str:
        return self.message or self.busy_text

    def _fingerprint_of(self, form_data: Mapping[str, Any]) -> str:
        form = {k: v for k, v in dict(form_data).items() if k != "source_image_path"}
        return json.dumps(
            {
                "sources": [[str(s.path), dict(s.lineage)] for s in self.sources],
                "form": form,
            },
            sort_keys=True,
            default=str,
        )

    def begin_preview(self, form_data: Mapping[str, Any]) -> BatchPreviewWork | None:
        """UI thread: claim the busy state and snapshot the inputs, or None with a reason."""

        if self.busy:
            self._set_message(f"{self.busy_text} Wait for it to finish.")
            return None
        if not self.sources:
            self._set_message(
                "Choose source images first (Select Images, Select Folder or Review)."
            )
            return None
        self._clear_preview("")
        work = BatchPreviewWork(
            token=self._token,
            sources=tuple(self.sources),
            duplicates_omitted=self.duplicates_omitted,
            form_data=copy.deepcopy(dict(form_data)),
            fingerprint=self._fingerprint_of(form_data),
        )
        self.busy = "preview"
        self._set_message("")
        return work

    def run_preview(self, work: BatchPreviewWork) -> WorkOutcome:
        """Worker thread: only the plain snapshot is used; no session or Tk state is touched."""

        try:
            plan = self._build_preview(
                sources=list(work.sources),
                form_data=work.form_data,
                duplicates_omitted=work.duplicates_omitted,
            )
        except Exception as exc:
            return WorkOutcome(error=str(exc) or type(exc).__name__)
        return WorkOutcome(value=plan)

    def finish_preview(
        self, work: BatchPreviewWork, outcome: WorkOutcome, current_form: Mapping[str, Any]
    ) -> bool:
        """UI thread: accept the result only if no edit happened since ``begin_preview``."""

        self.busy = None
        if work.token != self._token or self._fingerprint_of(current_form) != work.fingerprint:
            self._clear_preview(
                "The sources or form changed while the preview was building; build it again."
            )
            return False
        if outcome.error:
            self._set_message(f"Preview failed: {outcome.error}")
            return False
        plan = outcome.value
        self._plan = plan
        self.preview = build_preview_view(plan)
        self._fingerprint = work.fingerprint
        if plan.eligible:
            self._set_message(
                "Preview ready. Source images were prepared and frozen; nothing is queued until "
                "you press Queue Batch."
            )
        else:
            self._set_message(self.preview.headline)
        return True

    def invalidate_if_changed(self, form_data: Mapping[str, Any]) -> bool:
        """Drop a preview whose inputs no longer match the form; True when dropped."""

        if self._plan is None and self.preview is None:
            return False
        if self._fingerprint_of(form_data) == self._fingerprint:
            return False
        self._clear_preview("The sources or form changed after the preview; build it again.")
        return True

    def begin_queue(self, form_data: Mapping[str, Any]) -> BatchQueueWork | None:
        """UI thread: claim the busy state for ONE admission of the current eligible preview."""

        if self.busy:
            self._set_message(f"{self.busy_text} Wait for it to finish.")
            return None
        if self._plan is None or not self._plan.eligible:
            self._set_message("Build an eligible preview first; blocked sources must be excluded.")
            return None
        if self.invalidate_if_changed(form_data):
            return None
        self.busy = "queue"
        self._set_message("")
        return BatchQueueWork(plan=self._plan)

    def run_queue(self, work: BatchQueueWork) -> WorkOutcome:
        """Worker thread: re-verify every frozen file and admit once."""

        try:
            return WorkOutcome(value=self._submit_plan(work.plan))
        except Exception as exc:
            return WorkOutcome(error=str(exc) or type(exc).__name__)

    def finish_queue(self, work: BatchQueueWork, outcome: WorkOutcome) -> list[str]:
        """UI thread: report the admission (or the refusal; nothing was queued)."""

        self.busy = None
        if outcome.error:
            self._clear_preview(f"Queue refused: {outcome.error}")
            return []
        result = outcome.value
        self.last_result = result
        self._clear_preview("")
        ids = list(result.job_ids)
        shown = ", ".join(ids[:3]) + (f", ... (+{len(ids) - 3} more)" if len(ids) > 3 else "")
        text = (
            f"Queued {len(ids)} video job(s) as batch {result.batch_id}: {shown}. "
            "Follow progress and results in Queue / History."
        )
        if getattr(result, "warning", ""):
            text += f" Note: {result.warning}"
        self._set_message(text)
        return ids

    def build_preview(self, form_data: Mapping[str, Any]) -> bool:
        """Synchronous composition of the preview steps (the Tk panel runs them off-thread)."""

        work = self.begin_preview(form_data)
        if work is None:
            return False
        return self.finish_preview(work, self.run_preview(work), form_data)

    def queue(self, form_data: Mapping[str, Any]) -> list[str]:
        """Synchronous composition of the queue steps (the Tk panel runs them off-thread)."""

        work = self.begin_queue(form_data)
        if work is None:
            return []
        return self.finish_queue(work, self.run_queue(work))

    # ------------------------------------------------------------------ internals

    def _clear_preview(self, message: str) -> None:
        self._token += 1  # any in-flight preview result is now stale
        self._plan = None
        self.preview = None
        self._fingerprint = ""
        self._set_message(message)

    def _set_message(self, message: str) -> None:
        self.message = message
        if self._on_change is not None:
            self._on_change()


__all__ = [
    "BatchPreviewView",
    "BatchPreviewWork",
    "BatchQueueWork",
    "BatchRowView",
    "FolderScanWork",
    "MAX_BATCH_SOURCES",
    "VideoBatchSession",
    "build_preview_view",
]
