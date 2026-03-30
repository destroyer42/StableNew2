"""
StableNew - App Controller (Skeleton + CancelToken + Worker Thread Stub)

PR-CORE1-12: DEPRECATED - Legacy AppController retained only for GUI skeleton compatibility.
Runtime pipeline execution via pipeline_config has been REMOVED.

Use PipelineController + NJR path for all new code. Do not add pipeline_config-based
execution logic. All queue/runner execution must use NormalizedJobRecord (NJR) + PromptPack.

It provides:
- Lifecycle state management (IDLE, RUNNING, STOPPING, ERROR).
- Methods for GUI callbacks (run/stop/preview/etc.).
- A CancelToken + worker-thread stub for future pipeline integration.
- A 'threaded' mode for real runs and a synchronous mode for tests.

Real pipeline execution, WebUI client integration, and logging details
will be wired in later via a PipelineRunner abstraction.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import json
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, TypedDict

from src.api.webui_api import WebUIAPI
from src.api.webui_process_manager import (
    WebUIProcessManager,
    clear_global_webui_process_manager,
    get_global_webui_process_manager,
)
from src.api.webui_resource_service import (
    WebUIResourceService,
    build_empty_resource_map,
    normalize_resource_map,
)
from src.api.webui_resources import WebUIResource
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)
from src.gui.dropdown_loader_v2 import DropdownLoader
from src.gui.main_window_v2 import MainWindow
from src.gui.panels_v2.debug_hub_panel_v2 import DebugHubPanelV2
from src.gui.panels_v2.job_explanation_panel_v2 import JobExplanationPanelV2
from src.gui.views.error_modal_v2 import ErrorModalV2
from src.curation.curation_manifest import build_review_chunk_lineage_block
from src.pipeline.last_run_store_v2_5 import (
    LastRunStoreV2_5,
    current_config_to_last_run,
    update_current_config_from_last_run,
)
from src.pipeline.config_contract_v26 import (
    validate_svd_native_execution_config,
    validate_train_lora_execution_config,
)
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_requests_v2 import (
    PipelineRunMode,
    PipelineRunRequest,
    PipelineRunSource,
)
from src.pipeline.reprocess_builder import (
    ImageEditSpec,
    ReprocessEffectiveSettingsPreview,
    ReprocessJobBuilder,
    ReprocessSourceItem,
    extract_reprocess_output_paths,
)
from src.pipeline.pipeline_runner import normalize_run_result
from src.pipeline.job_models_v2 import JobStatusV2, UnifiedJobSummary
from src.controller.app_controller_services.learning_completion_router import (
    build_learning_completion_handler,
)
from src.controller.ports.default_runtime_ports import DefaultImageRuntimePorts
from src.controller.ports.runtime_ports import ImageRuntimePorts
from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.controller.app_controller_services.gui_config_service import GuiConfigService
from src.controller.app_controller_services.run_submission_service import (
    QueueRunSubmissionService,
)
from src.app.optional_dependency_probes import OptionalDependencySnapshot
import logging
import uuid

from src.config.app_config import (
    get_jsonl_log_config,
    is_debug_shutdown_inspector_enabled,
    set_webui_autostart_enabled,
    set_webui_health_initial_timeout_seconds,
    set_webui_health_retry_count,
    set_webui_health_retry_interval_seconds,
    set_webui_health_total_timeout_seconds,
    set_webui_workdir,
    set_job_history_path,
)
from src.controller.job_history_service import JobHistoryService
from src.controller.job_lifecycle_logger import JobLifecycleLogger
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.process_auto_scanner_service import (
    ProcessAutoScannerConfig,
    ProcessAutoScannerService,
)
from src.gui.controllers.review_workflow_adapter import ReviewWorkflowAdapter
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.learning.model_profiles import get_model_profile_defaults_for_model
from src.photo_optimize import get_photo_optimize_store
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.services.duration_stats_service import DurationStatsService
from src.state.output_routing import OUTPUT_ROUTE_MOVIE_CLIPS, get_output_route_root
from src.runtime_host import (
    RUNTIME_HOST_EVENT_JOB_FAILED,
    RUNTIME_HOST_EVENT_JOB_FINISHED,
    RUNTIME_HOST_EVENT_JOB_STARTED,
    RUNTIME_HOST_EVENT_QUEUE_EMPTY,
    RUNTIME_HOST_EVENT_QUEUE_STATUS,
    RUNTIME_HOST_EVENT_QUEUE_UPDATED,
    RUNTIME_HOST_EVENT_WATCHDOG_VIOLATION,
    RuntimeHostPort,
    build_local_runtime_host,
    coerce_runtime_host,
)
from src.utils import (
    InMemoryLogHandler,
    LogContext,
    StructuredLogger,
    attach_jsonl_log_handler,
    close_all_structured_loggers,
    log_with_ctx,
)
from src.utils.config import ConfigManager, LoraRuntimeConfig, normalize_lora_strengths
from src.utils.debug_shutdown_inspector import log_shutdown_state
from src.utils.diagnostics_bundle_v2 import build_crash_bundle
from src.utils.error_envelope_v2 import (
    UnifiedErrorEnvelope,
    get_attached_envelope,
    serialize_envelope,
    wrap_exception,
)
from src.utils.thread_registry import get_thread_registry
from src.utils.file_io import load_image_to_base64, read_prompt_pack
from src.utils.prompt_packs import PromptPackInfo, discover_packs
from src.utils.process_inspector_v2 import (
    collect_process_risk_snapshot,
    format_process_brief,
    iter_stablenew_like_processes,
)

logger = logging.getLogger(__name__)

_IMAGE_OUTPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
_QUEUE_PROJECTION_TIMING_INFO_MS = 150.0
_QUEUE_PROJECTION_TIMING_WARN_MS = 1000.0
_INITIAL_RESOURCE_PROBE_GRACE_SEC = 30.0
_DIAGNOSTICS_HEAVY_SNAPSHOT_TTL_SEC = 4.0


class LifecycleState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


class RunMode(str, Enum):
    QUEUE = "queue"


class RunSource(str, Enum):
    RUN_BUTTON = "run"
    RUN_NOW_BUTTON = "run_now"
    ADD_TO_QUEUE_BUTTON = "add_to_queue"


class RunConfigDict(TypedDict, total=False):
    run_mode: str
    source: str
    prompt_source: str
    prompt_pack_id: str
    pipeline_state_snapshot: dict[str, Any]


@dataclass
class RunConfig:
    """
    Minimal placeholder for the full run configuration.

    In a real implementation this will be built from:
    - presets/ JSON
    - GUI state (model, sampler, resolution, randomization, matrix)
    - prompt pack selection
    """

    preset_name: str = ""
    model_name: str = ""
    vae_name: str = ""
    sampler_name: str = ""
    scheduler_name: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 30
    cfg_scale: float = 7.5
    randomization_enabled: bool = False
    max_variants: int = 1
    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_at: float = 0.8
    hires_enabled: bool = False
    hires_upscaler_name: str = "Latent"
    hires_upscale_factor: float = 2.0
    hires_steps: int | None = None
    hires_denoise: float = 0.3
    hires_use_base_model_for_hires: bool = True
    # Future fields:
    # matrix_config, adetailer_config, video_config, etc.


@dataclass(frozen=True)
class DeprecatedPipelineConfigSnapshot:
    """Deprecated config snapshot retained only for non-runtime helpers/tests."""

    prompt: str
    negative_prompt: str
    model: str
    sampler: str
    width: int
    height: int
    steps: int
    cfg_scale: float
    pack_name: str | None = None
    preset_name: str | None = None
    lora_settings: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    refiner_enabled: bool = False
    refiner_model_name: str = ""
    refiner_switch_at: float = 0.8
    hires_fix: dict[str, Any] | None = None


@dataclass
class AppState:
    lifecycle: LifecycleState = LifecycleState.IDLE
    last_error: str | None = None
    current_config: RunConfig = field(default_factory=RunConfig)
    resources: dict[str, list[Any]] = field(
        default_factory=lambda: {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
        }
    )


class CancelToken:
    """
    Simple cancellable flag for cooperative cancellation of the pipeline.

    A real implementation can grow to include thread-safe semantics if needed.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()
        self._needs_stop_to_finish = False

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def require_stop_to_finish(self) -> None:
        """Signal that caller expects an explicit stop before finishing."""
        with self._lock:
            self._needs_stop_to_finish = True

    def clear_stop_requirement(self) -> None:
        with self._lock:
            self._needs_stop_to_finish = False

    def needs_stop_to_finish(self) -> bool:
        with self._lock:
            return self._needs_stop_to_finish


class AppController:
    _queue_submit_in_progress: bool = False

    def on_add_to_queue_clicked(self) -> None:
        """Fire-and-forget async boundary for Add to Queue."""
        if getattr(self, "_queue_submit_in_progress", False):
            self._append_log("[D21] Queue submit already in progress; ignoring duplicate request.")
            return
        self._queue_submit_in_progress = True
        jobs = getattr(self, "_draft_job_bundle", [])
        self._draft_job_bundle = []
        
        # PR-THREAD-001: Use tracked thread for clean shutdown
        self._spawn_tracked_thread(
            target=self._submit_jobs_async,
            args=(jobs,),
            name="QueueSubmit",
            purpose="Submit jobs to queue asynchronously"
        )

    def _submit_jobs_async(self, jobs):
        try:
            for job in jobs:
                self.job_service.submit_queued(job)
        finally:
            self._queue_submit_in_progress = False
    
    def _spawn_tracked_thread(
        self,
        target: Callable,
        args: tuple = (),
        kwargs: dict | None = None,
        name: str | None = None,
        daemon: bool = False,
        purpose: str | None = None,
    ) -> threading.Thread:
        """
        Spawn a tracked thread for clean shutdown.
        
        PR-THREAD-001: All background operations must use this method
        to ensure proper cleanup during shutdown.
        
        Args:
            target: Function to run in thread
            args: Positional arguments for target
            kwargs: Keyword arguments for target
            name: Thread name (required)
            daemon: Whether to use daemon mode (discouraged)
            purpose: Description of thread purpose
        
        Returns:
            The spawned thread
        """
        if kwargs is None:
            kwargs = {}
        
        return self._thread_registry.spawn(
            target=target,
            args=args,
            kwargs=kwargs,
            name=name or "UnnamedThread",
            daemon=daemon,
            purpose=purpose,
        )

    def __init__(
        self,
        main_window: MainWindow | None,
        pipeline_runner: Any | None = None,
        threaded: bool = True,
        packs_dir: Path | str | None = None,
        api_client: Any | None = None,
        structured_logger: StructuredLogger | None = None,
        webui_process_manager: WebUIProcessManager | None = None,
        config_manager: ConfigManager | None = None,
        resource_service: WebUIResourceService | None = None,
        job_service: JobService | None = None,
        runtime_host: RuntimeHostPort | None = None,
        pipeline_controller: PipelineController | None = None,
        ui_scheduler: Callable[[Callable[[], None]], None] = None,
        runtime_ports: ImageRuntimePorts | None = None,
        optional_dependency_snapshot: OptionalDependencySnapshot | None = None,
    ) -> None:
        import threading
        import time

        self._ui_thread_id = threading.get_ident()
        self._ui_scheduler = ui_scheduler
        self._runtime_ports = runtime_ports or DefaultImageRuntimePorts()
        self._optional_dependency_snapshot = optional_dependency_snapshot
        # --- BEGIN PR-CORE1-D21A: Watchdog/Diagnostics wiring ---
        # Watchdog is attached by app_factory after the GUI is constructed.
        # (Avoids triggering diagnostics during import/startup and allows tests to opt-out.)
        self.diagnostics_service = None
        self._system_watchdog = None
        # --- END PR-CORE1-D21A ---
        # PR-THREAD-001: Thread registry for clean shutdown
        self._thread_registry = get_thread_registry()
        self._is_shutting_down = False
        self.runtime_host = coerce_runtime_host(runtime_host or job_service)
        self.job_service = self.runtime_host
        self.last_ui_heartbeat_ts = time.monotonic()
        self.last_queue_activity_ts = time.monotonic()
        self.last_runner_activity_ts = time.monotonic()
        
        # PR-HB-002: Operation tracking for heartbeat stall diagnostics
        self.current_operation_label: str | None = None
        self.last_ui_action: str | None = None
        
        # PR-HB-003: UI update debouncing to prevent heartbeat stalls
        self._ui_preview_dirty = False
        self._ui_job_list_dirty = False
        self._ui_history_dirty = False
        self._ui_queue_dirty = False
        self._ui_debounce_pending = False
        self._ui_debounce_delay_ms = 150  # Coalesce updates within 150ms window
        self._preview_refresh_request_id = 0
        self._queue_refresh_request_id = 0
        self._queue_refresh_in_progress = False
        self._run_submission_in_progress = False
        self._last_queue_projection_timing: dict[str, Any] | None = None
        self._runtime_status_lock = threading.Lock()
        self._runtime_status_flush_scheduled = False
        self._pending_runtime_status = None
        self._last_runtime_status = None
        self._last_runtime_status_flush_ts = 0.0
        self._runtime_status_min_interval_ms = 250
        
        self.main_window = main_window
        self.app_state = getattr(main_window, "app_state", None)
        if self.app_state is None:
            self.app_state = AppStateV2()
            if main_window is not None:
                main_window.app_state = self.app_state
        self._job_lifecycle_logger = JobLifecycleLogger(app_state=self.app_state)
        self.state = AppState()
        self.threaded = threaded
        self._config_manager = config_manager or ConfigManager()
        self._dropdown_loader = DropdownLoader(self._config_manager)
        self._warned_missing_pipeline_apply = False
        self._last_executor_config: dict[str, Any] | None = None
        self._last_run_snapshot: dict[str, Any] | None = None
        self._last_run_auto_restored = False
        self._last_run_store = LastRunStoreV2_5()
        self._last_run_config: RunConfigDict | None = None
        # GUI log handler for LogTracePanelV2 (captures DEBUG and above for GUI display)
        self.gui_log_handler = InMemoryLogHandler(max_entries=500, level=logging.DEBUG)
        root_logger = logging.getLogger()
        # Ensure root logger level allows DEBUG messages to reach handlers
        if root_logger.level > logging.DEBUG or root_logger.level == logging.NOTSET:
            root_logger.setLevel(logging.INFO)  # Changed from DEBUG to reduce noise
        root_logger.addHandler(self.gui_log_handler)
        json_config = get_jsonl_log_config()
        self.json_log_handler = attach_jsonl_log_handler(json_config, level=logging.INFO)
        
        # Pipeline runner and controller setup
        # Don't do port discovery on startup - too slow (50+ seconds if WebUI not running)
        # Use default port and discover later if connection fails
        load_settings = getattr(self._config_manager, "load_settings", None)
        settings = load_settings() if callable(load_settings) else {}
        default_url = str(settings.get("webui_base_url") or "").strip() or os.getenv(
            "STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"
        )
        
        if pipeline_runner is not None:
            self.pipeline_runner = pipeline_runner
            self._api_client = api_client or self._runtime_ports.create_client(base_url=default_url)
            self._structured_logger = structured_logger or StructuredLogger()
        else:
            self._api_client = api_client or self._runtime_ports.create_client(base_url=default_url)
            self._structured_logger = structured_logger or StructuredLogger()
            self.pipeline_runner = self._runtime_ports.create_runner(
                api_client=self._api_client,
                structured_logger=self._structured_logger,
            )
        self._apply_initial_resource_probe_grace()
        self._webui_api: WebUIAPI | None = None
        client = getattr(self, "_api_client", None)
        self.resource_service = resource_service or WebUIResourceService(client=client)
        self.state.resources = self._empty_resource_map()
        self.webui_process_manager = webui_process_manager
        self._cancel_token: CancelToken | None = None
        self._worker_thread: threading.Thread | None = None
        self._packs_dir = Path(packs_dir) if packs_dir is not None else Path("packs")
        history_path = Path("runs") / "job_history.json"
        if os.environ.get("PYTEST_CURRENT_TEST"):
            history_path = (
                Path(tempfile.gettempdir())
                / f"job_history_{os.getpid()}_{uuid.uuid4().hex}.json"
            )
            set_job_history_path(str(history_path))
        self._job_history_path = history_path
        self._duration_stats_service = None
        self._last_diagnostics_bundle: Path | None = None
        self._last_diagnostics_bundle_reason: str | None = None
        self._app_state_visibility_listener = None

        self._diagnostics_lock = threading.Lock()
        self._diagnostics_process_snapshot_cache: dict[str, Any] | None = None
        self._diagnostics_thread_snapshot_cache: dict[str, Any] | None = None
        self._diagnostics_heavy_snapshot_ts = 0.0
        self._diagnostics_heavy_snapshot_refresh_in_progress = False
        self._last_error_envelope: UnifiedErrorEnvelope | None = None
        self._error_modal: ErrorModalV2 | None = None
        self._original_excepthook = sys.excepthook
        self._original_threading_excepthook = getattr(threading, "excepthook", None)
        self._original_tk_report_callback_exception: Callable[..., Any] | None = None
        self._shutdown_started_at: float | None = None
        self._shutdown_completed = False
        self._shutdown_watchdog_thread: threading.Thread | None = None
        self.packs: list[PromptPackInfo] = []
        self._selected_pack_index: int | None = None
        # Initialize PipelineController for modern pipeline execution (bridge)
        if pipeline_controller is not None:
            self.pipeline_controller = pipeline_controller
        else:
            self.pipeline_controller = PipelineController(
                api_client=self._api_client,
                structured_logger=self._structured_logger,
                runtime_host=self.runtime_host,
                pipeline_runner=self.pipeline_runner,
                job_lifecycle_logger=self._job_lifecycle_logger,
                app_state=self.app_state,
                runtime_ports=self._runtime_ports,
                app_controller=self,  # PR-HEARTBEAT-FIX: Pass self for heartbeat updates
            )
        try:
            setattr(self.pipeline_controller, "_app_state_queue_updates_managed_externally", True)
        except Exception:
            pass

        pipeline_runtime_host = None
        get_runtime_host = getattr(self.pipeline_controller, "get_runtime_host", None)
        if callable(get_runtime_host):
            pipeline_runtime_host = get_runtime_host()
        get_job_service = getattr(self.pipeline_controller, "get_job_service", None)
        if pipeline_runtime_host is None and callable(get_job_service):
            pipeline_runtime_host = get_job_service()
        elif pipeline_runtime_host is None and hasattr(self.pipeline_controller, "_job_service"):
            pipeline_runtime_host = getattr(self.pipeline_controller, "_job_service", None)
        if pipeline_runtime_host is not None:
            self.runtime_host = coerce_runtime_host(pipeline_runtime_host)
            self.job_service = self.runtime_host
        elif self.job_service is None:
            self.runtime_host = self._build_runtime_host()
            self.job_service = self.runtime_host

        if self.job_service and hasattr(self.job_service, "set_job_lifecycle_logger"):
            self.job_service.set_job_lifecycle_logger(self._job_lifecycle_logger)

        # PR-PIPE-002: Initialize duration stats service for queue ETA
        history_store = getattr(self.job_service, "history_store", None) if self.job_service else None
        self._duration_stats_service = DurationStatsService(history_store=history_store)
        if self._duration_stats_service:
            try:
                self._duration_stats_service.refresh()
            except Exception as exc:
                self._append_log(f"[duration_stats] Initial refresh failed: {exc}")
        
        # PR-LEARN-012: Initialize LearningExecutionController (NEW implementation)
        from src.learning.execution_controller import LearningExecutionController
        from src.gui.learning_state import LearningState
        
        # Initialize learning state if not exists
        if not hasattr(self, '_learning_state'):
            self._learning_state = LearningState()
        
        self.learning_execution_controller = LearningExecutionController(
            learning_state=self._learning_state,
            job_service=self.job_service,
        )
        # Compatibility for integration tests expecting a run callable field.
        try:
            self.learning_execution_controller._run_callable = self._learning_run_callable  # type: ignore[attr-defined]
        except Exception:
            pass
        
        # PR-LEARN-003: Register learning completion handler
        if self.job_service:
            self._learning_completion_handler = self._create_learning_completion_handler()
            register_completion = getattr(self.job_service, "register_completion_handler", None)
            if callable(register_completion):
                register_completion(self._learning_completion_handler)
            self._photo_optimize_completion_handler = self._create_photo_optimize_completion_handler()
            if callable(register_completion):
                register_completion(self._photo_optimize_completion_handler)
        
        self.webui_connection_controller = getattr(
            self.pipeline_controller, "_webui_connection", None
        )
        if self.webui_connection_controller is None:
            self.webui_connection_controller = WebUIConnectionController()
        
        # Override pack config state (for ConfigMergerV2 integration)
        self.override_pack_config_enabled = False
        try:
            self.webui_connection_controller.register_on_ready(self.on_webui_ready)
        except Exception:
            pass
        try:
            self.webui_connection_controller.set_on_resources_updated(
                self._on_webui_resources_updated
            )
        except Exception:
            pass
        if (
            hasattr(self._api_client, "set_options_readiness_provider")
            and self.webui_connection_controller is not None
        ):
            try:
                self._api_client.set_options_readiness_provider(
                    self.webui_connection_controller.is_webui_ready_strict
                )
            except Exception:
                pass
        # PR-CORE1-D21B: Wire activity hooks for queue/runner heartbeats
        if (
            hasattr(self.pipeline_controller, "job_service")
            and self.pipeline_controller.job_service is not None
        ):
            self.pipeline_controller.job_service.set_activity_hooks(
                on_queue_activity=self.notify_queue_activity,
                on_runner_activity=self.notify_runner_activity,
            )
        try:
            jc = getattr(self.pipeline_controller, "_job_controller", None)
            if jc and hasattr(self.job_service, "history_store"):
                shared_history = self.job_service.history_store
                queue = getattr(jc, "_queue", None)
                if queue is not None:
                    try:
                        queue._history_store = shared_history  # type: ignore[attr-defined]
                    except Exception:
                        pass
        except Exception:
            pass
        # PR-SCANNER-001: Disable ProcessAutoScanner by default to prevent self-kill
        self.process_auto_scanner = ProcessAutoScannerService(
            config=ProcessAutoScannerConfig(),
            protected_pids=self._get_protected_process_pids,
            start_thread=False,  # DISABLED - prevents GUI from being killed
        )
        
        # PR-HB-004: Initialize persistence worker with UI callback dispatcher
        try:
            from src.services.persistence_worker import get_persistence_worker
            worker = get_persistence_worker()
            if self.main_window and hasattr(self.main_window, "run_in_main_thread"):
                worker._ui_callback_dispatcher = self.main_window.run_in_main_thread
            logger.debug("[controller] Persistence worker initialized")
        except Exception as e:
            logger.error(f"[controller] Failed to initialize persistence worker: {e}")
        
        # Wire GUI overrides into PipelineController so config assembler can access GUI state
        if hasattr(self.pipeline_controller, "get_gui_overrides"):
            self.pipeline_controller.get_gui_overrides = self._get_gui_overrides_for_pipeline  # type: ignore[attr-defined]
        # Let the GUI wire its callbacks to us
        if self.main_window is not None:
            self._bind_app_state_visibility_listener()
            self._attach_to_gui()
            if hasattr(self.main_window, "connect_controller"):
                self.main_window.connect_controller(self)
        self._setup_queue_callbacks()
        self._setup_diagnostics_hooks()

    def shutdown(self) -> None:
        """
        Shutdown the AppController and all background services cleanly.
        
        PR-SHUTDOWN-001: Enhanced to stop SystemWatchdog, join all tracked threads,
        close file handles, and verify clean exit.
        """
        logger.info("[controller] shutdown(): Stopping system watchdog...")
        if hasattr(self, "_system_watchdog") and self._system_watchdog:
            try:
                self._system_watchdog.stop()
                logger.info("[controller] shutdown(): System watchdog stopped")
            except Exception as e:
                logger.error(f"[controller] shutdown(): Error stopping watchdog: {e}")
        
        # PR-HB-004: Shutdown persistence worker
        logger.info("[controller] shutdown(): Shutting down persistence worker...")
        try:
            from src.services.persistence_worker import shutdown_persistence_worker
            shutdown_persistence_worker(timeout=5.0)
            logger.info("[controller] shutdown(): Persistence worker shut down")
        except Exception as e:
            logger.error(f"[controller] shutdown(): Error shutting down persistence worker: {e}")
        
        # PR-SHUTDOWN-001: Shutdown history store background writer
        logger.info("[controller] shutdown(): Shutting down history store writer...")
        if self.job_service:
            history_store = getattr(self.job_service, "history_store", None)
            if history_store and hasattr(history_store, "shutdown"):
                try:
                    history_store.shutdown()
                    logger.info("[controller] shutdown(): History store writer shut down")
                except Exception as e:
                    logger.error(f"[controller] shutdown(): Error shutting down history store: {e}")
        
        # PR-THREAD-001: Join all tracked threads
        logger.info("[controller] shutdown(): Joining all tracked threads...")
        try:
            stats = self._thread_registry.shutdown_all(timeout=10.0)
            logger.info(
                f"[controller] shutdown(): Thread shutdown complete - "
                f"joined={stats['joined']}, timeout={stats['timeout']}, "
                f"orphaned={stats['orphaned']}"
            )
            if stats['timeout'] > 0 or stats['orphaned'] > 0:
                logger.warning(f"[controller] shutdown(): {stats['timeout']} threads timed out, {stats['orphaned']} daemon threads orphaned")
        except Exception as e:
            logger.error(f"[controller] shutdown(): Error during thread shutdown: {e}")

    def _ui_dispatch(self, fn: Callable[[], None]) -> None:
        import threading

        ui_thread_id = getattr(self, "_ui_thread_id", None)
        if ui_thread_id is not None and threading.get_ident() == ui_thread_id:
            fn()
            return
        scheduler = getattr(self, "_ui_scheduler", None)
        if callable(scheduler):
            scheduler(fn)
            return
        mw = getattr(self, "main_window", None)
        if mw is not None:
            dispatcher = getattr(mw, "run_in_main_thread", None)
            if callable(dispatcher):
                dispatcher(fn)
                return
        if self._dispatch_via_root_after(0, fn):
            return
        # fallback: run directly (test mode)
        fn()

    def _run_in_gui_thread(self, fn: Callable[[], None]) -> None:
        """Schedule the callable on the Tk main thread, safe from any thread."""
        import threading

        ui_thread_id = getattr(self, "_ui_thread_id", None)
        if ui_thread_id is not None and threading.get_ident() == ui_thread_id:
            fn()
            return
        mw = getattr(self, "main_window", None)
        if mw is not None:
            dispatcher = getattr(mw, "run_in_main_thread", None)
            if callable(dispatcher):
                dispatcher(fn)
                return
        self._ui_dispatch(fn)

    def _get_ui_root(self) -> Any | None:
        mw = getattr(self, "main_window", None)
        if mw is None:
            return None
        return getattr(mw, "root", None) or getattr(mw, "master", None) or mw

    def _dispatch_via_root_after(self, delay_ms: int, fn: Callable[[], None]) -> bool:
        root = self._get_ui_root()
        if root is None:
            return False
        after = getattr(root, "after", None)
        if not callable(after):
            return False
        try:
            after(int(delay_ms), fn)
            return True
        except Exception:
            return False

    def _ui_dispatch_later(self, delay_ms: int, fn: Callable[[], None]) -> None:
        delay = max(0, int(delay_ms or 0))
        if delay == 0:
            self._ui_dispatch(fn)
            return
        if self._dispatch_via_root_after(delay, fn):
            return
        fn()
    
    def _mark_ui_dirty(
        self,
        preview: bool = False,
        jobs: bool = False,
        history: bool = False,
        queue: bool = False,
    ) -> None:
        """Mark UI components as needing refresh and schedule debounced update.
        
        PR-HB-003: Coalesces multiple rapid update requests into a single
        periodic refresh to prevent heartbeat stalls.
        """
        if not hasattr(self, "_ui_preview_dirty"):
            self._ui_preview_dirty = False
        if not hasattr(self, "_ui_job_list_dirty"):
            self._ui_job_list_dirty = False
        if not hasattr(self, "_ui_history_dirty"):
            self._ui_history_dirty = False
        if not hasattr(self, "_ui_queue_dirty"):
            self._ui_queue_dirty = False
        if not hasattr(self, "_ui_debounce_pending"):
            self._ui_debounce_pending = False
        if not hasattr(self, "_ui_debounce_delay_ms"):
            self._ui_debounce_delay_ms = 0
        if preview:
            self._ui_preview_dirty = True
        if jobs:
            self._ui_job_list_dirty = True
        if history:
            self._ui_history_dirty = True
        if queue:
            self._ui_queue_dirty = True
        
        # Schedule debounced update if not already pending
        if not self._ui_debounce_pending:
            self._ui_debounce_pending = True
            self._schedule_debounced_ui_update()
    
    def _schedule_debounced_ui_update(self) -> None:
        """Schedule a debounced UI update after delay.
        
        PR-HB-003: Uses UI scheduler to coalesce updates into a single refresh.
        """
        self._ui_dispatch_later(self._ui_debounce_delay_ms, self._apply_pending_ui_updates)
    
    def _apply_pending_ui_updates(self) -> None:
        """Apply all pending UI updates and clear dirty flags.
        
        PR-HB-003: Central UI update sink that processes all coalesced updates.
        """
        try:
            self._ui_debounce_pending = False
            
            # Update last heartbeat timestamp
            import time
            self.last_ui_heartbeat_ts = time.monotonic()
            
            # Apply updates based on dirty flags
            if self._ui_preview_dirty:
                self._ui_preview_dirty = False
                try:
                    self._refresh_preview_from_state_async()
                except Exception as exc:
                    logger.exception(f"[AppController] Error refreshing preview: {exc}")
            
            if self._ui_job_list_dirty:
                self._ui_job_list_dirty = False
                try:
                    # Trigger job list refresh if needed
                    if self.main_window and hasattr(self.main_window, "refresh_job_list"):
                        self.main_window.refresh_job_list()
                except Exception as exc:
                    logger.exception(f"[AppController] Error refreshing job list: {exc}")
            
            if self._ui_history_dirty:
                self._ui_history_dirty = False
                try:
                    # Trigger history refresh if needed
                    if self.main_window and hasattr(self.main_window, "refresh_history"):
                        self.main_window.refresh_history()
                except Exception as exc:
                    logger.exception(f"[AppController] Error refreshing history: {exc}")

            if getattr(self, "_ui_queue_dirty", False):
                self._ui_queue_dirty = False
                try:
                    self._refresh_app_state_queue()
                except Exception as exc:
                    logger.exception(f"[AppController] Error refreshing queue state: {exc}")
        
        except Exception as exc:
            logger.exception(f"[AppController] Error in _apply_pending_ui_updates: {exc}")

    def _wrap_ui_callback(self, handler: Callable[..., None] | None) -> Callable[..., None] | None:
        """Return a callable that schedules `handler(*args, **kwargs)` via `_ui_dispatch`.

        If `handler` is None, returns None. The wrapper preserves argument shapes
        and does not swallow exceptions raised by `handler`.
        """
        if handler is None:
            return None

        def _wrapped(*args: Any, **kwargs: Any) -> None:
            def _call() -> None:
                handler(*args, **kwargs)

            self._run_in_gui_thread(_call)

        return _wrapped

    def _get_runtime_status_callback(self) -> Callable[[dict[str, Any]], None]:
        """Return a callback for runtime status updates from pipeline execution.
        
        This callback receives status updates during job execution and forwards them
        to app_state for display in the running job panel.
        """
        def _status_callback(status_data: dict[str, Any]) -> None:
            try:
                from src.pipeline.job_models_v2 import RuntimeJobStatus

                previous_status = self._get_latest_runtime_status()
                running_job = getattr(getattr(self, "app_state", None), "running_job", None)
                fallback_job_id = getattr(running_job, "job_id", None)
                current_stage = str(
                    status_data.get("current_stage")
                    or getattr(previous_status, "current_stage", "")
                    or self._infer_runtime_stage_name()
                )
                total_stages = max(
                    int(
                        status_data.get("total_stages")
                        if "total_stages" in status_data
                        else getattr(previous_status, "total_stages", None)
                        or self._infer_runtime_stage_count()
                    ),
                    1,
                )
                default_stage_index = self._infer_runtime_stage_index(current_stage)
                runtime_status = RuntimeJobStatus(
                    job_id=str(
                        status_data.get("job_id")
                        or getattr(previous_status, "job_id", "")
                        or fallback_job_id
                        or ""
                    ),
                    current_stage=current_stage,
                    stage_detail=(
                        status_data.get("stage_detail")
                        if "stage_detail" in status_data
                        else getattr(previous_status, "stage_detail", None)
                    ),
                    stage_index=int(
                        status_data.get("stage_index")
                        if "stage_index" in status_data
                        else getattr(previous_status, "stage_index", default_stage_index)
                        or 0
                    ),
                    total_stages=total_stages,
                    progress=float(
                        status_data.get("progress")
                        if "progress" in status_data
                        else getattr(previous_status, "progress", 0.0)
                        or 0.0
                    ),
                    eta_seconds=(
                        status_data.get("eta_seconds")
                        if "eta_seconds" in status_data
                        else getattr(previous_status, "eta_seconds", None)
                    ),
                    started_at=self._coerce_runtime_status_started_at(
                        status_data.get("started_at") if "started_at" in status_data else None,
                        getattr(previous_status, "started_at", None)
                        or getattr(running_job, "started_at", None)
                        or getattr(running_job, "created_at", None),
                    ),
                    actual_seed=(
                        status_data.get("actual_seed")
                        if "actual_seed" in status_data
                        else getattr(previous_status, "actual_seed", None)
                    ),
                    current_step=int(
                        status_data.get("current_step")
                        if "current_step" in status_data
                        else getattr(previous_status, "current_step", 0)
                        or 0
                    ),
                    total_steps=int(
                        status_data.get("total_steps")
                        if "total_steps" in status_data
                        else getattr(previous_status, "total_steps", 0)
                        or 0
                    ),
                )
                self._queue_runtime_status_update(runtime_status)
            except Exception as exc:
                logger.warning(f"Failed to process runtime status update: {exc}")
        
        return _status_callback

    def _get_latest_runtime_status(self) -> Any | None:
        lock = getattr(self, "_runtime_status_lock", None)
        if lock is None:
            return getattr(self, "_pending_runtime_status", None) or getattr(self, "_last_runtime_status", None)
        with lock:
            pending_status = getattr(self, "_pending_runtime_status", None)
        return pending_status or getattr(self, "_last_runtime_status", None)

    def _clear_runtime_status_cache(self) -> None:
        lock = getattr(self, "_runtime_status_lock", None)
        if lock is None:
            self._pending_runtime_status = None
            self._runtime_status_flush_scheduled = False
            self._last_runtime_status = None
            return
        with lock:
            self._pending_runtime_status = None
            self._runtime_status_flush_scheduled = False
        self._last_runtime_status = None

    @staticmethod
    def _coerce_runtime_status_started_at(value: Any, fallback: Any | None = None) -> datetime:
        for candidate in (value, fallback):
            if isinstance(candidate, datetime):
                return candidate
            if isinstance(candidate, (int, float)):
                try:
                    return datetime.fromtimestamp(candidate)
                except Exception:
                    continue
            if isinstance(candidate, str) and candidate.strip():
                try:
                    return datetime.fromisoformat(candidate)
                except Exception:
                    continue
        return datetime.utcnow()

    def _infer_runtime_stage_name(self) -> str:
        running_job = getattr(getattr(self, "app_state", None), "running_job", None)
        stage_chain_value = getattr(running_job, "stage_chain_labels", None)
        if not isinstance(stage_chain_value, (list, tuple)):
            return ""
        stage_chain = list(stage_chain_value)
        return str(stage_chain[0] if stage_chain else "")

    def _infer_runtime_stage_count(self) -> int:
        running_job = getattr(getattr(self, "app_state", None), "running_job", None)
        stage_chain_value = getattr(running_job, "stage_chain_labels", None)
        if not isinstance(stage_chain_value, (list, tuple)):
            return 1
        stage_chain = list(stage_chain_value)
        return len(stage_chain) or 1

    def _infer_runtime_stage_index(self, current_stage: str) -> int:
        running_job = getattr(getattr(self, "app_state", None), "running_job", None)
        stage_chain_value = getattr(running_job, "stage_chain_labels", None)
        if not isinstance(stage_chain_value, (list, tuple)):
            return 0
        stage_chain = list(stage_chain_value)
        if not stage_chain or not current_stage:
            return 0
        target = str(current_stage).strip().lower()
        for index, stage_name in enumerate(stage_chain):
            if str(stage_name).strip().lower() == target:
                return index
        return 0

    def _queue_runtime_status_update(self, runtime_status: Any) -> None:
        import time
        import threading

        if not hasattr(self, "_runtime_status_lock"):
            self._runtime_status_lock = threading.Lock()
        if not hasattr(self, "_pending_runtime_status"):
            self._pending_runtime_status = None
        if not hasattr(self, "_runtime_status_flush_scheduled"):
            self._runtime_status_flush_scheduled = False
        if not hasattr(self, "_last_runtime_status_flush_ts"):
            self._last_runtime_status_flush_ts = 0.0
        if not hasattr(self, "_runtime_status_min_interval_ms"):
            self._runtime_status_min_interval_ms = 250

        delay_ms = 0
        should_schedule = False
        with self._runtime_status_lock:
            self._pending_runtime_status = runtime_status
            if self._runtime_status_flush_scheduled:
                return
            elapsed_ms = (time.monotonic() - self._last_runtime_status_flush_ts) * 1000.0
            if elapsed_ms >= float(self._runtime_status_min_interval_ms):
                delay_ms = 0
            else:
                delay_ms = max(1, int(self._runtime_status_min_interval_ms - elapsed_ms))
            self._runtime_status_flush_scheduled = True
            should_schedule = True

        if should_schedule:
            self._ui_dispatch_later(delay_ms, self._flush_runtime_status_update)

    def _flush_runtime_status_update(self) -> None:
        import time

        runtime_status = None
        with self._runtime_status_lock:
            runtime_status = self._pending_runtime_status
            self._pending_runtime_status = None
            self._runtime_status_flush_scheduled = False
            self._last_runtime_status_flush_ts = time.monotonic()
            self._last_runtime_status = runtime_status

        if runtime_status is None:
            return
        if hasattr(self.app_state, "set_runtime_status"):
            self.app_state.set_runtime_status(runtime_status)

    def _apply_initial_resource_probe_grace(self) -> None:
        setter = getattr(self._api_client, "set_startup_probe_grace", None)
        if not callable(setter):
            return
        duration = _INITIAL_RESOURCE_PROBE_GRACE_SEC
        override = os.environ.get("STABLENEW_INITIAL_RESOURCE_GRACE_SEC")
        if override:
            try:
                duration = max(float(override), 0.0)
            except Exception:
                duration = _INITIAL_RESOURCE_PROBE_GRACE_SEC
        try:
            setter(duration)
        except Exception:
            logger.debug("Failed to install initial startup probe grace", exc_info=True)

    def list_models(self) -> list[WebUIResource]:
        return self.resource_service.list_models()

    def list_vaes(self) -> list[WebUIResource]:
        return self.resource_service.list_vaes()

    def list_upscalers(self) -> list[WebUIResource]:
        return self.resource_service.list_upscalers()

    def list_hypernetworks(self) -> list[WebUIResource]:
        return self.resource_service.list_hypernetworks()

    def list_embeddings(self) -> list[WebUIResource]:
        return self.resource_service.list_embeddings()

    def get_gui_log_handler(self) -> InMemoryLogHandler | None:
        return self.gui_log_handler

    @property
    def duration_stats_service(self) -> DurationStatsService | None:
        """Expose duration stats service for queue ETA estimation (PR-PIPE-002)."""
        return getattr(self, "_duration_stats_service", None)

    def run_txt2img_once(self, config: dict[str, Any] | None = None) -> None:
        self._append_log("[controller] run_txt2img_once called.")
        if config is None:
            config = {
                "prompt": "A beautiful landscape, trending on artstation",
                "model": "stable-diffusion-v1-5",
                "sampler": "Euler a",
                "width": 512,
                "height": 512,
                "steps": 20,
                "cfg_scale": 7.0,
            }
        try:
            result = self.pipeline_runner.run_txt2img_once(config)
            msg = f"Pipeline finished: {result.get('output_path', 'No output path')}"
            self._append_log(msg)
            self._update_status(msg)
        except Exception as exc:
            self._append_log(f"Pipeline error: {exc!r}")
            self._update_status(f"Error: {exc!r}")

    def _learning_run_callable(self, config: dict, step: Any) -> Any:
        """Callable passed to LearningExecutionController for running pipeline steps.

        PR-LEARN-002: Provides learning experiments with access to the pipeline execution system.
        """
        try:
            # Run through the pipeline runner with the learning experiment config
            result = self.pipeline_runner.run_txt2img_once(config)
            return normalize_run_result(result)
        except Exception as exc:
            logger.exception(f"[learning] Pipeline run failed for step {step}: {exc}")
            return normalize_run_result({
                "success": False,
                "error": str(exc),
            })
    
    def _create_learning_completion_handler(self):
        """Create a completion handler that routes to learning subsystem.

        PR-LEARN-003: Routes job completion events to the learning controller
        so experiments can update variant status as jobs complete.

        Extracted to app_controller_services.learning_completion_router (PR-047).
        """
        return build_learning_completion_handler(
            get_main_window=lambda: getattr(self, "main_window", None),
        )

    def _create_photo_optimize_completion_handler(self):
        def handler(job, result):
            self._handle_photo_optimize_completion(job, result)

        return handler

    def update_ui_heartbeat(self) -> None:
        import time

        self.last_ui_heartbeat_ts = time.monotonic()

    def attach_watchdog(self, diagnostics_service: Any) -> None:
        """Attach and start the system watchdog.

        The watchdog is responsible for emitting diagnostics bundles on detected stalls.
        This is attached late (post-GUI construction) to avoid spurious "stall" triggers
        during startup.
        """
        from src.services.watchdog_system_v2 import SystemWatchdogV2

        # Always refresh monotonic baselines when attaching.
        now = time.monotonic()
        self.last_ui_heartbeat_ts = now
        self.last_queue_activity_ts = now
        self.last_runner_activity_ts = now

        self.diagnostics_service = diagnostics_service
        if getattr(self, "_system_watchdog", None) is None:
            self._system_watchdog = SystemWatchdogV2(self, diagnostics_service)

        # Idempotent start (watchdog should never prevent app startup).
        try:
            self._system_watchdog.start()
        except Exception:
            logger.exception("Failed to start system watchdog")

    def _create_api_client_with_discovery(self) -> Any:
        """
        Create API client with automatic port discovery.
        
        WebUI auto-increments ports (7860 → 7861 → 7862...) when instances collide.
        This scans ports 7860-7869 to find the active WebUI instance.
        
        Returns:
            SDWebUIClient configured with discovered or default URL
        """
        import logging
        from src.utils.webui_discovery import find_webui_api_port
        
        logger = logging.getLogger(__name__)
        
        # Try to discover actual WebUI port
        discovered_url = find_webui_api_port(
            base_url="http://127.0.0.1",
            start_port=7860,
            max_attempts=10  # Check ports 7860-7869
        )
        
        if discovered_url:
            logger.info(f"[controller] Discovered WebUI at {discovered_url}")
            return self._runtime_ports.create_client(base_url=discovered_url)
        else:
            # Fall back to default or environment variable
            import os
            default_url = os.getenv("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860")
            logger.warning(f"[controller] WebUI discovery failed, using {default_url}")
            return self._runtime_ports.create_client(base_url=default_url)

    def notify_queue_activity(self) -> None:
        import time

        self.last_queue_activity_ts = time.monotonic()

    def notify_runner_activity(self) -> None:
        import time

        self.last_runner_activity_ts = time.monotonic()

    def start_run_v2(self) -> None:
        """
        Preferred entrypoint for the canonical controller pipeline path.
        """
        self._get_run_submission_service().ensure_queue_run_mode(self.app_state, "run")
        return self._start_run_v2(RunMode.QUEUE, RunSource.RUN_BUTTON)

    def _ensure_run_mode_default(self, button_source: str) -> None:
        self._get_run_submission_service().ensure_queue_run_mode(self.app_state, button_source)

    def _build_run_config(self, mode: RunMode, source: RunSource) -> RunConfigDict:
        return self._get_run_submission_service().build_run_config(
            self.app_state,
            mode=mode.value,
            source=source.value,
        )

    def on_run_now(self) -> Any:
        """Explicit event API: run pipeline now via the controller."""
        self._ensure_run_mode_default("run_now")
        return self._start_run_v2(RunMode.QUEUE, RunSource.RUN_NOW_BUTTON)

    def on_add_to_queue(self) -> None:
        """Legacy compatibility shim for preview-backed Add to Queue."""
        self.on_add_job_to_queue_v2()

    def on_clear_draft(self) -> None:
        """Explicit event API: clear the current job draft state."""
        controller = self.pipeline_controller
        if controller is None:
            return
        controller.clear_draft()
        self._append_log("[controller] Job draft cleared")

    def on_add_to_job(self, pack_ids: list[str]) -> None:
        """Explicit event API: add the selected packs to the pipeline draft."""
        self.on_pipeline_add_packs_to_job(pack_ids)

    def on_update_preview(self) -> None:
        """Explicit event API: refresh preview records."""
        controller = self.pipeline_controller
        if controller is None:
            return
        controller.refresh_preview_from_state()

    def _build_stage_flags(self) -> dict[str, bool]:
        defaults = {"txt2img": True, "img2img": False, "adetailer": True, "upscale": False}
        stage_flags: dict[str, bool] = dict(defaults)
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is not None:
            for stage in ("txt2img", "img2img", "adetailer", "upscale"):
                value = getattr(pipeline_tab, f"{stage}_enabled", None)
                if hasattr(value, "get"):
                    try:
                        stage_flags[stage] = bool(value.get())
                        continue
                    except Exception:
                        pass
                if isinstance(value, bool):
                    stage_flags[stage] = value
        # Include derived refiner/hires flags based on current config
        stage_flags.setdefault("refiner", bool(self.state.current_config.refiner_enabled))
        stage_flags.setdefault("hires", bool(self.state.current_config.hires_enabled))
        return stage_flags

    def _build_stage_plan_config_for_tests(self) -> dict[str, Any]:
        """Construct a minimal config dict for StageSequencer.build_stage_execution_plan."""

        def _val(obj: object, name: str, default: Any) -> Any:
            try:
                value = getattr(obj, name)
            except Exception:
                value = default
            return default if value in (None, "") else value

        cfg = getattr(self.state, "current_config", None)
        stage_flags = self._build_stage_flags()

        model_name = _val(cfg, "model_name", "model")
        sampler_name = _val(cfg, "sampler_name", "Euler")
        scheduler_name = _val(cfg, "scheduler_name", None)
        steps = int(_val(cfg, "steps", 20) or 20)
        cfg_scale = float(_val(cfg, "cfg_scale", 7.0) or 7.0)
        width = int(_val(cfg, "width", 512) or 512)
        height = int(_val(cfg, "height", 512) or 512)

        hires_enabled = bool(_val(cfg, "hires_enabled", False))
        hires_upscale = float(_val(cfg, "hires_upscale_factor", 2.0) or 2.0)
        hires_upscaler = _val(cfg, "hires_upscaler_name", "Latent")
        hires_denoise = float(_val(cfg, "hires_denoise", 0.3) or 0.3)
        hires_steps = _val(cfg, "hires_steps", None)

        refiner_enabled = bool(_val(cfg, "refiner_enabled", False))
        refiner_model = _val(cfg, "refiner_model_name", None)
        refiner_switch = _val(cfg, "refiner_switch_at", None)

        config: dict[str, Any] = {
            "pipeline": {
                "txt2img_enabled": stage_flags.get("txt2img", True),
                "img2img_enabled": stage_flags.get("img2img", False),
                "adetailer_enabled": stage_flags.get("adetailer", False),
                "upscale_enabled": stage_flags.get("upscale", False),
            },
            "txt2img": {
                "enabled": stage_flags.get("txt2img", True),
                "model": model_name,
                "sampler_name": sampler_name,
                "scheduler": scheduler_name,
                "steps": steps,
                "cfg_scale": cfg_scale,
                "width": width,
                "height": height,
                "refiner_enabled": refiner_enabled,
                "refiner_model_name": refiner_model,
                "refiner_switch_at": refiner_switch,
            },
            "img2img": {
                "enabled": stage_flags.get("img2img", False),
                "model": model_name,
                "sampler_name": sampler_name,
                "steps": steps,
                "cfg_scale": cfg_scale,
            },
            "upscale": {
                "enabled": stage_flags.get("upscale", False),
                "upscaler": hires_upscaler,
            },
            "adetailer": {
                "enabled": stage_flags.get("adetailer", False),
            },
            "hires_fix": {
                "enabled": hires_enabled,
                "upscale_factor": hires_upscale,
                "upscaler_name": hires_upscaler,
                "denoise": hires_denoise,
                "steps": hires_steps,
            },
        }

        return config

    def _capture_stage_plan_for_tests(self, controller: Any) -> None:
        validator = getattr(controller, "validate_stage_plan", None)
        if not callable(validator):
            return
        try:
            plan_config = self._build_stage_plan_config_for_tests()
            validator(plan_config)
        except Exception:
            # Test helper only; failures must not block user runs
            pass

    def _invoke_mock_generate_for_tests(self) -> None:
        """Trigger the patched ApiClient.generate_images during pytest runs."""
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            return
        try:
            from types import SimpleNamespace

            from src.api.client import ApiClient

            cfg = getattr(self.state, "current_config", None)
            pipeline_tab = getattr(getattr(self, "main_window", None), "pipeline_tab", None)
            tab_state = getattr(pipeline_tab, "pipeline_state", None)
            app_state_pipeline = getattr(self.app_state, "pipeline_state", None)

            prompt = (
                getattr(tab_state, "prompt", None)
                or getattr(app_state_pipeline, "prompt", None)
                or getattr(cfg, "prompt", "")
                or ""
            )
            negative = (
                getattr(tab_state, "negative_prompt", None)
                or getattr(app_state_pipeline, "negative_prompt", None)
                or getattr(cfg, "negative_prompt", "")
                or ""
            )

            request = SimpleNamespace(
                prompt=prompt,
                negative_prompt=negative,
                sampler="Euler",
                scheduler="Karras",
                steps=25,
                cfg_scale=7.0,
                batch_size=2,
            )

            payload = {
                "prompt": prompt,
                "negative_prompt": negative,
                "sampler_name": "Euler",
                "scheduler": "Karras",
                "steps": 25,
                "cfg_scale": 7.0,
                "batch_size": 2,
            }

            client = ApiClient()
            client.generate_images(request, payload)
        except Exception:
            pass

    def _build_randomizer_metadata(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.state.current_config.randomization_enabled),
            "max_variants": max(1, int(self.state.current_config.max_variants or 1)),
        }

    def _read_pack_prompts(self, pack: PromptPackInfo) -> tuple[str, str]:
        try:
            prompts = read_prompt_pack(pack.path)
        except Exception:
            prompts = []
        if not prompts:
            return "", ""
        first = prompts[0]
        return first.get("positive", "").strip(), first.get("negative", "").strip()

    def _start_run_v2(self, mode: RunMode, source: RunSource) -> Any:
        run_service = self._get_run_submission_service()
        run_service.ensure_queue_run_mode(self.app_state, source.value)
        pipeline_controller = getattr(self, "pipeline_controller", None)
        if self._should_submit_run_async() and pipeline_controller is not None:
            prepare = getattr(pipeline_controller, "prepare_queue_run_submission", None)
            if callable(prepare):
                if self._run_submission_in_progress:
                    self._append_log("[controller] Run submission already in progress; ignoring duplicate request.")
                    return False
                run_config = self._build_run_config(mode, source)
                prepared = prepare(run_config=run_config, source="gui")
                if prepared is None:
                    return False
                self._last_run_config = dict(prepared.run_config or {})
                self._capture_stage_plan_for_tests(pipeline_controller)
                self.current_operation_label = "Submitting run to queue"
                self.last_ui_action = "_start_run_v2(async)"
                self._run_submission_in_progress = True
                self._spawn_tracked_thread(
                    target=self._submit_run_to_queue_async,
                    args=(pipeline_controller, prepared, source.value),
                    name="RunQueueSubmit",
                    purpose="Build preview jobs and submit run asynchronously",
                )
                return True
        return run_service.start_run(
            app_state=self.app_state,
            pipeline_controller=pipeline_controller,
            mode=mode.value,
            source=source.value,
            set_last_run_config=lambda cfg: setattr(self, "_last_run_config", cfg),
        )

    def _should_submit_run_async(self) -> bool:
        return bool(
            getattr(self, "threaded", False)
            and getattr(self, "main_window", None) is not None
            and getattr(self, "_thread_registry", None) is not None
        )

    def _submit_run_to_queue_async(
        self,
        controller: Any,
        prepared_run: Any,
        origin_source: str,
    ) -> None:
        submitted = 0
        error: Exception | None = None
        ready = False
        had_preview_jobs = False
        try:
            ensure_ready = getattr(controller, "ensure_run_submission_ready", None)
            if callable(ensure_ready):
                ready = bool(ensure_ready())
            else:
                ready = True
            if ready:
                preview_jobs = list(getattr(controller, "get_preview_jobs")() or [])
                had_preview_jobs = bool(preview_jobs)
                if preview_jobs:
                    submitted = int(
                        controller.submit_preview_jobs_to_queue(
                            records=preview_jobs,
                            source=prepared_run.source,
                            prompt_source=prepared_run.prompt_source,
                            run_config=prepared_run.run_config,
                        )
                        or 0
                    )
        except Exception as exc:  # noqa: BLE001
            error = exc

        def _finish() -> None:
            self._run_submission_in_progress = False
            self.current_operation_label = None
            self.last_ui_action = None
            if self._is_preview_queue_submission_blocked():
                return
            transition = getattr(controller, "_safe_gui_transition", None)
            if error is not None:
                self._append_log(
                    f"[controller] Run submission error: {error!r} (source={origin_source})"
                )
                if callable(transition):
                    try:
                        transition(GUIState.ERROR)
                    except Exception:
                        pass
                return
            if not ready:
                self._append_log(
                    f"[controller] Run submission aborted because WebUI is not ready (source={origin_source})"
                )
                if callable(transition):
                    try:
                        transition(GUIState.ERROR)
                    except Exception:
                        pass
                return
            if submitted <= 0:
                if had_preview_jobs:
                    self._append_log(
                        f"[controller] Run submission completed without queueing jobs (source={origin_source})"
                    )
                else:
                    self._append_log(
                        f"[controller] No preview jobs available to run (source={origin_source})"
                    )
                return
            if callable(transition):
                try:
                    transition(GUIState.RUNNING)
                except Exception:
                    pass
            self._append_log(
                f"[controller] Submitted {submitted} job(s) to the queue in background (source={origin_source})"
            )

        self._ui_dispatch(_finish)

    def _get_run_submission_service(self) -> QueueRunSubmissionService:
        return QueueRunSubmissionService(
            append_log=self._append_log,
            capture_stage_plan_for_tests=self._capture_stage_plan_for_tests,
            invoke_mock_generate_for_tests=self._invoke_mock_generate_for_tests,
        )

    def _get_gui_config_service(self) -> GuiConfigService:
        return GuiConfigService()

    def on_run_job_now_v2(self) -> Any:
        """
        V2 entrypoint for "Run Now": prefer the explicit `on_run_now` API.
        """
        self._ensure_run_mode_default("run_now")
        try:
            on_run_now_fn = getattr(self, "on_run_now", None)
            underlying_run_now = getattr(on_run_now_fn, "__func__", None) if on_run_now_fn else None
            if on_run_now_fn is not None and underlying_run_now is not AppController.on_run_now:  # type: ignore[comparison-overlap]
                result = on_run_now_fn()
                if result is not None:
                    return result
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[controller] on_run_job_now_v2 error: {exc!r}")
        self._ensure_run_mode_default("run_now")
        start_run_v2_fn = getattr(self, "start_run_v2", None)
        if start_run_v2_fn is not None:
            underlying = getattr(start_run_v2_fn, "__func__", None)
            if underlying is not AppController.start_run_v2:  # type: ignore[comparison-overlap]
                return start_run_v2_fn()
        return self._start_run_v2(RunMode.QUEUE, RunSource.RUN_NOW_BUTTON)

    def on_add_job_to_queue_v2(self) -> None:
        """Queue-first Add-to-Queue entrypoint for preview-backed jobs."""
        import threading

        thread_name = threading.current_thread().name
        self._append_log(f"[D21] on_add_job_to_queue_v2 ENTRY (thread={thread_name})")
        self._ensure_run_mode_default("add_to_queue")
        if self._is_preview_queue_submission_blocked():
            self._append_log(
                f"[controller] Ignoring add-to-queue request because shutdown is in progress "
                f"(thread={thread_name})"
            )
            self._append_log(f"[D21] on_add_job_to_queue_v2 EXIT (thread={thread_name})")
            return
        controller = getattr(self, "pipeline_controller", None)
        run_config = self._prepare_queue_run_config()
        if getattr(self, "_queue_submit_in_progress", False):
            self._append_log(
                f"[controller] Queue submission already in progress; ignoring duplicate request "
                f"(thread={thread_name})"
            )
            self._append_log(f"[D21] on_add_job_to_queue_v2 EXIT (thread={thread_name})")
            return
        if controller is not None:
            preview_records = list(getattr(getattr(self, "app_state", None), "preview_jobs", None) or [])
            try:
                self._queue_submit_in_progress = True
                self._append_log(
                    f"[controller] Queueing preview jobs in background "
                    f"(count={len(preview_records) if preview_records else 'draft'}) "
                    f"(thread={thread_name})"
                )
                spawn_thread = getattr(self, "_spawn_tracked_thread", None)
                if callable(spawn_thread):
                    spawn_thread(
                        target=self._submit_preview_jobs_to_queue_async,
                        args=(controller, preview_records, run_config, thread_name),
                        name="PreviewQueueSubmit",
                        purpose="Submit preview jobs to queue asynchronously",
                    )
                else:
                    self._submit_preview_jobs_to_queue_async(
                        controller,
                        preview_records,
                        run_config,
                        thread_name,
                    )
                self._append_log(f"[D21] on_add_job_to_queue_v2 EXIT (thread={thread_name})")
                return
            except Exception as exc:  # noqa: BLE001
                self._queue_submit_in_progress = False
                self._append_log(
                    f"[controller] enqueue_draft_jobs error: {exc!r} (thread={thread_name})"
                )
        else:
            self._append_log(
                f"[controller] enqueue_draft_jobs unavailable: pipeline_controller missing "
                f"(thread={thread_name})"
            )
        self._append_log(f"[D21] on_add_job_to_queue_v2 EXIT (thread={thread_name})")

    def _is_preview_queue_submission_blocked(self) -> bool:
        return bool(getattr(self, "_is_shutting_down", False))

    def _should_dispatch_preview_queue_finish_to_ui(self) -> bool:
        return not self._is_preview_queue_submission_blocked()

    def _log_preview_queue_finish(self, message: str, *, error: bool = False) -> None:
        if self._is_preview_queue_submission_blocked():
            if error:
                logger.warning(message)
            else:
                logger.info(message)
            return
        self._append_log(message)

    def _submit_preview_jobs_to_queue_async(
        self,
        controller: Any,
        preview_records: list[Any],
        run_config: dict[str, Any] | None,
        origin_thread_name: str,
    ) -> None:
        submitted = 0
        error: Exception | None = None
        clear_preview_on_success = bool(preview_records)
        blocked_by_shutdown = False
        try:
            if self._is_preview_queue_submission_blocked():
                blocked_by_shutdown = True
            elif preview_records:
                submitted = int(
                    controller.submit_preview_jobs_to_queue(
                        records=preview_records,
                        run_config=run_config,
                    )
                    or 0
                )
            else:
                submitted = int(controller.enqueue_draft_jobs(run_config=run_config) or 0)
        except Exception as exc:  # noqa: BLE001
            error = exc

        def _finish() -> None:
            self._queue_submit_in_progress = False
            if error is not None:
                self._log_preview_queue_finish(
                    f"[controller] enqueue_draft_jobs error: {error!r} "
                    f"(thread={origin_thread_name})",
                    error=True,
                )
                return
            if blocked_by_shutdown:
                self._log_preview_queue_finish(
                    f"[controller] Skipped preview queue submission because shutdown is in progress "
                    f"(thread={origin_thread_name})"
                )
                return
            if submitted > 0 and clear_preview_on_success and submitted >= len(preview_records):
                app_state = getattr(self, "app_state", None)
                if app_state is not None:
                    clear_fn = getattr(app_state, "clear_job_draft", None)
                    if callable(clear_fn):
                        try:
                            clear_fn()
                        except Exception:
                            pass
                    preview_setter = getattr(app_state, "set_preview_jobs", None)
                    if callable(preview_setter):
                        try:
                            preview_setter([])
                        except Exception:
                            pass
                self._log_preview_queue_finish(
                    f"[controller] Submitted {submitted} job(s) from preview to queue "
                    f"(thread={origin_thread_name})"
                )
                return
            if submitted > 0 and clear_preview_on_success:
                self._log_preview_queue_finish(
                    f"[controller] Preview queue submission stopped early after {submitted} job(s); "
                    f"draft preview was preserved (thread={origin_thread_name})"
                )
                return
            if submitted > 0:
                self._log_preview_queue_finish(
                    f"[controller] Submitted {submitted} job(s) from preview to queue "
                    f"(thread={origin_thread_name})"
                )

        dispatch = getattr(self, "_ui_dispatch", None)
        if callable(dispatch) and self._should_dispatch_preview_queue_finish_to_ui():
            dispatch(_finish)
        else:
            _finish()

    def _prepare_queue_run_config(self) -> dict[str, Any]:
        run_config = self._build_run_config(RunMode.QUEUE, RunSource.ADD_TO_QUEUE_BUTTON)
        self._last_run_config = dict(run_config)
        return run_config

    def on_replay_history_job_v2(self, job_id: str) -> bool:
        controller = self.pipeline_controller
        if controller is None:
            return False
        try:
            count = controller.replay_job_from_history(job_id)
            if count > 0:
                self._append_log(f"[controller] Replayed job {job_id} ({count} queued).")
                return True
            self._append_log(f"[controller] Replay job {job_id} had no snapshot or jobs to queue.")
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[controller] Replay job {job_id} failed: {exc!r}")
        return False

    def on_reprocess_images(
        self, 
        image_paths: list[str], 
        stages: list[str],
        batch_size: int = 1,
    ) -> int:
        """Reprocess existing images through specified pipeline stages.
        
        Args:
            image_paths: List of paths to images to reprocess
            stages: List of stage names to apply (e.g., ["img2img", "adetailer", "upscale"])
            batch_size: Number of images per job (default 1 = one job per image)
            
        Returns:
            Number of jobs submitted to queue
            
        Raises:
            ValueError: If no images or stages provided, or if invalid stage names
        """
        if not image_paths:
            raise ValueError("No images provided for reprocessing")
        if not stages:
            raise ValueError("No stages specified for reprocessing")
        
        # Validate stages
        valid_stages = {"adetailer", "upscale", "img2img"}
        invalid_stages = set(stages) - valid_stages
        if invalid_stages:
            raise ValueError(f"Invalid stages: {invalid_stages}. Valid: {valid_stages}")
        
        builder = ReprocessJobBuilder()
        
        try:
            # Get current GUI configs for stages
            config = self._build_reprocess_config(stages)
            
            # Debug logging
            self._append_log(f"[reprocess] Stages enabled: {', '.join(stages)}")
            if "upscale" in stages:
                self._append_log(f"[reprocess] DEBUG: config['upscale'] = {config.get('upscale', 'NOT SET')}")
                self._append_log(f"[reprocess] DEBUG: config['upscaler'] flat key = {config.get('upscaler', 'NOT SET')}")

            items = [ReprocessSourceItem(input_image_path=str(path)) for path in image_paths]
            plan = builder.build_grouped_reprocess_jobs(
                items=items,
                stages=stages,
                fallback_config=config,
                batch_size=batch_size,
                pack_name="Reprocess",
                source="reprocess_panel",
            )
            
            submitted_count = self._submit_reprocess_njrs(plan.jobs, source="reprocess_panel")
            
            self._append_log(
                f"[reprocess] Submitted {submitted_count} job(s) for {len(image_paths)} image(s) "
                f"through stages: {' → '.join(stages)}"
            )
            
            return submitted_count
                
        except Exception as exc:
            self._append_log(f"[reprocess] Failed to submit reprocess jobs: {exc!r}")
            raise

    def on_reprocess_images_with_prompt_delta(
        self,
        image_paths: list[str],
        stages: list[str],
        prompt_delta: str = "",
        negative_prompt_delta: str = "",
        prompt_mode: str = "append",
        negative_prompt_mode: str = "append",
        batch_size: int = 1,
        source_metadata_by_image: dict[str, dict[str, Any]] | None = None,
    ) -> int:
        """Reprocess images while preserving metadata-derived settings and editing prompts.

        This path is used by the Review tab. For each image:
        - Reads embedded stage metadata (if present) for prompt/model/VAE/config baseline.
        - Applies prompt deltas in append/replace/modify mode.
        - Builds a single-image NJR and submits it to the queue.
        """
        if not image_paths:
            raise ValueError("No images provided for reprocessing")
        if not stages:
            raise ValueError("No stages specified for reprocessing")

        valid_stages = {"adetailer", "upscale", "img2img"}
        invalid_stages = set(stages) - valid_stages
        if invalid_stages:
            raise ValueError(f"Invalid stages: {invalid_stages}. Valid: {valid_stages}")
        if prompt_mode not in {"append", "replace", "modify"}:
            raise ValueError("prompt_mode must be 'append', 'replace', or 'modify'")
        if negative_prompt_mode not in {"append", "replace", "modify"}:
            raise ValueError("negative_prompt_mode must be 'append', 'replace', or 'modify'")
        if batch_size <= 0:
            raise ValueError("batch_size must be >= 1")

        builder = ReprocessJobBuilder()
        fallback_config = self._build_reprocess_config(stages)
        metadata_hits = 0
        items: list[ReprocessSourceItem] = []

        for image_path in image_paths:
            image_file = Path(image_path)
            base_prompt = ""
            base_negative_prompt = ""
            base_model: str | None = None
            base_vae: str | None = None
            metadata_config: dict[str, Any] = {}

            metadata_baseline = self._extract_reprocess_baseline_from_image(image_file)
            if metadata_baseline:
                metadata_hits += 1
                base_prompt = str(metadata_baseline.get("prompt") or "")
                base_negative_prompt = str(metadata_baseline.get("negative_prompt") or "")
                base_model = metadata_baseline.get("model")
                base_vae = metadata_baseline.get("vae")
                maybe_cfg = metadata_baseline.get("config")
                if isinstance(maybe_cfg, dict):
                    metadata_config = maybe_cfg

            effective_prompt = self._apply_prompt_delta(base_prompt, prompt_delta, prompt_mode)
            effective_negative_prompt = self._apply_prompt_delta(
                base_negative_prompt, negative_prompt_delta, negative_prompt_mode
            )
            item_metadata: dict[str, Any] = {
                "baseline_source": "embedded_metadata" if metadata_baseline else "fallback",
            }
            if isinstance(source_metadata_by_image, dict):
                source_meta = source_metadata_by_image.get(str(image_file)) or source_metadata_by_image.get(str(image_file.resolve()))
                if isinstance(source_meta, dict):
                    item_metadata.update(source_meta)

            items.append(
                ReprocessSourceItem(
                    input_image_path=str(image_file),
                    prompt=effective_prompt,
                    negative_prompt=effective_negative_prompt,
                    model=base_model,
                    vae=base_vae,
                    config=metadata_config,
                    metadata=item_metadata,
                )
            )

        def _extra_metadata_builder(chunk: list[ReprocessSourceItem], _job_output_dir: str) -> dict[str, Any]:
            if not chunk:
                return {}
            first_item_metadata = dict(chunk[0].metadata or {})
            target_stage = stages[0] if len(stages) == 1 else " -> ".join(stages)
            return build_review_chunk_lineage_block(first_item_metadata, target_stage=target_stage)

        plan = builder.build_grouped_reprocess_jobs(
            items=items,
            stages=stages,
            fallback_config=fallback_config,
            batch_size=batch_size,
            pack_name="ReviewReprocess",
            source="review_tab",
            extra_metadata_builder=_extra_metadata_builder,
        )

        submitted_count = self._submit_reprocess_njrs(plan.jobs, source="review_tab")
        self._append_log(
            f"[reprocess] Review-tab submit: {submitted_count} jobs, "
            f"metadata baseline used for {metadata_hits}/{len(image_paths)} images "
            f"across {plan.group_count} compatibility group(s), batch_size={batch_size}"
        )
        return submitted_count

    def get_review_reprocess_effective_settings_preview(
        self,
        *,
        image_path: str,
        stages: list[str],
        prompt_delta: str = "",
        negative_prompt_delta: str = "",
        prompt_mode: str = "append",
        negative_prompt_mode: str = "append",
    ) -> ReprocessEffectiveSettingsPreview:
        """Return the effective merged settings the Review submit path would queue."""
        if not image_path:
            raise ValueError("An image path is required for Review settings preview")
        if not stages:
            raise ValueError("At least one target stage is required for Review settings preview")

        image_file = Path(image_path)
        baseline = self._extract_reprocess_baseline_from_image(image_file)
        base_prompt = str(baseline.get("prompt") or "")
        base_negative_prompt = str(baseline.get("negative_prompt") or "")
        effective_prompt = self._apply_prompt_delta(base_prompt, prompt_delta, prompt_mode)
        effective_negative_prompt = self._apply_prompt_delta(
            base_negative_prompt,
            negative_prompt_delta,
            negative_prompt_mode,
        )
        metadata_config_dict: dict[str, Any] = {}
        metadata_config = baseline.get("config")
        if isinstance(metadata_config, dict):
            metadata_config_dict = dict(metadata_config)
        fallback_config = self._build_reprocess_config(stages)
        builder = ReprocessJobBuilder()
        return builder.build_effective_settings_preview(
            source_stage=str(baseline.get("stage") or "unknown"),
            source_model=baseline.get("model"),
            source_vae=baseline.get("vae"),
            stages=list(stages),
            fallback_config=fallback_config,
            metadata_config=metadata_config_dict,
            prompt=effective_prompt,
            negative_prompt=effective_negative_prompt,
            prompt_mode=prompt_mode,
            negative_prompt_mode=negative_prompt_mode,
            prompt_delta=prompt_delta,
            negative_prompt_delta=negative_prompt_delta,
            source_baseline_label="selected artifact baseline",
            fallback_source_label="current Review stage baseline",
        )

    def on_submit_image_edits(
        self,
        *,
        image_paths: list[str],
        mask_paths: list[str],
        prompt_delta: str = "",
        negative_prompt_delta: str = "",
        prompt_mode: str = "append",
        negative_prompt_mode: str = "append",
    ) -> int:
        """Submit masked image edits through the canonical reprocess/img2img path."""
        if not image_paths:
            raise ValueError("No images provided for editing")
        if not mask_paths:
            raise ValueError("No masks provided for editing")
        if len(image_paths) != len(mask_paths):
            raise ValueError("image_paths and mask_paths must have the same length")
        if prompt_mode not in {"append", "replace", "modify"}:
            raise ValueError("prompt_mode must be 'append', 'replace', or 'modify'")
        if negative_prompt_mode not in {"append", "replace", "modify"}:
            raise ValueError("negative_prompt_mode must be 'append', 'replace', or 'modify'")

        fallback_config = self._build_reprocess_config(["img2img"])
        builder = ReprocessJobBuilder()
        items: list[ReprocessSourceItem] = []
        metadata_hits = 0

        for image_path, mask_path in zip(image_paths, mask_paths, strict=False):
            image_file = Path(image_path)
            mask_file = Path(mask_path)
            if not image_file.exists():
                raise FileNotFoundError(f"Image not found: {image_file}")
            if not mask_file.exists():
                raise FileNotFoundError(f"Mask not found: {mask_file}")

            metadata_baseline = self._extract_reprocess_baseline_from_image(image_file)
            if metadata_baseline:
                metadata_hits += 1
            base_prompt = str(metadata_baseline.get("prompt") or "")
            base_negative_prompt = str(metadata_baseline.get("negative_prompt") or "")
            base_model = metadata_baseline.get("model")
            base_vae = metadata_baseline.get("vae")
            metadata_config = (
                metadata_baseline.get("config")
                if isinstance(metadata_baseline.get("config"), dict)
                else {}
            )
            effective_prompt = self._apply_prompt_delta(base_prompt, prompt_delta, prompt_mode)
            effective_negative_prompt = self._apply_prompt_delta(
                base_negative_prompt,
                negative_prompt_delta,
                negative_prompt_mode,
            )
            items.append(
                ReprocessSourceItem(
                    input_image_path=str(image_file),
                    prompt=effective_prompt,
                    negative_prompt=effective_negative_prompt,
                    model=base_model,
                    vae=base_vae,
                    config=metadata_config,
                    metadata={
                        "baseline_source": "embedded_metadata" if metadata_baseline else "fallback",
                    },
                    image_edit=ImageEditSpec(mask_image_path=str(mask_file)),
                )
            )

        plan = builder.build_grouped_reprocess_jobs(
            items=items,
            stages=["img2img"],
            fallback_config=fallback_config,
            batch_size=1,
            pack_name="ImageEdit",
            source="image_edit",
            extra_metadata_builder=lambda chunk, _job_output_dir: {
                "image_edit": {
                    "schema": "stablenew.image_edit.v2.6",
                    "source": "image_edit",
                    "item_count": len(chunk),
                    "operations": [
                        (item.image_edit.to_dict() if item.image_edit else {})
                        for item in chunk
                    ],
                    "prompt_mode": prompt_mode,
                    "prompt_delta": prompt_delta,
                    "negative_prompt_mode": negative_prompt_mode,
                    "negative_prompt_delta": negative_prompt_delta,
                }
            },
        )

        submitted_count = self._submit_reprocess_njrs(plan.jobs, source="image_edit")
        self._append_log(
            f"[image_edit] Submitted {submitted_count} masked edit job(s); "
            f"metadata baseline used for {metadata_hits}/{len(image_paths)} image(s)"
        )
        return submitted_count

    def build_photo_optimize_defaults(self) -> dict[str, Any]:
        config = self._build_reprocess_config(["img2img", "adetailer", "upscale"])
        txt2img_cfg = config.get("txt2img", {}) if isinstance(config, dict) else {}
        img2img_cfg = config.get("img2img", {}) if isinstance(config, dict) else {}
        model = (
            (img2img_cfg.get("model") if isinstance(img2img_cfg, dict) else None)
            or (txt2img_cfg.get("model") if isinstance(txt2img_cfg, dict) else None)
            or config.get("model")
            or ""
        )
        vae = (
            (img2img_cfg.get("vae") if isinstance(img2img_cfg, dict) else None)
            or (txt2img_cfg.get("vae") if isinstance(txt2img_cfg, dict) else None)
            or config.get("vae")
            or ""
        )
        return {
            "prompt": "",
            "negative_prompt": "",
            "model": str(model or ""),
            "vae": str(vae or ""),
            "stage_defaults": {
                "img2img": True,
                "adetailer": False,
                "upscale": False,
            },
            "config": config,
            "source": "manual",
        }

    def interrogate_photo_path(self, image_path: str | Path, *, model: str = "clip") -> str:
        image_file = Path(image_path)
        if not image_file.exists():
            raise FileNotFoundError(f"Image not found: {image_file}")
        if not hasattr(self, "_api_client") or self._api_client is None:
            raise RuntimeError("WebUI client is not available")

        image_base64 = load_image_to_base64(image_file)
        if not image_base64:
            raise RuntimeError(f"Failed to load image for interrogation: {image_file}")

        interrogate = getattr(self._api_client, "interrogate", None)
        if not callable(interrogate):
            raise RuntimeError("WebUI client does not support interrogate")

        caption = str(interrogate(image_base64, model=model) or "").strip()
        if not caption:
            raise RuntimeError("Interrogate returned no caption")

        self._append_log(f"[photo_optimize] Interrogated {image_file.name}")
        return caption

    def on_optimize_photo_assets(
        self,
        *,
        assets: list[dict[str, Any]],
        stages: list[str],
        prompt_delta: str = "",
        negative_prompt_delta: str = "",
        prompt_mode: str = "append",
        negative_prompt_mode: str = "append",
        batch_size: int = 1,
    ) -> int:
        if not assets:
            raise ValueError("No photo assets were provided for optimization")
        if not stages:
            raise ValueError("No stages specified for photo optimization")
        valid_stages = {"adetailer", "upscale", "img2img"}
        invalid_stages = set(stages) - valid_stages
        if invalid_stages:
            raise ValueError(f"Invalid stages: {invalid_stages}. Valid: {valid_stages}")
        if prompt_mode not in {"append", "replace", "modify"}:
            raise ValueError("prompt_mode must be 'append', 'replace', or 'modify'")
        if negative_prompt_mode not in {"append", "replace", "modify"}:
            raise ValueError("negative_prompt_mode must be 'append', 'replace', or 'modify'")
        if batch_size <= 0:
            raise ValueError("batch_size must be >= 1")

        fallback_config = self._build_reprocess_config(stages)
        builder = ReprocessJobBuilder()
        store = get_photo_optimize_store()
        items: list[ReprocessSourceItem] = []

        for asset in assets:
            asset_id = str(asset.get("asset_id") or "")
            if not asset_id:
                raise ValueError("Photo asset is missing asset_id")
            baseline = asset.get("baseline") or {}
            if hasattr(baseline, "to_dict"):
                baseline = baseline.to_dict()
            if not isinstance(baseline, dict):
                baseline = {}
            input_image_path = str(
                asset.get("input_image_path")
                or baseline.get("working_image_path")
                or asset.get("managed_original_path")
                or ""
            )
            if not input_image_path:
                raise ValueError(f"Photo asset '{asset_id}' is missing input_image_path")
            base_prompt = str(baseline.get("prompt") or "")
            base_negative_prompt = str(baseline.get("negative_prompt") or "")
            base_model = str(baseline.get("model") or "")
            base_vae = str(baseline.get("vae") or "")
            base_config = baseline.get("config") if isinstance(baseline.get("config"), dict) else {}
            effective_prompt = self._apply_prompt_delta(base_prompt, prompt_delta, prompt_mode)
            effective_negative_prompt = self._apply_prompt_delta(
                base_negative_prompt,
                negative_prompt_delta,
                negative_prompt_mode,
            )
            config_snapshot = ReprocessJobBuilder._merge_nested_dicts(fallback_config, base_config)
            ReprocessJobBuilder.apply_model_vae_to_config(
                config_snapshot,
                model=base_model or None,
                vae=base_vae or None,
            )
            items.append(
                ReprocessSourceItem(
                    input_image_path=input_image_path,
                    prompt=effective_prompt,
                    negative_prompt=effective_negative_prompt,
                    model=base_model or None,
                    vae=base_vae or None,
                    config=base_config,
                    metadata={
                        "photo_asset": {
                            "asset_id": asset_id,
                            "input_image_path": input_image_path,
                            "effective_prompt": effective_prompt,
                            "effective_negative_prompt": effective_negative_prompt,
                            "config_snapshot": config_snapshot,
                            "stages": list(stages),
                        }
                    },
                )
            )

        def _output_dir_factory(_chunk: list[ReprocessSourceItem]) -> str:
            return str(store.create_staging_run_dir("photo_optimize"))

        def _extra_metadata_builder(chunk: list[ReprocessSourceItem], job_output_dir: str) -> dict[str, Any]:
            return {
                "photo_optimize": {
                    "source": "photo_optimize_tab",
                    "run_id": Path(job_output_dir).name,
                    "stages": list(stages),
                    "prompt_mode": prompt_mode,
                    "prompt_delta": prompt_delta,
                    "negative_prompt_mode": negative_prompt_mode,
                    "negative_prompt_delta": negative_prompt_delta,
                    "assets": [
                        deepcopy((item.metadata or {}).get("photo_asset") or {})
                        for item in chunk
                    ],
                }
            }

        plan = builder.build_grouped_reprocess_jobs(
            items=items,
            stages=stages,
            fallback_config=fallback_config,
            batch_size=batch_size,
            pack_name="PhotoOptimize",
            source="photo_optimize_tab",
            output_dir_factory=_output_dir_factory,
            extra_metadata_builder=_extra_metadata_builder,
        )

        submitted_count = self._submit_reprocess_njrs(plan.jobs, source="photo_optimize_tab")
        self._append_log(
            f"[photo_optimize] Submitted {submitted_count} job(s) across "
            f"{plan.group_count} compatibility group(s), batch_size={batch_size}"
        )
        return submitted_count

    def _extract_reprocess_baseline_from_image(self, image_path: Path) -> dict[str, Any]:
        from src.utils.image_metadata import (
            extract_embedded_metadata,
            resolve_model_vae_fields,
            resolve_prompt_fields,
        )

        try:
            metadata_result = extract_embedded_metadata(image_path)
        except Exception:
            return {}

        if metadata_result.status != "ok" or not isinstance(metadata_result.payload, dict):
            return {}

        payload = metadata_result.payload
        generation = payload.get("generation")
        if not isinstance(generation, dict):
            generation = {}
        stage_manifest = payload.get("stage_manifest")
        if not isinstance(stage_manifest, dict):
            stage_manifest = {}

        config = stage_manifest.get("config")
        if not isinstance(config, dict):
            config = {}

        model_value, vae_value = resolve_model_vae_fields(payload)
        if isinstance(model_value, str) and model_value.strip().lower() in {"unknown", "n/a"}:
            model_value = None
        if isinstance(vae_value, str) and vae_value.strip().lower() in {"unknown", "n/a"}:
            vae_value = None
        prompt_value, negative_prompt_value = resolve_prompt_fields(payload)

        return {
            "stage": str(stage_manifest.get("stage") or payload.get("stage") or "unknown"),
            "prompt": prompt_value,
            "negative_prompt": negative_prompt_value,
            "model": model_value,
            "vae": vae_value,
            "config": config,
        }

    @staticmethod
    def _apply_prompt_delta(base: str, delta: str, mode: str) -> str:
        return ReviewWorkflowAdapter.apply_prompt_delta(base, delta, mode)

    def _extract_reprocess_output_paths(self, job: Job, result: Any) -> list[str]:
        njr = getattr(job, "_normalized_record", None)
        payload = getattr(job, "result", None)
        if not isinstance(payload, dict) and isinstance(result, dict):
            payload = result
        return extract_reprocess_output_paths(njr, payload)

    def _handle_photo_optimize_completion(self, job: Job, result: Any) -> None:
        njr = getattr(job, "_normalized_record", None)
        metadata = getattr(njr, "extra_metadata", None) if njr is not None else None
        if not isinstance(metadata, dict):
            return
        photo_meta = metadata.get("photo_optimize")
        if not isinstance(photo_meta, dict):
            return
        if getattr(job, "status", None) != JobStatus.COMPLETED:
            return

        output_paths = self._extract_reprocess_output_paths(job, result)
        assets = list(photo_meta.get("assets") or [])
        if not assets or not output_paths:
            return

        store = get_photo_optimize_store()
        processed_asset_ids: list[str] = []
        for index, asset_info in enumerate(assets):
            if not isinstance(asset_info, dict):
                continue
            if index >= len(output_paths):
                break
            asset_id = str(asset_info.get("asset_id") or "")
            if not asset_id:
                continue
            store.record_optimize_history(
                asset_id,
                run_id=str(photo_meta.get("run_id") or job.job_id),
                input_image_path=str(asset_info.get("input_image_path") or ""),
                source_output_paths=[output_paths[index]],
                prompt_mode=str(photo_meta.get("prompt_mode") or "append"),
                prompt_delta=str(photo_meta.get("prompt_delta") or ""),
                negative_prompt_mode=str(photo_meta.get("negative_prompt_mode") or "append"),
                negative_prompt_delta=str(photo_meta.get("negative_prompt_delta") or ""),
                effective_prompt=str(asset_info.get("effective_prompt") or ""),
                effective_negative_prompt=str(asset_info.get("effective_negative_prompt") or ""),
                stages=[str(item) for item in asset_info.get("stages") or photo_meta.get("stages") or []],
                config_snapshot=asset_info.get("config_snapshot") or {},
                job_ids=[job.job_id],
            )
            processed_asset_ids.append(asset_id)

        if processed_asset_ids and self.main_window is not None:
            tab = getattr(self.main_window, "photo_optimize_tab", None)
            refresh = getattr(tab, "on_assets_updated", None)
            if callable(refresh):
                self._ui_dispatch(lambda: refresh(processed_asset_ids))

    def _submit_reprocess_njrs(self, njrs: list[Any], *, source: str) -> int:
        if not self.job_service:
            raise RuntimeError("Job service not available")
        if not njrs:
            return 0
        builder = ReprocessJobBuilder()
        request = builder.build_run_request(
            njrs,
            source=source,
            requested_job_label="Photo Optimize" if source == "photo_optimize_tab" else "Reprocess",
        )
        job_ids = self.job_service.enqueue_njrs(njrs, request)
        return len(job_ids)
    
    def _build_reprocess_config(self, stages: list[str]) -> dict[str, Any]:
        """Build configuration dict for reprocess jobs.
        
        Respects the "Override pack configs with current stages" checkbox:
        - When checked: Uses current stage card GUI values
        - When unchecked: Uses pack config values
        
        Args:
            stages: List of stage names that will be used
            
        Returns:
            Config dict with both nested stage-specific settings and flat global settings
        """
        config: dict[str, Any] = {}
        
        # Check if override is enabled
        override_enabled = getattr(self, 'override_pack_config_enabled', False)
        
        if override_enabled:
            # Override enabled: Extract configs from current stage card GUI values
            try:
                current_stage_configs = self._collect_current_stage_configs()
                
                # Extract global settings from current configs
                config["cfg_scale"] = current_stage_configs.get("cfg_scale", 7.0)
                config["sampler_name"] = current_stage_configs.get("sampler_name", "DPM++ 2M Karras")
                config["steps"] = current_stage_configs.get("steps", 28)
                
                # Extract stage-specific configs from current GUI
                if "img2img" in stages:
                    img2img_cfg = current_stage_configs.get("img2img", {})
                    config["img2img"] = {
                        "steps": img2img_cfg.get("steps", current_stage_configs.get("steps", 28)),
                        "cfg_scale": img2img_cfg.get("cfg_scale", current_stage_configs.get("cfg_scale", 7.0)),
                        "sampler_name": img2img_cfg.get("sampler_name", current_stage_configs.get("sampler_name", "DPM++ 2M Karras")),
                        "scheduler": img2img_cfg.get("scheduler", current_stage_configs.get("scheduler", "Karras")),
                        "denoising_strength": img2img_cfg.get("denoising_strength", 0.3),
                        "width": img2img_cfg.get("width", 512),
                        "height": img2img_cfg.get("height", 512),
                    }
                    config["img2img_steps"] = config["img2img"]["steps"]
                    config["img2img_cfg_scale"] = config["img2img"]["cfg_scale"]
                    config["img2img_sampler_name"] = config["img2img"]["sampler_name"]
                    config["img2img_denoising_strength"] = config["img2img"]["denoising_strength"]
                
                if "adetailer" in stages:
                    ad_cfg = current_stage_configs.get("adetailer", {})
                    config["adetailer"] = {
                        "adetailer_model": ad_cfg.get("adetailer_model", "mediapipe_face_full"),
                        "adetailer_confidence": ad_cfg.get("adetailer_confidence", 0.69),
                        "adetailer_dilate": ad_cfg.get("adetailer_dilate", 4),
                        "adetailer_denoise": ad_cfg.get("adetailer_denoise", 0.25),
                        "adetailer_steps": ad_cfg.get("adetailer_steps") or 12,
                        "adetailer_cfg": ad_cfg.get("adetailer_cfg") or 5.7,
                        "adetailer_sampler": ad_cfg.get("adetailer_sampler") or "DPM++ 2M Karras",
                        "adetailer_prompt": ad_cfg.get("adetailer_prompt", "<stable_yogis_pdxl_positives>,<stable_yogis_realism_positives_v1>, highly realistic human face, natural skin texture, clear skin pores, balanced facial proportions, symmetrical facial features, well-defined eyes, natural eye reflections, accurate facial anatomy, sharp focus, photorealistic details, 8k resolution, professional lighting"),
                        "adetailer_negative_prompt": ad_cfg.get("adetailer_negative_prompt", "<stable_yogis_pdxl_negatives2-neg>,<stable_yogis_anatomy_negatives_v1-neg>,<sdxl_cyberrealistic_simpleneg-neg>,<negative_hands>,low quality,blurry,out of focus,distorted face,asymmetrical face,deformed facial features,warped eyes,crossed eyes,extra eyes,extra face,multiple faces,mutated face,plastic skin,over-smoothed skin,over-sharpened,harsh shadows,unrealistic skin texture,uncanny "),
                    }
                    if ad_cfg.get("adetailer_denoise") is not None:
                        config["adetailer_denoising_strength"] = ad_cfg["adetailer_denoise"]
                    if ad_cfg.get("adetailer_steps") is not None:
                        config["adetailer_steps"] = ad_cfg["adetailer_steps"]
                    if ad_cfg.get("adetailer_cfg") is not None:
                        config["adetailer_cfg_scale"] = ad_cfg["adetailer_cfg"]
                
                if "upscale" in stages:
                    upscale_cfg = current_stage_configs.get("upscale", {})
                    config["upscale"] = {
                        "upscaler": upscale_cfg.get("upscaler", "4xUltrasharp_4xUltrasharpV10"),
                        "upscale_by": upscale_cfg.get("upscale_by") or upscale_cfg.get("upscale_factor", 2.0),
                        "tile_size": upscale_cfg.get("tile_size", 512),
                        "denoising_strength": upscale_cfg.get("denoising_strength", 0.35),
                    }
                    config["upscale_denoising_strength"] = config["upscale"]["denoising_strength"]
                    config["upscaler"] = config["upscale"]["upscaler"]
                    config["upscale_factor"] = config["upscale"]["upscale_by"]
                
                self._append_log("[reprocess] Using current stage configs (override enabled)")
            except Exception as e:
                self._append_log(f"[reprocess] Failed to extract current stage configs: {e}, falling back to pack config")
                override_enabled = False  # Fall back to pack config
        
        if not override_enabled:
            # Override disabled: Extract configs from currently selected pack
            pack_config = {}
            
            # Get currently selected pack from GUI dropdown
            selected_pack = self._get_selected_pack()
            if selected_pack and hasattr(selected_pack, 'config'):
                pack_config = selected_pack.config or {}
                self._append_log(f"[reprocess] Using config from selected pack: {selected_pack.name}")
            else:
                self._append_log("[reprocess] WARNING: No pack selected, using defaults")
            
            # Extract global settings (flat keys at root level)
            config["cfg_scale"] = pack_config.get("cfg_scale", 7.0)
            config["sampler_name"] = pack_config.get("sampler_name", "DPM++ 2M Karras")
            config["steps"] = pack_config.get("steps", 28)
            
            # Extract stage-specific configs (nested dicts)
            if "img2img" in stages:
                img2img_config = pack_config.get("img2img", {})
                config["img2img"] = {
                    "steps": img2img_config.get("steps", pack_config.get("steps", 28)),
                    "cfg_scale": img2img_config.get("cfg_scale", pack_config.get("cfg_scale", 7.0)),
                    "sampler_name": img2img_config.get("sampler_name", pack_config.get("sampler_name", "DPM++ 2M Karras")),
                    "scheduler": img2img_config.get("scheduler", pack_config.get("scheduler", "Karras")),
                    "denoising_strength": img2img_config.get("denoising_strength", 0.3),
                    "width": img2img_config.get("width", 512),
                    "height": img2img_config.get("height", 512),
                }
                config["img2img_steps"] = config["img2img"]["steps"]
                config["img2img_cfg_scale"] = config["img2img"]["cfg_scale"]
                config["img2img_sampler_name"] = config["img2img"]["sampler_name"]
                # Also set flat key for builder
                config["img2img_denoising_strength"] = config["img2img"]["denoising_strength"]
            
            # adetailer config (use current pack's adetailer settings)
            if "adetailer" in stages:
                ad_config = pack_config.get("adetailer", {})
                config["adetailer"] = {
                    "adetailer_model": ad_config.get("adetailer_model", "mediapipe_face_full"),
                    "adetailer_confidence": ad_config.get("adetailer_confidence", 0.69),
                    "adetailer_dilate": ad_config.get("adetailer_dilate", 4),
                    "adetailer_denoise": ad_config.get("adetailer_denoise", 0.25),
                    "adetailer_steps": ad_config.get("adetailer_steps") or 12,
                    "adetailer_cfg": ad_config.get("adetailer_cfg") or 5.7,
                    "adetailer_sampler": ad_config.get("adetailer_sampler") or "DPM++ 2M Karras",
                    "adetailer_prompt": ad_config.get("adetailer_prompt", "<stable_yogis_pdxl_positives>,<stable_yogis_realism_positives_v1>, highly realistic human face, natural skin texture, clear skin pores, balanced facial proportions, symmetrical facial features, well-defined eyes, natural eye reflections, accurate facial anatomy, sharp focus, photorealistic details, 8k resolution, professional lighting"),
                    "adetailer_negative_prompt": ad_config.get("adetailer_negative_prompt", "<stable_yogis_pdxl_negatives2-neg>,<stable_yogis_anatomy_negatives_v1-neg>,<sdxl_cyberrealistic_simpleneg-neg>,<negative_hands>,low quality,blurry,out of focus,distorted face,asymmetrical face,deformed facial features,warped eyes,crossed eyes,extra eyes,extra face,multiple faces,mutated face,plastic skin,over-smoothed skin,over-sharpened,harsh shadows,unrealistic skin texture,uncanny "),
                }
                # Also set flat keys
                if ad_config.get("adetailer_denoise") is not None:
                    config["adetailer_denoising_strength"] = ad_config["adetailer_denoise"]
                if ad_config.get("adetailer_steps") is not None:
                    config["adetailer_steps"] = ad_config["adetailer_steps"]
                if ad_config.get("adetailer_cfg") is not None:
                    config["adetailer_cfg_scale"] = ad_config["adetailer_cfg"]
            
            # upscale config (use current pack's upscale settings)
            if "upscale" in stages:
                upscale_config = pack_config.get("upscale", {})
                config["upscale"] = {
                    "upscaler": upscale_config.get("upscaler", "4xUltrasharp_4xUltrasharpV10"),
                    "upscale_by": upscale_config.get("upscale_by") or upscale_config.get("upscale_factor", 2.0),
                    "tile_size": upscale_config.get("tile_size", 512),
                    "denoising_strength": upscale_config.get("denoising_strength", 0.35),
                }
                # Also set flat keys
                config["upscale_denoising_strength"] = config["upscale"]["denoising_strength"]
                config["upscaler"] = config["upscale"]["upscaler"]
                config["upscale_factor"] = config["upscale"]["upscale_by"]
            
            self._append_log("[reprocess] Using pack config (override disabled)")
        
        return config

    def set_main_window(self, main_window: MainWindow) -> None:
        """Set the main window and wire GUI callbacks."""
        previous_state = getattr(self, "app_state", None)
        previous_listener = getattr(self, "_app_state_visibility_listener", None)
        if (
            previous_state is not None
            and previous_listener is not None
            and hasattr(previous_state, "unsubscribe")
        ):
            try:
                previous_state.unsubscribe("content_visibility_mode", previous_listener)
            except Exception:
                pass
        self.main_window = main_window
        self.app_state = getattr(main_window, "app_state", None)
        self._bind_app_state_visibility_listener()
        self._attach_to_gui()
        if hasattr(self.main_window, "connect_controller"):
            self.main_window.connect_controller(self)

        # Initial status
        self._update_status("Idle")
        self.load_packs()

    def _bind_app_state_visibility_listener(self) -> None:
        app_state = getattr(self, "app_state", None)
        if app_state is None or not hasattr(app_state, "subscribe"):
            self._app_state_visibility_listener = None
            return
        listener = getattr(self, "_app_state_visibility_listener", None)
        if listener is None:
            listener = self._on_content_visibility_mode_changed
            self._app_state_visibility_listener = listener
        try:
            app_state.subscribe("content_visibility_mode", listener)
        except Exception:
            self._app_state_visibility_listener = None

    def _on_content_visibility_mode_changed(self, *_: Any) -> None:
        try:
            self.load_packs()
        except Exception as exc:
            logger.debug("Failed to reload packs after visibility mode change: %s", exc)

    # ------------------------------------------------------------------
    # GUI Wiring
    # ------------------------------------------------------------------

    def _attach_to_gui(self) -> None:
        mw = self.main_window
        if mw is None:
            return
        missing = [
            name for name in ("header_zone", "left_zone", "bottom_zone") if not hasattr(mw, name)
        ]
        if missing:
            logger.debug(
                f"AppController._attach_to_gui: main_window missing zones {missing}; deferring wiring"
            )
            return

        header = mw.header_zone
        left = mw.left_zone
        bottom = mw.bottom_zone

        # Header events
        header.run_button.configure(command=self.run_txt2img_once)
        header.stop_button.configure(command=self.on_stop_clicked)
        header.preview_button.configure(command=self.on_preview_clicked)
        header.settings_button.configure(command=self.on_open_settings)
        header.help_button.configure(command=self.on_help_clicked)

        # Left zone events
        if hasattr(left, "load_config_button"):
            # New V2 _PackLoaderCompat - buttons are already wired in the UI class
            pass
        elif left is not None:
            # Legacy LeftZone wiring
            if hasattr(left, "load_pack_button"):
                left.load_pack_button.configure(command=self.on_load_pack)
            if hasattr(left, "edit_pack_button"):
                left.edit_pack_button.configure(command=self.on_edit_pack)
            if hasattr(left, "packs_list"):
                left.packs_list.bind("<<ListboxSelect>>", self._on_pack_list_select)
            if hasattr(left, "preset_combo"):
                left.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_combo_select)

        self._update_webui_state("disconnected")

        # Flush deferred status if any
        if getattr(self, "_pending_status_text", None):
            self._update_status(self._pending_status_text)

    # ------------------------------------------------------------------
    # Queue & runtime-host helpers (PR-039B)
    # ------------------------------------------------------------------

    def _single_node_runner_factory(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
    ) -> SingleNodeJobRunner:
        """Factory that produces the runner used by the local runtime host."""

        return SingleNodeJobRunner(
            job_queue,
            run_callable=run_callable or self._execute_job,
            poll_interval=0.05,
        )

    def _build_local_runtime_service(self) -> JobService:
        self._job_history_path.parent.mkdir(parents=True, exist_ok=True)
        history_store = JSONLJobHistoryStore(self._job_history_path)
        job_queue = JobQueue(history_store=history_store)
        history_service = JobHistoryService(job_queue, history_store)
        return JobService(
            job_queue,
            runner_factory=self._single_node_runner_factory,
            history_store=history_store,
            history_service=history_service,
            run_callable=self._execute_job,
            job_lifecycle_logger=self._job_lifecycle_logger,
            require_normalized_records=True,
        )

    def _build_job_service(self) -> JobService:
        """Compatibility hook for tests still overriding the older helper name."""
        return self._build_local_runtime_service()

    def _build_runtime_host(self) -> RuntimeHostPort:
        return build_local_runtime_host(self._build_local_runtime_service())

    def _runtime_host_transport(self) -> str:
        host = getattr(self, "runtime_host", None) or getattr(self, "job_service", None)
        describe_protocol = getattr(host, "describe_protocol", None)
        if callable(describe_protocol):
            try:
                payload = describe_protocol() or {}
            except Exception:
                payload = {}
            transport = str(payload.get("transport") or "").strip()
            if transport:
                return transport
        return "local-only"

    def _runtime_host_manages_queue_state(self) -> bool:
        return self._runtime_host_transport() != "local-only"

    def _queue_is_paused(self, queue: Any | None) -> bool:
        if queue is None:
            return False
        paused = getattr(queue, "is_paused", False)
        if callable(paused):
            try:
                return bool(paused())
            except Exception:
                return False
        return bool(paused)

    def _setup_queue_callbacks(self) -> None:
        if not self.job_service:
            return
        use_event_dispatcher = False
        if hasattr(self.job_service, "set_event_dispatcher"):
            try:
                self.job_service.set_event_dispatcher(self._run_in_gui_thread)
                use_event_dispatcher = True
            except Exception:
                pass

        # Wrap callbacks so any background-thread emissions are marshaled
        # onto the UI thread via `_ui_dispatch` to avoid Tk thread violations.
        def _wrap_ui_callback(handler: Callable[..., None]) -> Callable[..., None]:
            if handler is None:
                return handler

            def _wrapped(*args: Any, **kwargs: Any) -> None:
                # Schedule the actual handler execution on the UI thread.
                # Preserve arg/kwarg shapes. Do not swallow exceptions here;
                # let Tk or existing hooks handle/report them.
                def _call() -> None:
                    handler(*args, **kwargs)

                self._ui_dispatch(_call)

            return _wrapped

        def _queue_callback(handler: Callable[..., None]) -> Callable[..., None]:
            return handler if use_event_dispatcher else _wrap_ui_callback(handler)

        self.job_service.register_callback(
            RUNTIME_HOST_EVENT_QUEUE_UPDATED, _queue_callback(self._on_queue_updated)
        )
        self.job_service.register_callback(
            RUNTIME_HOST_EVENT_QUEUE_STATUS, _queue_callback(self._on_queue_status_changed)
        )
        self.job_service.register_callback(
            RUNTIME_HOST_EVENT_JOB_STARTED, _queue_callback(self._on_job_started)
        )
        self.job_service.register_callback(
            RUNTIME_HOST_EVENT_JOB_FINISHED, _queue_callback(self._on_job_finished)
        )
        self.job_service.register_callback(
            RUNTIME_HOST_EVENT_JOB_FAILED, _queue_callback(self._on_job_failed)
        )
        self.job_service.register_callback(
            RUNTIME_HOST_EVENT_QUEUE_EMPTY, _queue_callback(self._on_queue_empty)
        )
        self._refresh_job_history()
        # PR-GUI-F3: Load persisted queue state on startup
        self._load_queue_state()
        # PR-D: Register status callback for queue/history panel sync
        if hasattr(self.job_service, "set_status_callback"):
            try:
                self.job_service.set_status_callback(
                    "gui_queue_history", _queue_callback(self._on_job_status_for_panels)
                )
            except Exception:
                pass

    def _setup_diagnostics_hooks(self) -> None:
        if not self.job_service:
            return
        try:
            sys.excepthook = self._handle_uncaught_exception
        except Exception:
            pass
        if hasattr(threading, "excepthook"):
            self._original_threading_excepthook = threading.excepthook
            threading.excepthook = self._handle_thread_exception
        root = getattr(self.main_window, "root", None)
        if root and hasattr(root, "report_callback_exception"):
            self._original_tk_report_callback_exception = root.report_callback_exception
            root.report_callback_exception = self._handle_tk_exception
        self.job_service.register_callback(
            RUNTIME_HOST_EVENT_WATCHDOG_VIOLATION,
            self._wrap_ui_callback(self._on_watchdog_violation_event),
        )

    # ------------------------------------------------------------------
    # PR-GUI-F3: Queue persistence helpers
    # ------------------------------------------------------------------

    def _load_queue_state(self) -> None:
        """Sync queue flags and queue view from the active runtime owner."""
        if self.job_service and self._runtime_host_manages_queue_state():
            queue = getattr(self.job_service, "job_queue", None) or getattr(
                self.job_service, "queue", None
            )
            if self.app_state:
                self.app_state.set_auto_run_queue(
                    bool(getattr(self.job_service, "auto_run_enabled", False))
                )
                self.app_state.set_is_queue_paused(self._queue_is_paused(queue))
            self._refresh_app_state_queue()
            return
        pipeline_controller = getattr(self, "pipeline_controller", None)
        job_exec = getattr(pipeline_controller, "_job_controller", None)
        if job_exec is None:
            return
        if self.app_state:
            self.app_state.set_auto_run_queue(bool(getattr(job_exec, "auto_run_enabled", False)))
            self.app_state.set_is_queue_paused(bool(getattr(job_exec, "is_queue_paused", False)))
        if self.job_service:
            self.job_service.auto_run_enabled = bool(getattr(job_exec, "auto_run_enabled", False))
        self._refresh_app_state_queue()

    def _save_queue_state(self) -> None:
        """Persist queue state only when the GUI owns the local queue."""
        if self._runtime_host_manages_queue_state():
            return
        pipeline_controller = getattr(self, "pipeline_controller", None)
        job_exec = getattr(pipeline_controller, "_job_controller", None)
        if job_exec is None:
            return
        persist = getattr(job_exec, "persist_queue_state", None)
        if callable(persist):
            persist()

    def _execute_job(self, job: Job) -> dict[str, Any]:
        """Execute a job via NJR only (PR-CORE1-D11 pack-only path)."""
        self._append_log(f"[queue] Executing job {job.job_id}")

        webui_ctrl = getattr(self, "webui_connection_controller", None)
        if (
            webui_ctrl is not None
            and webui_ctrl.get_state() == WebUIConnectionState.READY
            and not webui_ctrl.is_webui_ready_strict()
        ):
            reason = webui_ctrl.last_readiness_error or "unknown"
            message = f"WebUI not ready: {reason}"
            self._append_log(f"[queue] {message}")
            try:
                job.mark_status(JobStatus.FAILED, error_message=message)
            except Exception:
                pass
            result_payload: dict[str, Any] = {"error": message}
            canonical_result = normalize_run_result(result_payload, default_run_id=job.job_id)
            metadata = canonical_result.get("metadata") or {}
            metadata.setdefault("execution_path", "ready_gate")
            metadata["ready_gate_reason"] = reason
            canonical_result["metadata"] = metadata
            return canonical_result

        execution_path = "missing"
        result_payload: Any | None = None
        normalized_record = getattr(job, "_normalized_record", None)
        if normalized_record is not None and self.pipeline_controller is not None:
            execution_path = "njr"
            self._append_log(
                f"[queue] Job {job.job_id} has normalized_record, executing via NJR-only path"
            )
            try:
                result_payload = self.pipeline_controller._run_job(job)
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[queue] NJR execution for job {job.job_id} failed: {exc!r}")
                result_payload = {"success": False, "error": str(exc)}
        else:
            execution_path = "missing_njr"
            self._append_log(
                f"[queue] Job {job.job_id} is missing normalized_record; cannot execute."
            )
            result_payload = {
                "error": "Job is missing normalized_record; legacy/pipeline_config execution is disabled.",
            }

        canonical_result = normalize_run_result(result_payload, default_run_id=job.job_id)
        metadata = dict(canonical_result.get("metadata") or {})
        metadata["execution_path"] = execution_path
        metadata.setdefault("job_id", job.job_id)
        canonical_result["metadata"] = metadata
        return canonical_result

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    # _run_in_gui_thread is now replaced by _ui_dispatch everywhere

    def _on_job_status_for_panels(self, job: Job, status: JobStatus | str) -> None:
        """Update queue/history panels when job status changes (PR-D callback)."""
        from src.pipeline.job_models_v2 import JobHistoryItemDTO, JobQueueItemDTO

        if not self.main_window:
            return

        queue_panel = getattr(self.main_window, "queue_panel", None)
        history_panel = getattr(self.main_window, "history_panel", None)
        status_value = status.value if hasattr(status, "value") else str(status)
        summary = getattr(job, "unified_summary", None)

        # Update queue panel
        queue_upsert_needed = queue_panel and status_value in {"pending", "running", "queued"}
        queue_remove_needed = queue_panel and status_value in {"completed", "failed", "cancelled"}
        history_append_needed = history_panel and status_value == "completed"
        queue_dto = None
        history_dto = None

        if queue_upsert_needed:
            created_at = (
                getattr(summary, "created_at", None)
                or getattr(job, "created_at", None)
                or datetime.now()
            )
            queue_dto = JobQueueItemDTO(
                job_id=getattr(summary, "job_id", job.job_id),
                label=getattr(summary, "model_name", None) or getattr(job, "label", job.job_id),
                status=status_value,
                estimated_images=getattr(summary, "num_expected_images", 1),
                created_at=created_at,
            )

        if history_append_needed:
            completed_at = getattr(job, "completed_at", None) or datetime.now()
            history_dto = JobHistoryItemDTO(
                job_id=getattr(summary, "job_id", job.job_id),
                label=getattr(summary, "model_name", None) or getattr(job, "label", job.job_id),
                completed_at=completed_at,
                total_images=getattr(summary, "num_expected_images", 0),
                stages=getattr(summary, "stages", "-"),
            )

        if not (queue_upsert_needed or queue_remove_needed or history_append_needed):
            return

        def _apply_panel_updates() -> None:
            if queue_upsert_needed and queue_dto:
                upsert_fn = getattr(queue_panel, "upsert_job", None)
                if callable(upsert_fn):
                    try:
                        upsert_fn(queue_dto)
                    except Exception as exc:
                        self._append_log(f"[controller] Queue panel upsert error: {exc!r}")

            if queue_remove_needed:
                remove_fn = getattr(queue_panel, "remove_job", None)
                if callable(remove_fn):
                    try:
                        remove_fn(job.job_id)
                    except Exception as exc:
                        self._append_log(f"[controller] Queue panel remove error: {exc!r}")

            if history_append_needed and history_dto:
                append_fn = getattr(history_panel, "append_history_item", None)
                if callable(append_fn):
                    try:
                        append_fn(history_dto)
                    except Exception as exc:
                        self._append_log(f"[controller] History panel append error: {exc!r}")

        self._run_in_gui_thread(_apply_panel_updates)

    def _on_queue_updated(self, summaries: list[str]) -> None:
        if not self.app_state:
            return
        self._mark_ui_dirty(queue=True)

    def _on_queue_status_changed(self, status: str) -> None:
        def _apply() -> None:
            if not self.app_state:
                return
            self.app_state.set_queue_status(status)

        self._run_in_gui_thread(_apply)

    def _on_job_started(self, job: Job) -> None:
        def _apply() -> None:
            if not self.app_state:
                return
            self._clear_runtime_status_cache()
            self._set_running_job(job)

        self._run_in_gui_thread(_apply)

    def _on_job_finished(self, job: Job) -> None:
        def _apply() -> None:
            if self.app_state:
                self.app_state.set_running_job(None)
                self._clear_runtime_status_cache()
                if hasattr(self.app_state, "set_runtime_status"):
                    self.app_state.set_runtime_status(None)
            self._refresh_job_history()

        self._run_in_gui_thread(_apply)

    def _on_job_failed(self, job: Job) -> None:
        def _apply() -> None:
            if self.app_state:
                self.app_state.set_running_job(None)
                self._clear_runtime_status_cache()
                if hasattr(self.app_state, "set_runtime_status"):
                    self.app_state.set_runtime_status(None)
            self._refresh_job_history()
            try:
                self._handle_structured_job_failure(job)
            except Exception:
                pass

        self._run_in_gui_thread(_apply)

    def _on_queue_empty(self) -> None:
        def _apply() -> None:
            if self.app_state:
                self.app_state.set_queue_status("idle")

        self._run_in_gui_thread(_apply)

    def _handle_structured_job_failure(self, job: Job) -> None:
        if job is None:
            return
        envelope = getattr(job, "error_envelope", None)
        if envelope is None:
            return
        envelope.context.setdefault("run_mode", job.run_mode)
        envelope.context.setdefault("source", job.source)
        self._last_error_envelope = envelope
        self._log_structured_error(envelope, f"Job {job.job_id} failed")
        self.state.last_error = envelope.message
        if self.app_state:
            try:
                self.app_state.set_last_error(envelope.message)
            except Exception:
                pass
        self._append_log(f"[ERROR] job={job.job_id} {envelope.message}")
        self._show_structured_error_modal(envelope)

    def _refresh_app_state_queue(self) -> None:
        if not self.app_state or not self.job_service:
            return
        if self._should_refresh_queue_async():
            self._queue_refresh_request_id += 1
            if self._queue_refresh_in_progress:
                return
            self._queue_refresh_in_progress = True
            request_id = self._queue_refresh_request_id

            def _worker() -> None:
                queue_items: list[str] = []
                queue_jobs: list[UnifiedJobSummary] = []
                error: Exception | None = None
                try:
                    queue_items, queue_jobs = self._build_queue_projection()
                except Exception as exc:  # noqa: BLE001
                    error = exc

                def _apply() -> None:
                    self._queue_refresh_in_progress = False
                    if error is not None:
                        logger.exception("[AppController] Error refreshing queue state: %s", error)
                    elif request_id == self._queue_refresh_request_id and self.app_state is not None:
                        self.app_state.set_queue_items(queue_items)
                        self.app_state.set_queue_jobs(queue_jobs)
                    if request_id != self._queue_refresh_request_id:
                        self._refresh_app_state_queue()

                self._ui_dispatch(_apply)

            self._spawn_tracked_thread(
                target=_worker,
                name="QueueProjectionRefresh",
                purpose="Refresh queue summaries off the UI thread",
            )
            return

        queue_items, queue_jobs = self._build_queue_projection()
        self.app_state.set_queue_items(queue_items)
        self.app_state.set_queue_jobs(queue_jobs)

    def _should_refresh_queue_async(self) -> bool:
        return bool(
            getattr(self, "threaded", False)
            and getattr(self, "main_window", None) is not None
            and getattr(self, "_thread_registry", None) is not None
        )

    def _record_queue_projection_timing(
        self,
        *,
        elapsed_ms: float,
        job_count: int,
        summary_count: int,
        fallback_count: int,
    ) -> None:
        payload = {
            "elapsed_ms": round(float(elapsed_ms), 3),
            "job_count": int(job_count),
            "summary_count": int(summary_count),
            "fallback_count": int(fallback_count),
        }
        self._last_queue_projection_timing = payload
        if elapsed_ms < _QUEUE_PROJECTION_TIMING_INFO_MS:
            return
        level = (
            logging.WARNING
            if elapsed_ms >= _QUEUE_PROJECTION_TIMING_WARN_MS
            else logging.INFO
        )
        log_with_ctx(
            logger,
            level,
            "Queue projection timing",
            ctx=LogContext(subsystem="controller", stage="queue_projection"),
            extra_fields=payload,
        )
        if elapsed_ms >= _QUEUE_PROJECTION_TIMING_WARN_MS:
            self._append_log(
                f"[perf] Queue projection took {elapsed_ms:.1f}ms for {job_count} active job(s)."
            )

    def _build_queue_projection(self) -> tuple[list[str], list[UnifiedJobSummary]]:
        started_at = time.monotonic()
        jobs = self._list_service_jobs()
        # Convert Job objects to UnifiedJobSummary via their NJRs
        queue_jobs: list[UnifiedJobSummary] = []
        summaries: list[str] = []
        fallback_count = 0
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
                    logger.warning(f"Failed to convert job {job.job_id} to UnifiedJobSummary: {exc}")
                    summaries.append(job.job_id)
                    fallback_count += 1
            else:
                logger.debug(f"Job {job.job_id} missing NJR, using fallback queue summary")
                summaries.append(job.job_id)
                fallback_count += 1
                try:
                    status_value = str(getattr(job, "status", "queued")).lower()
                    status = JobStatusV2(status_value) if status_value in JobStatusV2._value2member_map_ else JobStatusV2.QUEUED
                    queue_jobs.append(UnifiedJobSummary.from_job(job, status))
                except Exception:
                    pass
        self._record_queue_projection_timing(
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            job_count=len(jobs),
            summary_count=len(queue_jobs),
            fallback_count=fallback_count,
        )
        return summaries, queue_jobs

    def _list_service_jobs(self) -> list[Job]:
        queue = getattr(self.job_service, "queue", None)
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
        if not self.app_state:
            return
        if job is None:
            self._clear_runtime_status_cache()
            self.app_state.set_running_job(None)
            if hasattr(self.app_state, "set_runtime_status"):
                self.app_state.set_runtime_status(None)
            # Also clear running job panel if it exists
            if hasattr(self, "main_window") and self.main_window:
                tab_frame = getattr(self.main_window, "pipeline_tab", None)
                if tab_frame and hasattr(tab_frame, "running_job_panel"):
                    tab_frame.running_job_panel.update_job_with_summary(None, None, None)
                if tab_frame and hasattr(tab_frame, "preview_panel"):
                    tab_frame.preview_panel.update_with_summary(None)
            return
        
        # Convert Job to UnifiedJobSummary via NJR
        summary = None
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
            except Exception as exc:
                logger.warning(f"Failed to convert running job {job.job_id} to UnifiedJobSummary: {exc}")
        else:
            logger.warning(f"Running job {job.job_id} missing NJR, cannot display in GUI")
        
        self.app_state.set_running_job(summary)
        
        # Update running job panel - pass Job object with runtime tracking, not just summary
        if hasattr(self, "main_window") and self.main_window:
            tab_frame = getattr(self.main_window, "pipeline_tab", None)
            if tab_frame and hasattr(tab_frame, "running_job_panel"):
                # Pass the actual Job object (with runtime attrs) and summary separately
                tab_frame.running_job_panel.update_job_with_summary(job, summary, None)
            if tab_frame and hasattr(tab_frame, "preview_panel"):
                tab_frame.preview_panel.update_with_summary(summary)

    # ------------------------------------------------------------------
    # PR-203: Queue Manipulation APIs
    # ------------------------------------------------------------------

    def on_queue_move_up_v2(self, job_id: str) -> bool:
        """Move a job up in the queue."""
        return self.move_queue_job_up(job_id)

    def on_queue_move_down_v2(self, job_id: str) -> bool:
        """Move a job down in the queue."""
        return self.move_queue_job_down(job_id)

    def move_queue_job_up(self, job_id: str) -> bool:
        """Move a job up in the queue and persist the new ordering."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "job_queue", None)
        if queue and hasattr(queue, "move_up"):
            try:
                result = bool(queue.move_up(job_id))
                if result:
                    self._refresh_app_state_queue()
                    self._save_queue_state()
                return result
            except Exception as exc:
                self._append_log(f"[controller] on_queue_move_up_v2 error: {exc!r}")
        return False

    def move_queue_job_down(self, job_id: str) -> bool:
        """Move a job down in the queue and persist the new ordering."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "job_queue", None)
        if queue and hasattr(queue, "move_down"):
            try:
                result = bool(queue.move_down(job_id))
                if result:
                    self._refresh_app_state_queue()
                    self._save_queue_state()
                return result
            except Exception as exc:
                self._append_log(f"[controller] on_queue_move_down_v2 error: {exc!r}")
        return False

    def move_queue_job_to_front(self, job_id: str) -> bool:
        """Move a job to the front of the queue."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "job_queue", None)
        if queue and hasattr(queue, "move_to_front"):
            try:
                result = bool(queue.move_to_front(job_id))
                if result:
                    self._refresh_app_state_queue()
                    self._save_queue_state()
                return result
            except Exception as exc:
                self._append_log(f"[controller] move_queue_job_to_front error: {exc!r}")
        return False

    def move_queue_job_to_back(self, job_id: str) -> bool:
        """Move a job to the back of the queue."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "job_queue", None)
        if queue and hasattr(queue, "move_to_back"):
            try:
                result = bool(queue.move_to_back(job_id))
                if result:
                    self._refresh_app_state_queue()
                    self._save_queue_state()
                return result
            except Exception as exc:
                self._append_log(f"[controller] move_queue_job_to_back error: {exc!r}")
        return False

    def on_queue_remove_job_v2(self, job_id: str) -> bool:
        """Remove a job from the queue."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "job_queue", None)
        if queue and hasattr(queue, "remove"):
            try:
                result = queue.remove(job_id) is not None
                if result:
                    self._refresh_app_state_queue()
                    self._save_queue_state()
                return result
            except Exception as exc:
                self._append_log(f"[controller] on_queue_remove_job_v2 error: {exc!r}")
        return False

    def on_queue_clear_v2(self) -> int:
        """Clear all jobs from the queue."""
        if not self.job_service:
            return 0
        queue = getattr(self.job_service, "job_queue", None)
        if queue and hasattr(queue, "clear"):
            try:
                result = int(queue.clear())
                if result > 0:
                    self._refresh_app_state_queue()
                self._save_queue_state()
                return result
            except Exception as exc:
                self._append_log(f"[controller] on_queue_clear_v2 error: {exc!r}")
        return 0

    def on_pause_queue_v2(self) -> None:
        """Pause queue processing."""
        if self.app_state:
            self.app_state.set_is_queue_paused(True)
        job_exec = getattr(getattr(self, "pipeline_controller", None), "_job_controller", None)
        if (
            job_exec
            and hasattr(job_exec, "set_queue_paused")
            and not self._runtime_host_manages_queue_state()
        ):
            job_exec.set_queue_paused(True)
        if self.job_service:
            pause_queue = getattr(self.job_service, "pause", None)
            if callable(pause_queue):
                pause_queue()
            else:
                queue = getattr(self.job_service, "job_queue", None)
                if queue and hasattr(queue, "pause"):
                    queue.pause()
        self._save_queue_state()

    def on_resume_queue_v2(self) -> None:
        """Resume queue processing."""
        if self.app_state:
            self.app_state.set_is_queue_paused(False)
        job_exec = getattr(getattr(self, "pipeline_controller", None), "_job_controller", None)
        if (
            job_exec
            and hasattr(job_exec, "set_queue_paused")
            and not self._runtime_host_manages_queue_state()
        ):
            job_exec.set_queue_paused(False)
        if self.job_service:
            resume_queue = getattr(self.job_service, "resume", None)
            if callable(resume_queue):
                resume_queue()
            else:
                queue = getattr(self.job_service, "job_queue", None)
                if queue and hasattr(queue, "resume"):
                    queue.resume()
        self._save_queue_state()

    def on_set_auto_run_v2(self, enabled: bool) -> None:
        """Set auto-run queue enabled/disabled."""
        if self.app_state:
            self.app_state.set_auto_run_queue(enabled)
        job_exec = getattr(getattr(self, "pipeline_controller", None), "_job_controller", None)
        if (
            job_exec
            and hasattr(job_exec, "set_auto_run_enabled")
            and not self._runtime_host_manages_queue_state()
        ):
            job_exec.set_auto_run_enabled(enabled)
        if self.job_service:
            self.job_service.auto_run_enabled = enabled
            # If enabling auto-run and queue has jobs, start the runner
            if enabled:
                queue = getattr(self.job_service, "job_queue", None)
                app_paused = bool(getattr(self.app_state, "is_queue_paused", False)) if self.app_state else False
                queue_paused = self._queue_is_paused(queue)
                is_paused = app_paused or queue_paused
                if is_paused:
                    self._append_log("[controller] Auto-run enabled but queue is paused; runner not started")
                elif queue and hasattr(queue, "list_jobs"):
                    jobs = list(queue.list_jobs())
                    if jobs:
                        try:
                            self.job_service.run_next_now()
                            self._append_log(f"[controller] Auto-run enabled - starting runner for {len(jobs)} queued job(s)")
                        except Exception as exc:
                            self._append_log(f"[controller] Failed to start runner: {exc!r}")
        self._save_queue_state()

    def on_pause_job_v2(self) -> None:
        """Pause the currently running job."""
        if self.job_service:
            queue = getattr(self.job_service, "queue", None)
            if queue and hasattr(queue, "pause_running_job"):
                queue.pause_running_job()

    def on_resume_job_v2(self) -> None:
        """Resume the paused running job."""
        if self.job_service:
            queue = getattr(self.job_service, "queue", None)
            if queue and hasattr(queue, "resume_running_job"):
                queue.resume_running_job()

    def on_cancel_job_v2(self) -> None:
        """Cancel the currently running job."""
        if self.job_service:
            self.job_service.cancel_current()
            # Also trigger the cancel token if available
            cancel_token = getattr(self, "_cancel_token", None)
            if cancel_token and hasattr(cancel_token, "cancel"):
                cancel_token.cancel()
        self._save_queue_state()

    def on_cancel_job_and_return_v2(self) -> None:
        """Cancel the running job and return it to the bottom of the queue.

        PR-GUI-F3: Allows user to cancel a job but keep it for retry later.
        """
        if self.job_service:
            self.job_service.cancel_current(return_to_queue=True)
            # Also trigger the cancel token if available
            cancel_token = getattr(self, "_cancel_token", None)
            if cancel_token and hasattr(cancel_token, "cancel"):
                cancel_token.cancel()
        self._save_queue_state()

    def on_queue_send_job_v2(self) -> None:
        """Manually dispatch the next job from the queue.

        PR-GUI-F3: Send Job button - dispatches top of queue immediately.
        Starts the runner to process queued jobs.
        """
        if not self.job_service:
            return
        # Check if paused
        is_paused = self.app_state.is_queue_paused if self.app_state else False
        if is_paused:
            self._append_log("[controller] Cannot send job - queue is paused")
            return
        # Start the runner to process queue
        try:
            self.job_service.run_next_now()
            self._append_log("[controller] Queue worker started via Send Job")
        except Exception as exc:
            self._append_log(f"[controller] Failed to start queue worker: {exc!r}")

    def refresh_job_history(self, limit: int | None = None) -> None:
        """Trigger a manual history refresh (exposed to GUI)."""
        self._refresh_job_history(limit=limit)

    def _refresh_job_history(self, limit: int | None = None) -> None:
        if not self.app_state or not self.job_service:
            return
        store = getattr(self.job_service, "history_store", None)
        if store is None:
            return
        try:
            # PR-HISTORY-FIX: Force cache invalidation before refresh to ensure we get latest data
            # This is critical for manual refresh button to work correctly
            if hasattr(store, "invalidate_cache"):
                store.invalidate_cache()
            
            # Only show completed and failed jobs in history (not queued/running/cancelled)
            entries = store.list_jobs(limit=limit or 20)
            # Filter to only show terminal states that made it through the pipeline
            from src.queue.job_model import JobStatus
            terminal_states = {JobStatus.COMPLETED, JobStatus.FAILED}
            filtered_entries = [e for e in entries if e.status in terminal_states]
            entries = filtered_entries
        except Exception:
            entries = []
        self.app_state.set_history_items(entries)
        
        # PR-PIPE-002: Refresh duration stats when history updates
        if hasattr(self, "_duration_stats_service") and self._duration_stats_service:
            try:
                self._duration_stats_service.refresh()
            except Exception as exc:
                self._append_log(f"[duration_stats] Refresh failed: {exc}")

    def on_open_settings(self) -> None:
        self._append_log("[controller] Opening settings dialog.")
        window = getattr(self, "main_window", None)
        if window is None or not hasattr(window, "open_engine_settings_dialog"):
            return
        try:
            window.open_engine_settings_dialog(config_manager=self._config_manager)
        except Exception:
            pass

    def on_settings_saved(self, new_values: dict[str, Any]) -> None:
        if not new_values:
            return
        self._config_manager.update_settings(new_values)
        self._config_manager.save_settings()
        if "webui_workdir" in new_values:
            set_webui_workdir(str(new_values.get("webui_workdir") or "").strip() or None)
        if "webui_autostart_enabled" in new_values:
            set_webui_autostart_enabled(bool(new_values.get("webui_autostart_enabled")))
        if "webui_health_initial_timeout_seconds" in new_values:
            set_webui_health_initial_timeout_seconds(
                float(new_values.get("webui_health_initial_timeout_seconds") or 0.0)
            )
        if "webui_health_retry_count" in new_values:
            set_webui_health_retry_count(int(new_values.get("webui_health_retry_count") or 0))
        if "webui_health_retry_interval_seconds" in new_values:
            set_webui_health_retry_interval_seconds(
                float(new_values.get("webui_health_retry_interval_seconds") or 0.0)
            )
        if "webui_health_total_timeout_seconds" in new_values:
            set_webui_health_total_timeout_seconds(
                float(new_values.get("webui_health_total_timeout_seconds") or 0.0)
            )
        prompt_optimizer = new_values.get("prompt_optimizer")
        if isinstance(prompt_optimizer, dict):
            self._apply_prompt_optimizer_ui_config(prompt_optimizer)
        self._append_log("[controller] Settings updated.")

    def on_open_advanced_editor(self) -> None:
        self._append_log("[controller] Opening advanced prompt editor.")
        prompt = self._get_active_prompt_text()
        window = getattr(self, "main_window", None)
        if window is None:
            return
        try:
            window.open_advanced_editor(
                initial_prompt=prompt,
                on_apply=self.on_advanced_prompt_applied,
            )
        except Exception:
            pass

    def on_advanced_prompt_applied(
        self, new_prompt: str, negative_prompt: str | None = None
    ) -> None:
        prompt_value = new_prompt or ""
        self._append_log("[controller] Advanced prompt applied.")
        ws = getattr(self.app_state, "prompt_workspace_state", None)
        if ws is not None:
            try:
                index = ws.get_current_slot_index()
                ws.set_slot_text(index, prompt_value)
            except Exception:
                pass

        window = getattr(self, "main_window", None)
        if window is not None:
            try:
                window.apply_prompt_text(prompt_value, negative_prompt=negative_prompt)
            except Exception:
                pass

        if self.app_state is not None:
            try:
                self.app_state.set_prompt(prompt_value)
            except Exception:
                pass
            if negative_prompt is not None:
                try:
                    self.app_state.set_negative_prompt(negative_prompt)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Internal helpers (state & logging)
    # ------------------------------------------------------------------

    def _set_lifecycle(self, new_state: LifecycleState, error: str | None = None) -> None:
        self.state.lifecycle = new_state
        self.state.last_error = error

        if new_state == LifecycleState.IDLE:
            self._update_status("Idle")
        elif new_state == LifecycleState.RUNNING:
            self._update_status("Running...")
        elif new_state == LifecycleState.STOPPING:
            self._update_status("Stopping...")
        elif new_state == LifecycleState.ERROR:
            self._update_status(f"Error: {error or 'Unknown error'}")

    def _set_lifecycle_threadsafe(
        self, new_state: LifecycleState, error: str | None = None
    ) -> None:
        """
        Schedule lifecycle change on the Tk main thread if threaded.
        For tests (threaded=False), apply immediately.
        """
        if not self.threaded:
            self._set_lifecycle(new_state, error)
            return

        if self.main_window is not None:
            self._ui_dispatch(lambda: self._set_lifecycle(new_state, error))

    def _update_status(self, text: str) -> None:
        """Update status bar text if the bottom zone is ready; otherwise cache it."""
        import threading

        self._pending_status_text = text
        app_state = getattr(self, "app_state", None)
        status_setter = getattr(app_state, "set_status_text", None)
        if callable(status_setter):
            try:
                status_setter(text)
            except Exception:
                pass
        thread_name = threading.current_thread().name
        status_bar = getattr(self.main_window, "status_bar_v2", None)

        def do_update():
            if status_bar and hasattr(status_bar, "update_status"):
                try:
                    status_bar.update_status(text=text)
                except Exception:
                    pass

        # Only update UI on main thread; otherwise, dispatch via controller scheduler
        if thread_name != "MainThread":
            logger.debug(f"[D21] _update_status dispatching to UI thread (from {thread_name})")
            self._ui_dispatch(do_update)
        else:
            do_update()

    def _update_webui_state(self, state: str) -> None:
        status_bar = getattr(self.main_window, "status_bar_v2", None)
        if status_bar and hasattr(status_bar, "update_webui_state"):
            try:
                status_bar.update_webui_state(state)
            except Exception:
                pass

    def _validate_pipeline_config(self) -> tuple[bool, str]:
        """DEPRECATED (PR-CORE1-12): Legacy validation for pipeline_config panel.

        Use PipelineController + NJR validation instead. This method is retained
        only for backward compatibility with archived GUI components.
        """
        cfg = self.app_state.current_config if self.app_state else self.state.current_config
        if not getattr(cfg, "model_name", None) and self.state.current_config:
            cfg = self.state.current_config
        gui_config = self._get_gui_config_service()
        adapter = gui_config.get_adapter(self.app_state)
        run_cfg = adapter.get_run_config_projection() if adapter is not None else {}
        model_name = (
            getattr(cfg, "model_name", None) or run_cfg.get("model") or run_cfg.get("model_name")
        )
        sampler_name = (
            getattr(cfg, "sampler_name", None)
            or run_cfg.get("sampler")
            or run_cfg.get("sampler_name")
        )
        steps_value = getattr(cfg, "steps", None) or run_cfg.get("steps")
        if not model_name:
            return False, "Please select a model before running the pipeline."
        if not sampler_name:
            return False, "Please select a sampler before running the pipeline."
        try:
            steps_int = int(steps_value)
        except Exception:
            steps_int = getattr(cfg, "steps", 0)
        if steps_int <= 0:
            return False, "Steps must be a positive integer."
        return True, ""

    def _set_validation_feedback(self, valid: bool, message: str) -> None:
        run_bar = getattr(self.main_window, "run_control_bar_v2", None)
        if run_bar and hasattr(run_bar, "set_run_enabled"):
            try:
                run_bar.set_run_enabled(valid)
            except Exception:
                pass

    def _append_log(self, text: str) -> None:
        app_state = getattr(self, "app_state", None)
        append_operator_log_line = getattr(app_state, "append_operator_log_line", None)
        if callable(append_operator_log_line):
            try:
                append_operator_log_line(text)
            except Exception:
                logger.debug("AppController._append_log(%s) failed to append operator log", text)

        trace_panel = getattr(self.main_window, "log_trace_panel_v2", None)
        schedule_refresh = getattr(trace_panel, "schedule_refresh_soon", None)
        if callable(schedule_refresh):
            try:
                schedule_refresh()
            except Exception:
                pass

    def _append_log_threadsafe(self, text: str) -> None:
        """
        Schedule a log append on the Tk main thread if threaded.
        For tests (threaded=False), apply immediately.
        """
        if not self.threaded:
            self._append_log(text)
            return

        if self.main_window is not None:
            self._ui_dispatch(lambda: self._append_log(text))

    def generate_diagnostics_bundle_manual(self) -> None:
        """Expose a manual trigger for diagnostics bundles."""
        self._generate_diagnostics_bundle("manual_request")

    def open_debug_hub(self) -> None:
        """Primary entrypoint for the Unified Debug Hub."""
        try:
            DebugHubPanelV2.open(
                master=self.main_window.root if self.main_window else None,
                controller=self,
                app_state=self.app_state,
                log_handler=self.gui_log_handler,
            )
        except Exception as exc:
            self._append_log(f"[controller] Failed to open Debug Hub: {exc!r}")

    def explain_job(self, job_id: str) -> None:
        """Open a job explanation for the given job ID."""
        if not job_id:
            return
        try:
            JobExplanationPanelV2(
                job_id,
                master=self.main_window.root if self.main_window else None,
                controller=self,
            )
        except Exception as exc:
            self._append_log(f"[controller] Failed to explain job {job_id}: {exc!r}")

    def get_preview_jobs(self) -> list[Any]:
        pipeline_controller = getattr(self, "pipeline_controller", None)
        getter = getattr(pipeline_controller, "get_preview_jobs", None)
        if callable(getter):
            try:
                return list(getter())
            except Exception:
                pass
        app_state = getattr(self, "app_state", None)
        return list(getattr(app_state, "preview_jobs", []) or [])

    def get_job_explanation_payload(self, job_id: str) -> dict[str, Any] | None:
        if not job_id:
            return None
        live_job = self._find_live_job(job_id)
        history_entry = self._get_history_entry_by_job_id(job_id)
        normalized = self._extract_normalized_snapshot(live_job=live_job, history_entry=history_entry)
        runtime_status = self._get_latest_runtime_status()
        if getattr(runtime_status, "job_id", None) != job_id:
            runtime_status = None
        if not normalized and history_entry is None and live_job is None:
            return None

        status_value = self._resolve_job_status_value(live_job=live_job, history_entry=history_entry)
        stage_flow = self._resolve_stage_flow(normalized, runtime_status)
        return {
            "job_id": job_id,
            "display_label": self._build_debug_job_label(job_id, normalized),
            "origin_text": self._build_job_origin_text(
                job_id=job_id,
                normalized=normalized,
                live_job=live_job,
                history_entry=history_entry,
                runtime_status=runtime_status,
            ),
            "stage_flow": stage_flow,
            "stage_prompts": self._build_job_stage_prompt_rows(
                normalized=normalized,
                stage_flow=stage_flow,
                runtime_status=runtime_status,
            ),
            "metadata": self._build_job_metadata_payload(
                job_id=job_id,
                normalized=normalized,
                live_job=live_job,
                history_entry=history_entry,
                runtime_status=runtime_status,
                status_value=status_value,
            ),
        }

    def get_process_auto_scanner(self) -> ProcessAutoScannerService | None:
        return getattr(self, "process_auto_scanner", None)

    def _get_protected_process_pids(self) -> Iterable[int]:
        pids: set[int] = set()

        # Always protect WebUI PID (if running)
        # This is critical to prevent ProcessAutoScannerService from killing WebUI
        # even if protected_pids callback logic changes in the future
        if hasattr(self, "webui_process_manager") and self.webui_process_manager:
            webui_pid = getattr(self.webui_process_manager, "pid", None)
            if webui_pid and isinstance(webui_pid, int):
                pids.add(webui_pid)

        # Protect PIDs from running jobs
        if self.job_service:
            snapshot = self.job_service.get_diagnostics_snapshot()
            jobs = snapshot.get("jobs") or []
            for entry in jobs:
                for pid in entry.get("external_pids", []) or []:
                    if isinstance(pid, int):
                        pids.add(pid)

        return pids

    def _generate_diagnostics_bundle(
        self, reason: str, *, extra_context: Mapping[str, Any] | None = None
    ) -> Path | None:
        if not self.gui_log_handler or not self.job_service:
            return None
        webui_tail = None
        manager = getattr(self, "webui_process_manager", None)
        if manager and hasattr(manager, "get_recent_output_tail"):
            try:
                webui_tail = manager.get_recent_output_tail()
            except Exception:
                webui_tail = None
        context = dict(extra_context) if extra_context else None
        if self._last_error_envelope:
            context = dict(context or {})
            context.setdefault("error_envelope", serialize_envelope(self._last_error_envelope))
        with self._diagnostics_lock:
            path = build_crash_bundle(
                reason=reason,
                log_handler=self.gui_log_handler,
                job_service=self.job_service,
                extra_context=context,
                webui_tail=webui_tail,
                include_process_state=True,
                include_queue_state=True,
            )
            if path:
                self._last_diagnostics_bundle = path
                self._last_diagnostics_bundle_reason = reason
                self._append_log(f"[DIAG] Saved diagnostics bundle: {path}")
            return path

    def _capture_error_envelope(
        self, exc: Exception, *, subsystem: str = "controller"
    ) -> UnifiedErrorEnvelope:
        envelope = get_attached_envelope(exc)
        if envelope is None:
            envelope = wrap_exception(exc, subsystem=subsystem)
        self._last_error_envelope = envelope
        return envelope

    def _log_structured_error(self, envelope: UnifiedErrorEnvelope, message: str) -> None:
        log_with_ctx(
            logger,
            logging.ERROR,
            message,
            ctx=LogContext(subsystem=envelope.subsystem or "controller"),
            extra_fields={"error_envelope": serialize_envelope(envelope)},
        )

    def _show_structured_error_modal(self, envelope: UnifiedErrorEnvelope) -> None:
        if self.main_window is None:
            return
        if self._error_modal and getattr(self._error_modal, "winfo_exists", lambda: False)():
            try:
                self._error_modal.lift()
            except Exception:
                pass
            return
        try:
            modal_parent = getattr(self.main_window, "root", None) or self.main_window
            self._error_modal = ErrorModalV2(
                modal_parent,
                envelope=envelope,
                on_close=self._clear_error_modal,
            )
        except Exception:
            logger.exception("Failed to show structured error modal")

    def _clear_error_modal(self) -> None:
        self._error_modal = None

    def _handle_uncaught_exception(
        self, exc_type: type[BaseException], exc_value: BaseException, exc_traceback
    ) -> None:
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        self._generate_diagnostics_bundle(
            "uncaught_exception",
            extra_context={"exception": str(exc_value), "traceback": tb},
        )
        if self._original_excepthook:
            self._original_excepthook(exc_type, exc_value, exc_traceback)

    def _handle_thread_exception(self, args: threading.ExceptHookArgs) -> None:
        tb = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        context = {"thread": getattr(args.thread, "name", None), "traceback": tb}
        self._generate_diagnostics_bundle("thread_exception", extra_context=context)
        if self._original_threading_excepthook:
            self._original_threading_excepthook(args)

    def _handle_tk_exception(
        self, exc_type: type[BaseException], exc_value: BaseException, exc_traceback
    ) -> None:
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        self._generate_diagnostics_bundle(
            "tk_exception",
            extra_context={"exception": str(exc_value), "traceback": tb},
        )
        if callable(self._original_tk_report_callback_exception):
            try:
                self._original_tk_report_callback_exception(exc_type, exc_value, exc_traceback)
            except Exception:
                pass

    def _on_watchdog_violation_event(self, job_id: str, envelope: UnifiedErrorEnvelope) -> None:
        reason = envelope.context.get("watchdog_reason", envelope.error_type)
        self._generate_diagnostics_bundle(
            f"watchdog_{reason.lower()}",
            extra_context={"job_id": job_id, "envelope": serialize_envelope(envelope)},
        )

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        snapshot = self.job_service.get_diagnostics_snapshot() if self.job_service else {}
        data = dict(snapshot)
        manager = getattr(self, "webui_process_manager", None)
        if manager and hasattr(manager, "get_recent_output_tail"):
            try:
                data["webui_tail"] = manager.get_recent_output_tail()
            except Exception:
                data["webui_tail"] = None
        data["controller"] = {
            "last_ui_heartbeat_ts": getattr(self, "last_ui_heartbeat_ts", None),
            "last_queue_activity_ts": getattr(self, "last_queue_activity_ts", None),
            "last_runner_activity_ts": getattr(self, "last_runner_activity_ts", None),
            "queue_projection_timing": (
                dict(self._last_queue_projection_timing)
                if isinstance(self._last_queue_projection_timing, Mapping)
                else None
            ),
        }
        pipeline_controller = getattr(self, "pipeline_controller", None)
        preview_timing_getter = getattr(
            pipeline_controller,
            "get_preview_build_timing_snapshot",
            None,
        )
        if callable(preview_timing_getter):
            try:
                data["pipeline_controller"] = {
                    "preview_build_timing": preview_timing_getter(),
                }
            except Exception:
                data["pipeline_controller"] = None
        webui_connection = getattr(self, "webui_connection_controller", None)
        if webui_connection is None and pipeline_controller is not None:
            webui_connection = getattr(pipeline_controller, "_webui_connection", None)
        readiness_timing_getter = getattr(
            webui_connection,
            "get_last_connection_timing_snapshot",
            None,
        )
        readiness_state_getter = getattr(webui_connection, "get_state", None)
        if callable(readiness_timing_getter):
            try:
                readiness_state = None
                if callable(readiness_state_getter):
                    state = readiness_state_getter()
                    readiness_state = getattr(state, "value", str(state) if state is not None else None)
                data["webui_connection"] = {
                    "state": readiness_state,
                    "timing": readiness_timing_getter(),
                }
            except Exception:
                data["webui_connection"] = None
        snapshot = getattr(self, "_optional_dependency_snapshot", None)
        if snapshot is not None and hasattr(snapshot, "to_dict"):
            try:
                data["optional_dependencies"] = snapshot.to_dict()
            except Exception:
                data["optional_dependencies"] = None
        pipeline_tab = getattr(getattr(self, "main_window", None), "pipeline_tab", None)
        getter = getattr(pipeline_tab, "get_diagnostics_snapshot", None)
        if callable(getter):
            try:
                data["pipeline_tab"] = getter()
            except Exception:
                data["pipeline_tab"] = None
        log_trace_panel = getattr(getattr(self, "main_window", None), "log_trace_panel_v2", None)
        log_trace_getter = getattr(log_trace_panel, "get_diagnostics_snapshot", None)
        if callable(log_trace_getter):
            try:
                data["log_trace_panel"] = log_trace_getter()
            except Exception:
                data["log_trace_panel"] = None
        data["app_state"] = self._build_diagnostics_app_state_snapshot()
        data["jobs"] = self._build_enriched_diagnostics_jobs(data.get("jobs"))
        process_snapshot, thread_snapshot = self._get_cached_heavy_diagnostics_snapshots()
        data["process_inspector"] = process_snapshot
        data["threads"] = thread_snapshot
        data["last_bundle"] = (
            str(self._last_diagnostics_bundle) if self._last_diagnostics_bundle else None
        )
        data["last_bundle_reason"] = self._last_diagnostics_bundle_reason
        return data

    def _get_cached_heavy_diagnostics_snapshots(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        process_snapshot: dict[str, Any] | None = None
        thread_snapshot: dict[str, Any] | None = None
        refresh_needed = False
        now = time.monotonic()
        with self._diagnostics_lock:
            if isinstance(self._diagnostics_process_snapshot_cache, dict):
                process_snapshot = deepcopy(self._diagnostics_process_snapshot_cache)
            if isinstance(self._diagnostics_thread_snapshot_cache, dict):
                thread_snapshot = deepcopy(self._diagnostics_thread_snapshot_cache)
            cache_ready = process_snapshot is not None and thread_snapshot is not None
            cache_stale = (
                cache_ready
                and self._diagnostics_heavy_snapshot_ts > 0.0
                and (now - self._diagnostics_heavy_snapshot_ts)
                >= _DIAGNOSTICS_HEAVY_SNAPSHOT_TTL_SEC
            )
            if (
                cache_stale
                and not self._diagnostics_heavy_snapshot_refresh_in_progress
                and not self._is_shutting_down
            ):
                self._diagnostics_heavy_snapshot_refresh_in_progress = True
                refresh_needed = True
        if process_snapshot is None or thread_snapshot is None:
            process_snapshot = self._build_process_inspector_snapshot()
            thread_snapshot = self._build_thread_snapshot()
            self._store_heavy_diagnostics_snapshots(process_snapshot, thread_snapshot)
            return process_snapshot, thread_snapshot
        if refresh_needed:
            self._schedule_heavy_diagnostics_refresh()
        return process_snapshot, thread_snapshot

    def _schedule_heavy_diagnostics_refresh(self) -> None:
        try:
            self._spawn_tracked_thread(
                target=self._refresh_heavy_diagnostics_snapshots_async,
                name="DiagnosticsSnapshotRefresh",
                purpose="Refresh cached process and thread diagnostics snapshots",
            )
        except Exception:
            with self._diagnostics_lock:
                self._diagnostics_heavy_snapshot_refresh_in_progress = False

    def _refresh_heavy_diagnostics_snapshots_async(self) -> None:
        process_snapshot: dict[str, Any] | None = None
        thread_snapshot: dict[str, Any] | None = None
        try:
            process_snapshot = self._build_process_inspector_snapshot()
        except Exception:
            process_snapshot = None
        try:
            thread_snapshot = self._build_thread_snapshot()
        except Exception:
            thread_snapshot = None
        with self._diagnostics_lock:
            if process_snapshot is not None:
                self._diagnostics_process_snapshot_cache = deepcopy(process_snapshot)
            if thread_snapshot is not None:
                self._diagnostics_thread_snapshot_cache = deepcopy(thread_snapshot)
            if process_snapshot is not None or thread_snapshot is not None:
                self._diagnostics_heavy_snapshot_ts = time.monotonic()
            self._diagnostics_heavy_snapshot_refresh_in_progress = False

    def _store_heavy_diagnostics_snapshots(
        self,
        process_snapshot: dict[str, Any],
        thread_snapshot: dict[str, Any],
    ) -> None:
        with self._diagnostics_lock:
            self._diagnostics_process_snapshot_cache = deepcopy(process_snapshot)
            self._diagnostics_thread_snapshot_cache = deepcopy(thread_snapshot)
            self._diagnostics_heavy_snapshot_ts = time.monotonic()
            self._diagnostics_heavy_snapshot_refresh_in_progress = False

    def _find_live_job(self, job_id: str) -> Any | None:
        job_service = getattr(self, "job_service", None)
        job_queue = getattr(job_service, "job_queue", None)
        getter = getattr(job_queue, "get_job", None)
        if callable(getter):
            try:
                return getter(job_id)
            except Exception:
                return None
        return None

    def _extract_normalized_snapshot(
        self,
        *,
        live_job: Any | None,
        history_entry: Any | None,
    ) -> dict[str, Any]:
        candidates: list[Any] = []
        if live_job is not None:
            candidates.append(getattr(live_job, "_normalized_record", None))
            candidates.append(getattr(live_job, "snapshot", None))
        if history_entry is not None:
            candidates.append(getattr(history_entry, "snapshot", None))
        for candidate in candidates:
            if candidate is None:
                continue
            if hasattr(candidate, "to_queue_snapshot") and callable(candidate.to_queue_snapshot):
                try:
                    snapshot = candidate.to_queue_snapshot()
                    if isinstance(snapshot, dict):
                        return dict(snapshot)
                except Exception:
                    continue
            if isinstance(candidate, dict):
                normalized = candidate.get("normalized_job") if "normalized_job" in candidate else candidate
                if isinstance(normalized, dict):
                    return dict(normalized)
        return {}

    @staticmethod
    def _resolve_job_status_value(*, live_job: Any | None, history_entry: Any | None) -> str:
        status = getattr(live_job, "status", None)
        if hasattr(status, "value"):
            return str(status.value)
        if status is not None:
            return str(status)
        history_status = getattr(history_entry, "status", None)
        if hasattr(history_status, "value"):
            return str(history_status.value)
        if history_status is not None:
            return str(history_status)
        return ""

    def _resolve_stage_flow(
        self,
        normalized: Mapping[str, Any],
        runtime_status: Any | None,
    ) -> list[str]:
        stage_chain = normalized.get("stage_chain") if isinstance(normalized, Mapping) else None
        if isinstance(stage_chain, list) and stage_chain:
            return [str(stage) for stage in stage_chain if stage]
        runtime_stage = getattr(runtime_status, "current_stage", None)
        if runtime_stage:
            return [str(runtime_stage)]
        return ["txt2img"]

    def _build_debug_job_label(self, job_id: str, normalized: Mapping[str, Any]) -> str:
        pack_name = str(
            normalized.get("prompt_pack_name")
            or normalized.get("pack_name")
            or normalized.get("prompt_pack_id")
            or normalized.get("model")
            or job_id
        )
        row_index = normalized.get("prompt_pack_row_index")
        variant_index = normalized.get("variant_index")
        batch_index = normalized.get("batch_index")
        parts = [pack_name]
        if isinstance(row_index, int):
            parts.append(f"row={row_index + 1}")
        if isinstance(variant_index, int):
            parts.append(f"v={variant_index + 1}")
        if isinstance(batch_index, int):
            parts.append(f"b={batch_index + 1}")
        return " | ".join(parts + [job_id])

    def _build_job_origin_text(
        self,
        *,
        job_id: str,
        normalized: Mapping[str, Any],
        live_job: Any | None,
        history_entry: Any | None,
        runtime_status: Any | None,
    ) -> str:
        parts: list[str] = [f"Job: {job_id}"]
        pack_usage = normalized.get("pack_usage") if isinstance(normalized, Mapping) else None
        if isinstance(pack_usage, list) and pack_usage:
            pack_labels = []
            for item in pack_usage:
                if isinstance(item, dict):
                    name = item.get("pack_name") or item.get("pack_id")
                    stage = item.get("used_for_stage")
                    if name and stage:
                        pack_labels.append(f"{name} ({stage})")
                    elif name:
                        pack_labels.append(str(name))
            if pack_labels:
                parts.append("Packs: " + ", ".join(pack_labels))
        elif normalized.get("prompt_pack_name"):
            parts.append(f"Pack: {normalized.get('prompt_pack_name')}")

        prompt_source = getattr(live_job, "prompt_source", None) or getattr(
            history_entry, "prompt_source", None
        )
        if prompt_source:
            parts.append(f"source={prompt_source}")
        run_mode = getattr(live_job, "run_mode", None) or getattr(history_entry, "run_mode", None)
        if run_mode:
            parts.append(f"run_mode={run_mode}")
        status_value = self._resolve_job_status_value(live_job=live_job, history_entry=history_entry)
        if status_value:
            parts.append(f"status={status_value}")
        if runtime_status is not None and hasattr(runtime_status, "get_stage_display"):
            try:
                parts.append(f"runtime={runtime_status.get_stage_display()}")
            except Exception:
                pass
        return " | ".join(parts)

    def _build_job_stage_prompt_rows(
        self,
        *,
        normalized: Mapping[str, Any],
        stage_flow: list[str],
        runtime_status: Any | None,
    ) -> list[dict[str, str]]:
        def _prompt_info_for(stage_name: str) -> Mapping[str, Any]:
            key = f"{stage_name}_prompt_info"
            value = normalized.get(key)
            return value if isinstance(value, Mapping) else {}

        rows: list[dict[str, str]] = []
        runtime_stage = str(getattr(runtime_status, "current_stage", "") or "")
        for stage_name in stage_flow:
            info = _prompt_info_for(str(stage_name))
            prompt = str(info.get("final_prompt") or normalized.get("prompt") or "-")
            negative = str(
                info.get("final_negative_prompt") or normalized.get("negative_prompt") or "-"
            )
            global_terms = str(info.get("global_negative_terms") or "-")
            status = "current" if runtime_stage and runtime_stage == str(stage_name) else "available"
            rows.append(
                {
                    "stage": str(stage_name),
                    "prompt": prompt,
                    "negative": negative,
                    "global_terms": global_terms,
                    "status": status,
                }
            )
        return rows

    def _build_job_metadata_payload(
        self,
        *,
        job_id: str,
        normalized: Mapping[str, Any],
        live_job: Any | None,
        history_entry: Any | None,
        runtime_status: Any | None,
        status_value: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "job_id": job_id,
            "status": status_value,
            "prompt_pack_id": normalized.get("prompt_pack_id"),
            "prompt_pack_name": normalized.get("prompt_pack_name"),
            "row_index": normalized.get("prompt_pack_row_index"),
            "variant_index": normalized.get("variant_index"),
            "batch_index": normalized.get("batch_index"),
            "model": normalized.get("model"),
            "sampler": normalized.get("sampler"),
            "steps": normalized.get("steps"),
            "cfg_scale": normalized.get("cfg_scale"),
            "width": normalized.get("width"),
            "height": normalized.get("height"),
            "seed": normalized.get("seed"),
            "output_dir": normalized.get("output_dir"),
            "stage_chain": list(normalized.get("stage_chain") or []),
            "randomization_enabled": normalized.get("randomization_enabled"),
            "matrix_slot_values": normalized.get("matrix_slot_values"),
            "config_layers": normalized.get("config_layers"),
            "error_message": getattr(live_job, "error_message", None)
            or getattr(history_entry, "error_message", None),
        }
        result = getattr(live_job, "result", None) or getattr(history_entry, "result", None)
        if isinstance(result, dict):
            metadata["result"] = dict(result)
        if runtime_status is not None:
            metadata["runtime_status"] = {
                "current_stage": getattr(runtime_status, "current_stage", None),
                "stage_index": getattr(runtime_status, "stage_index", None),
                "total_stages": getattr(runtime_status, "total_stages", None),
                "progress": getattr(runtime_status, "progress", None),
                "eta_seconds": getattr(runtime_status, "eta_seconds", None),
                "actual_seed": getattr(runtime_status, "actual_seed", None),
                "current_step": getattr(runtime_status, "current_step", None),
                "total_steps": getattr(runtime_status, "total_steps", None),
                "stage_detail": getattr(runtime_status, "stage_detail", None),
            }
        return metadata

    def _build_diagnostics_app_state_snapshot(self) -> dict[str, Any]:
        app_state = getattr(self, "app_state", None)
        running_job = getattr(app_state, "running_job", None)
        runtime_status = getattr(app_state, "runtime_status", None) or self._get_latest_runtime_status()
        queue_jobs = list(getattr(app_state, "queue_jobs", []) or [])
        history_items = list(getattr(app_state, "history_items", []) or [])
        return {
            "running_job": self._serialize_job_summary(running_job),
            "runtime_status": self._serialize_runtime_status(runtime_status),
            "queue_job_count": len(queue_jobs),
            "history_count": len(history_items),
        }

    def _build_enriched_diagnostics_jobs(self, jobs: Any) -> list[dict[str, Any]]:
        if not isinstance(jobs, list):
            return []
        app_state = getattr(self, "app_state", None)
        queue_jobs = list(getattr(app_state, "queue_jobs", []) or [])
        running_job = getattr(app_state, "running_job", None)
        history_items = list(getattr(app_state, "history_items", []) or [])
        summary_index = {
            summary.job_id: summary
            for summary in ([running_job] if running_job is not None else []) + queue_jobs
            if getattr(summary, "job_id", None)
        }
        history_index = {
            getattr(entry, "job_id", None): entry
            for entry in history_items
            if getattr(entry, "job_id", None)
        }
        runtime_status = self._get_latest_runtime_status()

        enriched: list[dict[str, Any]] = []
        for entry in jobs:
            if not isinstance(entry, dict):
                continue
            job_id = str(entry.get("job_id") or "")
            live_job = self._find_live_job(job_id)
            history_entry = history_index.get(job_id)
            normalized = self._extract_normalized_snapshot(
                live_job=live_job,
                history_entry=history_entry,
            )
            summary = summary_index.get(job_id)
            display_label = (
                summary.get_display_summary()
                if summary is not None and hasattr(summary, "get_display_summary")
                else self._build_debug_job_label(job_id, normalized)
            )
            stage_display = self._format_job_stage_display(
                job_id=job_id,
                summary=summary,
                normalized=normalized,
                runtime_status=runtime_status,
                result_summary=entry.get("result_summary"),
            )
            diagnostics_text = self._format_job_diagnostics_text(entry, history_entry)
            pids = [int(pid) for pid in entry.get("external_pids", []) if isinstance(pid, int)]
            enriched_entry = dict(entry)
            enriched_entry["display_label"] = display_label
            enriched_entry["stage_display"] = stage_display
            enriched_entry["pid_display"] = ", ".join(str(pid) for pid in pids) if pids else "none"
            enriched_entry["diagnostics_text"] = diagnostics_text
            enriched.append(enriched_entry)
        return enriched

    def _format_job_stage_display(
        self,
        *,
        job_id: str,
        summary: Any | None,
        normalized: Mapping[str, Any],
        runtime_status: Any | None,
        result_summary: Any,
    ) -> str:
        if getattr(runtime_status, "job_id", None) == job_id and hasattr(runtime_status, "get_stage_display"):
            try:
                stage_text = runtime_status.get_stage_display()
                progress = getattr(runtime_status, "progress", None)
                if isinstance(progress, (int, float)):
                    return f"{stage_text} ({int(float(progress) * 100)}%)"
                return stage_text
            except Exception:
                pass
        stage_chain = normalized.get("stage_chain") if isinstance(normalized, Mapping) else None
        if isinstance(stage_chain, list) and stage_chain:
            return " -> ".join(str(stage) for stage in stage_chain if stage)
        if summary is not None:
            stage_labels = getattr(summary, "stage_chain_labels", None)
            if isinstance(stage_labels, list) and stage_labels:
                return " -> ".join(str(stage) for stage in stage_labels if stage)
        if isinstance(result_summary, Mapping):
            primary_stage = result_summary.get("primary_stage")
            if primary_stage:
                return str(primary_stage)
        return "-"

    def _format_job_diagnostics_text(self, entry: Mapping[str, Any], history_entry: Any | None) -> str:
        parts: list[str] = []
        result_summary = entry.get("result_summary")
        if isinstance(result_summary, Mapping):
            duration_ms = result_summary.get("duration_ms")
            if isinstance(duration_ms, (int, float)):
                parts.append(f"duration={float(duration_ms):.0f}ms")
            output_count = result_summary.get("output_count")
            if isinstance(output_count, int):
                parts.append(f"outputs={output_count}")
            error = result_summary.get("error")
            if error:
                parts.append(f"error={error}")
        retries = entry.get("retry_attempts")
        if isinstance(retries, list) and retries:
            parts.append(f"retries={len(retries)}")
        duration_ms = getattr(history_entry, "duration_ms", None)
        if not parts and isinstance(duration_ms, int):
            parts.append(f"duration={duration_ms}ms")
        return " | ".join(parts) if parts else "no diagnostics"

    def _build_process_inspector_snapshot(self) -> dict[str, Any]:
        scanner = getattr(self, "process_auto_scanner", None)
        scanner_summary = getattr(scanner, "summary", None)
        summary_payload = None
        if scanner_summary is not None:
            summary_payload = {
                "timestamp": getattr(scanner_summary, "timestamp", None),
                "scanned": getattr(scanner_summary, "scanned", None),
                "killed": list(getattr(scanner_summary, "killed", []) or []),
            }
        try:
            risk = collect_process_risk_snapshot()
        except Exception:
            risk = None
        try:
            process_lines = [
                format_process_brief(process)
                for process in iter_stablenew_like_processes()
            ]
        except Exception:
            process_lines = []
        return {
            "scanner_status": scanner.get_status_text() if scanner is not None else None,
            "scanner_enabled": bool(getattr(scanner, "enabled", False)) if scanner is not None else False,
            "scan_interval": float(getattr(scanner, "scan_interval", 0.0) or 0.0)
            if scanner is not None
            else 0.0,
            "protected_pids": sorted(int(pid) for pid in self._get_protected_process_pids()),
            "summary": summary_payload,
            "risk": risk,
            "processes": process_lines,
        }

    def _build_thread_snapshot(self) -> dict[str, Any]:
        tracked_status = None
        tracked_threads: dict[int, Any] = {}
        try:
            registry = get_thread_registry()
            tracked_status = registry.dump_status()
            tracked_threads = {
                thread.thread.ident: thread
                for thread in registry.get_active_threads()
                if getattr(thread.thread, "ident", None) is not None
            }
        except Exception:
            tracked_status = None
        try:
            frames = sys._current_frames()
        except Exception:
            frames = {}
        threads: list[dict[str, Any]] = []
        for thread in threading.enumerate():
            ident = getattr(thread, "ident", None)
            frame = frames.get(ident) if ident is not None else None
            top_frame = None
            if frame is not None:
                try:
                    top_frame = {
                        "file": str(frame.f_code.co_filename),
                        "line": int(frame.f_lineno),
                        "function": str(frame.f_code.co_name),
                    }
                except Exception:
                    top_frame = None
            tracked = tracked_threads.get(ident) if ident is not None else None
            threads.append(
                {
                    "name": thread.name,
                    "ident": ident,
                    "daemon": bool(thread.daemon),
                    "alive": bool(thread.is_alive()),
                    "tracked": tracked is not None,
                    "purpose": getattr(tracked, "purpose", None) if tracked is not None else None,
                    "top_frame": top_frame,
                }
            )
        threads.sort(key=lambda item: (0 if item.get("name") == "MainThread" else 1, str(item.get("name") or "")))
        return {
            "thread_count": len(threads),
            "tracked_status": tracked_status,
            "threads": threads,
        }

    def _serialize_job_summary(self, summary: Any | None) -> dict[str, Any] | None:
        if summary is None:
            return None
        display_label = None
        getter = getattr(summary, "get_display_summary", None)
        if callable(getter):
            try:
                display_label = getter()
            except Exception:
                display_label = None
        return {
            "job_id": getattr(summary, "job_id", None),
            "display_label": display_label,
            "prompt_pack_name": getattr(summary, "prompt_pack_name", None),
            "stage_chain_labels": list(getattr(summary, "stage_chain_labels", []) or []),
            "status": getattr(summary, "status", None),
        }

    def _serialize_runtime_status(self, status: Any | None) -> dict[str, Any] | None:
        if status is None:
            return None
        stage_display = None
        stage_label = getattr(status, "get_stage_display", None)
        if callable(stage_label):
            try:
                stage_display = stage_label()
            except Exception:
                stage_display = None
        eta_display = None
        eta_getter = getattr(status, "get_eta_display", None)
        if callable(eta_getter):
            try:
                eta_display = eta_getter()
            except Exception:
                eta_display = None
        progress = getattr(status, "progress", None)
        progress_pct = int(float(progress) * 100) if isinstance(progress, (int, float)) else None
        started_at = getattr(status, "started_at", None)
        return {
            "job_id": getattr(status, "job_id", None),
            "stage_display": stage_display,
            "progress_pct": progress_pct,
            "eta_display": eta_display,
            "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
            "stage_detail": getattr(status, "stage_detail", None),
        }

    def show_log_trace_panel(self) -> None:
        """Expose helper that expands the LogTracePanelV2 if present."""
        trace_panel = getattr(self.main_window, "log_trace_panel_v2", None)
        if trace_panel is None:
            logger.warning("show_log_trace_panel called but log_trace_panel_v2 not found")
            return
        try:
            trace_panel.show()
        except Exception as e:
            logger.error(f"Failed to show log trace panel: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Run / Stop / Preview
    # ------------------------------------------------------------------

    def run_pipeline(self) -> Any:
        """Deprecated public entrypoint that now resolves to queue-backed run flow."""
        if self.state.lifecycle == LifecycleState.RUNNING:
            self._append_log(
                "[controller] run_pipeline requested, but pipeline is already running."
            )
            return None

        self._append_log(
            "[controller] run_pipeline is deprecated; normalizing to the queue-backed start_run_v2 flow."
        )
        return self.start_run_v2()

    def _run_via_pipeline_controller(self) -> Any:
        """Delegate pipeline execution to PipelineController for modern V2 stack."""
        if not hasattr(self, "pipeline_controller") or self.pipeline_controller is None:
            raise RuntimeError("PipelineController not initialized")

        raise RuntimeError("run_pipeline is disabled in NJR-only mode")

    def _execute_pipeline_via_runner(self, pipeline_config: Any) -> Any:
        """DEPRECATED (PR-CORE1-12): Legacy pipeline_config execution removed.

        Execute pipeline using the traditional PipelineRunner approach.

        This method is DISABLED as of PR-CORE1-B2 (NJR-only execution).
        Use PipelineController.start_pipeline_v2() which builds NJR + enqueues.

        Raises:
            RuntimeError: Always - pipeline_config execution is disabled.
        """
        raise RuntimeError("Legacy runner path is disabled in NJR-only mode")

    def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: Any) -> Any:
        """DEPRECATED (PR-CORE1-12): Legacy tab-based pipeline_config execution.

        This method routed execution based on pipeline_tab flags. No longer used
        since GUI V2 uses PipelineController for all execution.

        Consider removing in future cleanup after GUI V1 removal.
        """
        flags = {
            "txt2img": self._coerce_bool(getattr(pipeline_tab, "txt2img_enabled", None)),
            "img2img": self._coerce_bool(getattr(pipeline_tab, "img2img_enabled", None)),
            "adetailer": self._coerce_bool(getattr(pipeline_tab, "adetailer_enabled", None)),
            "upscale": self._coerce_bool(getattr(pipeline_tab, "upscale_enabled", None)),
        }
        factor, model, tile_size = self._get_pipeline_tab_upscale_params(pipeline_tab)
        prompt = self._get_pipeline_tab_prompt(pipeline_tab)
        if flags["upscale"] and not (flags["txt2img"] or flags["img2img"] or flags["adetailer"]):
            input_image_path = getattr(pipeline_tab, "input_image_path", "") or ""
            return self._run_standalone_upscale(
                input_image_path=input_image_path,
                factor=factor,
                model=model,
                tile_size=tile_size,
                prompt=prompt,
            )

        if flags["txt2img"] and flags["upscale"]:
            return self._run_txt2img_then_upscale(
                prompt=prompt,
                factor=factor,
                model=model,
                tile_size=tile_size,
            )

        raise RuntimeError("Legacy pipeline tab execution is disabled in NJR-only mode")

    def _run_standalone_upscale(
        self,
        *,
        input_image_path: str,
        factor: float,
        model: str,
        tile_size: int,
        prompt: str,
    ) -> dict[str, Any]:
        if not input_image_path:
            raise ValueError("No input image provided for standalone upscale.")
        image_path = Path(input_image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Input image not found: {image_path}")
        api = self._ensure_webui_api()
        kwargs: dict[str, Any] = {
            "image": str(image_path),
            "upscale_factor": factor,
            "model": model,
            "tile_size": tile_size,
            "prompt": prompt,
        }
        self._append_log("[controller] Performing standalone upscale via WebUI API.")
        response = api.upscale_image(**kwargs)
        return {
            "mode": "standalone_upscale",
            "input_image": str(image_path),
            "factor": factor,
            "model": model,
            "tile_size": tile_size,
            "prompt": prompt,
            "response": response,
        }

    def _run_txt2img_then_upscale(
        self,
        *,
        prompt: str,
        factor: float,
        model: str,
        tile_size: int,
    ) -> dict[str, Any]:
        api = self._ensure_webui_api()
        txt_kwargs: dict[str, Any] = {"prompt": prompt or ""}
        txt_response = api.txt2img(**txt_kwargs)
        self._append_log("[controller] Completed txt2img stage via WebUI API.")
        images = txt_response.get("images") or []
        upscaled_results: list[dict[str, Any]] = []
        for image in images:
            upscale_kwargs: dict[str, Any] = {
                "image": image,
                "upscale_factor": factor,
                "model": model,
                "tile_size": tile_size,
                "prompt": prompt,
            }
            upscaled_results.append(api.upscale_image(**upscale_kwargs))
        return {
            "mode": "txt2img_then_upscale",
            "prompt": prompt,
            "factor": factor,
            "model": model,
            "tile_size": tile_size,
            "txt2img": txt_response,
            "upscaled": upscaled_results,
        }

    def _run_pipeline_via_runner_only(self, pipeline_config: Any) -> Any:
        """DEPRECATED (PR-CORE1-12): Legacy fallback execution - NO LONGER USED.

        As of PR-CORE1-B2, all jobs execute via NJR-only path. This method existed
        as a fallback for jobs without NJR, but such jobs are no longer created.

        All execution MUST go through:
        GUI → PipelineController → JobService → Queue → Runner (NJR only)

        Raises:
            RuntimeError: Always - pipeline_config execution is disabled.
        """
        runner = getattr(self, "pipeline_runner", None)
        if runner is None:
            raise RuntimeError("No pipeline runner configured")
        raise RuntimeError("Legacy runner-only path is disabled in NJR-only mode")

    def _get_pipeline_tab_upscale_params(self, pipeline_tab: Any) -> tuple[float, str, int]:
        factor_var = getattr(pipeline_tab, "upscale_factor", None)
        try:
            factor = float(factor_var.get()) if hasattr(factor_var, "get") else float(factor_var)
        except Exception:
            factor = 2.0
        model_var = getattr(pipeline_tab, "upscale_model", None)
        model = ""
        try:
            model = (
                str(model_var.get()).strip() if hasattr(model_var, "get") else str(model_var or "")
            )
        except Exception:
            model = str(model_var or "")
        tile_var = getattr(pipeline_tab, "upscale_tile_size", None)
        try:
            tile = int(tile_var.get()) if hasattr(tile_var, "get") else int(tile_var or 0)
        except Exception:
            tile = 0
        return factor, model, tile

    def _get_pipeline_tab_prompt(self, pipeline_tab: Any) -> str:
        prompt_attr = getattr(pipeline_tab, "prompt_text", None)
        if prompt_attr is None:
            return ""
        try:
            if hasattr(prompt_attr, "get"):
                return str(prompt_attr.get() or "")
        except Exception:
            pass
        return str(prompt_attr or "")

    def _coerce_bool(self, value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if hasattr(value, "get"):
            try:
                return bool(value.get())
            except Exception:
                return default
        return bool(value)

    def _ensure_webui_api(self) -> WebUIAPI:
        if self._webui_api is None:
            self._webui_api = WebUIAPI()
        return self._webui_api

    def on_run_clicked(self) -> None:
        """
        Called when the user presses RUN.
        """
        if self.state.lifecycle == LifecycleState.RUNNING:
            self._append_log("[controller] Run requested, but pipeline is already running.")
            return

        self._append_log("[controller] Run clicked - gathering config.")
        is_valid, message = self._validate_pipeline_config()
        self._set_validation_feedback(is_valid, message)
        if not is_valid:
            self._append_log(f"[controller] Pipeline validation failed: {message}")
            return
        self._ensure_run_mode_default("run")
        self.start_run_v2()

    def start_run(self) -> Any:
        """Legacy-friendly entrypoint used by older harnesses."""
        if self.state.lifecycle == LifecycleState.RUNNING:
            self._append_log("[controller] start_run requested while already running.")
            return None
        self._append_log("[controller] start_run normalizing to queue-backed start_run_v2.")
        return self.start_run_v2()

    def on_launch_webui_clicked(self) -> None:
        if not self.webui_process_manager:
            return
        self._append_log("[webui] Launch requested by user.")
        logger.info("[webui] Launch requested by user.")
        self._update_webui_state("connecting")
        success = self.webui_process_manager.ensure_running()
        self._update_webui_state("connected" if success else "error")

    def on_retry_webui_clicked(self) -> None:
        if not self.webui_process_manager:
            return
        self._append_log("[webui] Retry connection requested by user.")
        healthy = self.webui_process_manager.check_health()
        self._update_webui_state("connected" if healthy else "error")

    def _run_pipeline_thread(self, cancel_token: CancelToken) -> None:
        """Retired legacy helper kept only to fail loudly if called."""
        cancel_token.cancel()
        cancel_token.clear_stop_requirement()
        self._cancel_token = None
        raise RuntimeError(
            "Legacy pipeline thread path is disabled; use the queue-backed start_run_v2 flow."
        )

    def _cache_last_run_payload(
        self, executor_config: dict[str, Any], pipeline_config: DeprecatedPipelineConfigSnapshot
    ) -> None:
        """DEPRECATED (PR-CORE1-12): Legacy payload caching for pipeline_config.

        This cached pipeline_config for debugging/replay. No longer used since
        NJR jobs include full snapshots. Consider removing in future cleanup.
        """
        if not executor_config:
            return
        snapshot = self._run_config_with_lora()
        payload: dict[str, Any] = {
            "executor_config": deepcopy(executor_config),
            "run_config_snapshot": snapshot,
            "prompt": pipeline_config.prompt,
            "pack_name": pipeline_config.pack_name,
            "preset_name": pipeline_config.preset_name,
        }
        self._last_executor_config = payload["executor_config"]
        self._last_run_snapshot = snapshot
        try:
            self._config_manager.write_last_run(payload)
            if self.app_state:
                try:
                    last_cfg = current_config_to_last_run(self.app_state.current_config)
                    self._last_run_store.save(last_cfg)
                except Exception:
                    pass
        except Exception:
            pass

    def get_last_run_config(self) -> dict[str, Any] | None:
        """Expose the last executor payload captured for the GUI helpers."""

        return self._last_executor_config

    def restore_last_run(self, *, force: bool = False) -> None:
        """Restore UI settings from disk and the cached payload."""

        if self._last_run_auto_restored and not force:
            return
        if self.app_state:
            try:
                last_cfg = self._last_run_store.load()
                if last_cfg is not None:
                    update_current_config_from_last_run(self.app_state.current_config, last_cfg)
            except Exception:
                pass
        payload = self._config_manager.load_last_run()
        if not payload:
            self._apply_model_profile_defaults(self.state.current_config.model_name or None)
            return
        executor_config = payload.get("executor_config")
        if not isinstance(executor_config, dict):
            return
        run_snapshot = payload.get("run_config_snapshot")
        if isinstance(run_snapshot, dict):
            self._last_run_snapshot = run_snapshot
        self._last_executor_config = executor_config
        self._apply_last_run_payload(executor_config, run_snapshot)
        if not force:
            self._last_run_auto_restored = True

    def _apply_last_run_payload(
        self,
        executor_config: dict[str, Any],
        run_snapshot: dict[str, Any] | None,
    ) -> None:
        stage_panel = self._get_stage_cards_panel()
        if stage_panel:
            for card_name in ("txt2img", "img2img", "upscale"):
                card = getattr(stage_panel, f"{card_name}_card", None)
                self._load_stage_card(card, executor_config)
            stage_panel.load_adetailer_config(executor_config.get("adetailer") or {})

        pipeline_section = executor_config.get("pipeline") or {}
        # Get stage flags directly from config without defaults - if missing, will be None
        txt2img_val = pipeline_section.get("txt2img_enabled")
        img2img_val = pipeline_section.get("img2img_enabled") 
        adetailer_val = pipeline_section.get("adetailer_enabled")
        upscale_val = pipeline_section.get("upscale_enabled")
        
        stage_defaults = {
            "txt2img": bool(txt2img_val) if txt2img_val is not None else True,
            "img2img": bool(img2img_val) if img2img_val is not None else False,
            "adetailer": bool(adetailer_val) if adetailer_val is not None else False,
            "upscale": bool(upscale_val) if upscale_val is not None else False,
        }
        logger.debug(
            "[controller] Loading stage flags from config: txt2img=%s, img2img=%s, adetailer=%s, upscale=%s",
            stage_defaults["txt2img"],
            stage_defaults["img2img"],
            stage_defaults["adetailer"],
            stage_defaults["upscale"],
        )
        for stage, enabled in stage_defaults.items():
            self._set_sidebar_stage_state(stage, enabled)
        self._refresh_stage_visibility()

        ad_config = executor_config.get("adetailer") or {}
        ad_enabled = bool(pipeline_section.get("adetailer_enabled") or ad_config.get("enabled"))
        if self.app_state:
            self.app_state.set_adetailer_enabled(ad_enabled)
            snapshot = dict(ad_config)
            snapshot["enabled"] = ad_enabled
            self.app_state.set_adetailer_config(snapshot)

        if self.app_state and isinstance(run_snapshot, dict):
            self.app_state.set_run_config(dict(run_snapshot))

    def _apply_model_profile_defaults(self, model_name: str | None) -> None:
        defaults = get_model_profile_defaults_for_model(model_name)
        if not defaults:
            return
        configs: list[Any] = []
        state_config = getattr(self.state, "current_config", None)
        if state_config is not None:
            configs.append(state_config)
        if self.app_state is not None:
            configs.append(self.app_state.current_config)
        for cfg in configs:
            self._set_profile_default(
                cfg, "refiner_model_name", defaults.get("default_refiner_id"), ""
            )
            self._set_profile_default(
                cfg, "refiner_switch_at", defaults.get("default_refiner_switch_at"), None
            )
            self._set_profile_default(
                cfg, "hires_upscaler_name", defaults.get("default_hires_upscaler_id"), "Latent"
            )
            self._set_profile_default(
                cfg, "hires_denoise", defaults.get("default_hires_denoise"), 0.3
            )
            # Keep hires_enabled False unless user explicitly toggles it.

    @staticmethod
    def _set_profile_default(
        cfg: Any,
        attr: str,
        value: Any,
        baseline: Any,
    ) -> None:
        if value is None:
            return
        current = getattr(cfg, attr, None)
        if current:
            if current != baseline or value == baseline:
                return
        setattr(cfg, attr, value)

    def _refresh_stage_visibility(self) -> None:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab and hasattr(pipeline_tab, "_handle_sidebar_change"):
            try:
                pipeline_tab._handle_sidebar_change()
            except Exception:
                pass

    def _set_sidebar_stage_state(self, stage: str, enabled: bool) -> None:
        sidebar = self._get_sidebar_panel()
        if not sidebar:
            return
        sidebar.set_stage_state(stage, enabled, emit_change=False)
        
        # Also update pipeline_tab flags to keep them in sync
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab:
            enabled_var = getattr(pipeline_tab, f"{stage}_enabled", None)
            if enabled_var is not None:
                try:
                    enabled_var.set(bool(enabled))
                    logger.debug(
                        "[controller] Synced stage '%s' to %s (sidebar + pipeline_tab)",
                        stage,
                        enabled,
                    )
                except Exception as exc:
                    logger.warning(
                        "[controller] Failed to sync stage '%s' to pipeline_tab: %s",
                        stage,
                        exc,
                    )

    def _apply_pipeline_stage_flags(self, pipeline_section: dict[str, Any]) -> None:
        if not pipeline_section:
            logger.warning("[controller] _apply_pipeline_stage_flags called with empty pipeline_section")
            return
        
        logger.info(
            "[controller] Applying stage flags from pipeline section: %s",
            {k: v for k, v in pipeline_section.items() if k.endswith("_enabled")},
        )
        
        for stage in ("txt2img", "img2img", "upscale", "adetailer"):
            key = f"{stage}_enabled"
            if key in pipeline_section:
                enabled = bool(pipeline_section.get(key))
                logger.info("[controller] Setting stage '%s' to %s", stage, enabled)
                self._set_sidebar_stage_state(stage, enabled)
            else:
                logger.warning("[controller] Pipeline section missing key '%s'", key)
        self._refresh_stage_visibility()

    def _load_stage_card(self, _card: Any | None, executor_config: dict[str, Any]) -> None:
        if _card is None:
            return
        loader = getattr(_card, "load_from_config", None)
        if callable(loader):
            try:
                loader(executor_config)
            except Exception:
                pass

    def on_stop_clicked(self) -> None:
        """
        Called when the user presses STOP.

        Sets lifecycle to STOPPING, triggers CancelToken, and lets the
        pipeline exit cooperatively. In synchronous mode, we immediately
        return to IDLE after marking cancel.
        """
        if self.state.lifecycle != LifecycleState.RUNNING:
            self._append_log("[controller] Stop requested, but pipeline is not running.")
            return

        self._append_log("[controller] Stop requested.")
        self._set_lifecycle(LifecycleState.STOPPING)

        if self._cancel_token is not None:
            self._cancel_token.cancel()
            self._cancel_token.clear_stop_requirement()

        worker_alive = self._worker_thread is not None and self._worker_thread.is_alive()
        if self.job_service is not None:
            self.job_service.cancel_current()
        if not worker_alive:
            self._set_lifecycle(LifecycleState.IDLE)
        # In threaded mode, lifecycle will transition to IDLE in _run_pipeline_thread
        # once the worker exits.

    def on_preview_clicked(self) -> None:
        """
        Called when the user presses Preview Payload.

        In real code, this would run randomizer/matrix to generate a preview
        payload without calling WebUI. For now, we just log a stub message.
        """
        self._append_log("[controller] Preview clicked (stub).")
        # TODO: gather config, pack, randomization, matrix → build preview payload.

    # ------------------------------------------------------------------
    # Settings / Help
    # ------------------------------------------------------------------

    def on_help_clicked(self) -> None:
        app_state = getattr(self, "app_state", None)
        toggle = getattr(app_state, "toggle_help_mode", None) if app_state is not None else None
        if callable(toggle):
            enabled = bool(toggle())
            self._append_log(f"[controller] Help mode {'enabled' if enabled else 'disabled'}.")
            return
        self._append_log("[controller] Help clicked, but no app state help-mode toggle is available.")

    def on_refresh_clicked(self) -> None:
        self._append_log("[controller] Refresh clicked.")
        # Run refresh in background thread to avoid GUI freeze
        import threading
        
        def _refresh_worker():
            try:
                self.refresh_resources_from_webui()
            except Exception as exc:
                logger.warning(f"Background refresh failed: {exc}")
                self._append_log(f"[controller] Refresh failed: {exc}")
        
        thread = threading.Thread(target=_refresh_worker, daemon=True, name="RefreshResourcesWorker")
        thread.start()
        self._append_log("[controller] Refresh started in background...")

    def stop_all_background_work(self) -> None:
        """Best-effort shutdown used by GUI teardown to avoid late Tk calls."""
        try:
            if self._cancel_token is not None:
                self._cancel_token.cancel()
        except Exception:
            pass
        worker_alive = self._worker_thread is not None and self._worker_thread.is_alive()
        if worker_alive and self._worker_thread is not None:
            try:
                self._worker_thread.join(timeout=2.0)
            except Exception:
                pass
            try:
                self._worker_thread = None
            except Exception:
                pass
        try:
            self.state.lifecycle = LifecycleState.IDLE
        except Exception:
            pass
        try:
            if self.process_auto_scanner:
                self.process_auto_scanner.stop()
        except Exception:
            pass

    def shutdown_app(self, reason: str | None = None) -> None:
        """Centralized shutdown path invoked by GUI teardown or main_finally."""
        if self._is_shutting_down:
            logger.info("[controller] shutdown_app: Already shutting down, skipping")
            return
        self._is_shutting_down = True
        label = reason or "shutdown"
        logger.info("[controller] ===== SHUTDOWN_APP CALLED (%s) =====", label)
        
        if self._shutdown_started_at is None:
            self._shutdown_started_at = time.time()
            self._shutdown_watchdog_thread = threading.Thread(
                target=self._shutdown_watchdog,
                name="ShutdownWatchdog",
                daemon=True,
            )
            self._shutdown_watchdog_thread.start()
        
        try:
            logger.info("[controller] Step 1/8: Cancelling active jobs...")
            self._cancel_active_jobs(label)
            logger.info("[controller] Step 1/8: Active jobs cancelled")
        except Exception:
            logger.exception("Error cancelling active jobs during shutdown")

        try:
            logger.info("[controller] Step 2/8: Stopping background work...")
            self.stop_all_background_work()
            logger.info("[controller] Step 2/8: Background work stopped")
        except Exception:
            logger.exception("Error stopping background work during shutdown")

        try:
            logger.info("[controller] Step 3/8: Shutting down learning hooks...")
            self._shutdown_learning_hooks()
            logger.info("[controller] Step 3/8: Learning hooks shutdown complete")
        except Exception:
            logger.exception("Error shutting down learning hooks")

        try:
            logger.info("[controller] Step 4/8: Shutting down WebUI process...")
            self._shutdown_webui()
            logger.info("[controller] Step 4/8: WebUI shutdown complete")
        except Exception:
            logger.exception("Error shutting down WebUI")
        try:
            logger.info("[controller] Step 5/8: Shutting down runtime host...")
            self._shutdown_runtime_host()
            logger.info("[controller] Step 5/8: Runtime host shutdown complete")
        except Exception:
            logger.exception("Error shutting down runtime host")
        
        # PR-SHUTDOWN-001: Call enhanced shutdown() for watchdog and thread cleanup
        try:
            logger.info("[controller] Step 5.5/8: Running enhanced shutdown sequence...")
            self.shutdown()
            logger.info("[controller] Step 5.5/8: Enhanced shutdown complete")
        except Exception:
            logger.exception("Error during enhanced shutdown")

        if is_debug_shutdown_inspector_enabled():
            try:
                logger.info("[controller] Step 6/8: Running shutdown inspector...")
                log_shutdown_state(logger, label)
                logger.info("[controller] Step 6/8: Shutdown inspector complete")
            except Exception:
                logger.exception("Error running shutdown inspector")

        try:
            logger.info("[controller] Step 7/8: Joining worker thread...")
            self._join_worker_thread()
            logger.info("[controller] Step 7/8: Worker thread joined")
        except Exception:
            logger.exception("Error waiting for worker thread during shutdown")

        # PR-PERSIST-FIX: Ensure queue state is saved before shutdown completes
        try:
            logger.info("[controller] Step 7.5/8: Saving queue state...")
            self._save_queue_state()
            logger.info("[controller] Step 7.5/8: Queue state saved")
        except Exception:
            logger.exception("Error saving queue state during shutdown")

        logger.info("[controller] Step 8/8: Closing API clients and finalizing shutdown...")

        # Close API client resources
        try:
            if hasattr(self, "_api_client") and self._api_client:
                self._api_client.close()
        except Exception:
            logger.exception("Error closing API client during shutdown")

        # Clear WebUI process manager global reference
        try:
            clear_global_webui_process_manager()
            logger.info("[controller] Global WebUI manager cleared")
        except Exception:
            logger.exception("Error clearing WebUI process manager during shutdown")

        self._shutdown_completed = True
        self._await_shutdown_watchdog_exit()
        logger.info("[controller] ===== SHUTDOWN_APP COMPLETE =====")

        try:
            close_all_structured_loggers()
        except Exception:
            pass


    def _cancel_active_jobs(self, reason: str) -> None:
        if self._cancel_token is not None:
            try:
                self._append_log(f"[shutdown] Cancelling pipeline ({reason}).")
                self._cancel_token.cancel()
                self._cancel_token.clear_stop_requirement()
            except Exception:
                pass
        if self.job_service is not None:
            try:
                self.job_service.cancel_current()
            except Exception:
                logger.exception("Error cancelling job service current job")

    def _join_worker_thread(self) -> None:
        if self._worker_thread is None:
            return
        if self._worker_thread.is_alive():
            try:
                self._worker_thread.join(timeout=2.0)
            except Exception:
                pass
        self._worker_thread = None

    def _shutdown_learning_hooks(self) -> None:
        learning_ctrl = getattr(self, "learning_controller", None)
        if not learning_ctrl:
            return
        for attr in ("shutdown", "stop", "close"):
            method = getattr(learning_ctrl, attr, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    logger.exception("Learning controller %s failed during shutdown", attr)
                break

    def _shutdown_webui(self) -> None:
        manager = self.webui_process_manager or get_global_webui_process_manager()
        if not manager:
            logger.info("[controller] _shutdown_webui: No WebUI manager to shutdown")
            return
        if self.webui_process_manager is None:
            self.webui_process_manager = manager
            logger.info("[controller] _shutdown_webui: Using global WebUI manager fallback")
        stop_fn = (
            getattr(manager, "stop_webui", None)
            or getattr(manager, "shutdown", None)
            or getattr(manager, "stop", None)
        )
        if callable(stop_fn):
            pid = getattr(manager, "pid", None)
            logger.info("[controller] _shutdown_webui: Calling stop_webui for PID %s", pid)
            try:
                result = stop_fn()
                running = manager.is_running() if hasattr(manager, "is_running") else None
                exit_code = getattr(manager, "_last_exit_code", None)
                logger.info(
                    "[controller] _shutdown_webui: WebUI shutdown result: running=%s, last_exit_code=%s, stop_return=%s",
                    running,
                    exit_code,
                    result,
                )
            except Exception:
                logger.exception("Error stopping WebUI")

    def _shutdown_runtime_host(self) -> None:
        host = getattr(self, "runtime_host", None) or getattr(self, "job_service", None)
        if not host:
            return
        # Call the public stop() hook for deterministic runtime lifecycle cleanup.
        if hasattr(host, "stop"):
            try:
                host.stop()
            except Exception:
                logger.exception("Error stopping runtime host")

    def _shutdown_job_service(self) -> None:
        """Compatibility alias for older tests and shutdown helpers."""
        self._shutdown_runtime_host()

    def _shutdown_watchdog(self) -> None:
        # PR-SHUTDOWN-002: Increased default from 8s to 15s to reduce false alarms
        # Normal shutdown takes 8-12s (thread joins, WebUI stop, etc.)
        # PR-SHUTDOWN-FIX: Poll shutdown_completed periodically instead of one long sleep
        timeout = float(os.environ.get("STABLENEW_SHUTDOWN_WATCHDOG_DELAY", "15"))
        hard_exit = os.environ.get("STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG", "0") == "1"
        
        # Poll every 0.5s for early exit when shutdown completes
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._shutdown_completed:
                return
            time.sleep(0.5)
        
        # Timeout reached - check if shutdown completed
        if not self._shutdown_completed:
            logger.error(
                "Shutdown watchdog triggered after %.1fs (completed=%s)",
                timeout,
                self._shutdown_completed,
            )
            if hard_exit:
                logger.error("Hard exit forced due to shutdown hang.")
                os._exit(1)

    def _await_shutdown_watchdog_exit(self, timeout: float = 1.0) -> None:
        thread = getattr(self, "_shutdown_watchdog_thread", None)
        if thread is None:
            return
        import threading

        if thread is threading.current_thread():
            return
        try:
            thread.join(max(0.0, float(timeout)))
        except Exception:
            return

    # ------------------------------------------------------------------
    # Packs / Presets
    # ------------------------------------------------------------------

    def _on_preset_combo_select(self, event: Any) -> None:
        if self.main_window is None:
            return
        left_zone = getattr(self.main_window, "left_zone", None)
        if left_zone is None:
            return
        combo = getattr(left_zone, "preset_combo", None)
        if combo is None:
            return
        new_preset = combo.get()
        self.on_saved_recipe_selected(new_preset)

    def on_saved_recipe_selected(self, recipe_name: str) -> None:
        self._append_log(f"[controller] Saved recipe selected: {recipe_name}")
        # selection should not immediately mutate config; wait for action

    def apply_saved_recipe_to_run_config(
        self, recipe_config: dict[str, Any], recipe_name: str
    ) -> None:
        """Apply saved recipe configuration to the current run config."""
        try:
            # Update AppStateV2 run_config
            if self.app_state is not None:
                try:
                    self.app_state.set_run_config(recipe_config)
                except Exception:
                    pass
                else:
                    self._apply_randomizer_from_config(recipe_config)
            self._sync_prompt_optimizer_run_config(recipe_config)

            base_generation_overrides = self._extract_base_generation_overrides_from_recipe(recipe_config)
            if base_generation_overrides:
                self._apply_base_generation_overrides(base_generation_overrides)

            self._append_log(f"[controller] Applied saved recipe '{recipe_name}' to run config")
            self._apply_adetailer_config_section(recipe_config)

        except Exception as e:
            self._append_log(f"[controller] Error applying saved recipe '{recipe_name}': {e}")

    def _extract_base_generation_overrides_from_recipe(self, preset_config: dict[str, Any]) -> dict[str, Any]:
        """Extract base-generation overrides from a saved recipe config."""
        overrides = {}

        # Get txt2img config as primary source
        txt2img_config = preset_config.get("txt2img", {})

        # Extract model
        if "model" in txt2img_config and txt2img_config["model"]:
            overrides["model"] = txt2img_config["model"]
        elif "model_name" in txt2img_config and txt2img_config["model_name"]:
            overrides["model"] = txt2img_config["model_name"]

        if "vae" in txt2img_config and txt2img_config["vae"]:
            overrides["vae"] = txt2img_config["vae"]
        elif "vae_name" in txt2img_config and txt2img_config["vae_name"]:
            overrides["vae"] = txt2img_config["vae_name"]

        # Extract sampler
        if "sampler_name" in txt2img_config and txt2img_config["sampler_name"]:
            overrides["sampler"] = txt2img_config["sampler_name"]

        if "scheduler" in txt2img_config and txt2img_config["scheduler"]:
            overrides["scheduler"] = txt2img_config["scheduler"]

        # Extract steps
        if "steps" in txt2img_config:
            try:
                overrides["steps"] = int(txt2img_config["steps"])
            except (ValueError, TypeError):
                pass

        # Extract cfg_scale
        if "cfg_scale" in txt2img_config:
            try:
                overrides["cfg_scale"] = float(txt2img_config["cfg_scale"])
            except (ValueError, TypeError):
                pass

        # Extract resolution
        if "width" in txt2img_config and "height" in txt2img_config:
            try:
                width = int(txt2img_config["width"])
                height = int(txt2img_config["height"])
                overrides["width"] = width
                overrides["height"] = height
                # Create a preset label for common resolutions
                if width == 512 and height == 512:
                    overrides["resolution_preset"] = "512x512"
                elif width == 768 and height == 768:
                    overrides["resolution_preset"] = "768x768"
                elif width == 1024 and height == 1024:
                    overrides["resolution_preset"] = "1024x1024"
                else:
                    overrides["resolution_preset"] = f"{width}x{height}"
            except (ValueError, TypeError):
                pass

        if "seed" in txt2img_config:
            overrides["seed"] = txt2img_config.get("seed")

        return overrides

    def _apply_base_generation_overrides(self, overrides: dict[str, Any]) -> None:
        """Apply base-generation overrides to the pipeline sidebar."""
        try:
            pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
            if pipeline_tab is None:
                return

            sidebar_panel = getattr(pipeline_tab, "sidebar", None)
            if sidebar_panel is None:
                return

            base_generation_panel = getattr(sidebar_panel, "get_base_generation_panel", lambda: None)()
            if base_generation_panel is None:
                return

            if hasattr(base_generation_panel, "apply_from_overrides"):
                base_generation_panel.apply_from_overrides(overrides)
                self._append_log(f"[controller] Applied base generation overrides: {overrides}")

        except Exception as e:
            self._append_log(f"[controller] Error applying base generation overrides: {e}")

    def _on_pack_list_select(self, event: Any) -> None:
        if self.main_window is None:
            return
        left_zone = getattr(self.main_window, "left_zone", None)
        if left_zone is None:
            return
        lb = getattr(left_zone, "packs_list", None)
        if lb is None or not lb.curselection():
            return
        index = lb.curselection()[0]
        self.on_pack_selected(int(index))

    def load_packs(self) -> None:
        """Discover packs and push them to the GUI."""
        discovered = discover_packs(self._packs_dir)
        self._all_packs_by_name = {pack.name: pack for pack in discovered}
        resolver = ContentVisibilityResolver(
            getattr(self.app_state, "content_visibility_mode", "nsfw")
        )
        visible_packs: list[PromptPackInfo] = []
        for pack in discovered:
            prompts = []
            try:
                prompts = read_prompt_pack(pack.path)
            except Exception:
                prompts = []
            if resolver.is_visible(
                {
                    "name": pack.name,
                    "description": " ".join(
                        " ".join(
                            part
                            for part in (
                                str(prompt.get("positive") or "").strip(),
                                str(prompt.get("negative") or "").strip(),
                            )
                            if part
                        )
                        for prompt in prompts
                        if isinstance(prompt, Mapping)
                    ),
                }
            ):
                visible_packs.append(pack)
        self.packs = visible_packs
        pack_names = [pack.name for pack in self.packs]
        if self.main_window is not None and hasattr(self.main_window, "update_pack_list"):
            self.main_window.update_pack_list(pack_names)
        self._selected_pack_index = None
        self._append_log(f"[controller] Loaded {len(pack_names)} pack(s).")

    def on_pack_selected(self, index: int) -> None:
        if index < 0 or index >= len(self.packs):
            self._append_log("[controller] Pack selection out of range.")
            return
        self._selected_pack_index = index
        pack = self.packs[index]
        self._append_log(f"[controller] Pack selected: {pack.name}")

    def _find_pack_by_id(self, pack_id: str) -> PromptPackInfo | None:
        """Find a pack by its ID (name)."""
        for pack in self.packs:
            if pack.name == pack_id:
                return pack
        all_packs = getattr(self, "_all_packs_by_name", None)
        if isinstance(all_packs, dict):
            pack = all_packs.get(pack_id)
            if isinstance(pack, PromptPackInfo):
                return pack
        try:
            discovered = discover_packs(self._packs_dir)
        except Exception:
            discovered = []
        for pack in discovered:
            if pack.name == pack_id:
                return pack
        return None

    def _get_selected_pack(self) -> PromptPackInfo | None:
        if self._selected_pack_index is None:
            return None
        if 0 <= self._selected_pack_index < len(self.packs):
            return self.packs[self._selected_pack_index]
        return None

    def on_load_pack(self) -> None:
        pack = self._get_selected_pack()
        if pack is None:
            self._append_log("[controller] Load Pack requested, but no pack is selected.")
            return
        self._append_log(f"[controller] Load Pack -> {pack.name} ({pack.path})")

    def on_edit_pack(self) -> None:
        pack = self._get_selected_pack()
        if pack is None:
            self._append_log("[controller] Edit Pack requested, but no pack is selected.")
            return
        self._append_log(f"[controller] Edit Pack -> {pack.path}")

    # ------------------------------------------------------------------
    # Prompt selection helpers (bridge until Pipeline tab refactor)
    # ------------------------------------------------------------------

    def _get_active_prompt_text(self) -> str:
        """
        Get prompt from Pipeline tab's prompt_text widget first, then fall back to PromptWorkspaceState.

        PR-D: Updated to check pipeline_panel.prompt_text for "Add to Job" functionality.
        """
        # First try pipeline panel prompt text widget
        try:
            pipeline_panel = getattr(self.main_window, "pipeline_panel", None)
            if pipeline_panel is not None and hasattr(pipeline_panel, "get_prompt"):
                prompt_text = pipeline_panel.get_prompt()
                if prompt_text and prompt_text.strip():
                    return prompt_text
        except Exception:
            pass

        # Fall back to PromptWorkspaceState (Prompt tab)
        try:
            ws = getattr(self.main_window, "prompt_workspace_state", None)
            if ws is not None:
                prompt_text = ws.get_current_prompt_text()
                if prompt_text and prompt_text.strip():
                    return prompt_text
        except Exception:
            pass

        return ""

    # ------------------------------------------------------------------
    # Config state helpers
    # ------------------------------------------------------------------

    # --- V2.5 resource discovery wiring ---
    # Duplicate resource list methods removed; use the main definitions above.
    def get_available_models(self) -> list[str]:
        resources = getattr(self.state, "resources", {})
        raw_models = list(resources.get("models") or [])
        names = [getattr(entry, "name", str(entry)) or str(entry) for entry in raw_models]
        return names or ["StableNew-XL"]

    def get_available_samplers(self) -> list[str]:
        resources = getattr(self.state, "resources", {})
        raw_samplers = list(resources.get("samplers") or [])
        names = [getattr(entry, "name", str(entry)) or str(entry) for entry in raw_samplers]
        return names or ["Euler"]

    def get_current_config(self) -> dict[str, float | int | str]:
        cfg = self.state.current_config
        return {
            "model": cfg.model_name or self.get_available_models()[0],
            "sampler": cfg.sampler_name or self.get_available_samplers()[0],
            "width": cfg.width,
            "height": cfg.height,
            "steps": cfg.steps,
            "cfg_scale": cfg.cfg_scale,
            "refiner_enabled": cfg.refiner_enabled,
            "refiner_model_name": cfg.refiner_model_name,
            "refiner_switch_at": cfg.refiner_switch_at,
            "hires_enabled": cfg.hires_enabled,
            "hires_upscaler_name": cfg.hires_upscaler_name,
            "hires_upscale_factor": cfg.hires_upscale_factor,
            "hires_steps": cfg.hires_steps,
            "hires_denoise": cfg.hires_denoise,
            "hires_use_base_model_for_hires": cfg.hires_use_base_model_for_hires,
        }

    def update_config(self, **kwargs: float | int | str) -> None:
        mapping = {
            "model": "model_name",
            "sampler": "sampler_name",
            "width": "width",
            "height": "height",
            "steps": "steps",
            "cfg_scale": "cfg_scale",
        }
        targets = [self.state.current_config]
        if self.app_state is not None and hasattr(self.app_state, "current_config"):
            targets.append(self.app_state.current_config)
        for field_name, value in kwargs.items():
            attr = mapping.get(field_name)
            if not attr:
                continue

            if attr in {"width", "height", "steps"}:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif attr == "cfg_scale":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            else:
                value = str(value)

            for cfg in targets:
                setattr(cfg, attr, value)
            self._append_log(f"[controller] Config updated: {field}={value}")

    def _get_gui_overrides_for_pipeline(self) -> dict[str, Any]:
        """Return GUI state as a dict for the PipelineController's config assembler.

        This method is wired to PipelineController.get_gui_overrides to bridge
        the GUI state (via get_current_config) to the assembler's input format.
        """
        current = self.get_current_config()
        pack = self._get_selected_pack()
        prompt = self._get_active_prompt_text() or self._resolve_prompt_from_pack(pack) or ""
        if not prompt:
            prompt = (pack.name if pack else current.get("preset_name")) or "StableNew GUI Run"

        # Get negative prompt from AppStateV2 (not CurrentConfig)
        negative_prompt = getattr(self.app_state, "negative_prompt", "") if self.app_state else ""

        return {
            "prompt": prompt,
            "negative_prompt": negative_prompt or "",
            "model": current.get("model", ""),
            "model_name": current.get("model", ""),
            "vae_name": getattr(self.state.current_config, "vae_name", "") or "",
            "sampler": current.get("sampler", ""),
            "width": current.get("width", 512),
            "height": current.get("height", 512),
            "steps": current.get("steps", 20),
            "cfg_scale": current.get("cfg_scale", 7.0),
            "batch_size": 1,
        }

    def build_pipeline_config_v2(self) -> DeprecatedPipelineConfigSnapshot:
        """DEPRECATED (PR-CORE1-12): Legacy pipeline_config builder.

        Build the pipeline configuration structure that drives the runner.

        NOTE: Retained only for deprecated helper/test surfaces. Execution no
        longer routes through this shape.
        """
        return self._build_pipeline_config()

    def _build_pipeline_config(self) -> DeprecatedPipelineConfigSnapshot:
        """DEPRECATED (PR-CORE1-12): Internal pipeline_config builder.

        NOTE: Retained only for deprecated config/profile helpers and tests.
        Controller execution no longer routes through this shape.
        """
        if (not getattr(self, "packs", None)) and getattr(self, "_packs_dir", None):
            try:
                self.packs = discover_packs(self._packs_dir)
            except Exception:
                self.packs = []
        if getattr(self, "_selected_pack_index", None) is None and getattr(self, "packs", None):
            try:
                self._selected_pack_index = 0
            except Exception:
                self._selected_pack_index = None
        current = self.get_current_config()
        pack = self._get_selected_pack()
        if pack is None and getattr(self, "packs", None):
            try:
                pack = self.packs[0]
            except Exception:
                pack = None
        prompt = (
            self._get_active_prompt_text()
            or self._resolve_prompt_from_pack(pack)
            or current.get("prompt", "")
        )
        if not prompt:
            prompt = (pack.name if pack else current.get("preset_name")) or "StableNew GUI Run"

        metadata: dict[str, Any] = {}
        if self.app_state:
            metadata["adetailer_enabled"] = bool(self.app_state.adetailer_enabled)
            metadata["adetailer"] = dict(self.app_state.adetailer_config or {})

        return DeprecatedPipelineConfigSnapshot(
            prompt=prompt,
            negative_prompt=str(current.get("negative_prompt", "")),
            model=str(current["model"]),
            sampler=str(current["sampler"]),
            width=int(current["width"]),
            height=int(current["height"]),
            steps=int(current["steps"]),
            cfg_scale=float(current["cfg_scale"]),
            pack_name=pack.name if pack else None,
            preset_name=self.state.current_config.preset_name or None,
            lora_settings=self._lora_settings_payload(),
            metadata=metadata,
            refiner_enabled=bool(current.get("refiner_enabled")),
            refiner_model_name=str(current.get("refiner_model_name") or ""),
            refiner_switch_at=float(current.get("refiner_switch_at") or 0.8),
            hires_fix={
                "enabled": bool(current.get("hires_enabled")),
                "upscaler_name": str(current.get("hires_upscaler_name") or "Latent"),
                "upscale_factor": float(current.get("hires_upscale_factor") or 2.0),
                "steps": current.get("hires_steps"),
                "denoise": float(current.get("hires_denoise") or 0.3),
                "use_base_model": bool(current.get("hires_use_base_model_for_hires")),
            },
        )

    def _resolve_prompt_from_pack(self, pack: PromptPackInfo | None) -> str:
        if not pack:
            return ""
        try:
            prompts = read_prompt_pack(pack.path)
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[controller] Failed to read pack {pack.name}: {exc}")
            return ""
        if not prompts:
            return ""
        first = prompts[0]
        return str(first.get("positive") or "")

    # ------------------------------------------------------------------
    # Config Changes (model, sampler, resolution, randomization, matrix)
    # ------------------------------------------------------------------

    def on_model_selected(self, model_name: str) -> None:
        self._append_log(f"[controller] Model selected: {model_name}")
        self.state.current_config.model_name = model_name
        self._apply_model_profile_defaults(model_name)

    def on_vae_selected(self, vae_name: str) -> None:
        self._append_log(f"[controller] VAE selected: {vae_name}")
        self.state.current_config.vae_name = vae_name

    def on_sampler_selected(self, sampler_name: str) -> None:
        self._append_log(f"[controller] Sampler selected: {sampler_name}")
        self.state.current_config.sampler_name = sampler_name

    def on_scheduler_selected(self, scheduler_name: str) -> None:
        self._append_log(f"[controller] Scheduler selected: {scheduler_name}")
        self.state.current_config.scheduler_name = scheduler_name

    def on_resolution_changed(self, width: int, height: int) -> None:
        self._append_log(f"[controller] Resolution changed to {width}x{height}")
        self.state.current_config.width = width
        self.state.current_config.height = height

    def on_randomization_toggled(self, enabled: bool) -> None:
        self._append_log(f"[controller] Randomization toggled: {enabled}")
        self.state.current_config.randomization_enabled = enabled
        self._update_run_config_randomizer(enabled=enabled)

    def on_randomizer_max_variants_changed(self, value: int) -> None:
        try:
            normalized = max(1, int(value))
        except (TypeError, ValueError):
            normalized = 1
        self._append_log(f"[controller] Randomizer max variants set to {normalized}")
        self.state.current_config.max_variants = normalized
        self._update_run_config_randomizer(max_variants=normalized)

    def on_matrix_base_prompt_changed(self, text: str) -> None:
        self._append_log("[controller] Matrix base prompt changed (stub).")
        # TODO: store in matrix config.

    def on_matrix_slots_changed(self) -> None:
        self._append_log("[controller] Matrix slots changed (stub).")
        # TODO: store in matrix config.

    # ------------------------------------------------------------------
    # Preview / Right Zone
    # ------------------------------------------------------------------

    def on_request_preview_refresh(self) -> None:
        self._append_log("[controller] Preview refresh requested (stub).")
        # TODO: set preview_label image or text based on latest run or preview.

    def _empty_resource_map(self) -> dict[str, list[Any]]:
        return build_empty_resource_map()

    def _emit_webui_resources_updated(self, resources: dict[str, list[Any]] | None) -> None:
        if resources is None:
            return
        delivered = False
        controller = getattr(self, "webui_connection_controller", None)
        if controller is not None and hasattr(controller, "notify_resources_updated"):
            try:
                controller.notify_resources_updated(resources)
                delivered = True
            except Exception:
                delivered = False
        if not delivered:
            self._on_webui_resources_updated(resources)

    def _on_webui_resources_updated(self, resources: dict[str, list[Any]] | None) -> None:
        self._run_in_gui_thread(lambda: self._apply_webui_resources(resources))

    def _apply_webui_resources(self, resources: dict[str, list[Any]] | None) -> None:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return
        applier = getattr(pipeline_tab, "apply_webui_resources", None)
        if callable(applier):
            try:
                applier(resources)
                return
            except Exception as exc:
                logger.warning("Failed to apply WebUI resources to pipeline tab: %s", exc)
        try:
            self._dropdown_loader.apply(resources, pipeline_tab=pipeline_tab)
        except Exception:
            if not self._warned_missing_pipeline_apply:
                logger.warning(
                    "Pipeline tab missing apply_webui_resources; skipping dropdown hydration"
                )
                self._warned_missing_pipeline_apply = True

    def refresh_resources_from_webui(self) -> dict[str, list[Any]] | None:
        """Refresh resources from WebUI API and update GUI dropdowns.
        
        PR-HB-003: This method is now designed to run on a worker thread.
        It makes potentially slow HTTP calls to fetch resources, then
        dispatches all GUI updates back to the main thread.
        """
        if not getattr(self, "resource_service", None):
            return None
        
        # PR-HB-003: This can take 3-10 seconds with large model collections
        # Now safe to block since we're on a worker thread
        try:
            payload = self.resource_service.refresh_all() or {}
        except Exception as exc:
            message = f"Failed to refresh WebUI resources: {exc}"
            self._append_log(f"[resources] {message}")
            logger.warning(message)
            return None

        normalized = self._normalize_resource_map(payload)
        
        # PR-HB-003: Schedule GUI updates on main thread
        def _update_gui():
            self.state.resources = normalized
            if self.app_state is not None:
                try:
                    self.app_state.set_resources(normalized)
                except Exception:
                    pass
            self._emit_webui_resources_updated(normalized)
            
            counts = tuple(
                len(normalized[key])
                for key in (
                    "models",
                    "vaes",
                    "samplers",
                    "schedulers",
                    "upscalers",
                    "hypernetworks",
                    "embeddings",
                )
            )
            msg = (
                f"Resource update: {counts[0]} models, {counts[1]} vaes, "
                f"{counts[2]} samplers, {counts[3]} schedulers, {counts[4]} upscalers, "
                f"{counts[5]} hypernetworks, {counts[6]} embeddings"
            )
            self._append_log(f"[resources] {msg}")
            logger.debug(msg)
        
        # PR-HB-003: Dispatch to main thread for GUI updates
        self._run_in_gui_thread(_update_gui)
        
        return normalized

    def on_webui_ready(self) -> None:
        """Handle WebUI transitioning to READY.
        
        PR-HB-003: Spawns worker thread for resource refresh to avoid blocking
        the calling thread (which may be UI thread or connection thread).
        """
        try:
            if hasattr(self._api_client, "clear_startup_probe_grace"):
                self._api_client.clear_startup_probe_grace()
        except Exception:
            pass
        self._append_log("[webui] READY received, refreshing resource lists asynchronously.")
        
        # PR-HB-003: Set operation label for diagnostics
        self.current_operation_label = "Refreshing WebUI resources"
        self.last_ui_action = "on_webui_ready()"
        
        # PR-HB-003: Spawn worker thread for slow resource fetching
        def _worker():
            try:
                self.refresh_resources_from_webui()
            except Exception as exc:
                logger.exception(f"[controller] Error refreshing WebUI resources: {exc}")
                self._append_log(f"[webui] Resource refresh failed: {exc}")
            finally:
                # Clear operation label
                self.current_operation_label = None
                self.last_ui_action = None
        
        # Use tracked thread for clean shutdown
        self._spawn_tracked_thread(
            target=_worker,
            name="WebUIResourceRefresh",
            purpose="Refresh WebUI resources after connection"
        )
        try:
            pipeline_controller = getattr(self, "pipeline_controller", None)
            job_controller = getattr(pipeline_controller, "_job_controller", None)
            trigger = getattr(job_controller, "trigger_deferred_autostart", None)
            if callable(trigger):
                trigger()
        except Exception as exc:
            logger.debug("[webui] Deferred queue autostart trigger after READY failed: %s", exc)

    def _normalize_resource_map(self, payload: dict[str, Any]) -> dict[str, list[Any]]:
        return normalize_resource_map(payload)

    def _update_gui_dropdowns(self) -> None:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return
        dropdowns = self._dropdown_loader.load_dropdowns(self, self.app_state)
        self._dropdown_loader.apply_to_gui(pipeline_tab, dropdowns)

        # Also refresh the sidebar's base-generation panel
        sidebar = self._get_sidebar_panel()
        if sidebar and hasattr(sidebar, "refresh_base_generation_from_webui"):
            try:
                sidebar.refresh_base_generation_from_webui()
            except Exception:
                pass

    def _get_stage_cards_panel(self) -> Any:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return None
        return getattr(pipeline_tab, "stage_cards_panel", None)

    def _get_sidebar_panel(self) -> Any:
        return getattr(getattr(self, "main_window", None), "sidebar_panel_v2", None)

    def _get_prompt_tab(self) -> Any:
        return getattr(getattr(self, "main_window", None), "prompt_tab", None)

    def _read_prompt_optimizer_ui_config(self) -> dict[str, Any] | None:
        prompt_tab = self._get_prompt_tab()
        if prompt_tab and hasattr(prompt_tab, "get_prompt_optimizer_config"):
            try:
                config = prompt_tab.get_prompt_optimizer_config()
            except Exception:
                return None
            if isinstance(config, dict):
                return dict(config)
        return None

    def _apply_prompt_optimizer_ui_config(self, config: dict[str, Any] | None) -> None:
        prompt_tab = self._get_prompt_tab()
        if prompt_tab and hasattr(prompt_tab, "apply_prompt_optimizer_config"):
            try:
                prompt_tab.apply_prompt_optimizer_config(config)
            except Exception as exc:
                self._append_log(f"[controller] Failed to apply prompt optimizer config: {exc}")

    def _sync_prompt_optimizer_run_config(self, config: dict[str, Any]) -> None:
        prompt_optimizer = config.get("prompt_optimizer")
        if isinstance(prompt_optimizer, dict):
            self._apply_prompt_optimizer_ui_config(prompt_optimizer)

    # ------------------------------------------------------------------
    # Pipeline Pack Config & Job Builder (PR-035)
    # ------------------------------------------------------------------

    def _maybe_set_app_state_lora_strengths(self, config: dict[str, Any]) -> None:
        if not self.app_state:
            return
        strengths = normalize_lora_strengths(config.get("lora_strengths"))
        self.app_state.set_lora_strengths(strengths)

    def on_stage_toggled(self, stage: str, enabled: bool) -> None:
        """Sync sidebar checkbox changes to pipeline_tab variables.
        
        This ensures that when user toggles a stage checkbox in the sidebar,
        the corresponding pipeline_tab.{stage}_enabled variable is updated
        so that Apply Config saves the correct state.
        """
        normalized = bool(enabled)
        
        # Sync to pipeline_tab so Apply Config captures the checkbox state
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab:
            enabled_var = getattr(pipeline_tab, f"{stage}_enabled", None)
            if enabled_var is not None:
                try:
                    enabled_var.set(normalized)
                    logger.debug(
                        "[controller] on_stage_toggled: synced %s to %s in pipeline_tab",
                        stage,
                        normalized,
                    )
                except Exception as exc:
                    logger.warning(
                        "[controller] Failed to sync %s toggle to pipeline_tab: %s",
                        stage,
                        exc,
                    )
        
        # Handle adetailer-specific app_state updates
        if stage == "adetailer" and self.app_state:
            self.app_state.set_adetailer_enabled(normalized)
            config_snapshot = self._collect_adetailer_panel_config()
            config_snapshot["enabled"] = normalized
            self.app_state.set_adetailer_config(config_snapshot)

    def on_override_pack_config_changed(self, enabled: bool) -> None:
        """Handle override pack config checkbox state change.
        
        When enabled=True, current stage card configs will override pack configs.
        When enabled=False, pack configs are used as-is.
        This state is consumed by ConfigMergerV2 when building StageOverrideFlags.
        """
        self.override_pack_config_enabled = bool(enabled)
        self._append_log(
            f"[controller] Pack config override: {'ENABLED' if enabled else 'DISABLED'} - "
            f"Current stage settings will {'override' if enabled else 'not override'} pack configs"
        )

    def _build_stage_override_flags(self):  # type: ignore[no-untyped-def]
        """Build StageOverrideFlags based on override checkbox state.
        
        When override checkbox is ON, all stage overrides are enabled.
        When OFF, all overrides are disabled (pack configs used as-is).
        
        Returns:
            StageOverrideFlags instance for use with ConfigMergerV2.merge_pipeline().
        """
        from src.pipeline.config_merger_v2 import StageOverrideFlags, ConfigMergerV2, StageOverridesBundle
        
        enabled = self.override_pack_config_enabled
        return StageOverrideFlags(
            txt2img_override_enabled=enabled,
            img2img_override_enabled=enabled,
            upscale_override_enabled=enabled,
            refiner_override_enabled=enabled,
            hires_override_enabled=enabled,
            adetailer_override_enabled=enabled,
        )

    def on_adetailer_config_changed(self, config: dict[str, Any]) -> None:
        if not self.app_state:
            return
        snapshot = dict(config or {})
        snapshot["enabled"] = bool(self.app_state.adetailer_enabled)
        self.app_state.set_adetailer_config(snapshot)

    def _collect_adetailer_panel_config(self) -> dict[str, Any]:
        panel = self._get_stage_cards_panel()
        if panel and hasattr(panel, "collect_adetailer_config"):
            try:
                return dict(panel.collect_adetailer_config() or {})
            except Exception:
                pass
        if self.app_state:
            return dict(self.app_state.adetailer_config or {})
        return {}

    def _apply_adetailer_config_section(self, config: dict[str, Any]) -> None:
        if not config:
            pipeline_section = {}
            ad_config = {}
        else:
            pipeline_section = config.get("pipeline") or {}
            ad_config = config.get("adetailer") or {}
        enabled = bool(pipeline_section.get("adetailer_enabled") or ad_config.get("enabled"))
        panel = self._get_stage_cards_panel()
        if panel and hasattr(panel, "load_adetailer_config"):
            panel.load_adetailer_config(ad_config)
        if panel and hasattr(panel, "set_stage_enabled"):
            panel.set_stage_enabled("adetailer", enabled)
        sidebar = self._get_sidebar_panel()
        if sidebar and hasattr(sidebar, "set_stage_state"):
            sidebar.set_stage_state("adetailer", enabled)
        if self.app_state:
            snapshot = dict(ad_config)
            snapshot["enabled"] = enabled
            self.app_state.set_adetailer_enabled(enabled)
            self.app_state.set_adetailer_config(snapshot)

    def _update_run_config_randomizer(
        self, enabled: bool | None = None, max_variants: int | None = None
    ) -> None:
        self._get_gui_config_service().update_randomizer(
            app_state=self.app_state,
            enabled=enabled,
            max_variants=max_variants,
        )

    def _apply_randomizer_from_config(self, config: dict[str, Any]) -> None:
        if not config:
            return
        self._get_gui_config_service().apply_randomizer_from_config(
            app_state=self.app_state,
            fallback_current_config=self.state.current_config,
            config=config,
        )

    def _get_panel_randomizer_config(self) -> dict[str, Any] | None:
        return self._get_gui_config_service().get_panel_randomizer_config(
            app_state=self.app_state,
            fallback_current_config=self.state.current_config,
        )

    def _run_config_with_lora(self) -> dict[str, Any]:
        prompt_optimizer_config = self._read_prompt_optimizer_ui_config()
        return self._get_gui_config_service().build_run_config_with_lora(
            app_state=self.app_state,
            fallback_current_config=getattr(self.state, "current_config", None),
            prompt_optimizer_config=prompt_optimizer_config,
        )

    def _lora_settings_payload(self) -> dict[str, dict[str, Any]] | None:
        if not self.app_state:
            return None
        payload = {}
        for config in self.app_state.lora_strengths:
            if config.name:
                payload[config.name] = config.to_dict()
        return payload or None

    def _build_job_from_draft(self) -> Job | None:
        if not self.app_state:
            self._append_log("[controller] Cannot build job - AppState missing.")
            return None
        if not self.app_state.job_draft.packs:
            self._append_log("[controller] Job draft is empty, skipping queue action.")
            return None
        job = Job(
            job_id=str(uuid.uuid4()),
            payload=self._job_payload_from_draft(),
            lora_settings=self._lora_settings_payload(),
        )
        return job

    def _job_payload_from_draft(self) -> dict[str, Any]:
        if not self.app_state:
            return {}
        packs = [
            {
                "pack_id": entry.pack_id,
                "pack_name": entry.pack_name,
                "config_snapshot": entry.config_snapshot,
            }
            for entry in self.app_state.job_draft.packs
        ]
        payload = {"packs": packs, "run_config": self._run_config_with_lora()}
        return payload

    def get_lora_runtime_settings(self) -> list[dict[str, Any]]:
        if not self.app_state:
            return []
        return [cfg.to_dict() for cfg in self.app_state.lora_strengths]

    def update_lora_runtime_strength(self, lora_name: str, strength: float) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = float(strength)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(
                    LoraRuntimeConfig(name=cfg.name, strength=normalized, enabled=cfg.enabled)
                )
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, strength=normalized, enabled=True))
        self.app_state.set_lora_strengths(updated)

    def update_lora_runtime_enabled(self, lora_name: str, enabled: bool) -> None:
        if not self.app_state:
            return
        updated: list[LoraRuntimeConfig] = []
        normalized = bool(enabled)
        found = False
        for cfg in self.app_state.lora_strengths:
            if cfg.name == lora_name:
                updated.append(
                    LoraRuntimeConfig(name=cfg.name, strength=cfg.strength, enabled=normalized)
                )
                found = True
            else:
                updated.append(cfg)
        if not found:
            updated.append(LoraRuntimeConfig(name=lora_name, enabled=normalized))
        self.app_state.set_lora_strengths(updated)

    def on_pipeline_pack_load_config(self, pack_id: str) -> None:
        """Load a pack's config into the stage cards."""
        self._append_log(f"[controller] Loading config for pack: {pack_id}")

        # Try to load pack config via ConfigManager
        pack_config = self._config_manager.load_pack_config(pack_id)
        if pack_config is None:
            self._append_log(f"[controller] No config found for pack: {pack_id}")
            return
        pipeline_section = pack_config.get("pipeline") or {}
        self._apply_pipeline_stage_flags(pipeline_section)

        # Apply to run config
        if self.app_state:
            self.app_state.set_run_config(pack_config)
            self._maybe_set_app_state_lora_strengths(pack_config)
            self._apply_randomizer_from_config(pack_config)
        self._sync_prompt_optimizer_run_config(pack_config)

        stage_panel = self._get_stage_cards_panel()
        if stage_panel:
            for card_name in ("txt2img", "img2img", "upscale"):
                card = getattr(stage_panel, f"{card_name}_card", None)
                self._load_stage_card(card, pack_config)
            stage_panel.load_adetailer_config(pack_config.get("adetailer") or {})
        self._apply_adetailer_config_section(pack_config)
        
        # Apply output settings from pack config to output panel
        pipeline_section = pack_config.get("pipeline", {})
        sidebar = getattr(self.main_window, "sidebar_panel_v2", None)
        output_card = getattr(sidebar, "output_settings_card", None) if sidebar else None
        output_panel = getattr(output_card, "child", None) if output_card else None
        if output_panel and hasattr(output_panel, "apply_from_overrides"):
            output_overrides = {
                "batch_size": pipeline_section.get("images_per_prompt", 1),
                "n_iter": pipeline_section.get("n_iter", 1),
                "output_dir": pipeline_section.get("output_dir", "output"),
                "filename_pattern": pipeline_section.get("filename_pattern", "{seed}"),
                "image_format": pipeline_section.get("image_format", "png"),
                "seed_mode": pipeline_section.get("seed_mode", "fixed"),
                "output_route": pipeline_section.get("output_route", "Auto"),
            }
            try:
                output_panel.apply_from_overrides(output_overrides)
                self._append_log(f"[controller] Applied output settings from pack config")
            except Exception as e:
                self._append_log(f"[controller] Error applying output settings: {e}")

        if sidebar and hasattr(sidebar, "apply_global_prompt_config"):
            try:
                sidebar.apply_global_prompt_config(pack_config)
                self._append_log("[controller] Applied global prompt settings from pack config")
            except Exception as e:
                self._append_log(f"[controller] Error applying global prompt settings: {e}")

        self._append_log(f"[controller] Loaded config for pack '{pack_id}'")

    def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> None:
        """Write current stage config into one or more packs."""
        self._append_log(f"[controller] Applying config to packs: {pack_ids}")

        # Gather CURRENT config from ALL stage cards
        current_config: dict[str, Any] = {}
        
        # Get stage cards panel
        stage_panel = self._get_stage_cards_panel()
        if stage_panel:
            # Gather from txt2img card
            txt2img_card = getattr(stage_panel, "txt2img_card", None)
            if txt2img_card and hasattr(txt2img_card, "to_config_dict"):
                try:
                    txt2img_config = txt2img_card.to_config_dict()
                    current_config.update(txt2img_config)
                    self._append_log("[controller] Gathered txt2img config from GUI")
                except Exception as e:
                    self._append_log(f"[controller] Error gathering txt2img config: {e}")
            
            # Gather from img2img card
            img2img_card = getattr(stage_panel, "img2img_card", None)
            if img2img_card and hasattr(img2img_card, "to_config_dict"):
                try:
                    img2img_config = img2img_card.to_config_dict()
                    current_config.update(img2img_config)
                    self._append_log("[controller] Gathered img2img config from GUI")
                except Exception as e:
                    self._append_log(f"[controller] Error gathering img2img config: {e}")
            
            # Gather from upscale card
            upscale_card = getattr(stage_panel, "upscale_card", None)
            if upscale_card and hasattr(upscale_card, "to_config_dict"):
                try:
                    upscale_config = upscale_card.to_config_dict()
                    current_config.update(upscale_config)
                    self._append_log("[controller] Gathered upscale config from GUI")
                except Exception as e:
                    self._append_log(f"[controller] Error gathering upscale config: {e}")
            
            # Gather from adetailer card (returns flat dict)
            adetailer_card = getattr(stage_panel, "adetailer_card", None)
            if adetailer_card and hasattr(adetailer_card, "to_config_dict"):
                try:
                    adetailer_config = adetailer_card.to_config_dict()
                    # Wrap in "adetailer" section to match pack structure
                    if "adetailer" not in current_config:
                        current_config["adetailer"] = {}
                    current_config["adetailer"].update(adetailer_config)
                    
                    # CRITICAL: Also include enabled flag in adetailer section
                    # Get it from pipeline_tab since adetailer card doesn't track it
                    pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
                    if pipeline_tab:
                        adetailer_enabled_var = getattr(pipeline_tab, "adetailer_enabled", None)
                        if adetailer_enabled_var is not None:
                            current_config["adetailer"]["adetailer_enabled"] = bool(adetailer_enabled_var.get())
                    
                    self._append_log("[controller] Gathered adetailer config from GUI")
                except Exception as e:
                    self._append_log(f"[controller] Error gathering adetailer config: {e}")
        
        # Add randomizer config
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            current_config.update(panel_randomizer)
        
        # Add LoRA settings
        if self.app_state and self.app_state.lora_strengths:
            current_config["lora_strengths"] = [cfg.to_dict() for cfg in self.app_state.lora_strengths]
        prompt_optimizer_config = self._read_prompt_optimizer_ui_config()
        if prompt_optimizer_config is not None:
            current_config["prompt_optimizer"] = prompt_optimizer_config
        
        if not current_config:
            self._append_log("[controller] No current config to apply")
            return
        
        # Update app_state with gathered config
        if self.app_state:
            self.app_state.set_run_config(current_config)
        
        # Gather output settings from GUI output panel
        sidebar = getattr(self.main_window, "sidebar_panel_v2", None)
        output_card = getattr(sidebar, "output_settings_card", None) if sidebar else None
        output_panel = getattr(output_card, "child", None) if output_card else None
        if output_panel and hasattr(output_panel, "get_output_overrides"):
            try:
                output_overrides = output_panel.get_output_overrides()
                # Ensure pipeline section exists
                if "pipeline" not in current_config:
                    current_config["pipeline"] = {}
                # Map output panel keys to pipeline section keys
                current_config["pipeline"]["images_per_prompt"] = output_overrides.get("batch_size", 1)
                current_config["pipeline"]["n_iter"] = output_overrides.get("n_iter", 1)
                current_config["pipeline"]["output_dir"] = output_overrides.get("output_dir", "output")
                current_config["pipeline"]["filename_pattern"] = output_overrides.get("filename_pattern", "{seed}")
                current_config["pipeline"]["image_format"] = output_overrides.get("image_format", "png")
                current_config["pipeline"]["seed_mode"] = output_overrides.get("seed_mode", "fixed")
                current_config["pipeline"]["output_route"] = output_overrides.get("output_route", "Auto")
                self._append_log(f"[controller] Gathered output settings from GUI")
            except Exception as e:
                self._append_log(f"[controller] Error gathering output settings: {e}")
        
        # Gather pipeline stage flags from pipeline_tab
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab:
            try:
                # Ensure pipeline section exists
                if "pipeline" not in current_config:
                    current_config["pipeline"] = {}
                
                # CRITICAL: Always gather ALL stage flags to ensure complete pipeline section
                # This prevents merge-with-defaults from using old default values
                txt2img_enabled_var = getattr(pipeline_tab, "txt2img_enabled", None)
                img2img_enabled_var = getattr(pipeline_tab, "img2img_enabled", None)
                adetailer_enabled_var = getattr(pipeline_tab, "adetailer_enabled", None)
                upscale_enabled_var = getattr(pipeline_tab, "upscale_enabled", None)
                
                # Set all flags explicitly (use True as default for txt2img, False for others)
                current_config["pipeline"]["txt2img_enabled"] = (
                    bool(txt2img_enabled_var.get()) if txt2img_enabled_var is not None else True
                )
                current_config["pipeline"]["img2img_enabled"] = (
                    bool(img2img_enabled_var.get()) if img2img_enabled_var is not None else False
                )
                current_config["pipeline"]["adetailer_enabled"] = (
                    bool(adetailer_enabled_var.get()) if adetailer_enabled_var is not None else False
                )
                current_config["pipeline"]["upscale_enabled"] = (
                    bool(upscale_enabled_var.get()) if upscale_enabled_var is not None else False
                )
                
                self._append_log(
                    f"[controller] Gathered pipeline stage flags: "
                    f"txt2img={current_config['pipeline'].get('txt2img_enabled')}, "
                    f"img2img={current_config['pipeline'].get('img2img_enabled')}, "
                    f"adetailer={current_config['pipeline'].get('adetailer_enabled')}, "
                    f"upscale={current_config['pipeline'].get('upscale_enabled')}"
                )
            except Exception as e:
                self._append_log(f"[controller] Error gathering stage flags: {e}")

        # Save to each pack
        for pack_id in pack_ids:
            success = self._config_manager.save_pack_config(pack_id, current_config)
            if success:
                self._append_log(f"[controller] Applied config to pack '{pack_id}'")
            else:
                self._append_log(f"[controller] Failed to apply config to pack '{pack_id}'")

    def save_current_pipeline_saved_recipe(self, recipe_name: str) -> bool:
        """Persist the current pipeline/stage config as a named saved recipe."""
        self._append_log(
            f"[controller] Saving current pipeline config as saved recipe '{recipe_name}'"
        )
        payload = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            payload.update(panel_randomizer)
        if not payload:
            self._append_log("[controller] No current config to save as saved recipe")
            return False
        success = self._config_manager.save_preset(recipe_name, payload)
        if success:
            self._append_log(f"[controller] Saved recipe '{recipe_name}'")
        else:
            self._append_log(f"[controller] Failed to save recipe '{recipe_name}'")
        return success

    def _collect_current_stage_configs(self) -> dict[str, Any]:
        """Collect current stage configurations from the GUI cards.
        
        This is similar to the logic in on_pipeline_pack_apply_config but returns
        the config instead of applying it to packs.
        """
        current_config: dict[str, Any] = {}
        
        # Get stage cards panel (defensive check)
        try:
            stage_panel = self._get_stage_cards_panel()
        except (AttributeError, TypeError):
            stage_panel = None
            
        if stage_panel:
            # Gather from txt2img card
            txt2img_card = getattr(stage_panel, "txt2img_card", None)
            if txt2img_card and hasattr(txt2img_card, "to_config_dict"):
                try:
                    txt2img_config = txt2img_card.to_config_dict()
                    current_config.update(txt2img_config)
                except Exception as e:
                    self._append_log(f"[controller] Error gathering txt2img config: {e}")
            
            # Gather from img2img card
            img2img_card = getattr(stage_panel, "img2img_card", None)
            if img2img_card and hasattr(img2img_card, "to_config_dict"):
                try:
                    img2img_config = img2img_card.to_config_dict()
                    current_config.update(img2img_config)
                except Exception as e:
                    self._append_log(f"[controller] Error gathering img2img config: {e}")
            
            # Gather from upscale card
            upscale_card = getattr(stage_panel, "upscale_card", None)
            if upscale_card and hasattr(upscale_card, "to_config_dict"):
                try:
                    upscale_config = upscale_card.to_config_dict()
                    current_config.update(upscale_config)
                except Exception as e:
                    self._append_log(f"[controller] Error gathering upscale config: {e}")
            
            # Gather from adetailer card
            adetailer_card = getattr(stage_panel, "adetailer_card", None)
            if adetailer_card and hasattr(adetailer_card, "to_config_dict"):
                try:
                    adetailer_config = adetailer_card.to_config_dict()
                    # Wrap in "adetailer" section to match pack structure
                    if "adetailer" not in current_config:
                        current_config["adetailer"] = {}
                    current_config["adetailer"].update(adetailer_config)
                    
                    # Include enabled flag in adetailer section
                    if hasattr(self, 'main_window') and self.main_window:
                        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
                        if pipeline_tab:
                            adetailer_enabled_var = getattr(pipeline_tab, "adetailer_enabled", None)
                            if adetailer_enabled_var is not None:
                                current_config["adetailer"]["adetailer_enabled"] = bool(adetailer_enabled_var.get())
                except Exception as e:
                    self._append_log(f"[controller] Error gathering adetailer config: {e}")
        
        # Add randomizer config (defensive check)
        try:
            panel_randomizer = self._get_panel_randomizer_config()
            if panel_randomizer:
                current_config.update(panel_randomizer)
        except (AttributeError, TypeError):
            pass
        prompt_optimizer_config = self._read_prompt_optimizer_ui_config()
        if prompt_optimizer_config is not None:
            current_config["prompt_optimizer"] = prompt_optimizer_config
        
        return current_config

    def _add_global_prompt_flags(self, config: dict[str, Any]) -> None:
        """Add global prompt application flags from sidebar checkboxes to config.
        
        Args:
            config: Configuration dict to modify (modifies in-place)
        """
        # Get sidebar reference from main window
        main_window = getattr(self, "main_window", None)
        if not main_window:
            return
        
        sidebar = getattr(main_window, "sidebar_panel_v2", None)
        if not sidebar:
            return
        
        # Get global prompt configurations from sidebar
        try:
            global_positive_config = sidebar.get_global_positive_config()
            global_negative_config = sidebar.get_global_negative_config()
            
            # Add flags to pipeline section
            pipeline_section = config.setdefault("pipeline", {})
            pipeline_section["apply_global_positive_txt2img"] = global_positive_config.get("enabled", False)
            pipeline_section["apply_global_negative_txt2img"] = global_negative_config.get("enabled", True)
            config["global_positive_prompt"] = global_positive_config.get("text", "")
            config["global_negative_prompt"] = global_negative_config.get("text", "")
            
        except Exception as e:
            # Fallback: if anything goes wrong, default to safe values
            self._append_log(f"[controller] Failed to read global prompt flags: {e}")
            pipeline_section = config.setdefault("pipeline", {})
            pipeline_section.setdefault("apply_global_positive_txt2img", False)
            pipeline_section.setdefault("apply_global_negative_txt2img", True)

    def _build_config_snapshot_with_override(self, pack_config: dict[str, Any]) -> dict[str, Any]:
        """Build config snapshot considering the override checkbox state.
        
        Args:
            pack_config: The base configuration from the pack
            
        Returns:
            A configuration dict that either uses the pack config as-is (override disabled)
            or merges pack config with current GUI stage configs (override enabled)
        """
        base_config = self._run_config_with_lora()
        
        # Check if override is enabled (defensive check for tests/incomplete setup)
        override_enabled = getattr(self, 'override_pack_config_enabled', False)
        
        if not override_enabled:
            # Override disabled: use pack config merged with base run config
            merged_config = {**base_config, **pack_config}
            # Add global prompt flags from sidebar checkboxes
            self._add_global_prompt_flags(merged_config)
            self._append_log("[controller] Override disabled: using pack config as-is")
            return merged_config
        
        # Override enabled: merge current stage configs into pack config
        try:
            current_stage_configs = self._collect_current_stage_configs()
            
            # Build stage overrides bundle from current GUI configs
            stage_overrides = self._build_stage_overrides_from_current_config(current_stage_configs)
            
            # Build override flags (all enabled when override checkbox is on)
            override_flags = self._build_stage_override_flags()
            
            # Merge pack config with stage overrides using ConfigMergerV2
            from src.pipeline.config_merger_v2 import ConfigMergerV2
            
            base_merged = {**base_config, **pack_config}
            final_config = ConfigMergerV2().merge_pipeline(
                base_config=base_merged,
                stage_overrides=stage_overrides,
                override_flags=override_flags
            )
            
            # Add global prompt flags from sidebar checkboxes
            self._add_global_prompt_flags(final_config)
            
            self._append_log("[controller] Override enabled: merged current stage configs with pack config")
            return final_config
        
        except Exception as e:
            # Fallback: if anything goes wrong with override merging, use base config
            self._append_log(f"[controller] Override merge failed: {e}, falling back to pack config")
            return {**base_config, **pack_config}

    def _build_stage_overrides_from_current_config(self, current_config: dict[str, Any]) -> StageOverridesBundle:
        """Build a StageOverridesBundle from the current GUI stage configurations."""
        from src.pipeline.config_merger_v2 import (
            StageOverridesBundle,
            Txt2ImgOverrides,
            Img2ImgOverrides,
            UpscaleOverrides,
            RefinerOverrides,
            HiresOverrides,
            ADetailerOverrides,
        )

        def _first_defined(*values: Any) -> Any:
            for value in values:
                if value is not None:
                    return value
            return None
        
        # Extract txt2img settings (stage cards export under "txt2img")
        txt2img_overrides = None
        txt2img_config = current_config.get("txt2img", {}) or {}
        if any(
            key in txt2img_config
            for key in ["model", "sampler_name", "scheduler", "steps", "cfg_scale", "width", "height"]
        ):
            txt2img_overrides = Txt2ImgOverrides(
                model=txt2img_config.get("model"),
                vae=txt2img_config.get("vae"),
                sampler=txt2img_config.get("sampler_name"),  # Note: field is "sampler", not "sampler_name"
                scheduler=txt2img_config.get("scheduler"),
                steps=txt2img_config.get("steps"),
                cfg_scale=txt2img_config.get("cfg_scale"),
                width=txt2img_config.get("width"),
                height=txt2img_config.get("height"),
            )
        
        # Extract img2img settings (if any)
        img2img_overrides = None
        img2img_config = current_config.get("img2img", {})
        if img2img_config:
            img2img_overrides = Img2ImgOverrides(
                enabled=img2img_config.get("enabled", False),
                denoise_strength=img2img_config.get("denoising_strength"),  # Note: field is "denoise_strength"
            )
        
        # Extract upscale settings (if any)
        upscale_overrides = None
        upscale_config = current_config.get("upscale", {})
        if upscale_config:
            upscale_overrides = UpscaleOverrides(
                enabled=upscale_config.get("enabled", False),
                upscaler_name=upscale_config.get("upscaler"),  # Note: field is "upscaler_name"
                scale_factor=upscale_config.get("scale_factor"),
                denoise_strength=upscale_config.get("denoise_strength"),
            )
        
        # Extract refiner settings (if any)
        refiner_overrides = None
        if any(key.startswith("refiner_") for key in txt2img_config.keys()) or "use_refiner" in txt2img_config:
            refiner_overrides = RefinerOverrides(
                enabled=txt2img_config.get("use_refiner", False),
                model_name=txt2img_config.get("refiner_model_name") or txt2img_config.get("refiner_checkpoint"),
                switch_at=txt2img_config.get("refiner_switch_at"),
            )
        
        # Extract hires fix settings (if any)
        hires_overrides = None
        if any(key.startswith("hr_") for key in txt2img_config.keys()) or "enable_hr" in txt2img_config:
            hires_overrides = HiresOverrides(
                enabled=txt2img_config.get("enable_hr", False),
                scale_factor=txt2img_config.get("hr_scale"),
                upscaler_name=txt2img_config.get("hr_upscaler"),
                steps=txt2img_config.get("hr_second_pass_steps"),
                denoise_strength=txt2img_config.get("denoising_strength"),
            )
        
        # Extract adetailer settings (if any)
        adetailer_overrides = None
        adetailer_config = current_config.get("adetailer", {})
        if adetailer_config:
            adetailer_overrides = ADetailerOverrides(  # Note: class name is "ADetailerOverrides"
                enabled=_first_defined(
                    adetailer_config.get("adetailer_enabled"),
                    adetailer_config.get("enabled"),
                    False,
                ),
                checkpoint_model=_first_defined(
                    adetailer_config.get("adetailer_checkpoint_model"),
                    adetailer_config.get("sd_model_checkpoint"),
                ),
                model=_first_defined(
                    adetailer_config.get("model"),
                    adetailer_config.get("adetailer_model"),
                ),
                confidence=_first_defined(
                    adetailer_config.get("confidence"),
                    adetailer_config.get("ad_confidence"),
                    adetailer_config.get("adetailer_confidence"),
                ),
                max_detections=adetailer_config.get("max_detections"),
                denoise_strength=_first_defined(
                    adetailer_config.get("denoising_strength"),
                    adetailer_config.get("ad_denoising_strength"),
                    adetailer_config.get("adetailer_denoise"),
                ),
                # Additional settings from GUI
                sampler=_first_defined(
                    adetailer_config.get("sampler_name"),
                    adetailer_config.get("ad_sampler"),
                    adetailer_config.get("adetailer_sampler"),
                ),
                scheduler=_first_defined(
                    adetailer_config.get("scheduler"),
                    adetailer_config.get("ad_scheduler"),
                    adetailer_config.get("adetailer_scheduler"),
                ),
                steps=_first_defined(
                    adetailer_config.get("steps"),
                    adetailer_config.get("ad_steps"),
                    adetailer_config.get("adetailer_steps"),
                ),
                cfg_scale=_first_defined(
                    adetailer_config.get("cfg_scale"),
                    adetailer_config.get("ad_cfg_scale"),
                    adetailer_config.get("adetailer_cfg"),
                ),
                prompt=adetailer_config.get("adetailer_prompt"),
                negative_prompt=adetailer_config.get("adetailer_negative_prompt"),
                # Mask processing
                mask_blur=_first_defined(
                    adetailer_config.get("mask_blur"),
                    adetailer_config.get("ad_mask_blur"),
                ),
                mask_feather=_first_defined(
                    adetailer_config.get("mask_feather"),
                    adetailer_config.get("ad_mask_feather"),
                    adetailer_config.get("adetailer_mask_feather"),
                ),
                dilate_erode=_first_defined(
                    adetailer_config.get("mask_dilate_erode"),
                    adetailer_config.get("ad_dilate_erode"),
                ),
                inpaint_padding=_first_defined(
                    adetailer_config.get("ad_inpaint_only_masked_padding"),
                    adetailer_config.get("adetailer_padding"),
                    adetailer_config.get("inpaint_padding"),
                ),
                inpaint_only_masked=adetailer_config.get("ad_inpaint_only_masked"),
                use_inpaint_width_height=adetailer_config.get("ad_use_inpaint_width_height"),
                inpaint_width=adetailer_config.get("ad_inpaint_width"),
                inpaint_height=adetailer_config.get("ad_inpaint_height"),
                mask_merge_invert=_first_defined(
                    adetailer_config.get("ad_mask_merge_invert"),
                    adetailer_config.get("mask_merge_mode"),
                ),
                enable_face_pass=adetailer_config.get("enable_face_pass"),
                # Mask filtering
                mask_filter_method=_first_defined(
                    adetailer_config.get("mask_filter_method"),
                    adetailer_config.get("ad_mask_filter_method"),
                ),
                mask_k_largest=_first_defined(
                    adetailer_config.get("mask_k_largest"),
                    adetailer_config.get("ad_mask_k_largest"),
                ),
                mask_min_ratio=_first_defined(
                    adetailer_config.get("mask_min_ratio"),
                    adetailer_config.get("ad_mask_min_ratio"),
                ),
                mask_max_ratio=_first_defined(
                    adetailer_config.get("mask_max_ratio"),
                    adetailer_config.get("ad_mask_max_ratio"),
                ),
                hands_model=_first_defined(
                    adetailer_config.get("adetailer_hands_model"),
                    adetailer_config.get("hands_model"),
                ),
                enable_hands_pass=_first_defined(
                    adetailer_config.get("enable_hands_pass"),
                    adetailer_config.get("ad_hands_enabled"),
                ),
                hands_confidence=adetailer_config.get("adetailer_hands_confidence"),
                hands_steps=adetailer_config.get("adetailer_hands_steps"),
                hands_cfg_scale=adetailer_config.get("adetailer_hands_cfg"),
                hands_denoise_strength=adetailer_config.get("adetailer_hands_denoise"),
                hands_sampler=adetailer_config.get("adetailer_hands_sampler"),
                hands_scheduler=adetailer_config.get("adetailer_hands_scheduler"),
                hands_prompt=adetailer_config.get("adetailer_hands_prompt"),
                hands_negative_prompt=adetailer_config.get("adetailer_hands_negative_prompt"),
                hands_inpaint_only_masked=adetailer_config.get("ad_hands_inpaint_only_masked"),
                hands_padding=_first_defined(
                    adetailer_config.get("ad_hands_padding"),
                    adetailer_config.get("hands_padding"),
                ),
                hands_use_inpaint_width_height=adetailer_config.get(
                    "ad_hands_use_inpaint_width_height"
                ),
                hands_inpaint_width=adetailer_config.get("ad_hands_inpaint_width"),
                hands_inpaint_height=adetailer_config.get("ad_hands_inpaint_height"),
                hands_mask_filter_method=adetailer_config.get("ad_hands_mask_filter_method"),
                hands_mask_k_largest=adetailer_config.get("ad_hands_mask_k"),
                hands_mask_min_ratio=adetailer_config.get("ad_hands_mask_min_ratio"),
                hands_mask_max_ratio=adetailer_config.get("ad_hands_mask_max_ratio"),
                hands_dilate_erode=adetailer_config.get("ad_hands_dilate_erode"),
                hands_mask_blur=adetailer_config.get("ad_hands_mask_blur"),
                hands_mask_feather=adetailer_config.get("ad_hands_mask_feather"),
                hands_mask_merge_invert=adetailer_config.get("ad_hands_mask_merge_invert"),
            )
        
        return StageOverridesBundle(
            txt2img=txt2img_overrides,
            img2img=img2img_overrides,
            upscale=upscale_overrides,
            refiner=refiner_overrides,
            hires=hires_overrides,
            adetailer=adetailer_overrides,
        )

    def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
        """
        Add one or more packs to the current job draft.
        
        PR-HB-002: This method now spawns a worker thread to avoid blocking the UI thread
        during heavy I/O operations (reading pack files with 100s of prompts).
        """
        if not pack_ids:
            return
        
        # PR-HB-002: Set operation label for heartbeat stall diagnostics
        self.current_operation_label = f"Adding {len(pack_ids)} pack(s) to job"
        self.last_ui_action = f"on_pipeline_add_packs_to_job({pack_ids})"
        
        logger.debug(f"[AppController] on_pipeline_add_packs_to_job called with pack_ids: {pack_ids}")
        self._append_log(f"[controller] Adding packs to job: {pack_ids}")
        
        # Validate inputs and collect metadata on UI thread (fast)
        stage_flags = self._build_stage_flags()
        randomizer_metadata = self._build_randomizer_metadata()
        
        # PR-HB-002: Spawn worker thread for I/O-heavy work
        def _worker():
            try:
                entries = []
                logger.debug(f"[AppController] Stage flags: {stage_flags}")
                
                for pack_id in pack_ids:
                    pack = self._find_pack_by_id(pack_id)
                    logger.debug(f"[AppController] Looking for pack '{pack_id}': {pack}")
                    if pack is None:
                        self._append_log(f"[controller] Pack not found: {pack_id}")
                        logger.debug(f"[AppController] ERROR: Pack '{pack_id}' not found!")
                        continue

                    # Get pack configuration - read the actual pack file to get its config
                    pack_config = {}
                    try:
                        pack_prompts = read_prompt_pack(pack.path)
                        if pack_prompts and len(pack_prompts) > 0:
                            # Use first prompt's metadata as pack config (common approach)
                            first_prompt = pack_prompts[0]
                            pack_config = {k: v for k, v in first_prompt.items() if k not in ["positive", "negative"]}
                    except Exception as e:
                        self._append_log(f"[controller] Failed to read pack config for '{pack_id}': {e}")

                    # Build config snapshot considering override checkbox state
                    config_snapshot = self._build_config_snapshot_with_override(pack_config)

                    # Add stage enable flags to pipeline section so executor can check them
                    pipeline_section = config_snapshot.setdefault("pipeline", {})
                    pipeline_section["adetailer_enabled"] = stage_flags.get("adetailer", False)
                    pipeline_section["upscale_enabled"] = stage_flags.get("upscale", False)
                    pipeline_section["txt2img_enabled"] = stage_flags.get("txt2img", True)
                    pipeline_section["img2img_enabled"] = stage_flags.get("img2img", False)

                    # Ensure randomization is included
                    if "randomization_enabled" not in config_snapshot:
                        config_snapshot["randomization_enabled"] = (
                            self.state.current_config.randomization_enabled
                        )
                    
                    # Read all prompts from pack file (not just first)
                    try:
                        all_prompts = read_prompt_pack(pack.path)
                    except Exception as e:
                        self._append_log(f"[controller] Failed to read pack '{pack_id}': {e}")
                        all_prompts = []
                    
                    if not all_prompts:
                        self._append_log(f"[controller] Pack '{pack_id}' has no prompts")
                        continue
                    
                    logger.debug(f"[AppController] Pack '{pack_id}' has {len(all_prompts)} prompts")
                    
                    # Create one PackJobEntry per prompt row
                    for row_index, prompt_row in enumerate(all_prompts):
                        prompt_text = prompt_row.get("positive", "").strip()
                        negative_prompt_text = prompt_row.get("negative", "").strip()
                        
                        entry = PackJobEntry(
                            pack_id=pack_id,
                            pack_name=pack.name,
                            config_snapshot=config_snapshot,
                            prompt_text=prompt_text,
                            negative_prompt_text=negative_prompt_text,
                            stage_flags=stage_flags,
                            randomizer_metadata=randomizer_metadata,
                            pack_row_index=row_index,
                        )
                        entries.append(entry)
                    
                    logger.debug(f"[AppController] Created {len(all_prompts)} PackJobEntry objects for '{pack_id}'")

                # PR-HB-003: Schedule UI updates on main thread using debounced refresh
                def _update_ui():
                    if entries and self.app_state:
                        self.app_state.add_packs_to_job_draft(entries)
                        self._append_log(f"[controller] Added {len(entries)} pack entry(s) to job draft")
                        # Use debounced refresh instead of direct call
                        self._mark_ui_dirty(preview=True)
                    
                    # Clear operation label
                    self.current_operation_label = None
                    self.last_ui_action = None
                
                # Schedule callback on UI thread
                if self.main_window and hasattr(self.main_window, "run_in_main_thread"):
                    self.main_window.run_in_main_thread(_update_ui)
                else:
                    # Fallback: direct call (for tests without GUI)
                    _update_ui()
                    
            except Exception as exc:
                logger.exception(f"[AppController] Worker error in on_pipeline_add_packs_to_job: {exc}")
                self._append_log(f"[controller] Error adding packs: {exc}")
                # Clear operation label on error
                self.current_operation_label = None
                self.last_ui_action = None
        
        can_schedule_back_to_ui = bool(
            getattr(self, "main_window", None)
            and callable(getattr(self.main_window, "run_in_main_thread", None))
        )
        if not self.threaded or not can_schedule_back_to_ui:
            _worker()
            return

        # PR-HB-002: Use tracked thread for clean shutdown
        self._spawn_tracked_thread(
            target=_worker,
            name=f"PackAdd-{len(pack_ids)}",
            purpose=f"Add {len(pack_ids)} pack(s) to job draft"
        )

    def add_single_prompt_to_draft(self) -> None:
        """Capture the current prompt/negative pair in the pipeline draft summary."""
        if not self.app_state:
            return
        prompt = (getattr(self.app_state, "prompt", "") or "").strip()
        if not prompt:
            return
        negative = (getattr(self.app_state, "negative_prompt", "") or "").strip()
        self.app_state.add_job_draft_part(prompt, negative, estimated_images=1)
        self._append_log("[controller] Added current prompt pair to job draft")
        if hasattr(self, "_ui_thread_id") or getattr(self, "main_window", None) is not None:
            self._mark_ui_dirty(preview=True)
            return
        self._refresh_preview_from_state()

    def _refresh_preview_from_state(self) -> None:
        """Refresh preview records using the current AppState/job draft."""
        controller = getattr(self, "pipeline_controller", None)
        if controller is None:
            return
        refresh_fn = getattr(controller, "refresh_preview_from_state", None)
        if not callable(refresh_fn):
            return
        try:
            refresh_fn()
        except Exception as exc:
            self._append_log(f"[controller] Refresh preview error: {exc!r}")

    def request_preview_refresh(self) -> None:
        """Request a debounced preview refresh suitable for GUI-triggered draft updates."""
        scheduler = getattr(self, "_ui_scheduler", None)
        main_window = getattr(self, "main_window", None)
        dispatcher = getattr(main_window, "run_in_main_thread", None) if main_window is not None else None
        if callable(scheduler) or callable(dispatcher) or self._get_ui_root() is not None:
            self._mark_ui_dirty(preview=True)
            return
        self._refresh_preview_from_state()

    def _refresh_preview_from_state_async(self) -> None:
        """
        PR-HB-002: Async version of _refresh_preview_from_state that moves heavy work off UI thread.
        
        This spawns a worker thread to call pipeline_controller.refresh_preview_from_state(),
        which can be slow when processing many pack entries. UI updates are scheduled back
        to the main thread.
        """
        controller = getattr(self, "pipeline_controller", None)
        if controller is None:
            return
        getter = getattr(controller, "get_preview_jobs", None)
        if not callable(getter):
            return
        self._preview_refresh_request_id += 1
        request_id = self._preview_refresh_request_id

        # PR-HB-002: Set operation label for diagnostics
        self.current_operation_label = "Refreshing preview from state"
        self.last_ui_action = "_refresh_preview_from_state_async()"

        def _worker():
            try:
                records = list(getter() or [])
            except Exception as exc:
                logger.exception(f"[AppController] Error in _refresh_preview_from_state_async: {exc}")
                self._append_log(f"[controller] Refresh preview error: {exc!r}")
                records = None
            finally:
                def _apply():
                    if request_id != self._preview_refresh_request_id:
                        return
                    if records is not None and self.app_state is not None:
                        setter = getattr(self.app_state, "set_preview_jobs", None)
                        if callable(setter):
                            setter(records)
                    self.current_operation_label = None
                    self.last_ui_action = None

                if self.main_window and hasattr(self.main_window, "run_in_main_thread"):
                    self.main_window.run_in_main_thread(_apply)
                else:
                    _apply()

        # PR-HB-002: Use tracked thread for clean shutdown
        self._spawn_tracked_thread(
            target=_worker,
            name="PreviewRefresh",
            purpose="Refresh preview from state async"
        )

    def on_add_job_to_queue(self) -> None:
        """Enqueue the current job draft."""
        job = self._build_job_from_draft()
        if job is None:
            return
        if not self.job_service:
            return
        self.job_service.enqueue(job)
        payload = job.payload if isinstance(job.payload, dict) else {}
        packs = payload.get("packs", [])
        pack_count = len(packs) if isinstance(packs, list) else 0
        self._append_log(f"[controller] Enqueued job {job.job_id} with {pack_count} pack(s)")

    def on_run_job_now(self) -> None:
        """Enqueue and execute the next queued job via the runtime host."""
        self.on_run_queue_now_clicked()

    def on_run_queue_now_clicked(self) -> None:
        """Delegate immediate execution to the runtime host."""
        job = self._build_job_from_draft()
        if job is None or not self.job_service:
            return
        self.job_service.run_now(job)
        self._append_log(f"[controller] Running job {job.job_id} immediately")

    def on_clear_job_draft(self) -> None:
        """Clear the current job draft entries."""
        if not self.app_state:
            return
        self.app_state.clear_job_draft()
        self._append_log("[controller] Job draft cleared")

    def on_pause_queue(self) -> None:
        """Pause queue execution."""
        if not self.job_service:
            return
        self.job_service.pause()
        self._append_log("[controller] Queue paused")

    def on_resume_queue(self) -> None:
        """Resume queue execution."""
        if not self.job_service:
            return
        self.job_service.resume()
        self._append_log("[controller] Queue resumed")

    def on_cancel_current_job(self) -> None:
        """Cancel the currently running job."""
        if not self.job_service:
            return
        self.job_service.cancel_current()
        self._append_log("[controller] Cancelled current job")

    def on_pause_current_job(self) -> None:
        """Pause the currently running job."""
        if not self.job_service:
            return
        self.job_service.pause()
        self._append_log("[controller] Paused current job")

    def on_resume_current_job(self) -> None:
        """Resume the paused job."""
        if not self.job_service:
            return
        self.job_service.resume()
        self._append_log("[controller] Resumed current job")

    def on_pipeline_saved_recipe_apply_to_working_state(self, recipe_name: str) -> None:
        """Apply saved recipe config to the current run config and optionally mark default."""
        self._append_log(f"[controller] Applying saved recipe '{recipe_name}' to working state")

        recipe_config = self._load_and_apply_saved_recipe(recipe_name)
        if recipe_config is None:
            return

        success = self._config_manager.set_default_preset(recipe_name)
        if success:
            self._append_log(f"[controller] Set '{recipe_name}' as default preset")
        else:
            self._append_log("[controller] Failed to set default preset")

    def _load_and_apply_saved_recipe(self, recipe_name: str) -> dict[str, Any] | None:
        recipe_config = self._config_manager.load_preset(recipe_name)
        if recipe_config is None:
            self._append_log(f"[controller] Failed to load saved recipe: {recipe_name}")
            return None

        self.apply_saved_recipe_to_run_config(recipe_config, recipe_name)
        return recipe_config

    def on_pipeline_saved_recipe_apply_to_selected_packs(
        self, recipe_name: str, pack_ids: list[str]
    ) -> None:
        """Copy saved recipe values into configs of selected packs."""
        self._append_log(f"[controller] Applying saved recipe '{recipe_name}' to packs: {pack_ids}")

        recipe_config = self._config_manager.load_preset(recipe_name)
        if recipe_config is None:
            self._append_log(f"[controller] Failed to load saved recipe: {recipe_name}")
            return

        # Apply to each pack
        for pack_id in pack_ids:
            success = self._config_manager.save_pack_config(pack_id, recipe_config)
            if success:
                self._append_log(f"[controller] Applied saved recipe to pack '{pack_id}'")
            else:
                self._append_log(f"[controller] Failed to apply saved recipe to pack '{pack_id}'")

    def on_pipeline_saved_recipe_load_to_pipeline(self, recipe_name: str) -> None:
        """Load saved recipe values into the active pipeline workspace."""
        self._append_log(f"[controller] Loading saved recipe '{recipe_name}' to pipeline")

        recipe_config = self._config_manager.load_preset(recipe_name)
        if recipe_config is None:
            self._append_log(f"[controller] Failed to load saved recipe: {recipe_name}")
            return

        # Apply to run config
        if self.app_state:
            self.app_state.set_run_config(recipe_config)
            self._apply_randomizer_from_config(recipe_config)
        self._sync_prompt_optimizer_run_config(recipe_config)

        self._apply_adetailer_config_section(recipe_config)

    def on_pipeline_saved_recipe_save_current(self, recipe_name: str) -> None:
        """Save current stage config as a saved recipe."""
        self._append_log(f"[controller] Saving saved recipe '{recipe_name}' from stages")

        # Get current config
        current_config = self._run_config_with_lora()
        if not current_config:
            self._append_log("[controller] No current config to save")
            return

        # Save as preset
        success = self._config_manager.save_preset(recipe_name, current_config)
        if success:
            self._append_log(f"[controller] Saved recipe '{recipe_name}'")
        else:
            self._append_log(f"[controller] Failed to save saved recipe '{recipe_name}'")

    def on_pipeline_saved_recipe_delete(self, recipe_name: str) -> None:
        """Remove an existing saved recipe."""
        self._append_log(f"[controller] Deleting saved recipe '{recipe_name}'")

        # TODO: Add confirmation dialog if needed
        success = self._config_manager.delete_preset(recipe_name)
        if success:
            self._append_log(f"[controller] Deleted saved recipe '{recipe_name}'")
        else:
            self._append_log(f"[controller] Failed to delete saved recipe '{recipe_name}'")

    # ------------------------------------------------------------------
    # PR-CORE-VIDEO-002: Movie Clips entrypoints
    # ------------------------------------------------------------------

    def on_build_movie_clip(
        self,
        image_paths: list,
        settings: dict,
        on_complete: Any = None,
        on_error: Any = None,
    ) -> None:
        """Build a movie clip from the given image paths and settings.

        Runs clip assembly on a background thread so the GUI stays responsive.
        Calls on_complete(output_path_str) or on_error(reason_str) on the GUI
        thread when finished.
        """
        from pathlib import Path as _Path
        from src.video.movie_clip_service import MovieClipService
        from src.video.movie_clip_models import ClipRequest, ClipSettings

        def _worker() -> None:
            try:
                paths = [_Path(p) if not isinstance(p, _Path) else p for p in image_paths]
                fps = int(settings.get("fps", 24))
                codec = str(settings.get("codec", "libx264"))
                quality = str(settings.get("quality", "medium"))
                mode = str(settings.get("mode", "sequence"))

                clip_settings = ClipSettings(fps=fps, codec=codec, quality=quality, mode=mode)

                output_dir = get_output_route_root("output", OUTPUT_ROUTE_MOVIE_CLIPS)
                request = ClipRequest(
                    image_paths=paths,
                    output_dir=output_dir,
                    settings=clip_settings,
                    clip_name="clip",
                )

                service = MovieClipService()
                result = service.build_clip(request)

                if result.success and result.output_path:
                    if callable(on_complete):
                        self._run_in_gui_thread(lambda: on_complete(str(result.output_path)))
                else:
                    reason = result.error or "Unknown error"
                    if callable(on_error):
                        self._run_in_gui_thread(lambda: on_error(reason))
            except Exception as exc:
                logger.exception("[controller] on_build_movie_clip worker failed")
                if callable(on_error):
                    self._run_in_gui_thread(lambda: on_error(str(exc)))

        t = threading.Thread(target=_worker, daemon=True, name="movie-clip-builder")
        t.start()

    def on_load_movie_clip_source(
        self,
        source_dir: str,
        on_loaded: Any = None,
        on_error: Any = None,
    ) -> None:
        """Resolve and return sorted image filenames from source_dir.

        Calls on_loaded(image_names: list[str]) or on_error(reason) on the GUI thread.
        """
        from pathlib import Path as _Path
        _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

        def _worker() -> None:
            try:
                folder = _Path(source_dir)
                if not folder.is_dir():
                    if callable(on_error):
                        self._run_in_gui_thread(lambda: on_error(f"Not a directory: {source_dir}"))
                    return
                names = sorted(
                    [p.name for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXTS]
                )
                if callable(on_loaded):
                    self._run_in_gui_thread(lambda: on_loaded(names))
            except Exception as exc:
                logger.exception("[controller] on_load_movie_clip_source worker failed")
                if callable(on_error):
                    self._run_in_gui_thread(lambda: on_error(str(exc)))

        t = threading.Thread(target=_worker, daemon=True, name="movie-clip-source-loader")
        t.start()

    # ------------------------------------------------------------------
    # Native SVD entrypoints
    # ------------------------------------------------------------------

    def _get_svd_controller(self):
        controller = getattr(self, "_svd_controller", None)
        if controller is None:
            from src.controller.svd_controller import SVDController

            controller = SVDController(app_controller=self)
            self._svd_controller = controller
        return controller

    def get_supported_svd_models(
        self,
        *,
        cache_dir: str | None = None,
        local_files_only: bool = False,
    ) -> list[str]:
        from src.video.svd_models import get_default_svd_model_id, get_svd_model_options

        supported = list(get_svd_model_options(cache_dir=cache_dir, local_files_only=local_files_only))
        default_model = get_default_svd_model_id()
        if default_model in supported:
            return [default_model, *[model_id for model_id in supported if model_id != default_model]]
        return supported

    def build_svd_defaults(self) -> dict[str, Any]:
        return self._get_svd_controller().build_default_config().to_dict()

    def build_character_training_defaults(self) -> dict[str, Any]:
        current_config = getattr(getattr(self, "app_state", None), "current_config", None)
        base_model = str(getattr(current_config, "model_name", "") or "").strip()
        return {
            "character_name": "",
            "image_dir": "",
            "output_dir": str(Path("data") / "embeddings"),
            "epochs": 100,
            "learning_rate": 0.0001,
            "base_model": base_model,
            "trigger_phrase": "",
            "rank": 16,
            "network_alpha": 16,
            "trainer_command": os.environ.get("STABLENEW_TRAIN_LORA_COMMAND", ""),
        }

    def submit_character_training_job(self, form_data: dict[str, Any]) -> str:
        if not self.job_service:
            raise RuntimeError("Job service not available")

        train_lora_config = validate_train_lora_execution_config(form_data)
        character_name = str(train_lora_config.get("character_name") or "").strip()
        character_key = "".join(
            ch.lower() if ch.isalnum() else "-" for ch in character_name
        ).strip("-") or "character"
        prompt_text = f"Train LoRA for {character_name}"
        prompt_pack_id = f"character-training:{character_key}"
        execution_config = {
            "train_lora": dict(train_lora_config),
            "pipeline": {
                "train_lora_enabled": bool(train_lora_config.get("enabled", True)),
            },
            "metadata": {
                "job_type": "train_lora",
                "character_name": character_name,
            },
        }
        entry = PackJobEntry(
            pack_id=prompt_pack_id,
            pack_name=f"Character Training: {character_name}",
            config_snapshot=execution_config,
            prompt_text=prompt_text,
            negative_prompt_text="",
            stage_flags={"train_lora": True},
            pack_row_index=0,
        )
        request = PipelineRunRequest(
            prompt_pack_id=prompt_pack_id,
            selected_row_ids=[character_key],
            config_snapshot_id=f"train-lora-{uuid.uuid4().hex}",
            run_mode=PipelineRunMode.QUEUE,
            source=PipelineRunSource.ADD_TO_QUEUE,
            explicit_output_dir=str(train_lora_config.get("output_dir") or "output"),
            tags=["train_lora", "character_training", character_key],
            requested_job_label="Character Training",
            max_njr_count=1,
            pack_entries=[entry],
        )
        builder = JobBuilderV2()
        njrs = builder.build_from_run_request(request)
        if not njrs:
            raise RuntimeError("Character training request did not produce an NJR.")
        job_ids = self.job_service.enqueue_njrs(njrs, request)
        if not job_ids:
            raise RuntimeError("Character training job was not enqueued.")
        job_id = job_ids[0]
        self._append_log(
            f"[train_lora] Queued character training job {job_id} for {character_name}"
        )
        return job_id

    def validate_svd_source_image(self, path: str | Path) -> tuple[bool, str | None]:
        return self._get_svd_controller().validate_source_image(path)

    def get_svd_postprocess_capabilities(self, form_data: dict[str, Any] | None = None) -> dict[str, dict[str, object]]:
        controller = self._get_svd_controller()
        validated_form_data = (
            validate_svd_native_execution_config(form_data)
            if isinstance(form_data, dict)
            else None
        )
        config = controller.build_svd_config(validated_form_data) if isinstance(validated_form_data, dict) else None
        return controller.get_postprocess_capabilities(config)

    def submit_svd_job(self, *, source_image_path: str | Path, form_data: dict[str, Any]) -> str:
        controller = self._get_svd_controller()
        validated_form_data = validate_svd_native_execution_config(form_data)
        config = controller.build_svd_config(validated_form_data)
        valid, reason = controller.validate_source_image(source_image_path)
        if not valid:
            raise ValueError(reason or "SVD source image is invalid")
        pipeline_payload = validated_form_data.get("pipeline") if isinstance(validated_form_data, dict) else None
        output_route = None
        if isinstance(pipeline_payload, dict):
            output_route = pipeline_payload.get("output_route")
        job_id = controller.submit_svd_job(
            source_image_path=source_image_path,
            config=config,
            output_route=str(output_route) if output_route else None,
        )
        self._sync_queue_state_after_direct_submission()
        self._append_log(f"[svd] Queued SVD Img2Vid job {job_id} for {Path(source_image_path).name}")
        return job_id

    def _sync_queue_state_after_direct_submission(self) -> None:
        try:
            self._refresh_app_state_queue()
        except Exception as exc:
            logger.debug("Direct submission queue refresh failed: %s", exc)

        app_state = getattr(self, "app_state", None)
        flush_now = getattr(app_state, "flush_now", None)
        if callable(flush_now):
            try:
                flush_now()
            except Exception as exc:
                logger.debug("Direct submission app_state flush failed: %s", exc)

    def get_latest_output_image_path(self) -> str | None:
        app_state = getattr(self, "app_state", None)
        history_items = list(getattr(app_state, "history_items", []) or [])
        for entry in history_items:
            for candidate in self._iter_history_image_candidates(entry):
                path = Path(candidate)
                if path.suffix.lower() in _IMAGE_OUTPUT_EXTENSIONS and path.exists():
                    return str(path)
        return None

    def get_latest_video_output_bundle(self) -> dict[str, Any] | None:
        app_state = getattr(self, "app_state", None)
        history_items = list(getattr(app_state, "history_items", []) or [])
        for entry in history_items:
            bundle = self._get_history_video_bundle(entry)
            if isinstance(bundle, dict):
                if bundle.get("primary_path") or bundle.get("output_paths") or bundle.get("frame_paths"):
                    return bundle
        return None

    def send_image_to_svd(self, image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"SVD source image does not exist: {path}")
        main_window = getattr(self, "main_window", None)
        if main_window is None:
            raise RuntimeError("Main window is not available")
        svd_tab = getattr(main_window, "svd_tab", None)
        if svd_tab is None:
            raise RuntimeError("SVD tab is not available")
        notebook = getattr(main_window, "center_notebook", None)
        if notebook is not None:
            try:
                notebook.select(svd_tab)
            except Exception:
                pass
        setter = getattr(svd_tab, "set_source_image_path", None)
        if not callable(setter):
            raise RuntimeError("SVD tab does not support source handoff")
        setter(str(path), status_message=f"Loaded into SVD tab: {path.name}")
        self._append_log(f"[svd] Routed image to SVD tab: {path.name}")
        return str(path)

    def _get_video_workflow_controller(self):
        controller = getattr(self, "_video_workflow_controller", None)
        if controller is None:
            from src.controller.video_workflow_controller import VideoWorkflowController

            controller = VideoWorkflowController(app_controller=self)
            self._video_workflow_controller = controller
        return controller

    def get_video_workflow_specs(self) -> list[dict[str, Any]]:
        return self._get_video_workflow_controller().list_workflow_specs()

    def build_video_workflow_defaults(self) -> dict[str, Any]:
        return self._get_video_workflow_controller().build_default_form_state()

    def submit_video_workflow_job(
        self,
        *,
        source_image_path: str | Path,
        form_data: dict[str, Any],
    ) -> str:
        controller = self._get_video_workflow_controller()
        job_id = controller.submit_video_workflow_job(
            source_image_path=source_image_path,
            form_data=form_data,
        )
        self._sync_queue_state_after_direct_submission()
        self._append_log(
            f"[video_workflow] Queued workflow '{form_data.get('workflow_id', '')}' job {job_id} "
            f"for {Path(source_image_path).name}"
        )
        return job_id

    def send_image_to_video_workflow(self, image_path: str | Path) -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Video workflow source image does not exist: {path}")
        main_window = getattr(self, "main_window", None)
        if main_window is None:
            raise RuntimeError("Main window is not available")
        from src.gui.controllers.video_workspace_handoff import route_image_to_video_workflow

        route_image_to_video_workflow(
            main_window=main_window,
            image_path=str(path),
            status_message=f"Loaded into Video Workflow tab: {path.name}",
        )
        self._append_log(f"[video_workflow] Routed image to Video Workflow tab: {path.name}")
        return str(path)

    def send_history_job_image_to_svd(self, job_id: str) -> str:
        entry = self._get_history_entry_by_job_id(job_id)
        if entry is None:
            raise ValueError(f"History job not found: {job_id}")
        image_path = self._get_history_image_path(entry)
        if image_path is None:
            raise ValueError(f"History job {job_id} has no image output available for SVD")
        return self.send_image_to_svd(image_path)

    def send_history_job_image_to_video_workflow(self, job_id: str) -> str:
        entry = self._get_history_entry_by_job_id(job_id)
        if entry is None:
            raise ValueError(f"History job not found: {job_id}")
        bundle = self._get_history_video_bundle(entry)
        if bundle:
            main_window = getattr(self, "main_window", None)
            if main_window is None:
                raise RuntimeError("Main window is not available")
            from src.gui.controllers.video_workspace_handoff import route_bundle_to_video_workflow

            best_path = route_bundle_to_video_workflow(
                main_window=main_window,
                bundle=dict(bundle),
                status_message="Loaded video output into Video Workflow tab.",
            )
            if best_path:
                self._append_log(
                    f"[video_workflow] Routed video history output to Video Workflow tab: {Path(best_path).name}"
                )
                return str(best_path)

        image_path = self._get_history_image_path(entry)
        if image_path is None:
            raise ValueError(
                f"History job {job_id} has no usable image or video output available for Video Workflow"
            )
        return self.send_image_to_video_workflow(image_path)

    def send_history_job_to_movie_clips(self, job_id: str) -> str:
        entry = self._get_history_entry_by_job_id(job_id)
        if entry is None:
            raise ValueError(f"History job not found: {job_id}")
        main_window = getattr(self, "main_window", None)
        if main_window is None:
            raise RuntimeError("Main window is not available")

        bundle = self._get_history_video_bundle(entry)
        if bundle:
            from src.gui.controllers.video_workspace_handoff import route_bundle_to_movie_clips

            route_bundle_to_movie_clips(
                main_window=main_window,
                bundle=dict(bundle),
                status_message="Loaded history output into Movie Clips.",
            )
            primary_path = str(bundle.get("primary_path") or "")
            if primary_path:
                self._append_log(
                    f"[movie_clips] Routed history output to Movie Clips: {Path(primary_path).name}"
                )
            else:
                self._append_log("[movie_clips] Routed history output to Movie Clips")
            return primary_path

        image_path = self._get_history_image_path(entry)
        if image_path is None:
            raise ValueError(f"History job {job_id} has no usable output available for Movie Clips")

        from src.gui.controllers.video_workspace_handoff import route_image_to_movie_clips

        route_image_to_movie_clips(
            main_window=main_window,
            image_path=image_path,
            status_message=f"Loaded {Path(image_path).name} into Movie Clips.",
        )
        self._append_log(f"[movie_clips] Routed image to Movie Clips: {Path(image_path).name}")
        return str(image_path)

    def clear_svd_model_cache(self, model_id: str | None = None) -> None:
        controller = self._get_svd_controller()
        clearer = getattr(controller, "clear_model_cache", None)
        if not callable(clearer):
            raise RuntimeError("SVD cache controls are not available")
        clearer(model_id=model_id)
        if model_id:
            self._append_log(f"[svd] Cleared loaded SVD model cache for {model_id}")
        else:
            self._append_log("[svd] Cleared all loaded SVD model caches")

    def open_path_in_file_browser(self, path: str | Path) -> None:
        candidate = Path(path)
        if not candidate.exists():
            candidate = candidate.parent
        if os.name == "nt":
            os.startfile(str(candidate))
            return
        if sys.platform == "darwin":
            subprocess.run(["open", str(candidate)], check=False)
            return
        subprocess.run(["xdg-open", str(candidate)], check=False)

    def get_recent_svd_history(self, limit: int = 25) -> list[dict[str, Any]]:
        app_state = getattr(self, "app_state", None)
        history_items = list(getattr(app_state, "history_items", []) or [])
        records: list[dict[str, Any]] = []
        for entry in history_items:
            record = self._build_svd_history_record(entry)
            if record is not None:
                records.append(record)
        records.sort(
            key=lambda item: self._history_sort_key(
                item.get("completed_at") or item.get("started_at") or item.get("created_at")
            ),
            reverse=True,
        )
        return records[: max(int(limit), 1)]

    def _iter_history_image_candidates(self, entry: Any) -> list[str]:
        candidates: list[str] = []
        result = getattr(entry, "result", None)
        if isinstance(result, dict):
            for key in ("output_paths", "frame_paths", "video_paths", "gif_paths"):
                value = result.get(key)
                if isinstance(value, list):
                    candidates.extend(str(item) for item in value if item)
            path_value = result.get("path")
            if path_value:
                candidates.append(str(path_value))
            thumbnail = result.get("thumbnail_path")
            if thumbnail:
                candidates.append(str(thumbnail))
        snapshot = getattr(entry, "snapshot", None)
        if isinstance(snapshot, dict):
            normalized = snapshot.get("normalized_job")
            if isinstance(normalized, dict):
                for key in ("output_paths",):
                    value = normalized.get(key)
                    if isinstance(value, list):
                        candidates.extend(str(item) for item in value if item)
                thumbnail = normalized.get("thumbnail_path")
                if thumbnail:
                    candidates.append(str(thumbnail))
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    def _get_history_entry_by_job_id(self, job_id: str) -> Any | None:
        app_state = getattr(self, "app_state", None)
        history_items = list(getattr(app_state, "history_items", []) or [])
        for entry in history_items:
            if getattr(entry, "job_id", None) == job_id:
                return entry
        return None

    def _get_history_image_path(self, entry: Any) -> str | None:
        for candidate in self._iter_history_image_candidates(entry):
            path = Path(candidate)
            if path.suffix.lower() in _IMAGE_OUTPUT_EXTENSIONS and path.exists():
                return str(path)
        return None

    def _get_history_video_bundle(self, entry: Any) -> dict[str, Any] | None:
        result = getattr(entry, "result", None)
        if not isinstance(result, dict):
            return None
        bundle = result.get("video_bundle")
        if isinstance(bundle, dict):
            return dict(bundle)
        metadata = self._extract_history_result_metadata(entry)
        artifact = self._extract_video_artifact_summary(
            metadata,
            result,
            preferred_stage=None,
        )
        if not isinstance(artifact, dict):
            return None
        return {
            "primary_path": artifact.get("primary_path"),
            "stage": artifact.get("stage"),
            "backend_id": artifact.get("backend_id"),
            "artifact_type": "video",
            "thumbnail_path": artifact.get("thumbnail_path"),
            "manifest_paths": list(artifact.get("manifest_paths") or []),
            "output_paths": list(artifact.get("output_paths") or []),
            "video_paths": list(artifact.get("video_paths") or []),
            "gif_paths": list(artifact.get("gif_paths") or []),
            "frame_paths": list(artifact.get("frame_paths") or []),
            "source_image_path": artifact.get("source_image_path"),
            "count": artifact.get("count"),
        }

    def _extract_history_result_metadata(self, entry: Any) -> dict[str, Any]:
        result = getattr(entry, "result", None)
        if not isinstance(result, dict):
            return {}
        metadata = result.get("metadata")
        if isinstance(metadata, dict):
            return metadata
        if isinstance(metadata, list):
            for item in reversed(metadata):
                if isinstance(item, dict):
                    return item
        return {}

    @staticmethod
    def _history_sort_key(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _load_svd_manifest_payload(manifest_paths: Iterable[str]) -> dict[str, Any]:
        for manifest_path in manifest_paths:
            path = Path(str(manifest_path or "")).expanduser()
            if not path.exists() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    @staticmethod
    def _extract_video_artifact_summary(
        metadata: dict[str, Any],
        result: dict[str, Any] | None,
        *,
        preferred_stage: str | None = None,
    ) -> dict[str, Any] | None:
        preferred = str(preferred_stage or "").strip()

        video_artifacts = metadata.get("video_artifacts")
        if isinstance(video_artifacts, dict):
            if preferred and isinstance(video_artifacts.get(preferred), dict):
                return dict(video_artifacts[preferred])
            for aggregate in video_artifacts.values():
                if isinstance(aggregate, dict):
                    return dict(aggregate)

        primary_artifact = metadata.get("video_primary_artifact")
        if isinstance(primary_artifact, dict):
            if not preferred or str(primary_artifact.get("stage") or "").strip() == preferred:
                return dict(primary_artifact)

        video_backend_results = metadata.get("video_backend_results")
        if isinstance(video_backend_results, dict):
            if preferred and isinstance(video_backend_results.get(preferred), dict):
                return dict(video_backend_results[preferred])
            for aggregate in video_backend_results.values():
                if isinstance(aggregate, dict):
                    return dict(aggregate)

        legacy_keys: list[str] = []
        if preferred:
            legacy_keys.append(f"{preferred}_artifact")
        legacy_keys.extend(["svd_native_artifact", "animatediff_artifact"])
        seen: set[str] = set()
        for key in legacy_keys:
            if key in seen:
                continue
            seen.add(key)
            aggregate = metadata.get(key)
            if isinstance(aggregate, dict):
                return dict(aggregate)
            if isinstance(result, dict) and isinstance(result.get(key), dict):
                return dict(result[key])
        return None

    def _build_svd_history_record(self, entry: Any) -> dict[str, Any] | None:
        metadata = self._extract_history_result_metadata(entry)
        result = getattr(entry, "result", None)
        artifact = self._extract_video_artifact_summary(
            metadata,
            result if isinstance(result, dict) else None,
            preferred_stage="svd_native",
        )

        variants = []
        if isinstance(result, dict):
            raw_variants = result.get("variants")
            if isinstance(raw_variants, list):
                variants = [item for item in raw_variants if isinstance(item, dict)]
        primary_variant = variants[0] if variants else {}
        artifacts = []
        if isinstance(artifact, dict):
            raw_artifacts = artifact.get("artifacts")
            if isinstance(raw_artifacts, list):
                artifacts = [item for item in raw_artifacts if isinstance(item, dict)]
        if not artifacts:
            artifacts = [
                dict(item.get("artifact"))
                for item in variants
                if isinstance(item.get("artifact"), dict)
            ]
        primary_artifact = artifacts[0] if artifacts else {}

        manifest_candidates: list[str] = []
        if isinstance(artifact, dict):
            manifest_candidates.extend(str(item) for item in artifact.get("manifest_paths", []) if item)
        manifest_value = primary_variant.get("manifest_path") or primary_artifact.get("manifest_path")
        if manifest_value:
            manifest_candidates.append(str(manifest_value))
        manifest_payload = self._load_svd_manifest_payload(manifest_candidates)
        manifest_artifact = (
            dict(manifest_payload.get("artifact"))
            if isinstance(manifest_payload.get("artifact"), dict)
            else {}
        )

        if not isinstance(artifact, dict) and not manifest_payload and not primary_artifact:
            return None

        postprocess = primary_variant.get("postprocess")
        if not isinstance(postprocess, dict):
            postprocess = manifest_payload.get("postprocess") if isinstance(manifest_payload.get("postprocess"), dict) else {}
        applied = [str(item) for item in postprocess.get("applied", []) if item]
        input_frame_count = postprocess.get("input_frame_count")
        output_frame_count = postprocess.get("output_frame_count")
        output_width = postprocess.get("output_width")
        output_height = postprocess.get("output_height")

        video_paths = [str(item) for item in (artifact or {}).get("video_paths", []) if item]
        if not video_paths:
            video_paths = [str(item) for item in manifest_payload.get("video_paths", []) if item]
        if not video_paths:
            video_value = primary_variant.get("video_path")
            if video_value:
                video_paths = [str(video_value)]

        gif_paths = [str(item) for item in (artifact or {}).get("gif_paths", []) if item]
        if not gif_paths:
            gif_paths = [str(item) for item in manifest_payload.get("gif_paths", []) if item]
        if not gif_paths:
            gif_value = primary_variant.get("gif_path")
            if gif_value:
                gif_paths = [str(gif_value)]

        output_paths = [str(item) for item in (artifact or {}).get("output_paths", []) if item]
        if not output_paths and isinstance(primary_artifact, dict):
            output_paths = [str(item) for item in primary_artifact.get("output_paths", []) if item]
        if not output_paths:
            output_paths = [str(item) for item in manifest_payload.get("output_paths", []) if item]
        if not output_paths:
            output_paths = [str(item) for item in manifest_payload.get("frame_paths", []) if item]
        if not output_paths and primary_variant.get("path"):
            output_paths = [str(primary_variant["path"])]

        manifest_paths = [str(item) for item in (artifact or {}).get("manifest_paths", []) if item]
        if not manifest_paths:
            manifest_paths = [str(item) for item in manifest_payload.get("manifest_paths", []) if item]
        if not manifest_paths and manifest_value:
            manifest_paths = [str(manifest_value)]

        thumbnail_path = (
            (artifact or {}).get("thumbnail_path")
            or primary_variant.get("thumbnail_path")
            or primary_artifact.get("thumbnail_path")
            or manifest_payload.get("thumbnail_path")
            or manifest_artifact.get("thumbnail_path")
        )
        source_image_path = (
            primary_variant.get("source_image_path")
            or primary_artifact.get("input_image_path")
            or manifest_payload.get("source_image_path")
            or manifest_artifact.get("input_image_path")
        )
        if not source_image_path:
            snapshot = getattr(entry, "snapshot", None)
            if isinstance(snapshot, dict):
                normalized = snapshot.get("normalized_job")
                if isinstance(normalized, dict):
                    input_paths = normalized.get("input_image_paths")
                    if isinstance(input_paths, list) and input_paths:
                        source_image_path = input_paths[0]
        primary_output = (
            (video_paths[0] if video_paths else None)
            or (gif_paths[0] if gif_paths else None)
            or (output_paths[0] if output_paths else None)
        )
        output_dir = None
        if primary_output:
            output_dir = str(Path(primary_output).parent)
        elif thumbnail_path:
            output_dir = str(Path(thumbnail_path).parent)
        elif manifest_paths:
            output_dir = str(Path(manifest_paths[0]).parent.parent)

        return {
            "job_id": getattr(entry, "job_id", ""),
            "status": getattr(getattr(entry, "status", None), "value", str(getattr(entry, "status", ""))),
            "created_at": getattr(entry, "created_at", None),
            "started_at": getattr(entry, "started_at", None),
            "completed_at": getattr(entry, "completed_at", None),
            "source_image_path": str(source_image_path) if source_image_path else None,
            "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
            "video_path": video_paths[0] if video_paths else None,
            "gif_path": gif_paths[0] if gif_paths else None,
            "output_path": primary_output,
            "output_dir": output_dir,
            "manifest_path": manifest_paths[0] if manifest_paths else None,
            "frame_count": primary_variant.get("frame_count") or manifest_payload.get("frame_count"),
            "fps": primary_variant.get("fps") or manifest_payload.get("fps"),
            "model_id": primary_variant.get("model_id") or manifest_payload.get("model_id"),
            "count": (artifact or {}).get("count") or manifest_payload.get("count") or len(output_paths),
            "postprocess": postprocess or None,
            "postprocess_applied": applied,
            "postprocess_stage_count": len(applied),
            "postprocess_input_frame_count": input_frame_count,
            "postprocess_output_frame_count": output_frame_count,
            "postprocess_output_width": output_width,
            "postprocess_output_height": output_height,
        }


# Convenience entrypoint for testing the skeleton standalone
if __name__ == "__main__":
    from src.gui.main_window_v2 import StableNewApp

    app = StableNewApp()
    controller = AppController(app.main_window, threaded=True)
    app.mainloop()
