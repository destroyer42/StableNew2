"""Validate and apply review gateway outbox records on the PC (RG-120).

Every record is untrusted input, checked as strictly as ``_desktop_call`` in ``src/app/site_phone_connector.py``
(S3): a closed list of kinds and verdicts; the target resolved only by library id through this PC's own publish ledger
(never a path from the gateway), the file re-hashed and compared with the record's SHA-256; the device enrolled from an
offer this PC issued, not revoked, holding the scope the record needs. Decisions are applied through the native
services only:

* **Keep** appends a Retain disposition to the Learning evidence (``src/review/review_evidence.py``), with the phone's
  Favorite flag and reason tags as additive metadata. A Keep for an item a phone Delete archived first restores the
  file through ``src/review/archive.py`` (the phone's Undo).
* **Delete** is a phone Discard: a Discard disposition, then a move into ``<output root>/_archive/`` through
  ``src/review/archive.py`` (links refused, the digest re-checked immediately before the move, never a delete,
  undoable with Restore).
* **Action requests** (RG-140) need the device's separate ``queue`` scope; the target is resolved and re-hashed
  exactly as for a decision, then handed to the injected ``GatewayActions`` (``src/app/review_gateway_actions.py``),
  which prepares a summary or admits through the phone admission service. Without one they are refused
  (``not_granted``). This module itself still has no reference to the queue, the runner or ``JobService`` (RG-100
  invariant 6).
* **Admin requests** (LAUNCH-UPDATE-2) need the device's ``admin`` scope, issued only by the desktop's dedicated
  remote-update pairing offer (D2). They name no item; the injected ``AdminRequests`` handler
  (``src/app/live_update_remote.py``) runs them through the LAUNCH-UPDATE-1 service, which also requires the
  PC-local "Allow remote update" switch. While an update is under way the record is left unanswered
  (``in_progress``) and asked again on later cycles, across the restart, until the update has a receipt.

Each outcome is written to the ledger before it is acknowledged, so a re-sent record gets the same answer and is never
applied twice.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from src.app.review_gateway_protocol import (
    ARCHIVE_FAILED,
    DIGEST_MISMATCH,
    FAVORITE_WITH_DELETE,
    INVALID_RECORD,
    NOT_GRANTED,
    REVOKED_DEVICE,
    UNKNOWN_ITEM,
    AdminRecord,
    OutboxRecord,
    ProtocolError,
    parse_record,
    record_id_of,
    utc_now,
    utc_text,
)
from src.app.review_gateway_store import SyncLedger
from src.app.site_media_files import SiteOutputError, checked_digest, inside, open_scoped
from src.app.site_video_playback import VIDEO_LIMIT
from src.learning.learning_record import LearningRecordWriter
from src.review.archive import apply_archive, archived_location, plan_archive, restore_file
from src.review.review_evidence import (
    REVIEW_FAVORITE,
    REVIEW_GATEWAY_RECEIPT,
    REVIEW_TAGS,
    build_disposition_with_prior_settings,
    image_source_job,
    stamp_review_batch,
)

if TYPE_CHECKING:
    from src.app.review_gateway_actions import GatewayActions

log = logging.getLogger(__name__)

_HASH_LIMIT = max(VIDEO_LIMIT, 64 * 1024 * 1024)
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
#: An answer that is not final yet: the record is neither recorded nor acknowledged and is asked again later.
IN_PROGRESS = "in_progress"
UPDATE_UNAVAILABLE = "update_unavailable"


@dataclass(frozen=True)
class Applied:
    record_id: str
    outcome: str
    reason: str = ""
    receipt: Mapping[str, Any] = field(default_factory=dict)


class AdminRequests(Protocol):
    """Runs an ``admin_request``; ``None`` while it is still in progress (nothing is recorded or acknowledged)."""

    def handle(self, record: AdminRecord) -> Applied | None: ...


class ApplyDeferred(Exception):
    """The record could not be decided now (the evidence file is unavailable); it stays pending and is retried."""


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RecordApplier:
    def __init__(
        self,
        ledger: SyncLedger,
        output_root: Path,
        records_path: Path,
        *,
        active_inputs: Callable[[], Collection[str]] | None,
        actions: GatewayActions | None = None,
        admin: AdminRequests | None = None,
        batch_of_job: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self._ledger = ledger
        self._root = output_root
        self._records_path = records_path
        self._active_inputs = active_inputs
        self._actions = actions
        self.admin = admin
        self._batch_of_job = batch_of_job

    def handle(self, raw: Any) -> Applied | None:
        """The outcome for one raw outbox record; ``None`` when it has no acknowledgeable record id.

        Raises ``ApplyDeferred`` (nothing recorded, nothing acknowledged) when the evidence cannot be written now.
        """

        record_id = record_id_of(raw)
        if record_id is None:
            return None
        prior = self._ledger.outcome(record_id)
        if prior is not None:
            return Applied(prior.record_id, prior.outcome, prior.reason, prior.receipt)
        key: str | None = None
        try:
            record = parse_record(raw)
            key = record.idempotency_key
            first = self._ledger.outcome_for_key(key)
            if first is not None:
                # A request's duplicate repeats the first receipt, so the phone still sees its job ids (S8).
                receipt = first.receipt if record.kind != "decision" else {}
                result = Applied(record_id, "duplicate", receipt=receipt)
                key = None  # the key already names the first record
            else:
                result = self._apply(record)
                if result.outcome == IN_PROGRESS:
                    return result  # not final: nothing recorded, nothing acknowledged
        except ProtocolError:
            result = Applied(record_id, "refused", INVALID_RECORD)
        except _Refused as refusal:
            result = Applied(record_id, "refused", refusal.reason)
        except (
            OSError
        ) as error:  # an I/O failure is not the record's fault: decide it on a later cycle
            raise ApplyDeferred("io_unavailable") from error
        self._ledger.record_outcome(
            record_id, key, result.outcome, result.reason, result.receipt, utc_text(utc_now())
        )
        return result

    # -- checks ----------------------------------------------------------------------------------------------------

    def _authorize(self, record: OutboxRecord | AdminRecord, scope: str) -> None:
        device = self._ledger.device(record.device_id)
        if device is None or device.revoked:
            raise _Refused(REVOKED_DEVICE)
        if scope not in device.scopes:
            raise _Refused(NOT_GRANTED)

    def _resolve(self, record: OutboxRecord) -> tuple[Path, str]:
        published = self._ledger.published(record.target.library_id)
        if published is None or published["state"] != "published":
            raise _Refused(UNKNOWN_ITEM)
        if published["sha256"] != record.target.sha256:
            raise _Refused(DIGEST_MISMATCH)
        return self._root / str(published["rel_path"]), str(published["rel_path"])

    def _current_digest(self, path: Path) -> str | None:
        """SHA-256 of the file now at ``path`` (``None`` when absent); refuses links and paths outside the root."""

        try:
            path.lstat()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise _Refused(UNKNOWN_ITEM) from error
        try:
            inside(self._root, path)
            with open_scoped(self._root, path) as stream:
                return checked_digest(stream, size_limit=_HASH_LIMIT)
        except (SiteOutputError, OSError) as error:
            raise _Refused(UNKNOWN_ITEM) from error

    # -- apply -----------------------------------------------------------------------------------------------------

    def _apply(self, record: OutboxRecord | AdminRecord) -> Applied:
        if isinstance(record, AdminRecord):
            return self._admin(record)
        if record.kind == "action_request":
            return self._action(record)
        decision = record.decision
        assert decision is not None
        self._authorize(record, "review")
        if decision.verdict == "delete" and decision.favorite:
            raise _Refused(FAVORITE_WITH_DELETE)
        if decision.verdict == "delete" and "needs_fix" in decision.tags:
            raise _Refused(INVALID_RECORD)
        path, rel_path = self._resolve(record)
        if decision.verdict == "keep":
            return self._keep(record, path)
        return self._discard(record, path, rel_path)

    def _admin(self, record: AdminRecord) -> Applied:
        self._authorize(record, "admin")
        handler = self.admin
        if handler is None:
            raise _Refused(UPDATE_UNAVAILABLE)
        result = handler.handle(record)
        if result is None:
            return Applied(record.record_id, IN_PROGRESS)
        return Applied(record.record_id, result.outcome, result.reason, dict(result.receipt))

    def _action(self, record: OutboxRecord) -> Applied:
        self._authorize(record, "queue")
        if self._actions is None:
            raise _Refused(NOT_GRANTED)
        path, _rel_path = self._resolve(record)
        current = self._current_digest(path)
        if current is None:
            raise _Refused(UNKNOWN_ITEM)
        if current != record.target.sha256:
            raise _Refused(DIGEST_MISMATCH)
        result = self._actions.handle(record, path)
        return Applied(record.record_id, result.outcome, result.reason, dict(result.receipt))

    def _keep(self, record: OutboxRecord, path: Path) -> Applied:
        target = record.target
        current = self._current_digest(path)
        if current is None:
            if self._ledger.discarded_path(target.library_id, target.sha256) is None:
                raise _Refused(UNKNOWN_ITEM)
            outcome = restore_file(path, output_root=self._root, digest=target.sha256)
            if outcome.status not in ("moved", "noop", "duplicate"):
                raise _Refused(ARCHIVE_FAILED)
            current = self._current_digest(path)
            self._ledger.forget_discard(target.library_id, target.sha256)
        if current != target.sha256:
            raise _Refused(DIGEST_MISMATCH)
        evidence = self._write(record, path, "retain")
        return Applied(record.record_id, "applied", receipt={"review_evidence_id": evidence})

    def _discard(self, record: OutboxRecord, path: Path, rel_path: str) -> Applied:
        target = record.target
        current = self._current_digest(path)
        if current is None:
            archived = archived_location(path, output_root=self._root, digest=target.sha256)
            if archived is None:
                raise _Refused(UNKNOWN_ITEM)
            # Already in the archive (an earlier Delete of the same bytes): nothing to move.
            return Applied(record.record_id, "applied", receipt={"archived": True})
        if current != target.sha256:
            raise _Refused(DIGEST_MISMATCH)
        if not plan_archive(path, output_root=self._root, active_inputs=self._active_inputs).ok:
            raise _Refused(ARCHIVE_FAILED)
        evidence = self._write(record, path, "discard")
        # Re-plan immediately before the move: the plan hashes the file again and re-checks links and the queue.
        plan = plan_archive(path, output_root=self._root, active_inputs=self._active_inputs)
        if not plan.ok or plan.duplicate or plan.digest != target.sha256:
            raise _Refused(ARCHIVE_FAILED)
        outcome = apply_archive(plan)
        if not outcome.moved:
            log.warning(
                "A phone Discard was recorded but the file was not moved (%s)", outcome.code
            )
            raise _Refused(ARCHIVE_FAILED)
        self._ledger.remember_discard(target.library_id, target.sha256, rel_path, record.record_id)
        return Applied(
            record.record_id,
            "applied",
            receipt={"review_evidence_id": evidence, "archived": True},
        )

    def _write(self, record: OutboxRecord, path: Path, disposition: str) -> str:
        decision = record.decision
        assert decision is not None
        image = path.suffix.lower() in _IMAGE_SUFFIXES
        evidence = build_disposition_with_prior_settings(
            self._records_path,
            image_path=path,
            disposition=disposition,
            artifact_sha256=record.target.sha256,
            source_job_id=image_source_job(path) if image else "",
        )
        stamp_review_batch(evidence, self._batch_of_job)
        if disposition == "retain" and decision.favorite:
            evidence.metadata[REVIEW_FAVORITE] = True
        if decision.tags:
            evidence.metadata[REVIEW_TAGS] = list(decision.tags)
        evidence.metadata[REVIEW_GATEWAY_RECEIPT] = {
            "record_id": record.record_id,
            "idempotency_key": record.idempotency_key,
            "device_id": record.device_id,
            "library_id": record.target.library_id,
        }
        if not LearningRecordWriter(self._records_path).append_record(evidence):
            raise ApplyDeferred("evidence_unavailable")
        return evidence.run_id[:128]
