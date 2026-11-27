"""Bridge GUI run requests and witnessed previews to the queue submission worker."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from src.controller.pipeline_controller_services.preview_admission import (
    PreviewSupersededError,
    accepted_preview_records,
    release_admitted_draft,
)
from src.pipeline.config_contract_v26 import attach_config_layers


def queue_refusal_text(refusal: BaseException | str) -> str:
    """The on-screen wording of a Queue-time refusal: that nothing was queued, why, and what to do.

    Admission blocks write their own why and fix into the message; this only frames it.
    """

    reason = str(refusal).strip() or f"{type(refusal).__name__} (see the log)"
    if "nothing was queued" not in reason.lower():
        reason = f"Nothing was queued. {reason}"
    return f"{reason}\nThe Preview is kept: fix this, then queue again."


def report_queue_refusal(app_state: Any, refusal: BaseException | str | None) -> None:
    """Publish (or, with ``None``, clear) the refusal the Preview panel shows. Safe on a worker thread."""

    publish = getattr(app_state, "set_queue_refusal", None)
    if callable(publish):
        publish(None if refusal is None else queue_refusal_text(refusal))


class QueueRunSubmissionService:
    """Own the queue-backed run bridge used by AppController."""

    def __init__(
        self,
        *,
        append_log: Callable[[str], None],
        capture_stage_plan_for_tests: Callable[[Any], None],
    ) -> None:
        self._append_log = append_log
        self._capture_stage_plan_for_tests = capture_stage_plan_for_tests

    def accepted_preview_jobs(self, app_state: Any, pipeline_controller: Any) -> list[Any]:
        """Run / Run Now admit the accepted Preview's frozen records, not a fresh (re-sampled) compile.

        A compile that the draft outran is refused: nothing is returned (so nothing is queued) and the operator is told.
        """
        report_queue_refusal(app_state, None)  # a new Run: the previous refusal no longer applies
        try:
            return accepted_preview_records(app_state, pipeline_controller.get_preview_jobs)
        except PreviewSupersededError as exc:
            self._append_log(f"[controller] Run not submitted: {exc}")
            report_queue_refusal(app_state, exc)
            return []

    @staticmethod
    def release_admitted_draft(app_state: Any, admitted: list[Any]) -> bool:
        """Clear the draft after a successful Add to Queue, but never an edit made after the submission was admitted."""
        return release_admitted_draft(app_state, admitted)

    def ensure_queue_run_mode(self, app_state: Any, button_source: str) -> None:
        pipeline_state = getattr(app_state, "pipeline_state", None)
        if pipeline_state is None or not hasattr(pipeline_state, "run_mode"):
            return
        current = (getattr(pipeline_state, "run_mode", None) or "").strip().lower()
        if current == "queue":
            return
        pipeline_state.run_mode = "queue"
        if button_source == "run":
            self._append_log("[controller] Normalizing run_mode to 'queue' for Run button.")
        elif button_source == "run_now":
            self._append_log("[controller] Normalizing run_mode to 'queue' for Run Now button.")
        elif button_source == "add_to_queue":
            self._append_log(
                "[controller] Normalizing run_mode to 'queue' for Add to Queue button."
            )

    def build_run_config(self, app_state: Any, *, mode: str, source: str) -> dict[str, Any]:
        cfg: dict[str, Any] = {"run_mode": mode, "source": source}
        prompt_source = "manual"
        prompt_pack_id = ""
        adapter = getattr(app_state, "config_adapter", None)
        if adapter is not None and hasattr(adapter, "resolve_prompt_pack_context"):
            prompt_source, prompt_pack_id = adapter.resolve_prompt_pack_context()
        else:
            job_draft = getattr(app_state, "job_draft", None)
            if job_draft is not None:
                pack_id = getattr(job_draft, "pack_id", "") or ""
                if pack_id:
                    prompt_source = "pack"
                    prompt_pack_id = pack_id
        cfg["prompt_source"] = prompt_source
        if prompt_pack_id:
            cfg["prompt_pack_id"] = prompt_pack_id
        pipeline_state = getattr(app_state, "pipeline_state", None)
        if pipeline_state is not None:
            cfg["pipeline_state_snapshot"] = {
                "run_mode": getattr(pipeline_state, "run_mode", None),
                "stage_txt2img_enabled": getattr(pipeline_state, "stage_txt2img_enabled", None),
                "stage_img2img_enabled": getattr(pipeline_state, "stage_img2img_enabled", None),
                "stage_upscale_enabled": getattr(pipeline_state, "stage_upscale_enabled", None),
                "stage_adetailer_enabled": getattr(pipeline_state, "stage_adetailer_enabled", None),
            }
        return attach_config_layers(cfg, intent_config=cfg, execution_config={})

    def start_run(
        self,
        *,
        app_state: Any,
        pipeline_controller: Any,
        mode: str,
        source: str,
        set_last_run_config: Callable[[dict[str, Any]], None],
    ) -> Any:
        pipeline_state = getattr(app_state, "pipeline_state", None)
        if pipeline_state is not None:
            try:
                current_mode = getattr(pipeline_state, "run_mode", None)
                if current_mode != "queue":
                    pipeline_state.run_mode = "queue"
            except Exception:
                pass
        run_config = self.build_run_config(app_state, mode=mode, source=source)
        set_last_run_config(dict(run_config))
        if pipeline_controller is None:
            self._append_log(
                "[controller] _start_run_v2 aborted: pipeline_controller is unavailable."
            )
            return False
        try:
            self._capture_stage_plan_for_tests(pipeline_controller)
            self._append_log(
                f"[controller] _start_run_v2 via PipelineController.start_pipeline "
                f"(mode={mode}, source={source})"
            )
            return pipeline_controller.start_pipeline(run_config=run_config)
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[controller] _start_run_v2 bridge error: {exc!r}")
            return False


PreviewWitness = tuple[int, tuple[Any, ...]]


def same_preview(left: PreviewWitness, right: PreviewWitness) -> bool:
    """Match the revision and exact live immutable records, including records changed in place in GUI state."""
    revision, records = left
    return (
        revision == right[0]
        and bool(records)
        and len(records) == len(right[1])
        and all(a is b for a, b in zip(records, right[1], strict=True))
    )


def launch_preview_queue_submission(app: Any, *, expected_preview: PreviewWitness | None) -> bool:
    """Start the existing Add-to-Queue worker. An explicit witness has no draft fallback."""
    name = threading.current_thread().name

    def log(message: str) -> None:
        app._append_log(f"[controller] {message} (thread={name})")

    app._append_log(f"[D21] on_add_job_to_queue_v2 ENTRY (thread={name})")
    try:
        app._ensure_run_mode_default("add_to_queue")
        if app._is_preview_queue_submission_blocked():
            log("Ignoring add-to-queue request because shutdown is in progress")
            return False
        controller = getattr(app, "pipeline_controller", None)
        run_config = app._prepare_queue_run_config()
        if getattr(app, "_queue_submit_in_progress", False):
            log("Queue submission already in progress; ignoring duplicate request")
            return False
        if controller is None:
            log("enqueue_draft_jobs unavailable: pipeline_controller missing")
            return False

        state = getattr(app, "app_state", None)
        if expected_preview is None:
            records = list(getattr(state, "preview_jobs", None) or [])
        else:
            if state is None:
                return False
            current = state.snapshot_accepted_preview()
            if not same_preview(expected_preview, current):
                log("Preview changed before Site submission")
                return False
            records = list(current[1])
        try:
            app._queue_submit_in_progress = True
            report_queue_refusal(state, None)
            log(
                f"Queueing preview jobs in background (count={len(records) if records else 'draft'})"
            )
            spawn_thread = getattr(app, "_spawn_tracked_thread", None)
            if callable(spawn_thread):
                spawn_thread(
                    target=app._submit_preview_jobs_to_queue_async,
                    args=(controller, records, run_config, name),
                    name="PreviewQueueSubmit",
                    purpose="Submit preview jobs to queue asynchronously",
                )
            else:
                app._submit_preview_jobs_to_queue_async(controller, records, run_config, name)
        except Exception as exc:  # noqa: BLE001 - keep native callback failure handling
            app._queue_submit_in_progress = False
            log(f"enqueue_draft_jobs error: {exc!r}")
            return False
        return True
    finally:
        app._append_log(f"[D21] on_add_job_to_queue_v2 EXIT (thread={name})")
