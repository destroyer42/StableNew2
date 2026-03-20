from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from src.pipeline.config_contract_v26 import attach_config_layers


class QueueRunSubmissionService:
    """Own the queue-backed run bridge used by AppController."""

    def __init__(
        self,
        *,
        append_log: Callable[[str], None],
        capture_stage_plan_for_tests: Callable[[Any], None],
        invoke_mock_generate_for_tests: Callable[[], None],
    ) -> None:
        self._append_log = append_log
        self._capture_stage_plan_for_tests = capture_stage_plan_for_tests
        self._invoke_mock_generate_for_tests = invoke_mock_generate_for_tests

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
            self._append_log("[controller] Normalizing run_mode to 'queue' for Add to Queue button.")

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
            self._append_log("[controller] _start_run_v2 aborted: pipeline_controller is unavailable.")
            return False
        try:
            pytest_flag = os.environ.get("PYTEST_CURRENT_TEST")
            if not pytest_flag:
                os.environ.pop("PYTEST_CURRENT_TEST", None)
            else:
                self._invoke_mock_generate_for_tests()
            self._capture_stage_plan_for_tests(pipeline_controller)
            self._append_log(
                f"[controller] _start_run_v2 via PipelineController.start_pipeline "
                f"(mode={mode}, source={source})"
            )
            return pipeline_controller.start_pipeline(run_config=run_config)
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[controller] _start_run_v2 bridge error: {exc!r}")
            return False
