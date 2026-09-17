"""Frozen experiment preview and one-boundary queue admission helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord


def freeze_snapshot(payload: dict[str, Any]) -> str:
    """Return a deterministic immutable representation of an experiment baseline."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def thaw_snapshot(snapshot_json: str) -> dict[str, Any]:
    """Return an isolated copy of a stored preview snapshot."""

    payload = json.loads(snapshot_json)
    if not isinstance(payload, dict):
        raise ValueError("experiment execution snapshot must be an object")
    return payload


def snapshot_digest(snapshot_json: str) -> str:
    return hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExperimentAdmission:
    """All precompiled records for one atomically admitted experiment."""

    records: tuple[NormalizedJobRecord, ...]


class ExperimentAdmissionService:
    """Compile first, then cross the existing JobService boundary exactly once."""

    def compile_all(
        self,
        variants: list[Any],
        build_record: Callable[[Any], NormalizedJobRecord],
    ) -> ExperimentAdmission:
        records = tuple(build_record(variant) for variant in variants)
        if not records:
            raise ValueError("experiment has no pending variants to admit")
        return ExperimentAdmission(records=records)

    def submit(self, admission: ExperimentAdmission, job_service: Any) -> list[str]:
        submit_njrs = getattr(job_service, "submit_njrs", None)
        if not callable(submit_njrs):
            raise RuntimeError("JobService.submit_njrs is unavailable")
        # JobService/repository owns the transactional all-or-none admission.
        result = submit_njrs(list(admission.records), SubmissionPolicy())
        return [str(job_id) for job_id in (result or [])]
