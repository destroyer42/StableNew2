"""Phone actions from the review gateway (RG-140 slice 1): prepare a summary, then admit what it showed.

An ``action_request`` outbox record is untrusted input. ``RecordApplier`` has already checked its closed lists, the
device and its ``queue`` scope, and resolved the target by library id through this PC's publish ledger with the file
re-hashed (S3, invariant 3). This module then:

* **prepare** compiles exactly what the action would queue with the existing compilers (the Review re-work compile
  for the ADetailer fixes, the History variation compiler for "more like this"), admits nothing, and answers with an
  ``action_summary``: PC-written text, the job count, where the jobs go in the queue and every N1 warning, all
  scrubbed of paths (S7, S12);
* **confirm** compiles again and admits only when the fresh summary has the revision the phone showed. Admission is
  one call to ``admit_phone_records`` (``JobService.submit_njrs``; invariant 6) with deterministic job ids, the
  shown warnings frozen as accepted on the phone, fixes at the queue's existing HIGH priority (D8 first step) and
  "more like this" at NORMAL.

Caps per device over a rolling 24 hours and per request (S4), and one admission per prepare (S8), are enforced
here; the gateway's caps only refuse earlier. Compiler failures become closed ``detail`` codes, never their text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol

from src.app.review_gateway_protocol import (
    ACTION_UNAVAILABLE,
    ADMISSION_REFUSED,
    CAP_EXCEEDED,
    DETAILS,
    INVALID_RECORD,
    PREPARE_REQUIRED,
    SLICE_ONE_ACTIONS,
    SUMMARY_CHANGED,
    ActionSummary,
    OutboxRecord,
    SummaryWarning,
    parse_timestamp,
    utc_now,
    utc_text,
)
from src.app.review_gateway_store import SyncLedger
from src.app.site_media_files import SiteOutputError
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.policy_warnings import PolicyWarning, pending_warnings

log = logging.getLogger(__name__)

DEFAULT_SEEDS = 4
PREPARE_TTL = timedelta(minutes=30)
USAGE_WINDOW = timedelta(hours=24)
_SEED_LIMIT = 2**31

_TITLES = {
    "fix_face": "Fix face",
    "fix_hands": "Fix hands",
    "fix_both": "Fix face and hands",
    "more_like_this": "More like this",
}
_PASSES = {"fix_face": (True, False), "fix_hands": (False, True), "fix_both": (True, True)}
#: Compiler and admission refusals that keep their own name on the phone; anything else is ``compile_failed``.
_DETAIL_ALIASES = {
    "followup_provenance_unverified": "provenance_unverified",
    "media_changed": "source_changed",
    "preview_changed": "source_changed",
    "preview_unavailable": "app_busy",
}


@dataclass(frozen=True)
class Caps:
    """S4 limits per device (owner question Q3 in the RG-140 work package)."""

    jobs_per_day: int = 64
    prepares_per_day: int = 200
    jobs_per_request: int = 8


@dataclass(frozen=True)
class CompiledAction:
    """What an action would queue, compiled by the existing compilers, plus what the phone is shown about it."""

    records: tuple[NormalizedJobRecord, ...]
    lines: tuple[str, ...]
    warnings: tuple[PolicyWarning, ...]
    identity: tuple[str, ...]
    reprocess: bool
    kind: str
    require_current: Callable[[], None] = lambda: None


class ActionRefused(Exception):
    """An action this PC cannot prepare or admit now; ``detail`` is one of the schema's closed codes."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail if detail in DETAILS else "compile_failed"


class ActionCompiler(Protocol):
    def compile(
        self, action: str, path: Path, digest: str, seeds: tuple[int, ...]
    ) -> CompiledAction: ...


#: ``(owner, receipt id, compiled action, warnings shown, runs next) -> admitted job ids``.
Admit = Callable[[str, str, CompiledAction, tuple[PolicyWarning, ...], bool], list[str]]


def shown_warnings(compiled: CompiledAction) -> tuple[PolicyWarning, ...]:
    """Every N1 warning the summary shows: the compiler's and those attached to the jobs (one per code and subject)."""

    shown = {item.key: item for item in compiled.warnings}
    for job in compiled.records:
        for item in pending_warnings(job):
            shown.setdefault(item.key, item)
    return tuple(shown.values())


@dataclass(frozen=True)
class ActionOutcome:
    outcome: str
    reason: str = ""
    receipt: Mapping[str, Any] = field(default_factory=dict)


def _refused(reason: str, **receipt: Any) -> ActionOutcome:
    return ActionOutcome("refused", reason, receipt)


def detail_of(error: BaseException) -> str:
    code = str(error)
    code = _DETAIL_ALIASES.get(code, code)
    return code if code in DETAILS else "compile_failed"


def _warning(item: PolicyWarning) -> SummaryWarning:
    return SummaryWarning(
        item.code,
        PureWindowsPath(item.subject).name or item.subject,
        item.title,
        item.why,
        item.fix,
    )


def model_name(record: NormalizedJobRecord) -> str:
    return PureWindowsPath(str(record.base_model or "")).name or "the recorded checkpoint"


class GatewayActions:
    def __init__(
        self,
        ledger: SyncLedger,
        compiler: ActionCompiler,
        admit: Admit,
        *,
        owner_of: Callable[[str], str],
        caps: Caps = Caps(),
        clock: Callable[[], datetime] = utc_now,
        seeds: Callable[[], int] = lambda: secrets.randbelow(_SEED_LIMIT),
    ) -> None:
        self._ledger = ledger
        self._compiler = compiler
        self._admit = admit
        self._owner_of = owner_of
        self._caps = caps
        self._clock = clock
        self._seeds = seeds

    def handle(self, record: OutboxRecord, path: Path) -> ActionOutcome:
        request = record.action_request
        assert request is not None
        if request.action not in SLICE_ONE_ACTIONS:
            return _refused(INVALID_RECORD)  # reserved for a later slice
        now = self._clock()
        prepares, jobs = self._ledger.action_usage(record.device_id, utc_text(now - USAGE_WINDOW))
        if request.step == "prepare":
            return self._prepare(record, path, now, prepares)
        return self._confirm(record, path, now, prepares, jobs)

    # -- steps -----------------------------------------------------------------------------------------------------

    def _seed_count(self, action: str, requested: int | None) -> int:
        return (requested or DEFAULT_SEEDS) if action == "more_like_this" else 0

    def _compile(
        self, action: str, path: Path, digest: str, count: int, now: datetime
    ) -> tuple[CompiledAction, ActionSummary]:
        seeds = tuple(self._seeds() for _ in range(count))
        try:
            compiled = self._compiler.compile(action, path, digest, seeds)
        except ActionRefused:
            raise
        except (SiteOutputError, ValueError, OSError) as error:
            raise ActionRefused(detail_of(error)) from error
        except Exception as error:  # noqa: BLE001 - one bad record must never stall the outbox behind it
            log.error("A phone action could not be compiled (%s)", type(error).__name__)
            raise ActionRefused("compile_failed") from error
        if not 1 <= len(compiled.records) <= self._caps.jobs_per_request:
            raise ActionRefused("compile_failed")
        return compiled, self._summary(action, compiled, now)

    def _prepare(
        self, record: OutboxRecord, path: Path, now: datetime, prepares: int
    ) -> ActionOutcome:
        request = record.action_request
        assert request is not None
        if prepares >= self._caps.prepares_per_day:
            return _refused(CAP_EXCEEDED)
        count = self._seed_count(request.action, request.count)
        if count > self._caps.jobs_per_request:
            return _refused(CAP_EXCEEDED)
        self._ledger.log_action(record.record_id, record.device_id, "prepare", 0, utc_text(now))
        try:
            _compiled, summary = self._compile(
                request.action, path, record.target.sha256, count, now
            )
        except ActionRefused as refusal:
            return _refused(ACTION_UNAVAILABLE, detail=refusal.detail)
        self._remember(record, request.action, count, summary, now)
        return ActionOutcome("applied", receipt={"action_summary": summary.payload()})

    def _confirm(
        self, record: OutboxRecord, path: Path, now: datetime, prepares: int, jobs: int
    ) -> ActionOutcome:
        request = record.action_request
        assert request is not None
        prepared = self._ledger.prepared(request.prepared_record)
        if (
            prepared is None
            or prepared["device_id"] != record.device_id
            or (prepared["library_id"], prepared["sha256"])
            != (record.target.library_id, record.target.sha256)
            or prepared["action"] != request.action
            or parse_timestamp(prepared["at"]) + PREPARE_TTL < now
        ):
            return _refused(PREPARE_REQUIRED)
        if prepared["admitted_by"] is not None:
            # S8: one admission per prepare. A second confirm answers with the first receipt.
            return ActionOutcome("duplicate", receipt=json.loads(prepared["receipt"] or "{}"))
        if prepared["revision"] != request.summary_revision:
            return _refused(SUMMARY_CHANGED)
        count = int(prepared["seeds"] or 0)
        try:
            compiled, summary = self._compile(
                request.action, path, record.target.sha256, count, now
            )
        except ActionRefused as refusal:
            return _refused(ACTION_UNAVAILABLE, detail=refusal.detail)
        if summary.revision != prepared["revision"]:
            # The phone shows this one instead; confirming this record admits it (it counts as a prepare).
            if prepares >= self._caps.prepares_per_day:
                return _refused(CAP_EXCEEDED)
            self._ledger.log_action(record.record_id, record.device_id, "prepare", 0, utc_text(now))
            self._remember(record, request.action, count, summary, now)
            return _refused(SUMMARY_CHANGED, action_summary=summary.payload())
        if jobs + len(compiled.records) > self._caps.jobs_per_day:
            return _refused(CAP_EXCEEDED)
        receipt_id = str(prepared["record_id"]).replace("-", "")
        try:
            compiled.require_current()
            job_ids = self._admit(
                self._owner_of(record.device_id),
                receipt_id,
                compiled,
                shown_warnings(compiled),
                request.action in _PASSES,
            )
        except ActionRefused as refusal:
            return _refused(ADMISSION_REFUSED, detail=refusal.detail)
        except (SiteOutputError, ValueError, OSError) as error:
            log.info("A phone action was not admitted (%s)", detail_of(error))
            return _refused(ADMISSION_REFUSED, detail=detail_of(error))
        except Exception as error:  # noqa: BLE001 - answered, never retried into a second admission
            log.error("A phone action was not admitted (%s)", type(error).__name__)
            return _refused(ADMISSION_REFUSED, detail="compile_failed")
        receipt = {"job_ids": job_ids, "action_summary": summary.payload()}
        self._ledger.log_action(
            record.record_id, record.device_id, "confirm", len(job_ids), utc_text(now)
        )
        self._ledger.mark_prepare_admitted(str(prepared["record_id"]), record.record_id, receipt)
        return ActionOutcome("applied", receipt=receipt)

    # -- summary ---------------------------------------------------------------------------------------------------

    def _remember(
        self, record: OutboxRecord, action: str, count: int, summary: ActionSummary, now: datetime
    ) -> None:
        self._ledger.remember_prepare(
            record.record_id,
            record.device_id,
            record.target.library_id,
            record.target.sha256,
            action,
            count or None,
            summary.revision,
            utc_text(now),
        )

    def _summary(self, action: str, compiled: CompiledAction, now: datetime) -> ActionSummary:
        warnings = tuple(_warning(item) for item in shown_warnings(compiled))
        position = "next" if action in _PASSES else "last"
        lines = (
            *compiled.lines,
            "Runs next, after the current job."
            if position == "next"
            else "Joins the end of the queue.",
        )
        body = {
            "action": action,
            "title": _TITLES[action],
            "lines": list(lines),
            "job_count": len(compiled.records),
            "queue_position": position,
            "warnings": [item.payload() for item in warnings],
            "identity": list(compiled.identity),
        }
        revision = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        return ActionSummary(
            action=action,
            revision=revision,
            title=_TITLES[action],
            lines=tuple(lines),
            job_count=len(compiled.records),
            queue_position=position,
            warnings=warnings,
            expires_at=now + PREPARE_TTL,
        )


# -- the running application ------------------------------------------------------------------------------------------

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_HASH_LIMIT = 256 * 1024 * 1024


class AppActionCompiler:
    """Slice-1 compiles on the running application, through the existing phone Preview and follow-up services."""

    def __init__(self, host: Any, repository: Any, output_root: Path) -> None:
        self._host = host
        self._repository = repository
        self._root = output_root

    def compile(
        self, action: str, path: Path, digest: str, seeds: tuple[int, ...]
    ) -> CompiledAction:
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            raise ActionRefused("not_an_image")
        if action in _PASSES:
            return self._fix(action, path, digest)
        if action == "more_like_this":
            return self._more(path, digest, seeds)
        raise ActionRefused("compile_failed")

    def _fix(self, action: str, path: Path, digest: str) -> CompiledAction:
        face, hands = _PASSES[action]
        draft = self._host.compile_gateway_fix(path, digest, face=face, hands=hands)
        [job] = draft.records
        block = job.config.get("adetailer")
        settings = block if isinstance(block, Mapping) else {}
        detectors = [
            PureWindowsPath(str(settings.get(key) or "")).name
            for key, enabled in (("adetailer_model", face), ("adetailer_hands_model", hands))
            if enabled
        ]
        passes = {
            "fix_face": "ADetailer face pass",
            "fix_hands": "ADetailer hand pass",
            "fix_both": "ADetailer face pass, then the hand pass",
        }[action]
        lines = (
            f"{passes} on this exact image ({', '.join(name for name in detectors if name) or 'default detector'}).",
            "The original stays as it is; the result is a new image in Reprocess.",
            f"Checkpoint {model_name(job)}.",
        )
        identity = (
            action,
            str(job.base_model or ""),
            ",".join(job.stage_chain_labels),
            *detectors,
            digest,
        )
        return CompiledAction(
            tuple(draft.records),
            lines,
            (),
            identity,
            reprocess=True,
            kind="rework",
            require_current=draft.require_current,
        )

    def _more(self, path: Path, digest: str, seeds: tuple[int, ...]) -> CompiledAction:
        from src.app.site_media_files import open_scoped
        from src.app.site_phone_followup import verified_history_source
        from src.image_backends.model_policy_warnings import shown_model_warnings
        from src.pipeline.history_variation_compiler import (
            HistoryVariationDraft,
            HistoryVariationRefused,
            compile_history_variation,
        )

        if not seeds:
            raise ActionRefused("compile_failed")

        def source() -> tuple[NormalizedJobRecord, str]:
            with open_scoped(self._root, path) as stream:
                raw = stream.read(_HASH_LIMIT + 1)
            if len(raw) > _HASH_LIMIT or hashlib.sha256(raw).hexdigest() != digest:
                raise ActionRefused("source_changed")
            return verified_history_source(self._repository, path, raw)

        record, snapshot = source()
        try:
            draft = HistoryVariationDraft.from_source(record, parent_artifact_id=f"sha256:{digest}")
            jobs = tuple(compile_history_variation(draft.with_edits(seed=seed)) for seed in seeds)
        except HistoryVariationRefused as error:
            raise ActionRefused("recipe_not_variable") from error

        def require_current() -> None:
            if source()[1] != snapshot:
                raise ActionRefused("source_changed")

        count = len(jobs)
        return CompiledAction(
            jobs,
            (
                f"{count} new image{'s' if count != 1 else ''}, each with a new seed.",
                "Same prompt, checkpoint and settings as this image.",
                f"Checkpoint {model_name(record)}.",
            ),
            tuple(shown_model_warnings(record)),
            ("more_like_this", record.job_id, snapshot, str(count)),
            reprocess=False,
            kind="followup",
            require_current=require_current,
        )
