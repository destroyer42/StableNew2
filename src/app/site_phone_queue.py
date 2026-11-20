"""Phone-scoped projections over the native queue and History repository."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from src.app.site_media_files import SiteOutputError
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_phone_credentials import IDENTIFIER, PhoneGrant
from src.controller.job_service import JobService
from src.pipeline.reprocess_builder import extract_reprocess_output_paths
from src.queue.job_history_store import (
    CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN,
    INTERRUPTED_RESTART_ACTION_REQUIRED,
    JobHistoryEntry,
)
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.video.video_review_group import ArmState, classify_entry

PHONE_QUEUE_PATH = "/v1/phone-queue"
PHONE_SUBMISSION = "phone_submission"
MAX_PHONE_JOBS = 250
_READ = re.compile(r"(list|receipt|result)(?:/([a-f0-9]{16}|[a-f0-9]{32}))?")
_KINDS = frozenset({"rework", "promptpack", "video", "video_eval", "followup"})
_EVAL_RUN_ID = re.compile(r"\d{8}_\d{6}_[A-Za-z0-9_-]{1,150}")
_PUBLIC_CAUSES = {
    INTERRUPTED_RESTART_ACTION_REQUIRED: "restart_action_required",
    CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN: "dispatch_uncertain",
    "ResourceLimitError": "resource_limit",
    "WatchdogViolationError": "watchdog_limit",
    "WebUIError": "backend_error",
    "ConfigError": "configuration_error",
}


def phone_owner(grant: PhoneGrant) -> str:
    return hashlib.sha256(f"phone-queue-v1:{grant.id}:{grant.host_secret}".encode()).hexdigest()


def phone_job_id(owner: str, receipt: str, position: int) -> str:
    return hashlib.sha256(f"phone-job-v1:{owner}:{receipt}:{position}".encode()).hexdigest()[:32]


def _claim(job: JobHistoryEntry | None, owner: str) -> dict[str, Any] | None:
    if job is None:
        return None
    record = (job.snapshot or {}).get("normalized_job", {})
    if not isinstance(record, dict) or record.get("job_id") != job.job_id:
        return None
    provenance = record.get("provenance", {})
    metadata = provenance.get("metadata", {}) if isinstance(provenance, dict) else None
    claim = metadata.get(PHONE_SUBMISSION) if isinstance(metadata, dict) else None
    if not isinstance(claim, dict) or claim.get("owner") != owner:
        return None
    receipt, kind, index, count = (claim.get(key) for key in ("receipt", "kind", "index", "count"))
    eval_run = claim.get("eval_run")
    if (
        isinstance(receipt, str)
        and IDENTIFIER.fullmatch(receipt)
        and isinstance(kind, str)
        and kind in _KINDS
        and (
            isinstance(eval_run, str) and _EVAL_RUN_ID.fullmatch(eval_run)
            if kind == "video_eval"
            else eval_run is None
        )
        and type(index) is int
        and type(count) is int
        and 0 <= index < count <= MAX_PHONE_JOBS
        and phone_job_id(owner, receipt, index) == job.job_id
    ):
        return claim
    return None


class PhoneQueueView:
    def __init__(self, repository: JobRepository, job_service: JobService) -> None:
        self._repository = repository
        self._jobs = job_service

    def _queued_cause(self) -> str | None:
        queue = self._jobs.queue
        if queue.is_gpu_quarantined():
            return "gpu_quarantine"
        if queue.is_webui_held():
            return "backend_hold"
        if queue.is_paused():
            return "queue_paused"
        if queue.is_dispatch_fenced():
            return "app_shutting_down"
        return None

    def _project(self, job: JobHistoryEntry, claim: dict[str, Any]) -> dict[str, Any]:
        cause = None
        if job.status is JobStatus.QUEUED:
            cause = self._queued_cause()
        elif job.error_envelope is not None:
            cause = _PUBLIC_CAUSES.get(job.error_envelope.error_type)
        if cause is None and job.status is JobStatus.FAILED:
            cause = "job_failed"
        return {
            "job_id": job.job_id,
            "receipt_id": claim["receipt"],
            "kind": claim["kind"],
            "status": "blocked" if job.status is JobStatus.QUEUED and cause else job.status.value,
            "cause": cause,
            "created_at": job.created_at.isoformat(),
            **({"eval_run": claim["eval_run"]} if "eval_run" in claim else {}),
        }

    def receipt(self, owner: str, receipt_id: str) -> dict[str, Any]:
        first = self._repository.get_job(phone_job_id(owner, receipt_id, 0))
        claim = _claim(first, owner)
        if first is None or claim is None or claim["receipt"] != receipt_id:
            return {"receipt_id": receipt_id, "state": "unconfirmed", "job_ids": []}
        job_ids = [phone_job_id(owner, receipt_id, index) for index in range(claim["count"])]
        jobs = self._repository.get_job_entries(job_ids)
        for index, job_id in enumerate(job_ids):
            if _claim(jobs.get(job_id), owner) != {**claim, "index": index}:
                return {"receipt_id": receipt_id, "state": "unconfirmed", "job_ids": []}
        return {
            "receipt_id": receipt_id,
            "state": "admitted",
            "job_ids": job_ids,
            "jobs": [self._project(jobs[job_id], claim) for job_id in job_ids],
            **({"eval_run": claim["eval_run"]} if "eval_run" in claim else {}),
        }

    def handle(
        self,
        catalog: SiteOutputCatalog,
        grant: PhoneGrant,
        route: str,
        method: object,
        body: object,
    ) -> dict[str, Any]:
        if method != "GET" or body is not None:
            raise SiteOutputError("phone_scope_refused")
        return self.read(catalog, grant, PHONE_QUEUE_PATH + "/" + route)

    def read(self, catalog: SiteOutputCatalog, grant: PhoneGrant, path: str) -> dict[str, Any]:
        match = _READ.fullmatch(path.removeprefix(PHONE_QUEUE_PATH + "/"))
        if match is None:
            raise SiteOutputError("unknown_route")
        action, identifier = match.groups()
        owner = phone_owner(grant)
        if action == "list" and (identifier is None or len(identifier) == 16):
            # The public cursor does not expose the repository's global insertion position.
            cursor_key = hashlib.sha256(f"phone-cursor-v1:{grant.host_secret}:{owner}".encode())
            mask = int(cursor_key.hexdigest()[:16], 16)
            before = int(identifier, 16) ^ mask if identifier else None
            jobs, cursor = self._repository.read_phone_job_page(owner, before=before)
            return {
                "jobs": [
                    self._project(job, claim) for job in jobs if (claim := _claim(job, owner))
                ],
                "next": f"{cursor ^ mask:016x}" if cursor is not None else None,
            }
        if identifier is None or not IDENTIFIER.fullmatch(identifier):
            raise SiteOutputError("unknown_route")
        if action == "receipt":
            return self.receipt(owner, identifier)
        if action == "result":
            job = self._repository.get_job(identifier)
            claim = _claim(job, owner)
            if job is None or claim is None:
                raise SiteOutputError("unknown_job")
            if claim["kind"] in {"video", "video_eval"}:
                state, _message, artifact_path = classify_entry(job)
                paths = (
                    [artifact_path]
                    if state is ArmState.PLAYABLE and artifact_path is not None
                    else []
                )
            else:
                paths = extract_reprocess_output_paths(None, job.result)
            media = catalog.results(paths) if job.status is JobStatus.COMPLETED else []
            return {**self._project(job, claim), "media": media}
        raise SiteOutputError("unknown_route")
