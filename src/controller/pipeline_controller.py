"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller."""

from __future__ import annotations

import uuid

from typing import Callable, Any

from src.controller.job_service import JobService
from src.gui.controller import PipelineController as _GUIPipelineController
from src.gui.state import StateManager
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.controller.job_execution_controller import JobExecutionController
from src.controller.queue_execution_controller import QueueExecutionController
from src.queue.job_model import JobStatus, Job, JobPriority
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.pipeline.pipeline_runner import PipelineRunResult, PipelineConfig, PipelineRunner
from src.gui.state import GUIState
from src.controller.webui_connection_controller import WebUIConnectionController, WebUIConnectionState
from src.config import app_config
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides, RunPlan, PlannedJob
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.state import PipelineState
from src.api.client import SDWebUIClient
from src.utils import StructuredLogger


class PipelineController(_GUIPipelineController):
    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower == "direct":
            return "direct"
        return "queue"

    def _build_job(
        self,
        config: PipelineConfig,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        lora_settings: dict | None = None,
        randomizer_metadata: dict | None = None,
        learning_enabled: bool = False,
    ) -> Job:
        """Build a Job with full metadata for provenance tracking (PR-106)."""
        # Create config snapshot for auditing
        config_snapshot: dict[str, Any] = {}
        if config is not None:
            try:
                config_snapshot = {
                    "prompt": getattr(config, "prompt", ""),
                    "model": getattr(config, "model", "") or getattr(config, "model_name", ""),
                    "steps": getattr(config, "steps", None),
                    "cfg_scale": getattr(config, "cfg_scale", None),
                    "width": getattr(config, "width", None),
                    "height": getattr(config, "height", None),
                    "sampler": getattr(config, "sampler", None),
                }
            except Exception:
                config_snapshot = {}

        return Job(
            job_id=str(uuid.uuid4()),
            pipeline_config=config,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            lora_settings=lora_settings,
            randomizer_metadata=randomizer_metadata,
            learning_enabled=learning_enabled,
        )

    def _coerce_overrides(self, overrides: GuiOverrides | dict[str, Any] | None) -> GuiOverrides:
        if isinstance(overrides, GuiOverrides):
            return overrides
        if isinstance(overrides, dict):
            return GuiOverrides(
                prompt=str(overrides.get("prompt", "")),
                model=str(overrides.get("model", "")),
                model_name=str(overrides.get("model_name", overrides.get("model", ""))),
                vae_name=str(overrides.get("vae_name", "")),
                sampler=str(overrides.get("sampler", "")),
                width=int(overrides.get("width", 512) or 512),
                height=int(overrides.get("height", 512) or 512),
                steps=int(overrides.get("steps", 20) or 20),
                cfg_scale=float(overrides.get("cfg_scale", 7.0) or 7.0),
                resolution_preset=str(overrides.get("resolution_preset", "")),
                negative_prompt=str(overrides.get("negative_prompt", "")),
                output_dir=str(overrides.get("output_dir", "")),
                filename_pattern=str(overrides.get("filename_pattern", "")),
                image_format=str(overrides.get("image_format", "")),
                batch_size=int(overrides.get("batch_size", 1) or 1),
                seed_mode=str(overrides.get("seed_mode", "")),
                metadata=dict(overrides.get("metadata") or {}),
            )
        return GuiOverrides()

    def _extract_state_overrides(self) -> GuiOverrides:
        extractor = getattr(self.state_manager, "get_pipeline_overrides", None)
        if callable(extractor):
            try:
                return self._coerce_overrides(extractor())
            except Exception:
                pass

        if hasattr(self.state_manager, "pipeline_overrides"):
            try:
                return self._coerce_overrides(getattr(self.state_manager, "pipeline_overrides"))
            except Exception:
                pass

        fallback = getattr(self, "get_gui_overrides", None)
        if callable(fallback):
            try:
                return self._coerce_overrides(fallback())
            except Exception:
                pass

        return GuiOverrides()

    def get_webui_connection_state(self):
        if hasattr(self, "_webui_connection") and self._webui_connection is not None:
            return self._webui_connection.get_state()
        return None


    def _extract_metadata(self, attr_name: str) -> dict[str, Any] | None:
        value = None
        accessor = getattr(self.state_manager, attr_name, None)
        if callable(accessor):
            try:
                value = accessor()
            except Exception:
                value = None
        elif accessor is not None:
            value = accessor

        if isinstance(value, dict):
            return dict(value)
        return None

    def _build_pipeline_config_from_state(self) -> PipelineConfig:
        overrides = self._extract_state_overrides()
        learning_metadata = self._extract_metadata("learning_metadata")
        randomizer_metadata = self._extract_metadata("randomizer_metadata")

        if learning_metadata is None and self._learning_enabled:
            learning_metadata = {"learning_enabled": True}

        return self._config_assembler.build_from_gui_input(
            overrides=overrides,
            learning_metadata=learning_metadata,
            randomizer_metadata=randomizer_metadata,
        )

    def build_pipeline_config_with_profiles(
        self,
        base_model_name: str,
        lora_names: list[str],
        user_overrides: dict[str, any],
    ) -> dict:
        """Build pipeline config using ModelProfile and LoraProfile priors."""
        from pathlib import Path
        from src.learning.model_profiles import find_model_profile_for_checkpoint, find_lora_profile_for_name, suggest_preset_for
        # Resolve checkpoint path (stub: assumes models are in 'models/' dir)
        checkpoint_path = Path("models") / f"{base_model_name}.ckpt"
        model_profile = find_model_profile_for_checkpoint(checkpoint_path)
        lora_search_paths = [Path("loras")]
        lora_profiles = [find_lora_profile_for_name(name, lora_search_paths) for name in lora_names]
        lora_profiles = [lp for lp in lora_profiles if lp]
        suggested = suggest_preset_for(model_profile, lora_profiles)
        # Start from default config
        config = self.get_default_config() if hasattr(self, "get_default_config") else {}
        # Always ensure txt2img key exists and populate with defaults if missing
        if "txt2img" not in config:
            config["txt2img"] = {
                "sampler_name": "Euler",
                "scheduler": None,
                "steps": 20,
                "cfg_scale": 5.0,
                "width": 512,
                "height": 512,
                "loras": [],
            }
        # Apply suggested preset if available
        if suggested:
            config["txt2img"].update({
                "sampler_name": suggested.sampler,
                "scheduler": suggested.scheduler,
                "steps": suggested.steps,
                "cfg_scale": suggested.cfg,
                "width": suggested.resolution[0],
                "height": suggested.resolution[1],
            })
            # Apply LoRA weights
            config["txt2img"]["loras"] = [
                {"name": name, "weight": suggested.lora_weights.get(name, 0.6)} for name in lora_names
            ]
            import logging
            logging.info(f"Using model profile preset {suggested.preset_id} (source={suggested.source}) for {base_model_name} + {lora_names}.")
        # Apply user overrides last
        for k, v in user_overrides.items():
            # Map common override keys to txt2img
            if k in ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height", "loras"):
                config["txt2img"][k] = v
            elif k == "cfg":
                config["txt2img"]["cfg_scale"] = v
            elif k == "resolution" and isinstance(v, (tuple, list)) and len(v) == 2:
                config["txt2img"]["width"] = v[0]
                config["txt2img"]["height"] = v[1]
            else:
                config[k] = v
        return config

    """Provide a default StateManager so legacy imports keep working."""

    def __init__(
        self,
        state_manager: StateManager | None = None,
        *,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: PipelineConfigAssembler | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        api_client = kwargs.pop("api_client", None)
        job_service = kwargs.pop("job_service", None)
        structured_logger = kwargs.pop("structured_logger", None)
        pipeline_runner = kwargs.pop("pipeline_runner", None)
        
        queue_execution_controller = kwargs.pop("queue_execution_controller", None)
        webui_conn = kwargs.pop("webui_connection_controller", None)
        super().__init__(state_manager or StateManager(), **kwargs)
        self._learning_runner = None
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_learning_record: LearningRecord | None = None
        self._last_run_result: PipelineRunResult | None = None
        self._last_stage_execution_plan: StageExecutionPlan | None = None
        self._last_stage_events: list[dict[Any, Any]] | None = None
        self._learning_enabled: bool = False
        self._job_controller = JobExecutionController(execute_job=self._execute_job)
        self._queue_execution_controller: QueueExecutionController | None = queue_execution_controller or QueueExecutionController(job_controller=self._job_controller)
        self._queue_execution_enabled: bool = is_queue_execution_enabled()
        self._config_assembler = config_assembler if config_assembler is not None else PipelineConfigAssembler()
        self._webui_connection = webui_conn if webui_conn is not None else WebUIConnectionController()
        self._pipeline_runner = pipeline_runner
        if self._queue_execution_controller:
            try:
                self._queue_execution_controller.observe("pipeline_ctrl", self._on_queue_status)
            except Exception:
                pass
        self._job_history_service: JobHistoryService | None = None
        self._active_job_id: str | None = None
        self._last_run_config: dict[str, Any] | None = None
        self._last_run_config: dict[str, Any] | None = None
        queue = self._job_controller.get_queue()
        runner = self._job_controller.get_runner()
        history_store = self._job_controller.get_history_store()
        self._job_service = job_service if job_service is not None else JobService(queue, runner, history_store)
        self._job_controller.set_status_callback("pipeline", self._on_job_status)

    def _get_learning_runner(self):
        if self._learning_runner is None:
            from src.learning.learning_runner import LearningRunner

            self._learning_runner = LearningRunner()
        return self._learning_runner

    def get_learning_runner_for_tests(self):
        """Return the learning runner instance for test inspection."""

        return self._get_learning_runner()

    def handle_learning_record(self, record: LearningRecord) -> None:
        """Handle learning records forwarded from pipeline runner."""

        self._last_learning_record = record
        if self._learning_record_writer and self._learning_enabled:
            try:
                append = getattr(self._learning_record_writer, "append_record", None)
                if callable(append):
                    append(record)
                else:
                    self._learning_record_writer.write(record)
            except Exception:
                pass
        if self._learning_record_callback:
            try:
                self._learning_record_callback(record)
            except Exception:
                pass

    def get_learning_record_handler(self):
        """Return a callback suitable for passing to PipelineRunner."""

        return self.handle_learning_record

    def get_last_learning_record(self) -> LearningRecord | None:
        """Return the most recent LearningRecord handled by the controller."""

        return self._last_learning_record

    def set_learning_enabled(self, enabled: bool) -> None:
        """Enable or disable passive learning record emission."""

        self._learning_enabled = bool(enabled)

    def is_learning_enabled(self) -> bool:
        """Return whether learning record emission is enabled."""

        return self._learning_enabled

    def record_run_result(self, result: PipelineRunResult) -> None:
        """Record the last PipelineRunResult for inspection by higher layers/tests."""

        self._last_run_result = result
        self._last_stage_events = getattr(result, "stage_events", None)

    def get_last_run_result(self) -> PipelineRunResult | None:
        """Return the most recent PipelineRunResult recorded on this controller."""

        return self._last_run_result

    def validate_stage_plan(self, config: dict) -> StageExecutionPlan:
        """Build and store a stage execution plan for testing/inspection."""

        plan = build_stage_execution_plan(config)
        self._last_stage_execution_plan = plan
        return plan

    def get_last_stage_execution_plan_for_tests(self) -> StageExecutionPlan | None:
        """Return the most recent StageExecutionPlan built by this controller."""

        return self._last_stage_execution_plan

    def get_last_run_config_for_tests(self) -> dict[str, Any] | None:
        return self._last_run_config

    def get_last_stage_events_for_tests(self) -> list[dict] | None:
        """Return last emitted stage events."""

        return self._last_stage_events

    # Queue-backed execution -------------------------------------------------
    def start_pipeline(
        self,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
        *,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        run_config: dict[str, Any] | None = None,
    ) -> bool:
        """Submit a pipeline job using assembler-enforced config."""
        if not self.state_manager.can_run():
            return False

        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self.state_manager.transition_to(GUIState.ERROR)
                except Exception:
                    pass
                return False

        if run_config is not None:
            self._last_run_config = run_config
            requested_mode = (run_config.get("run_mode") or "").strip().lower()
            try:
                if requested_mode in {"direct", "queue"}:
                    self.state_manager.pipeline_state.run_mode = requested_mode
            except Exception:
                pass

        try:
            config = self._build_pipeline_config_from_state()
        except Exception as exc:  # noqa: BLE001
            if on_error:
                on_error(exc)
            raise

        def _payload() -> dict[Any, Any]:
            try:
                result: dict[str, Any] = {"config": config}
                run_result = self._run_pipeline_job(config, pipeline_func=pipeline_func)
                if isinstance(run_result, dict):
                    result.update(run_result)
                if on_complete:
                    on_complete(result)
                return result
            except Exception as exc:  # noqa: BLE001
                if on_error:
                    on_error(exc)
                raise

        if self._queue_execution_enabled and self._queue_execution_controller:
            self._active_job_id = self._queue_execution_controller.submit_pipeline_job(_payload)
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass
            return True

        self._active_job_id = self._job_controller.submit_pipeline_run(_payload)
        try:
            self.state_manager.transition_to(GUIState.RUNNING)
        except Exception:
            pass
        return True

    def _run_pipeline_job(
        self,
        config: PipelineConfig,
        *,
        pipeline_func: Callable[[], dict[Any, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a pipeline job using the assembled config or a compatibility callable.

        Priority:
        1. Legacy `run_full_pipeline` hook (if provided).
        2. Explicit `pipeline_func` callable (tests/compat).
        3. Default: use this controller's `run_pipeline` (PipelineRunner-backed).
        """

        # 1) Legacy compatibility hook (used by older harnesses/tests)
        runner = getattr(self, "run_full_pipeline", None)
        if callable(runner):
            maybe_result = runner(config)
            if isinstance(maybe_result, dict):
                return maybe_result

        # 2) Explicit pipeline callable (primarily for tests)
        if pipeline_func:
            maybe_result = pipeline_func()
            if isinstance(maybe_result, dict):
                return maybe_result

        # 3) Default path: run via PipelineRunner through this controller
        try:
            run_result = self.run_pipeline(config)
        except Exception as exc:  # noqa: BLE001
            # Surface error in a structured way so JobQueue/GUI can display it.
            return {"error": str(exc)}

        # Normalize result into a dict payload for JobQueue/history.
        if hasattr(run_result, "to_dict"):
            return {"result": run_result.to_dict()}
        if isinstance(run_result, dict):
            return run_result
        return {"result": run_result}

    def stop_pipeline(self) -> bool:
        """Cancel the active job."""

        if self._active_job_id:
            if self._queue_execution_enabled and self._queue_execution_controller:
                try:
                    self._queue_execution_controller.cancel_job(self._active_job_id)
                except Exception:
                    pass
            else:
                self._job_controller.cancel_job(self._active_job_id)
            self._active_job_id = None
            try:
                self.state_manager.transition_to(GUIState.STOPPING)
            except Exception:
                pass
            return True
        return False

    def _execute_job(self, job: Any) -> dict[Any, Any]:
        if hasattr(job, "payload") and callable(job.payload):
            result = job.payload()
            if isinstance(result, dict):
                return result
            return {}
        return {}

    def _on_job_status(self, job: Any, status: JobStatus) -> None:
        self._handle_status(job.job_id, status)

    def _on_queue_status(self, job: Any, status: JobStatus) -> None:
        self._handle_status(getattr(job, "job_id", None), status)

    def _handle_status(self, job_id: str | None, status: JobStatus) -> None:
        if job_id is None or job_id != self._active_job_id:
            return
        if status == JobStatus.COMPLETED:
            try:
                self.state_manager.transition_to(GUIState.IDLE)
            except Exception:
                pass
            self._active_job_id = None
        elif status == JobStatus.FAILED:
            try:
                self.state_manager.transition_to(GUIState.ERROR)
            except Exception:
                pass
            self._active_job_id = None
        elif status == JobStatus.CANCELLED:
            try:
                self.state_manager.transition_to(GUIState.IDLE)
            except Exception:
                pass
            self._active_job_id = None
        elif status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            try:
                self.state_manager.transition_to(GUIState.RUNNING)
            except Exception:
                pass

    def submit_run_plan(
        self,
        run_plan: RunPlan,
        pipeline_state: PipelineState,
        app_state: Any,
    ) -> None:
        """Submit jobs from a RunPlan to the executor."""
        if not run_plan.jobs:
            self._log("RunPlan has no jobs to submit", "WARNING")
            return

        for planned_job in run_plan.jobs:
            # Build PipelineConfig for this job
            config = self._config_assembler.build_from_gui_input(
                overrides=GuiOverrides(prompt=planned_job.prompt_text),
                lora_settings=planned_job.lora_settings,
                randomizer_metadata=planned_job.randomizer_metadata,
            )

            # Create Job
            from src.queue.job_model import Job, JobPriority
            run_mode = self._normalize_run_mode(pipeline_state)
            job = Job(
                job_id=str(uuid.uuid4()),
                pipeline_config=config,
                priority=JobPriority.NORMAL,
                lora_settings=planned_job.lora_settings,
                randomizer_metadata=planned_job.randomizer_metadata,
                run_mode=run_mode,
            )
            job.payload = lambda job=job: self._run_job(job)

            self._job_service.submit_job_with_run_mode(job)

    def _run_job(self, job: Job) -> dict[str, Any]:
        """Run a single job."""
        if not job.pipeline_config:
            return {"error": "No pipeline config"}
        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
        structured_logger = StructuredLogger()
        runner = PipelineRunner(api_client, structured_logger)
        result = runner.run(job.pipeline_config, self.cancel_token)
        return result.to_dict() if hasattr(result, 'to_dict') else {"result": result}

    def run_pipeline(self, config: PipelineConfig) -> PipelineRunResult:
        """Run pipeline synchronously and return result."""
        if self._pipeline_runner is not None:
            result = self._pipeline_runner.run(config, self.cancel_token)
        else:
            api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
            result = runner.run(config, self.cancel_token)
        self.record_run_result(result)
        return result

    def get_job_history_service(self) -> JobHistoryService | None:
        """Return a JobHistoryService bound to this controller's queue/history."""

        if self._job_history_service is None:
            try:
                queue = self._job_controller.get_queue()
                history = self._job_controller.get_history_store()
                self._job_history_service = JobHistoryService(queue, history, job_controller=self._job_controller)
            except Exception:
                pass
        return self._job_history_service
