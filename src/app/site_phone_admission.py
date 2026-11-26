"""Prepare and admit one explicitly reviewed phone Preview through the native services."""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import PureWindowsPath
from threading import Lock
from typing import TYPE_CHECKING, Any

from src.app.site_media_files import SiteOutputError
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_pack_catalog import PreparePack, SitePackCatalog
from src.app.site_phone_credentials import IDENTIFIER, PhoneGrant
from src.app.site_phone_queue import (
    MAX_PHONE_JOBS,
    PHONE_SUBMISSION,
    PhoneQueueView,
    phone_job_id,
    phone_owner,
)
from src.controller.job_service import JobService
from src.controller.reprocess_admission import submit_reprocess_njrs
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord, UnifiedJobSummary, WorkloadKind
from src.pipeline.njr_compiler import NjrDerivation, derive_njr
from src.pipeline.policy_warnings import SURFACE_PHONE, PolicyWarning, with_accepted_warnings

if TYPE_CHECKING:
    from src.app.site_phone_followup import PhoneFollowup
    from src.app.site_phone_video import PhoneVideo

_DIGEST = re.compile(r"[a-f0-9]{64}")
REWORK_STAGES = frozenset({"img2img", "adetailer", "upscale"})
_PREVIEW_SECONDS = 600
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhonePreviewInput:
    label: str
    records: tuple[NormalizedJobRecord, ...]
    require_current: Callable[[], None]
    job_details: tuple[dict[str, Any], ...] = ()
    admit: Callable[[tuple[NormalizedJobRecord, ...]], None] | None = None
    eval_run: str = ""


@dataclass(frozen=True)
class _FrozenPreview:
    id: str
    owner: str
    scope: str
    kind: str
    until: float
    draft: PhonePreviewInput
    evidence_kind: str = ""


def _preview_job(record: NormalizedJobRecord) -> dict[str, Any]:
    summary = UnifiedJobSummary.from_normalized_record(record)
    config = record.config
    img2img = config.get("img2img")
    adetailer = config.get("adetailer")
    upscale = config.get("upscale")
    enabled = set(record.stage_chain_labels)
    return {
        "job_id": record.job_id,
        "stages": record.stage_chain_labels,
        "model": PureWindowsPath(summary.base_model).name if summary.base_model else "",
        "slot": summary.prompt_pack_row_index + 1 if record.prompt_pack_id else None,
        "width": summary.width,
        "height": summary.height,
        "sampler": summary.sampler_name,
        "steps": summary.steps,
        "cfg": summary.cfg_scale,
        "seed": record.seed,
        "denoise": img2img.get("denoising_strength")
        if "img2img" in enabled and isinstance(img2img, Mapping)
        else None,
        "detector": PureWindowsPath(str(adetailer.get("adetailer_model") or "")).name
        if "adetailer" in enabled and isinstance(adetailer, Mapping)
        else "",
        "upscaler": PureWindowsPath(str(upscale.get("upscaler") or "")).name
        if "upscale" in enabled and isinstance(upscale, Mapping)
        else "",
        "scale": upscale.get("scale_factor")
        if "upscale" in enabled and isinstance(upscale, Mapping)
        else None,
    }


def phone_records(
    owner: str,
    identifier: str,
    kind: str,
    records: tuple[NormalizedJobRecord, ...] | list[NormalizedJobRecord],
    *,
    eval_run: str = "",
    claim: Mapping[str, str] | None = None,
) -> tuple[NormalizedJobRecord, ...]:
    """The phone-owned identities of ``records``: deterministic job ids and the ``phone_submission`` claim.

    One derivation for every phone channel (the hosted relay's Preview and the review gateway's actions), so a
    phone receipt always names exactly the jobs it admitted.
    """

    return tuple(
        derive_njr(
            record,
            NjrDerivation(
                job_id=phone_job_id(owner, identifier, index),
                provenance=replace(
                    record.provenance,
                    metadata={
                        **record.provenance.metadata,
                        PHONE_SUBMISSION: {
                            **(claim or {}),
                            "owner": owner,
                            "receipt": identifier,
                            "kind": kind,
                            "index": index,
                            "count": len(records),
                            **({"eval_run": eval_run} if eval_run else {}),
                        },
                    },
                ),
            ),
        )
        for index, record in enumerate(records)
    )


def admit_phone_records(
    jobs: JobService,
    view: PhoneQueueView,
    owner: str,
    identifier: str,
    kind: str,
    records: tuple[NormalizedJobRecord, ...],
    warnings: tuple[PolicyWarning, ...],
    *,
    reprocess: bool,
    policy: SubmissionPolicy,
    claim: Mapping[str, str] | None = None,
) -> list[str]:
    """Admit one phone request through ``JobService.submit_njrs`` exactly once (RG-100 invariant 6).

    The warnings the phone showed are frozen into provenance as accepted on the phone (S12). The job ids are
    deterministic, so a request that was already admitted (a resent record, a restart between admission and its
    receipt) answers with the existing receipt instead of admitting twice. Raises ``SiteOutputError`` when nothing
    was admitted.
    """

    if not 1 <= len(records) <= MAX_PHONE_JOBS:
        raise SiteOutputError("image_preview_required")
    existing = view.receipt(owner, identifier)
    if existing["state"] == "admitted":
        return list(existing["job_ids"])
    if jobs.queue.is_dispatch_fenced():
        raise SiteOutputError("app_shutting_down")
    derived = [
        with_accepted_warnings(record, warnings, surface=SURFACE_PHONE)
        for record in phone_records(owner, identifier, kind, records, claim=claim)
    ]
    try:
        if reprocess:
            submit_reprocess_njrs(jobs, derived, surface=SURFACE_PHONE, policy=policy)
        else:
            jobs.submit_njrs(derived, policy)
    except Exception as exc:  # noqa: BLE001 - an exception can arrive after the native commit
        admitted = view.receipt(owner, identifier)
        if admitted["state"] == "admitted":
            log.exception("A phone request was admitted but its submission reported an error")
            return list(admitted["job_ids"])
        raise SiteOutputError("admission_refused") from exc
    return [record.job_id for record in derived]


class PhoneQueueAdmission:
    def __init__(
        self,
        queue_view: PhoneQueueView,
        jobs: JobService,
        *,
        packs: Callable[[], SitePackCatalog],
        compile_pack: Callable[[PreparePack], PhonePreviewInput],
        compile_rework: Callable[[SiteOutputCatalog, str, str, str], PhonePreviewInput],
        video: PhoneVideo | None = None,
        followup: PhoneFollowup | None = None,
    ) -> None:
        self._queue = queue_view
        self._jobs = jobs
        self._packs = packs
        self._compile_pack = compile_pack
        self._compile_rework = compile_rework
        self._video = video
        self._followup = followup
        self._lock = Lock()
        self._catalog: tuple[str, str, SitePackCatalog] | None = None
        self._preview: _FrozenPreview | None = None
        self._refused: tuple[str, str, str] | None = None

    def handle(
        self,
        catalog: SiteOutputCatalog,
        grant: PhoneGrant,
        route: str,
        method: object,
        body: object,
    ) -> dict[str, Any]:
        owner = phone_owner(grant)
        if method == "GET" and body is None and route.startswith("receipt/"):
            identifier = route.removeprefix("receipt/")
            if IDENTIFIER.fullmatch(identifier):
                return self._receipt(owner, identifier)
        if (
            method == "GET"
            and body is None
            and route.split("/", 1)[0] in {"list", "receipt", "result"}
        ):
            return self._queue.handle(catalog, grant, route, method, body)
        if not grant.queue_submit:
            raise SiteOutputError("phone_scope_refused")
        if method == "GET" and body is None:
            if route == "video-options" and self._video is not None:
                return self._video.options()
            if route == "packs":
                shared = self._packs()
                catalog.require_active()
                self._catalog = owner, catalog.scope, shared
                return {"packs": shared.list_packs()}
            key = route.removeprefix("packs/")
            if route.startswith("packs/") and IDENTIFIER.fullmatch(key):
                shared = self._pack_catalog(owner, catalog)
                try:
                    return shared.describe(key)
                except ValueError as exc:
                    raise SiteOutputError("promptpack_changed") from exc
        if method == "POST" and isinstance(body, dict):
            if route == "followup" and self._followup is not None:
                return self._followup.suggest(catalog, grant, body)
            if route == "preview":
                return self._prepare(owner, catalog, grant, body)
            if route == "submit":
                return self._submit(owner, catalog, grant, body)
        raise SiteOutputError("phone_scope_refused")

    def _pack_catalog(self, owner: str, catalog: SiteOutputCatalog) -> SitePackCatalog:
        current = self._catalog
        if current is None or current[:2] != (owner, catalog.scope):
            raise SiteOutputError("refresh_promptpacks")
        return current[2]

    def _prepare(
        self, owner: str, catalog: SiteOutputCatalog, grant: PhoneGrant, body: dict[str, Any]
    ) -> dict[str, Any]:
        kind = body.get("kind")
        evidence_kind = ""
        workload = WorkloadKind.IMAGE
        with self._lock:
            self._preview = None
        if kind == "promptpack" and body.keys() == {"kind", "pack_id", "revision", "slots"}:
            key, revision, slots = (body[field] for field in ("pack_id", "revision", "slots"))
            if not (
                isinstance(key, str)
                and IDENTIFIER.fullmatch(key)
                and isinstance(revision, str)
                and _DIGEST.fullmatch(revision)
                and isinstance(slots, list)
                and 1 <= len(slots) <= 16
                and all(type(slot) is int and 0 <= slot < 500 for slot in slots)
                and len(set(slots)) == len(slots)
            ):
                raise SiteOutputError("invalid_preview")
            shared = self._pack_catalog(owner, catalog)
            try:
                command = shared.prepare(key, revision, tuple(slots))
            except (OSError, ValueError) as exc:
                raise SiteOutputError("promptpack_changed") from exc
            draft = self._compile_pack(command)
        elif kind == "rework" and body.keys() == {"kind", "id", "scope", "digest", "stage"}:
            key, scope, digest, stage = (
                body[field] for field in ("id", "scope", "digest", "stage")
            )
            if not (
                scope == catalog.scope
                and isinstance(key, str)
                and IDENTIFIER.fullmatch(key)
                and isinstance(digest, str)
                and _DIGEST.fullmatch(digest)
                and isinstance(stage, str)
                and stage in REWORK_STAGES
            ):
                raise SiteOutputError("invalid_preview")
            draft = self._compile_rework(catalog, key, digest, stage)
        elif kind in ("video", "video_eval") and self._video is not None:
            draft = self._video.preview(catalog, body, evaluation=kind == "video_eval")
            workload = WorkloadKind.VIDEO
        elif kind == "followup" and self._followup is not None:
            draft = self._followup.preview(catalog, grant, body)
            evidence_kind = body["source"]["kind"]
            kind = "video_eval" if draft.eval_run else "followup"
            workload = WorkloadKind.VIDEO if draft.eval_run else WorkloadKind.IMAGE
        else:
            raise SiteOutputError("invalid_preview")
        if not 1 <= len(draft.records) <= MAX_PHONE_JOBS or any(
            record.workload_kind is not workload for record in draft.records
        ):
            raise SiteOutputError(
                "image_preview_required"
                if workload is WorkloadKind.IMAGE
                else "video_preview_failed"
            )
        draft.require_current()
        catalog.require_active()
        identifier = secrets.token_hex(16)
        records = phone_records(owner, identifier, kind, draft.records, eval_run=draft.eval_run)
        with self._lock:
            self._preview = _FrozenPreview(
                identifier,
                owner,
                catalog.scope,
                kind,
                time.monotonic() + _PREVIEW_SECONDS,
                replace(draft, records=records),
                evidence_kind,
            )
        return {
            "preview_id": identifier,
            "kind": body["kind"],
            "label": draft.label,
            "jobs": [
                {"job_id": record.job_id, "stages": record.stage_chain_labels, **details}
                for record, details in zip(records, draft.job_details, strict=True)
            ]
            if draft.job_details
            else [_preview_job(record) for record in records],
        }

    def _refusal(self, identifier: str, reason: str) -> dict[str, Any]:
        return {"state": "refused", "receipt_id": identifier, "cause": reason, "job_ids": []}

    def _receipt(self, owner: str, identifier: str) -> dict[str, Any]:
        with self._lock:
            refused = self._refused
        if refused and refused[:2] == (owner, identifier):
            return self._refusal(identifier, refused[2])
        return self._queue.receipt(owner, identifier)

    def _submit(
        self, owner: str, catalog: SiteOutputCatalog, grant: PhoneGrant, body: dict[str, Any]
    ) -> dict[str, Any]:
        identifier = body.get("preview_id")
        if body.keys() != {"preview_id", "confirmed"} or not (
            body["confirmed"] is True
            and isinstance(identifier, str)
            and IDENTIFIER.fullmatch(identifier)
        ):
            raise SiteOutputError("invalid_preview")
        with self._lock:
            preview = self._preview
            if preview is not None and (preview.owner, preview.id) == (owner, identifier):
                self._preview = None
            else:
                preview = None
        if preview is None:
            return self._receipt(owner, identifier)
        try:
            if (
                preview.evidence_kind in {"rating", "returned"}
                and not grant.native_review
                or preview.evidence_kind == "evaluation"
                and not grant.rating
            ):
                raise SiteOutputError("phone_scope_refused")
            if preview.scope != catalog.scope or preview.until <= time.monotonic():
                raise SiteOutputError("preview_changed")
            if self._jobs.queue.is_dispatch_fenced():
                raise SiteOutputError("app_shutting_down")
            preview.draft.require_current()
            catalog.require_active()
        except (SiteOutputError, ValueError, OSError) as exc:
            reason = str(exc) if isinstance(exc, SiteOutputError) else "preview_changed"
            with self._lock:
                self._refused = owner, identifier, reason
            return self._refusal(identifier, reason)
        try:
            if preview.draft.admit is not None:
                preview.draft.admit(preview.draft.records)
            elif preview.kind == "rework":
                submit_reprocess_njrs(self._jobs, list(preview.draft.records))
            else:
                self._jobs.submit_njrs(preview.draft.records)
        except Exception:  # noqa: BLE001 - an exception can arrive after the native commit
            log.exception("Unable to confirm the phone submission; inspect its native receipt")
        return self._queue.receipt(owner, identifier)
