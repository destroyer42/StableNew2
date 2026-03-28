"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller.

PipelineController canonical run path:

GUI Run buttons -> AppController._start_run_v2 -> PipelineController.start_pipeline
-> preview NJR build -> JobService submit_job_with_run_mode
-> PipelineController._run_job -> PipelineRunner.run_njr.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Any

from src.controller.core_pipeline_controller import CorePipelineController
from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_lifecycle_logger import JobLifecycleLogger
from src.controller.job_service import JobService
from src.controller.runtime_state import GUIState, PipelineState
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.pipeline.pipeline_runner import PipelineRunner, PipelineRunResult
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.queue.job_model import Job, JobPriority, JobStatus
from src.api.client import SDWebUIClient
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.controller.pipeline_submission_service import PipelinePreviewSubmissionService
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.history.history_record import HistoryRecord
from src.learning.model_defaults_resolver import (
    GuiDefaultsResolver,
    ModelDefaultsContext,
    ModelDefaultsResolver,
)
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import (
    BatchSettings,
    NormalizedJobRecord,
    OutputSettings,
    UnifiedJobSummary,
)

from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.pipeline.run_plan import RunPlan
from src.queue.job_history_store import JobHistoryEntry
from src.utils import LogContext, StructuredLogger, log_with_ctx
from src.utils.config import ConfigManager
from src.utils.error_envelope_v2 import (
    get_attached_envelope,
    serialize_envelope,
    wrap_exception,
)

# Logger for this module
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreviewSummaryDTO:
    job_count: int
    label: str
    positive_preview: str
    negative_preview: str | None
    sampler_name: str | None
    steps: int | None
    cfg_scale: float | None


class PipelineController(CorePipelineController):
    def _build_njrs_from_pack_bundle(
        self, pack_entries: list[PackJobEntry]
    ) -> list[NormalizedJobRecord]:
        """Build NormalizedJobRecord(s) from a bundle of PackJobEntry using the canonical builder pipeline."""
        _logger.info(f"[PipelineController] _build_njrs_from_pack_bundle received {len(pack_entries)} PackJobEntry objects")
        builder = self._get_prompt_pack_builder()
        if builder is None:
            return []
        njrs = builder.build_jobs(pack_entries)
        _logger.info(f"[PipelineController] Builder returned {len(njrs)} NormalizedJobRecord(s)")
        _logger.debug(f"[PipelineController] About to return {len(njrs)} jobs")
        _logger.debug(f"[PipelineController] First job: {njrs[0] if njrs else 'NONE'}")
        return njrs

    def _normalize_run_mode(self, pipeline_state: PipelineState) -> str:
        mode = getattr(pipeline_state, "run_mode", "") or "queue"
        mode_lower = str(mode).lower()
        if mode_lower != "queue":
            try:
                pipeline_state.run_mode = "queue"
            except Exception:
                pass
        return "queue"

    def _build_job(
        self,
        config: Any,
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
                if isinstance(config, Mapping):
                    config_snapshot = {
                        "prompt": config.get("prompt", ""),
                        "model": config.get("model", "") or config.get("model_name", ""),
                        "steps": config.get("steps"),
                        "cfg_scale": config.get("cfg_scale"),
                        "width": config.get("width"),
                        "height": config.get("height"),
                        "sampler": config.get("sampler"),
                    }
                else:
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

    def get_webui_connection_state(self):
        if hasattr(self, "_webui_connection") and self._webui_connection is not None:
            return self._webui_connection.get_state()
        return None

    def _extract_metadata(self, attr_name: str) -> dict[str, Any] | None:
        getter = getattr(self, "gui_get_metadata", None)
        if callable(getter):
            try:
                return getter(attr_name)
            except Exception:
                return None
        return None

    # -------------------------------------------------------------------------
    # V2 Job Building via JobBuilderV2 (PR-204C)
    # -------------------------------------------------------------------------

    def _build_normalized_jobs_from_state(
        self,
        base_config: Any | None = None,
    ) -> list[NormalizedJobRecord]:
        """Build fully-normalized jobs from current GUI/AppState.

        This is the single entrypoint for V2 job construction.
        All run entrypoints should call this helper.

        Args:
            base_config: Optional pre-built base config object.
                If None, builds from current state.

        Returns:
            List of NormalizedJobRecord instances ready for queue/preview.
        """

        # Extract randomization plan from state if available
        randomization_plan = None
        try:
            rand_meta = self._extract_metadata("randomizer_metadata")
            if rand_meta and rand_meta.get("enabled"):
                from src.randomizer import RandomizationPlanV2, RandomizationSeedMode

                seed_mode_str = rand_meta.get("seed_mode", "FIXED")
                try:
                    seed_mode = RandomizationSeedMode[seed_mode_str.upper()]
                except (KeyError, AttributeError):
                    seed_mode = RandomizationSeedMode.FIXED

                randomization_plan = RandomizationPlanV2(
                    enabled=True,
                    model_choices=rand_meta.get("model_choices", []),
                    sampler_choices=rand_meta.get("sampler_choices", []),
                    cfg_scale_values=rand_meta.get("cfg_scale_values", []),
                    steps_values=rand_meta.get("steps_values", []),
                    seed_mode=seed_mode,
                    base_seed=rand_meta.get("base_seed"),
                    max_variants=rand_meta.get("max_variants", 0),
                )
        except Exception as exc:
            _logger.debug("Could not extract randomization plan: %s", exc)

        # Extract batch settings from state
        batch_settings = BatchSettings()
        try:
            overrides = self._extract_state_overrides()
            batch_size = getattr(overrides, "batch_size", 1) or 1
            batch_runs = self._get_batch_runs()
            batch_settings = BatchSettings(batch_size=batch_size, batch_runs=batch_runs)
        except Exception as exc:
            _logger.debug("Could not extract batch settings: %s", exc)

        # Extract output settings from state
        output_settings = OutputSettings()
        try:
            overrides = self._extract_state_overrides()
            output_dir = getattr(overrides, "output_dir", "") or "output"
            filename_pattern = getattr(overrides, "filename_pattern", "") or "{seed}"
            output_settings = OutputSettings(
                base_output_dir=output_dir,
                filename_template=filename_pattern,
            )
        except Exception as exc:
            _logger.debug("Could not extract output settings: %s", exc)

        # PR-CORE-E: Extract config sweep plan from state
        config_variant_plan = None
        try:
            from src.pipeline.config_variant_plan_v2 import ConfigVariant, ConfigVariantPlanV2

            # Check if app state has config sweep enabled
            app_state = self._app_state
            if app_state:
                sweep_enabled = getattr(app_state, "config_sweep_enabled", False)
                sweep_variants = getattr(app_state, "config_sweep_variants", [])

                if sweep_enabled and sweep_variants:
                    # Build ConfigVariant objects from state
                    variants = []
                    for idx, var_dict in enumerate(sweep_variants):
                        variant = ConfigVariant(
                            label=var_dict.get("label", f"variant_{idx}"),
                            overrides=var_dict.get("overrides", {}),
                            index=idx,
                        )
                        variants.append(variant)

                    config_variant_plan = ConfigVariantPlanV2(
                        variants=variants,
                        enabled=True,
                    )
        except Exception as exc:
            _logger.debug("Could not extract config variant plan: %s", exc)

        # Build jobs via JobBuilderV2
        if base_config is None:
            assembler = getattr(self, "_config_assembler", None)
            build_from_gui_input = getattr(assembler, "build_from_gui_input", None)
            if callable(build_from_gui_input):
                try:
                    base_config = build_from_gui_input()
                except Exception as exc:
                    _logger.warning("Config assembler failed to build base config: %s", exc)
                    base_config = None
        try:
            jobs = self._job_builder.build_jobs(
                base_config=base_config,
                randomization_plan=randomization_plan,
                batch_settings=batch_settings,
                output_settings=output_settings,
                config_variant_plan=config_variant_plan,  # PR-CORE-E
            )
        except Exception as exc:
            _logger.warning("JobBuilderV2 failed to build jobs: %s", exc)
            return []

        if not jobs:
            _logger.warning("JobBuilderV2 returned no jobs for current state")

        return jobs

    def _get_prompt_pack_builder(self) -> PromptPackNormalizedJobBuilder | None:
        if not self._config_manager or not getattr(self, "_job_builder", None):
            return None
        builder = getattr(self, "_prompt_pack_builder", None)
        if builder is not None:
            return builder
        packs_dir = getattr(self._config_manager, "packs_dir", "packs")
        builder = PromptPackNormalizedJobBuilder(
            config_manager=self._config_manager,
            job_builder=self._job_builder,
            packs_dir=packs_dir,
        )
        self._prompt_pack_builder = builder
        return builder

    def get_preview_jobs(self) -> list[NormalizedJobRecord]:
        """Return normalized jobs derived from the current GUI state for preview panels."""
        try:
            job_draft = getattr(self._app_state, "job_draft", None)
            pack_entries = getattr(job_draft, "packs", None) or []
            if pack_entries:
                njrs = self._build_njrs_from_pack_bundle(pack_entries)
                if njrs:
                    _logger.debug(
                        "Built %d preview jobs from %d prompt pack entries",
                        len(njrs),
                        len(pack_entries),
                    )
                    return njrs
                _logger.debug(
                    "Prompt pack preview builder returned no jobs, falling back to empty list"
                )
            return self._build_normalized_jobs_from_state()
        except Exception as exc:
            _logger.exception("Failed to build preview jobs - EXCEPTION DETAILS:")
            return []

    def _to_queue_job(
        self,
        record: NormalizedJobRecord,
        *,
        run_mode: str = "queue",
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        run_config: dict[str, Any] | None = None,
    ) -> Job:
        """Convert a NormalizedJobRecord into the Job model used by JobService.

        This adapter preserves all metadata from the normalized record
        while producing a Job compatible with the existing queue system.

        PR-CORE1-B3: NJR-backed jobs MUST NOT carry pipeline_config. The field may
        exist for legacy records, but new v2.6 jobs rely solely on NJR snapshots.
        """
        return self._get_preview_submission_service().to_queue_job(
            record,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            last_run_config=run_config or self._last_run_config,
        )

    def start_pipeline_v2(
        self,
        *,
        run_mode: str | None = None,
        source: str = "gui",
        prompt_source: str = "manual",
        prompt_pack_id: str | None = None,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Start pipeline using preview-built NJRs and JobService submission."""
        if not self.gui_can_run():
            return False
        self._sync_auto_run_setting()

        # Check WebUI connection
        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self._safe_gui_transition(GUIState.ERROR)
                except Exception:
                    pass
                return False

        # Fresh runtime execution is queue-only.
        if run_mode is None:
            try:
                pipeline_state = self._get_pipeline_state()
                if pipeline_state:
                    run_mode = self._normalize_run_mode(pipeline_state)
                else:
                    run_mode = "queue"
            except Exception:
                run_mode = "queue"
        else:
            run_mode = "queue"

        return self._submit_preview_jobs_for_run(
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            on_complete=on_complete,
            on_error=on_error,
        )

    def _submit_preview_jobs_for_run(
        self,
        *,
        run_mode: str,
        source: str,
        prompt_source: str,
        prompt_pack_id: str | None,
        on_complete: Callable[[dict[Any, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        try:
            normalized_jobs = self.get_preview_jobs()
        except Exception as exc:
            _logger.error("Failed to build preview jobs: %s", exc)
            if on_error:
                on_error(exc)
            return False

        effective_prompt_pack_id = prompt_pack_id
        if not effective_prompt_pack_id:
            last_run_config = getattr(self, "_last_run_config", None) or {}
            effective_prompt_pack_id = last_run_config.get("prompt_pack_id")

        if not normalized_jobs:
            _logger.warning("No preview jobs available to submit")
            return False

        submission = self._get_preview_submission_service().submit_preview_jobs(
            normalized_jobs,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=effective_prompt_pack_id,
            last_run_config=getattr(self, "_last_run_config", None),
            on_error=on_error,
        )
        if submission is None:
            return False

        self._safe_gui_transition(GUIState.RUNNING)
        _logger.info(
            "Submitted %d preview job(s) via canonical controller path",
            submission.submitted_jobs,
        )
        if on_complete:
            on_complete(
                {
                    "submitted_jobs": submission.submitted_jobs,
                    "run_mode": submission.run_mode,
                }
            )
        return True

    def _get_preview_submission_service(self) -> PipelinePreviewSubmissionService:
        return PipelinePreviewSubmissionService(
            job_service=self._job_service,
            run_job_callback=self._run_job,
            learning_enabled=self._learning_enabled,
        )

    def _get_history_handoff_service(self) -> HistoryHandoffService:
        return HistoryHandoffService()

    def build_pipeline_config_with_profiles(
        self,
        base_model_name: str,
        lora_names: list[str],
        user_overrides: dict[str, any],
    ) -> dict:
        """Build pipeline config using ModelProfile and LoraProfile priors."""
        from pathlib import Path

        from src.learning.model_profiles import (
            find_lora_profile_for_name,
            find_model_profile_for_checkpoint,
            suggest_preset_for,
        )

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
            config["txt2img"].update(
                {
                    "sampler_name": suggested.sampler,
                    "scheduler": suggested.scheduler,
                    "steps": suggested.steps,
                    "cfg_scale": suggested.cfg,
                    "width": suggested.resolution[0],
                    "height": suggested.resolution[1],
                }
            )
            # Apply LoRA weights
            config["txt2img"]["loras"] = [
                {"name": name, "weight": suggested.lora_weights.get(name, 0.6)}
                for name in lora_names
            ]
            import logging

            logging.info(
                f"Using model profile preset {suggested.preset_id} (source={suggested.source}) for {base_model_name} + {lora_names}."
            )
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

    def __init__(
        self,
        *,
        app_state: AppStateV2 | None = None,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        config_assembler: Any | None = None,
        job_builder: JobBuilderV2 | None = None,
        job_lifecycle_logger: JobLifecycleLogger | None = None,
        config_manager: ConfigManager | None = None,
        gui_defaults_resolver: GuiDefaultsResolver | None = None,
        **kwargs,
    ):
        # Pop parameters that are not for the parent class
        kwargs.pop("api_client", None)
        job_service = kwargs.pop("job_service", None)
        kwargs.pop("structured_logger", None)
        pipeline_runner = kwargs.pop("pipeline_runner", None)

        webui_conn = kwargs.pop("webui_connection_controller", None)
        super().__init__(**kwargs)
        self._learning_runner = None
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_learning_record: LearningRecord | None = None
        self._last_run_result: PipelineRunResult | None = None
        self._last_stage_execution_plan: StageExecutionPlan | None = None
        self._last_stage_events: list[dict[Any, Any]] | None = None
        self._learning_enabled: bool = False
        self._learning_queue_cap: int = 3
        injected_queue = getattr(job_service, "queue", None) if job_service is not None else None
        injected_runner = getattr(job_service, "runner", None) if job_service is not None else None
        injected_history_store = (
            getattr(job_service, "history_store", None) if job_service is not None else None
        )
        self._job_controller = JobExecutionController(
            execute_job=self._execute_job,
            history_store=injected_history_store,
            replay_runner=self,
            queue=injected_queue,
            runner=injected_runner,
            restore_state=job_service is None,
        )
        self._queue_execution_enabled: bool = is_queue_execution_enabled()
        self._config_manager = config_manager or ConfigManager()
        self._gui_defaults_resolver = (
            gui_defaults_resolver
            if gui_defaults_resolver is not None
            else GuiDefaultsResolver(config_manager=self._config_manager)
        )
        self._model_defaults_resolver = ModelDefaultsResolver(config_manager=self._config_manager)
        self._config_assembler = config_assembler
        self._job_builder = job_builder if job_builder is not None else JobBuilderV2()
        self._webui_connection = (
            webui_conn if webui_conn is not None else WebUIConnectionController()
        )
        self._pipeline_runner = pipeline_runner
        try:
            self._job_controller.set_status_callback("pipeline_ctrl", self._on_queue_status)
        except Exception:
            pass
        self._job_history_service: JobHistoryService | None = None
        self._active_job_id: str | None = None
        self._last_run_config: dict[str, Any] | None = None
        self._app_state: AppStateV2 | None = app_state
        self._app_state_queue_updates_managed_externally = bool(
            getattr(self, "_app_controller", None)
        )
        self._job_lifecycle_logger = job_lifecycle_logger

        queue = self._job_controller.get_queue()
        runner = self._job_controller.get_runner()
        history_store = self._job_controller.get_history_store()
        history_service = self.get_job_history_service()
        self._job_service = (
            job_service
            if job_service is not None
            else JobService(queue, runner, history_store, history_service=history_service)
        )
        if self._job_lifecycle_logger and hasattr(self._job_service, "set_job_lifecycle_logger"):
            try:
                self._job_service.set_job_lifecycle_logger(self._job_lifecycle_logger)
            except Exception:
                pass
        if hasattr(self._job_service, "set_status_callback"):
            try:
                self._job_service.set_status_callback("pipeline", self._on_job_status)
            except Exception:
                pass
        self._sync_auto_run_setting()
        self._setup_queue_callbacks()

    def _sync_auto_run_setting(self, forced_value: bool | None = None) -> None:
        """Propagate auto-run preference from AppState into JobService."""
        if not self._job_service:
            return
        if forced_value is None:
            if self._app_state is not None:
                enabled = bool(getattr(self._app_state, "auto_run_queue", False))
            else:
                enabled = bool(
                    getattr(
                        self._job_controller,
                        "auto_run_enabled",
                        getattr(self._job_service, "auto_run_enabled", False),
                    )
                )
        else:
            enabled = bool(forced_value)
        self._job_service.auto_run_enabled = enabled

    def _get_pipeline_state(self) -> PipelineState | None:
        getter = getattr(self, "gui_get_pipeline_state", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return None

    def _get_batch_runs(self) -> int:
        pipeline_state = self._get_pipeline_state()
        count = getattr(pipeline_state, "batch_runs", 1) or 1
        return max(1, count)

    def _safe_gui_transition(self, new_state: GUIState) -> None:
        transition = getattr(self, "gui_transition_state", None)
        if callable(transition):
            try:
                transition(new_state)
            except Exception:
                pass

    def _set_pipeline_run_mode(self, mode: str) -> None:
        setter = getattr(self, "gui_set_pipeline_run_mode", None)
        if callable(setter):
            try:
                setter(mode)
            except Exception:
                pass

    def _get_prompt_workspace_state(self) -> PromptWorkspaceState | None:
        if self._app_state is not None:
            prompt_state = getattr(self._app_state, "prompt_workspace_state", None)
            if prompt_state is not None:
                return prompt_state
        getter = getattr(self, "gui_get_prompt_workspace_state", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return None

    def _get_learning_runner(self):
        if self._learning_runner is None:
            from src.learning.learning_runner import LearningRunner

            self._learning_runner = LearningRunner()
        return self._learning_runner

    def get_gui_model_defaults(
        self, model_name: str | None, preset_name: str | None = None
    ) -> dict[str, Any]:
        """Return GUI-ready defaults for the specified model/preset."""
        if not self._gui_defaults_resolver:
            return {}
        defaults = self._gui_defaults_resolver.resolve_for_gui(
            model_name=model_name, preset_name=preset_name
        )
        _logger.debug(
            "GUI defaults resolved for model=%s preset=%s keys=%s",
            model_name,
            preset_name,
            sorted(defaults.keys()),
        )
        return defaults

    def build_merged_config_for_run(
        self,
        model_name: str | None,
        preset_name: str | None = None,
        runtime_overrides: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a model/preset-aware config dict for job construction."""
        context = ModelDefaultsContext(model_name=model_name, preset_name=preset_name)
        merged = self._model_defaults_resolver.resolve_config(
            context,
            runtime_overrides=runtime_overrides,
        )
        _logger.debug(
            "Merged run config: model=%s preset=%s runtime_keys=%s",
            model_name,
            preset_name,
            sorted((runtime_overrides or {}).keys()),
        )
        return merged

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

    def set_learning_queue_cap(self, cap: int) -> None:
        """Set max queue depth allowed for learning automation submissions."""
        try:
            value = int(cap)
        except Exception:
            value = 1
        self._learning_queue_cap = max(1, value)

    def get_learning_queue_cap(self) -> int:
        return max(1, int(getattr(self, "_learning_queue_cap", 1)))

    def get_queue_depth(self) -> int:
        """Best-effort queue depth used by learning automation guardrails."""
        queue = None
        if self._job_service is not None:
            queue = getattr(self._job_service, "queue", None)
        if queue is not None:
            qsize = getattr(queue, "qsize", None)
            if callable(qsize):
                try:
                    return int(qsize())
                except Exception:
                    pass
            size = getattr(queue, "size", None)
            if callable(size):
                try:
                    return int(size())
                except Exception:
                    pass
            try:
                return len(queue)
            except Exception:
                pass

        if self._job_service is not None:
            getter = getattr(self._job_service, "get_diagnostics_snapshot", None)
            if callable(getter):
                try:
                    snapshot = getter() or {}
                    queue_snapshot = snapshot.get("queue") or {}
                    if isinstance(queue_snapshot, dict):
                        if "count" in queue_snapshot:
                            return int(queue_snapshot.get("count", 0))
                        jobs = queue_snapshot.get("jobs")
                        if isinstance(jobs, list):
                            return len(jobs)
                except Exception:
                    pass
        return 0

    def can_enqueue_learning_jobs(self, requested_jobs: int) -> tuple[bool, str]:
        """Check learning-automation queue cap before enqueuing more jobs."""
        requested = max(1, int(requested_jobs or 1))
        depth = self.get_queue_depth()
        cap = self.get_learning_queue_cap()
        if (depth + requested) > cap:
            return False, f"queue cap exceeded: depth={depth}, requested={requested}, cap={cap}"
        return True, ""

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
        *,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        run_config: dict[str, Any] | None = None,
    ) -> bool:
        """Submit preview-built NJRs using the canonical controller path."""
        if not self.gui_can_run():
            return False
        self._sync_auto_run_setting()

        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self._safe_gui_transition(GUIState.ERROR)
                except Exception:
                    pass
                return False

        if run_config is not None:
            self._last_run_config = run_config
            requested_mode = (run_config.get("run_mode") or "").strip().lower()
            try:
                self._set_pipeline_run_mode("queue")
            except Exception:
                pass
        run_mode = "queue"
        pipeline_state = self._get_pipeline_state()
        if pipeline_state is not None:
            try:
                run_mode = self._normalize_run_mode(pipeline_state)
            except Exception:
                run_mode = "queue"
        if run_config is not None:
            run_mode = "queue"

        prompt_source = "manual"
        prompt_pack_id = None
        if run_config is not None:
            prompt_source = str(run_config.get("prompt_source") or prompt_source)
            prompt_pack_id = run_config.get("prompt_pack_id")

        return self._submit_preview_jobs_for_run(
            run_mode=run_mode,
            source="gui",
            prompt_source=prompt_source,
            prompt_pack_id=prompt_pack_id,
            on_complete=on_complete,
            on_error=on_error,
        )

    def stop_pipeline(self) -> bool:
        """Cancel the active job."""

        if not self._active_job_id:
            return False
        try:
            self._job_controller.cancel_job(self._active_job_id)
        except Exception:
            pass
        self._active_job_id = None
        self._safe_gui_transition(GUIState.STOPPING)
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
            self._safe_gui_transition(GUIState.IDLE)
            self._active_job_id = None
        elif status == JobStatus.FAILED:
            self._safe_gui_transition(GUIState.ERROR)
            self._active_job_id = None
        elif status == JobStatus.CANCELLED:
            self._safe_gui_transition(GUIState.IDLE)
            self._active_job_id = None
        elif status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            self._safe_gui_transition(GUIState.RUNNING)

    def bind_app_state(self, app_state: Any | None) -> None:
        """Bind an AppStateV2 instance for updating GUI data."""
        self._app_state = app_state
        self._refresh_app_state_queue()
        try:
            preview_jobs = self.get_preview_jobs()
            if hasattr(app_state, "set_preview_jobs"):
                app_state.set_preview_jobs(preview_jobs)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Queue wiring for AppState integration
    # ------------------------------------------------------------------

    def _setup_queue_callbacks(self) -> None:
        if not self._job_service:
            return
        self._job_service.register_callback(JobService.EVENT_QUEUE_UPDATED, self._on_queue_updated)
        self._job_service.register_callback(
            JobService.EVENT_QUEUE_STATUS, self._on_queue_status_changed
        )
        self._job_service.register_callback(JobService.EVENT_JOB_STARTED, self._on_job_started)
        self._job_service.register_callback(JobService.EVENT_JOB_FINISHED, self._on_job_finished)
        self._job_service.register_callback(JobService.EVENT_JOB_FAILED, self._on_job_failed)
        self._job_service.register_callback(JobService.EVENT_QUEUE_EMPTY, self._on_queue_empty)
        self._setup_history_callbacks()

    def _on_queue_updated(self, summaries: list[str]) -> None:
        if not self._app_state:
            return
        if self._app_state_queue_updates_managed_externally:
            _logger.debug(
                "_on_queue_updated: external app-state owner present, skipping duplicate refresh"
            )
            return
        _logger.debug(f"_on_queue_updated: Received {len(summaries)} summaries, refreshing app_state")
        self._refresh_app_state_queue()

    def _on_queue_status_changed(self, status: str) -> None:
        if not self._app_state:
            return
        self._app_state.set_queue_status(status)

    def _on_job_started(self, job: Job) -> None:
        self._set_running_job(job)

    def _on_job_finished(self, job: Job) -> None:
        self._set_running_job(None)

    def _on_job_failed(self, job: Job) -> None:
        self._set_running_job(None)

    def _on_queue_empty(self) -> None:
        if self._app_state:
            self._app_state.set_queue_status("idle")

    def _setup_history_callbacks(self) -> None:
        history_service = self.get_job_history_service()
        if history_service is None:
            return
        history_service.register_callback(self._on_history_entry_updated)

    def _on_history_entry_updated(self, entry: JobHistoryEntry) -> None:
        status = getattr(entry, "status", None)
        status_value = status.value if hasattr(status, "value") else str(status or "")
        if status_value.lower() not in {"completed", "failed"}:
            return
        self._refresh_app_state_history()

    def _refresh_app_state_queue(self) -> None:
        if not self._app_state or not self._job_service:
            return
        jobs = self._list_service_jobs()
        # Convert Job objects to UnifiedJobSummary via their NJRs
        queue_jobs = []
        summaries = []
        for job in jobs:
            njr = getattr(job, "_normalized_record", None)
            if njr:
                try:
                    summary = UnifiedJobSummary.from_normalized_record(njr)
                    status_value = getattr(job, "status", None)
                    status_text = (
                        status_value.value if hasattr(status_value, "value") else str(status_value or "")
                    ).strip()
                    if status_text:
                        summary = replace(summary, status=status_text.upper())
                    queue_jobs.append(summary)
                    summaries.append(summary.positive_prompt_preview or job.job_id)
                except Exception as exc:
                    _logger.warning(f"Failed to convert job {job.job_id} to UnifiedJobSummary: {exc}")
                    summaries.append(job.job_id)
            else:
                _logger.debug(f"Job {job.job_id} missing NJR, cannot display in GUI")
                summaries.append(job.job_id)
        
        _logger.debug(f"_refresh_app_state_queue: Setting {len(queue_jobs)} jobs")
        self._app_state.set_queue_items(summaries)
        setter = getattr(self._app_state, "set_queue_jobs", None)
        if callable(setter):
            try:
                setter(queue_jobs)
                _logger.debug(f"_refresh_app_state_queue: set_queue_jobs called successfully")
            except Exception as exc:
                _logger.error(f"_refresh_app_state_queue: set_queue_jobs failed: {exc}", exc_info=True)

    def _refresh_app_state_history(self) -> None:
        if not self._app_state or not self._job_service:
            return
        store = getattr(self._job_service, "history_store", None)
        entries: list[JobHistoryEntry] = []
        if store and hasattr(store, "list_jobs"):
            try:
                entries = store.list_jobs(limit=20)
            except Exception:
                entries = []
        setter = getattr(self._app_state, "set_history_items", None)
        if callable(setter):
            setter(entries)

    def _list_service_jobs(self) -> list[Job]:
        queue = getattr(self._job_service, "queue", None)
        if queue and hasattr(queue, "list_active_jobs_ordered"):
            try:
                return list(queue.list_active_jobs_ordered())
            except Exception:
                return []
        if queue and hasattr(queue, "list_jobs"):
            try:
                return list(queue.list_jobs())
            except Exception:
                return []
        return []

    def _set_running_job(self, job: Job | None) -> None:
        if not self._app_state:
            return
        if job is None:
            self._app_state.set_running_job(None)
            if hasattr(self._app_state, "set_runtime_status"):
                self._app_state.set_runtime_status(None)
            return
        # Convert Job to UnifiedJobSummary via NJR
        njr = getattr(job, "_normalized_record", None)
        if njr:
            try:
                summary = UnifiedJobSummary.from_normalized_record(njr)
                status_value = getattr(job, "status", None)
                status_text = (
                    status_value.value if hasattr(status_value, "value") else str(status_value or "")
                ).strip()
                if status_text:
                    summary = replace(summary, status=status_text.upper())
                self._app_state.set_running_job(summary)
            except Exception as exc:
                _logger.warning(f"Failed to convert running job {job.job_id} to UnifiedJobSummary: {exc}")
        else:
            _logger.warning(f"Running job {job.job_id} missing NJR, cannot display in GUI")

    def _get_draft_part_count(self) -> int:
        if not self._app_state:
            return 0
        summary = getattr(self._app_state.job_draft, "summary", None)
        if summary is None:
            return 0
        return getattr(summary, "part_count", 0) or 0

    def _log_add_to_queue_event(self, job_id: str | None) -> None:
        logger = getattr(self, "_job_lifecycle_logger", None)
        if not logger:
            return
        logger.log_add_to_queue(
            source="pipeline_tab",
            job_id=job_id,
            draft_size=self._get_draft_part_count(),
        )

    # ------------------------------------------------------------------
    # GUI callbacks for preview + job controls
    # ------------------------------------------------------------------

    def on_add_job_to_queue_v2(self) -> None:
        records = self.get_preview_jobs()
        if not records:
            return
        if self._app_state and hasattr(self._app_state, "set_preview_jobs"):
            try:
                self._app_state.set_preview_jobs(records)
            except Exception:
                pass
        self.submit_preview_jobs_to_queue(records=records)

    def on_clear_job_draft(self) -> None:
        if not self._app_state:
            return
        clear_fn = getattr(self._app_state, "clear_job_draft", None)
        if callable(clear_fn):
            try:
                clear_fn()
            except Exception:
                pass
        preview_setter = getattr(self._app_state, "set_preview_jobs", None)
        if callable(preview_setter):
            try:
                preview_setter([])
            except Exception:
                pass

    def on_queue_move_up_v2(self, job_id: str) -> bool:
        queue = getattr(self._job_service, "queue", None)
        if queue and hasattr(queue, "move_up"):
            try:
                return bool(queue.move_up(job_id))
            except Exception:
                _logger.exception("on_queue_move_up_v2 failed", exc_info=True)
        return False

    def on_queue_move_down_v2(self, job_id: str) -> bool:
        queue = getattr(self._job_service, "queue", None)
        if queue and hasattr(queue, "move_down"):
            try:
                return bool(queue.move_down(job_id))
            except Exception:
                _logger.exception("on_queue_move_down_v2 failed", exc_info=True)
        return False

    def on_queue_remove_job_v2(self, job_id: str) -> bool:
        queue = getattr(self._job_service, "job_queue", None)
        if queue and hasattr(queue, "remove"):
            try:
                removed = queue.remove(job_id)
                if removed is not None and self._app_state:
                    self._refresh_app_state_queue()
                return removed is not None
            except Exception:
                _logger.exception("on_queue_remove_job_v2 failed", exc_info=True)
        return False

    def on_queue_clear_v2(self) -> None:
        queue = getattr(self._job_service, "job_queue", None)
        if queue and hasattr(queue, "clear"):
            try:
                queue.clear()
            except Exception:
                _logger.exception("on_queue_clear_v2 failed", exc_info=True)

    def on_set_auto_run_v2(self, enabled: bool) -> None:
        if self._app_state:
            self._app_state.set_auto_run_queue(bool(enabled))
        if self._job_controller and hasattr(self._job_controller, "set_auto_run_enabled"):
            try:
                self._job_controller.set_auto_run_enabled(bool(enabled))
            except Exception:
                _logger.exception("Failed to sync auto-run to JobExecutionController", exc_info=True)
        self._sync_auto_run_setting(bool(enabled))
        if not enabled or not self._job_service:
            return
        if self._app_state and bool(getattr(self._app_state, "is_queue_paused", False)):
            return
        queue = getattr(self._job_service, "queue", None) or getattr(self._job_service, "job_queue", None)
        if not queue or not hasattr(queue, "list_jobs"):
            return
        try:
            has_queued = any(job.status == JobStatus.QUEUED for job in queue.list_jobs())
        except Exception:
            has_queued = False
        if has_queued:
            self._job_service.resume()

    def on_pause_queue_v2(self) -> None:
        if not self._job_service:
            return
        self._job_service.pause()
        if self._job_controller and hasattr(self._job_controller, "set_queue_paused"):
            try:
                self._job_controller.set_queue_paused(True)
            except Exception:
                _logger.exception("Failed to sync pause state to JobExecutionController", exc_info=True)
        if self._app_state:
            self._app_state.set_is_queue_paused(True)

    def on_resume_queue_v2(self) -> None:
        if not self._job_service:
            return
        self._job_service.resume()
        if self._job_controller and hasattr(self._job_controller, "set_queue_paused"):
            try:
                self._job_controller.set_queue_paused(False)
            except Exception:
                _logger.exception("Failed to sync pause state to JobExecutionController", exc_info=True)
        if self._app_state:
            self._app_state.set_is_queue_paused(False)

    def on_queue_send_job_v2(self) -> None:
        if not self._job_service:
            return
        self._job_service.run_next_now()

    def on_pause_job_v2(self) -> None:
        self.on_pause_queue_v2()

    def on_resume_job_v2(self) -> None:
        self.on_resume_queue_v2()

    def on_cancel_job_v2(self) -> None:
        if not self._job_service:
            return
        self._job_service.cancel_current()

    def on_cancel_job_and_return_v2(self) -> None:
        if not self._job_service:
            return
        self._job_service.cancel_current(return_to_queue=True)

    def _refresh_preview_jobs_from_state(self) -> None:
        """Refresh preview jobs so GUI panels display the latest normalized records."""
        if not self._app_state:
            return
        records = self.get_preview_jobs()
        setter = getattr(self._app_state, "set_preview_jobs", None)
        if callable(setter):
            setter(records or [])

    def refresh_preview_from_state(self) -> None:
        """Public helper used by the GUI bridge to rebuild preview job records."""
        self._refresh_preview_jobs_from_state()

    def build_preview_summary(self) -> PreviewSummaryDTO | None:
        """Return a simple preview summary based on the first normalized job record."""
        records = self.get_preview_jobs()
        if not records:
            return None
        first = records[0]
        ui_summary = first.to_ui_summary() if hasattr(first, "to_ui_summary") else None
        label = getattr(ui_summary, "label", getattr(first, "job_id", ""))
        positive = getattr(ui_summary, "positive_preview", "")
        negative = getattr(ui_summary, "negative_preview", None)
        sampler = getattr(ui_summary, "sampler_name", None)
        steps = getattr(ui_summary, "steps", None)
        cfg_scale = getattr(ui_summary, "cfg_scale", None)
        return PreviewSummaryDTO(
            job_count=len(records),
            label=label,
            positive_preview=positive,
            negative_preview=negative,
            sampler_name=sampler,
            steps=steps,
            cfg_scale=cfg_scale,
        )

    def enqueue_draft_jobs(self, *, run_config: dict[str, Any] | None = None) -> int:
        """Enqueue all preview jobs derived from the current AppState job draft."""
        preview_records = list(getattr(self._app_state, "preview_jobs", None) or [])
        count = self.submit_preview_jobs_to_queue(records=preview_records or None, run_config=run_config)
        if count and self._app_state:
            self._app_state.clear_job_draft()
            setter = getattr(self._app_state, "set_preview_jobs", None)
            if callable(setter):
                setter([])
            else:
                self.refresh_preview_from_state()
        return count

    def add_packs_to_draft(self, entries: list[PackJobEntry]) -> None:
        if not self._app_state:
            return
        if not entries:
            return
        self._app_state.add_packs_to_job_draft(entries)
        self.refresh_preview_from_state()

    def remove_pack_from_draft(self, pack_id: str) -> None:
        if not self._app_state:
            return
        filtered = [entry for entry in self._app_state.job_draft.packs if entry.pack_id != pack_id]
        if len(filtered) == len(self._app_state.job_draft.packs):
            return
        self._app_state.job_draft.packs = filtered
        self.refresh_preview_from_state()

    def clear_draft(self) -> None:
        if not self._app_state:
            return
        self._app_state.clear_job_draft()
        self.refresh_preview_from_state()

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
            # Create Job
            from src.queue.job_model import Job, JobPriority

            run_mode = self._normalize_run_mode(pipeline_state)
            job = Job(
                job_id=str(uuid.uuid4()),
                priority=JobPriority.NORMAL,
                lora_settings=planned_job.lora_settings,
                randomizer_metadata=planned_job.randomizer_metadata,
                run_mode=run_mode,
            )
            job.payload = lambda job=job: self._run_job(job)

            self._job_service.submit_job_with_run_mode(job)

    def _run_job(self, job: Job) -> dict[str, Any]:
        """Run a single job using NJR-only execution (PR-CORE1-B1/C2).

        Accepts a Job that must have _normalized_record (preferred) for PipelineRunner.run_njr().
        Legacy pipeline_config execution is retired in CORE1-C2.

        Returns dict with job result metadata or error information.

        If the record is missing, returns an error dict instead of raising.
        """
        record = getattr(job, "_normalized_record", None)
        if record is not None:
            try:
                result = self.run_njr(record)
                return result.to_dict() if hasattr(result, "to_dict") else {"result": result}
            except Exception as exc:  # noqa: BLE001
                envelope = get_attached_envelope(exc)
                if envelope is None:
                    envelope = wrap_exception(
                        exc,
                        subsystem="pipeline_controller",
                    )
                return {
                    "error": str(exc),
                    "error_envelope": serialize_envelope(envelope),
                }
        error_msg = "Job missing _normalized_record; NJR-only execution requires NormalizedJobRecord snapshots."
        return {"error": error_msg, "job_id": job.job_id}

    def _get_runtime_status_callback(self) -> Callable[[dict[str, Any]], None] | None:
        app_controller = getattr(self, "app_controller", None)
        if app_controller and hasattr(app_controller, "_get_runtime_status_callback"):
            return app_controller._get_runtime_status_callback()
        return None

    def _create_runtime_pipeline_runner(self) -> PipelineRunner:
        if self._pipeline_runner is not None:
            return self._pipeline_runner
        return PipelineRunner(
            SDWebUIClient(base_url="http://127.0.0.1:7860"),
            StructuredLogger(),
            status_callback=self._get_runtime_status_callback(),
        )

    def run_njr(
        self,
        record: NormalizedJobRecord,
        cancel_token: Any | None = None,
        run_plan: Any | None = None,
        log_fn: Callable[[str], None] | None = None,
        checkpoint_callback: Callable[[str, list[str], dict[str, Any] | None], None] | None = None,
    ) -> PipelineRunResult:
        """Execute an NJR through the controller-owned canonical runner path."""
        runner = self._create_runtime_pipeline_runner()
        result = runner.run_njr(
            record,
            cancel_token=cancel_token if cancel_token is not None else self.cancel_token,
            run_plan=run_plan,
            log_fn=log_fn,
            checkpoint_callback=checkpoint_callback,
        )
        self.record_run_result(result)
        return result

    def _infer_job_stage(self, job: Job) -> str | None:
        record = getattr(job, "_normalized_record", None)
        if record and record.stage_chain:
            first_stage = record.stage_chain[0]
            stage_name = getattr(first_stage, "stage_type", None) or getattr(
                first_stage, "stage_name", None
            )
            if stage_name:
                return str(stage_name).lower()
        snapshot = getattr(job, "snapshot", None) or {}
        stage = snapshot.get("stage") or snapshot.get("stage_name")
        if stage:
            return str(stage).lower()
        config_snapshot = getattr(job, "config_snapshot", None) or {}
        stage = config_snapshot.get("stage") or config_snapshot.get("stage_name")
        if stage:
            return str(stage).lower()
        return None

    def submit_preview_jobs_to_queue(
        self,
        *,
        records: list[NormalizedJobRecord] | None = None,
        source: str = "gui",
        prompt_source: str = "pack",
        run_config: dict[str, Any] | None = None,
    ) -> int:
        """Submit preview jobs as queue jobs using NormalizedJobRecord data.
        
        Args:
            records: Optional pre-fetched records to submit. If None, calls get_preview_jobs().
            source: Source identifier for job tracking.
            prompt_source: Prompt source type ("pack", "manual", etc).
            run_config: Optional runtime configuration overrides.
            
        Returns:
            Number of jobs successfully submitted to queue.
        """
        normalized_jobs = records if records is not None else self.get_preview_jobs()
        if not normalized_jobs:
            return 0
        queueable, non_queueable = self._split_queueable_records(normalized_jobs)

        if run_config is not None:
            self._last_run_config = run_config

        if not queueable:
            message = (
                "No queueable jobs were found for the current preview. "
                "Select at least one prompt pack before adding jobs to the queue."
            )
            log_with_ctx(
                _logger,
                logging.WARNING,
                "submit_preview_jobs_to_queue: rejecting enqueue of non-queueable jobs",
                ctx=LogContext(subsystem="pipeline_controller"),
                extra_fields={
                    "total_records": len(normalized_jobs),
                    "non_queueable": len(non_queueable),
                },
            )
            raise ValueError(message)

        submitted = self._submit_normalized_jobs(
            queueable,
            run_config=run_config,
            source=source,
            prompt_source=prompt_source,
        )
        return submitted

    def _split_queueable_records(
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

    def _ensure_record_prompt_pack_metadata(
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

    def _sort_jobs_by_model(self, records: list[NormalizedJobRecord]) -> list[NormalizedJobRecord]:
        """Sort jobs by model+VAE to minimize expensive WebUI state switches."""

        def _extract_model_vae_key(record: NormalizedJobRecord) -> tuple[str, str]:
            config = record.config or {}
            if not isinstance(config, dict):
                return ("", "")

            # Model: try top-level, then txt2img section.
            model = config.get("model_name") or config.get("model") or ""
            if not model:
                txt2img = config.get("txt2img", {})
                if isinstance(txt2img, dict):
                    model = txt2img.get("model_name") or txt2img.get("model") or ""

            # VAE: treat empty/automatic/none as default to preserve grouping semantics.
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

        # Keep unspecified models at the end, then sort by model and VAE.
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
            _logger.info(
                "[PipelineController] Job grouping by model+vae: %s",
                ", ".join(f"{group}: {count}" for group, count in model_groups.items()),
            )

        return sorted_records

    def _submit_normalized_jobs(
        self,
        records: list[NormalizedJobRecord],
        *,
        run_config: dict[str, Any] | None = None,
        source: str = "gui",
        prompt_source: str = "pack",
    ) -> int:
        if not records or not self._job_service:
            return 0
        if str(source).startswith("learning_"):
            allowed, reason = self.can_enqueue_learning_jobs(len(records))
            if not allowed:
                _logger.warning("[PipelineController] Learning enqueue blocked: %s", reason)
                return 0
        
        _logger.info(f"[PipelineController] _submit_normalized_jobs called with {len(records)} NormalizedJobRecord(s)")
        
        # Sort jobs by model+VAE to minimize switch churn and crash risk
        records = self._sort_jobs_by_model(records)
        _logger.info(
            f"[PipelineController] Sorted {len(records)} jobs by model+vae to minimize WebUI switches"
        )

        submit_job = getattr(self._job_service, "submit_job_with_run_mode", None)
        emit_queue_updated = getattr(self._job_service, "_emit_queue_updated", None)
        queue = getattr(self._job_service, "job_queue", None)
        coalesce_queue_state = getattr(queue, "coalesce_state_notifications", None)
        submitted = 0
        run_config_to_use = run_config or getattr(self, "_last_run_config", None)
        batch_context = nullcontext()
        if callable(coalesce_queue_state):
            candidate_context = coalesce_queue_state()
            if hasattr(candidate_context, "__enter__") and hasattr(candidate_context, "__exit__"):
                batch_context = candidate_context
        with batch_context:
            for idx, record in enumerate(records):
                _logger.info(f"[PipelineController] Submitting NJR {idx+1}/{len(records)}: pack={record.prompt_pack_id}, row={record.prompt_pack_row_index}")
                prompt_pack_id = None
                cfg = record.config
                if isinstance(cfg, dict):
                    prompt_pack_id = cfg.get("prompt_pack_id")
                if prompt_pack_id and not getattr(record, "prompt_pack_id", None):
                    try:
                        record.prompt_pack_id = prompt_pack_id  # type: ignore[attr-defined]
                    except Exception:
                        record.prompt_pack_id = prompt_pack_id
                prompt_pack_name = None
                if isinstance(cfg, dict):
                    prompt_pack_name = cfg.get("prompt_pack_name") or cfg.get("pack_name")
                self._ensure_record_prompt_pack_metadata(record, prompt_pack_id, prompt_pack_name)
                job = self._to_queue_job(
                    record,
                    run_mode="queue",
                    source=source,
                    prompt_source=prompt_source,
                    prompt_pack_id=prompt_pack_id,
                    run_config=run_config_to_use,
                )
                job.payload = lambda j=job: self._run_job(j)
                if not hasattr(job, "_normalized_record") or job._normalized_record is None:
                    _logger.warning(
                        "PR-CORE1-B2: Job submitted without normalized_record in NJR-only mode. "
                        f"Job ID: {job.job_id}, Source: {source}"
                    )

                if callable(submit_job):
                    try:
                        submit_job(job, emit_queue_updated=False)
                    except TypeError:
                        submit_job(job)
                self._log_add_to_queue_event(job.job_id)
                submitted += 1

        if submitted > 0 and callable(emit_queue_updated):
            try:
                emit_queue_updated()
            except Exception:
                _logger.exception(
                    "[PipelineController] Failed to emit coalesced queue update after batch submission",
                    exc_info=True,
                )

        _logger.info(f"[PipelineController] Successfully submitted {submitted} jobs to queue")
        return submitted

    def reconstruct_jobs_from_snapshot(self, snapshot: dict[str, Any]) -> list[NormalizedJobRecord]:
        """Rebuild normalized jobs from a stored snapshot dictionary."""
        if not snapshot:
            return []
        record = self._hydrate_njr_from_snapshot(snapshot)
        if record is None:
            return []
        return [record]

    def _hydrate_history_record(self, entry: Any):
        return self._get_history_handoff_service().hydrate_history_record(entry)

    def _hydrate_njr_from_snapshot(
        self, snapshot: Mapping[str, Any] | None
    ) -> NormalizedJobRecord | None:
        return self._get_history_handoff_service().hydrate_njr_from_snapshot(snapshot)

    def replay_job_from_history(self, job_id: str) -> int:
        count = self._get_history_handoff_service().replay_job_from_history(
            job_id=job_id,
            history_service=self.get_job_history_service(),
            app_state=self._app_state,
            submit_normalized_jobs=self._submit_normalized_jobs,
            set_last_run_config=lambda config: setattr(self, "_last_run_config", config),
        )
        if count:
            _logger.info("Replayed job %s with %d queued job(s)", job_id, count)
        return count

    def on_replay_history_job_v2(self, record: HistoryRecord) -> Any:
        """Replay entrypoint that assumes NJR-only history records."""
        try:
            return self._job_controller.replay(record)
        except Exception:
            return None

    def get_job_history_service(self) -> JobHistoryService | None:
        """Return a JobHistoryService bound to this controller's queue/history."""

        if self._job_history_service is None:
            try:
                queue = self._job_controller.get_queue()
                history = self._job_controller.get_history_store()
                self._job_history_service = JobHistoryService(
                    queue, history, job_controller=self._job_controller
                )
            except Exception:
                pass
        return self._job_history_service

    def get_job_execution_controller(self) -> JobExecutionController:
        """Return the queue execution controller backing this pipeline controller."""
        return self._job_controller

    def get_job_service(self) -> JobService | None:
        """Return the queue service used by pipeline-facing GUI actions."""
        return self._job_service

    def replace_queue_runner(self, runner: Any) -> None:
        if self._job_service is None:
            raise RuntimeError("PipelineController has no JobService to synchronize")
        self._job_controller.replace_runner(runner)
        replace_runner = getattr(self._job_service, "replace_runner", None)
        if not callable(replace_runner):
            raise RuntimeError("JobService does not support coordinated runner replacement")
        replace_runner(runner)
        if self._job_controller.get_runner() is not self._job_service.runner:
            raise RuntimeError("Queue runner replacement left controller and service desynchronized")

    # -------------------------------------------------------------------------
    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        """Get diagnostics snapshot (PR-CORE1-A3: includes NJR visibility).

        Delegates to JobService which provides queue/history state including
        NormalizedJobRecord snapshots for debugging.
        """
        if self._job_service is None:
            return {}
        try:
            return self._job_service.get_diagnostics_snapshot()
        except Exception:
            return {}
