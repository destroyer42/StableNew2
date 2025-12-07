"""
StableNew - App Controller (Skeleton + CancelToken + Worker Thread Stub)

Deprecated: kept only for legacy GUI skeleton in src/gui/main_window_v2.py.
Use PipelineController + StableNewGUI for the active V2 application.

It provides:
- Lifecycle state management (IDLE, RUNNING, STOPPING, ERROR).
- Methods for GUI callbacks (run/stop/preview/etc.).
- A CancelToken + worker-thread stub for future pipeline integration.
- A 'threaded' mode for real runs and a synchronous mode for tests.

Real pipeline execution, WebUI client integration, and logging details
will be wired in later via a PipelineRunner abstraction.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, TypedDict
import os
import sys
import threading
import time
import traceback

from src.api.client import SDWebUIClient
from src.api.webui_api import WebUIAPI
from src.api.webui_resource_service import WebUIResourceService
from src.api.webui_resources import WebUIResource
from src.api.webui_process_manager import WebUIProcessManager
from src.pipeline.last_run_store_v2_5 import (
    LastRunConfigV2_5,
    LastRunStoreV2_5,
    current_config_to_last_run,
    update_current_config_from_last_run,
)
from src.gui.dropdown_loader_v2 import DropdownLoader
from src.gui.main_window_v2 import MainWindow
from src.gui.views.error_modal_v2 import ErrorModalV2
from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunner
from src.config.app_config import get_jsonl_log_config, is_debug_shutdown_inspector_enabled
from src.utils import (
    InMemoryLogHandler,
    LogContext,
    StructuredLogger,
    attach_jsonl_log_handler,
    log_with_ctx,
)
from src.utils.queue_helpers_v2 import job_to_queue_job
from src.utils.diagnostics_bundle_v2 import build_crash_bundle
from src.utils.error_envelope_v2 import (
    get_attached_envelope,
    serialize_envelope,
    UnifiedErrorEnvelope,
    wrap_exception,
)
from src.utils.config import ConfigManager, LoraRuntimeConfig, normalize_lora_strengths
from src.utils.debug_shutdown_inspector import log_shutdown_state
from src.utils.file_io import read_prompt_pack
from src.utils.prompt_packs import PromptPackInfo, discover_packs
from src.gui.app_state_v2 import PackJobEntry, AppStateV2
from src.learning.model_profiles import get_model_profile_defaults_for_model
from src.controller.pipeline_controller import PipelineController
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.queue.job_history_store import JSONLJobHistoryStore
from src.controller.job_history_service import JobHistoryService
from src.controller.job_service import JobService
from src.services.queue_store_v2 import (
    QueueSnapshotV1,
    load_queue_snapshot,
    save_queue_snapshot,
)

import logging
import uuid
logger = logging.getLogger(__name__)


class LifecycleState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


class RunMode(str, Enum):
    DIRECT = "direct"
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


@dataclass
class AppState:
    lifecycle: LifecycleState = LifecycleState.IDLE
    last_error: Optional[str] = None
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
    from src.api.webui_resources import WebUIResource
    from src.pipeline.last_run_store_v2_5 import LastRunConfigV2_5

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

    def get_gui_log_handler(self) -> Optional[InMemoryLogHandler]:
        return self.gui_log_handler
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

    """
    Orchestrates GUI events and (eventually) pipeline execution.

    Responsibilities:
        - Maintain lifecycle state (IDLE/RUNNING/STOPPING/ERROR).
        - Bridge GUI interactions to the pipeline, config, and randomizer.
        - Provide high-level methods for GUI callbacks.

    'threaded' controls whether runs happen in a worker thread (True, default)
    or synchronously (False, ideal for tests).
    """

    def __init__(
        self,
        main_window: MainWindow | None,
        pipeline_runner: Optional[PipelineRunner] = None,
        threaded: bool = True,
        packs_dir: Path | str | None = None,
        api_client: SDWebUIClient | None = None,
        structured_logger: StructuredLogger | None = None,
        webui_process_manager: WebUIProcessManager | None = None,
        config_manager: ConfigManager | None = None,
        resource_service: WebUIResourceService | None = None,
        job_service: JobService | None = None,
        pipeline_controller: PipelineController | None = None,
    ) -> None:
        self.main_window = main_window
        self.app_state = getattr(main_window, "app_state", None)
        self.state = AppState()
        self.threaded = threaded
        self._config_manager = config_manager or ConfigManager()
        self._dropdown_loader = DropdownLoader(self._config_manager)
        self._last_executor_config: dict[str, Any] | None = None
        self._last_run_snapshot: dict[str, Any] | None = None
        self._last_run_auto_restored = False
        self._last_run_store = LastRunStoreV2_5()
        self._last_run_config: RunConfigDict | None = None

        if pipeline_runner is not None:
            self.pipeline_runner = pipeline_runner
            # Still set api_client and structured_logger for PipelineController
            self._api_client = api_client or SDWebUIClient()
            self._structured_logger = structured_logger or StructuredLogger()
        else:
            self._api_client = api_client or SDWebUIClient()
            self._structured_logger = structured_logger or StructuredLogger()
            self.pipeline_runner = PipelineRunner(self._api_client, self._structured_logger)

        self._webui_api: WebUIAPI | None = None

        client = getattr(self, "_api_client", None)
        self.resource_service = resource_service or WebUIResourceService(client=client)
        self.state.resources = self._empty_resource_map()
        self.webui_process_manager = webui_process_manager
        self._cancel_token: Optional[CancelToken] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._packs_dir = Path(packs_dir) if packs_dir is not None else Path("packs")
        self._job_history_path = Path("runs") / "job_history.json"
        self.job_service = job_service or self._build_job_service()
        self._last_diagnostics_bundle: Path | None = None
        self._last_diagnostics_bundle_reason: str | None = None
        self._diagnostics_lock = threading.Lock()
        self._last_error_envelope: UnifiedErrorEnvelope | None = None
        self._error_modal: ErrorModalV2 | None = None
        self._original_excepthook = sys.excepthook
        self._original_threading_excepthook = getattr(threading, "excepthook", None)
        self._original_tk_report_callback_exception: Callable[..., Any] | None = None
        self._is_shutting_down = False
        self._shutdown_started_at: float | None = None
        self._shutdown_completed = False
        self.packs: list[PromptPackInfo] = []
        self._selected_pack_index: Optional[int] = None

        # Initialize PipelineController for modern pipeline execution (bridge)
        self.pipeline_controller = pipeline_controller or PipelineController(
            api_client=self._api_client,
            structured_logger=self._structured_logger,
            job_service=self.job_service,
            pipeline_runner=self.pipeline_runner,
        )

        # Wire GUI overrides into PipelineController so config assembler can access GUI state
        self.pipeline_controller.get_gui_overrides = self._get_gui_overrides_for_pipeline  # type: ignore[attr-defined]

        # GUI log handler for LogTracePanelV2
        self.gui_log_handler = InMemoryLogHandler(max_entries=500, level=logging.INFO)
        root_logger = logging.getLogger()
        if root_logger.level > logging.INFO or root_logger.level == logging.NOTSET:
            root_logger.setLevel(logging.INFO)
        root_logger.addHandler(self.gui_log_handler)
        json_config = get_jsonl_log_config()
        self.json_log_handler = attach_jsonl_log_handler(json_config, level=logging.INFO)

        # Let the GUI wire its callbacks to us
        if self.main_window is not None:
            self._attach_to_gui()
            if hasattr(self.main_window, "connect_controller"):
                self.main_window.connect_controller(self)
        self._setup_queue_callbacks()
        self._setup_diagnostics_hooks()

    def run_pipeline_v2_bridge(self) -> bool:
        """
        Optional hook into the modern PipelineController path.

        Returns True if a PipelineController was attached and called successfully.
        """
        controller = getattr(self, "pipeline_controller", None)
        if controller is None:
            return False

        start_fn = getattr(controller, "start_pipeline", None)
        if not callable(start_fn):
            return False

        try:
            start_fn()
            return True
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[controller] PipelineController bridge error: {exc!r}")
            return False

    def start_run_v2(self) -> Any:
        """
        Preferred, backward-compatible entrypoint for the V2 pipeline path.

        Tries the PipelineController bridge first; on failure, falls back to legacy start_run().
        """
        self._ensure_run_mode_default("run")
        return self._start_run_v2(RunMode.DIRECT, RunSource.RUN_BUTTON)

    def _ensure_run_mode_default(self, button_source: str) -> None:
        pipeline_state = getattr(self.app_state, "pipeline_state", None)
        if pipeline_state is None:
            return
        current = (getattr(pipeline_state, "run_mode", None) or "").strip().lower()
        if current in {"direct", "queue"}:
            return
        if button_source == "run":
            pipeline_state.run_mode = "direct"
            self._append_log("[controller] Defaulting run_mode to 'direct' for Run button.")
        elif button_source == "run_now":
            pipeline_state.run_mode = "queue"
            self._append_log("[controller] Defaulting run_mode to 'queue' for Run Now button.")
        elif button_source == "add_to_queue":
            pipeline_state.run_mode = "queue"
            self._append_log("[controller] Defaulting run_mode to 'queue' for Add to Queue button.")

    def _build_run_config(self, mode: RunMode, source: RunSource) -> RunConfigDict:
        cfg: RunConfigDict = {"run_mode": mode.value, "source": source.value}
        prompt_source = "manual"
        prompt_pack_id = ""
        job_draft = getattr(self.app_state, "job_draft", None)
        if job_draft is not None:
            pack_id = getattr(job_draft, "pack_id", "") or ""
            if pack_id:
                prompt_source = "pack"
                prompt_pack_id = pack_id
        cfg["prompt_source"] = prompt_source
        if prompt_pack_id:
            cfg["prompt_pack_id"] = prompt_pack_id
        pipeline_state = getattr(self.app_state, "pipeline_state", None)
        if pipeline_state is not None:
            snapshot = {
                "run_mode": getattr(pipeline_state, "run_mode", None),
                "stage_txt2img_enabled": getattr(pipeline_state, "stage_txt2img_enabled", None),
                "stage_img2img_enabled": getattr(pipeline_state, "stage_img2img_enabled", None),
                "stage_upscale_enabled": getattr(pipeline_state, "stage_upscale_enabled", None),
                "stage_adetailer_enabled": getattr(pipeline_state, "stage_adetailer_enabled", None),
            }
            cfg["pipeline_state_snapshot"] = snapshot
        return cfg

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
        pipeline_state = getattr(self.app_state, "pipeline_state", None)
        if pipeline_state is not None:
            try:
                pipeline_state.run_mode = mode.value
            except Exception:
                pass
        run_config = self._build_run_config(mode, source)
        self._last_run_config = dict(run_config)
        controller = getattr(self, "pipeline_controller", None)
        if controller is not None:
            start_fn = getattr(controller, "start_pipeline", None)
            if callable(start_fn):
                try:
                    self._append_log(
                        f"[controller] _start_run_v2 via PipelineController.start_pipeline "
                        f"(mode={mode.value}, source={source.value})"
                    )
                    return start_fn(run_config=run_config)
                except TypeError:
                    self._append_log(
                        "[controller] PipelineController.start_pipeline does not accept run_config; calling without it."
                    )
                    return start_fn()
                except Exception as exc:  # noqa: BLE001
                    self._append_log(f"[controller] _start_run_v2 bridge error: {exc!r}")
        self._append_log("[controller] _start_run_v2 falling back to legacy start_run().")
        legacy = getattr(self, "start_run", None)
        if callable(legacy):
            return legacy()
        return None

    def on_run_job_now_v2(self) -> Any:
        """
        V2 entrypoint for "Run Now": prefer the queue-backed handler, fall back to start_run_v2().
        """
        self._ensure_run_mode_default("run_now")
        handler_names = ("on_run_job_now", "on_run_queue_now_clicked")
        for name in handler_names:
            handler = getattr(self, name, None)
            if callable(handler):
                try:
                    self._append_log(f"[controller] on_run_job_now_v2 using {name}.")
                    return handler()
                except Exception as exc:  # noqa: BLE001
                    self._append_log(f"[controller] on_run_job_now_v2 handler {name} error: {exc!r}")
                    break

        self._ensure_run_mode_default("run_now")
        return self._start_run_v2(RunMode.QUEUE, RunSource.RUN_NOW_BUTTON)

    def on_add_job_to_queue_v2(self) -> None:
        """Queue-first Add-to-Queue entrypoint; safe no-op if none available."""
        self._ensure_run_mode_default("add_to_queue")
        run_config = self._build_run_config(RunMode.QUEUE, RunSource.ADD_TO_QUEUE_BUTTON)
        self._last_run_config = dict(run_config)
        pipeline_ctrl = getattr(self, "pipeline_controller", None)
        if pipeline_ctrl and hasattr(pipeline_ctrl, "submit_preview_jobs_to_queue"):
            try:
                count = pipeline_ctrl.submit_preview_jobs_to_queue(
                    source="gui",
                    prompt_source="pack",
                )
                if count > 0:
                    self._append_log(f"[controller] Submitted {count} job(s) from preview to queue")
                    return
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[controller] submit_preview_jobs_to_queue error: {exc!r}")

        handler_names = ("on_add_job_to_queue", "on_add_to_queue")
        for name in handler_names:
            handler = getattr(self, name, None)
            if callable(handler):
                try:
                    self._append_log(f"[controller] on_add_job_to_queue_v2 using {name}.")
                    handler()
                    return
                except Exception as exc:  # noqa: BLE001
                    self._append_log(
                        f"[controller] on_add_job_to_queue_v2 handler {name} error: {exc!r}"
                    )
                    return

        self._ensure_run_mode_default("add_to_queue")
        self._start_run_v2(RunMode.QUEUE, RunSource.ADD_TO_QUEUE_BUTTON)

    def set_main_window(self, main_window: MainWindow) -> None:
        """Set the main window and wire GUI callbacks."""
        self.main_window = main_window
        self.app_state = getattr(main_window, "app_state", None)
        self._attach_to_gui()
        if hasattr(self.main_window, "connect_controller"):
            self.main_window.connect_controller(self)

        # Initial status
        self._update_status("Idle")
        self.load_packs()

    # ------------------------------------------------------------------
    # GUI Wiring
    # ------------------------------------------------------------------

    def _attach_to_gui(self) -> None:
        mw = self.main_window
        if mw is None:
            return
        missing = [name for name in ("header_zone", "left_zone", "bottom_zone") if not hasattr(mw, name)]
        if missing:
            print(f"AppController._attach_to_gui: main_window missing zones {missing}; deferring wiring")
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

        # Initial API status (placeholder)
        if bottom is not None and hasattr(bottom, "api_status_label"):
            bottom.api_status_label.configure(text="API: Unknown")

        # Flush deferred status if any
        if getattr(self, "_pending_status_text", None):
            self._update_status(self._pending_status_text)

    # ------------------------------------------------------------------
    # Queue & JobService helpers (PR-039B)
    # ------------------------------------------------------------------

    def _single_node_runner_factory(
        self,
        job_queue: JobQueue,
        run_callable: Callable[[Job], dict] | None,
    ) -> SingleNodeJobRunner:
        """Factory that produces the SingleNodeJobRunner used by JobService."""

        return SingleNodeJobRunner(
            job_queue,
            run_callable=run_callable or self._execute_job,
            poll_interval=0.05,
        )

    def _build_job_service(self) -> JobService:
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
        )

    def _setup_queue_callbacks(self) -> None:
        if not self.job_service:
            return
        self.job_service.register_callback(JobService.EVENT_QUEUE_UPDATED, self._on_queue_updated)
        self.job_service.register_callback(JobService.EVENT_QUEUE_STATUS, self._on_queue_status_changed)
        self.job_service.register_callback(JobService.EVENT_JOB_STARTED, self._on_job_started)
        self.job_service.register_callback(JobService.EVENT_JOB_FINISHED, self._on_job_finished)
        self.job_service.register_callback(JobService.EVENT_JOB_FAILED, self._on_job_failed)
        self.job_service.register_callback(JobService.EVENT_QUEUE_EMPTY, self._on_queue_empty)
        self._refresh_job_history()
        # PR-GUI-F3: Load persisted queue state on startup
        self._load_queue_state()

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
            JobService.EVENT_WATCHDOG_VIOLATION, self._on_watchdog_violation_event
        )

    # ------------------------------------------------------------------
    # PR-GUI-F3: Queue persistence helpers
    # ------------------------------------------------------------------

    def _load_queue_state(self) -> None:
        """Load persisted queue state on startup.
        
        PR-GUI-F3: Restores queue jobs and control flags from disk.
        """
        snapshot = load_queue_snapshot()
        if snapshot is None:
            return

        # Restore auto_run and paused flags to AppState
        if self.app_state:
            self.app_state.set_auto_run_queue(snapshot.auto_run_enabled)
            self.app_state.set_is_queue_paused(snapshot.paused)

        # Note: We can't easily restore jobs to the V1 JobQueue since it uses
        # a different job model. This is a limitation of the current architecture.
        # The V1 queue doesn't persist job payloads - they're typically callables.
        # For PR-GUI-F3, we'll at least restore the flags.
        logger.info(
            f"Restored queue state: auto_run={snapshot.auto_run_enabled}, "
            f"paused={snapshot.paused}, {len(snapshot.jobs)} jobs (jobs not restored in V1 queue)"
        )

    def _save_queue_state(self) -> None:
        """Save current queue state for persistence.
        
        PR-GUI-F3: Persists queue control flags to disk.
        Note: V1 JobQueue jobs contain callables and can't be serialized.
        """
        auto_run = getattr(self.app_state, "auto_run_queue", False) if self.app_state else False
        paused = getattr(self.app_state, "is_queue_paused", False) if self.app_state else False

        snapshot = QueueSnapshotV1(
            jobs=[],  # V1 queue jobs can't be serialized (contain callables)
            auto_run_enabled=auto_run,
            paused=paused,
        )
        save_queue_snapshot(snapshot)

    def _execute_job(self, job: Job) -> dict[str, Any]:
        self._append_log(f"[queue] Executing job {job.job_id} with payload {job.payload!r}")

        payload = getattr(job, "payload", None)

        if callable(payload):
            try:
                result = payload()
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[queue] Callable payload for job {job.job_id} raised: {exc!r}")
                raise
            return {
                "job_id": job.job_id,
                "status": "executed",
                "mode": "callable",
                "result": result,
            }

        if not isinstance(payload, dict):
            return {
                "job_id": job.job_id,
                "status": "executed",
                "mode": "opaque",
                "payload_type": type(payload).__name__,
            }

        packs = payload.get("packs") or []
        run_config = payload.get("run_config") or {}

        if not packs:
            return {
                "job_id": job.job_id,
                "status": "executed",
                "mode": "prompt_pack_batch",
                "total_entries": 0,
                "results": [],
            }

        results: list[dict[str, Any]] = []
        for idx, pack in enumerate(packs):
            pack_id = pack.get("pack_id", "")
            pack_name = pack.get("pack_name", "")
            cfg_snapshot = pack.get("config_snapshot") or {}
            variant_index = pack.get("variant_index") or cfg_snapshot.get("variant_index") or idx
            try:
                entry_result = self._execute_pack_entry(
                    pack_id=pack_id,
                    pack_name=pack_name,
                    cfg_snapshot=cfg_snapshot,
                    run_config=run_config,
                    variant_index=variant_index,
                )
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[queue] Error while executing pack {pack_id or pack_name}: {exc!r}")
                entry_result = self._build_pack_result(
                    pack_id=pack_id,
                    pack_name=pack_name,
                    variant_index=variant_index,
                    prompt=cfg_snapshot.get("prompt", ""),
                    negative_prompt=cfg_snapshot.get("negative_prompt", ""),
                    params=self._merge_run_params(cfg_snapshot, run_config),
                    pipeline_mode=None,
                    run_result=None,
                    status="error",
                    error=str(exc),
                )
            results.append(entry_result)

        return {
            "job_id": job.job_id,
            "status": "executed",
            "mode": "prompt_pack_batch",
            "total_entries": len(packs),
            "results": results,
        }

    def _execute_pack_entry(
        self,
        *,
        pack_id: str,
        pack_name: str,
        cfg_snapshot: dict[str, Any],
        run_config: dict[str, Any],
        variant_index: int | None = None,
    ) -> dict[str, Any]:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)

        prompt = self._derive_prompt(cfg_snapshot, run_config)
        negative_prompt = self._derive_negative_prompt(cfg_snapshot, run_config)

        if pipeline_tab and hasattr(pipeline_tab, "prompt_text"):
            try:
                pipeline_tab.prompt_text.delete(0, "end")
                if prompt:
                    pipeline_tab.prompt_text.insert(0, prompt)
            except Exception:
                pass

        self._apply_pipeline_tab_config(pipeline_tab, cfg_snapshot, run_config)

        params = self._merge_run_params(cfg_snapshot, run_config)

        run_result = self.run_pipeline()
        pipeline_mode = run_result.get("mode") if isinstance(run_result, dict) else None

        return self._build_pack_result(
            pack_id=pack_id,
            pack_name=pack_name,
            variant_index=variant_index,
            prompt=prompt,
            negative_prompt=negative_prompt,
            params=params,
            pipeline_mode=pipeline_mode,
            run_result=run_result,
            status="ok",
        )

    def _build_pack_result(
        self,
        *,
        pack_id: str,
        pack_name: str,
        variant_index: int | None,
        prompt: str,
        negative_prompt: str,
        params: dict[str, Any],
        pipeline_mode: str | None,
        run_result: dict[str, Any] | None,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        outputs = self._collect_outputs(run_result)
        return {
            "pack_id": pack_id,
            "pack_name": pack_name,
            "variant_index": variant_index,
            "status": status,
            "error": error,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "pipeline_mode": pipeline_mode,
            "params": params,
            "outputs": outputs,
            "raw_result": run_result,
        }

    def _collect_outputs(self, run_result: dict[str, Any] | None) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        if not isinstance(run_result, dict):
            return outputs

        images: list[Any] = []

        def gather(entry: Any) -> None:
            if isinstance(entry, dict):
                imgs = entry.get("images")
                if isinstance(imgs, list):
                    images.extend(imgs)

        gather(run_result.get("response") or run_result.get("raw") or run_result)
        for entry in run_result.get("upscaled") or []:
            gather(entry)

        for idx in range(len(images)):
            outputs.append({"path": None, "index": idx})

        return outputs

    def _apply_pipeline_tab_config(
        self,
        pipeline_tab: Any | None,
        cfg_snapshot: dict[str, Any],
        run_config: dict[str, Any],
    ) -> None:
        if pipeline_tab is None:
            return

        def _set_if_has(attr: str, value: Any) -> None:
            if value is None:
                return
            target = getattr(pipeline_tab, attr, None)
            if target is None:
                return
            try:
                if hasattr(target, "set"):
                    target.set(value)
            except Exception:
                pass

        for key, attr in [
            ("txt2img_enabled", "txt2img_enabled"),
            ("img2img_enabled", "img2img_enabled"),
            ("adetailer_enabled", "adetailer_enabled"),
            ("upscale_enabled", "upscale_enabled"),
        ]:
            _set_if_has(attr, cfg_snapshot.get(key, run_config.get(key)))

        for key, attr in [
            ("upscale_factor", "upscale_factor"),
            ("upscale_model", "upscale_model"),
            ("upscale_tile_size", "upscale_tile_size"),
        ]:
            _set_if_has(attr, cfg_snapshot.get(key, run_config.get(key)))

        input_image_path = cfg_snapshot.get("input_image_path") or run_config.get("input_image_path")
        if input_image_path and hasattr(pipeline_tab, "input_image_path"):
            try:
                pipeline_tab.input_image_path = input_image_path
            except Exception:
                pass

    def _derive_prompt(self, cfg_snapshot: dict[str, Any], run_config: dict[str, Any]) -> str:
        return (
            cfg_snapshot.get("prompt")
            or cfg_snapshot.get("positive_prompt")
            or run_config.get("prompt", "")
        ) or ""

    def _derive_negative_prompt(self, cfg_snapshot: dict[str, Any], run_config: dict[str, Any]) -> str:
        return (
            cfg_snapshot.get("negative_prompt") or run_config.get("negative_prompt", "")
        ) or ""

    def _merge_run_params(self, cfg_snapshot: dict[str, Any], run_config: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        params["model"] = (
            cfg_snapshot.get("model")
            or cfg_snapshot.get("model_name")
            or run_config.get("model")
            or run_config.get("model_name")
            or ""
        )
        params["sampler"] = (
            cfg_snapshot.get("sampler")
            or cfg_snapshot.get("sampler_name")
            or run_config.get("sampler")
            or run_config.get("sampler_name")
            or ""
        )
        params["steps"] = self._safe_int(cfg_snapshot.get("steps") or run_config.get("steps"), 0)
        params["width"] = self._safe_int(cfg_snapshot.get("width") or run_config.get("width"), 512)
        params["height"] = self._safe_int(cfg_snapshot.get("height") or run_config.get("height"), 512)
        params["cfg_scale"] = self._safe_float(
            cfg_snapshot.get("cfg_scale") or run_config.get("cfg_scale"), 7.0
        )
        params["seed"] = cfg_snapshot.get("seed") or run_config.get("seed")
        params["upscale_factor"] = float(
            cfg_snapshot.get("upscale_factor")
            or run_config.get("upscale_factor")
            or 2.0
        )
        params["upscale_model"] = (
            cfg_snapshot.get("upscale_model")
            or cfg_snapshot.get("upscaler")
            or run_config.get("upscale_model")
            or ""
        )
        params["upscale_tile_size"] = self._safe_int(
            cfg_snapshot.get("upscale_tile_size") or run_config.get("upscale_tile_size"), 0
        )
        lora_settings = cfg_snapshot.get("lora_strengths") or run_config.get("lora_strengths") or []
        params["lora"] = [
            dict(item) if isinstance(item, dict) else item for item in lora_settings
        ]
        params["randomization_enabled"] = bool(
            cfg_snapshot.get("randomization_enabled") or run_config.get("randomization_enabled")
        )
        return params

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

    def _on_queue_updated(self, summaries: list[str]) -> None:
        if not self.app_state:
            return
        self._refresh_app_state_queue()

    def _on_queue_status_changed(self, status: str) -> None:
        if not self.app_state:
            return
        self.app_state.set_queue_status(status)

    def _on_job_started(self, job: Job) -> None:
        if not self.app_state:
            return
        self._set_running_job(job)

    def _on_job_finished(self, job: Job) -> None:
        if self.app_state:
            self.app_state.set_running_job(None)
        self._refresh_job_history()

    def _on_job_failed(self, job: Job) -> None:
        if self.app_state:
            self.app_state.set_running_job(None)
        self._refresh_job_history()
        try:
            self._handle_structured_job_failure(job)
        except Exception:
            pass

    def _on_queue_empty(self) -> None:
        if self.app_state:
            self.app_state.set_queue_status("idle")

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
        jobs = self._list_service_jobs()
        queue_jobs = [job_to_queue_job(job) for job in jobs]
        summaries = [queue_job.get_display_summary() for queue_job in queue_jobs]
        self.app_state.set_queue_items(summaries)
        self.app_state.set_queue_jobs(queue_jobs)

    def _list_service_jobs(self) -> list[Job]:
        queue = getattr(self.job_service, "queue", None)
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
            self.app_state.set_running_job(None)
            return
        queue_job = job_to_queue_job(job)
        self.app_state.set_running_job(queue_job)

    # ------------------------------------------------------------------
    # PR-203: Queue Manipulation APIs
    # ------------------------------------------------------------------

    def on_queue_move_up_v2(self, job_id: str) -> bool:
        """Move a job up in the queue."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "queue", None)
        if queue and hasattr(queue, "move_up"):
            try:
                return bool(queue.move_up(job_id))
            except Exception as exc:
                self._append_log(f"[controller] on_queue_move_up_v2 error: {exc!r}")
        return False

    def on_queue_move_down_v2(self, job_id: str) -> bool:
        """Move a job down in the queue."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "queue", None)
        if queue and hasattr(queue, "move_down"):
            try:
                return bool(queue.move_down(job_id))
            except Exception as exc:
                self._append_log(f"[controller] on_queue_move_down_v2 error: {exc!r}")
        return False

    def on_queue_remove_job_v2(self, job_id: str) -> bool:
        """Remove a job from the queue."""
        if not self.job_service:
            return False
        queue = getattr(self.job_service, "queue", None)
        if queue and hasattr(queue, "remove"):
            try:
                return queue.remove(job_id) is not None
            except Exception as exc:
                self._append_log(f"[controller] on_queue_remove_job_v2 error: {exc!r}")
        return False

    def on_queue_clear_v2(self) -> int:
        """Clear all jobs from the queue."""
        if not self.job_service:
            return 0
        queue = getattr(self.job_service, "queue", None)
        if queue and hasattr(queue, "clear"):
            try:
                result = int(queue.clear())
                self._save_queue_state()
                return result
            except Exception as exc:
                self._append_log(f"[controller] on_queue_clear_v2 error: {exc!r}")
        return 0

    def on_pause_queue_v2(self) -> None:
        """Pause queue processing."""
        if self.app_state:
            self.app_state.set_is_queue_paused(True)
        if self.job_service:
            queue = getattr(self.job_service, "queue", None)
            if queue and hasattr(queue, "pause"):
                queue.pause()
        self._save_queue_state()

    def on_resume_queue_v2(self) -> None:
        """Resume queue processing."""
        if self.app_state:
            self.app_state.set_is_queue_paused(False)
        if self.job_service:
            queue = getattr(self.job_service, "queue", None)
            if queue and hasattr(queue, "resume"):
                queue.resume()
        self._save_queue_state()

    def on_set_auto_run_v2(self, enabled: bool) -> None:
        """Set auto-run queue enabled/disabled."""
        if self.app_state:
            self.app_state.set_auto_run_queue(enabled)
        if self.job_service:
            queue = getattr(self.job_service, "queue", None)
            if queue and hasattr(queue, "auto_run_enabled"):
                queue.auto_run_enabled = enabled
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
            self.job_service.cancel_current()
            queue = getattr(self.job_service, "queue", None)
            if queue and hasattr(queue, "cancel_running_job"):
                queue.cancel_running_job(return_to_queue=True)
            # Also trigger the cancel token if available
            cancel_token = getattr(self, "_cancel_token", None)
            if cancel_token and hasattr(cancel_token, "cancel"):
                cancel_token.cancel()
        self._save_queue_state()

    def on_queue_send_job_v2(self) -> None:
        """Manually dispatch the next job from the queue.
        
        PR-GUI-F3: Send Job button - dispatches top of queue immediately.
        Respects pause state (if paused, does nothing).
        """
        if not self.job_service:
            return
        queue = getattr(self.job_service, "queue", None)
        if queue and hasattr(queue, "start_next_job"):
            # Only dispatch if not paused
            if not getattr(queue, "is_paused", False):
                queue.start_next_job()

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
            entries = store.list_jobs(limit=limit or 20)
        except Exception:
            entries = []
        self.app_state.set_history_items(entries)

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

    def on_advanced_prompt_applied(self, new_prompt: str, negative_prompt: Optional[str] = None) -> None:
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

    def _set_lifecycle(self, new_state: LifecycleState, error: Optional[str] = None) -> None:
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
        self, new_state: LifecycleState, error: Optional[str] = None
    ) -> None:
        """
        Schedule lifecycle change on the Tk main thread if threaded.
        For tests (threaded=False), apply immediately.
        """
        if not self.threaded:
            self._set_lifecycle(new_state, error)
            return

        if self.main_window is not None:
            self.main_window.after(0, lambda: self._set_lifecycle(new_state, error))

    def _update_status(self, text: str) -> None:
        """Update status bar text if the bottom zone is ready; otherwise cache it."""
        self._pending_status_text = text

        status_bar = getattr(self.main_window, "status_bar_v2", None)
        if status_bar and hasattr(status_bar, "update_status"):
            try:
                status_bar.update_status(text=text)
            except Exception:
                pass

        bottom_zone = getattr(self.main_window, "bottom_zone", None)
        if bottom_zone is None:
            logger.debug(
                "AppController._update_status(%s) called before bottom_zone exists; deferring",
                text,
            )
            return

        status_label = getattr(bottom_zone, "status_label", None)
        if status_label is None:
            logger.debug(
                "AppController._update_status(%s) called before status_label exists on bottom_zone; deferring",
                text,
            )
            return

        status_label.configure(text=f"Status: {text}")

    def _update_webui_state(self, state: str) -> None:
        status_bar = getattr(self.main_window, "status_bar_v2", None)
        if status_bar and hasattr(status_bar, "update_webui_state"):
            try:
                status_bar.update_webui_state(state)
            except Exception:
                pass

    def _validate_pipeline_config(self) -> tuple[bool, str]:
        cfg = self.app_state.current_config if self.app_state else self.state.current_config
        if not cfg.model_name:
            return False, "Please select a model before running the pipeline."
        if not cfg.sampler_name:
            return False, "Please select a sampler before running the pipeline."
        if cfg.steps <= 0:
            return False, "Steps must be a positive integer."
        return True, ""

    def _set_validation_feedback(self, valid: bool, message: str) -> None:
        panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if panel and hasattr(panel, "set_validation_message"):
            try:
                panel.set_validation_message("" if valid else message)
            except Exception:
                pass
        run_bar = getattr(self.main_window, "run_control_bar_v2", None)
        if run_bar and hasattr(run_bar, "set_run_enabled"):
            try:
                run_bar.set_run_enabled(valid)
            except Exception:
                pass

    def _append_log(self, text: str) -> None:
        bottom_zone = getattr(self.main_window, "bottom_zone", None)
        if bottom_zone is None:
            logger.debug(
                "AppController._append_log(%s) called before bottom_zone exists; deferring",
                text,
            )
            return

        log_widget = getattr(bottom_zone, "log_text", None)
        if log_widget is None:
            logger.debug(
                "AppController._append_log(%s) called before log_text exists on bottom_zone; deferring",
                text,
            )
            return

        log_widget.insert("end", text + "\n")
        log_widget.see("end")

        trace_panel = getattr(self.main_window, "log_trace_panel_v2", None)
        if trace_panel and hasattr(trace_panel, "refresh"):
            try:
                trace_panel.refresh()
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
            self.main_window.after(0, lambda: self._append_log(text))

    def generate_diagnostics_bundle_manual(self) -> None:
        """Expose a manual trigger for diagnostics bundles."""
        self._generate_diagnostics_bundle("manual_request")

    def _generate_diagnostics_bundle(
        self, reason: str, *, extra_context: Mapping[str, Any] | None = None
    ) -> Path | None:
        if not self.gui_log_handler or not self.job_service:
            return None
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

    def _log_structured_error(
        self, envelope: UnifiedErrorEnvelope, message: str
    ) -> None:
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
            self._error_modal = ErrorModalV2(
                self.main_window,
                envelope=envelope,
                on_close=self._clear_error_modal,
            )
        except Exception:
            logger.exception("Failed to show structured error modal")

    def _clear_error_modal(self) -> None:
        self._error_modal = None

    def _handle_uncaught_exception(self, exc_type: type[BaseException], exc_value: BaseException, exc_traceback) -> None:
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

    def _handle_tk_exception(self, exc_type: type[BaseException], exc_value: BaseException, exc_traceback) -> None:
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

    def _on_watchdog_violation_event(
        self, job_id: str, envelope: UnifiedErrorEnvelope
    ) -> None:
        reason = envelope.context.get("watchdog_reason", envelope.error_type)
        self._generate_diagnostics_bundle(
            f"watchdog_{reason.lower()}",
            extra_context={"job_id": job_id, "envelope": serialize_envelope(envelope)},
        )

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        snapshot = self.job_service.get_diagnostics_snapshot() if self.job_service else {}
        data = dict(snapshot)
        data["last_bundle"] = str(self._last_diagnostics_bundle) if self._last_diagnostics_bundle else None
        data["last_bundle_reason"] = self._last_diagnostics_bundle_reason
        return data

    def show_log_trace_panel(self) -> None:
        """Expose helper that expands the LogTracePanelV2 if present."""
        trace_panel = getattr(self.main_window, "log_trace_panel_v2", None)
        if trace_panel is None:
            return
        try:
            trace_panel.show()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Run / Stop / Preview
    # ------------------------------------------------------------------

    def run_pipeline(self) -> Any:
        """Public, synchronous pipeline entrypoint used by journeys and tests.

        This method:
        - Validates the current pipeline config.
        - Builds the PipelineConfig.
        - Delegates to PipelineController for execution.
        - Updates lifecycle state and returns the result.
        """
        if self.state.lifecycle == LifecycleState.RUNNING:
            self._append_log("[controller] run_pipeline requested, but pipeline is already running.")
            return None

        self._append_log("[controller] run_pipeline - delegating to PipelineController.")
        is_valid, message = self._validate_pipeline_config()
        self._set_validation_feedback(is_valid, message)
        if not is_valid:
            self._append_log(f"[controller] Pipeline validation failed: {message}")
            return None

        self._last_error_envelope = None
        self._set_lifecycle(LifecycleState.RUNNING)
        try:
            result = self._run_via_pipeline_controller()
            self._set_lifecycle(LifecycleState.IDLE)
            return result
        except Exception as exc:  # noqa: BLE001
            envelope = self._capture_error_envelope(exc, subsystem="controller")
            self._log_structured_error(envelope, "Pipeline error in run_pipeline")
            self._append_log(f"[controller] Pipeline error in run_pipeline: {exc!r}")
            self._set_lifecycle(LifecycleState.ERROR, error=str(exc))
            self._show_structured_error_modal(envelope)
            return None

    def _run_via_pipeline_controller(self) -> Any:
        """Delegate pipeline execution to PipelineController for modern V2 stack."""
        if not hasattr(self, "pipeline_controller") or self.pipeline_controller is None:
            raise RuntimeError("PipelineController not initialized")

        pipeline_config = self.build_pipeline_config_v2()
        self._append_log("[controller] Delegating to PipelineController for execution.")

        # Run synchronously via PipelineController
        result = self.pipeline_controller.run_pipeline(pipeline_config)
        return result

    def _execute_pipeline_via_runner(self, pipeline_config: PipelineConfig) -> Any:
        """Execute pipeline using the traditional PipelineRunner approach."""
        runner = getattr(self, "pipeline_runner", None)
        if runner is None:
            raise RuntimeError("No pipeline runner configured")
        
        # Run the pipeline synchronously
        result = runner.run(pipeline_config, self.pipeline_controller.cancel_token, self._append_log_threadsafe)
        return result

    def _run_pipeline_from_tab(self, pipeline_tab: Any, pipeline_config: PipelineConfig) -> Any:
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

        return self._run_pipeline_via_runner_only(pipeline_config)

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

    def _run_pipeline_via_runner_only(self, pipeline_config: PipelineConfig) -> Any:
        runner = getattr(self, "pipeline_runner", None)
        if runner is None:
            raise RuntimeError("No pipeline runner configured")
        self._append_log("[controller] Starting pipeline execution (runner).")
        executor_config = runner._build_executor_config(pipeline_config)
        self._cache_last_run_payload(executor_config, pipeline_config)
        return runner.run(pipeline_config, None, self._append_log_threadsafe)

    def _get_pipeline_tab_upscale_params(self, pipeline_tab: Any) -> tuple[float, str, int]:
        factor_var = getattr(pipeline_tab, "upscale_factor", None)
        try:
            factor = float(factor_var.get()) if hasattr(factor_var, "get") else float(factor_var)
        except Exception:
            factor = 2.0
        model_var = getattr(pipeline_tab, "upscale_model", None)
        model = ""
        try:
            model = str(model_var.get()).strip() if hasattr(model_var, "get") else str(model_var or "")
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

        In threaded mode:
        - Spawns a worker thread to run the pipeline with a CancelToken.

        In synchronous mode (threaded=False, useful for tests):
        - Runs the pipeline stub synchronously.
        """
        if self.state.lifecycle == LifecycleState.RUNNING:
            self._append_log("[controller] Run requested, but pipeline is already running.")
            return

        # If there was a previous worker, ensure it is not still alive (best-effort)
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._append_log("[controller] Previous worker still running; refusing new run.")
            return

        self._append_log("[controller] Run clicked - gathering config.")
        is_valid, message = self._validate_pipeline_config()
        self._set_validation_feedback(is_valid, message)
        if not is_valid:
            self._append_log(f"[controller] Pipeline validation failed: {message}")
            return

        self._cancel_token = CancelToken()
        self._set_lifecycle(LifecycleState.RUNNING)

        if self.threaded:
            self._worker_thread = threading.Thread(
                target=self._run_pipeline_thread,
                args=(self._cancel_token,),
                daemon=True,
            )
            self._worker_thread.start()
        else:
            # Synchronous run (for tests and journeys) via public facade
            self.run_pipeline()

    def start_run(self) -> Any:
        """Legacy-friendly entrypoint used by older harnesses."""
        if self.state.lifecycle == LifecycleState.RUNNING:
            self._append_log("[controller] start_run requested while already running.")
            return None
        self._append_log("[controller] start_run invoking run_pipeline.")
        return self.run_pipeline()

    def on_launch_webui_clicked(self) -> None:
        if not self.webui_process_manager:
            return
        self._append_log("[webui] Launch requested by user.")
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
        try:
            pipeline_config = self.build_pipeline_config_v2()
            self._append_log_threadsafe("[controller] Starting pipeline execution.")
            executor_config = self.pipeline_runner._build_executor_config(pipeline_config)
            self._cache_last_run_payload(executor_config, pipeline_config)
            self.pipeline_runner.run(pipeline_config, cancel_token, self._append_log_threadsafe)

            if cancel_token.is_cancelled():
                self._append_log_threadsafe("[controller] Pipeline ended due to cancel (stub).")
            else:
                self._append_log_threadsafe("[controller] Pipeline completed successfully.")

            if cancel_token.needs_stop_to_finish() and not cancel_token.is_cancelled():
                self._append_log_threadsafe(
                    "[controller] Pipeline awaiting explicit stop to finish (stub)."
                )
                return

            cancel_token.clear_stop_requirement()
            self._set_lifecycle_threadsafe(LifecycleState.IDLE)
        except Exception as exc:  # noqa: BLE001
            self._append_log_threadsafe(f"[controller] Pipeline error: {exc!r}")
            self._set_lifecycle_threadsafe(LifecycleState.ERROR, error=str(exc))
            cancel_token.clear_stop_requirement()

    def _cache_last_run_payload(self, executor_config: dict[str, Any], pipeline_config: PipelineConfig) -> None:
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

        sidebar = self._get_sidebar_panel()
        pipeline_section = executor_config.get("pipeline") or {}
        stage_defaults = {
            "txt2img": bool(pipeline_section.get("txt2img_enabled", True)),
            "img2img": bool(pipeline_section.get("img2img_enabled", True)),
            "adetailer": bool(pipeline_section.get("adetailer_enabled", True)),
            "upscale": bool(pipeline_section.get("upscale_enabled", False)),
        }
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

        pipeline_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if run_snapshot and pipeline_panel and hasattr(pipeline_panel, "apply_run_config"):
            pipeline_panel.apply_run_config(run_snapshot)
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
            self._set_profile_default(cfg, "refiner_model_name", defaults.get("default_refiner_id"), "")
            self._set_profile_default(cfg, "refiner_switch_at", defaults.get("default_refiner_switch_at"), None)
            self._set_profile_default(cfg, "hires_upscaler_name", defaults.get("default_hires_upscaler_id"), "Latent")
            self._set_profile_default(cfg, "hires_denoise", defaults.get("default_hires_denoise"), 0.3)
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

    def _apply_pipeline_stage_flags(self, pipeline_section: dict[str, Any]) -> None:
        if not pipeline_section:
            return
        for stage in ("txt2img", "img2img", "upscale", "adetailer"):
            key = f"{stage}_enabled"
            if key in pipeline_section:
                self._set_sidebar_stage_state(stage, bool(pipeline_section.get(key)))
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
        self._append_log("[controller] Help clicked (stub).")
        # TODO: open docs/README in browser or show help overlay.

    def on_refresh_clicked(self) -> None:
        self._append_log("[controller] Refresh clicked.")
        self.refresh_resources_from_webui()

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

    def shutdown_app(self, reason: str | None = None) -> None:
        """Centralized shutdown path invoked by GUI teardown or main_finally."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True
        if self._shutdown_started_at is None:
            self._shutdown_started_at = time.time()
            threading.Thread(target=self._shutdown_watchdog, daemon=True).start()
        label = reason or "shutdown"
        logger.info("[controller] shutdown_app called (%s)", label)

        try:
            self._cancel_active_jobs(label)
        except Exception:
            logger.exception("Error cancelling active jobs during shutdown")

        try:
            self.stop_all_background_work()
        except Exception:
            logger.exception("Error stopping background work during shutdown")

        try:
            self._shutdown_learning_hooks()
        except Exception:
            logger.exception("Error shutting down learning hooks")

        try:
            self._shutdown_webui()
        except Exception:
            logger.exception("Error shutting down WebUI")
        try:
            self._shutdown_job_service()
        except Exception:
            logger.exception("Error shutting down job service")

        if is_debug_shutdown_inspector_enabled():
            try:
                log_shutdown_state(logger, label)
            except Exception:
                logger.exception("Error running shutdown inspector")

        try:
            self._join_worker_thread()
        except Exception:
            logger.exception("Error waiting for worker thread during shutdown")

        self._shutdown_completed = True

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
        manager = self.webui_process_manager
        if not manager:
            return
        stop_fn = getattr(manager, "stop_webui", None) or getattr(manager, "shutdown", None) or getattr(manager, "stop", None)
        if callable(stop_fn):
            def _stop_and_log() -> None:
                pid = getattr(manager, "pid", None)
                logger.info("Calling stop_webui for PID %s", pid)
                try:
                    result = stop_fn()
                    running = manager.is_running()
                    exit_code = getattr(manager, "_last_exit_code", None)
                    logger.info(
                        "WebUI shutdown result: running=%s, last_exit_code=%s, stop_return=%s",
                        running,
                        exit_code,
                        result,
                    )
                except Exception:
                    logger.exception("Error stopping WebUI")

            try:
                threading.Thread(target=_stop_and_log, daemon=True).start()
            except Exception:
                logger.exception("Error stopping WebUI process")

    def _shutdown_job_service(self) -> None:
        svc = getattr(self, "job_service", None)
        if not svc:
            return
        runner = getattr(svc, "runner", None)
        if runner and hasattr(runner, "stop"):
            try:
                runner.stop()
            except Exception:
                logger.exception("Error stopping job runner")

    def _shutdown_watchdog(self) -> None:
        timeout = float(os.environ.get("STABLENEW_SHUTDOWN_WATCHDOG_DELAY", "8"))
        hard_exit = os.environ.get("STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG", "0") == "1"
        time.sleep(timeout)
        if not self._shutdown_completed:
            logger.error("Shutdown watchdog triggered after %.1fs (completed=%s)", timeout, self._shutdown_completed)
            if hard_exit:
                logger.error("Hard exit forced due to shutdown hang.")
                os._exit(1)

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
        self.on_preset_selected(new_preset)

    def on_preset_selected(self, preset_name: str) -> None:
        self._append_log(f"[controller] Preset selected: {preset_name}")
        # selection should not immediately mutate config; wait for action

    def apply_preset_to_run_config(self, preset_config: dict[str, Any], preset_name: str) -> None:
        """Apply preset configuration to the current run config."""
        try:
            # Update AppStateV2 run_config
            if self.app_state is not None:
                try:
                    self.app_state.set_run_config(preset_config)
                except Exception:
                    pass
                else:
                    self._apply_randomizer_from_config(preset_config)
            
            # Extract core config fields from preset and apply to core config panel
            core_overrides = self._extract_core_overrides_from_preset(preset_config)
            if core_overrides:
                self._apply_core_overrides(core_overrides)
            
            # Update PipelineConfigPanelV2 if available
            pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
            if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
                try:
                    pipeline_config_panel.apply_run_config(preset_config)
                except Exception:
                    pass
            
            self._append_log(f"[controller] Applied preset '{preset_name}' to run config")
            self._apply_adetailer_config_section(preset_config)
            
        except Exception as e:
            self._append_log(f"[controller] Error applying preset '{preset_name}': {e}")

    def _extract_core_overrides_from_preset(self, preset_config: dict[str, Any]) -> dict[str, Any]:
        """Extract core configuration overrides from preset config."""
        overrides = {}
        
        # Get txt2img config as primary source
        txt2img_config = preset_config.get("txt2img", {})
        
        # Extract model
        if "model" in txt2img_config and txt2img_config["model"]:
            overrides["model"] = txt2img_config["model"]
        
        # Extract sampler
        if "sampler_name" in txt2img_config and txt2img_config["sampler_name"]:
            overrides["sampler"] = txt2img_config["sampler_name"]
        
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
        
        return overrides

    def _apply_core_overrides(self, overrides: dict[str, Any]) -> None:
        """Apply core configuration overrides to the core config panel."""
        try:
            # Find the core config panel in the sidebar
            pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
            if pipeline_tab is None:
                return
            
            sidebar_panel = getattr(pipeline_tab, "sidebar", None)
            if sidebar_panel is None:
                return
            
            core_config_panel = getattr(sidebar_panel, "get_core_config_panel", lambda: None)()
            if core_config_panel is None:
                return
            
            # Apply the overrides
            if hasattr(core_config_panel, "apply_from_overrides"):
                core_config_panel.apply_from_overrides(overrides)
                self._append_log(f"[controller] Applied core config overrides: {overrides}")
                
        except Exception as e:
            self._append_log(f"[controller] Error applying core config overrides: {e}")

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
        self.packs = discover_packs(self._packs_dir)
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

    def _find_pack_by_id(self, pack_id: str) -> Optional[PromptPackInfo]:
        """Find a pack by its ID (name)."""
        for pack in self.packs:
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
        Prefer PromptWorkspaceState prompt (Prompt tab) when available; fall back to legacy sources.

        This is a temporary bridge until the full Pipeline tab refactor lands.
        """
        try:
            ws = getattr(self.main_window, "prompt_workspace_state", None)
            if ws is not None:
                prompt_text = ws.get_current_prompt_text()
                if prompt_text and prompt_text.strip():
                    self._append_log("[controller] Using PromptWorkspaceState prompt.")
                    return prompt_text
        except Exception:
            pass

        self._append_log("[controller] Using legacy prompt source (PromptWorkspaceState empty).")
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
        cfg = self.state.current_config
        for field, value in kwargs.items():
            attr = mapping.get(field)
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

        return {
            "prompt": prompt,
            "negative_prompt": getattr(self.state.current_config, "negative_prompt", "") or "",
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

    def build_pipeline_config_v2(self) -> PipelineConfig:
        """Build the pipeline configuration structure that drives the runner."""
        return self._build_pipeline_config()

    def _build_pipeline_config(self) -> PipelineConfig:
        current = self.get_current_config()
        pack = self._get_selected_pack()
        prompt = self._get_active_prompt_text() or self._resolve_prompt_from_pack(pack) or current.get("prompt", "")
        if not prompt:
            prompt = (pack.name if pack else current.get("preset_name")) or "StableNew GUI Run"

        metadata: dict[str, Any] = {}
        if self.app_state:
            metadata["adetailer_enabled"] = bool(self.app_state.adetailer_enabled)
            metadata["adetailer"] = dict(self.app_state.adetailer_config or {})

        return PipelineConfig(
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
        return {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
            "upscalers": [],
            "adetailer_models": [],
            "adetailer_detectors": [],
        }

    def refresh_resources_from_webui(self) -> dict[str, list[Any]] | None:
        if not getattr(self, "resource_service", None):
            return None
        try:
            payload = self.resource_service.refresh_all() or {}
        except Exception as exc:
            message = f"Failed to refresh WebUI resources: {exc}"
            self._append_log(f"[resources] {message}")
            logger.warning(message)
            return None

        normalized = self._normalize_resource_map(payload)
        self.state.resources = normalized
        if self.app_state is not None:
            try:
                self.app_state.set_resources(normalized)
            except Exception:
                pass
        self._update_gui_dropdowns()
        counts = tuple(len(normalized[key]) for key in ("models", "vaes", "samplers", "schedulers", "upscalers"))
        msg = (
            f"Resource update: {counts[0]} models, {counts[1]} vaes, "
            f"{counts[2]} samplers, {counts[3]} schedulers, {counts[4]} upscalers"
        )
        self._append_log(f"[resources] {msg}")
        logger.info(msg)
        return normalized

    def on_webui_ready(self) -> None:
        """Handle WebUI transitioning to READY."""
        self._append_log("[webui] READY received, refreshing resource lists.")
        self.refresh_resources_from_webui()

    def _normalize_resource_map(self, payload: dict[str, Any]) -> dict[str, list[Any]]:
        resources = self._empty_resource_map()
        for name in resources:
            resources[name] = list(payload.get(name) or [])
        resources["adetailer_models"] = list(payload.get("adetailer_models") or [])
        resources["adetailer_detectors"] = list(payload.get("adetailer_detectors") or [])
        return resources

    def _update_gui_dropdowns(self) -> None:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return
        dropdowns = self._dropdown_loader.load_dropdowns(self, self.app_state)
        self._dropdown_loader.apply_to_gui(pipeline_tab, dropdowns)
        
        # Also refresh the sidebar's core config panel
        sidebar = self._get_sidebar_panel()
        if sidebar and hasattr(sidebar, "refresh_core_config_from_webui"):
            try:
                sidebar.refresh_core_config_from_webui()
            except Exception as e:
                pass

    def _get_stage_cards_panel(self) -> Any:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return None
        return getattr(pipeline_tab, "stage_cards_panel", None)

    def _get_sidebar_panel(self) -> Any:
        return getattr(self.main_window, "sidebar_panel_v2", None)

    # ------------------------------------------------------------------
    # Pipeline Pack Config & Job Builder (PR-035)
    # ------------------------------------------------------------------

    def _maybe_set_app_state_lora_strengths(self, config: dict[str, Any]) -> None:
        if not self.app_state:
            return
        strengths = normalize_lora_strengths(config.get("lora_strengths"))
        self.app_state.set_lora_strengths(strengths)

    def on_stage_toggled(self, stage: str, enabled: bool) -> None:
        if stage != "adetailer" or not self.app_state:
            return
        normalized = bool(enabled)
        self.app_state.set_adetailer_enabled(normalized)
        config_snapshot = self._collect_adetailer_panel_config()
        config_snapshot["enabled"] = normalized
        self.app_state.set_adetailer_config(config_snapshot)

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

    def _update_run_config_randomizer(self, enabled: bool | None = None, max_variants: int | None = None) -> None:
        if not self.app_state:
            return
        current = dict(self.app_state.run_config or {})
        updated = False
        if enabled is not None and current.get("randomization_enabled") != enabled:
            current["randomization_enabled"] = enabled
            updated = True
        if max_variants is not None and current.get("max_variants") != max_variants:
            current["max_variants"] = max_variants
            updated = True
        if updated:
            self.app_state.set_run_config(current)

    def _apply_randomizer_from_config(self, config: dict[str, Any]) -> None:
        if not config:
            return
        fallback = self.state.current_config
        random_section = config.get("randomization") or {}
        enabled = config.get("randomization_enabled")
        if enabled is None:
            enabled = random_section.get("enabled", fallback.randomization_enabled)
        max_variants = config.get("max_variants")
        if max_variants is None:
            max_variants = random_section.get("max_variants", fallback.max_variants)
        try:
            normalized_max = int(max_variants)
        except (TypeError, ValueError):
            normalized_max = fallback.max_variants
        normalized_max = max(1, normalized_max)
        normalized_enabled = bool(enabled)
        fallback.randomization_enabled = normalized_enabled
        fallback.max_variants = normalized_max
        self._update_run_config_randomizer(enabled=normalized_enabled, max_variants=normalized_max)

    def _get_panel_randomizer_config(self) -> dict[str, Any] | None:
        panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if panel is None or not hasattr(panel, "get_randomizer_config"):
            return None
        try:
            config = panel.get_randomizer_config()
        except Exception:
            return None
        if not config:
            return None
        return config

    def _run_config_with_lora(self) -> dict[str, Any]:
        base = self.app_state.run_config.copy() if self.app_state else {}
        if self.app_state and self.app_state.lora_strengths:
            base["lora_strengths"] = [cfg.to_dict() for cfg in self.app_state.lora_strengths]
        if "randomization_enabled" not in base:
            base["randomization_enabled"] = self.state.current_config.randomization_enabled
        if "max_variants" not in base:
            base["max_variants"] = self.state.current_config.max_variants
        return base

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
            pipeline_config=None,
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
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=normalized, enabled=cfg.enabled))
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
                updated.append(LoraRuntimeConfig(name=cfg.name, strength=cfg.strength, enabled=normalized))
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
        
        # Update stage cards if available
        pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
            try:
                pipeline_config_panel.apply_run_config(pack_config)
            except Exception as e:
                self._append_log(f"[controller] Error applying pack config to stages: {e}")
        stage_panel = self._get_stage_cards_panel()
        if stage_panel:
            for card_name in ("txt2img", "img2img", "upscale"):
                card = getattr(stage_panel, f"{card_name}_card", None)
                self._load_stage_card(card, pack_config)
            stage_panel.load_adetailer_config(pack_config.get("adetailer") or {})
        self._apply_adetailer_config_section(pack_config)
        
        self._append_log(f"[controller] Loaded config for pack '{pack_id}'")

    def on_pipeline_pack_apply_config(self, pack_ids: list[str]) -> None:
        """Write current stage config into one or more packs."""
        self._append_log(f"[controller] Applying config to packs: {pack_ids}")
        
        # Get current run config
        current_config = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            current_config.update(panel_randomizer)
        if not current_config:
            self._append_log("[controller] No current config to apply")
            return
        if self.app_state:
            self.app_state.set_run_config(current_config)
        
        # Save to each pack
        for pack_id in pack_ids:
            success = self._config_manager.save_pack_config(pack_id, current_config)
            if success:
                self._append_log(f"[controller] Applied config to pack '{pack_id}'")
            else:
                self._append_log(f"[controller] Failed to apply config to pack '{pack_id}'")

    def save_current_pipeline_preset(self, preset_name: str) -> bool:
        """Persist the current pipeline/stage config as a named preset."""
        self._append_log(f"[controller] Saving current pipeline config as preset '{preset_name}'")
        payload = self._run_config_with_lora()
        panel_randomizer = self._get_panel_randomizer_config()
        if panel_randomizer:
            payload.update(panel_randomizer)
        if not payload:
            self._append_log("[controller] No current config to save as preset")
            return False
        success = self._config_manager.save_preset(preset_name, payload)
        if success:
            self._append_log(f"[controller] Preset '{preset_name}' saved")
        else:
            self._append_log(f"[controller] Failed to save preset '{preset_name}'")
        return success

    def on_pipeline_add_packs_to_job(self, pack_ids: list[str]) -> None:
        """Add one or more packs to the current job draft."""
        self._append_log(f"[controller] Adding packs to job: {pack_ids}")
        
        entries = []
        stage_flags = self._build_stage_flags()
        randomizer_metadata = self._build_randomizer_metadata()
        for pack_id in pack_ids:
            pack = self._find_pack_by_id(pack_id)
            if pack is None:
                self._append_log(f"[controller] Pack not found: {pack_id}")
                continue
            
            # Get current run config from app_state
            run_config = self._run_config_with_lora()
            
            # Ensure randomization is included
            if "randomization_enabled" not in run_config:
                run_config["randomization_enabled"] = self.state.current_config.randomization_enabled
            prompt_text, negative_prompt_text = self._read_pack_prompts(pack)
            entry = PackJobEntry(
                pack_id=pack_id,
                pack_name=pack.name,
                config_snapshot=run_config,
                prompt_text=prompt_text,
                negative_prompt_text=negative_prompt_text,
                stage_flags=dict(stage_flags),
                randomizer_metadata=randomizer_metadata,
            )
            entries.append(entry)
        
        if entries and self.app_state:
            self.app_state.add_packs_to_job_draft(entries)
            self._append_log(f"[controller] Added {len(entries)} pack(s) to job draft")

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
        """Enqueue and execute the next queued job via JobService."""
        self.on_run_queue_now_clicked()

    def on_run_queue_now_clicked(self) -> None:
        """Delegate to JobService to execute the next queued job."""
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

    def on_pipeline_preset_apply_to_default(self, preset_name: str) -> None:
        """Apply preset config to the current run config and optionally mark default."""
        self._append_log(f"[controller] Applying preset '{preset_name}' to default")

        preset_config = self._load_and_apply_preset(preset_name)
        if preset_config is None:
            return

        success = self._config_manager.set_default_preset(preset_name)
        if success:
            self._append_log(f"[controller] Set '{preset_name}' as default preset")
        else:
            self._append_log(f"[controller] Failed to set default preset")

    def _load_and_apply_preset(self, preset_name: str) -> dict[str, Any] | None:
        preset_config = self._config_manager.load_preset(preset_name)
        if preset_config is None:
            self._append_log(f"[controller] Failed to load preset: {preset_name}")
            return None

        self.apply_preset_to_run_config(preset_config, preset_name)
        return preset_config

    def on_pipeline_preset_apply_to_packs(self, preset_name: str, pack_ids: list[str]) -> None:
        """Copy preset values into configs of selected packs."""
        self._append_log(f"[controller] Applying preset '{preset_name}' to packs: {pack_ids}")
        
        preset_config = self._config_manager.load_preset(preset_name)
        if preset_config is None:
            self._append_log(f"[controller] Failed to load preset: {preset_name}")
            return
        
        # Apply to each pack
        for pack_id in pack_ids:
            success = self._config_manager.save_pack_config(pack_id, preset_config)
            if success:
                self._append_log(f"[controller] Applied preset to pack '{pack_id}'")
            else:
                self._append_log(f"[controller] Failed to apply preset to pack '{pack_id}'")

    def on_pipeline_preset_load_to_stages(self, preset_name: str) -> None:
        """Load preset values into stage cards."""
        self._append_log(f"[controller] Loading preset '{preset_name}' to stages")
        
        preset_config = self._config_manager.load_preset(preset_name)
        if preset_config is None:
            self._append_log(f"[controller] Failed to load preset: {preset_name}")
            return
        
        # Apply to run config
        if self.app_state:
            self.app_state.set_run_config(preset_config)
            self._apply_randomizer_from_config(preset_config)
        
        # Update stage cards
        pipeline_config_panel = getattr(self.main_window, "pipeline_config_panel_v2", None)
        if pipeline_config_panel and hasattr(pipeline_config_panel, "apply_run_config"):
            try:
                pipeline_config_panel.apply_run_config(preset_config)
                self._append_log(f"[controller] Loaded preset '{preset_name}' to stages")
            except Exception as e:
                self._append_log(f"[controller] Error loading preset to stages: {e}")
        self._apply_adetailer_config_section(preset_config)

    def on_pipeline_preset_save_from_stages(self, preset_name: str) -> None:
        """Save current stage config as a preset."""
        self._append_log(f"[controller] Saving preset '{preset_name}' from stages")
        
        # Get current config
        current_config = self._run_config_with_lora()
        if not current_config:
            self._append_log("[controller] No current config to save")
            return
        
        # Save as preset
        success = self._config_manager.save_preset(preset_name, current_config)
        if success:
            self._append_log(f"[controller] Saved preset '{preset_name}'")
        else:
            self._append_log(f"[controller] Failed to save preset '{preset_name}'")

    def on_pipeline_preset_delete(self, preset_name: str) -> None:
        """Remove an existing preset."""
        self._append_log(f"[controller] Deleting preset '{preset_name}'")
        
        # TODO: Add confirmation dialog if needed
        success = self._config_manager.delete_preset(preset_name)
        if success:
            self._append_log(f"[controller] Deleted preset '{preset_name}'")
        else:
            self._append_log(f"[controller] Failed to delete preset '{preset_name}'")


# Convenience entrypoint for testing the skeleton standalone
if __name__ == "__main__":
    import tkinter as tk
    from src.gui.main_window_v2 import StableNewApp

    app = StableNewApp()
    controller = AppController(app.main_window, threaded=True)
    app.mainloop()
