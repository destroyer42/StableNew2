"""Toolkit-neutral session for the Queue/History "Batches" view (PR-BATCH-OPS-201).

All state, derivation and action gating live here so they are testable without Tk. Blocking work is delegated to
``BatchOperationsService`` through the existing ``BackgroundWorkRunner`` (off the UI thread); every completion
callback runs on the UI thread and is dropped when the session was closed or a newer request superseded it, so a
stale background result can never overwrite newer selection or state. Dialogs and hand-offs are injected hooks.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import PurePath
from typing import Any

from src.controller.content_visibility_resolver import REDACTED_TEXT, ContentVisibilityResolver
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome
from src.queue.batch_membership import KIND_LABELS, BatchKey
from src.queue.batch_projection import BatchJobView, BatchSummary, OutputKind
from src.queue.failure_triage import CATEGORY_LABELS, TriageCategory
from src.queue.job_model import JobStatus

MAX_LISTED_OUTPUTS = 8
_SEPARATORS = re.compile(r"[_\-./\\]+")


@dataclass(frozen=True)
class ActionState:
    enabled: bool
    #: Why the action is unavailable, or what it will do when enabled (used as the button's tooltip).
    reason: str


@dataclass(frozen=True)
class BatchRow:
    token: str
    kind: str
    short_id: str
    jobs: str
    state: str
    progress: str
    note: str


@dataclass(frozen=True)
class JobRow:
    job_id: str
    position: str
    source: str
    model: str
    status: str
    priority: str
    failure: str
    outputs: str
    retry: str


@dataclass
class BatchViewHooks:
    """Tk-side effects, injected by the view. Every hook runs on the UI thread."""

    confirm_cancel: Callable[[Any], bool] = lambda plan: False
    #: Shows the retry review; returns the acknowledged job ids to submit, or ``None`` to abort.
    review_retry: Callable[[Any], tuple[str, ...] | None] = lambda plan: None
    open_in_review: Callable[[tuple[str, ...]], int] = lambda paths: 0
    open_folder: Callable[[str], None] = lambda path: None
    open_movie_clips: Callable[[dict[str, Any]], None] = lambda bundle: None


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "-"


def _finished(summary: BatchSummary) -> int:
    counts = summary.counts
    return counts.completed + counts.failed + counts.cancelled


class BatchOperationsSession:
    def __init__(
        self,
        *,
        service: Any,
        runner: BackgroundWorkRunner,
        hooks: BatchViewHooks | None = None,
        on_change: Callable[[], None] | None = None,
        visibility_mode: Callable[[], Any] | None = None,
    ) -> None:
        self._service = service
        self._visibility_mode = visibility_mode or (lambda: "nsfw")
        self._runner = runner
        self.hooks = hooks or BatchViewHooks()
        self._on_change = on_change or (lambda: None)
        self.snapshot: Any = None
        self.detail: BatchSummary | None = None
        self.selected_key: BatchKey | None = None
        self.selected_ids: tuple[str, ...] = ()
        self.status_filter: JobStatus | None = None
        self.category_filter: TriageCategory | None = None
        self.busy = ""
        self._message = ""
        self.loading = False
        self._closed = False
        self._refresh_token = 0
        self._refresh_pending = False

    # -- lifecycle -----------------------------------------------------------------------------------------

    def close(self) -> None:
        """After close every in-flight completion is ignored (the widget may already be destroyed)."""

        self._closed = True

    def _changed(self) -> None:
        if not self._closed:
            self._on_change()

    @property
    def message(self) -> str:
        """The operator message, redacted at READ time against the CURRENT mode and hidden jobs, so a message
        written before an SFW toggle can never keep showing content the policy now hides."""

        return self._safe(self._message)

    def _say(self, text: str) -> None:
        self._message = text
        self._changed()

    # -- content visibility (the same policy History applies) -----------------------------------------------

    def _resolver(self) -> ContentVisibilityResolver:
        return ContentVisibilityResolver(self._visibility_mode())

    def _safe(self, text: str) -> str:
        """Free text shown to the operator: redacted whole when it contains explicit terms in SFW mode."""

        if not text:
            return text
        if self._mentions_hidden_content(text):
            return REDACTED_TEXT
        # Paths and file names are "_"/"-"/"."-separated, which defeats the resolver's word boundaries: classify
        # a separator-normalized copy, but redact (or keep) the original text as a whole.
        return self._resolver().redact_text(text, item={"prompt": _SEPARATORS.sub(" ", text)})

    def _mentions_hidden_content(self, text: str) -> bool:
        """True when ``text`` names a hidden job's source, file or path (service errors embed those verbatim)."""

        if self.detail is None or self._resolver().mode.value != "sfw":
            return False
        for job in self.detail.jobs:
            if not self._hidden(job):
                continue
            names = {job.source_label, *job.source_paths}
            for ref in job.artifacts:
                names.update((ref.path, PurePath(ref.path).name, str(PurePath(ref.path).parent)))
            if any(name and name in text for name in names):
                return True
        return False

    def _hidden(self, job: BatchJobView) -> bool:
        """A job the shared policy would hide in the current mode: none of its content is displayed or opened."""

        # Everything that names the job's content takes part (file name AND directories of sources/outputs).
        named = " ".join([job.source_label, *job.source_paths, *(ref.path for ref in job.artifacts)])
        label = _SEPARATORS.sub(" ", named)
        return not self._resolver().decide({**job.visibility_subject, "label": label}).visible

    def notify_visibility_changed(self) -> None:
        """The global SFW/NSFW mode toggled: everything displayed is re-derived from the same state."""

        self._changed()

    # -- refresh (latest request wins) -----------------------------------------------------------------------

    def refresh(self) -> bool:
        """Start one read. At most one is ever in flight: a request that arrives meanwhile is remembered and
        served by a single follow-up read, so a slow scan is never superseded by every new event."""

        if self._closed or self.busy:
            return False
        if self.loading:
            self._refresh_pending = True
            return False
        self._refresh_pending = False
        self._refresh_token += 1
        token, key = self._refresh_token, self.selected_key
        self.loading = True
        self._changed()

        def work() -> WorkOutcome:
            return WorkOutcome(value=self._service.refresh(key))

        def done(outcome: WorkOutcome) -> None:
            if self._closed or token != self._refresh_token:
                return
            self.loading = False
            if outcome.error:
                self._say(f"Refresh failed: {outcome.error}")
            else:
                self._apply(outcome.value, key)
            if self._refresh_pending:
                self.refresh()

        return self._spawn(f"BatchOps-Refresh-{token}", work, done)

    def _spawn(self, name: str, work: Callable[[], WorkOutcome], done: Callable[[WorkOutcome], None]) -> bool:
        try:
            self._runner.start(name, work, done)
        except Exception as exc:  # noqa: BLE001 - e.g. no thread available: never leave a spinner/busy stuck
            self.loading = False
            self.busy = ""
            self._say(f"Could not start background work: {type(exc).__name__}: {exc}")
            return False
        return True

    def _apply(self, snapshot: Any, requested: BatchKey | None) -> None:
        self.snapshot = snapshot
        catalog = snapshot.catalog
        if self.selected_key is not None and catalog.get(self.selected_key) is None:
            self.selected_key, self.selected_ids = None, ()
        stale_detail = self.selected_key is not None and requested != self.selected_key
        self.detail = (
            catalog.get(self.selected_key) if stale_detail else snapshot.selected
        ) if self.selected_key is not None else None
        if self.detail is not None:
            known = {job.job_id for job in self.detail.jobs}
            self.selected_ids = tuple(job_id for job_id in self.selected_ids if job_id in known)
        else:
            self.selected_ids = ()
        notes = []
        if catalog.truncated:
            notes.append("The scan limit was reached; older batches may be missing.")
        if catalog.ambiguous_job_ids:
            notes.append(f"{len(catalog.ambiguous_job_ids)} job(s) have conflicting batch identifiers.")
        self._message = " ".join(notes) or self._message
        self._changed()
        if stale_detail:  # selection moved while the read was in flight: load the current one's detail
            self.refresh()

    # -- selection and filters ---------------------------------------------------------------------------------

    def select_batch(self, key: BatchKey | None) -> None:
        if key == self.selected_key:
            return
        self.selected_key, self.selected_ids = key, ()
        self.detail = self.snapshot.catalog.get(key) if self.snapshot and key else None
        self._changed()
        if key is not None:
            self.refresh()

    def set_job_selection(self, job_ids: Sequence[str]) -> None:
        self.selected_ids = tuple(dict.fromkeys(job_ids))
        self._changed()

    def set_filters(
        self, status: JobStatus | None = None, category: TriageCategory | None = None
    ) -> None:
        self.status_filter, self.category_filter = status, category
        known = {job.job_id for job in self.visible_jobs()}
        self.selected_ids = tuple(job_id for job_id in self.selected_ids if job_id in known)
        self._changed()

    def visible_jobs(self) -> tuple[BatchJobView, ...]:
        if self.detail is None:
            return ()
        return tuple(
            job
            for job in self.detail.jobs
            if (self.status_filter is None or job.status is self.status_filter)
            and (
                self.category_filter is None
                or (job.failure is not None and job.failure.category is self.category_filter)
            )
        )

    def selected_jobs(self) -> tuple[BatchJobView, ...]:
        if self.detail is None:
            return ()
        by_id = {job.job_id: job for job in self.detail.jobs}
        return tuple(by_id[job_id] for job_id in self.selected_ids if job_id in by_id)

    # -- projections for the view ----------------------------------------------------------------------------

    def batch_rows(self) -> tuple[BatchRow, ...]:
        if self.snapshot is None:
            return ()
        rows = []
        for item in self.snapshot.catalog.summaries:
            declared = item.declared_source_count
            jobs = _plural(item.job_count, "job") + (f" / {_plural(declared, 'source')}" if declared else "")
            note = "conflicting membership" if item.conflicting else (
                f"{item.held_count} held (WebUI)" if item.held_count else "")
            rows.append(
                BatchRow(
                    item.key.to_token(), KIND_LABELS[item.key.kind], item.key.short_id, jobs,
                    item.state.value, f"{_finished(item)}/{item.job_count} finished", note,
                )
            )
        return tuple(rows)

    def job_rows(self) -> tuple[JobRow, ...]:
        rows = []
        for job in self.visible_jobs():
            hidden = self._hidden(job)
            produced = [ref for ref in job.artifacts if ref.available is not False]
            missing = len(job.artifacts) - len(produced)
            outputs = "none" if not job.artifacts else f"{len(produced)} file(s)" + (
                f", {missing} missing" if missing else "")
            retry = ", ".join(f"{c.job_id[:8]} ({c.status.value})" for c in job.retry_children)
            status = job.status.value.upper() + (" (held)" if job.held_by_webui else "")
            rows.append(
                JobRow(
                    job.job_id,
                    "-" if job.source_index is None else str(job.source_index + 1),
                    REDACTED_TEXT if hidden else self._safe(job.source_label) or job.job_id[:8],
                    REDACTED_TEXT if hidden else self._safe(job.model_label), status, job.priority_label,
                    job.failure.label if job.failure else "", "hidden" if hidden else outputs, retry,
                )
            )
        return tuple(rows)

    def summary_text(self) -> str:
        item = self.detail
        if item is None:
            return "Select a batch to see its progress."
        counts = item.counts
        lines = [
            f"{item.key.label} - {item.state.value}",
            f"{item.job_count} job(s)"
            + (f", {item.declared_source_count} declared source(s)" if item.declared_source_count else "")
            + (f", {item.covered_source_count} source image(s) in jobs" if item.key.kind.value == "review" else ""),
            f"Queued {counts.queued} - Running {counts.running} - Completed {counts.completed} - "
            f"Failed {counts.failed} - Cancelled {counts.cancelled}"
            + (f" - {item.held_count} queued job(s) held by a WebUI outage" if item.held_count else ""),
            f"First job created {_when(item.first_created_at)} UTC (batches are not stored; this is the "
            "earliest job record)",
        ]
        if item.origin_batch is not None:
            lines.append(f"Retry of {item.origin_batch.label}")
        if self.snapshot is not None and self.snapshot.queue_paused:
            lines.append("The queue is paused.")
        if self.snapshot is not None and self.snapshot.webui_hold:
            lines.append("WebUI-dependent work is held: " + str(self.snapshot.webui_hold.get("reason")))
        lines.extend(item.notes)
        return "\n".join(lines)

    def detail_text(self) -> str:
        jobs = self.selected_jobs()
        if not jobs:
            return "Select a job to see its details."
        job = jobs[-1]
        hidden = self._hidden(job)
        lines = [
            f"Job {job.job_id}  -  {job.status.value.upper()}  -  priority {job.priority_label}  -  "
            f"queue order {job.queue_order}",
        ]
        if hidden:
            lines.append(f"Content hidden in SFW mode ({REDACTED_TEXT}): source, model, message and outputs are not shown.")
        else:
            lines.append(f"Source: {self._safe(', '.join(job.source_paths)) or '-'}")
            lines.append(f"Model / workflow: {self._safe(job.model_label) or '-'}")
        lines.append(
            f"Created {_when(job.created_at)}  Started {_when(job.started_at)}  Finished {_when(job.completed_at)}"
        )
        if job.hydration_error and not hidden:
            lines.append(self._safe(job.hydration_error))
        if job.failure is not None:
            failure = job.failure
            lines.append(
                f"Failure: {failure.label}" + ("" if failure.typed else " (no typed evidence; not classified)")
                + (f"  Stage: {failure.stage}" if failure.stage else "")
            )
            if not hidden:
                lines.append(f"Message: {self._safe(failure.summary)}")
            lines.append(f"Dispatch certainty: {failure.dispatch_certainty}")
            if failure.acknowledgement_text:
                lines.append("! " + failure.acknowledgement_text)
            if failure.action_required:
                lines.append("Action required: inspect existing outputs before generating again.")
        if job.checkpoints:
            lines.append("Stage checkpoints: " + ", ".join(
                f"{c.stage_name} ({c.output_count} output(s))" for c in job.checkpoints))
        if not hidden:
            for ref in job.artifacts[:MAX_LISTED_OUTPUTS]:
                state = {True: "available", False: "missing or moved", None: "not checked"}[ref.available]
                lines.append(self._safe(f"Output [{ref.kind.value}, {state}]: {PurePath(ref.path).name}  ({ref.path})"))
            if len(job.artifacts) > MAX_LISTED_OUTPUTS:
                lines.append(f"... and {len(job.artifacts) - MAX_LISTED_OUTPUTS} more output(s)")
        if job.parent_job_id:
            lines.append(f"Parent job: {job.parent_job_id}")
        if job.replay_origin is not None and job.replay_origin.key is not None:
            lines.append(f"Replay origin: {job.replay_origin.key.label} (historical, not a member)")
        for child in job.retry_children:
            lines.append(f"Retried as {child.job_id} ({child.status.value})")
        return "\n".join(lines)

    # -- truthful action gating -------------------------------------------------------------------------------

    def _blocked(self, *, mutating: bool = True) -> str:
        if self.busy:
            return "Another batch operation is in progress."
        if self.detail is None:
            return "Select a batch first."
        if mutating and self.detail.conflicting:
            return "This batch has conflicting membership records."
        return ""

    def cancel_state(self) -> ActionState:
        if reason := self._blocked():
            return ActionState(False, reason)
        queued = self.detail.counts.queued if self.detail else 0
        if not queued:
            return ActionState(False, "No queued jobs remain in this batch.")
        return ActionState(True, f"Cancel the {queued} job(s) still queued. Started jobs are left alone.")

    def retry_state(self) -> ActionState:
        if reason := self._blocked():
            return ActionState(False, reason)
        selected = self.selected_jobs()
        if not selected:
            return ActionState(False, "Select one or more failed jobs.")
        failed = sum(1 for job in selected if job.status is JobStatus.FAILED)
        if not failed:
            return ActionState(False, "None of the selected jobs failed.")
        return ActionState(True, f"Review and retry {failed} failed job(s) as new jobs.")

    def _output_state(self, kind: OutputKind | None, empty: str) -> ActionState:
        if reason := self._blocked(mutating=False):
            return ActionState(False, reason)
        selected = self.selected_jobs()
        if not selected:
            return ActionState(False, "Select one or more jobs.")
        usable = [
            ref for job in selected if not self._hidden(job) for ref in job.artifacts
            if ref.available is not False and (kind is None or ref.kind is kind)
        ]
        if not usable and any(self._hidden(job) for job in selected):
            return ActionState(False, "Outputs of content hidden in SFW mode are not opened.")
        return ActionState(bool(usable), "Uses the selected jobs' recorded outputs." if usable else empty)

    def review_state(self) -> ActionState:
        return self._output_state(OutputKind.IMAGE, "The selected jobs have no recorded image to review.")

    def folder_state(self) -> ActionState:
        return self._output_state(None, "The selected jobs have no recorded output.")

    def movie_clips_state(self) -> ActionState:
        return self._output_state(OutputKind.VIDEO, "The selected jobs have no recorded video.")

    # -- actions ---------------------------------------------------------------------------------------------------

    def _begin(self, name: str, allowed: ActionState) -> bool:
        if self._closed or not allowed.enabled:
            if not self._closed:
                self._say(allowed.reason)
            return False
        self.busy = name
        self._changed()
        return True

    def _finish(self, text: str, *, refresh: bool = True) -> None:
        self.busy = ""
        self._message = text
        self._changed()
        if refresh:
            self.refresh()

    def _run(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]) -> bool:
        def outcome_work() -> WorkOutcome:
            return WorkOutcome(value=work())

        delivered = []

        def on_done(outcome: WorkOutcome) -> None:
            if self._closed or delivered:
                return  # closed, or a duplicate delivery of a completion already applied
            delivered.append(True)
            if outcome.error:
                self._finish(f"{name} failed: {outcome.error}")
                return
            try:
                done(outcome.value)
            except Exception as exc:  # noqa: BLE001 - a hook failure is reported, never left half-applied
                self._finish(f"{name} could not finish: {type(exc).__name__}: {exc}", refresh=False)

        return self._spawn(f"BatchOps-{name}", outcome_work, on_done)

    def cancel_remaining(self) -> bool:
        if not self._begin("Cancel", self.cancel_state()):
            return False
        key = self.selected_key
        return self._run(
            "Cancel", lambda: self._service.plan_cancel_remaining(key), lambda plan: self._confirm_cancel(key, plan)
        )

    def _confirm_cancel(self, key: BatchKey, plan: Any) -> None:
        if not plan.target_job_ids:
            self._finish("Nothing to cancel: no member of this batch is queued any more.")
            return
        if not self.hooks.confirm_cancel(plan):
            self._finish("Cancel Remaining was not confirmed; nothing changed.", refresh=False)
            return
        self._run(
            "Cancel",
            lambda: self._service.cancel_remaining(key, confirmed_job_ids=plan.target_job_ids),
            lambda result: self._finish(result.message),
        )

    def retry_selected(self) -> bool:
        if not self._begin("Retry", self.retry_state()):
            return False
        key, ids = self.selected_key, self.selected_ids
        return self._run(
            "Retry", lambda: self._service.preflight_retry(key, ids), lambda plan: self._review_retry(plan)
        )

    def _redacted_plan(self, plan: Any) -> Any:
        """The retry review shows hidden jobs' content as redacted; eligibility and tokens are unchanged."""

        by_id = {job.job_id: job for job in (self.detail.jobs if self.detail else ())}
        items = []
        for item in plan.items:
            job = by_id.get(item.job_id)
            hidden = job is not None and self._hidden(job)
            items.append(replace(
                item,
                source_label=REDACTED_TEXT if hidden else self._safe(item.source_label),
                reasons=tuple(REDACTED_TEXT if hidden else self._safe(r) for r in item.reasons),
                notices=tuple(REDACTED_TEXT if hidden else self._safe(n) for n in item.notices),
            ))
        return replace(plan, items=tuple(items))

    def _review_retry(self, plan: Any) -> None:
        acknowledged = self.hooks.review_retry(self._redacted_plan(plan))
        if acknowledged is None or not plan.submittable:
            self._finish("Retry was not submitted; nothing changed.", refresh=False)
            return
        self._run(
            "Retry",
            lambda: self._service.submit_retry(plan, acknowledged_job_ids=acknowledged),
            lambda result: self._finish(result.message),
        )

    def open_outputs(self, target: str) -> bool:
        """``target`` is ``review`` (images), ``folder`` or ``movie_clips`` (videos)."""

        gate = {"review": self.review_state, "folder": self.folder_state, "movie_clips": self.movie_clips_state}[target]()
        if not self._begin("Outputs", gate):
            return False
        key = self.selected_key
        # Content the shared policy hides is never resolved, opened or handed to Review/Movie Clips.
        ids = tuple(job.job_id for job in self.selected_jobs() if not self._hidden(job))
        return self._run(
            "Outputs",
            lambda: self._service.resolve_outputs(key, ids),
            lambda res: self._hand_off(target, res, ids),
        )

    def _hand_off(self, target: str, resolution: Any, requested: tuple[str, ...] = ()) -> None:
        by_id = {job.job_id: job for job in (self.detail.jobs if self.detail else ())}
        if any(job_id in by_id and self._hidden(by_id[job_id]) for job_id in requested):
            # The mode (or the data) changed while the files were being resolved: hand nothing off.
            self._finish("The display mode changed while outputs were being resolved; nothing was opened.", refresh=False)
            return
        problems = " ".join(resolution.messages)
        if target == "review":
            if not resolution.images:
                self._finish(f"No usable image to open in Review. {problems}".strip(), refresh=False)
                return
            count = self.hooks.open_in_review(resolution.images)
            self._finish(f"Opened {count} image(s) in Review. {problems}".strip(), refresh=False)
        elif target == "movie_clips":
            if not resolution.videos:
                self._finish(f"No available video to open. {problems}".strip(), refresh=False)
                return
            self.hooks.open_movie_clips({
                "primary_path": resolution.videos[0], "artifact_type": "video",
                "output_paths": list(resolution.videos), "video_paths": list(resolution.videos)})
            self._finish(f"Sent {len(resolution.videos)} video(s) to Movie Clips. {problems}".strip(), refresh=False)
        else:
            if not resolution.folders:
                self._finish(f"No existing output folder. {problems}".strip(), refresh=False)
                return
            self.hooks.open_folder(resolution.folders[0])
            extra = f" ({len(resolution.folders) - 1} more folder(s))" if len(resolution.folders) > 1 else ""
            self._finish(f"Opened {resolution.folders[0]}{extra}. {problems}".strip(), refresh=False)


__all__ = [
    "ActionState",
    "BatchOperationsSession",
    "BatchRow",
    "BatchViewHooks",
    "CATEGORY_LABELS",
    "JobRow",
]
