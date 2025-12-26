"""Compatibility wrapper that exposes the GUI pipeline controller at src.controller.

PipelineController – V2 Run Path (summary)

GUI Run buttons → AppController._start_run_v2 → PipelineController.start_pipeline
→ JobService / SingleNodeJobRunner → PipelineController._run_pipeline_job
→ run_pipeline (PipelineRunner-backed) → Executor/API → images in output_dir.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.controller.archive.pipeline_config_assembler import (
    GuiOverrides,
    PipelineConfigAssembler,
)
from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_lifecycle_logger import JobLifecycleLogger
from src.controller.job_service import JobService
from src.gui.controller import PipelineController as _GUIPipelineController
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.pipeline.pipeline_runner import PipelineRunner, PipelineRunResult
from src.pipeline.stage_sequencer import StageExecutionPlan, build_stage_execution_plan
from src.queue.job_model import Job, JobPriority, JobStatus

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from src.controller.archive.pipeline_config_types import PipelineConfig
# At runtime, some legacy code still constructs a PipelineConfig instance.
# Import the archive-only legacy dataclass when available so runtime calls
# that create `PipelineConfig(...)` continue to work in tests.
try:  # pragma: no cover - best-effort runtime import
    from src.controller.archive.pipeline_config_types import PipelineConfig  # type: ignore
except Exception:
    PipelineConfig = None  # type: ignore
from src.api.client import SDWebUIClient
from src.config.app_config import is_queue_execution_enabled
from src.controller.job_history_service import JobHistoryService
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.state import GUIState, PipelineState
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
)

# PR-CORE1-12: Legacy adapter still used by deprecated run_pipeline() method
# Will be removed when run_pipeline() is fully retired
from src.pipeline.legacy_njr_adapter import build_njr_from_legacy_pipeline_config
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
from src.utils.snapshot_builder_v2 import build_job_snapshot, normalized_job_from_snapshot

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


class PipelineController(_GUIPipelineController):
    def _build_njrs_from_pack_bundle(
        self, pack_entries: list[PackJobEntry]
    ) -> list[NormalizedJobRecord]:
        """Build NormalizedJobRecord(s) from a bundle of PackJobEntry using the canonical builder pipeline."""
        from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder

        _logger.info(f"[PipelineController] _build_njrs_from_pack_bundle received {len(pack_entries)} PackJobEntry objects")
        
        builder = PromptPackNormalizedJobBuilder(
            config_manager=self._config_manager,
            job_builder=self._job_builder,
            packs_dir=getattr(self._config_manager, "packs_dir", "packs"),
        )
        njrs = builder.build_jobs(pack_entries)
        _logger.info(f"[PipelineController] Builder returned {len(njrs)} NormalizedJobRecord(s)")
        _logger.debug(f"[PipelineController] About to return {len(njrs)} jobs")
        _logger.debug(f"[PipelineController] First job: {njrs[0] if njrs else 'NONE'}")
        return njrs

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
        base_config: PipelineConfig | None = None,
    ) -> list[NormalizedJobRecord]:
        """Build fully-normalized jobs from current GUI/AppState.

        This is the single entrypoint for V2 job construction.
        All run entrypoints should call this helper.

        Args:
            base_config: Optional pre-built PipelineConfig.
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
        base_config = None
        if self._config_assembler is not None:
            try:
                base_config = self._config_assembler.build_from_gui_input()
            except Exception as exc:
                _logger.debug("Config assembler failed: %s", exc)
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
        packs_dir = getattr(self._config_manager, "packs_dir", "packs")
        return PromptPackNormalizedJobBuilder(
            config_manager=self._config_manager,
            job_builder=self._job_builder,
            packs_dir=packs_dir,
        )

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
        if record is None:
            raise ValueError("PR-CORE1-B3: _to_queue_job requires a NormalizedJobRecord")

        config_snapshot = record.to_queue_snapshot()

        # Build randomizer metadata from record
        randomizer_metadata = record.randomizer_summary
        if not prompt_pack_id:
            prompt_pack_id = getattr(record, "prompt_pack_id", None) or None
        prompt_pack_name = getattr(record, "prompt_pack_name", None)
        prompt_source_value = prompt_source or getattr(record, "prompt_source", None) or "manual"
        prompt_source_value = str(prompt_source_value).lower()
        if prompt_pack_id and prompt_source_value != "pack":
            prompt_source_value = "pack"

        job = Job(
            job_id=record.job_id,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source_value,
            prompt_pack_id=prompt_pack_id,
            config_snapshot=config_snapshot,
            randomizer_metadata=randomizer_metadata,
            variant_index=record.variant_index,
            variant_total=record.variant_total,
            learning_enabled=self._learning_enabled,
        )
        job.snapshot = build_job_snapshot(
            job,
            record,
            run_config=run_config or self._last_run_config,
        )
        # PR-CORE1-B2: Attach NormalizedJobRecord for NJR-only execution
        job._normalized_record = record  # type: ignore[attr-defined]
        _logger.debug(
            "Prepared NJR-backed job for queue",
            extra={
                "job_id": job.job_id,
                "prompt_source": prompt_source_value,
                "prompt_pack_id": prompt_pack_id,
                "prompt_pack_name": prompt_pack_name,
            },
        )
        return job

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
        """Start pipeline using V2 job building via JobBuilderV2.

        This is the new V2 run entrypoint that:
        1. Builds normalized jobs via JobBuilderV2
        2. Converts them to queue Jobs
        3. Submits via JobService respecting run_mode

        Args:
            run_mode: Force "direct" or "queue". If None, uses state.
            source: Job source for provenance (e.g., "gui", "api").
            prompt_source: Prompt source type (e.g., "manual", "pack").
            prompt_pack_id: Optional prompt pack ID if using packs.
            on_complete: Callback on successful completion.
            on_error: Callback on error.

        Returns:
            True if jobs were submitted, False otherwise.
        """
        if not self.gui_can_run():
            return False

        # Check WebUI connection
        if hasattr(self, "_webui_connection"):
            state = self._webui_connection.ensure_connected(autostart=True)
            if state is not None and state is not WebUIConnectionState.READY:
                try:
                    self._safe_gui_transition(GUIState.ERROR)
                except Exception:
                    pass
                return False

        # Resolve run mode
        if run_mode is None:
            try:
                pipeline_state = self._get_pipeline_state()
                if pipeline_state:
                    run_mode = self._normalize_run_mode(pipeline_state)
                else:
                    run_mode = "queue"
            except Exception:
                run_mode = "queue"

        # Build normalized jobs
        try:
            normalized_jobs = self._build_normalized_jobs_from_state()
        except Exception as exc:
            _logger.error("Failed to build normalized jobs: %s", exc)
            if on_error:
                on_error(exc)
            return False

        prompt_pack_id = self._last_run_config and self._last_run_config.get("prompt_pack_id")
        if not prompt_pack_id:
            exc = ValueError("start_pipeline_v2 requires prompt_pack_id for provenance")
            if on_error:
                on_error(exc)
            return False

        if not normalized_jobs:
            _logger.warning("No jobs to submit")
            return False

        # Convert and submit each job
        submitted_count = 0
        for record in normalized_jobs:
            try:
                job = self._to_queue_job(
                    record,
                    run_mode=run_mode,
                    source=source,
                    prompt_source=prompt_source,
                    prompt_pack_id=prompt_pack_id,
                )
                # Attach payload for execution
                job.payload = lambda j=job: self._run_job(j)

                self._job_service.submit_job_with_run_mode(job)
                submitted_count += 1
            except Exception as exc:
                _logger.error("Failed to submit job %s: %s", record.job_id, exc)
                if on_error:
                    on_error(exc)

        if submitted_count > 0:
            self._safe_gui_transition(GUIState.RUNNING)
            _logger.info("Submitted %d jobs via V2 pipeline", submitted_count)
            return True

        return False

    def _build_pipeline_config_from_state(self) -> PipelineConfig:
        """Minimal pipeline_config builder for legacy/direct run pathways."""
        prompt = "StableNew GUI Run"
        try:
            app_state = getattr(self, "_app_state", None)
            if app_state and hasattr(app_state, "prompt"):
                prompt = app_state.prompt or prompt
        except Exception:
            prompt = "StableNew GUI Run"
        return PipelineConfig(
            prompt=prompt,
            model="model",
            sampler="sampler",
            width=512,
            height=512,
            steps=20,
            cfg_scale=7.0,
        )

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
        config_assembler: PipelineConfigAssembler | None = None,
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
        self._job_controller = JobExecutionController(execute_job=self._execute_job)
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
        self._setup_queue_callbacks()

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
        if not self.gui_can_run():
            return False

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
                if requested_mode in {"direct", "queue"}:
                    self._set_pipeline_run_mode(requested_mode)
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
            requested_mode = (run_config.get("run_mode") or "").strip().lower()
            if requested_mode in {"direct", "queue"}:
                run_mode = requested_mode

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

        try:
            self._active_job_id = self._job_controller.submit_pipeline_run(
                _payload, run_mode=run_mode
            )
        except TypeError:
            self._active_job_id = self._job_controller.submit_pipeline_run(_payload)
        self._safe_gui_transition(GUIState.RUNNING)
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

        # Normalize result into a dict payload for JobQueue/history.
        if hasattr(run_result, "to_dict"):
            return {"result": run_result.to_dict()}
        if isinstance(run_result, dict):
            return run_result
        return {"result": run_result}

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
                    queue_jobs.append(summary)
                    summaries.append(summary.positive_prompt_preview or job.job_id)
                except Exception:
                    summaries.append(job.job_id)
            else:
                summaries.append(job.job_id)
        self._app_state.set_queue_items(summaries)
        setter = getattr(self._app_state, "set_queue_jobs", None)
        if callable(setter):
            try:
                setter(queue_jobs)
            except Exception:
                pass

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
            return
        # Convert Job to UnifiedJobSummary via NJR
        njr = getattr(job, "_normalized_record", None)
        if njr:
            try:
                summary = UnifiedJobSummary.from_normalized_record(njr)
                self._app_state.set_running_job(summary)
            except Exception:
                pass

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

    def on_queue_remove_job_v2(self, job_id: str) -> None:
        queue = getattr(self._job_service, "job_queue", None)
        if queue and hasattr(queue, "remove"):
            try:
                queue.remove(job_id)
            except Exception:
                _logger.exception("on_queue_remove_job_v2 failed", exc_info=True)

    def on_queue_clear_v2(self) -> None:
        queue = getattr(self._job_service, "job_queue", None)
        if queue and hasattr(queue, "clear"):
            try:
                queue.clear()
            except Exception:
                _logger.exception("on_queue_clear_v2 failed", exc_info=True)

    def on_set_auto_run_v2(self, enabled: bool) -> None:
        if not self._app_state:
            return
        self._app_state.set_auto_run_queue(bool(enabled))

    def on_pause_queue_v2(self) -> None:
        if not self._job_service:
            return
        self._job_service.pause()
        if self._app_state:
            self._app_state.set_is_queue_paused(True)

    def on_resume_queue_v2(self) -> None:
        if not self._job_service:
            return
        self._job_service.resume()
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
        job = self._job_service.cancel_current()
        if job:
            job.status = JobStatus.QUEUED
            job.error_message = None
            self._job_service.enqueue(job)

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
        count = self.submit_preview_jobs_to_queue(run_config=run_config)
        if count and self._app_state:
            self._app_state.clear_job_draft()
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
            # Build PipelineConfig for this job
            _config = self._config_assembler.build_from_gui_input(
                overrides=GuiOverrides(prompt=planned_job.prompt_text),
                lora_settings=planned_job.lora_settings,
                randomizer_metadata=planned_job.randomizer_metadata,
            )

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
            api_client = SDWebUIClient(
                base_url="http://127.0.0.1:7860",
            )
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
            try:
                result = runner.run_njr(record, self.cancel_token)
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
        
        _logger.info(f"[PipelineController] _submit_normalized_jobs called with {len(records)} NormalizedJobRecord(s)")
        
        submitted = 0
        run_config_to_use = run_config or getattr(self, "_last_run_config", None)
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
            # PR-CORE1-B2: Enforce NJR-only invariant for new queue jobs
            if not hasattr(job, "_normalized_record") or job._normalized_record is None:
                _logger.warning(
                    "PR-CORE1-B2: Job submitted without normalized_record in NJR-only mode. "
                    f"Job ID: {job.job_id}, Source: {source}"
                )

            self._job_service.submit_job_with_run_mode(job)
            self._log_add_to_queue_event(job.job_id)
            submitted += 1
        
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

    def _hydrate_history_record(self, entry: Any) -> HistoryRecord | None:
        if entry is None:
            return None
        if isinstance(entry, HistoryRecord):
            return entry
        raw: dict[str, Any] = {}
        if isinstance(entry, Mapping):
            raw.update(entry)
        else:
            raw.update(getattr(entry, "__dict__", {}) or {})
        if hasattr(entry, "job_id"):
            raw.setdefault("job_id", entry.job_id)
            raw.setdefault("id", entry.job_id)
        if hasattr(entry, "status"):
            raw.setdefault("status", entry.status)
        if hasattr(entry, "created_at"):
            raw.setdefault("timestamp", entry.created_at)
        snapshot = getattr(entry, "snapshot", None)
        if snapshot is not None:
            raw.setdefault("snapshot", snapshot)
        return HistoryRecord.from_dict(raw)

    def _hydrate_njr_from_snapshot(
        self, snapshot: Mapping[str, Any] | None
    ) -> NormalizedJobRecord | None:
        if not snapshot:
            return None
        constructor = getattr(NormalizedJobRecord, "from_snapshot", None)
        if callable(constructor):
            try:
                return constructor(snapshot)
            except Exception:
                pass
        if "normalized_job" in snapshot:
            return normalized_job_from_snapshot(snapshot)
        return normalized_job_from_snapshot({"normalized_job": snapshot})

    def replay_job_from_history(self, job_id: str) -> int:
        history_service = self.get_job_history_service()
        if history_service is None:
            return 0
        entry = history_service.get_job(job_id)
        record = self._hydrate_history_record(entry)
        if record is None:
            return 0
        njr = self._hydrate_njr_from_snapshot(record.njr_snapshot)
        if njr is None:
            return 0
        records = [njr]
        if self._app_state and hasattr(self._app_state, "set_preview_jobs"):
            try:
                self._app_state.set_preview_jobs(records)
            except Exception:
                pass
        run_config = record.metadata or record.njr_snapshot.get("run_config") or {}
        if run_config:
            self._last_run_config = run_config
        count = self._submit_normalized_jobs(
            records,
            run_config=run_config,
            source=record.njr_snapshot.get("source", "gui"),
            prompt_source=record.njr_snapshot.get("prompt_source", "manual"),
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

    def run_pipeline(self, config: PipelineConfig) -> PipelineRunResult:
        """DEPRECATED (PR-CORE1-12): Legacy synchronous pipeline execution.

        This method converts pipeline_config to NJR using legacy adapter, then
        executes via run_njr(). Used only by deprecated app_controller paths.

        PREFER: start_pipeline_v2() which builds NJR + enqueues for async execution.

        Args:
            config: Legacy PipelineConfig (converted internally to NJR)

        Returns:
            PipelineRunResult
        """
        if self._pipeline_runner is not None:
            record = build_njr_from_legacy_pipeline_config(config)
            result = self._pipeline_runner.run_njr(record, self.cancel_token)
        else:
            api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
            structured_logger = StructuredLogger()
            runner = PipelineRunner(api_client, structured_logger)
            record = build_njr_from_legacy_pipeline_config(config)
            result = runner.run_njr(record, self.cancel_token)
        self.record_run_result(result)
        return result

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
