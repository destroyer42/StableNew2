from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord


class QueueSubmissionService:
    """Own queue submission orchestration for normalized preview/history jobs."""

    def __init__(self, *, job_service: Any, logger: logging.Logger | None = None) -> None:
        self._job_service = job_service
        self._logger = logger or logging.getLogger(__name__)

    def split_queueable_records(
        self,
        records: list[NormalizedJobRecord],
    ) -> tuple[list[NormalizedJobRecord], list[NormalizedJobRecord]]:
        queueable: list[NormalizedJobRecord] = []
        non_queueable: list[NormalizedJobRecord] = []
        for record in records:
            config = record.config or {}
            prompt_pack_id = record.prompt_pack_id or (
                config.get("prompt_pack_id") if isinstance(config, dict) else None
            )
            prompt_source = str(getattr(record, "prompt_source", "") or "").lower()
            if prompt_pack_id or prompt_source != "pack":
                queueable.append(record)
            else:
                non_queueable.append(record)
        return queueable, non_queueable

    def sort_jobs_by_model(
        self,
        records: list[NormalizedJobRecord],
    ) -> list[NormalizedJobRecord]:
        def _extract_model_vae_key(record: NormalizedJobRecord) -> tuple[str, str]:
            config = record.config or {}
            if not isinstance(config, dict):
                return ("", "")

            model = config.get("model_name") or config.get("model") or ""
            if not model:
                txt2img = config.get("txt2img", {})
                if isinstance(txt2img, dict):
                    model = txt2img.get("model_name") or txt2img.get("model") or ""

            vae = config.get("vae") or config.get("sd_vae") or ""
            if not vae:
                txt2img = config.get("txt2img", {})
                if isinstance(txt2img, dict):
                    vae = txt2img.get("vae") or txt2img.get("sd_vae") or ""
            model_key = str(model).strip().lower()
            vae_key = str(vae).strip().lower()
            if vae_key in {"", "automatic", "none"}:
                vae_key = "automatic"
            return model_key, vae_key

        sorted_records = sorted(
            records,
            key=lambda r: (
                _extract_model_vae_key(r)[0] == "",
                _extract_model_vae_key(r)[0],
                _extract_model_vae_key(r)[1],
            ),
        )

        if len(sorted_records) > 1:
            model_groups: dict[str, int] = {}
            for record in sorted_records:
                model, vae = _extract_model_vae_key(record)
                group_key = f"{model or '(none)'}|vae={vae}"
                model_groups[group_key] = model_groups.get(group_key, 0) + 1
            self._logger.info(
                "[QueueSubmissionService] Job grouping by model+vae: %s",
                ", ".join(f"{group}: {count}" for group, count in model_groups.items()),
            )
        return sorted_records

    def submit_normalized_jobs(
        self,
        records: list[NormalizedJobRecord],
        *,
        policy: SubmissionPolicy | None = None,
        can_enqueue_learning_jobs: Callable[[int], tuple[bool, str]],
        is_queue_submission_blocked: Callable[[], bool],
        sort_jobs_by_model: Callable[[list[NormalizedJobRecord]], list[NormalizedJobRecord]],
    ) -> int:
        if not records or not self._job_service:
            return 0
        learning_count = sum(
            1 for record in records if record.source.kind.value == "learning"
        )
        if learning_count:
            allowed, reason = can_enqueue_learning_jobs(learning_count)
            if not allowed:
                self._logger.warning(
                    "[QueueSubmissionService] Learning enqueue blocked: %s", reason
                )
                return 0
        if is_queue_submission_blocked():
            self._logger.info(
                "[QueueSubmissionService] Skipping queue submission because shutdown is in progress"
            )
            return 0

        records = sort_jobs_by_model(records)
        if is_queue_submission_blocked():
            self._logger.info(
                "[QueueSubmissionService] Skipping queue submission because shutdown is in progress"
            )
            return 0
        job_ids = self._job_service.submit_njrs(records, policy or SubmissionPolicy())
        return len(job_ids)


__all__ = ["QueueSubmissionService"]
