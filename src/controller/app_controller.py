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

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional
import threading

from src.api.client import SDWebUIClient
from src.api.webui_resource_service import WebUIResourceService
from src.api.webui_resources import WebUIResource
from src.api.webui_process_manager import WebUIProcessManager
from src.pipeline.last_run_store_v2_5 import LastRunConfigV2_5
from src.gui.main_window_v2 import MainWindow
from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunner
from src.utils import StructuredLogger
from src.utils.config import ConfigManager
from src.utils.file_io import read_prompt_pack
from src.utils.prompt_packs import PromptPackInfo, discover_packs

import logging
logger = logging.getLogger(__name__)


class LifecycleState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


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

    def get_last_run_config(self) -> LastRunConfigV2_5 | None:
        if not hasattr(self, "_last_run_store"):
            from src.pipeline.last_run_store_v2_5 import LastRunStoreV2_5
        return self._last_run_store.load()
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
        main_window: MainWindow,
        pipeline_runner: Optional[PipelineRunner] = None,
        threaded: bool = True,
        packs_dir: Path | str | None = None,
        api_client: SDWebUIClient | None = None,
        structured_logger: StructuredLogger | None = None,
        webui_process_manager: WebUIProcessManager | None = None,
        config_manager: ConfigManager | None = None,
        resource_service: WebUIResourceService | None = None,
    ) -> None:
        self.main_window = main_window
        self.app_state = getattr(main_window, "app_state", None)
        self.state = AppState()
        self.threaded = threaded
        self._config_manager = config_manager or ConfigManager()

        if pipeline_runner is not None:
            self.pipeline_runner = pipeline_runner
        else:
            self._api_client = api_client or SDWebUIClient()
            self._structured_logger = structured_logger or StructuredLogger()
            self.pipeline_runner = PipelineRunner(self._api_client, self._structured_logger)

        client = getattr(self, "_api_client", None)
        self.resource_service = resource_service or WebUIResourceService(client=client)
        self.state.resources = self._empty_resource_map()
        self.webui_process_manager = webui_process_manager
        self._cancel_token: Optional[CancelToken] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._packs_dir = Path(packs_dir) if packs_dir is not None else Path("packs")
        self.packs: list[PromptPackInfo] = []
        self._selected_pack_index: Optional[int] = None

        # Let the GUI wire its callbacks to us
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
        left.load_pack_button.configure(command=self.on_load_pack)
        left.edit_pack_button.configure(command=self.on_edit_pack)
        left.packs_list.bind("<<ListboxSelect>>", self._on_pack_list_select)
        left.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_combo_select)

        # Initial API status (placeholder)
        bottom.api_status_label.configure(text="API: Unknown")

        # Flush deferred status if any
        if getattr(self, "_pending_status_text", None):
            self._update_status(self._pending_status_text)

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
        cfg = self.state.current_config
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

        self.main_window.after(0, lambda: self._append_log(text))

    # ------------------------------------------------------------------
    # Run / Stop / Preview
    # ------------------------------------------------------------------

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
            # Synchronous run (for tests)
            self._run_pipeline_thread(self._cancel_token)

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
            pipeline_config = self._build_pipeline_config()
            self._append_log_threadsafe("[controller] Starting pipeline execution.")
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

    def on_open_settings(self) -> None:
        self._append_log("[controller] Settings clicked (stub).")
        # TODO: open a settings dialog or config editor.

    def on_help_clicked(self) -> None:
        self._append_log("[controller] Help clicked (stub).")
        # TODO: open docs/README in browser or show help overlay.

    def stop_all_background_work(self) -> None:
        """Best-effort shutdown used by GUI teardown to avoid late Tk calls."""
        try:
            if self._cancel_token is not None:
                self._cancel_token.cancel()
        except Exception:
            pass
        worker_alive = self._worker_thread is not None and self._worker_thread.is_alive()
        if worker_alive:
            try:
                self._worker_thread = None
            except Exception:
                pass
        try:
            self.state.lifecycle = LifecycleState.IDLE
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Packs / Presets
    # ------------------------------------------------------------------

    def _on_preset_combo_select(self, event) -> None:  # type: ignore[override]
        combo = self.main_window.left_zone.preset_combo
        new_preset = combo.get()
        self.on_preset_selected(new_preset)

    def on_preset_selected(self, preset_name: str) -> None:
        self._append_log(f"[controller] Preset selected: {preset_name}")
        self.state.current_config.preset_name = preset_name
        # TODO: load preset JSON, update GUI fields, etc.

    def _on_pack_list_select(self, event) -> None:  # type: ignore[override]
        lb = self.main_window.left_zone.packs_list
        if not lb.curselection():
            return
        index = lb.curselection()[0]
        self.on_pack_selected(int(index))

    def load_packs(self) -> None:
        """Discover packs and push them to the GUI."""
        self.packs = discover_packs(self._packs_dir)
        pack_names = [pack.name for pack in self.packs]
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

    def _get_selected_pack(self) -> Optional[PromptPackInfo]:
        if self._selected_pack_index is None:
            return None
        if self._selected_pack_index < 0 or self._selected_pack_index >= len(self.packs):
            return None
        return self.packs[self._selected_pack_index]

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
    def get_current_config(self) -> dict[str, float | int | str]:
        cfg = self.state.current_config
        return {
            "model": cfg.model_name or self.get_available_models()[0],
            "sampler": cfg.sampler_name or self.get_available_samplers()[0],
            "height": cfg.height,
            "steps": cfg.steps,
            "cfg_scale": cfg.cfg_scale,
        }
    def update_config(self, **kwargs: float | int | str) -> None:
        mapping = {
            "model": "model_name",
            "sampler": "sampler_name",
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

    def _build_pipeline_config(self) -> PipelineConfig:
        current = self.get_current_config()
        pack = self._get_selected_pack()
        prompt = self._get_active_prompt_text() or self._resolve_prompt_from_pack(pack) or current.get("prompt", "")
        if not prompt:
            prompt = (pack.name if pack else current.get("preset_name")) or "StableNew GUI Run"

        return PipelineConfig(
            prompt=prompt,
            model=str(current["model"]),
            sampler=str(current["sampler"]),
            width=int(current["width"]),
            height=int(current["height"]),
            steps=int(current["steps"]),
            cfg_scale=float(current["cfg_scale"]),
            pack_name=pack.name if pack else None,
            preset_name=self.state.current_config.preset_name or None,
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
        counts = tuple(len(normalized[key]) for key in ("models", "vaes", "samplers", "schedulers"))
        msg = (
            f"Resource update: {counts[0]} models, {counts[1]} vaes, "
            f"{counts[2]} samplers, {counts[3]} schedulers"
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
        return resources

    def _update_gui_dropdowns(self) -> None:
        pipeline_tab = getattr(self.main_window, "pipeline_tab", None)
        if pipeline_tab is None:
            return
        panel = getattr(pipeline_tab, "stage_cards_panel", None)
        if panel is None:
            return
        updater = getattr(panel, "apply_resource_update", None)
        if callable(updater):
            try:
                updater(self.state.resources)
            except Exception:
                pass


# Convenience entrypoint for testing the skeleton standalone
if __name__ == "__main__":
    import tkinter as tk
    from src.gui.main_window_v2 import StableNewApp

    app = StableNewApp()
    controller = AppController(app.main_window, threaded=True)
    app.mainloop()
