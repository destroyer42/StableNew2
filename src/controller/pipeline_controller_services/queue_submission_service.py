from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

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

    def ensure_record_prompt_pack_metadata(
        self,
        record: NormalizedJobRecord,
        prompt_pack_id: str | None,
        prompt_pack_name: str | None,
    ) -> None:
        if not prompt_pack_id:
            return
        record.prompt_source = "pack"
        if not getattr(record, "prompt_pack_id", None):
            record.prompt_pack_id = prompt_pack_id
        if prompt_pack_name and not getattr(record, "prompt_pack_name", None):
            record.prompt_pack_name = prompt_pack_name

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
        run_config: dict[str, Any] | None,
        source: str,
        prompt_source: str,
        last_run_config: dict[str, Any] | None,
        can_enqueue_learning_jobs: Callable[[int], tuple[bool, str]],
        is_queue_submission_blocked: Callable[[], bool],
        sort_jobs_by_model: Callable[[list[NormalizedJobRecord]], list[NormalizedJobRecord]],
        ensure_record_prompt_pack_metadata: Callable[[NormalizedJobRecord, str | None, str | None], None],
        to_queue_job: Callable[..., Any],
        log_add_to_queue_event: Callable[[str], None],
        run_job_payload_factory: Callable[[Any], Callable[[], dict[str, Any]]] | None = None,
    ) -> int:
        if not records or not self._job_service:
            return 0
        if str(source).startswith("learning_"):
            allowed, reason = can_enqueue_learning_jobs(len(records))
            if not allowed:
                self._logger.warning("[QueueSubmissionService] Learning enqueue blocked: %s", reason)
                return 0
        if is_queue_submission_blocked():
            self._logger.info(
                "[QueueSubmissionService] Skipping queue submission because shutdown is in progress"
            )
            return 0

        submit_job = getattr(self._job_service, "submit_job_with_run_mode", None)
        emit_queue_updated = getattr(self._job_service, "_emit_queue_updated", None)
        queue = getattr(self._job_service, "job_queue", None)
        coalesce_queue_state = getattr(queue, "coalesce_state_notifications", None)
        submitted = 0
        run_config_to_use = run_config or last_run_config
        raw_auto_run_enabled = getattr(self._job_service, "auto_run_enabled", False)
        auto_run_enabled = raw_auto_run_enabled if isinstance(raw_auto_run_enabled, bool) else False
        run_next_now = getattr(self._job_service, "run_next_now", None)
        batch_context = nullcontext()
        if callable(coalesce_queue_state):
            candidate_context = coalesce_queue_state()
            if hasattr(candidate_context, "__enter__") and hasattr(candidate_context, "__exit__"):
                batch_context = candidate_context

        records = sort_jobs_by_model(records)
        if auto_run_enabled:
            try:
                self._job_service.auto_run_enabled = False
            except Exception:
                auto_run_enabled = False

        try:
            with batch_context:
                for record in records:
                    if is_queue_submission_blocked():
                        self._logger.info(
                            "[QueueSubmissionService] Stopping queue submission after %d/%d jobs because shutdown is in progress",
                            submitted,
                            len(records),
                        )
                        break
                    cfg = record.config
                    prompt_pack_id = cfg.get("prompt_pack_id") if isinstance(cfg, dict) else None
                    if prompt_pack_id and not getattr(record, "prompt_pack_id", None):
                        try:
                            record.prompt_pack_id = prompt_pack_id  # type: ignore[attr-defined]
                        except Exception:
                            record.prompt_pack_id = prompt_pack_id
                    prompt_pack_name = None
                    if isinstance(cfg, dict):
                        prompt_pack_name = cfg.get("prompt_pack_name") or cfg.get("pack_name")
                    ensure_record_prompt_pack_metadata(record, prompt_pack_id, prompt_pack_name)
                    job = to_queue_job(
                        record,
                        run_mode="queue",
                        source=source,
                        prompt_source=prompt_source,
                        prompt_pack_id=prompt_pack_id,
                        run_config=run_config_to_use,
                    )
                    if run_job_payload_factory is not None:
                        job.payload = run_job_payload_factory(job)
                    if not hasattr(job, "_normalized_record") or job._normalized_record is None:
                        self._logger.warning(
                            "PR-CORE1-B2: Job submitted without normalized_record in NJR-only mode. Source: %s",
                            source,
                        )

                    accepted = True
                    if callable(submit_job):
                        try:
                            result = submit_job(job, emit_queue_updated=False)
                        except TypeError:
                            result = submit_job(job)
                        accepted = result is not False

                    if not accepted:
                        self._logger.warning(
                            "[QueueSubmissionService] Job %s was rejected during queue submission",
                            getattr(job, "job_id", None),
                        )
                        continue

                    log_add_to_queue_event(job.job_id)
                    submitted += 1
        finally:
            if auto_run_enabled:
                try:
                    self._job_service.auto_run_enabled = True
                except Exception:
                    pass

        if submitted > 0 and callable(emit_queue_updated):
            try:
                emit_queue_updated()
            except Exception:
                self._logger.exception(
                    "[QueueSubmissionService] Failed to emit coalesced queue update after batch submission",
                    exc_info=True,
                )
        if submitted > 0 and auto_run_enabled and callable(run_next_now) and not is_queue_submission_blocked():
            try:
                run_next_now()
            except Exception:
                self._logger.exception(
                    "[QueueSubmissionService] Failed to start queue worker after batch submission",
                    exc_info=True,
                )
        return submitted


__all__ = ["QueueSubmissionService"]
