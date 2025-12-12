# PR-GUI-V2-SHIM-AND-ARCHIVE-005_V2-P1 — Convert main_window to V2 shim and archive legacy GUI

**Baseline snapshot:** `StableNew-snapshot-20251128-154233.zip`  
**Scope:**  
- Replace `src/gui/main_window.py` with a minimal V2-only shim.  
- Archive the legacy `StableNewGUI` implementation to `archive/gui_v1/main_window.py`.  
- Archive the hybrid layout engine `AppLayoutV2` to `archive/gui_v1/app_layout_v2.py` and leave a stub in `src/gui/app_layout_v2.py`.

---

## Files touched

- `src/gui/main_window.py` (replace with shim)
- `archive/gui_v1/main_window.py` (new file with archived legacy implementation)
- `archive/gui_v1/app_layout_v2.py` (new file with archived legacy implementation)
- `src/gui/app_layout_v2.py` (replace with tiny stub pointing to archive)

---

## Patch: `src/gui/main_window.py` → V2 shim

```diff
--- a/src/gui/main_window.py
+++ b/src/gui/main_window.py
@@ -1,7384 +1,8 @@
-from __future__ import annotations
+# Minimal V2-only shim for GUI entrypoint.
+# Legacy StableNewGUI implementation has been archived under archive/gui_v1/.
 
-import json
-import logging
-import os
-import re
-import subprocess
-import sys
-import threading
-import time
-import tkinter as tk
-from copy import deepcopy
-from enum import Enum, auto
-from pathlib import Path
-from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
-from typing import Any, Callable
-
-from src.api.client import SDWebUIClient, find_webui_api_port, validate_webui_health
-from src.controller.pipeline_controller import PipelineController
-from src.controller.learning_execution_controller import LearningExecutionController
-from src.gui.advanced_prompt_editor import AdvancedPromptEditor
-from src.gui.api_status_panel import APIStatusPanel
-from src.gui.config_panel import ConfigPanel
-from src.gui.enhanced_slider import EnhancedSlider
-from src.gui.engine_settings_dialog import EngineSettingsDialog
-from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
-from src.gui.log_panel import LogPanel, TkinterLogHandler
-from src.gui.pipeline_controls_panel import PipelineControlsPanel
-from src.gui.prompt_pack_panel import PromptPackPanel
-from src.gui.panels_v2 import PipelinePanelV2, PreviewPanelV2, RandomizerPanelV2, SidebarPanelV2, StatusBarV2
-from src.gui.app_layout_v2 import AppLayoutV2
-from src.gui_v2.adapters.pipeline_adapter_v2 import build_effective_config
-from src.gui_v2.adapters.randomizer_adapter_v2 import compute_variant_count
-from src.gui_v2.adapters.status_adapter_v2 import StatusAdapterV2
-from src.controller.settings_suggestion_controller import SettingsSuggestionController
-from src.ai.settings_generator_contract import SuggestionIntent
-from src.gui.scrolling import enable_mousewheel, make_scrollable
-from src.gui.state import GUIState, StateManager
-from src.gui.theme_v2 import Theme
 from src.gui.main_window_v2 import MainWindowV2
 
-# V2 GUI alias for entrypoint wiring
+# Compatibility aliases for old entrypoint / tests
 StableNewGUI = MainWindowV2
-ENTRYPOINT_GUI_CLASS = StableNewGUI
-from src.gui.tooltip import Tooltip
-from src.api.webui_process_manager import WebUIProcessManager
-from src.pipeline.executor import Pipeline
-from src.services.config_service import ConfigService
-from src.utils import StructuredLogger
-from src.utils.aesthetic_detection import detect_aesthetic_extension
-from src.utils.config import ConfigManager
-from src.utils.file_io import get_prompt_packs, read_prompt_pack
-from src.utils.preferences import PreferencesManager
-from src.utils.randomizer import (
-    PromptRandomizer,
-    PromptVariant,
-    apply_variant_to_config,
-    build_variant_plan,
-)
-from src.utils.state import CancellationError
-from src.utils.webui_discovery import WebUIDiscovery
-from src.utils.webui_launcher import launch_webui_safely
-from src.controller.webui_connection_controller import WebUIConnectionState
-from src.config.app_config import (
-    learning_enabled_default,
-    get_learning_enabled,
-    is_queue_execution_enabled,
-    set_queue_execution_enabled,
-)
-
-
-# Config source state machine
-class ConfigSource(Enum):
-    PACK = auto()
-    PRESET = auto()
-    GLOBAL_LOCK = auto()
-
-
-class ConfigContext:
-    def __init__(
-        self,
-        source=ConfigSource.PACK,
-        editor_cfg=None,
-        locked_cfg=None,
-        active_preset=None,
-        active_list=None,
-    ):
-        self.source = source
-        self.editor_cfg = editor_cfg or {}
-        self.locked_cfg = locked_cfg
-        self.active_preset = active_preset
-        self.active_list = active_list
-
-
-logger = logging.getLogger(__name__)
-
-_FORCE_GUI_TEST_MODE: bool | None = None
-
-
-def enable_gui_test_mode() -> None:
-    """Explicit hook for tests to force GUI test behavior."""
-
-    global _FORCE_GUI_TEST_MODE
-    _FORCE_GUI_TEST_MODE = True
-
-
-def disable_gui_test_mode() -> None:
-    """Forcefully disable GUI test mode regardless of environment."""
-
-    global _FORCE_GUI_TEST_MODE
-    _FORCE_GUI_TEST_MODE = False
-
-
-def reset_gui_test_mode() -> None:
-    """Return GUI test mode detection to the environment-based default."""
-
-    global _FORCE_GUI_TEST_MODE
-    _FORCE_GUI_TEST_MODE = None
-
-
-def is_gui_test_mode() -> bool:
-    """Return True when running under automated GUI test harness."""
-
-    if _FORCE_GUI_TEST_MODE is not None:
-        return _FORCE_GUI_TEST_MODE
-    return os.environ.get("STABLENEW_GUI_TEST_MODE") == "1"
-
-
-def sanitize_prompt(text: str) -> str:
-    """Strip leftover [[slot]] / __wildcard__ tokens before sending to WebUI."""
-    if not text:
-        return text
-    cleaned = re.sub(r"\[\[[^\]]+\]\]", "", text)
-    cleaned = re.sub(r"__\w+__", "", cleaned)
-    return " ".join(cleaned.split())
-
-class StableNewGUI:
-    def __init__(
-        self,
-        root: tk.Tk | None = None,
-        config_manager: ConfigManager | None = None,
-        preferences: PreferencesManager | None = None,
-        state_manager: StateManager | None = None,
-        controller: PipelineController | None = None,
-        webui_discovery: WebUIDiscovery | None = None,
-        webui_process_manager: WebUIProcessManager | None = None,
-        title: str = "StableNew",
-        geometry: str = "1360x900",
-        default_preset_name: str | None = None,
-    ) -> None:
-        self.config_manager = config_manager or ConfigManager()
-        self.preferences_manager = preferences or PreferencesManager()
-        self.state_manager = state_manager or StateManager(initial_state=GUIState.IDLE)
-        self.layout_version = "v2"
-        self._run_button_validation_locked = False
-        self._last_txt2img_validation_result = None
-        self.api_connected = False
-        try:
-            self._learning_enabled_flag = get_learning_enabled()
-        except Exception:
-            self._learning_enabled_flag = learning_enabled_default()
-
-        # Single StructuredLogger instance owned by the GUI and shared with the controller.
-        self.structured_logger = StructuredLogger()
-
-        self.controller = controller or PipelineController(self.state_manager)
-        try:
-            self.controller.structured_logger = self.structured_logger
-        except Exception:
-            setattr(self.controller, "structured_logger", self.structured_logger)
-        self.job_history_service = None
-        getter = getattr(self.controller, "get_job_history_service", None)
-        if callable(getter):
-            try:
-                self.job_history_service = getter()
-            except Exception:
-                self.job_history_service = None
-        self.settings_suggestion_controller = SettingsSuggestionController()
-        self.webui = webui_discovery or WebUIDiscovery()
-        self.webui_process_manager = webui_process_manager
-        self._refreshing_config = False
-        self.learning_execution_controller = LearningExecutionController()
-        try:
-            self.controller.set_learning_enabled(self.learning_enabled_var.get())
-        except Exception:
-            pass
-        try:
-            self.learning_execution_controller.set_learning_enabled(self.learning_enabled_var.get())
-        except Exception:
-            pass
-        if root is not None:
-            self.root = root
-        else:
-            self.root = tk.Tk()
-        self.learning_enabled_var = tk.BooleanVar(master=self.root, value=self._learning_enabled_flag)
-        self.root.title(title)
-        self.root.geometry(geometry)
-        self.window_min_size = (1200, 780)
-        self.root.minsize(*self.window_min_size)
-        self._build_menu_bar()
-
-        # Initialize theme
-        self.theme = Theme()
-        self.theme.apply_root(self.root)
-
-        # Initialize ttk style and theme colors
-        self.style = ttk.Style()
-        self.theme.apply_ttk_styles(self.style)
-
-        # --- ConfigService and ConfigContext wiring ---
-        packs_dir = Path("packs")
-        presets_dir = Path("presets")
-        lists_dir = Path("lists")
-        self.config_service = ConfigService(packs_dir, presets_dir, lists_dir)
-        self.ctx = ConfigContext()
-        self.config_source_banner = None
-        self.current_selected_packs = []
-        self.is_locked = False
-        self.previous_source = None
-        self.previous_banner_text = "Using: Global Config"
-        self.current_preset_name = None
-
-        # Initialize API-related variables
-        self.api_url_var = tk.StringVar(value="http://127.0.0.1:7860")
-        self.preset_var = tk.StringVar(value="default")
-        self._wrappable_labels: list[tk.Widget] = []
-        self.scrollable_sections: dict[str, dict[str, tk.Widget | None]] = {}
-        self._log_min_lines = 7
-        self._image_warning_threshold = 250
-        self.upscaler_names: list[str] = []
-        self.sampler_names: list[str] = []
-
-        # Initialize aesthetic/randomization defaults before building UI
-        self.aesthetic_script_available = False
-        self.aesthetic_extension_root: Path | None = None
-        self.aesthetic_embeddings: list[str] = ["None"]
-        self.aesthetic_embedding_var = tk.StringVar(value="None")
-        self.aesthetic_status_var = tk.StringVar(value="Aesthetic extension not detected")
-        self.aesthetic_widgets: dict[str, list[tk.Widget]] = {
-            "all": [],
-            "script": [],
-            "prompt": [],
-        }
-
-        # Stage toggles used by multiple panels
-        self.txt2img_enabled = tk.BooleanVar(value=True)
-        self.img2img_enabled = tk.BooleanVar(value=True)
-        self.adetailer_enabled = tk.BooleanVar(value=False)
-        self.upscale_enabled = tk.BooleanVar(value=True)
-        self.video_enabled = tk.BooleanVar(value=False)
-        self._config_dirty = False
-        self._config_panel_prefs_bound = False
-        self._preferences_ready = False
-        self._new_features_dialog_shown = False
-
-        # Initialize progress-related attributes
-        self._progress_eta_default = "ETA: --:--"
-        self._progress_idle_message = "Ready"
-        self._last_randomizer_plan_result = None
-        self._randomizer_variant_update_job: int | None = None
-        self._ai_settings_enabled = bool(os.environ.get("ENABLE_AI_SETTINGS_GENERATOR"))
-
-        # Load preferences before building UI
-        default_config = self.config_manager.get_default_config()
-        try:
-            self.preferences = self.preferences_manager.load_preferences(default_config)
-        except Exception as exc:
-            logger.error(
-                "Failed to load preferences; falling back to defaults: %s", exc, exc_info=True
-            )
-            self.preferences = self.preferences_manager.default_preferences(default_config)
-            self._handle_preferences_load_failure(exc)
-
-        # Build the user interface
-        if self.layout_version == "v2":
-            self._build_ui_v2()
-        else:
-            self._build_ui()
-        self._wire_progress_callbacks()
-        try:
-            self.root.bind("<Configure>", self._on_root_resize, add="+")
-        except Exception:
-            pass
-        self._reset_config_dirty_state()
-        self._preferences_ready = True
-
-        # Initialize summary variables for live config display
-        self.txt2img_summary_var = tk.StringVar(value="")
-        self.img2img_summary_var = tk.StringVar(value="")
-        self.upscale_summary_var = tk.StringVar(value="")
-        self._maybe_show_new_features_dialog()
-
-    def _apply_webui_status(self, status) -> None:
-        # Update any labels/combos based on discovered status.
-        # (Implement specific UI updates in your controls panel)
-        try:
-            self.pipeline_controls_panel.on_webui_status(status)
-        except Exception:
-            logger.exception("Failed to apply WebUI status")
-
-    def _apply_webui_error(self, e: Exception) -> None:
-        logger.warning("WebUI error: %s", e)
-        # Optionally update UI to reflect disconnected state
-        try:
-            self.pipeline_controls_panel.on_webui_error(e)
-        except Exception:
-            logger.exception("Failed to apply WebUI error")
-
-    def _update_config_source_banner(self, text: str) -> None:
-        """Update the config source banner with the given text."""
-        self.config_source_banner.config(text=text)
-
-    def _effective_cfg_for_pack(self, pack: str) -> dict[str, Any]:
-        """Get the effective config for a pack based on current ctx.source."""
-        if self.ctx.source is ConfigSource.GLOBAL_LOCK and self.ctx.locked_cfg is not None:
-            return deepcopy(self.ctx.locked_cfg)
-        if self.ctx.source is ConfigSource.PRESET:
-            return deepcopy(self.ctx.editor_cfg)
-        cfg = self.config_service.load_pack_config(pack)
-        return cfg if cfg else deepcopy(self.ctx.editor_cfg)  # fallback to editor defaults
-
-    def _preview_payload_dry_run(self) -> None:
-        """
-        Dry-run the selected packs and report how many prompts/variants would be produced.
-        """
-        selected_packs = self._get_selected_packs()
-        if not selected_packs:
-            self.log_message("No prompt packs selected for dry run", "WARNING")
-            return
-        selected_copy = list(selected_packs)
-
-        def worker():
-            config_snapshot = self._get_config_snapshot()
-            rand_cfg = deepcopy(config_snapshot.get("randomization") or {})
-
-            total_prompts = 0
-            total_variants = 0
-            sample_variants: list[PromptVariant] = []
-            pack_summaries: list[str] = []
-
-            for pack_path in selected_copy:
-                prompts = read_prompt_pack(pack_path)
-                if not prompts:
-                    self.log_message(
-                        f"[DRY RUN] No prompts found in {pack_path.name}", "WARNING"
-                    )
-                    continue
-
-                total_prompts += len(prompts)
-                pack_variants, pack_samples = self._estimate_pack_variants(
-                    prompts, deepcopy(rand_cfg)
-                )
-                total_variants += pack_variants
-                pack_summaries.append(
-                    f"[DRY RUN] Pack {pack_path.name}: {len(prompts)} prompt(s) -> {pack_variants} variant(s)"
-                )
-                for variant in pack_samples:
-                    if len(sample_variants) >= 10:
-                        break
-                    sample_variants.append(variant)
-
-            images_per_prompt = self._safe_int_from_var(self.images_per_prompt_var, 1)
-            loop_multiplier = self._safe_int_from_var(self.loop_count_var, 1)
-            predicted_images = total_variants * images_per_prompt * loop_multiplier
-
-            summary = (
-                f"[DRY RUN] {len(selected_copy)} pack(s) • "
-                f"{total_prompts} prompt(s) • "
-                f"{total_variants} variant(s) × {images_per_prompt} img/prompt × loops={loop_multiplier} "
-                f"→ ≈ {predicted_images} image(s)"
-            )
-            self.log_message(summary, "INFO")
-
-            for line in pack_summaries:
-                self.log_message(line, "INFO")
-
-            for idx, variant in enumerate(sample_variants[:5], start=1):
-                label_part = f" ({variant.label})" if variant.label else ""
-                preview_text = (variant.text or "")[:200]
-                self.log_message(f"[DRY RUN] ex {idx}{label_part}: {preview_text}", "INFO")
-
-            self._maybe_warn_large_output(predicted_images, "dry run preview")
-
-        threading.Thread(target=worker, daemon=True).start()
-
-    def _safe_int_from_var(self, var: tk.Variable | None, default: int = 1) -> int:
-        try:
-            value = int(var.get()) if var is not None else default
-        except Exception:
-            value = default
-        return value if value > 0 else default
-
-    def _estimate_pack_variants(
-        self, prompts: list[dict[str, str]], rand_cfg: dict[str, Any]
-    ) -> tuple[int, list[PromptVariant]]:
-        total = 0
-        samples: list[PromptVariant] = []
-        if not prompts:
-            return 0, samples
-
-        simulator: PromptRandomizer | None = None
-        rand_enabled = bool(rand_cfg.get("enabled")) if isinstance(rand_cfg, dict) else False
-        if rand_enabled:
-            try:
-                simulator = PromptRandomizer(deepcopy(rand_cfg))
-            except Exception:
-                simulator = None
-
-        for prompt_data in prompts:
-            prompt_text = prompt_data.get("positive", "") or ""
-            if simulator:
-                variants = simulator.generate(prompt_text)
-                if not variants:
-                    variants = [PromptVariant(text=prompt_text, label=None)]
-            else:
-                variants = [PromptVariant(text=prompt_text, label=None)]
-
-            total += len(variants)
-            if len(samples) < 10:
-                samples.extend(variants[:2])
-
-        return total, samples
-
-    def _maybe_warn_large_output(self, count: int, context: str) -> bool:
-        """Warn about very large runs while avoiding modal dialogs off the Tk thread."""
-
-        threshold = getattr(self, "_image_warning_threshold", 0) or 0
-        if not threshold or count < threshold:
-            return True
-
-        self.log_message(
-            f"⚠️ Expected to generate approximately {count} image(s) for {context}. "
-            "Adjust Randomization or Images/Prompt if this is unintended.",
-            "WARNING",
-        )
-
-        suppress = is_gui_test_mode() or os.environ.get("STABLENEW_NO_DIALOGS") in {
-            "1",
-            "true",
-            "TRUE",
-        }
-        if suppress:
-            logger.warning(
-                "Large run estimate (%d images for %s) but dialogs suppressed; proceeding automatically.",
-                count,
-                context,
-            )
-            return True
-
-        if threading.current_thread() is not threading.main_thread():
-            logger.warning(
-                "Large run estimate (%d images for %s) but warning invoked off Tk thread; "
-                "skipping dialog to avoid deadlock.",
-                count,
-                context,
-            )
-            return True
-
-        message = (
-            f"This run may generate approximately {count} image(s) for {context}. "
-            "This could take a long time. Do you want to continue?"
-        )
-        try:
-            return messagebox.askyesno("Large Run Warning", message)
-        except Exception:
-            logger.exception("Failed to display large-run warning dialog")
-            return True
-
-
-    # -------- mediator selection -> config refresh --------
-    def _on_pack_selection_changed_mediator(self, packs: list[str]) -> None:
-        """
-        Mediator callback from PromptPackPanel; always UI thread.
-        We keep this handler strictly non-blocking and UI-only.
-        """
-        try:
-            self.current_selected_packs = packs
-            count = len(packs)
-            if count == 0:
-                logger.info("📦 No pack selected")
-            else:
-                logger.info("📦 Selected pack: %s", packs[0] if count == 1 else f"{count} packs")
-            # Update banner instead of refreshing config
-            if packs:
-                if len(packs) == 1:
-                    text = "Using: Pack Config"
-                else:
-                    text = "Using: Multi-Pack Config"
-            else:
-                text = "Using: Global Config"
-            self._update_config_source_banner(text)
-        except Exception:
-            logger.exception("Mediator selection handler failed")
-
-    def _refresh_config(self, packs: list[str]) -> None:
-        """
-        Load pack config and apply to controls. UI-thread only. Non-reentrant.
-        """
-        if self._refreshing_config:
-            logger.debug("[DIAG] _refresh_config: re-entry detected; skipping")
-            return
-
-        self._refreshing_config = True
-        try:
-            # We currently apply config for first selected pack
-            pack = packs[0]
-            cfg = self.config_manager.load_pack_config(pack)  # disk read is fine; cheap
-            logger.debug("Loaded pack config: %s", pack)
-
-            # Push config to controls panel (must be UI-only logic)
-            self.pipeline_controls_panel.apply_config(cfg)
-            logger.info("Loaded config for pack: %s", pack)
-
-        except Exception as e:
-            logger.exception("Failed to refresh config: %s", e)
-            self._safe_messagebox("error", "Config Error", f"{type(e).__name__}: {e}")
-        finally:
-            self._refreshing_config = False
-
-    # -------- run pipeline --------
-    def _on_run_clicked(self) -> None:
-        """Handler for RUN button; delegates to the canonical pipeline starter."""
-        try:
-            try:
-                selected = self.prompt_pack_panel.get_selected_packs()
-            except Exception:
-                selected = []
-            if not selected:
-                self._safe_messagebox(
-                    "warning", "No Pack Selected", "Please select a prompt pack first."
-                )
-                return
-
-            packs_str = selected[0] if len(selected) == 1 else f"{len(selected)} packs"
-            logger.info("▶️ Starting pipeline execution for %s", packs_str)
-
-            # Delegate to the canonical runner that wires controller callbacks.
-            self._run_full_pipeline()
-
-        except Exception as e:
-            logger.exception("Run click failed: %s", e)
-            self._safe_messagebox("error", "Run Failed", f"{type(e).__name__}: {e}")
-
-    def _on_cancel_clicked(self) -> None:
-        """Handler for STOP/CANCEL button."""
-        try:
-            stopping = self.controller.stop_pipeline()
-        except Exception as exc:
-            self.log_message(f"⏹️ Stop failed: {exc}", "ERROR")
-            return
-
-        if stopping:
-            self.log_message("⏹️ Stop requested - cancelling pipeline...", "WARNING")
-        else:
-            self.log_message("⏹️ No pipeline running", "INFO")
-    # -------- utilities --------
-    def on_error(self, error: Exception | str) -> None:
-        """Expose a public error handler for legacy controller/test hooks."""
-        if isinstance(error, Exception):
-            message = f"{type(error).__name__}: {error}"
-        else:
-            message = str(error) if error else "Pipeline error"
-
-        try:
-            self.state_manager.transition_to(GUIState.ERROR)
-        except Exception:
-            logger.exception("Failed to transition GUI state to ERROR after pipeline error")
-
-        self._signal_pipeline_finished()
-
-        def handle_error() -> None:
-            self._handle_pipeline_error_main_thread(message, error)
-
-        try:
-            self.root.after(0, handle_error)
-        except Exception:
-            handle_error()
-
-    def _handle_pipeline_error_main_thread(self, message: str, error: Exception | str) -> None:
-        """Perform UI-safe pipeline error handling on the Tk thread."""
-
-        self.log_message(f"? Pipeline error: {message}", "ERROR")
-
-        suppress_dialog = is_gui_test_mode() or os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {
-            "1",
-            "true",
-            "TRUE",
-        }
-        if not suppress_dialog:
-            self._safe_messagebox("error", "Pipeline Error", message)
-
-    # Duplicate _setup_theme and other duplicate/unused methods removed for linter/ruff compliance
-
-    def _launch_webui(self):
-        """Request WebUI startup via the configured process manager (non-blocking)."""
-        if os.environ.get("STABLENEW_NO_WEBUI", "").lower() in {"1", "true", "yes"}:
-            logger.info("Auto-launch of WebUI disabled by STABLENEW_NO_WEBUI")
-            return
-
-        def discovery_and_launch():
-            def safe_after(delay_ms: int, func):
-                try:
-                    self.root.after(delay_ms, func)
-                except RuntimeError:
-                    logger.debug("Tk not ready for after() in discovery_and_launch", exc_info=True)
-
-            manager = getattr(self, "webui_process_manager", None)
-            if manager is None:
-                logger.info("No WebUI process manager configured; skipping autostart")
-                safe_after(0, self._check_api_connection)
-                return
-
-            try:
-                manager.start()
-                self.log_message("?? Launching Stable Diffusion WebUI via process manager...", "INFO")
-            except Exception as exc:
-                self.log_message(f"? WebUI launch failed: {exc}", "ERROR")
-                return
-
-            safe_after(1000, self._check_api_connection)
-            safe_after(10_000, self._check_api_connection)
-            safe_after(13_000, self._check_api_connection)
-
-            def final_notice():
-                if not getattr(self, "api_connected", False):
-                    self.log_message(
-                        "? Unable to connect to WebUI after auto-start attempts. Please start WebUI manually.",
-                        "ERROR",
-                    )
-                    suppress = is_gui_test_mode() or os.environ.get("STABLENEW_NO_DIALOGS") in {
-                        "1",
-                        "true",
-                        "TRUE",
-                    }
-                    if not suppress:
-                        try:
-                            messagebox.showerror(
-                                "WebUI Connection",
-                                "Unable to connect to Stable Diffusion WebUI after auto-start attempts.\n"
-                                "Please start WebUI manually and click 'Check API'.",
-                            )
-                        except Exception:
-                            logger.debug("Failed to display WebUI connection error dialog", exc_info=True)
-
-            safe_after(14_500, final_notice)
-
-        try:
-            self.root.after(50, discovery_and_launch)
-        except Exception:
-            logger.exception("Failed to schedule WebUI discovery/launch")
-
-    def _ensure_default_preset(self):
-        """Ensure default preset exists and load it if set as startup default"""
-        if "default" not in self.config_manager.list_presets():
-            default_config = self.config_manager.get_default_config()
-            self.config_manager.save_preset("default", default_config)
-
-        # Check if a default preset is configured for startup
-        default_preset_name = self.config_manager.get_default_preset()
-        if default_preset_name:
-            logger.info(f"Loading default preset on startup: {default_preset_name}")
-            preset_config = self.config_manager.load_preset(default_preset_name)
-            if preset_config:
-                self.current_preset = default_preset_name
-                self.current_config = preset_config
-                # preset_var will be set in __init__ after this call
-                self.preferences["preset"] = default_preset_name
-            else:
-                logger.warning(f"Failed to load default preset '{default_preset_name}'")
-
-    def _build_ui_v2(self) -> None:
-        """Explicit V2 entrypoint (currently delegates to the unified builder)."""
-        self._build_ui()
-
-    def _build_ui(self):
-        """Build the modern user interface"""
-        # Create main container with minimal padding for space efficiency
-        main_frame = ttk.Frame(self.root, style="Dark.TFrame")
-        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
-
-        # Config source banner at the top
-        self.config_source_banner = ttk.Label(
-            main_frame, text="Using: Pack Config", style="Dark.TLabel"
-        )
-        self.config_source_banner.pack(anchor=tk.W, padx=5, pady=(0, 5))
-
-        # Action bar for explicit config loading
-        self._build_action_bar(main_frame)
-
-        # Main content + log splitter so the bottom panel stays visible
-        vertical_split = ttk.Panedwindow(main_frame, orient=tk.VERTICAL, style="Dark.TPanedwindow")
-        self._vertical_split = vertical_split
-        vertical_split.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
-
-        # Main content frame - optimized layout
-        content_frame = ttk.Frame(vertical_split, style="Dark.TFrame")
-
-        # Bottom shell reserved for logs/status; create early so AppLayoutV2 can hook status bar
-        bottom_shell = ttk.Frame(vertical_split, style="Dark.TFrame")
-        self._bottom_pane = bottom_shell
-        self.bottom_zone = bottom_shell
-
-        vertical_split.add(content_frame, weight=5)
-        vertical_split.add(bottom_shell, weight=2)
-
-        # Configure grid for better space utilization
-        content_frame.columnconfigure(0, weight=1, minsize=280)
-        content_frame.columnconfigure(1, weight=3)
-        content_frame.columnconfigure(2, weight=1, minsize=260)
-        content_frame.rowconfigure(0, weight=1)
-
-        # Define layout zones; AppLayoutV2 owns panel composition
-        self.left_zone = ttk.Frame(content_frame, style="Dark.TFrame")
-        self.left_zone.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
-
-        self.center_zone = ttk.Frame(content_frame, style="Dark.TFrame")
-        self.center_zone.grid(row=0, column=1, sticky=tk.NSEW)
-        self.center_zone.columnconfigure(0, weight=1)
-
-        self.center_stack = ttk.Frame(self.center_zone, style="Dark.TFrame")
-        self.center_stack.pack(fill=tk.BOTH, expand=True)
-
-        self.right_zone = ttk.Frame(content_frame, style="Dark.TFrame")
-        self.right_zone.grid(row=0, column=2, sticky=tk.NSEW, padx=(5, 0))
-
-        # Let AppLayoutV2 create and attach V2 panels and the run button alias
-        self._layout_v2 = AppLayoutV2(self, theme=self.theme)
-        self._layout_v2.build_layout(getattr(self, "root", None))
-        try:
-            # Ensure status bar created by AppLayout can be re-packed after bottom panel scaffolding
-            if hasattr(self, "status_bar_v2"):
-                self.status_bar_v2.pack_forget()
-        except Exception:
-            pass
-
-        self._wire_pipeline_command_bar()
-
-        self._build_bottom_panel(bottom_shell)
-        if self._layout_v2:
-            self._layout_v2.attach_run_button(getattr(self, "run_pipeline_btn", None))
-
-        # Populate panels now that layout is composed
-        if getattr(self, "sidebar_panel_v2", None) is not None:
-            self._build_prompt_pack_panel(self.sidebar_panel_v2.body)
-        if getattr(self, "pipeline_panel_v2", None) is not None:
-            self.pipeline_panel_v2.set_txt2img_change_callback(self._on_pipeline_txt2img_updated)
-            self._build_config_pipeline_panel(self.pipeline_panel_v2.body)
-        if getattr(self, "randomizer_panel_v2", None) is not None:
-            self.randomizer_panel_v2.set_change_callback(self._on_randomizer_panel_changed)
-        self._initialize_pipeline_panel_config()
-        self._initialize_randomizer_panel_config()
-
-        # Defer all heavy UI state initialization until after Tk mainloop starts
-        try:
-            self.root.after(0, self._initialize_ui_state_async)
-        except Exception as exc:
-            logger.warning("Failed to schedule UI state init: %s", exc)
-
-        # Setup state callbacks
-        self._setup_state_callbacks()
-
-        # Attempt to auto-launch WebUI / discover API on startup via process manager
-        try:
-            self._launch_webui()
-        except Exception:
-            logger.exception("Failed to launch WebUI")
-
-        try:
-            self.root.after(1500, self._check_api_connection)
-        except Exception:
-            logger.warning("Unable to schedule API connection check")
-
-    def _wire_pipeline_command_bar(self) -> None:
-        """Route run/stop/queue controls through the new command bar."""
-
-        panel = getattr(self, "pipeline_panel_v2", None)
-        command_bar = getattr(panel, "command_bar", None)
-        if command_bar is None:
-            return
-
-        try:
-            command_bar.run_button.configure(command=self._run_full_pipeline)
-        except Exception:
-            pass
-        try:
-            command_bar.stop_button.configure(command=self._on_cancel_clicked)
-        except Exception:
-            pass
-
-        try:
-            command_bar.set_queue_mode(is_queue_execution_enabled())
-        except Exception:
-            pass
-        try:
-            command_bar.set_queue_toggle_callback(self._on_queue_mode_toggled)
-        except Exception:
-            pass
-
-        self.run_pipeline_btn = command_bar.run_button
-        self.run_button = self.run_pipeline_btn
-        self.stop_button = command_bar.stop_button
-        try:
-            self._attach_tooltip(
-                self.run_pipeline_btn,
-                "Process every highlighted pack sequentially using the current configuration. Override mode applies when enabled.",
-            )
-        except Exception:
-            pass
-        self._apply_run_button_state()
-
-    def _update_webui_state(self, state) -> None:
-        panel = getattr(self, "api_status_panel", None)
-        if panel and hasattr(panel, "set_webui_state"):
-            try:
-                panel.set_webui_state(state)
-            except Exception:
-                pass
-        if state == WebUIConnectionState.READY:
-            self.api_connected = True
-        elif state in {WebUIConnectionState.ERROR, WebUIConnectionState.DISCONNECTED, WebUIConnectionState.DISABLED}:
-            self.api_connected = False
-        self._apply_run_button_state()
-
-    def _ensure_webui_connection(self, autostart: bool) -> WebUIConnectionState:
-        state = None
-        ctrl = getattr(self, "controller", None)
-        if ctrl is not None and hasattr(ctrl, "_webui_connection"):
-            try:
-                state = ctrl._webui_connection.ensure_connected(autostart=autostart)
-            except Exception:
-                state = WebUIConnectionState.ERROR
-        if state is None:
-            state = WebUIConnectionState.ERROR
-        self._update_webui_state(state)
-        return state
-
-    def _on_webui_launch(self):
-        manager = getattr(self, "webui_process_manager", None)
-        if manager is not None:
-            try:
-                manager.start()
-            except Exception as exc:
-                self.log_message(f"? Failed to start WebUI: {exc}", "ERROR")
-        self._ensure_webui_connection(autostart=True)
-
-    def _on_webui_retry(self):
-        self._ensure_webui_connection(autostart=False)
-
-    def _on_webui_reconnect(self):
-        self._ensure_webui_connection(autostart=True)
-
-
-    def _build_api_status_frame(self, parent):
-        """Build the API status frame using APIStatusPanel."""
-        # Prefer the status bar's embedded WebUI panel when available to avoid duplicates.
-        existing_panel = getattr(getattr(self, "status_bar_v2", None), "webui_panel", None)
-        if existing_panel is not None:
-            self.api_status_panel = existing_panel
-            try:
-                self.api_status_panel.set_launch_callback(self._on_webui_launch)
-                self.api_status_panel.set_retry_callback(self._on_webui_retry)
-            except Exception:
-                pass
-            try:
-                state = None
-                ctrl = getattr(self, "controller", None)
-                if ctrl and hasattr(ctrl, "get_webui_connection_state"):
-                    state = ctrl.get_webui_connection_state()
-                if state is None:
-                    state = WebUIConnectionState.DISCONNECTED
-                self._update_webui_state(state)
-            except Exception:
-                pass
-            return
-
-        frame = ttk.Frame(
-            parent,
-            style=getattr(self.theme, "SURFACE_FRAME_STYLE", "Dark.TFrame"),
-            relief=tk.SUNKEN,
-        )
-        frame.pack(fill=tk.X, padx=5, pady=(4, 0))
-        frame.configure(height=48)
-        frame.pack_propagate(False)
-
-        self.api_status_panel = APIStatusPanel(
-            frame,
-            coordinator=self,
-            style=getattr(self.theme, "SURFACE_FRAME_STYLE", "Dark.TFrame"),
-        )
-        self.api_status_panel.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
-        try:
-            self.api_status_panel.set_launch_callback(self._on_webui_launch)
-            self.api_status_panel.set_retry_callback(self._on_webui_retry)
-        except Exception:
-            pass
-        try:
-            state = None
-            ctrl = getattr(self, "controller", None)
-            if ctrl and hasattr(ctrl, "get_webui_connection_state"):
-                state = ctrl.get_webui_connection_state()
-            if state is None:
-                state = WebUIConnectionState.DISCONNECTED
-            self._update_webui_state(state)
-        except Exception:
-            pass
-
-    def _build_prompt_pack_panel(self, parent):
-        """Build the prompt pack selection panel."""
-        # Create PromptPackPanel
-        self.prompt_pack_panel = PromptPackPanel(
-            parent,
-            coordinator=self,
-            on_selection_changed=self._on_pack_selection_changed_mediator,
-            style="Dark.TFrame",
-        )
-        self.prompt_pack_panel.pack(fill=tk.BOTH, expand=True)
-
-    def _build_config_pipeline_panel(self, parent):
-        """Build the consolidated configuration notebook with Pipeline, Randomization, and General tabs."""
-        # Create main notebook for center panel
-        self.center_notebook = ttk.Notebook(parent, style="Dark.TNotebook")
-        self.center_notebook.pack(fill=tk.BOTH, expand=True)
-
-        # Pipeline tab - configuration
-        pipeline_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
-        self.center_notebook.add(pipeline_tab, text="Pipeline")
-
-        self._build_info_box(
-            pipeline_tab,
-            "Pipeline Configuration",
-            "Configure txt2img, img2img, and upscale behavior for the next run. "
-            "Use override mode to apply these settings to every selected pack.",
-        ).pack(fill=tk.X, padx=10, pady=(10, 4))
-
-        try:
-            override_header = ttk.Frame(pipeline_tab, style="Dark.TFrame")
-            override_header.pack(fill=tk.X, padx=10, pady=(0, 4))
-            override_checkbox = ttk.Checkbutton(
-                override_header,
-                text="Override pack settings with current config",
-                variable=self.override_pack_var,
-                style="Dark.TCheckbutton",
-                command=self._on_override_changed,
-            )
-            override_checkbox.pack(side=tk.LEFT)
-            self._attach_tooltip(
-                override_checkbox,
-                "When enabled, the visible configuration is applied to every selected pack. Disable to use each pack's saved config.",
-            )
-        except Exception:
-            pass
-
-        config_scroll = ttk.Frame(pipeline_tab, style="Dark.TFrame")
-        config_scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
-        pipeline_canvas, config_body = make_scrollable(config_scroll, style="Dark.TFrame")
-        self._register_scrollable_section("pipeline", pipeline_canvas, config_body)
-
-        self.config_panel = ConfigPanel(config_body, coordinator=self, style="Dark.TFrame")
-        self.config_panel.pack(fill=tk.BOTH, expand=True)
-
-        self.txt2img_vars = self.config_panel.txt2img_vars
-        self.img2img_vars = self.config_panel.img2img_vars
-        self.upscale_vars = self.config_panel.upscale_vars
-        self.api_vars = self.config_panel.api_vars
-        self.config_status_label = self.config_panel.config_status_label
-        self.adetailer_panel = getattr(self.config_panel, "adetailer_panel", None)
-
-        try:
-            summary_frame = ttk.LabelFrame(
-                pipeline_tab, text="Next Run Summary", style="Dark.TLabelframe", padding=5
-            )
-            summary_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
-
-            self.txt2img_summary_var = getattr(self, "txt2img_summary_var", tk.StringVar(value=""))
-            self.img2img_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
-            self.upscale_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
-            self.upscale_summary_var = getattr(self, "upscale_summary_var", tk.StringVar(value=""))
-
-            for var in (
-                self.txt2img_summary_var,
-                self.img2img_summary_var,
-                self.upscale_summary_var,
-            ):
-                ttk.Label(
-                    summary_frame,
-                    textvariable=var,
-                    style="Dark.TLabel",
-                    font=("Consolas", 9),
-                ).pack(anchor=tk.W, pady=1)
-
-            self._attach_summary_traces()
-            self._update_live_config_summary()
-        except Exception:
-            pass
-
-        # Randomization tab
-        randomization_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
-        self.center_notebook.add(randomization_tab, text="Randomization")
-        self._build_randomization_tab(randomization_tab)
-
-        # General tab - pipeline controls and API settings
-        general_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
-        self.center_notebook.add(general_tab, text="General")
-
-        general_split = ttk.Frame(general_tab, style="Dark.TFrame")
-        general_split.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))
-
-        general_scroll_container = ttk.Frame(general_split, style="Dark.TFrame")
-        general_scroll_container.pack(fill=tk.BOTH, expand=True)
-        general_canvas, general_body = make_scrollable(general_scroll_container, style="Dark.TFrame")
-        self._register_scrollable_section("general", general_canvas, general_body)
-
-        self._build_info_box(
-            general_body,
-            "General Settings",
-            "Manage batch size, looping behavior, and API connectivity. "
-            "These settings apply to every run regardless of prompt pack.",
-        ).pack(fill=tk.X, pady=(0, 6))
-
-        video_frame = ttk.Frame(general_body, style="Dark.TFrame")
-        video_frame.pack(fill=tk.X, pady=(0, 4))
-        ttk.Checkbutton(
-            video_frame,
-            text="Enable video stage",
-            variable=self.video_enabled,
-            style="Dark.TCheckbutton",
-        ).pack(anchor=tk.W)
-
-        # Pipeline controls in General tab
-        self._build_pipeline_controls_panel(general_body)
-        if self._ai_settings_enabled:
-            self._build_ai_settings_button(general_body)
-
-        api_frame = ttk.LabelFrame(
-            general_body, text="API Configuration", style="Dark.TLabelframe", padding=8
-        )
-        api_frame.pack(fill=tk.X, pady=(10, 10))
-        ttk.Label(api_frame, text="Base URL:", style="Dark.TLabel").grid(
-            row=0, column=0, sticky=tk.W, pady=2
-        )
-        ttk.Entry(
-            api_frame,
-            textvariable=self.api_vars.get("base_url"),
-            style="Dark.TEntry",
-        ).grid(row=0, column=1, sticky=tk.EW, pady=2, padx=(5, 0))
-        api_frame.columnconfigure(1, weight=1)
-
-        ttk.Label(api_frame, text="Timeout (s):", style="Dark.TLabel").grid(
-            row=1, column=0, sticky=tk.W, pady=2
-        )
-        ttk.Entry(
-            api_frame,
-            textvariable=self.api_vars.get("timeout"),
-            style="Dark.TEntry",
-        ).grid(row=1, column=1, sticky=tk.EW, pady=2, padx=(5, 0))
-
-        # Advanced editor tab for legacy editor access
-        advanced_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
-        self.center_notebook.add(advanced_tab, text="Advanced Editor")
-        self._build_advanced_editor_tab(advanced_tab)
-
-    def _initialize_pipeline_panel_config(self) -> None:
-        panel = getattr(self, "pipeline_panel_v2", None)
-        if panel is None:
-            return
-        try:
-            initial_config = getattr(self, "current_config", None)
-            if not initial_config and getattr(self, "config_manager", None):
-                initial_config = self.config_manager.get_default_config()
-            if initial_config:
-                panel.load_from_config(initial_config)
-                self._refresh_txt2img_validation(broadcast_status=False)
-        except Exception:
-            logger.debug("Unable to initialize PipelinePanelV2 config", exc_info=True)
-
-    def _initialize_randomizer_panel_config(self) -> None:
-        panel = getattr(self, "randomizer_panel_v2", None)
-        if panel is None:
-            return
-        try:
-            initial_config = getattr(self, "current_config", None)
-            if not initial_config and getattr(self, "config_manager", None):
-                initial_config = self.config_manager.get_default_config()
-            if initial_config:
-                panel.load_from_config(initial_config)
-            self._refresh_randomizer_variant_count()
-        except Exception:
-            logger.debug("Unable to initialize RandomizerPanelV2 config", exc_info=True)
-
-    def _apply_pipeline_panel_overrides(self, config_snapshot: dict) -> dict:
-        panel = getattr(self, "pipeline_panel_v2", None)
-        if panel is None:
-            return config_snapshot
-        try:
-            delta = panel.to_config_delta() or {}
-        except Exception:
-            logger.debug("PipelinePanelV2 delta failed", exc_info=True)
-            delta = {}
-        return build_effective_config(
-            config_snapshot or {},
-            txt2img_overrides=delta.get("txt2img"),
-            img2img_overrides=delta.get("img2img"),
-            upscale_overrides=delta.get("upscale"),
-            pipeline_overrides=delta.get("pipeline"),
-        )
-
-    def get_gui_overrides(self) -> dict[str, object]:
-        """Expose current GUI core overrides for the controller/assembler path."""
-        overrides: dict[str, object] = {}
-        panel = getattr(self, "pipeline_panel_v2", None)
-        if panel:
-            try:
-                overrides["prompt"] = panel.get_prompt()
-            except Exception:
-                overrides["prompt"] = ""
-        sidebar = getattr(self, "sidebar_panel_v2", None)
-        if sidebar:
-            try:
-                overrides.update(sidebar.get_model_overrides())
-            except Exception:
-                pass
-            try:
-                overrides.update(sidebar.get_core_overrides())
-            except Exception:
-                pass
-            try:
-                overrides["negative_prompt"] = sidebar.get_negative_prompt()
-            except Exception:
-                pass
-            try:
-                width, height = sidebar.get_resolution()
-                overrides["width"] = width
-                overrides["height"] = height
-                overrides["resolution_preset"] = sidebar.get_resolution_preset()
-            except Exception:
-                pass
-            try:
-                overrides.update(sidebar.get_output_overrides())
-            except Exception:
-                pass
-        return overrides
-
-    def _build_randomizer_plan_result(self, config_snapshot: dict):
-        panel = getattr(self, "randomizer_panel_v2", None)
-        if panel is None or config_snapshot is None:
-            return None
-        try:
-            plan_result = panel.build_variant_plan(config_snapshot)
-            self._last_randomizer_plan_result = plan_result
-            return plan_result
-        except Exception:
-            logger.debug("Randomizer plan evaluation failed", exc_info=True)
-            return None
-
-    def _on_randomizer_panel_changed(self) -> None:
-        if getattr(self, "root", None) is None:
-            return
-        if self._randomizer_variant_update_job:
-            try:
-                self.root.after_cancel(self._randomizer_variant_update_job)
-            except Exception:
-                pass
-        try:
-            self._randomizer_variant_update_job = self.root.after(
-                0, self._refresh_randomizer_variant_count
-            )
-        except Exception:
-            self._refresh_randomizer_variant_count()
-
-    def _refresh_randomizer_variant_count(self) -> None:
-        self._randomizer_variant_update_job = None
-        panel = getattr(self, "randomizer_panel_v2", None)
-        if panel is None:
-            return
-        base_config = self._current_randomizer_base_config()
-        options = panel.get_randomizer_options()
-        try:
-            count = compute_variant_count(base_config, options)
-        except Exception:
-            count = 1
-        panel.update_variant_count(count)
-
-    def _current_randomizer_base_config(self) -> dict:
-        try:
-            snapshot = self._get_config_from_forms()
-            if snapshot:
-                return snapshot
-        except Exception:
-            pass
-        try:
-            if getattr(self, "current_config", None):
-                return deepcopy(self.current_config)
-        except Exception:
-            pass
-        if getattr(self, "config_manager", None):
-            try:
-                return self.config_manager.get_default_config()
-            except Exception:
-                pass
-        return {}
-
-    def _on_pipeline_txt2img_updated(self) -> None:
-        self._refresh_txt2img_validation()
-
-    def _refresh_txt2img_validation(self, *, broadcast_status: bool = True) -> bool:
-        panel = getattr(self, "pipeline_panel_v2", None)
-        if panel is None:
-            return True
-        try:
-            result = panel.validate_txt2img()
-        except Exception:
-            logger.debug("txt2img validation failed", exc_info=True)
-            return True
-
-        self._last_txt2img_validation_result = result
-        is_valid = bool(getattr(result, "is_valid", True))
-        self._run_button_validation_locked = not is_valid
-        self._apply_run_button_state()
-
-        status_bar = getattr(self, "status_bar_v2", None)
-        if status_bar is not None:
-            if is_valid:
-                status_bar.clear_validation_error()
-            elif broadcast_status:
-                status_bar.set_validation_error(self._describe_validation_error(result))
-        return is_valid
-
-    @staticmethod
-    def _describe_validation_error(result) -> str:
-        errors = getattr(result, "errors", None) or {}
-        try:
-            return next(iter(errors.values()))
-        except StopIteration:
-            return "Invalid configuration."
-
-    def _apply_run_button_state(self) -> None:
-        button = getattr(self, "run_pipeline_btn", None)
-        if button is None:
-            return
-        allowed_states = {GUIState.IDLE, GUIState.ERROR}
-        current_state = getattr(self.state_manager, "current_state", GUIState.IDLE)
-        state_allows = current_state in allowed_states
-        connected = getattr(self, "api_connected", False)
-        enabled = state_allows and connected and not self._run_button_validation_locked
-        button.config(state=tk.NORMAL if enabled else tk.DISABLED)
-
-    def _on_queue_mode_toggled(self, enabled: bool | None = None) -> None:
-        try:
-            value = bool(enabled) if enabled is not None else False
-        except Exception:
-            value = False
-        try:
-            set_queue_execution_enabled(value)
-        except Exception:
-            pass
-        controller = getattr(self, "controller", None)
-        if controller is not None:
-            try:
-                setattr(controller, "_queue_execution_enabled", value)
-            except Exception:
-                pass
-
-    def _on_learning_toggle(self, enabled: bool) -> None:
-        try:
-            self.controller.set_learning_enabled(bool(enabled))
-        except Exception:
-            pass
-        try:
-            self.learning_execution_controller.set_learning_enabled(bool(enabled))
-        except Exception:
-            pass
-        try:
-            self.learning_enabled_var.set(bool(enabled))
-        except Exception:
-            pass
-
-    def _open_learning_review_dialog(self) -> None:
-        try:
-            records = self.learning_execution_controller.list_recent_records(limit=10)
-            LearningReviewDialogV2(self.root, self.learning_execution_controller, records)
-        except Exception:
-            logger.debug("Failed to open learning review dialog", exc_info=True)
-
-    def _handle_preferences_load_failure(self, exc: Exception) -> None:
-        """Notify the user that preferences failed to load and backup the corrupt file."""
-
-        warning_text = (
-            "Your last settings could not be loaded. StableNew has reset to safe defaults.\n\n"
-            "The previous settings file was moved aside (or removed) to prevent future issues."
-        )
-        try:
-            messagebox.showwarning("StableNew", warning_text)
-        except Exception:
-            logger.exception("Failed to display corrupt preferences warning dialog")
-
-        try:
-            self.preferences_manager.backup_corrupt_preferences()
-        except Exception:
-            logger.exception("Failed to backup corrupt preferences file")
-
-        self._reset_randomization_to_defaults()
-
-    def _initialize_ui_state_async(self):
-        """Initialize UI state asynchronously after mainloop starts."""
-        # Restore UI state from preferences
-        self._restore_ui_state_from_preferences()
-
-    def _initialize_ui_state(self):
-        """Legacy synchronous initialization hook retained for tests."""
-
-        self._initialize_ui_state_async()
-
-    def _restore_ui_state_from_preferences(self):
-        """Restore UI state from loaded preferences."""
-        try:
-            if "preset" in self.preferences:
-                self.preset_var.set(self.preferences["preset"])
-
-            if "selected_packs" in self.preferences:
-                self.current_selected_packs = self.preferences["selected_packs"]
-                if hasattr(self, "prompt_pack_panel"):
-                    self.prompt_pack_panel.set_selected_packs(self.current_selected_packs)
-
-            if "override_pack" in self.preferences and hasattr(self, "override_pack_var"):
-                self.override_pack_var.set(self.preferences["override_pack"])
-
-            if "pipeline_controls" in self.preferences and hasattr(self, "pipeline_controls_panel"):
-                self.pipeline_controls_panel.set_state(self.preferences["pipeline_controls"])
-
-            if "config" in self.preferences:
-                self.current_config = self.preferences["config"]
-                if hasattr(self, "config_panel"):
-                    self._load_config_into_forms(self.current_config)
-        except Exception as exc:
-            logger.error("Failed to restore preferences to UI; reverting to defaults: %s", exc)
-            try:
-                fallback_cfg = self.config_manager.get_default_config()
-                self.preferences = self.preferences_manager.default_preferences(fallback_cfg)
-                self.preset_var.set(self.preferences.get("preset", "default"))
-                self.current_selected_packs = []
-                if hasattr(self, "prompt_pack_panel"):
-                    self.prompt_pack_panel.set_selected_packs([])
-                if hasattr(self, "override_pack_var"):
-                    self.override_pack_var.set(False)
-                if hasattr(self, "pipeline_controls_panel"):
-                    self.pipeline_controls_panel.set_state(
-                        self.preferences.get("pipeline_controls", {})
-                    )
-                if hasattr(self, "config_panel"):
-                    self._load_config_into_forms(self.preferences.get("config", {}))
-                self._reset_randomization_to_defaults()
-            except Exception:
-                logger.exception("Failed to apply fallback preferences after restore failure")
-
-    def _reset_randomization_to_defaults(self) -> None:
-        """Reset randomization config to defaults and update UI if available."""
-
-        try:
-            default_cfg = self.config_manager.get_default_config() or {}
-            random_defaults = deepcopy(default_cfg.get("randomization", {}) or {})
-        except Exception as exc:
-            logger.error("Failed to obtain default randomization config: %s", exc)
-            return
-
-        self.preferences.setdefault("config", {})["randomization"] = random_defaults
-
-        if hasattr(self, "randomization_vars"):
-            try:
-                self._load_randomization_config({"randomization": random_defaults})
-            except Exception:
-                logger.exception("Failed to apply default randomization settings to UI")
-
-    def _build_action_bar(self, parent):
-        """Build the action bar with explicit load controls."""
-        action_bar = ttk.Frame(parent, style="Dark.TFrame")
-        action_bar.pack(fill=tk.X, padx=5, pady=(0, 5))
-
-        button_width = 28
-
-        def add_toolbar_button(container, column, text, command, tooltip=None, style="Dark.TButton"):
-            btn = ttk.Button(container, text=text, command=command, style=style, width=button_width)
-            btn.grid(row=0, column=column, padx=4, pady=2, sticky="ew")
-            container.grid_columnconfigure(column, weight=1)
-            if tooltip:
-                self._attach_tooltip(btn, tooltip)
-            return btn
-
-        row1 = ttk.Frame(action_bar, style="Dark.TFrame")
-        row1.pack(fill=tk.X, pady=(0, 4))
-        row2 = ttk.Frame(action_bar, style="Dark.TFrame")
-        row2.pack(fill=tk.X)
-
-        add_toolbar_button(
-            row1,
-            0,
-            "Load Pack Config",
-            self._ui_load_pack_config,
-            "Load the selected pack's saved configuration into the editor.",
-        )
-
-        preset_container = ttk.Frame(row1, style="Dark.TFrame")
-        preset_container.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
-        row1.grid_columnconfigure(1, weight=2)
-        ttk.Label(preset_container, text="Preset:", style="Dark.TLabel").pack(side=tk.LEFT)
-        self.preset_combobox = ttk.Combobox(
-            preset_container,
-            textvariable=self.preset_var,
-            values=self.config_service.list_presets(),
-            state="readonly",
-            width=30,
-            style="Dark.TCombobox",
-        )
-        self.preset_combobox.pack(side=tk.LEFT, padx=(5, 6))
-        preset_load_btn = ttk.Button(
-            preset_container, text="Load Preset", command=self._ui_load_preset, style="Dark.TButton"
-        )
-        preset_load_btn.pack(side=tk.LEFT)
-        self._attach_tooltip(preset_load_btn, "Load the selected preset into the editor.")
-
-        add_toolbar_button(
-            row1,
-            2,
-            "Save Editor → Preset",
-            self._ui_save_preset,
-            "Persist the current editor configuration to the active preset slot.",
-        )
-        add_toolbar_button(
-            row1,
-            3,
-            "Delete Preset",
-            self._ui_delete_preset,
-            "Remove the selected preset from disk.",
-            style="Danger.TButton",
-        )
-
-        list_container = ttk.Frame(row2, style="Dark.TFrame")
-        list_container.grid(row=0, column=0, padx=4, pady=2, sticky="ew")
-        row2.grid_columnconfigure(0, weight=2)
-        ttk.Label(list_container, text="List:", style="Dark.TLabel").pack(side=tk.LEFT)
-        self.list_combobox = ttk.Combobox(
-            list_container,
-            values=self.config_service.list_lists(),
-            state="readonly",
-            width=24,
-            style="Dark.TCombobox",
-        )
-        self.list_combobox.pack(side=tk.LEFT, padx=(5, 6))
-        list_load_btn = ttk.Button(
-            list_container, text="Load List", command=self._ui_load_list, style="Dark.TButton"
-        )
-        list_load_btn.pack(side=tk.LEFT)
-        self._attach_tooltip(list_load_btn, "Load saved pack selections from the chosen list.")
-
-        add_toolbar_button(
-            row2,
-            1,
-            "Save Selection as List",
-            self._ui_save_list,
-            "Persist the current pack selection as a reusable list.",
-        )
-        add_toolbar_button(
-            row2,
-            2,
-            "Overwrite List",
-            self._ui_overwrite_list,
-            "Replace the chosen list with the current selection.",
-        )
-        add_toolbar_button(
-            row2,
-            3,
-            "Delete List",
-            self._ui_delete_list,
-            "Remove the chosen list from disk.",
-            style="Danger.TButton",
-        )
-        self.lock_button = add_toolbar_button(
-            row2,
-            4,
-            "Lock This Config",
-            self._ui_toggle_lock,
-            "Prevent accidental edits by locking the current configuration.",
-        )
-        add_toolbar_button(
-            row2,
-            5,
-            "Apply Editor → Pack(s)",
-            self._ui_apply_editor_to_packs,
-            "Push the editor settings into the selected pack(s).",
-        )
-        add_toolbar_button(
-            row2,
-            6,
-            "Preview Payload (Dry Run)",
-            self._preview_payload_dry_run,
-            "Simulate a run and show prompt/variant counts without calling WebUI.",
-        )
-
-    def _build_menu_bar(self) -> None:
-        """Construct the top-level menu bar."""
-
-        menubar = tk.Menu(self.root)
-        settings_menu = tk.Menu(menubar, tearoff=0)
-        settings_menu.add_command(
-            label="Engine settings...",
-            command=self._open_engine_settings_dialog,
-        )
-        settings_menu.add_checkbutton(
-            label="Enable learning (record runs for review)",
-            variable=self.learning_enabled_var,
-            command=lambda: self._on_learning_toggle(self.learning_enabled_var.get()),
-        )
-        settings_menu.add_command(
-            label="Review recent runs...",
-            command=self._open_learning_review_dialog,
-        )
-        menubar.add_cascade(label="Settings", menu=settings_menu)
-        self.root.config(menu=menubar)
-        self._menubar = menubar
-        self._settings_menu = settings_menu
-
-    def _apply_editor_from_cfg(self, cfg: dict) -> None:
-        """Apply config to the editor (config panel)."""
-        if not cfg:
-            return
-        if hasattr(self, "config_panel"):
-            self.config_panel.set_config(cfg)
-        try:
-            self.pipeline_controls_panel.apply_config(cfg)
-        except Exception:
-            logger.debug("Pipeline controls apply_config skipped", exc_info=True)
-        try:
-            self._apply_adetailer_config_section(cfg.get("adetailer", {}))
-        except Exception:
-            logger.debug("ADetailer config apply skipped", exc_info=True)
-        try:
-            self._load_randomization_config(cfg)
-        except Exception:
-            logger.debug("Randomization config apply skipped", exc_info=True)
-        try:
-            self._load_aesthetic_config(cfg)
-        except Exception:
-            logger.debug("Aesthetic config apply skipped", exc_info=True)
-
-    def _apply_adetailer_config_section(self, adetailer_cfg: dict | None) -> None:
-        """Apply ADetailer config to the panel, normalizing scheduler defaults."""
-        panel = getattr(self, "adetailer_panel", None)
-        if not panel:
-            return
-        cfg = dict(adetailer_cfg or {})
-        scheduler_value = cfg.get("adetailer_scheduler", cfg.get("scheduler", "inherit")) or "inherit"
-        cfg["adetailer_scheduler"] = scheduler_value
-        cfg["scheduler"] = scheduler_value
-        panel.set_config(cfg)
-
-    def _ui_toggle_lock(self) -> None:
-        """Toggle the config lock state."""
-        if self.is_locked:
-            self._unlock_config()
-        else:
-            self._lock_config()
-
-    def _open_engine_settings_dialog(self) -> None:
-        """Open the Engine Settings dialog wired to WebUI options."""
-
-        if self.client is None:
-            messagebox.showerror(
-                "Engine Settings",
-                "Connect to the Stable Diffusion API before editing engine settings.",
-            )
-            return
-
-        try:
-            self._add_log_message("⚙️ Opening Engine Settings dialog…")
-        except Exception:
-            pass
-
-        try:
-            EngineSettingsDialog(self.root, self.client)
-        except Exception as exc:
-            messagebox.showerror("Engine Settings", f"Unable to open dialog: {exc}")
-
-    def _lock_config(self) -> None:
-        """Lock the current config."""
-        self.previous_source = self.ctx.source
-        self.previous_banner_text = self.config_source_banner.cget("text")
-        self.ctx.source = ConfigSource.GLOBAL_LOCK
-        self.ctx.locked_cfg = deepcopy(self.pipeline_controls_panel.get_settings())
-        self.is_locked = True
-        self.lock_button.config(text="Unlock Config")
-        self._update_config_source_banner("Using: Global Lock")
-
-    def _unlock_config(self) -> None:
-        """Unlock the config."""
-        self.ctx.source = self.previous_source
-        self.ctx.locked_cfg = None
-        self.is_locked = False
-        self.lock_button.config(text="Lock This Config")
-        self._update_config_source_banner(self.previous_banner_text)
-
-    def _ui_load_pack_config(self) -> None:
-        """Load config from the first selected pack into the editor."""
-        if self._check_lock_before_load():
-            if not self.current_selected_packs:
-                return
-            pack = self.current_selected_packs[0]
-            cfg = self.config_service.load_pack_config(pack)
-            if not cfg:
-                self._safe_messagebox(
-                    "info",
-                    "No Saved Config",
-                    f"No config saved for '{pack}'. Showing defaults.",
-                )
-                return
-            self._apply_editor_from_cfg(cfg)
-            self._update_config_source_banner("Using: Pack Config (view)")
-            self._reset_config_dirty_state()
-
-    def _ui_load_preset(self) -> None:
-        """Load selected preset into the editor."""
-        if self._check_lock_before_load():
-            name = self.preset_combobox.get()
-            if not name:
-                return
-            cfg = self.config_service.load_preset(name)
-            self._apply_editor_from_cfg(cfg)
-            self.current_preset_name = name
-            self._update_config_source_banner(f"Using: Preset: {name}")
-            self._reset_config_dirty_state()
-
-    def _check_lock_before_load(self) -> bool:
-        """Check if locked and prompt to unlock. Returns True if should proceed."""
-        if not self.is_locked:
-            return True
-        result = messagebox.askyesno("Config Locked", "Unlock to proceed?")
-        if result:
-            self._unlock_config()
-            return True
-        return False
-
-    def _ui_apply_editor_to_packs(self) -> None:
-        """Apply current editor config to selected packs."""
-        if not self.current_selected_packs:
-            messagebox.showwarning("No Selection", "Please select one or more packs first.")
-            return
-
-        num_packs = len(self.current_selected_packs)
-        result = messagebox.askyesno(
-            "Confirm Overwrite",
-            f"Overwrite configs for {num_packs} pack{'s' if num_packs > 1 else ''}?",
-        )
-        if not result:
-            return
-
-        # Capture the full editor config (txt2img/img2img/upscale/pipeline/randomization/etc.)
-        editor_cfg = self._get_config_from_forms()
-        if not editor_cfg:
-            messagebox.showerror("Error", "Unable to read the current editor configuration.")
-            return
-
-        # Save in worker thread
-        def save_worker():
-            try:
-                for pack in self.current_selected_packs:
-                    self.config_service.save_pack_config(pack, editor_cfg)
-                # Success callback on UI thread
-                def _on_success():
-                    messagebox.showinfo(
-                        "Success", f"Applied to {num_packs} pack{'s' if num_packs > 1 else ''}."
-                    )
-                    self._reset_config_dirty_state()
-
-                self.root.after(0, _on_success)
-            except Exception as exc:
-                error_msg = str(exc)
-                # Error callback on UI thread
-                self.root.after(
-                    0, lambda: messagebox.showerror("Error", f"Failed to save configs: {error_msg}")
-                )
-
-        threading.Thread(target=save_worker, daemon=True).start()
-
-    def _refresh_preset_dropdown(self) -> None:
-        """Refresh the preset dropdown with current presets."""
-        self.preset_combobox["values"] = self.config_service.list_presets()
-
-    def _refresh_list_dropdown(self) -> None:
-        """Refresh the list dropdown with current lists."""
-        self.list_combobox["values"] = self.config_service.list_lists()
-
-    def _ui_save_preset(self) -> None:
-        """Save current editor config as a new preset."""
-        name = simpledialog.askstring("Save Preset", "Enter preset name:")
-        if not name:
-            return
-        if name in self.config_service.list_presets():
-            if not messagebox.askyesno(
-                "Overwrite Preset", f"Preset '{name}' already exists. Overwrite?"
-            ):
-                return
-        editor_cfg = self.pipeline_controls_panel.get_settings()
-        try:
-            self.config_service.save_preset(name, editor_cfg, overwrite=True)
-            self._refresh_preset_dropdown()
-            messagebox.showinfo("Success", f"Preset '{name}' saved.")
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to save preset: {e}")
-
-    def _ui_delete_preset(self) -> None:
-        """Delete the selected preset."""
-        name = self.preset_combobox.get()
-        if not name:
-            messagebox.showwarning("No Selection", "Please select a preset to delete.")
-            return
-        if not messagebox.askyesno("Delete Preset", f"Delete preset '{name}'?"):
-            return
-        try:
-            self.config_service.delete_preset(name)
-            self._refresh_preset_dropdown()
-            # Clear selection
-            self.preset_combobox.set("")
-            # If it was the current preset, revert banner
-            if self.current_preset_name == name:
-                self.current_preset_name = None
-                if self.current_selected_packs:
-                    self._update_config_source_banner("Using: Pack Config (view)")
-                else:
-                    self._update_config_source_banner("Using: Pack Config")
-            messagebox.showinfo("Success", f"Preset '{name}' deleted.")
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to delete preset: {e}")
-
-    def _ui_load_list(self) -> None:
-        """Load selected list and set pack selection."""
-        name = self.list_combobox.get()
-        if not name:
-            messagebox.showwarning("No Selection", "Please select a list to load.")
-            return
-        try:
-            packs = self.config_service.load_list(name)
-            if not packs:
-                messagebox.showinfo("Empty List", f"List '{name}' has no packs saved.")
-                return
-            available = list(self.prompt_pack_panel.packs_listbox.get(0, tk.END))
-            valid_packs = [p for p in packs if p in available]
-            if not valid_packs:
-                messagebox.showwarning(
-                    "No Matching Packs",
-                    f"None of the packs from '{name}' are available in this workspace.",
-                )
-                return
-            self.prompt_pack_panel.set_selected_packs(valid_packs)
-            try:
-                self.root.update_idletasks()
-            except Exception:
-                pass
-            selected_after = self.prompt_pack_panel.get_selected_packs()
-            self.current_selected_packs = selected_after or valid_packs
-            self.ctx.active_list = name
-            messagebox.showinfo("Success", f"List '{name}' loaded ({len(valid_packs)} packs).")
-            self._reset_config_dirty_state()
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to load list: {e}")
-
-    def _ui_save_list(self) -> None:
-        """Save current pack selection as a new list."""
-        if not self.current_selected_packs:
-            messagebox.showwarning("No Selection", "Please select packs to save as list.")
-            return
-        name = simpledialog.askstring("Save List", "Enter list name:")
-        if not name:
-            return
-        if name in self.config_service.list_lists():
-            if not messagebox.askyesno(
-                "Overwrite List", f"List '{name}' already exists. Overwrite?"
-            ):
-                return
-        try:
-            self.config_service.save_list(name, self.current_selected_packs, overwrite=True)
-            self.ctx.active_list = name
-            self._refresh_list_dropdown()
-            messagebox.showinfo(
-                "Success", f"List '{name}' saved ({len(self.current_selected_packs)} packs)."
-            )
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to save list: {e}")
-
-    def _ui_overwrite_list(self) -> None:
-        """Overwrite the current active list with current selection."""
-        if not self.ctx.active_list:
-            messagebox.showwarning(
-                "No Active List", "No list is currently active. Use 'Save Selection as List' first."
-            )
-            return
-        if not self.current_selected_packs:
-            messagebox.showwarning("No Selection", "Please select packs to save.")
-            return
-        if not messagebox.askyesno(
-            "Overwrite List", f"Overwrite list '{self.ctx.active_list}' with current selection?"
-        ):
-            return
-        try:
-            self.config_service.save_list(
-                self.ctx.active_list, self.current_selected_packs, overwrite=True
-            )
-            messagebox.showinfo(
-                "Success",
-                f"List '{self.ctx.active_list}' updated ({len(self.current_selected_packs)} packs).",
-            )
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to overwrite list: {e}")
-
-    def _ui_delete_list(self) -> None:
-        """Delete the selected list."""
-        name = self.list_combobox.get()
-        if not name:
-            messagebox.showwarning("No Selection", "Please select a list to delete.")
-            return
-        if not messagebox.askyesno("Delete List", f"Delete list '{name}'?"):
-            return
-        try:
-            self.config_service.delete_list(name)
-            self._refresh_list_dropdown()
-            self.list_combobox.set("")
-            if self.ctx.active_list == name:
-                self.ctx.active_list = None
-            messagebox.showinfo("Success", f"List '{name}' deleted.")
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to delete list: {e}")
-
-    def _setup_theme(self):
-        self.style.configure(
-            "Dark.TCheckbutton",
-            background=self.bg_color,
-            foreground=self.fg_color,
-            focuscolor="none",
-            font=("Segoe UI", 9),
-        )
-        self.style.configure(
-            "Dark.TRadiobutton",
-            background=self.bg_color,
-            foreground=self.fg_color,
-            focuscolor="none",
-            font=("Segoe UI", 9),
-        )
-        self.style.configure("Dark.TNotebook", background=self.bg_color, borderwidth=0)
-        self.style.configure(
-            "Dark.TNotebook.Tab",
-            background=self.button_bg,
-            foreground=self.fg_color,
-            padding=[20, 8],
-            borderwidth=0,
-        )
-
-        # Accent button styles for CTAs
-        self.style.configure(
-            "Accent.TButton",
-            background="#0078d4",
-            foreground=self.fg_color,
-            borderwidth=1,
-            focuscolor="none",
-            font=("Segoe UI", 9, "bold"),
-        )
-        self.style.configure(
-            "Danger.TButton",
-            background="#dc3545",
-            foreground=self.fg_color,
-            borderwidth=1,
-            focuscolor="none",
-            font=("Segoe UI", 9, "bold"),
-        )
-
-        # Map states
-        self.style.map(
-            "Dark.TCombobox",
-            fieldbackground=[("readonly", self.entry_bg)],
-            selectbackground=[("readonly", "#0078d4")],
-        )
-        self.style.map(
-            "Accent.TButton",
-            background=[("active", "#106ebe"), ("pressed", "#005a9e")],
-            foreground=[("active", self.fg_color)],
-        )
-        self.style.map(
-            "Dark.TNotebook.Tab",
-            background=[("selected", "#0078d4"), ("active", self.button_active)],
-        )
-
-    def _layout_panels(self):
-        # Example layout for preset bar and dropdown
-        preset_bar = ttk.Frame(self.root, style="Dark.TFrame")
-        preset_bar.grid(row=0, column=0, sticky=tk.W)
-        ttk.Label(preset_bar, text="Preset:", style="Dark.TLabel").grid(
-            row=0, column=0, sticky=tk.W, padx=(2, 4)
-        )
-        self.preset_dropdown = ttk.Combobox(
-            preset_bar,
-            textvariable=self.preset_var,
-            state="readonly",
-            width=28,
-            values=self.config_manager.list_presets(),
-        )
-        self.preset_dropdown.grid(row=0, column=1, sticky=tk.W)
-        self.preset_dropdown.grid(row=0, column=1, sticky=tk.W)
-        self.preset_dropdown.bind(
-            "<<ComboboxSelected>>", lambda _e: self._on_preset_dropdown_changed()
-        )
-        self._attach_tooltip(
-            self.preset_dropdown,
-            "Select a preset to load its settings into the active configuration (spans all tabs).",
-        )
-
-        apply_default_btn = ttk.Button(
-            preset_bar,
-            text="Apply Default",
-            command=self._apply_default_to_selected_packs,
-            width=14,
-            style="Dark.TButton",
-        )
-        apply_default_btn.grid(row=0, column=2, padx=(8, 4))
-        self._attach_tooltip(
-            apply_default_btn,
-            "Load the 'default' preset into the form (not saved until you click Save to Pack(s)).",
-        )
-
-        # Right-aligned action strip
-        actions_strip = ttk.Frame(preset_bar, style="Dark.TFrame")
-        actions_strip.grid(row=0, column=3, sticky=tk.E, padx=(10, 4))
-
-        save_packs_btn = ttk.Button(
-            actions_strip,
-            text="Save to Pack(s)",
-            command=self._save_config_to_packs,
-            style="Accent.TButton",
-            width=18,
-        )
-        save_packs_btn.pack(side=tk.LEFT, padx=2)
-        self._attach_tooltip(
-            save_packs_btn,
-            "Persist current configuration to selected pack(s). Single selection saves that pack; multi-selection saves all.",
-        )
-
-        save_as_btn = ttk.Button(
-            actions_strip,
-            text="Save As Preset…",
-            command=self._save_preset_as,
-            width=16,
-        )
-        save_as_btn.pack(side=tk.LEFT, padx=2)
-        self._attach_tooltip(
-            save_as_btn, "Create a new preset from the current configuration state."
-        )
-
-        set_default_btn = ttk.Button(
-            actions_strip,
-            text="Set Default",
-            command=self._set_as_default_preset,
-            width=12,
-        )
-        set_default_btn.pack(side=tk.LEFT, padx=2)
-        self._attach_tooltip(set_default_btn, "Mark the selected preset as the startup default.")
-
-        del_preset_btn = ttk.Button(
-            actions_strip,
-            text="Delete",
-            command=self._delete_selected_preset,
-            style="Danger.TButton",
-            width=10,
-        )
-        del_preset_btn.pack(side=tk.LEFT, padx=2)
-        self._attach_tooltip(
-            del_preset_btn, "Delete the selected preset (cannot delete 'default')."
-        )
-
-        # Notebook sits below preset bar
-
-    def _build_randomization_tab(self, parent: tk.Widget) -> None:
-        """Build the randomization tab UI and data bindings."""
-
-        scroll_shell = ttk.Frame(parent, style="Dark.TFrame")
-        scroll_shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 10))
-        canvas, body = make_scrollable(scroll_shell, style="Dark.TFrame")
-        self._register_scrollable_section("randomization", canvas, body)
-
-        self._build_info_box(
-            body,
-            "Prompt Randomization & Aesthetic Tools",
-            "Enable randomized prompt variations using AUTOMATIC1111-style syntax. "
-            "Combine Prompt S/R rules, wildcard tokens, matrices, and optional aesthetic gradients.",
-        ).pack(fill=tk.X, padx=10, pady=(0, 6))
-
-        self.randomization_vars = {
-            "enabled": tk.BooleanVar(value=False),
-            "prompt_sr_enabled": tk.BooleanVar(value=False),
-            "prompt_sr_mode": tk.StringVar(value="random"),
-            "wildcards_enabled": tk.BooleanVar(value=False),
-            "wildcard_mode": tk.StringVar(value="random"),
-            "matrix_enabled": tk.BooleanVar(value=False),
-            "matrix_mode": tk.StringVar(value="fanout"),
-            "matrix_prompt_mode": tk.StringVar(value="replace"),
-            "matrix_limit": tk.IntVar(value=8),
-        }
-        self.randomization_widgets = {}
-
-        self.aesthetic_vars = {
-            "enabled": tk.BooleanVar(value=False),
-            "mode": tk.StringVar(value="script" if self.aesthetic_script_available else "prompt"),
-            "weight": tk.DoubleVar(value=0.9),
-            "steps": tk.IntVar(value=5),
-            "learning_rate": tk.StringVar(value="0.0001"),
-            "slerp": tk.BooleanVar(value=False),
-            "slerp_angle": tk.DoubleVar(value=0.1),
-            "text": tk.StringVar(value=""),
-            "text_is_negative": tk.BooleanVar(value=False),
-            "fallback_prompt": tk.StringVar(value=""),
-        }
-        self.aesthetic_widgets = {"all": [], "script": [], "prompt": []}
-
-        master_frame = ttk.Frame(body, style="Dark.TFrame")
-        master_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
-        ttk.Checkbutton(
-            master_frame,
-            text="Enable randomization for the next run",
-            variable=self.randomization_vars["enabled"],
-            style="Dark.TCheckbutton",
-            command=self._update_randomization_states,
-        ).pack(side=tk.LEFT)
-
-        ttk.Label(
-            master_frame,
-            text="Randomization expands prompts before the pipeline starts, so counts multiply per stage.",
-            style="Dark.TLabel",
-            wraplength=600,
-        ).pack(side=tk.LEFT, padx=(10, 0))
-
-        # Prompt S/R section
-        sr_frame = ttk.LabelFrame(body, text="Prompt S/R", style="Dark.TLabelframe", padding=10)
-        sr_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
-
-        sr_header = ttk.Frame(sr_frame, style="Dark.TFrame")
-        sr_header.pack(fill=tk.X)
-        ttk.Checkbutton(
-            sr_header,
-            text="Enable Prompt S/R replacements",
-            variable=self.randomization_vars["prompt_sr_enabled"],
-            style="Dark.TCheckbutton",
-            command=self._update_randomization_states,
-        ).pack(side=tk.LEFT)
-
-        sr_mode_frame = ttk.Frame(sr_frame, style="Dark.TFrame")
-        sr_mode_frame.pack(fill=tk.X, pady=(4, 2))
-        ttk.Label(sr_mode_frame, text="Selection mode:", style="Dark.TLabel").pack(side=tk.LEFT)
-        ttk.Radiobutton(
-            sr_mode_frame,
-            text="Random per prompt",
-            variable=self.randomization_vars["prompt_sr_mode"],
-            value="random",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-        ttk.Radiobutton(
-            sr_mode_frame,
-            text="Round robin",
-            variable=self.randomization_vars["prompt_sr_mode"],
-            value="round_robin",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-
-        ttk.Label(
-            sr_frame,
-            text="Format: search term => replacement A | replacement B. One rule per line. "
-            "Matches are case-sensitive and apply before wildcard/matrix expansion.",
-            style="Dark.TLabel",
-            wraplength=700,
-        ).pack(fill=tk.X, pady=(2, 4))
-
-        sr_text = scrolledtext.ScrolledText(sr_frame, height=6, wrap=tk.WORD)
-        sr_text.pack(fill=tk.BOTH, expand=True)
-        self.randomization_widgets["prompt_sr_text"] = sr_text
-        enable_mousewheel(sr_text)
-        # Persist on edits
-        self._bind_autosave_text(sr_text)
-
-        # Wildcards section
-        wildcard_frame = ttk.LabelFrame(
-            body, text="Wildcards (__token__ syntax)", style="Dark.TFrame", padding=10
-        )
-        wildcard_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
-
-        wildcard_header = ttk.Frame(wildcard_frame, style="Dark.TFrame")
-        wildcard_header.pack(fill=tk.X)
-        ttk.Checkbutton(
-            wildcard_header,
-            text="Enable wildcard replacements",
-            variable=self.randomization_vars["wildcards_enabled"],
-            style="Dark.TCheckbutton",
-            command=self._update_randomization_states,
-        ).pack(side=tk.LEFT)
-
-        ttk.Label(
-            wildcard_frame,
-            text="Use __token__ in your prompts (same as AUTOMATIC1111 wildcards). "
-            "Provide values below using token: option1 | option2.",
-            style="Dark.TLabel",
-            wraplength=700,
-        ).pack(fill=tk.X, pady=(4, 4))
-
-        wildcard_mode_frame = ttk.Frame(wildcard_frame, style="Dark.TFrame")
-        wildcard_mode_frame.pack(fill=tk.X, pady=(0, 4))
-        ttk.Label(wildcard_mode_frame, text="Selection mode:", style="Dark.TLabel").pack(
-            side=tk.LEFT
-        )
-        ttk.Radiobutton(
-            wildcard_mode_frame,
-            text="Random per prompt",
-            variable=self.randomization_vars["wildcard_mode"],
-            value="random",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-        ttk.Radiobutton(
-            wildcard_mode_frame,
-            text="Sequential (loop through values)",
-            variable=self.randomization_vars["wildcard_mode"],
-            value="sequential",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-
-        wildcard_text = scrolledtext.ScrolledText(wildcard_frame, height=6, wrap=tk.WORD)
-        wildcard_text.pack(fill=tk.BOTH, expand=True)
-        self.randomization_widgets["wildcard_text"] = wildcard_text
-        enable_mousewheel(wildcard_text)
-        self._bind_autosave_text(wildcard_text)
-
-        # Prompt matrix section
-        matrix_frame = ttk.LabelFrame(
-            body, text="Prompt Matrix ([[Slot]] syntax)", style="Dark.TFrame", padding=10
-        )
-        matrix_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
-
-        matrix_header = ttk.Frame(matrix_frame, style="Dark.TFrame")
-        matrix_header.pack(fill=tk.X)
-        ttk.Checkbutton(
-            matrix_header,
-            text="Enable prompt matrix expansion",
-            variable=self.randomization_vars["matrix_enabled"],
-            style="Dark.TCheckbutton",
-            command=self._update_randomization_states,
-        ).pack(side=tk.LEFT)
-
-        matrix_mode_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
-        matrix_mode_frame.pack(fill=tk.X, pady=(4, 2))
-        ttk.Label(matrix_mode_frame, text="Expansion mode:", style="Dark.TLabel").pack(side=tk.LEFT)
-        ttk.Radiobutton(
-            matrix_mode_frame,
-            text="Fan-out (all combos)",
-            variable=self.randomization_vars["matrix_mode"],
-            value="fanout",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-        ttk.Radiobutton(
-            matrix_mode_frame,
-            text="Rotate per prompt",
-            variable=self.randomization_vars["matrix_mode"],
-            value="rotate",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-
-        # Prompt mode: how base_prompt relates to pack prompt
-        prompt_mode_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
-        prompt_mode_frame.pack(fill=tk.X, pady=(2, 2))
-        ttk.Label(prompt_mode_frame, text="Prompt mode:", style="Dark.TLabel").pack(side=tk.LEFT)
-        ttk.Radiobutton(
-            prompt_mode_frame,
-            text="Replace pack",
-            variable=self.randomization_vars["matrix_prompt_mode"],
-            value="replace",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-        ttk.Radiobutton(
-            prompt_mode_frame,
-            text="Append to pack",
-            variable=self.randomization_vars["matrix_prompt_mode"],
-            value="append",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-        ttk.Radiobutton(
-            prompt_mode_frame,
-            text="Prepend before pack",
-            variable=self.randomization_vars["matrix_prompt_mode"],
-            value="prepend",
-            style="Dark.TRadiobutton",
-        ).pack(side=tk.LEFT, padx=(8, 0))
-
-        limit_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
-        limit_frame.pack(fill=tk.X, pady=(2, 4))
-        ttk.Label(limit_frame, text="Combination cap:", style="Dark.TLabel").pack(side=tk.LEFT)
-        ttk.Spinbox(
-            limit_frame,
-            from_=1,
-            to=64,
-            width=5,
-            textvariable=self.randomization_vars["matrix_limit"],
-        ).pack(side=tk.LEFT, padx=(4, 0))
-        ttk.Label(
-            limit_frame,
-            text="(prevents runaway combinations when many slots are defined)",
-            style="Dark.TLabel",
-        ).pack(side=tk.LEFT, padx=(6, 0))
-
-        # Base prompt field
-        base_prompt_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
-        base_prompt_frame.pack(fill=tk.X, pady=(4, 2))
-        ttk.Label(
-            base_prompt_frame,
-            text="Base prompt:",
-            style="Dark.TLabel",
-            width=14,
-        ).pack(side=tk.LEFT)
-        base_prompt_entry = ttk.Entry(base_prompt_frame)
-        base_prompt_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
-        self.randomization_widgets["matrix_base_prompt"] = base_prompt_entry
-        self._bind_autosave_entry(base_prompt_entry)
-
-        ttk.Label(
-            matrix_frame,
-            text="Add [[Slot Name]] markers in your base prompt. Define combination slots below:",
-            style="Dark.TLabel",
-            wraplength=700,
-        ).pack(fill=tk.X, pady=(2, 4))
-
-        # Scrollable container for slot rows
-        slots_container = ttk.Frame(matrix_frame, style="Dark.TFrame")
-        slots_container.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
-
-        slots_canvas = tk.Canvas(
-            slots_container,
-            bg="#2b2b2b",
-            highlightthickness=0,
-            height=150,
-        )
-        slots_scrollbar = ttk.Scrollbar(
-            slots_container,
-            orient=tk.VERTICAL,
-            command=slots_canvas.yview,
-        )
-        slots_scrollable_frame = ttk.Frame(slots_canvas, style="Dark.TFrame")
-
-        slots_scrollable_frame.bind(
-            "<Configure>",
-            lambda e: slots_canvas.configure(scrollregion=slots_canvas.bbox("all")),
-        )
-
-        slots_canvas.create_window((0, 0), window=slots_scrollable_frame, anchor="nw")
-        slots_canvas.configure(yscrollcommand=slots_scrollbar.set)
-
-        slots_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
-        slots_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
-
-        self.randomization_widgets["matrix_slots_frame"] = slots_scrollable_frame
-        self.randomization_widgets["matrix_slots_canvas"] = slots_canvas
-        self.randomization_widgets["matrix_slot_rows"] = []
-
-        # Add slot button
-        add_slot_btn = ttk.Button(
-            matrix_frame,
-            text="+ Add Combination Slot",
-            command=self._add_matrix_slot_row,
-        )
-        add_slot_btn.pack(fill=tk.X, pady=(0, 4))
-
-        # Legacy text view (hidden by default, for advanced users)
-        legacy_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
-        legacy_frame.pack(fill=tk.BOTH, expand=True)
-
-        self.randomization_vars["matrix_show_legacy"] = tk.BooleanVar(value=False)
-        ttk.Checkbutton(
-            legacy_frame,
-            text="Show advanced text editor (legacy format)",
-            variable=self.randomization_vars["matrix_show_legacy"],
-            style="Dark.TCheckbutton",
-            command=self._toggle_matrix_legacy_view,
-        ).pack(fill=tk.X, pady=(0, 2))
-
-        legacy_text_container = ttk.Frame(legacy_frame, style="Dark.TFrame")
-        self.randomization_widgets["matrix_legacy_container"] = legacy_text_container
-
-        matrix_text = scrolledtext.ScrolledText(
-            legacy_text_container,
-            height=6,
-            wrap=tk.WORD,
-        )
-        matrix_text.pack(fill=tk.BOTH, expand=True)
-        self.randomization_widgets["matrix_text"] = matrix_text
-        enable_mousewheel(matrix_text)
-        self._bind_autosave_text(matrix_text)
-
-        # Aesthetic gradient section
-        aesthetic_frame = ttk.LabelFrame(
-            body, text="Aesthetic Gradient", style="Dark.TLabelframe", padding=10
-        )
-        aesthetic_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
-
-        aesthetic_header = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
-        aesthetic_header.pack(fill=tk.X)
-        ttk.Checkbutton(
-            aesthetic_header,
-            text="Enable aesthetic gradient adjustments",
-            variable=self.aesthetic_vars["enabled"],
-            style="Dark.TCheckbutton",
-            command=self._update_aesthetic_states,
-        ).pack(side=tk.LEFT)
-
-        ttk.Label(
-            aesthetic_header,
-            textvariable=self.aesthetic_status_var,
-            style="Dark.TLabel",
-            wraplength=400,
-        ).pack(side=tk.LEFT, padx=(12, 0))
-
-        mode_frame = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
-        mode_frame.pack(fill=tk.X, pady=(6, 4))
-        ttk.Label(mode_frame, text="Mode:", style="Dark.TLabel").pack(side=tk.LEFT)
-        script_radio = ttk.Radiobutton(
-            mode_frame,
-            text="Use Aesthetic Gradient script",
-            variable=self.aesthetic_vars["mode"],
-            value="script",
-            style="Dark.TRadiobutton",
-            state=tk.NORMAL if self.aesthetic_script_available else tk.DISABLED,
-            command=self._update_aesthetic_states,
-        )
-        script_radio.pack(side=tk.LEFT, padx=(6, 0))
-        prompt_radio = ttk.Radiobutton(
-            mode_frame,
-            text="Fallback prompt / embedding",
-            variable=self.aesthetic_vars["mode"],
-            value="prompt",
-            style="Dark.TRadiobutton",
-            command=self._update_aesthetic_states,
-        )
-        prompt_radio.pack(side=tk.LEFT, padx=(6, 0))
-        self.aesthetic_widgets["all"].extend([script_radio, prompt_radio])
-
-        embedding_row = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
-        embedding_row.pack(fill=tk.X, pady=(2, 4))
-        ttk.Label(embedding_row, text="Embedding:", style="Dark.TLabel", width=14).pack(
-            side=tk.LEFT
-        )
-        self.aesthetic_embedding_combo = ttk.Combobox(
-            embedding_row,
-            textvariable=self.aesthetic_embedding_var,
-            state="readonly",
-            width=24,
-            values=self.aesthetic_embeddings,
-        )
-        self.aesthetic_embedding_combo.pack(side=tk.LEFT, padx=(4, 0))
-        refresh_btn = ttk.Button(
-            embedding_row, text="Refresh", command=self._refresh_aesthetic_embeddings, width=8
-        )
-        refresh_btn.pack(side=tk.LEFT, padx=(6, 0))
-        self.aesthetic_widgets["all"].extend([self.aesthetic_embedding_combo, refresh_btn])
-
-        script_box = ttk.LabelFrame(
-            aesthetic_frame, text="Script Parameters", style="Dark.TLabelframe", padding=6
-        )
-        script_box.pack(fill=tk.X, pady=(4, 4))
-
-        weight_row = ttk.Frame(script_box, style="Dark.TFrame")
-        weight_row.pack(fill=tk.X, pady=2)
-        ttk.Label(weight_row, text="Weight:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
-        weight_slider = EnhancedSlider(
-            weight_row,
-            from_=0.0,
-            to=1.0,
-            resolution=0.01,
-            variable=self.aesthetic_vars["weight"],
-            width=140,
-        )
-        weight_slider.pack(side=tk.LEFT, padx=(4, 10))
-
-        steps_row = ttk.Frame(script_box, style="Dark.TFrame")
-        steps_row.pack(fill=tk.X, pady=2)
-        ttk.Label(steps_row, text="Steps:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
-        steps_slider = EnhancedSlider(
-            steps_row,
-            from_=0,
-            to=50,
-            resolution=1,
-            variable=self.aesthetic_vars["steps"],
-            width=140,
-        )
-        steps_slider.pack(side=tk.LEFT, padx=(4, 10))
-
-        lr_row = ttk.Frame(script_box, style="Dark.TFrame")
-        lr_row.pack(fill=tk.X, pady=2)
-        ttk.Label(lr_row, text="Learning rate:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
-        lr_entry = ttk.Entry(lr_row, textvariable=self.aesthetic_vars["learning_rate"], width=12)
-        lr_entry.pack(side=tk.LEFT, padx=(4, 10))
-
-        slerp_row = ttk.Frame(script_box, style="Dark.TFrame")
-        slerp_row.pack(fill=tk.X, pady=2)
-        slerp_check = ttk.Checkbutton(
-            slerp_row,
-            text="Enable slerp interpolation",
-            variable=self.aesthetic_vars["slerp"],
-            style="Dark.TCheckbutton",
-            command=self._update_aesthetic_states,
-        )
-        slerp_check.pack(side=tk.LEFT)
-        ttk.Label(slerp_row, text="Angle:", style="Dark.TLabel", width=8).pack(
-            side=tk.LEFT, padx=(10, 0)
-        )
-        slerp_angle_slider = EnhancedSlider(
-            slerp_row,
-            from_=0.0,
-            to=1.0,
-            resolution=0.01,
-            variable=self.aesthetic_vars["slerp_angle"],
-            width=120,
-        )
-        slerp_angle_slider.pack(side=tk.LEFT, padx=(4, 0))
-
-        text_row = ttk.Frame(script_box, style="Dark.TFrame")
-        text_row.pack(fill=tk.X, pady=2)
-        ttk.Label(text_row, text="Text prompt:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
-        text_entry = ttk.Entry(text_row, textvariable=self.aesthetic_vars["text"])
-        text_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
-        text_neg_check = ttk.Checkbutton(
-            text_row,
-            text="Apply as negative text",
-            variable=self.aesthetic_vars["text_is_negative"],
-            style="Dark.TCheckbutton",
-        )
-        text_neg_check.pack(side=tk.LEFT, padx=(6, 0))
-
-        self.aesthetic_widgets["script"].extend(
-            [
-                weight_slider,
-                steps_slider,
-                lr_entry,
-                slerp_check,
-                slerp_angle_slider,
-                text_entry,
-                text_neg_check,
-            ]
-        )
-
-        prompt_box = ttk.LabelFrame(
-            aesthetic_frame, text="Fallback Prompt Injection", style="Dark.TLabelframe", padding=6
-        )
-        prompt_box.pack(fill=tk.X, pady=(4, 0))
-
-        ttk.Label(
-            prompt_box,
-            text="Optional phrase appended to the positive prompt when using fallback mode.",
-            style="Dark.TLabel",
-            wraplength=700,
-        ).pack(fill=tk.X, pady=(0, 4))
-        fallback_entry = ttk.Entry(prompt_box, textvariable=self.aesthetic_vars["fallback_prompt"])
-        fallback_entry.pack(fill=tk.X, padx=2)
-
-        self.aesthetic_widgets["prompt"].append(fallback_entry)
-        self.aesthetic_widgets["all"].append(fallback_entry)
-        self.aesthetic_widgets["all"].extend(
-            [
-                weight_slider,
-                steps_slider,
-                lr_entry,
-                slerp_check,
-                slerp_angle_slider,
-                text_entry,
-                text_neg_check,
-            ]
-        )
-
-        for key in ("enabled", "prompt_sr_enabled", "wildcards_enabled", "matrix_enabled"):
-            try:
-
-                def _rand_trace_cb(*_args, _k=key):
-                    self._update_randomization_states()
-                    if _k.endswith("enabled"):
-                        self._autosave_preferences_if_needed()
-
-                self.randomization_vars[key].trace_add("write", _rand_trace_cb)
-            except Exception:
-                pass
-        # Persist changes to modes/limits too
-        for key in (
-            "prompt_sr_mode",
-            "wildcard_mode",
-            "matrix_mode",
-            "matrix_prompt_mode",
-            "matrix_limit",
-        ):
-            try:
-                self.randomization_vars[key].trace_add(
-                    "write", lambda *_: self._autosave_preferences_if_needed()
-                )
-            except Exception:
-                pass
-
-        try:
-            self.aesthetic_vars["enabled"].trace_add(
-                "write", lambda *_: self._aesthetic_autosave_handler()
-            )
-            self.aesthetic_vars["mode"].trace_add(
-                "write", lambda *_: self._aesthetic_autosave_handler()
-            )
-            self.aesthetic_vars["slerp"].trace_add(
-                "write", lambda *_: self._aesthetic_autosave_handler()
-            )
-            # Also persist other aesthetic fields on change
-            for _k, _var in self.aesthetic_vars.items():
-                try:
-                    _var.trace_add("write", lambda *_: self._autosave_preferences_if_needed())
-                except Exception:
-                    pass
-        except Exception:
-            pass
-
-        self._update_randomization_states()
-        self._refresh_aesthetic_embeddings()
-        self._update_aesthetic_states()
-
-    def _update_randomization_states(self) -> None:
-        """Enable/disable randomization widgets based on current toggles."""
-
-        vars_dict = getattr(self, "randomization_vars", None)
-        widgets = getattr(self, "randomization_widgets", None)
-        if not vars_dict or not widgets:
-            return
-
-        master = bool(vars_dict.get("enabled", tk.BooleanVar(value=False)).get())
-        section_enabled = {
-            "prompt_sr_text": master
-            and bool(vars_dict.get("prompt_sr_enabled", tk.BooleanVar()).get()),
-            "wildcard_text": master
-            and bool(vars_dict.get("wildcards_enabled", tk.BooleanVar()).get()),
-            "matrix_text": master and bool(vars_dict.get("matrix_enabled", tk.BooleanVar()).get()),
-        }
-
-        for key, widget in widgets.items():
-            if widget is None or isinstance(widget, list):
-                continue
-            state = tk.NORMAL if section_enabled.get(key, master) else tk.DISABLED
-            try:
-                widget.configure(state=state)
-            except (tk.TclError, AttributeError):
-                pass
-        # Throttled autosave to keep last_settings.json aligned with UI
-        self._autosave_preferences_if_needed()
-
-    def _autosave_preferences_if_needed(self, force: bool = False) -> None:
-        """Autosave preferences (including randomization enabled flag) with 2s throttle."""
-        if not getattr(self, "_preferences_ready", False) and not force:
-            return
-        now = time.time()
-        last = getattr(self, "_last_pref_autosave", 0.0)
-        if not force and now - last < 2.0:
-            return
-        self._last_pref_autosave = now
-        try:
-            prefs = self._collect_preferences()
-            if self.preferences_manager.save_preferences(prefs):
-                self.preferences = prefs
-        except Exception:
-            pass
-
-    def _bind_autosave_text(self, widget: tk.Text) -> None:
-        """Bind common events on a Text widget to autosave preferences (throttled)."""
-        try:
-            widget.bind("<KeyRelease>", lambda _e: self._autosave_preferences_if_needed())
-            widget.bind("<FocusOut>", lambda _e: self._autosave_preferences_if_needed())
-        except Exception:
-            pass
-
-    def _bind_autosave_entry(self, widget: tk.Entry) -> None:
-        """Bind common events on an Entry widget to autosave preferences (throttled)."""
-        try:
-            widget.bind("<KeyRelease>", lambda _e: self._autosave_preferences_if_needed())
-            widget.bind("<FocusOut>", lambda _e: self._autosave_preferences_if_needed())
-        except Exception:
-            pass
-
-    def _aesthetic_autosave_handler(self) -> None:
-        """Handler for aesthetic state changes that also triggers autosave."""
-        self._update_aesthetic_states()
-        self._autosave_preferences_if_needed()
-
-    def _get_randomization_text(self, key: str) -> str:
-        """Return trimmed contents of a randomization text widget."""
-
-        widget = self.randomization_widgets.get(key)
-        if widget is None:
-            return ""
-        try:
-            current_state = widget["state"]
-        except (tk.TclError, KeyError):
-            current_state = tk.NORMAL
-
-        try:
-            if current_state == tk.DISABLED:
-                widget.configure(state=tk.NORMAL)
-                value = widget.get("1.0", tk.END)
-                widget.configure(state=tk.DISABLED)
-            else:
-                value = widget.get("1.0", tk.END)
-        except tk.TclError:
-            value = ""
-        return value.strip()
-
-    def _set_randomization_text(self, key: str, value: str) -> None:
-        """Populate a randomization text widget with new content."""
-
-        widget = self.randomization_widgets.get(key)
-        if widget is None:
-            return
-        try:
-            current_state = widget["state"]
-        except (tk.TclError, KeyError):
-            current_state = tk.NORMAL
-
-        try:
-            widget.configure(state=tk.NORMAL)
-            widget.delete("1.0", tk.END)
-            if value:
-                widget.insert(tk.END, value)
-        except tk.TclError:
-            pass
-        finally:
-            try:
-                widget.configure(state=current_state)
-            except tk.TclError:
-                pass
-
-    def _update_aesthetic_states(self) -> None:
-        """Enable/disable aesthetic widgets based on mode and availability."""
-
-        vars_dict = getattr(self, "aesthetic_vars", None)
-        widgets = getattr(self, "aesthetic_widgets", None)
-        if not vars_dict or not widgets:
-            return
-
-        enabled = bool(vars_dict.get("enabled", tk.BooleanVar(value=False)).get())
-        mode = vars_dict.get("mode", tk.StringVar(value="prompt")).get()
-        if mode == "script" and not self.aesthetic_script_available:
-            mode = "prompt"
-            vars_dict["mode"].set("prompt")
-
-        def set_state(target_widgets: list[tk.Widget], active: bool) -> None:
-            for widget in target_widgets:
-                if widget is None:
-                    continue
-                state = tk.NORMAL if active else tk.DISABLED
-                try:
-                    widget.configure(state=state)
-                except (tk.TclError, AttributeError):
-                    if hasattr(widget, "configure_state"):
-                        try:
-                            widget.configure_state("normal" if active else "disabled")
-                        except Exception:
-                            continue
-
-        set_state(widgets.get("all", []), enabled)
-        set_state(widgets.get("script", []), enabled and mode == "script")
-        set_state(widgets.get("prompt", []), enabled and mode == "prompt")
-
-        if self.aesthetic_script_available:
-            status = "Aesthetic extension detected"
-        else:
-            status = "Extension not detected – fallback mode only"
-        if len(self.aesthetic_embeddings) <= 1:
-            status += " (no embeddings found)"
-        self.aesthetic_status_var.set(status)
-
-    def _detect_aesthetic_extension_root(self):
-        """Locate the Aesthetic Gradient extension directory if present."""
-
-        candidates: list[Path] = []
-        env_root = os.environ.get("WEBUI_ROOT")
-        if env_root:
-            candidates.append(Path(env_root))
-        candidates.append(Path.home() / "stable-diffusion-webui")
-        repo_candidate = Path(__file__).resolve().parents[3] / "stable-diffusion-webui"
-        candidates.append(repo_candidate)
-        local_candidate = Path("..") / "stable-diffusion-webui"
-        candidates.append(local_candidate.resolve())
-
-        detected, extension_dir = detect_aesthetic_extension(candidates)
-        if detected and extension_dir:
-            return True, extension_dir
-        return False, None
-
-    def _refresh_aesthetic_embeddings(self, *_):
-        """Reload available aesthetic embedding names from disk."""
-
-        embeddings = ["None"]
-        if self.aesthetic_extension_root:
-            embed_dir = self.aesthetic_extension_root / "aesthetic_embeddings"
-            if embed_dir.exists():
-                for file in sorted(embed_dir.glob("*.pt")):
-                    embeddings.append(file.stem)
-        self.aesthetic_embeddings = sorted(
-            dict.fromkeys(embeddings), key=lambda name: (name != "None", name.lower())
-        )
-
-        if self.aesthetic_embedding_var.get() not in self.aesthetic_embeddings:
-            self.aesthetic_embedding_var.set("None")
-
-        if hasattr(self, "aesthetic_embedding_combo"):
-            try:
-                self.aesthetic_embedding_combo["values"] = self.aesthetic_embeddings
-            except Exception:
-                pass
-
-        if self.aesthetic_script_available:
-            status = "Aesthetic extension detected"
-        else:
-            status = "Extension not detected – fallback mode only"
-        if len(self.aesthetic_embeddings) <= 1:
-            status += " (no embeddings found)"
-        self.aesthetic_status_var.set(status)
-
-    def _collect_randomization_config(self) -> dict[str, Any]:
-        """Collect randomization settings into a serializable dict."""
-
-        vars_dict = getattr(self, "randomization_vars", None)
-        if not vars_dict:
-            return {}
-
-        sr_text = self._get_randomization_text("prompt_sr_text")
-        wildcard_text = self._get_randomization_text("wildcard_text")
-
-        # Collect matrix data from UI fields (not legacy text)
-        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
-        base_prompt = base_prompt_widget.get() if base_prompt_widget else ""
-
-        matrix_slots = []
-        for row in self.randomization_widgets.get("matrix_slot_rows", []):
-            name = row["name_entry"].get().strip()
-            values_text = row["values_entry"].get().strip()
-            if name and values_text:
-                values = [v.strip() for v in values_text.split("|") if v.strip()]
-                if values:
-                    matrix_slots.append({"name": name, "values": values})
-
-        # Build raw_text for backward compatibility
-        matrix_raw_lines = []
-        if base_prompt:
-            matrix_raw_lines.append(f"# Base: {base_prompt}")
-        matrix_raw_lines.append(self._format_matrix_lines(matrix_slots))
-        matrix_raw_text = "\n".join(matrix_raw_lines)
-
-        return {
-            "enabled": bool(vars_dict["enabled"].get()),
-            "prompt_sr": {
-                "enabled": bool(vars_dict["prompt_sr_enabled"].get()),
-                "mode": vars_dict["prompt_sr_mode"].get(),
-                "rules": self._parse_prompt_sr_rules(sr_text),
-                "raw_text": sr_text,
-            },
-            "wildcards": {
-                "enabled": bool(vars_dict["wildcards_enabled"].get()),
-                "mode": vars_dict["wildcard_mode"].get(),
-                "tokens": self._parse_token_lines(wildcard_text),
-                "raw_text": wildcard_text,
-            },
-            "matrix": {
-                "enabled": bool(vars_dict["matrix_enabled"].get()),
-                "mode": vars_dict["matrix_mode"].get(),
-                "prompt_mode": vars_dict["matrix_prompt_mode"].get(),
-                "limit": int(vars_dict["matrix_limit"].get() or 0),
-                "slots": matrix_slots,
-                "raw_text": matrix_raw_text,
-                "base_prompt": base_prompt,
-            },
-        }
-
-    def _load_randomization_config(self, config: dict[str, Any]) -> None:
-        """Populate randomization UI from configuration values."""
-
-        vars_dict = getattr(self, "randomization_vars", None)
-        if not vars_dict:
-            return
-
-        try:
-            data = (config or {}).get("randomization", {})
-            vars_dict["enabled"].set(bool(data.get("enabled", False)))
-
-            sr = data.get("prompt_sr", {})
-            vars_dict["prompt_sr_enabled"].set(bool(sr.get("enabled", False)))
-            vars_dict["prompt_sr_mode"].set(sr.get("mode", "random"))
-            sr_text = sr.get("raw_text") or self._format_prompt_sr_rules(sr.get("rules", []))
-            self._set_randomization_text("prompt_sr_text", sr_text)
-
-            wildcards = data.get("wildcards", {})
-            vars_dict["wildcards_enabled"].set(bool(wildcards.get("enabled", False)))
-            vars_dict["wildcard_mode"].set(wildcards.get("mode", "random"))
-            wildcard_text = wildcards.get("raw_text") or self._format_token_lines(
-                wildcards.get("tokens", [])
-            )
-            self._set_randomization_text("wildcard_text", wildcard_text)
-
-            matrix = data.get("matrix", {})
-            vars_dict["matrix_enabled"].set(bool(matrix.get("enabled", False)))
-            vars_dict["matrix_mode"].set(matrix.get("mode", "fanout"))
-            vars_dict["matrix_prompt_mode"].set(matrix.get("prompt_mode", "replace"))
-            vars_dict["matrix_limit"].set(int(matrix.get("limit", 8)))
-
-            base_prompt = matrix.get("base_prompt", "")
-            base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
-            if base_prompt_widget:
-                base_prompt_widget.delete(0, tk.END)
-                base_prompt_widget.insert(0, base_prompt)
-
-            slots = matrix.get("slots", [])
-            self._clear_matrix_slot_rows()
-            for slot in slots:
-                name = slot.get("name", "")
-                values = slot.get("values", [])
-                if name and values:
-                    values_str = " | ".join(values)
-                    self._add_matrix_slot_row(name, values_str)
-
-            matrix_text = matrix.get("raw_text") or self._format_matrix_lines(slots)
-            self._set_randomization_text("matrix_text", matrix_text)
-
-            self._update_randomization_states()
-        except Exception as exc:
-            logger.error("Failed to load randomization config: %s", exc)
-
-    def _collect_aesthetic_config(self) -> dict[str, Any]:
-        """Collect aesthetic gradient settings."""
-
-        vars_dict = getattr(self, "aesthetic_vars", None)
-        if not vars_dict:
-            return {}
-
-        mode = vars_dict["mode"].get()
-        if mode == "script" and not self.aesthetic_script_available:
-            mode = "prompt"
-
-        def _safe_float(value: Any, default: float) -> float:
-            try:
-                return float(value)
-            except (TypeError, ValueError):
-                return default
-
-        config = {
-            "enabled": bool(vars_dict["enabled"].get()),
-            "mode": mode,
-            "weight": _safe_float(vars_dict["weight"].get(), 0.9),
-            "steps": int(vars_dict["steps"].get() or 0),
-            "learning_rate": _safe_float(vars_dict["learning_rate"].get(), 0.0001),
-            "slerp": bool(vars_dict["slerp"].get()),
-            "slerp_angle": _safe_float(vars_dict["slerp_angle"].get(), 0.1),
-            "embedding": self.aesthetic_embedding_var.get() or "None",
-            "text": vars_dict["text"].get().strip(),
-            "text_is_negative": bool(vars_dict["text_is_negative"].get()),
-            "fallback_prompt": vars_dict["fallback_prompt"].get().strip(),
-        }
-        return config
-
-    def _load_aesthetic_config(self, config: dict[str, Any]) -> None:
-        """Populate aesthetic gradient UI from stored configuration."""
-
-        vars_dict = getattr(self, "aesthetic_vars", None)
-        if not vars_dict:
-            return
-
-        data = (config or {}).get("aesthetic", {})
-        vars_dict["enabled"].set(bool(data.get("enabled", False)))
-        desired_mode = data.get("mode", "script")
-        if desired_mode == "script" and not self.aesthetic_script_available:
-            desired_mode = "prompt"
-        vars_dict["mode"].set(desired_mode)
-        vars_dict["weight"].set(float(data.get("weight", 0.9)))
-        vars_dict["steps"].set(int(data.get("steps", 5)))
-        vars_dict["learning_rate"].set(str(data.get("learning_rate", 0.0001)))
-        vars_dict["slerp"].set(bool(data.get("slerp", False)))
-        vars_dict["slerp_angle"].set(float(data.get("slerp_angle", 0.1)))
-        vars_dict["text"].set(data.get("text", ""))
-        vars_dict["text_is_negative"].set(bool(data.get("text_is_negative", False)))
-        vars_dict["fallback_prompt"].set(data.get("fallback_prompt", ""))
-
-        embedding = data.get("embedding", "None") or "None"
-        if embedding not in self.aesthetic_embeddings:
-            embedding = "None"
-        self.aesthetic_embedding_var.set(embedding)
-        self._update_aesthetic_states()
-
-    @staticmethod
-    def _parse_prompt_sr_rules(text: str) -> list[dict[str, Any]]:
-        """Parse Prompt S/R rule definitions."""
-
-        rules: list[dict[str, Any]] = []
-        for raw_line in text.splitlines():
-            line = raw_line.strip()
-            if not line or line.startswith("#") or "=>" not in line:
-                continue
-            search, replacements = line.split("=>", 1)
-            search = search.strip()
-            replacement_values = [item.strip() for item in replacements.split("|") if item.strip()]
-            if search and replacement_values:
-                rules.append({"search": search, "replacements": replacement_values})
-        return rules
-
-    @staticmethod
-    def _format_prompt_sr_rules(rules: list[dict[str, Any]]) -> str:
-        """Format Prompt S/R rules back into editable text."""
-
-        lines: list[str] = []
-        for entry in rules or []:
-            search = entry.get("search", "")
-            replacements = entry.get("replacements", [])
-            if not search or not replacements:
-                continue
-            lines.append(f"{search} => {' | '.join(replacements)}")
-        return "\n".join(lines)
-
-    @staticmethod
-    def _parse_token_lines(text: str) -> list[dict[str, Any]]:
-        """Parse wildcard token definitions."""
-
-        tokens: list[dict[str, Any]] = []
-        for raw_line in text.splitlines():
-            line = raw_line.strip()
-            if not line or line.startswith("#") or ":" not in line:
-                continue
-            token, values = line.split(":", 1)
-            base_name = token.strip().strip("_")
-            value_list = [item.strip() for item in values.split("|") if item.strip()]
-            if base_name and value_list:
-                tokens.append({"token": f"__{base_name}__", "values": value_list})
-        return tokens
-
-    @staticmethod
-    def _format_token_lines(tokens: list[dict[str, Any]]) -> str:
-        """Format wildcard tokens back into editable text."""
-
-        lines: list[str] = []
-        for token in tokens or []:
-            name = token.get("token", "")
-            values = token.get("values", [])
-            if not name or not values:
-                continue
-            stripped_name = (
-                name.strip("_") if name.startswith("__") and name.endswith("__") else name
-            )
-            lines.append(f"{stripped_name}: {' | '.join(values)}")
-        return "\n".join(lines)
-
-    @staticmethod
-    def _parse_matrix_lines(text: str) -> list[dict[str, Any]]:
-        """Parse matrix slot definitions."""
-
-        slots: list[dict[str, Any]] = []
-        for raw_line in text.splitlines():
-            line = raw_line.strip()
-            if not line or line.startswith("#") or ":" not in line:
-                continue
-            slot, values = line.split(":", 1)
-            slot_name = slot.strip()
-            value_list = [item.strip() for item in values.split("|") if item.strip()]
-            if slot_name and value_list:
-                slots.append({"name": slot_name, "values": value_list})
-        return slots
-
-    @staticmethod
-    def _format_matrix_lines(slots: list[dict[str, Any]]) -> str:
-        """Format matrix slots back into editable text."""
-
-        lines: list[str] = []
-        for slot in slots or []:
-            name = slot.get("name", "")
-            values = slot.get("values", [])
-            if not name or not values:
-                continue
-            lines.append(f"{name}: {' | '.join(values)}")
-        return "\n".join(lines)
-
-    def _add_matrix_slot_row(self, slot_name: str = "", slot_values: str = "") -> None:
-        """Add a new matrix slot row to the UI."""
-
-        slots_frame = self.randomization_widgets.get("matrix_slots_frame")
-        if not slots_frame:
-            return
-
-        row_frame = ttk.Frame(slots_frame, style="Dark.TFrame")
-        row_frame.pack(fill=tk.X, pady=2)
-
-        # Slot name entry
-        ttk.Label(row_frame, text="Slot:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)
-        name_entry = ttk.Entry(row_frame, width=15)
-        name_entry.pack(side=tk.LEFT, padx=(2, 4))
-        if slot_name:
-            name_entry.insert(0, slot_name)
-        # Autosave when editing slot name
-        self._bind_autosave_entry(name_entry)
-
-        # Values entry
-        ttk.Label(row_frame, text="Options (| separated):", style="Dark.TLabel").pack(
-            side=tk.LEFT, padx=(4, 2)
-        )
-        values_entry = ttk.Entry(row_frame)
-        values_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 4))
-        if slot_values:
-            values_entry.insert(0, slot_values)
-        # Autosave when editing slot values
-        self._bind_autosave_entry(values_entry)
-
-        # Remove button
-        remove_btn = ttk.Button(
-            row_frame,
-            text="−",
-            width=3,
-            command=lambda: self._remove_matrix_slot_row(row_frame),
-        )
-        remove_btn.pack(side=tk.LEFT)
-
-        # Store row data
-        row_data = {
-            "frame": row_frame,
-            "name_entry": name_entry,
-            "values_entry": values_entry,
-        }
-        self.randomization_widgets["matrix_slot_rows"].append(row_data)
-
-        # Update scroll region
-        canvas = self.randomization_widgets.get("matrix_slots_canvas")
-        if canvas:
-            canvas.configure(scrollregion=canvas.bbox("all"))
-
-    def _remove_matrix_slot_row(self, row_frame: tk.Widget) -> None:
-        """Remove a matrix slot row from the UI."""
-
-        slot_rows = self.randomization_widgets.get("matrix_slot_rows", [])
-        self.randomization_widgets["matrix_slot_rows"] = [
-            row for row in slot_rows if row["frame"] != row_frame
-        ]
-        row_frame.destroy()
-
-        # Update scroll region
-        canvas = self.randomization_widgets.get("matrix_slots_canvas")
-        if canvas:
-            canvas.configure(scrollregion=canvas.bbox("all"))
-
-    def _clear_matrix_slot_rows(self) -> None:
-        """Clear all matrix slot rows from the UI."""
-
-        for row in self.randomization_widgets.get("matrix_slot_rows", []):
-            row["frame"].destroy()
-        self.randomization_widgets["matrix_slot_rows"] = []
-
-        # Update scroll region
-        canvas = self.randomization_widgets.get("matrix_slots_canvas")
-        if canvas:
-            canvas.configure(scrollregion=canvas.bbox("all"))
-
-    def _toggle_matrix_legacy_view(self) -> None:
-        """Toggle between modern UI and legacy text editor for matrix config."""
-
-        show_legacy = self.randomization_vars.get("matrix_show_legacy", tk.BooleanVar()).get()
-        legacy_container = self.randomization_widgets.get("matrix_legacy_container")
-
-        if legacy_container:
-            if show_legacy:
-                # Sync from UI to legacy text before showing
-                self._sync_matrix_ui_to_text()
-                legacy_container.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
-            else:
-                # Sync from legacy text to UI before hiding
-                self._sync_matrix_text_to_ui()
-                legacy_container.pack_forget()
-
-    def _sync_matrix_ui_to_text(self) -> None:
-        """Sync matrix UI fields to the legacy text widget."""
-
-        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
-        base_prompt = base_prompt_widget.get() if base_prompt_widget else ""
-
-        slots = []
-        for row in self.randomization_widgets.get("matrix_slot_rows", []):
-            name = row["name_entry"].get().strip()
-            values_text = row["values_entry"].get().strip()
-            if name and values_text:
-                slots.append(
-                    {
-                        "name": name,
-                        "values": [v.strip() for v in values_text.split("|") if v.strip()],
-                    }
-                )
-
-        # Build legacy format: base prompt on first line, then slots
-        lines = []
-        if base_prompt:
-            lines.append(f"# Base: {base_prompt}")
-        lines.append(self._format_matrix_lines(slots))
-
-        matrix_text = self.randomization_widgets.get("matrix_text")
-        if matrix_text:
-            matrix_text.delete("1.0", tk.END)
-            matrix_text.insert("1.0", "\n".join(lines))
-
-    def _sync_matrix_text_to_ui(self) -> None:
-        """Sync legacy text widget to matrix UI fields."""
-
-        matrix_text = self.randomization_widgets.get("matrix_text")
-        if not matrix_text:
-            return
-
-        text = matrix_text.get("1.0", tk.END).strip()
-        lines = text.splitlines()
-
-        # Check for base prompt marker
-        base_prompt = ""
-        slot_lines = []
-        for line in lines:
-            line_stripped = line.strip()
-            if line_stripped.startswith("# Base:"):
-                base_prompt = line_stripped[7:].strip()
-            elif line_stripped and not line_stripped.startswith("#"):
-                slot_lines.append(line_stripped)
-
-        # Update base prompt
-        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
-        if base_prompt_widget:
-            base_prompt_widget.delete(0, tk.END)
-            base_prompt_widget.insert(0, base_prompt)
-
-        # Parse slots and rebuild UI
-        slots = self._parse_matrix_lines("\n".join(slot_lines))
-        self._clear_matrix_slot_rows()
-        for slot in slots:
-            values_str = " | ".join(slot.get("values", []))
-            self._add_matrix_slot_row(slot.get("name", ""), values_str)
-        return "\n".join(lines)
-
-    def _build_pipeline_controls_panel(self, parent):
-        """Build compact pipeline controls panel using PipelineControlsPanel component, with state restore."""
-        # Save previous state if panel exists
-        prev_state = None
-        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
-            try:
-                prev_state = self.pipeline_controls_panel.get_state()
-            except Exception as e:
-                logger.warning(f"Failed to get PipelineControlsPanel state: {e}")
-        # Destroy old panel if present
-        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
-            self.pipeline_controls_panel.destroy()
-        # Determine initial state for the new panel
-        initial_state = (
-            prev_state if prev_state is not None else self.preferences.get("pipeline_controls")
-        )
-
-        # Create the PipelineControlsPanel component
-        stage_vars = {
-            "txt2img": self.txt2img_enabled,
-            "img2img": self.img2img_enabled,
-            "adetailer": self.adetailer_enabled,
-            "upscale": self.upscale_enabled,
-            "video": self.video_enabled,
-        }
-
-        self.pipeline_controls_panel = PipelineControlsPanel(
-            parent,
-            initial_state=initial_state,
-            stage_vars=stage_vars,
-            show_variant_controls=False,
-            on_change=self._on_pipeline_controls_changed,
-            style="Dark.TFrame",
-        )
-        # Place inside parent with pack for consistency with surrounding layout
-        self.pipeline_controls_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
-        # Restore previous state if available
-        if prev_state:
-            try:
-                self.pipeline_controls_panel.set_state(prev_state)
-            except Exception as e:
-                logger.warning(f"Failed to restore PipelineControlsPanel state: {e}")
-        # Keep shared references for non-stage settings
-        self.video_enabled = self.pipeline_controls_panel.video_enabled
-        self.loop_type_var = self.pipeline_controls_panel.loop_type_var
-        self.loop_count_var = self.pipeline_controls_panel.loop_count_var
-        self.pack_mode_var = self.pipeline_controls_panel.pack_mode_var
-        self.images_per_prompt_var = self.pipeline_controls_panel.images_per_prompt_var
-
-    def _build_config_display_tab(self, notebook):
-        """Build interactive configuration tabs using ConfigPanel"""
-
-        config_frame = ttk.Frame(notebook, style="Dark.TFrame")
-        notebook.add(config_frame, text="⚙️ Configuration")
-
-        # Create ConfigPanel component
-        self.config_panel = ConfigPanel(config_frame, coordinator=self, style="Dark.TFrame")
-        self.config_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
-
-        # Set up variable references for backward compatibility
-        self.txt2img_vars = self.config_panel.txt2img_vars
-        self.img2img_vars = self.config_panel.img2img_vars
-        self.upscale_vars = self.config_panel.upscale_vars
-        self.api_vars = self.config_panel.api_vars
-        self._bind_config_panel_persistence_hooks()
-
-    def _build_bottom_panel(self, parent):
-        """Build bottom panel with logs and action buttons"""
-        bottom_frame = ttk.Frame(
-            parent, style=getattr(self.theme, "SURFACE_FRAME_STYLE", "Dark.TFrame")
-        )
-        bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
-
-        # Compact action buttons frame
-        actions_frame = ttk.Frame(bottom_frame, style="Dark.TFrame")
-        actions_frame.pack(fill=tk.X, pady=(0, 5))
-
-        # Main execution buttons with accent colors
-        main_buttons = ttk.Frame(actions_frame, style="Dark.TFrame")
-        main_buttons.pack(side=tk.LEFT)
-
-        if getattr(self, "run_pipeline_btn", None) is None:
-            self.run_pipeline_btn = ttk.Button(
-                main_buttons,
-                text="Run Full Pipeline",
-                command=self._run_full_pipeline,
-                style="Success.TButton",
-            )
-            self.run_pipeline_btn.pack(side=tk.LEFT, padx=(0, 10))
-            self._attach_tooltip(
-                self.run_pipeline_btn,
-                "Process every highlighted pack sequentially using the current configuration. Override mode applies when enabled.",
-            )
-            self.run_button = self.run_pipeline_btn
-
-        txt2img_only_btn = ttk.Button(
-            main_buttons,
-            text="txt2img Only",
-            command=self._run_txt2img_only,
-            style="Dark.TButton",
-        )
-        txt2img_only_btn.pack(side=tk.LEFT, padx=(0, 10))
-        self._attach_tooltip(
-            txt2img_only_btn,
-            "Generate txt2img outputs for the selected pack(s) only.",
-        )
-
-        upscale_only_btn = ttk.Button(
-            main_buttons,
-            text="Upscale Only",
-            command=self._run_upscale_only,
-            style="Dark.TButton",
-        )
-        upscale_only_btn.pack(side=tk.LEFT, padx=(0, 10))
-        self._attach_tooltip(
-            upscale_only_btn,
-            "Run only the upscale stage for the currently selected outputs (skips txt2img/img2img).",
-        )
-
-        create_video_btn = ttk.Button(
-            main_buttons, text="Create Video", command=self._create_video, style="Dark.TButton"
-        )
-        create_video_btn.pack(side=tk.LEFT, padx=(0, 10))
-        self._attach_tooltip(create_video_btn, "Combine rendered images into a video file.")
-
-        # Utility buttons
-        util_buttons = ttk.Frame(actions_frame, style="Dark.TFrame")
-        util_buttons.pack(side=tk.RIGHT)
-
-        open_output_btn = ttk.Button(
-            util_buttons,
-            text="Open Output",
-            command=self._open_output_folder,
-            style="Dark.TButton",
-        )
-        open_output_btn.pack(side=tk.LEFT, padx=(0, 10))
-        self._attach_tooltip(
-            open_output_btn, "Open the output directory in your system file browser."
-        )
-
-        if getattr(self, "stop_button", None) is None:
-            stop_btn = ttk.Button(
-                util_buttons, text="Stop", command=self._on_cancel_clicked, style="Danger.TButton"
-            )
-            stop_btn.pack(side=tk.LEFT, padx=(0, 10))
-            self._attach_tooltip(
-                stop_btn,
-                "Request cancellation of the pipeline run. The current stage finishes before stopping.",
-            )
-            self.stop_button = stop_btn
-
-        exit_btn = ttk.Button(
-            util_buttons, text="Exit", command=self._graceful_exit, style="Danger.TButton"
-        )
-        exit_btn.pack(side=tk.LEFT)
-        self._attach_tooltip(exit_btn, "Gracefully stop background work and close StableNew.")
-
-        # Reparent early log panel to bottom_frame
-        # (log_panel was created early in __init__ to avoid AttributeError)
-        # Create log panel directly with bottom_frame as parent
-        self.log_panel = LogPanel(bottom_frame, coordinator=self, height=18, style="Dark.TFrame")
-        self.log_panel.pack(fill=tk.BOTH, expand=True)
-        self.log_panel.pack_propagate(False)
-        self.add_log = self.log_panel.append
-        self.log_text = getattr(self.log_panel, "log_text", None)
-        if self.log_text is not None:
-            enable_mousewheel(self.log_text)
-        self._ensure_log_panel_min_height()
-
-        # Attach logging handler to redirect standard logging to GUI
-        if not hasattr(self, "gui_log_handler"):
-            self.gui_log_handler = TkinterLogHandler(self.log_panel)
-            logging.getLogger().addHandler(self.gui_log_handler)
-
-        self._build_api_status_frame(bottom_frame)
-        self._build_status_bar(bottom_frame)
-        self._refresh_txt2img_validation()
-
-    def _ensure_log_panel_min_height(self) -> None:
-        """Ensure the log panel retains a minimum visible height."""
-        if not hasattr(self, "log_panel"):
-            return
-        min_lines = max(1, getattr(self, "_log_min_lines", 7))
-        text_widget = getattr(self.log_panel, "log_text", None)
-        if text_widget is not None:
-            try:
-                current_height = int(text_widget.cget("height"))
-            except Exception:
-                current_height = min_lines
-            if current_height < min_lines:
-                try:
-                    text_widget.configure(height=min_lines)
-                except Exception:
-                    pass
-
-        def _apply_min_height():
-            try:
-                self.log_panel.update_idletasks()
-                line_height = 18
-                try:
-                    if text_widget is not None:
-                        info = text_widget.dlineinfo("1.0")
-                        if info:
-                            line_height = info[3] or line_height
-                except Exception:
-                    pass
-                min_height = int(line_height * min_lines + 60)
-                self.log_panel.configure(height=min_height)
-                self.log_panel.pack_propagate(False)
-                if (
-                    hasattr(self, "_vertical_split")
-                    and hasattr(self, "_bottom_pane")
-                    and getattr(self, "_vertical_split", None) is not None
-                ):
-                    try:
-                        self._vertical_split.paneconfigure(self._bottom_pane, minsize=min_height + 120)
-                    except Exception:
-                        pass
-            except Exception:
-                pass
-
-        try:
-            self.root.after(0, _apply_min_height)
-        except Exception:
-            _apply_min_height()
-
-    def _build_status_bar(self, parent):
-        """Build status bar showing current state"""
-        status_bar = getattr(self, "status_bar_v2", None)
-        if status_bar is None:
-            status_bar = StatusBarV2(parent, controller=self.controller, theme=self.theme)
-            self.status_bar_v2 = status_bar
-        try:
-            status_bar.pack_forget()
-        except Exception:
-            pass
-        try:
-            status_bar.pack(fill=tk.X, pady=(4, 0))
-        except Exception:
-            pass
-
-        status_frame = getattr(status_bar, "body", status_bar)
-        status_frame.configure(height=52)
-        status_frame.pack_propagate(False)
-        try:
-            status_bar.set_idle()
-        except Exception:
-            pass
-        self._status_adapter = StatusAdapterV2(status_bar)
-
-        self.progress_message_var = tk.StringVar(value=self._progress_idle_message)
-        self.progress_status_var = self.progress_message_var
-        ttk.Label(status_frame, textvariable=self.progress_message_var, style="Dark.TLabel").pack(
-            side=tk.LEFT, padx=10
-        )
-
-    def _build_ai_settings_button(self, parent) -> None:
-        """Optional AI settings button guarded by feature flag."""
-        try:
-            btn = ttk.Button(
-                parent,
-                text="Ask AI for Settings",
-                command=self._on_ask_ai_for_settings_clicked,
-                state="normal",
-            )
-            btn.pack(anchor=tk.W, pady=(10, 0))
-            self._ai_settings_button = btn
-        except Exception:
-            self._ai_settings_button = None
-
-    def _setup_state_callbacks(self):
-        """Setup callbacks for state transitions"""
-
-        def on_state_change(old_state, new_state):
-            """Called when state changes"""
-            mapped = {
-                GUIState.IDLE: "idle",
-                GUIState.RUNNING: "running",
-                GUIState.STOPPING: "running",
-                GUIState.ERROR: "error",
-            }
-            self._on_pipeline_state_change(mapped.get(new_state, "idle"))
-            if new_state == GUIState.RUNNING:
-                self.progress_message_var.set("Running pipeline...")
-            elif new_state == GUIState.STOPPING:
-                self.progress_message_var.set("Cancelling pipeline...")
-            elif new_state == GUIState.ERROR:
-                self.progress_message_var.set("Error")
-            elif new_state == GUIState.IDLE and old_state == GUIState.STOPPING:
-                self.progress_message_var.set("Ready")
-            elif new_state == GUIState.IDLE:
-                self.progress_message_var.set("Ready")
-
-            # Update button states
-            if new_state == GUIState.RUNNING:
-                self._apply_run_button_state()
-            elif new_state == GUIState.STOPPING:
-                self._apply_run_button_state()
-            elif new_state == GUIState.IDLE:
-                self._apply_run_button_state()
-            elif new_state == GUIState.ERROR:
-                self._apply_run_button_state()
-
-        self.state_manager.on_transition(on_state_change)
-
-    def _wire_progress_callbacks(self) -> None:
-        controller = getattr(self, "controller", None)
-        if controller is None:
-            return
-
-        callbacks = {
-            "on_progress": self._on_pipeline_progress,
-            "on_state_change": self._on_pipeline_state_change,
-        }
-
-        for name in (
-            "configure_progress_callbacks",
-            "register_progress_callbacks",
-            "set_progress_callbacks",
-        ):
-            method = getattr(controller, name, None)
-            if not callable(method):
-                continue
-            try:
-                method(**callbacks)
-                return
-            except TypeError:
-                try:
-                    code = method.__code__
-                    param_names = code.co_varnames[: code.co_argcount]
-                    filtered = {k: v for k, v in callbacks.items() if k in param_names}
-                    if filtered:
-                        method(**filtered)
-                        return
-                except Exception:
-                    continue
-
-    def _on_pipeline_progress(
-        self,
-        progress: float | None = None,
-        total: float | None = None,
-        eta_seconds: float | None = None,
-    ) -> None:
-        try:
-            progress_val = float(progress) if progress is not None else None
-        except (TypeError, ValueError):
-            progress_val = None
-        try:
-            total_val = float(total) if total is not None else None
-        except (TypeError, ValueError):
-            total_val = None
-
-        fraction = None
-        if progress_val is not None and total_val and total_val > 0:
-            fraction = progress_val / total_val
-
-        try:
-            eta_val = float(eta_seconds) if eta_seconds is not None else None
-        except (TypeError, ValueError):
-            eta_val = None
-
-        def apply():
-            if hasattr(self, "_status_adapter"):
-                self._status_adapter.on_progress(
-                    {"percent": (fraction * 100) if fraction is not None else None, "eta_seconds": eta_val}
-                )
-
-        apply()
-        try:
-            self.root.after(0, apply)
-        except Exception:
-            pass
-
-    def _on_ask_ai_for_settings_clicked(self) -> None:
-        try:
-            baseline = self._get_config_from_forms()
-            pack = None
-            if hasattr(self, "current_selected_packs") and self.current_selected_packs:
-                pack = getattr(self.current_selected_packs[0], "name", None) or str(
-                    self.current_selected_packs[0]
-                )
-            suggestion = self.settings_suggestion_controller.request_suggestion(
-                SuggestionIntent.HIGH_DETAIL,
-                pack,
-                baseline,
-                dataset_snapshot=None,
-            )
-            new_config = self.settings_suggestion_controller.apply_suggestion_to_config(
-                baseline, suggestion
-            )
-            self._load_config_into_forms(new_config)
-            self.log_message("Applied AI settings suggestion (stub).", "INFO")
-        except Exception as exc:
-            self.log_message(f"AI settings suggestion failed: {exc}", "WARNING")
-
-    def _on_pipeline_state_change(self, state: str | None) -> None:
-        normalized = (state or "").lower()
-
-        def apply():
-            if hasattr(self, "_status_adapter"):
-                self._status_adapter.on_state_change(normalized)
-
-        apply()
-        try:
-            self.root.after(0, apply)
-        except Exception:
-            pass
-
-    def _signal_pipeline_finished(self, event=None) -> None:
-        """Notify tests waiting on lifecycle_event that the run has terminated."""
-
-        event = event or getattr(self.controller, "lifecycle_event", None)
-        if event is None:
-            logger.debug("No lifecycle_event available to signal")
-            return
-        try:
-            event.set()
-        except Exception:
-            logger.debug("Failed to signal lifecycle_event", exc_info=True)
-
-    def _normalize_api_url(self, value: Any) -> str:
-        """Ensure downstream API clients always receive a fully-qualified URL."""
-        if isinstance(value, (int, float)):
-            return f"http://127.0.0.1:{int(value)}"
-        url = str(value or "").strip()
-        if not url:
-            return "http://127.0.0.1:7860"
-        lowered = url.lower()
-        if lowered.startswith(("http://", "https://")):
-            return url
-        if lowered.startswith("://"):
-            return f"http{url}"
-        if lowered.startswith(("127.", "localhost")):
-            return f"http://{url}"
-        if lowered.startswith(":"):
-            return f"http://127.0.0.1{url}"
-        return f"http://{url}"
-
-    def _set_api_url_var(self, value: Any) -> None:
-        if hasattr(self, "api_url_var"):
-            self.api_url_var.set(self._normalize_api_url(value))
-
-    def _poll_controller_logs(self):
-        """Poll controller for log messages and display them"""
-        messages = self.controller.get_log_messages()
-        for msg in messages:
-            self.log_message(msg.message, msg.level)
-            self._apply_status_text(msg.message)
-
-        # Schedule next poll
-        self.root.after(100, self._poll_controller_logs)
-
-    # Class-level API check method
-    def _check_api_connection(self):
-        """Check API connection status with improved diagnostics."""
-
-        if is_gui_test_mode():
-            return
-        if os.environ.get("STABLENEW_NO_WEBUI", "").lower() in {"1", "true", "yes"}:
-            return
-
-        try:
-            initial_api_url = self._normalize_api_url(self.api_url_var.get())
-        except Exception:
-            initial_api_url = self._normalize_api_url("")
-        timeout_value: int | None = None
-        if hasattr(self, "api_vars") and "timeout" in self.api_vars:
-            try:
-                timeout_value = int(self.api_vars["timeout"].get() or 30)
-            except Exception:
-                timeout_value = None
-
-        def check_in_thread(initial_url: str, timeout: int | None):
-            api_url = initial_url
-
-            # Try the specified URL first
-            self.log_message("?? Checking API connection...", "INFO")
-
-            # First try direct connection
-            client = SDWebUIClient(api_url)
-            # Apply configured timeout from API tab (keeps UI responsive on failures)
-            if timeout:
-                try:
-                    client.timeout = timeout
-                except Exception:
-                    pass
-            if client.check_api_ready():
-                # Perform health check
-                health = validate_webui_health(api_url)
-
-                self.api_connected = True
-                self.client = client
-                self.pipeline = Pipeline(client, self.structured_logger)
-                self.controller.set_pipeline(self.pipeline)
-
-                self.root.after(0, lambda: self._update_api_status(True, api_url))
-
-                if health["models_loaded"]:
-                    self.log_message(
-                        f"? API connected! Found {health.get('model_count', 0)} models", "SUCCESS"
-                    )
-                else:
-                    self.log_message("?? API connected but no models loaded", "WARNING")
-                return
-
-            # If direct connection failed, try port discovery
-            self.log_message("?? Trying port discovery...", "INFO")
-            discovered_url = find_webui_api_port()
-
-            if discovered_url:
-                # Test the discovered URL
-                client = SDWebUIClient(discovered_url)
-                if timeout:
-                    try:
-                        client.timeout = timeout
-                    except Exception:
-                        pass
-                if client.check_api_ready():
-                    health = validate_webui_health(discovered_url)
-
-                    self.api_connected = True
-                    self.client = client
-                    self.pipeline = Pipeline(client, self.structured_logger)
-                    self.controller.set_pipeline(self.pipeline)
-
-                    # Update URL field and status
-                    self.root.after(0, lambda: self._set_api_url_var(discovered_url))
-                    self.root.after(1000, self._check_api_connection)
-
-                    if health["models_loaded"]:
-                        self.log_message(
-                            f"? API found at {discovered_url}! Found {health.get('model_count', 0)} models",
-                            "SUCCESS",
-                        )
-                    else:
-                        self.log_message("?? API found but no models loaded", "WARNING")
-                    return
-
-            # Connection failed
-            self.api_connected = False
-            self.root.after(0, lambda: self._update_api_status(False))
-            self.log_message(
-                "? API connection failed. Please ensure WebUI is running with --api", "ERROR"
-            )
-            self.log_message("?? Tip: Check ports 7860-7864, restart WebUI if needed", "INFO")
-        threading.Thread(
-            target=check_in_thread, args=(initial_api_url, timeout_value), daemon=True
-        ).start()
-        # Note: previously this method started two identical threads; that was redundant and has been removed
-
-    def _update_api_status(self, connected: bool, url: str = None):
-        """Update API status indicator"""
-        if connected:
-            if hasattr(self, "api_status_panel"):
-                self.api_status_panel.set_status("Connected", "green")
-            self._apply_run_button_state()
-
-            # Update URL field if we found a different working port
-            normalized_url = self._normalize_api_url(url) if url else None
-            if normalized_url and normalized_url != self.api_url_var.get():
-                self._set_api_url_var(normalized_url)
-                self.log_message(f"Updated API URL to working port: {normalized_url}", "INFO")
-
-            # Refresh models, VAE, samplers, upscalers, and schedulers when connected
-            def refresh_all():
-                try:
-                    # Perform API calls in worker thread
-                    self._refresh_models_async()
-                    self._refresh_vae_models_async()
-                    self._refresh_samplers_async()
-                    self._refresh_hypernetworks_async()
-                    self._refresh_upscalers_async()
-                    self._refresh_schedulers_async()
-                except Exception as exc:
-                    # Marshal error message back to main thread
-                    # Capture exception in default argument to avoid closure issues
-                    self.root.after(
-                        0,
-                        lambda err=exc: self.log_message(
-                            f"⚠️ Failed to refresh model lists: {err}", "WARNING"
-                        ),
-                    )
-
-            # Run refresh in a separate thread to avoid blocking UI
-            threading.Thread(target=refresh_all, daemon=True).start()
-        else:
-            if hasattr(self, "api_status_panel"):
-                self.api_status_panel.set_status("Disconnected", "red")
-            self._apply_run_button_state()
-
-    def _on_pack_selection_changed_mediator(self, selected_packs: list[str]):
-        """
-        Mediator callback for pack selection changes from PromptPackPanel.
-
-        Args:
-            selected_packs: List of selected pack names
-        """
-        if getattr(self, "_diag_enabled", False):
-            logger.info(
-                f"[DIAG] mediator _on_pack_selection_changed_mediator start; packs={selected_packs}"
-            )
-        # Update internal state
-        self.selected_packs = selected_packs
-        self.current_selected_packs = selected_packs
-
-        if selected_packs:
-            pack_name = selected_packs[0]
-            self.log_message(f"📦 Selected pack: {pack_name}")
-            self._last_selected_pack = pack_name
-        else:
-            self.log_message("No pack selected")
-            self._last_selected_pack = None
-
-        # NOTE: Pack selection no longer auto-loads config - use Load Pack Config button instead
-        if getattr(self, "_diag_enabled", False):
-            logger.info("[DIAG] mediator _on_pack_selection_changed_mediator end")
-
-    # ...existing code...
-
-    # ...existing code...
-
-    # ...existing code...
-
-    def _refresh_prompt_packs(self):
-        """Refresh the prompt packs list"""
-        if hasattr(self, "prompt_pack_panel"):
-            self.prompt_pack_panel.refresh_packs(silent=False)
-            self.log_message("Refreshed prompt packs", "INFO")
-
-    def _refresh_prompt_packs_silent(self):
-        """Refresh the prompt packs list without logging (for initialization)"""
-        if hasattr(self, "prompt_pack_panel"):
-            self.prompt_pack_panel.refresh_packs(silent=True)
-
-    def _refresh_prompt_packs_async(self):
-        """Scan packs directory on a worker thread and populate asynchronously."""
-        if not hasattr(self, "prompt_pack_panel"):
-            return
-
-        def scan_and_populate():
-            try:
-                packs_dir = Path("packs")
-                pack_files = get_prompt_packs(packs_dir)
-                self.root.after(0, lambda: self.prompt_pack_panel.populate(pack_files))
-                self.root.after(
-                    0, lambda: self.log_message(f"?? Loaded {len(pack_files)} prompt packs", "INFO")
-                )
-            except Exception as exc:
-                self.root.after(
-                    0, lambda err=exc: self.log_message(f"? Failed to load packs: {err}", "WARNING")
-                )
-
-        threading.Thread(target=scan_and_populate, daemon=True).start()
-
-    def _refresh_config(self):
-        """Refresh configuration based on pack selection and override state"""
-        if getattr(self, "_diag_enabled", False):
-            logger.info("[DIAG] _refresh_config start")
-        # Prevent recursive refreshes
-        if self._refreshing_config:
-            if getattr(self, "_diag_enabled", False):
-                logger.info("[DIAG] _refresh_config skipped (already refreshing)")
-            return
-
-        self._refreshing_config = True
-        try:
-            selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
-            selected_packs = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
-
-            # Update UI state based on selection and override mode
-            override_mode = hasattr(self, "override_pack_var") and self.override_pack_var.get()
-            if override_mode:
-                # Override mode: use current GUI config for all selected packs
-                self._handle_override_mode(selected_packs)
-            elif len(selected_packs) == 1:
-                # Single pack: show that pack's individual config
-                self._handle_single_pack_mode(selected_packs[0])
-            elif len(selected_packs) > 1:
-                # Multiple packs: grey out config, show status message
-                self._handle_multi_pack_mode(selected_packs)
-            else:
-                # No packs selected: show preset config
-                self._handle_no_pack_mode()
-
-        finally:
-            self._refreshing_config = False
-            if getattr(self, "_diag_enabled", False):
-                logger.info("[DIAG] _refresh_config end")
-
-    def _handle_override_mode(self, selected_packs):
-        """Handle override mode: current config applies to all selected packs"""
-        # Enable all config controls
-        self._set_config_editable(True)
-
-        # Update status messages
-        if hasattr(self, "current_pack_label"):
-            self.current_pack_label.configure(
-                text=f"Override mode: {len(selected_packs)} packs selected", foreground="#ffa500"
-            )
-
-        # Show override message in config area
-        self._show_config_status(
-            "Override mode active - current config will be used for all selected packs"
-        )
-
-        self.log_message(f"Override mode: Config will apply to {len(selected_packs)} packs", "INFO")
-
-    def _handle_single_pack_mode(self, pack_name):
-        """Handle single pack selection: show pack's individual config"""
-        if getattr(self, "_diag_enabled", False):
-            logger.info(f"[DIAG] _handle_single_pack_mode start; pack={pack_name}")
-        # If override mode is NOT enabled, load the pack's config
-        if not (hasattr(self, "override_pack_var") and self.override_pack_var.get()):
-            # Ensure pack has a config file
-            pack_config = self.config_manager.ensure_pack_config(
-                pack_name, self.preset_var.get() or "default"
-            )
-
-            # Load pack's individual config into forms
-            self._load_config_into_forms(pack_config)
-            self.current_config = pack_config
-
-            self.log_message(f"Loaded config for pack: {pack_name}", "INFO")
-        else:
-            # Override mode: keep current config visible (don't reload from pack)
-            self.log_message(f"Override mode: keeping current config for pack: {pack_name}", "INFO")
-
-        # Enable config controls
-        self._set_config_editable(True)
-
-        # Update status
-        if hasattr(self, "current_pack_label"):
-            override_enabled = hasattr(self, "override_pack_var") and self.override_pack_var.get()
-            if override_enabled:
-                self.current_pack_label.configure(
-                    text=f"Pack: {pack_name} (Override)", foreground="#ffa500"
-                )
-            else:
-                self.current_pack_label.configure(text=f"Pack: {pack_name}", foreground="#00ff00")
-
-        if override_enabled:
-            self._show_config_status(f"Override mode: current config will apply to {pack_name}")
-        else:
-            self._show_config_status(f"Showing config for pack: {pack_name}")
-        if getattr(self, "_diag_enabled", False):
-            logger.info(f"[DIAG] _handle_single_pack_mode end; pack={pack_name}")
-
-    def _handle_multi_pack_mode(self, selected_packs):
-        """Handle multiple pack selection: show first pack's config, save applies to all"""
-        # If override mode is NOT enabled, load the first pack's config
-        if not self.override_pack_var.get():
-            first_pack = selected_packs[0]
-            pack_config = self.config_manager.ensure_pack_config(
-                first_pack, self.preset_var.get() or "default"
-            )
-
-            # Load first pack's config into forms
-            self._load_config_into_forms(pack_config)
-            self.current_config = pack_config
-
-            self.log_message(f"Showing config from first selected pack: {first_pack}", "INFO")
-        else:
-            # Override mode: keep current config visible
-            self.log_message(
-                f"Override mode: current config will apply to {len(selected_packs)} packs", "INFO"
-            )
-
-        # Enable config controls
-        self._set_config_editable(True)
-
-        # Update status
-        if hasattr(self, "current_pack_label"):
-            override_enabled = hasattr(self, "override_pack_var") and self.override_pack_var.get()
-            if override_enabled:
-                self.current_pack_label.configure(
-                    text=f"{len(selected_packs)} packs (Override)", foreground="#ffa500"
-                )
-            else:
-                self.current_pack_label.configure(
-                    text=f"{len(selected_packs)} packs selected", foreground="#ffff00"
-                )
-
-        if override_enabled:
-            self._show_config_status(
-                f"Override mode: current config will apply to all {len(selected_packs)} packs"
-            )
-        else:
-            self._show_config_status(
-                f"Showing config from first pack ({selected_packs[0]}). Click Save to apply to all {len(selected_packs)} pack(s)."
-            )
-
-    def _handle_no_pack_mode(self):
-        """Handle no pack selection: show preset config"""
-        # Enable config controls
-        self._set_config_editable(True)
-
-        # Load preset config
-        preset_config = self.config_manager.load_preset(self.preset_var.get())
-        if preset_config:
-            self._load_config_into_forms(preset_config)
-            self.current_config = preset_config
-
-        # Update status
-        if hasattr(self, "current_pack_label"):
-            self.current_pack_label.configure(text="No pack selected", foreground="#ff6666")
-
-        self._show_config_status(f"Showing preset config: {self.preset_var.get()}")
-
-    def _set_config_editable(self, editable: bool):
-        """Enable/disable config form controls"""
-        if hasattr(self, "config_panel"):
-            self.config_panel.set_editable(editable)
-
-    def _show_config_status(self, message: str):
-        """Show configuration status message in the config area"""
-        if hasattr(self, "config_panel"):
-            self.config_panel.set_status_message(message)
-
-    def _get_config_from_forms(self) -> dict[str, Any]:
-        """Extract current configuration from GUI forms"""
-        config = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
-        # 1) Start with ConfigPanel values if present
-        if hasattr(self, "config_panel") and self.config_panel is not None:
-            try:
-                config = self.config_panel.get_config()
-            except Exception as exc:
-                self.log_message(f"Error reading config from panel: {exc}", "ERROR")
-        # 2) Overlay with values from this form if available (authoritative when present)
-        try:
-            if hasattr(self, "txt2img_vars"):
-                for k, v in self.txt2img_vars.items():
-                    config.setdefault("txt2img", {})[k] = v.get()
-            if hasattr(self, "img2img_vars"):
-                for k, v in self.img2img_vars.items():
-                    config.setdefault("img2img", {})[k] = v.get()
-            if hasattr(self, "upscale_vars"):
-                for k, v in self.upscale_vars.items():
-                    config.setdefault("upscale", {})[k] = v.get()
-        except Exception as exc:
-            self.log_message(f"Error overlaying config from main form: {exc}", "ERROR")
-
-        # 3) Pipeline controls
-        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
-            try:
-                config["pipeline"] = self.pipeline_controls_panel.get_settings()
-            except Exception:
-                pass
-
-        if hasattr(self, "adetailer_panel") and self.adetailer_panel is not None:
-            try:
-                config["adetailer"] = self.adetailer_panel.get_config()
-            except Exception:
-                pass
-
-        try:
-            config["randomization"] = self._collect_randomization_config()
-        except Exception:
-            config["randomization"] = {}
-
-        try:
-            config["aesthetic"] = self._collect_aesthetic_config()
-        except Exception:
-            config["aesthetic"] = {}
-
-        return config
-
-    def _get_config_snapshot(self) -> dict[str, Any]:
-        """Capture a deep copy of the current form configuration."""
-        try:
-            snapshot = self._get_config_from_forms()
-        except Exception as exc:
-            self.log_message(f"Failed to capture config snapshot: {exc}", "WARNING")
-            snapshot = {}
-        return deepcopy(snapshot or {})
-
-    def _attach_summary_traces(self) -> None:
-        """Attach change traces to update live summaries."""
-        if getattr(self, "_summary_traces_attached", False):
-            return
-        try:
-
-            def attach_dict(dct: dict):
-                for var in dct.values():
-                    try:
-                        var.trace_add("write", lambda *_: self._update_live_config_summary())
-                    except Exception:
-                        pass
-
-            if hasattr(self, "txt2img_vars"):
-                attach_dict(self.txt2img_vars)
-            if hasattr(self, "img2img_vars"):
-                attach_dict(self.img2img_vars)
-            if hasattr(self, "upscale_vars"):
-                attach_dict(self.upscale_vars)
-            if hasattr(self, "pipeline_controls_panel"):
-                p = self.pipeline_controls_panel
-                for v in (
-                    getattr(p, "txt2img_enabled", None),
-                    getattr(p, "img2img_enabled", None),
-                    getattr(p, "upscale_enabled", None),
-                ):
-                    try:
-                        v and v.trace_add("write", lambda *_: self._update_live_config_summary())
-                    except Exception:
-                        pass
-            self._summary_traces_attached = True
-        except Exception:
-            pass
-
-    def _update_live_config_summary(self) -> None:
-        """Compute and render the per-tab "next run" summaries from current vars."""
-        try:
-            # txt2img summary
-            if hasattr(self, "txt2img_vars") and hasattr(self, "txt2img_summary_var"):
-                t = self.txt2img_vars
-                steps = t.get("steps").get() if "steps" in t else "-"
-                sampler = t.get("sampler_name").get() if "sampler_name" in t else "-"
-                cfg = t.get("cfg_scale").get() if "cfg_scale" in t else "-"
-                width = t.get("width").get() if "width" in t else "-"
-                height = t.get("height").get() if "height" in t else "-"
-                self.txt2img_summary_var.set(
-                    f"Next run: steps {steps}, sampler {sampler}, cfg {cfg}, size {width}x{height}"
-                )
-
-            # img2img summary
-            if hasattr(self, "img2img_vars") and hasattr(self, "img2img_summary_var"):
-                i2i = self.img2img_vars
-                steps = i2i.get("steps").get() if "steps" in i2i else "-"
-                denoise = (
-                    i2i.get("denoising_strength").get() if "denoising_strength" in i2i else "-"
-                )
-                sampler = i2i.get("sampler_name").get() if "sampler_name" in i2i else "-"
-                self.img2img_summary_var.set(
-                    f"Next run: steps {steps}, denoise {denoise}, sampler {sampler}"
-                )
-
-            # upscale summary
-            if hasattr(self, "upscale_vars") and hasattr(self, "upscale_summary_var"):
-                up = self.upscale_vars
-                mode = (up.get("upscale_mode").get() if "upscale_mode" in up else "single").lower()
-                scale = up.get("upscaling_resize").get() if "upscaling_resize" in up else "-"
-                if mode == "img2img":
-                    steps = up.get("steps").get() if "steps" in up else "-"
-                    denoise = (
-                        up.get("denoising_strength").get() if "denoising_strength" in up else "-"
-                    )
-                    sampler = up.get("sampler_name").get() if "sampler_name" in up else "-"
-                    self.upscale_summary_var.set(
-                        f"Mode: img2img — steps {steps}, denoise {denoise}, sampler {sampler}, scale {scale}x"
-                    )
-                else:
-                    upscaler = up.get("upscaler").get() if "upscaler" in up else "-"
-                    self.upscale_summary_var.set(
-                        f"Mode: single — upscaler {upscaler}, scale {scale}x"
-                    )
-        except Exception:
-            pass
-
-    def _save_current_pack_config(self):
-        """Save current configuration to the selected pack (single pack mode only)"""
-        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
-        if len(selected_indices) == 1 and not (
-            hasattr(self, "override_pack_var") and self.override_pack_var.get()
-        ):
-            pack_name = self.prompt_pack_panel.packs_listbox.get(selected_indices[0])
-            current_config = self._get_config_from_forms()
-
-            if self.config_manager.save_pack_config(pack_name, current_config):
-                self.log_message(f"Saved configuration for pack: {pack_name}", "SUCCESS")
-                self._show_config_status(f"Configuration saved for pack: {pack_name}")
-            else:
-                self.log_message(f"Failed to save configuration for pack: {pack_name}", "ERROR")
-
-    def log_message(self, message: str, level: str = "INFO"):
-        """Add message to live log with safe console fallback."""
-        import datetime
-        import sys
-        import threading
-
-        if threading.current_thread() is not threading.main_thread():
-            try:
-                self.root.after(0, lambda: self.log_message(message, level))
-                return
-            except Exception:
-                # If we cannot schedule onto Tk, fall back to console logging below.
-                pass
-
-        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
-        log_entry = f"[{timestamp}] {message}"
-
-        # Prefer GUI log panel once available
-        try:
-            add_log = getattr(self, "add_log", None)
-            if callable(add_log):
-                add_log(log_entry.strip(), level)
-            elif getattr(self, "log_panel", None) is not None:
-                self.log_panel.log(log_entry.strip(), level)
-            else:
-                raise RuntimeError("GUI log not ready")
-        except Exception:
-            # Safe console fallback that won't crash on Windows codepages
-            try:
-                enc = getattr(sys.stdout, "encoding", None) or "utf-8"
-                safe_line = f"[{level}] {log_entry.strip()}".encode(enc, errors="replace").decode(
-                    enc, errors="replace"
-                )
-                print(safe_line)
-            except Exception:
-                # Last-resort: swallow to avoid crashing the GUI init
-                pass
-
-        # Mirror to standard logger
-        if level == "ERROR":
-            logger.error(message)
-        elif level == "WARNING":
-            logger.warning(message)
-        else:
-            logger.info(message)
-
-    def _attach_tooltip(self, widget: tk.Widget, text: str, delay: int = 1500) -> None:
-        """Attach a tooltip to a widget if possible."""
-        try:
-            Tooltip(widget, text, delay=delay)
-        except Exception:
-            pass
-
-    def _run_full_pipeline(self):
-        if not self._refresh_txt2img_validation():
-            return
-        if not self._confirm_run_with_dirty():
-            return
-        self._run_full_pipeline_impl()
-
-    def _start_learning_run_stub(self) -> None:
-        """Placeholder for future learning-mode entry point."""
-
-        self.log_message("Learning mode is not enabled yet.", "INFO")
-
-    def _collect_learning_feedback_stub(self) -> None:
-        """Placeholder for future learning-mode feedback collection."""
-
-        self.log_message("Learning feedback collection is not implemented yet.", "INFO")
-
-    def _run_full_pipeline_impl(self):
-        """Run the complete pipeline"""
-        if not self.api_connected:
-            messagebox.showerror("API Error", "Please connect to API first")
-            return
-
-        # Controller-based, cancellable implementation (bypasses legacy thread path below)
-        from src.utils.file_io import read_prompt_pack
-
-        from .state import CancellationError
-
-        selected_packs = self._get_selected_packs()
-        if not selected_packs:
-            self.log_message("No prompt packs selected", "WARNING")
-            return
-
-        pack_summary = ", ".join(pack.name for pack in selected_packs)
-        self.log_message(
-            f"▶️ Starting pipeline execution for {len(selected_packs)} pack(s): {pack_summary}",
-            "INFO",
-        )
-        try:
-            override_mode = bool(self.override_pack_var.get())
-        except Exception:
-            override_mode = False
-
-        # Snapshot Tk-backed values on the main thread (thread-safe)
-        try:
-            config_snapshot = self._get_config_from_forms()
-        except Exception:
-            config_snapshot = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
-        try:
-            batch_size_snapshot = int(self.images_per_prompt_var.get())
-        except Exception:
-            batch_size_snapshot = 1
-
-        try:
-            loop_multiplier_snapshot = self._safe_int_from_var(self.loop_count_var, 1)
-        except Exception:
-            loop_multiplier_snapshot = 1
-
-        config_snapshot = config_snapshot or {
-            "txt2img": {},
-            "img2img": {},
-            "upscale": {},
-            "api": {},
-        }
-        config_snapshot = self._apply_pipeline_panel_overrides(config_snapshot)
-        randomizer_plan_result = self._build_randomizer_plan_result(config_snapshot)
-        controller_run_config = deepcopy(config_snapshot)
-        if randomizer_plan_result and getattr(randomizer_plan_result, "configs", None):
-            controller_run_config = deepcopy(randomizer_plan_result.configs[0])
-            if randomizer_plan_result.variant_count > 1:
-                logger.info(
-                    "Randomizer plan produced %d variants; TODO: multi-variant execution",
-                    randomizer_plan_result.variant_count,
-                )
-        pipeline_overrides = deepcopy(config_snapshot.get("pipeline", {}))
-        api_overrides = deepcopy(config_snapshot.get("api", {}))
-        try:
-            preset_snapshot = self.preset_var.get()
-        except Exception:
-            preset_snapshot = "default"
-
-        def resolve_config_for_pack(pack_file: Path) -> dict[str, Any]:
-            """Return per-pack configuration honoring override mode."""
-            if override_mode:
-                return deepcopy(config_snapshot)
-
-            pack_config: dict[str, Any] = {}
-            if hasattr(self, "config_manager") and self.config_manager:
-                try:
-                    pack_config = self.config_manager.ensure_pack_config(
-                        pack_file.name, preset_snapshot or "default"
-                    )
-                except Exception as exc:
-                    self.log_message(
-                        f"⚠️ Failed to load config for {pack_file.name}: {exc}. Using current form values.",
-                        "WARNING",
-                    )
-
-            merged = deepcopy(pack_config) if pack_config else {}
-            if pipeline_overrides:
-                merged.setdefault("pipeline", {}).update(pipeline_overrides)
-            if api_overrides:
-                merged.setdefault("api", {}).update(api_overrides)
-            # Always honor runtime-only sections from the current form (they are not stored per-pack)
-            for runtime_key in ("randomization", "aesthetic"):
-                snapshot_section = (
-                    deepcopy(config_snapshot.get(runtime_key)) if config_snapshot else None
-                )
-                if snapshot_section:
-                    merged[runtime_key] = snapshot_section
-
-            # Overlay live model / VAE selections from the form in non-override mode if present.
-            # Packs often persist a model/vae, but user dropdown changes should take effect for the run.
-            try:
-                live_txt2img = (config_snapshot or {}).get("txt2img", {})
-                if live_txt2img:
-                    for k in ("model", "sd_model_checkpoint", "vae"):
-                        val = live_txt2img.get(k)
-                        if isinstance(val, str) and val.strip():
-                            merged.setdefault("txt2img", {})[k] = val.strip()
-                live_img2img = (config_snapshot or {}).get("img2img", {})
-                if live_img2img:
-                    for k in ("model", "sd_model_checkpoint", "vae"):
-                        val = live_img2img.get(k)
-                        if isinstance(val, str) and val.strip():
-                            merged.setdefault("img2img", {})[k] = val.strip()
-            except Exception as exc:
-                self.log_message(
-                    f"⚠️ Failed to overlay live model/VAE selections: {exc}", "WARNING"
-                )
-
-            if merged:
-                return merged
-            return deepcopy(config_snapshot)
-
-        def pipeline_func():
-            cancel = self.controller.cancel_token
-            session_run_dir = self.structured_logger.create_run_directory()
-            self.log_message(f"📁 Session directory: {session_run_dir.name}", "INFO")
-
-            logger.info("[pipeline] ENTER pack loop (packs=%d)", len(selected_packs))
-
-            total_generated = 0
-            for pack_file in list(selected_packs):
-                pack_name = getattr(pack_file, "name", str(pack_file))
-                if cancel.is_cancelled():
-                    raise CancellationError("User cancelled before pack start")
-                self.log_message(f"[pipeline] PACK START: {pack_name}", "INFO")
-
-                read_start = time.time()
-                self.log_message(f"[pipeline] PACK {pack_name}: reading prompts", "INFO")
-                prompts = read_prompt_pack(pack_file)
-                self.log_message(
-                    f"[pipeline] PACK {pack_name}: read {len(prompts)} prompt(s) in "
-                    f"{time.time() - read_start:.2f}s",
-                    "INFO",
-                )
-                if not prompts:
-                    self.log_message(
-                        f"[pipeline] PACK {pack_name}: no prompts found; skipping", "WARNING"
-                    )
-                    continue
-
-                cfg_start = time.time()
-                self.log_message(f"[pipeline] PACK {pack_name}: resolving config", "INFO")
-                config = resolve_config_for_pack(pack_file)
-                self.log_message(
-                    f"[pipeline] PACK {pack_name}: config resolved in {time.time() - cfg_start:.2f}s",
-                    "INFO",
-                )
-                config_mode = "override" if override_mode else "pack"
-                self.log_message(
-                    f"⚙️ Using {config_mode} configuration for {pack_name}", "INFO"
-                )
-                rand_cfg = config.get("randomization", {}) or {}
-                matrix_cfg = (rand_cfg.get("matrix", {}) or {})
-                if rand_cfg.get("enabled"):
-                    sr_count = len((rand_cfg.get("prompt_sr", {}) or {}).get("rules", []) or [])
-                    wc_count = len((rand_cfg.get("wildcards", {}) or {}).get("tokens", []) or [])
-                    mx_slots = len(matrix_cfg.get("slots", []) or [])
-                    mx_base = matrix_cfg.get("base_prompt", "")
-                    mx_prompt_mode = matrix_cfg.get("prompt_mode", "replace")
-                    self.log_message(
-                        f"🎲 Randomization active: S/R={sr_count}, wildcards={wc_count}, matrix slots={mx_slots}",
-                        "INFO",
-                    )
-                    seed_val = rand_cfg.get("seed", None)
-                    if seed_val is not None:
-                        self.log_message(f"🎲 Randomization seed: {seed_val}", "INFO")
-                    if mx_base:
-                        mode_verb = {
-                            "replace": "replace",
-                            "append": "append to",
-                            "prepend": "prepend to",
-                        }
-                        verb = mode_verb.get(mx_prompt_mode, "replace")
-                        self.log_message(
-                            f"🎯 Matrix base_prompt will {verb} pack prompts: {mx_base[:60]}...",
-                            "INFO",
-                        )
-                    slot_names = [slot.get("name", "?") for slot in matrix_cfg.get("slots", [])]
-                    logger.info(
-                        "[pipeline] Randomizer matrix: mode=%s slots=%s limit=%s",
-                        matrix_cfg.get("mode", "fanout"),
-                        ",".join(slot_names) if slot_names else "-",
-                        matrix_cfg.get("limit", "n/a"),
-                    )
-                pack_variant_estimate, _ = self._estimate_pack_variants(
-                    prompts, deepcopy(rand_cfg)
-                )
-                approx_images = pack_variant_estimate * batch_size_snapshot
-                loop_multiplier = loop_multiplier_snapshot
-                if loop_multiplier > 1:
-                    approx_images *= loop_multiplier
-                self.log_message(
-                    f"?? Prediction for {pack_file.name}: {pack_variant_estimate} variant(s) -> "
-                    f"≈ {approx_images} image(s) at {batch_size_snapshot} img/prompt (loops={loop_multiplier})",
-                    "INFO",
-                )
-                self._maybe_warn_large_output(approx_images, f"pack {pack_file.name}")
-                try:
-                    randomizer = PromptRandomizer(rand_cfg)
-                except Exception as exc:
-                    self.log_message(
-                        f"?? Randomization disabled for {pack_file.name}: {exc}", "WARNING"
-                    )
-                    randomizer = PromptRandomizer({})
-                variant_plan = build_variant_plan(config)
-                if variant_plan.active:
-                    self.log_message(
-                        f"🎛️ Variant plan ({variant_plan.mode}) with {len(variant_plan.variants)} combo(s)",
-                        "INFO",
-                    )
-                batch_size = batch_size_snapshot
-                rotate_cursor = 0
-                prompt_run_index = 0
-
-                logger.info(
-                    "[pipeline] Pack %s contains %d prompt(s)",
-                    pack_file.name,
-                    len(prompts),
-                )
-
-                for i, prompt_data in enumerate(prompts):
-                    if cancel.is_cancelled():
-                        raise CancellationError("User cancelled during prompt loop")
-                    prompt_text = (prompt_data.get("positive") or "").strip()
-                    negative_override = (prompt_data.get("negative") or "").strip()
-                    self.log_message(
-                        f"📝 Prompt {i+1}/{len(prompts)}: {prompt_text[:50]}...",
-                        "INFO",
-                    )
-
-                    logger.info(
-                        "[pipeline] pack=%s prompt=%d/%d: building variants",
-                        pack_file.name,
-                        i + 1,
-                        len(prompts),
-                    )
-                    matrix_enabled = bool((rand_cfg.get("matrix", {}) or {}).get("enabled"))
-                    if matrix_enabled:
-                        logger.info("[pipeline] Calling randomizer.generate(...)")
-                        randomized_variants = randomizer.generate(prompt_text)
-                        logger.info(
-                            "[pipeline] randomizer.generate returned %d variant(s)",
-                            len(randomized_variants),
-                        )
-                    else:
-                        randomized_variants = randomizer.generate(prompt_text)
-                    if rand_cfg.get("enabled") and len(randomized_variants) == 1:
-                        self.log_message(
-                            "ℹ️ Randomization produced only one variant. Ensure prompt contains tokens (e.g. __mood__, [[slot]]) and rules have matches.",
-                            "INFO",
-                        )
-                    if not randomized_variants:
-                        randomized_variants = [PromptVariant(text=prompt_text, label=None)]
-
-                    sanitized_negative = sanitize_prompt(negative_override) if negative_override else ""
-
-                    for random_variant in randomized_variants:
-                        random_label = random_variant.label
-                        variant_prompt_text = sanitize_prompt(random_variant.text)
-                        if random_label:
-                            self.log_message(f"🎲 Randomization: {random_label}", "INFO")
-
-                        if variant_plan.active and variant_plan.variants:
-                            if variant_plan.mode == "fanout":
-                                variants_to_run = variant_plan.variants
-                            else:
-                                variant = variant_plan.variants[
-                                    rotate_cursor % len(variant_plan.variants)
-                                ]
-                                variants_to_run = [variant]
-                                rotate_cursor += 1
-                        else:
-                            variants_to_run = [None]
-
-                        logger.info(
-                            "[pipeline] pack=%s prompt=%d: running %d variant slot(s)",
-                            pack_file.name,
-                            i + 1,
-                            len(variants_to_run),
-                        )
-                        for variant in variants_to_run:
-                            if cancel.is_cancelled():
-                                raise CancellationError("User cancelled during prompt loop")
-
-                            stage_variant_label = None
-                            variant_index = 0
-                            if variant is not None:
-                                stage_variant_label = variant.label
-                                variant_index = variant.index
-                                self.log_message(
-                                    f"?? Variant {variant.index + 1}/{len(variant_plan.variants)}: {stage_variant_label}",
-                                    "INFO",
-                                )
-
-                            effective_config = apply_variant_to_config(config, variant)
-                            try:
-                                t2i_cfg = effective_config.setdefault("txt2img", {}) or {}
-                                t2i_cfg["prompt"] = variant_prompt_text
-                                if sanitized_negative:
-                                    t2i_cfg["negative_prompt"] = sanitized_negative
-                            except Exception:
-                                logger.exception("Failed to inject randomized prompt into txt2img config")
-                            # Log effective model/VAE selections for visibility in live log
-                            try:
-                                t2i_cfg = (effective_config or {}).get("txt2img", {}) or {}
-                                model_name = (
-                                    t2i_cfg.get("model") or t2i_cfg.get("sd_model_checkpoint") or ""
-                                )
-                                vae_name = t2i_cfg.get("vae") or ""
-                                if model_name or vae_name:
-                                    self.log_message(
-                                        f"🎛️ txt2img weights → model: {model_name or '(unchanged)'}; VAE: {vae_name or '(unchanged)'}",
-                                        "INFO",
-                                    )
-                                i2i_enabled = bool(
-                                    (effective_config or {})
-                                    .get("pipeline", {})
-                                    .get("img2img_enabled", False)
-                                )
-                                if i2i_enabled:
-                                    i2i_cfg = (effective_config or {}).get("img2img", {}) or {}
-                                    i2i_model = (
-                                        i2i_cfg.get("model")
-                                        or i2i_cfg.get("sd_model_checkpoint")
-                                        or ""
-                                    )
-                                    i2i_vae = i2i_cfg.get("vae") or ""
-                                    if i2i_model or i2i_vae:
-                                        self.log_message(
-                                            f"🎛️ img2img weights → model: {i2i_model or '(unchanged)'}; VAE: {i2i_vae or '(unchanged)'}",
-                                            "INFO",
-                                        )
-                            except Exception:
-                                pass
-                            logger.info(
-                                "[pipeline] Calling run_pack_pipeline (variant %d/%d)",
-                                variant_index + 1 if variant is not None else 1,
-                                len(variants_to_run),
-                            )
-                            result = self.pipeline.run_pack_pipeline(
-                                pack_name=pack_file.stem,
-                                prompt=variant_prompt_text,
-                                config=effective_config,
-                                run_dir=session_run_dir,
-                                prompt_index=prompt_run_index,
-                                batch_size=batch_size,
-                                variant_index=variant_index,
-                                variant_label=stage_variant_label,
-                            )
-                            prompt_run_index += 1
-
-                            if cancel.is_cancelled():
-                                raise CancellationError("User cancelled after pack stage")
-
-                            if result and result.get("summary"):
-                                logger.info(
-                                    "[pipeline] run_pack_pipeline returned summary=%d",
-                                    len(result.get("summary", [])),
-                                )
-                                gen = len(result["summary"])
-                                total_generated += gen
-                                suffix_parts = []
-                                if random_label:
-                                    suffix_parts.append(f"random: {random_label}")
-                                if stage_variant_label:
-                                    suffix_parts.append(f"variant {variant_index + 1}")
-                                suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
-                                self.log_message(
-                                    f"✅ Generated {gen} image(s) for prompt {i+1}{suffix}",
-                                    "SUCCESS",
-                                )
-                            else:
-                                logger.info("[pipeline] run_pack_pipeline returned no summary")
-                                suffix_parts = []
-                                if random_label:
-                                    suffix_parts.append(f"random: {random_label}")
-                                if stage_variant_label:
-                                    suffix_parts.append(f"variant {variant_index + 1}")
-                                suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
-                                self.log_message(
-                                    f"❌ Failed to generate images for prompt {i+1}{suffix}",
-                                    "ERROR",
-                                )
-                self.log_message(f"✅ Completed pack '{pack_file.stem}'", "SUCCESS")
-            return {"images_generated": total_generated, "output_dir": str(session_run_dir)}
-
-        def on_complete(result: dict):
-            try:
-                num_images = int(result.get("images_generated", 0)) if result else 0
-                output_dir = result.get("output_dir", "") if result else ""
-            except Exception:
-                num_images, output_dir = 0, ""
-            self.log_message(f"?? Pipeline completed: {num_images} image(s)", "SUCCESS")
-            if output_dir:
-                self.log_message(f"?? Output: {output_dir}", "INFO")
-            # Combined summary of effective weights
-            try:
-                model = getattr(self.pipeline, "_current_model", None)
-                vae = getattr(self.pipeline, "_current_vae", None)
-                hyper = getattr(self.pipeline, "_current_hypernetwork", None)
-                hn_strength = getattr(self.pipeline, "_current_hn_strength", None)
-                self.log_message(
-                    f"?? Run summary  model={model or '(none)'}; vae={vae or '(none)'}; hypernetwork={hyper or '(none)'}; strength={hn_strength if hn_strength is not None else '(n/a)'}",
-                    "INFO",
-                )
-            except Exception:
-                pass
-
-        def on_error(e: Exception):
-            self._handle_pipeline_error(e)
-
-        final_run_config = deepcopy(controller_run_config)
-        try:
-            setattr(self.controller, "last_run_config", final_run_config)
-        except Exception:
-            pass
-        record_hook = getattr(self.controller, "record_run_config", None)
-        if callable(record_hook):
-            try:
-                record_hook(final_run_config)
-            except Exception:
-                logger.debug("record_run_config hook failed", exc_info=True)
-
-        started = self.controller.start_pipeline(
-            pipeline_func, on_complete=on_complete, on_error=on_error
-        )
-        if started and is_gui_test_mode():
-            try:
-                event = getattr(self.controller, "lifecycle_event", None)
-                if event is not None:
-                    if not event.wait(timeout=5.0):
-                        self._signal_pipeline_finished(event)
-            except Exception:
-                pass
-        return
-
-        def run_pipeline_thread():
-            try:
-                # Create single session run directory for all packs
-                session_run_dir = self.structured_logger.create_run_directory()
-                self.log_message(f"📁 Created session directory: {session_run_dir.name}", "INFO")
-
-                # Get selected prompt packs
-                selected_packs = self._get_selected_packs()
-                if not selected_packs:
-                    self.log_message("No prompt packs selected", "WARNING")
-                    return
-
-                # Process each pack
-                for pack_file in selected_packs:
-                    self.log_message(f"Processing pack: {pack_file.name}", "INFO")
-
-                    # Read prompts from pack
-                    prompts = read_prompt_pack(pack_file)
-                    if not prompts:
-                        self.log_message(f"No prompts found in {pack_file.name}", "WARNING")
-                        continue
-
-                    # Always read the latest form values to ensure UI changes are respected
-                    config = self._get_config_from_forms()
-
-                    # Process each prompt in the pack
-                    images_generated = 0
-                    for i, prompt_data in enumerate(prompts):
-                        try:
-                            self.log_message(
-                                f"Processing prompt {i+1}/{len(prompts)}: {prompt_data['positive'][:50]}...",
-                                "INFO",
-                            )
-
-                            # Run pipeline with new directory structure
-                            result = self.pipeline.run_pack_pipeline(
-                                pack_name=pack_file.stem,
-                                prompt=prompt_data["positive"],
-                                config=config,
-                                run_dir=session_run_dir,
-                                prompt_index=i,
-                                batch_size=int(self.images_per_prompt_var.get()),
-                            )
-
-                            if result and result.get("summary"):
-                                images_generated += len(result["summary"])
-                                self.log_message(
-                                    f"✅ Generated {len(result['summary'])} images for prompt {i+1}",
-                                    "SUCCESS",
-                                )
-                            else:
-                                self.log_message(
-                                    f"❌ Failed to generate images for prompt {i+1}", "ERROR"
-                                )
-
-                        except Exception as e:
-                            self.log_message(f"❌ Error processing prompt {i+1}: {str(e)}", "ERROR")
-                            continue
-
-                    self.log_message(
-                        f"Completed pack {pack_file.name}: {images_generated} images", "SUCCESS"
-                    )
-
-                self.log_message("🎉 Pipeline execution completed!", "SUCCESS")
-
-            except Exception as e:
-                self.log_message(f"Pipeline execution failed: {e}", "ERROR")
-
-        # Run in separate thread to avoid blocking UI
-        self.log_message("🚀 Starting pipeline execution...", "INFO")
-        threading.Thread(target=run_pipeline_thread, daemon=True).start()
-
-    def _run_txt2img_only(self):
-        """Run only txt2img generation"""
-        if not self.api_connected:
-            messagebox.showerror("API Error", "Please connect to API first")
-            return
-
-        selected = self._get_selected_packs()
-        if not selected:
-            messagebox.showerror("Selection Error", "Please select at least one prompt pack")
-            return
-
-        self.log_message("🎨 Running txt2img only...", "INFO")
-
-        def txt2img_thread():
-            try:
-                run_dir = self.structured_logger.create_run_directory("txt2img_only")
-                images_per_prompt = self._safe_int_from_var(self.images_per_prompt_var, 1)
-                try:
-                    preset_name = self.preset_var.get() or "default"
-                except Exception:
-                    preset_name = "default"
-
-                for pack_path in selected:
-                    pack_name = pack_path.name
-                    self.log_message(f"Processing pack: {pack_name}", "INFO")
-
-                    prompts = read_prompt_pack(pack_path)
-                    if not prompts:
-                        self.log_message(f"No prompts found in {pack_name}", "WARNING")
-                        continue
-
-                    try:
-                        pack_config = self.config_manager.ensure_pack_config(pack_name, preset_name)
-                    except Exception as exc:
-                        self.log_message(
-                            f"?? Failed to load config for {pack_name}: {exc}. Using default settings.",
-                            "WARNING",
-                        )
-                        pack_config = {}
-
-                    rand_cfg = deepcopy(pack_config.get("randomization") or {})
-                    randomizer = None
-                    if isinstance(rand_cfg, dict) and rand_cfg.get("enabled"):
-                        try:
-                            randomizer = PromptRandomizer(rand_cfg)
-                        except Exception as exc:
-                            self.log_message(
-                                f"?? Randomization disabled for {pack_name}: {exc}", "WARNING"
-                            )
-                            randomizer = None
-
-                    txt2img_base_cfg = deepcopy(pack_config.get("txt2img", {}) or {})
-                    total_variants = 0
-
-                    for idx, prompt_data in enumerate(prompts):
-                        prompt_text = (prompt_data.get("positive") or "").strip()
-                        negative_override = (prompt_data.get("negative") or "").strip()
-                        sanitized_negative = (
-                            sanitize_prompt(negative_override) if negative_override else ""
-                        )
-                        variants = (
-                            randomizer.generate(prompt_text)
-                            if randomizer
-                            else [PromptVariant(text=prompt_text, label=None)]
-                        )
-                        total_variants += len(variants)
-
-                        if randomizer and len(variants) == 1:
-                            self.log_message(
-                                "?? Randomization produced only one variant. Ensure prompt contains tokens (e.g. __mood__, [[slot]]) and rules have matches.",
-                                "INFO",
-                            )
-
-                        for variant in variants:
-                            variant_prompt = sanitize_prompt(variant.text)
-                            cfg = deepcopy(txt2img_base_cfg)
-                            cfg["prompt"] = variant_prompt
-                            if sanitized_negative:
-                                cfg["negative_prompt"] = sanitized_negative
-                            if variant.label:
-                                self.log_message(f"?? Randomization: {variant.label}", "INFO")
-
-                            try:
-                                results = self.pipeline.run_txt2img(
-                                    prompt=variant_prompt,
-                                    config=cfg,
-                                    run_dir=run_dir,
-                                    batch_size=images_per_prompt,
-                                )
-                                if results:
-                                    self.log_message(
-                                        f"✅ Generated {len(results)} image(s) for prompt {idx+1}",
-                                        "SUCCESS",
-                                    )
-                                else:
-                                    self.log_message(
-                                        f"❌ Failed to generate image {idx+1}", "ERROR"
-                                    )
-                            except Exception as exc:
-                                self.log_message(
-                                    f"❌ Error generating image {idx+1}: {exc}", "ERROR"
-                                )
-
-                    approx_images = total_variants * images_per_prompt
-                    self._maybe_warn_large_output(
-                        approx_images, f"txt2img-only pack {pack_name}"
-                    )
-
-                self.log_message("🎉 Txt2img generation completed!", "SUCCESS")
-
-            except Exception as exc:
-                self.log_message(f"❌ Txt2img generation failed: {exc}", "ERROR")
-
-        thread = threading.Thread(target=txt2img_thread, daemon=True)
-        thread.start()
-
-    def _run_upscale_only(self):
-        """Run upscaling on existing images"""
-        if not self.api_connected:
-            messagebox.showerror("API Error", "Please connect to API first")
-            return
-
-        # Open file dialog to select images
-        file_paths = filedialog.askopenfilenames(
-            title="Select Images to Upscale",
-            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff")],
-        )
-
-        if not file_paths:
-            return
-
-        def upscale_thread():
-            try:
-                config = self.current_config or self.config_manager.get_default_config()
-                run_dir = self.structured_logger.create_run_directory("upscale_only")
-
-                for file_path in file_paths:
-                    image_path = Path(file_path)
-                    self.log_message(f"Upscaling: {image_path.name}", "INFO")
-
-                    result = self.pipeline.run_upscale(image_path, config["upscale"], run_dir)
-                    if result:
-                        self.log_message(f"✅ Upscaled: {image_path.name}", "SUCCESS")
-                    else:
-                        self.log_message(f"❌ Failed to upscale: {image_path.name}", "ERROR")
-
-                self.log_message("Upscaling completed!", "SUCCESS")
-
-            except Exception as e:
-                self.log_message(f"Upscaling failed: {e}", "ERROR")
-
-        threading.Thread(target=upscale_thread, daemon=True).start()
-
-    def _create_video(self):
-        """Create video from image sequence"""
-        # Open folder dialog to select image directory
-        folder_path = filedialog.askdirectory(title="Select Image Directory")
-        if not folder_path:
-            return
-
-        def video_thread():
-            try:
-                image_dir = Path(folder_path)
-                image_files = []
-
-                for ext in ["*.png", "*.jpg", "*.jpeg"]:
-                    image_files.extend(image_dir.glob(ext))
-
-                if not image_files:
-                    self.log_message("No images found in selected directory", "WARNING")
-                    return
-
-                # Create output video path
-                video_path = image_dir / "output_video.mp4"
-                video_path.parent.mkdir(exist_ok=True)
-
-                self.log_message(f"Creating video from {len(image_files)} images...", "INFO")
-
-                success = self.video_creator.create_video_from_images(
-                    image_files, video_path, fps=24
-                )
-
-                if success:
-                    self.log_message(f"✅ Video created: {video_path}", "SUCCESS")
-                else:
-                    self.log_message("❌ Video creation failed", "ERROR")
-
-            except Exception as e:
-                self.log_message(f"Video creation failed: {e}", "ERROR")
-
-        threading.Thread(target=video_thread, daemon=True).start()
-
-    def _get_selected_packs(self) -> list[Path]:
-        """Resolve the currently selected prompt packs in UI order."""
-        pack_names: list[str] = []
-
-        if getattr(self, "selected_packs", None):
-            pack_names = list(dict.fromkeys(self.selected_packs))
-        elif hasattr(self, "prompt_pack_panel") and hasattr(
-            self.prompt_pack_panel, "get_selected_packs"
-        ):
-            try:
-                pack_names = list(self.prompt_pack_panel.get_selected_packs())
-            except Exception:
-                pack_names = []
-
-        if (
-            not pack_names
-            and hasattr(self, "prompt_pack_panel")
-            and hasattr(self.prompt_pack_panel, "packs_listbox")
-        ):
-            try:
-                selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
-                pack_names = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
-            except Exception:
-                pack_names = []
-
-        packs_dir = Path("packs")
-        resolved: list[Path] = []
-        for pack_name in pack_names:
-            pack_path = packs_dir / pack_name
-            if pack_path.exists():
-                resolved.append(pack_path)
-            else:
-                self.log_message(f"⚠️ Pack not found on disk: {pack_path}", "WARNING")
-
-        return resolved
-
-    def _build_info_box(self, parent, title: str, text: str):
-        """Reusable helper for informational sections within tabs."""
-        frame = ttk.LabelFrame(parent, text=title, style="Dark.TLabelframe", padding=6)
-        label = ttk.Label(
-            frame,
-            text=text,
-            style="Dark.TLabel",
-            wraplength=self._current_wraplength(),
-            justify=tk.LEFT,
-        )
-        label.pack(fill=tk.X)
-        self._register_wrappable_label(label)
-        return frame
-
-    def _build_advanced_editor_tab(self, parent: tk.Widget) -> None:
-        shell = ttk.Frame(parent, style="Dark.TFrame")
-        shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
-        canvas, body = make_scrollable(shell, style="Dark.TFrame")
-        self._register_scrollable_section("advanced_editor", canvas, body)
-
-        self._build_info_box(
-            body,
-            "Advanced Prompt Editor",
-            "Manage prompt packs, validate syntax, and edit long-form content in the Advanced "
-            "Prompt Editor. Use this tab to launch the editor without digging through menus.",
-        ).pack(fill=tk.X, pady=(0, 6))
-
-        launch_frame = ttk.Frame(body, style="Dark.TFrame")
-        launch_frame.pack(fill=tk.X, pady=(0, 10))
-        ttk.Button(
-            launch_frame,
-            text="Open Advanced Prompt Editor",
-            style="Primary.TButton",
-            command=self._open_prompt_editor,
-        ).pack(side=tk.LEFT, padx=(0, 12))
-        helper_label = ttk.Label(
-            launch_frame,
-            text="Opens a new window with multi-tab editing, validation, and global negative tools.",
-            style="Dark.TLabel",
-            wraplength=self._current_wraplength(),
-            justify=tk.LEFT,
-        )
-        helper_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
-        self._register_wrappable_label(helper_label)
-
-        features_label = ttk.Label(
-            body,
-            text="Features:\n• Block-based and TSV editing modes.\n• Global negative prompt manager.\n"
-            "• Validation for missing embeddings/LoRAs.\n• Model browser with quick insert actions.",
-            style="Dark.TLabel",
-            justify=tk.LEFT,
-            wraplength=self._current_wraplength(),
-        )
-        features_label.pack(fill=tk.X, pady=(0, 10))
-        self._register_wrappable_label(features_label)
-
-    def _bind_config_panel_persistence_hooks(self) -> None:
-        """Ensure key config fields trigger preference persistence when changed."""
-        if getattr(self, "_config_panel_prefs_bound", False):
-            return
-        if not hasattr(self, "config_panel"):
-            return
-
-        tracked_vars = []
-        for key in ("model", "refiner_checkpoint"):
-            var = self.config_panel.txt2img_vars.get(key)
-            if isinstance(var, tk.Variable):
-                tracked_vars.append(var)
-
-        if not tracked_vars:
-            return
-
-        self._config_panel_prefs_bound = True
-        for var in tracked_vars:
-            try:
-                var.trace_add("write", lambda *_: self._on_config_panel_primary_change())
-            except Exception:
-                continue
-
-    def _on_config_panel_primary_change(self) -> None:
-        self._autosave_preferences_if_needed(force=True)
-
-    def _on_pipeline_controls_changed(self) -> None:
-        self._set_config_dirty(True)
-        self._autosave_preferences_if_needed(force=True)
-
-    def _set_config_dirty(self, dirty: bool) -> None:
-        self._config_dirty = bool(dirty)
-
-    def _reset_config_dirty_state(self) -> None:
-        self._set_config_dirty(False)
-
-    def _confirm_run_with_dirty(self) -> bool:
-        if not getattr(self, "_config_dirty", False):
-            return True
-        if is_gui_test_mode():
-            return True
-        return messagebox.askyesno(
-            "Unsaved Changes",
-            "The config has unsaved changes that won’t be applied to any pack. Continue anyway?",
-        )
-
-    def _maybe_show_new_features_dialog(self) -> None:
-        """Opt-in 'new features' dialog; suppressed unless explicitly enabled."""
-
-        if os.environ.get("STABLENEW_SHOW_NEW_FEATURES_DIALOG", "").lower() not in {
-            "1",
-            "true",
-            "yes",
-        }:
-            self._new_features_dialog_shown = True
-            return
-
-        if is_gui_test_mode():
-            return
-        if getattr(self, "_new_features_dialog_shown", False):
-            return
-        self._new_features_dialog_shown = True
-        self._show_new_features_dialog()
-
-    def _show_new_features_dialog(self) -> None:
-        """Display the latest feature highlights. Skips errors silently."""
-
-        try:
-            messagebox.showinfo(
-                "New Features Available",
-                (
-                    "New GUI enhancements have been added in this release.\n\n"
-                    "• Advanced prompt editor with validation tools.\n"
-                    "• Improved pack persistence and scheduler handling.\n"
-                    "• Faster pipeline startup diagnostics.\n\n"
-                    "See CHANGELOG.md for full details."
-                ),
-            )
-        except Exception:
-            logger.debug("Failed to display new features dialog", exc_info=True)
-
-    def _register_scrollable_section(
-        self, name: str, canvas: tk.Canvas, body: tk.Widget
-    ) -> None:
-        scrollbar = getattr(canvas, "_vertical_scrollbar", None)
-        self.scrollable_sections[name] = {
-            "canvas": canvas,
-            "body": body,
-            "scrollbar": scrollbar,
-        }
-
-    def _current_wraplength(self, width: int | None = None) -> int:
-        if width is None or width <= 0:
-            try:
-                width = self.root.winfo_width()
-            except Exception:
-                width = None
-        if not width or width <= 1:
-            width = self.window_min_size[0]
-        return max(int(width * 0.55), 360)
-
-    def _register_wrappable_label(self, label: tk.Widget) -> None:
-        self._wrappable_labels.append(label)
-        try:
-            label.configure(wraplength=self._current_wraplength())
-        except Exception:
-            pass
-
-    def _on_root_resize(self, event) -> None:
-        if getattr(event, "widget", None) is not self.root:
-            return
-        wrap = self._current_wraplength(event.width)
-        for label in list(self._wrappable_labels):
-            try:
-                label.configure(wraplength=wrap)
-            except Exception:
-                continue
-
-    def _open_output_folder(self):
-        """Open the output folder"""
-        output_dir = Path("output")
-        if output_dir.exists():
-            if sys.platform == "win32":
-                subprocess.run(["explorer", str(output_dir)])
-            elif sys.platform == "darwin":
-                subprocess.run(["open", str(output_dir)])
-            else:
-                subprocess.run(["xdg-open", str(output_dir)])
-        else:
-            messagebox.showinfo("No Output", "Output directory doesn't exist yet")
-
-
-
-    def _stop_execution(self):
-        """Backward-compatible alias for legacy callers."""
-        self._on_cancel_clicked()
-
-    def _open_prompt_editor(self):
-        """Open the advanced prompt pack editor"""
-        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
-        pack_path = None
-
-        if selected_indices:
-            pack_name = self.prompt_pack_panel.packs_listbox.get(selected_indices[0])
-            pack_path = Path("packs") / pack_name
-
-        # Initialize advanced editor if not already done
-        if not hasattr(self, "advanced_editor"):
-            self.advanced_editor = AdvancedPromptEditor(
-                parent_window=self.root,
-                config_manager=self.config_manager,
-                on_packs_changed=self._refresh_prompt_packs,
-                on_validation=self._handle_editor_validation,
-            )
-
-        # Open editor with selected pack
-        self.advanced_editor.open_editor(pack_path)
-
-    def _handle_editor_validation(self, results):
-        """Handle validation results from the prompt editor"""
-        # Log validation summary
-        error_count = len(results.get("errors", []))
-        warning_count = len(results.get("warnings", []))
-        # info_count = len(results.get("info", []))  # Removed unused variable
-
-        if error_count == 0 and warning_count == 0:
-            self.log_message("✅ Pack validation passed - no issues found", "SUCCESS")
-        else:
-            if error_count > 0:
-                self.log_message(f"❌ Pack validation found {error_count} error(s)", "ERROR")
-                for error in results["errors"][:3]:  # Show first 3 errors
-                    self.log_message(f"  • {error}", "ERROR")
-                if error_count > 3:
-                    self.log_message(f"  ... and {error_count - 3} more", "ERROR")
-
-            if warning_count > 0:
-                self.log_message(f"⚠️  Pack has {warning_count} warning(s)", "WARNING")
-                for warning in results["warnings"][:2]:  # Show first 2 warnings
-                    self.log_message(f"  • {warning}", "WARNING")
-                if warning_count > 2:
-                    self.log_message(f"  ... and {warning_count - 2} more", "WARNING")
-
-        # Show stats
-        stats = results.get("stats", {})
-        self.log_message(
-            f"📊 Pack stats: {stats.get('prompt_count', 0)} prompts, "
-            f"{stats.get('embedding_count', 0)} embeddings, "
-            f"{stats.get('lora_count', 0)} LoRAs",
-            "INFO",
-        )
-
-    def _open_advanced_editor(self):
-        """Wrapper method for opening advanced editor (called by button)"""
-        self._open_prompt_editor()
-
-    def _graceful_exit(self):
-        """Gracefully exit the application and guarantee process termination."""
-        self.log_message("Shutting down gracefully...", "INFO")
-
-        try:
-            self.log_message("✅ Graceful shutdown complete", "SUCCESS")
-        except Exception as exc:  # pragma: no cover - defensive logging path
-            logger.error("Error during shutdown logging: %s", exc)
-
-        try:
-            preferences = self._collect_preferences()
-            if self.preferences_manager.save_preferences(preferences):
-                self.preferences = preferences
-        except Exception as exc:  # pragma: no cover
-            logger.error("Failed to save preferences: %s", exc)
-
-        try:
-            if (
-                hasattr(self, "controller")
-                and self.controller is not None
-                and not self.controller.is_terminal
-            ):
-                try:
-                    self.controller.stop_pipeline()
-                except Exception:
-                    logger.exception("Error while stopping pipeline during exit")
-                try:
-                    self.controller.lifecycle_event.wait(timeout=5.0)
-                except Exception:
-                    logger.exception("Error waiting for controller cleanup during exit")
-        except Exception:
-            logger.exception("Unexpected error during controller shutdown")
-
-        try:
-            self.root.quit()
-            self.root.destroy()
-        except Exception:
-            logger.exception("Error tearing down Tk root during exit")
-
-        os._exit(0)
-
-    def run(self):
-        """Start the GUI application"""
-        # Start initial config refresh
-        self._refresh_config()
-
-        # Now refresh prompt packs asynchronously to avoid blocking
-        self._refresh_prompt_packs_async()
-
-        # Set up proper window closing
-        self.root.protocol("WM_DELETE_WINDOW", self._graceful_exit)
-
-        self.log_message("🚀 StableNew GUI started", "SUCCESS")
-        self.log_message("Please connect to WebUI API to begin", "INFO")
-
-        # Ensure window is visible and focused before starting mainloop
-        self.root.deiconify()  # Make sure window is not minimized
-        self.root.lift()  # Bring to front
-        self.root.focus_force()  # Force focus
-
-        # Log window state for debugging
-        self.log_message("🖥️ GUI window should now be visible", "INFO")
-
-        # Add a periodic check to ensure window stays visible
-        def check_window_visibility():
-            if self.root.state() == "iconic":  # Window is minimized
-                self.log_message("⚠️ Window was minimized, restoring...", "WARNING")
-                self.root.deiconify()
-                self.root.lift()
-            # Schedule next check in 30 seconds
-            self.root.after(30000, check_window_visibility)
-
-        # Start the visibility checker
-        self.root.after(5000, check_window_visibility)  # First check after 5 seconds
-
-    def run(self):
-        """Start the Tkinter main loop with diagnostics."""
-        logger.info("[DIAG] About to enter Tkinter mainloop", extra={"flush": True})
-        self.root.mainloop()
-
-    def _build_txt2img_config_tab(self, notebook):
-        """Build txt2img configuration form"""
-        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
-        notebook.add(tab_frame, text="🎨 txt2img")
-
-        # Pack status header
-        pack_status_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
-        pack_status_frame.pack(fill=tk.X, padx=10, pady=5)
-
-        ttk.Label(
-            pack_status_frame, text="Current Pack:", style="Dark.TLabel", font=("Arial", 9, "bold")
-        ).pack(side=tk.LEFT)
-        self.current_pack_label = ttk.Label(
-            pack_status_frame,
-            text="No pack selected",
-            style="Dark.TLabel",
-            font=("Arial", 9),
-            foreground="#ffa500",
-        )
-        self.current_pack_label.pack(side=tk.LEFT, padx=(5, 0))
-
-        # Override controls
-        override_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
-
-        self.override_pack_var = tk.BooleanVar(value=False)
-        override_checkbox = ttk.Checkbutton(
-            override_frame,
-            text="Override pack settings with current config",
-            variable=self.override_pack_var,
-            style="Dark.TCheckbutton",
-            command=self._on_override_changed,
-        )
-        override_checkbox.pack(side=tk.LEFT)
-
-        ttk.Separator(tab_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)
-
-        # Create scrollable frame
-        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
-        scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=canvas.yview)
-        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")
-
-        scrollable_frame.bind(
-            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
-        )
-
-        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
-        canvas.configure(yscrollcommand=scrollbar.set)
-
-        # Initialize config variables and widget references
-        self.txt2img_vars = {}
-        self.txt2img_widgets = {}
-
-        # Compact generation settings
-        gen_frame = ttk.LabelFrame(
-            scrollable_frame, text="Generation Settings", style="Dark.TLabelframe", padding=5
-        )
-        gen_frame.pack(fill=tk.X, pady=2)
-
-        # Steps - compact inline
-        steps_row = ttk.Frame(gen_frame, style="Dark.TFrame")
-        steps_row.pack(fill=tk.X, pady=2)
-        ttk.Label(steps_row, text="Generation Steps:", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        self.txt2img_vars["steps"] = tk.IntVar(value=20)
-        steps_spin = ttk.Spinbox(
-            steps_row, from_=1, to=150, width=8, textvariable=self.txt2img_vars["steps"]
-        )
-        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
-        self.txt2img_widgets["steps"] = steps_spin
-
-        # Sampler - compact inline
-        sampler_row = ttk.Frame(gen_frame, style="Dark.TFrame")
-        sampler_row.pack(fill=tk.X, pady=2)
-        ttk.Label(sampler_row, text="Sampler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.txt2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
-        sampler_combo = ttk.Combobox(
-            sampler_row,
-            textvariable=self.txt2img_vars["sampler_name"],
-            values=[
-                "Euler a",
-                "Euler",
-                "LMS",
-                "Heun",
-                "DPM2",
-                "DPM2 a",
-                "DPM++ 2S a",
-                "DPM++ 2M",
-                "DPM++ SDE",
-                "DPM fast",
-                "DPM adaptive",
-                "LMS Karras",
-                "DPM2 Karras",
-                "DPM2 a Karras",
-                "DPM++ 2S a Karras",
-                "DPM++ 2M Karras",
-                "DPM++ SDE Karras",
-                "DDIM",
-                "PLMS",
-            ],
-            width=18,
-            state="readonly",
-        )
-        sampler_combo.pack(side=tk.LEFT, padx=(5, 0))
-        self.txt2img_widgets["sampler_name"] = sampler_combo
-
-        # CFG Scale - compact inline
-        cfg_row = ttk.Frame(gen_frame, style="Dark.TFrame")
-        cfg_row.pack(fill=tk.X, pady=2)
-        ttk.Label(cfg_row, text="CFG Scale:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.txt2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
-        cfg_slider = EnhancedSlider(
-            cfg_row,
-            from_=1.0,
-            to=20.0,
-            variable=self.txt2img_vars["cfg_scale"],
-            resolution=0.1,
-            width=120,
-        )
-        cfg_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.txt2img_widgets["cfg_scale"] = cfg_slider
-
-        # Dimensions - compact single row
-        dims_frame = ttk.LabelFrame(
-            scrollable_frame, text="Image Dimensions", style="Dark.TLabelframe", padding=5
-        )
-        dims_frame.pack(fill=tk.X, pady=2)
-
-        dims_row = ttk.Frame(dims_frame, style="Dark.TFrame")
-        dims_row.pack(fill=tk.X)
-
-        ttk.Label(dims_row, text="Width:", style="Dark.TLabel", width=8).pack(side=tk.LEFT)
-        self.txt2img_vars["width"] = tk.IntVar(value=512)
-        width_combo = ttk.Combobox(
-            dims_row,
-            textvariable=self.txt2img_vars["width"],
-            values=[256, 320, 384, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024],
-            width=8,
-        )
-        width_combo.pack(side=tk.LEFT, padx=(2, 10))
-        self.txt2img_widgets["width"] = width_combo
-
-        ttk.Label(dims_row, text="Height:", style="Dark.TLabel", width=8).pack(side=tk.LEFT)
-        self.txt2img_vars["height"] = tk.IntVar(value=512)
-        height_combo = ttk.Combobox(
-            dims_row,
-            textvariable=self.txt2img_vars["height"],
-            values=[256, 320, 384, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024],
-            width=8,
-        )
-        height_combo.pack(side=tk.LEFT, padx=2)
-        self.txt2img_widgets["height"] = height_combo
-
-        # Advanced Settings
-        advanced_frame = ttk.LabelFrame(
-            scrollable_frame, text="Advanced Settings", style="Dark.TLabelframe", padding=5
-        )
-        advanced_frame.pack(fill=tk.X, pady=2)
-
-        # Seed controls
-        seed_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
-        seed_row.pack(fill=tk.X, pady=2)
-        ttk.Label(seed_row, text="Seed:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.txt2img_vars["seed"] = tk.IntVar(value=-1)
-        seed_spin = ttk.Spinbox(
-            seed_row, from_=-1, to=2147483647, width=12, textvariable=self.txt2img_vars["seed"]
-        )
-        seed_spin.pack(side=tk.LEFT, padx=(5, 5))
-        self.txt2img_widgets["seed"] = seed_spin
-        ttk.Button(
-            seed_row,
-            text="🎲 Random",
-            command=lambda: self.txt2img_vars["seed"].set(-1),
-            width=10,
-            style="Dark.TButton",
-        ).pack(side=tk.LEFT, padx=(5, 0))
-
-        # CLIP Skip
-        clip_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
-        clip_row.pack(fill=tk.X, pady=2)
-        ttk.Label(clip_row, text="CLIP Skip:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.txt2img_vars["clip_skip"] = tk.IntVar(value=2)
-        clip_spin = ttk.Spinbox(
-            clip_row, from_=1, to=12, width=8, textvariable=self.txt2img_vars["clip_skip"]
-        )
-        clip_spin.pack(side=tk.LEFT, padx=(5, 0))
-        self.txt2img_widgets["clip_skip"] = clip_spin
-
-        # Scheduler
-        scheduler_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
-        scheduler_row.pack(fill=tk.X, pady=2)
-        ttk.Label(scheduler_row, text="Scheduler:", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        self.txt2img_vars["scheduler"] = tk.StringVar(value="normal")
-        scheduler_combo = ttk.Combobox(
-            scheduler_row,
-            textvariable=self.txt2img_vars["scheduler"],
-            values=[
-                "normal",
-                "Karras",
-                "exponential",
-                "sgm_uniform",
-                "simple",
-                "ddim_uniform",
-                "beta",
-                "linear",
-                "cosine",
-            ],
-            width=15,
-            state="readonly",
-        )
-        scheduler_combo.pack(side=tk.LEFT, padx=(5, 0))
-        self.txt2img_widgets["scheduler"] = scheduler_combo
-
-        # Model Selection
-        model_frame = ttk.LabelFrame(
-            scrollable_frame, text="Model & VAE Selection", style="Dark.TLabelframe", padding=5
-        )
-        model_frame.pack(fill=tk.X, pady=2)
-
-        # SD Model
-        model_row = ttk.Frame(model_frame, style="Dark.TFrame")
-        model_row.pack(fill=tk.X, pady=2)
-        ttk.Label(model_row, text="SD Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.txt2img_vars["model"] = tk.StringVar(value="")
-        self.model_combo = ttk.Combobox(
-            model_row, textvariable=self.txt2img_vars["model"], width=40, state="readonly"
-        )
-        self.model_combo.pack(side=tk.LEFT, padx=(5, 5))
-        self.txt2img_widgets["model"] = self.model_combo
-        ttk.Button(
-            model_row, text="🔄", command=self._refresh_models, width=3, style="Dark.TButton"
-        ).pack(side=tk.LEFT)
-
-        # VAE Model
-        vae_row = ttk.Frame(model_frame, style="Dark.TFrame")
-        vae_row.pack(fill=tk.X, pady=2)
-        ttk.Label(vae_row, text="VAE Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.txt2img_vars["vae"] = tk.StringVar(value="")
-        self.vae_combo = ttk.Combobox(
-            vae_row, textvariable=self.txt2img_vars["vae"], width=40, state="readonly"
-        )
-        self.vae_combo.pack(side=tk.LEFT, padx=(5, 5))
-        self.txt2img_widgets["vae"] = self.vae_combo
-        ttk.Button(
-            vae_row, text="🔄", command=self._refresh_vae_models, width=3, style="Dark.TButton"
-        ).pack(side=tk.LEFT)
-
-        # Hires.Fix Settings
-        hires_frame = ttk.LabelFrame(
-            scrollable_frame, text="High-Res Fix (Hires.fix)", style="Dark.TFrame", padding=5
-        )
-        hires_frame.pack(fill=tk.X, pady=2)
-
-        # Enable Hires.fix checkbox
-        hires_enable_row = ttk.Frame(hires_frame, style="Dark.TFrame")
-        hires_enable_row.pack(fill=tk.X, pady=2)
-        self.txt2img_vars["enable_hr"] = tk.BooleanVar(value=False)
-        hires_check = ttk.Checkbutton(
-            hires_enable_row,
-            text="Enable High-Resolution Fix",
-            variable=self.txt2img_vars["enable_hr"],
-            style="Dark.TCheckbutton",
-            command=self._on_hires_toggle,
-        )
-        hires_check.pack(side=tk.LEFT)
-        self.txt2img_widgets["enable_hr"] = hires_check
-
-        # Hires scale
-        scale_row = ttk.Frame(hires_frame, style="Dark.TFrame")
-        scale_row.pack(fill=tk.X, pady=2)
-        ttk.Label(scale_row, text="Scale Factor:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.txt2img_vars["hr_scale"] = tk.DoubleVar(value=2.0)
-        scale_spin = ttk.Spinbox(
-            scale_row,
-            from_=1.1,
-            to=4.0,
-            increment=0.1,
-            width=8,
-            textvariable=self.txt2img_vars["hr_scale"],
-        )
-        scale_spin.pack(side=tk.LEFT, padx=(5, 0))
-        self.txt2img_widgets["hr_scale"] = scale_spin
-
-        # Hires upscaler
-        upscaler_row = ttk.Frame(hires_frame, style="Dark.TFrame")
-        upscaler_row.pack(fill=tk.X, pady=2)
-        ttk.Label(upscaler_row, text="HR Upscaler:", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        self.txt2img_vars["hr_upscaler"] = tk.StringVar(value="Latent")
-        hr_upscaler_combo = ttk.Combobox(
-            upscaler_row,
-            textvariable=self.txt2img_vars["hr_upscaler"],
-            values=[
-                "Latent",
-                "Latent (antialiased)",
-                "Latent (bicubic)",
-                "Latent (bicubic antialiased)",
-                "Latent (nearest)",
-                "Latent (nearest-exact)",
-                "None",
-                "Lanczos",
-                "Nearest",
-                "LDSR",
-                "BSRGAN",
-                "ESRGAN_4x",
-                "R-ESRGAN General 4xV3",
-                "ScuNET GAN",
-                "ScuNET PSNR",
-                "SwinIR 4x",
-            ],
-            width=20,
-            state="readonly",
-        )
-        hr_upscaler_combo.pack(side=tk.LEFT, padx=(5, 0))
-        self.txt2img_widgets["hr_upscaler"] = hr_upscaler_combo
-
-        # Hires denoising strength
-        hr_denoise_row = ttk.Frame(hires_frame, style="Dark.TFrame")
-        hr_denoise_row.pack(fill=tk.X, pady=2)
-        ttk.Label(hr_denoise_row, text="HR Denoising:", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        self.txt2img_vars["denoising_strength"] = tk.DoubleVar(value=0.7)
-        hr_denoise_slider = EnhancedSlider(
-            hr_denoise_row,
-            from_=0.0,
-            to=1.0,
-            variable=self.txt2img_vars["denoising_strength"],
-            resolution=0.05,
-            length=150,
-        )
-        hr_denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.txt2img_widgets["denoising_strength"] = hr_denoise_slider
-
-        # Additional Positive Prompt - compact
-        pos_frame = ttk.LabelFrame(
-            scrollable_frame,
-            text="Additional Positive Prompt (appended to pack prompts)",
-            style="Dark.TFrame",
-            padding=5,
-        )
-        pos_frame.pack(fill=tk.X, pady=2)
-        self.txt2img_vars["prompt"] = tk.StringVar(value="")
-        self.pos_text = tk.Text(
-            pos_frame, height=2, bg="#3d3d3d", fg="#ffffff", wrap=tk.WORD, font=("Segoe UI", 9)
-        )
-        self.pos_text.pack(fill=tk.X, pady=2)
-
-        # Additional Negative Prompt - compact
-        neg_frame = ttk.LabelFrame(
-            scrollable_frame,
-            text="Additional Negative Prompt (appended to pack negative prompts)",
-            style="Dark.TFrame",
-            padding=5,
-        )
-        neg_frame.pack(fill=tk.X, pady=2)
-        self.txt2img_vars["negative_prompt"] = tk.StringVar(
-            value="blurry, bad quality, distorted, ugly, malformed"
-        )
-        self.neg_text = tk.Text(
-            neg_frame, height=2, bg="#3d3d3d", fg="#ffffff", wrap=tk.WORD, font=("Segoe UI", 9)
-        )
-        self.neg_text.pack(fill=tk.X, pady=2)
-        self.neg_text.insert(1.0, self.txt2img_vars["negative_prompt"].get())
-
-        canvas.pack(side="left", fill="both", expand=True)
-        scrollbar.pack(side="right", fill="y")
-        enable_mousewheel(canvas)
-        enable_mousewheel(canvas)
-        enable_mousewheel(canvas)
-
-        # Live summary for next run (txt2img)
-        try:
-            self.txt2img_summary_var = getattr(self, "txt2img_summary_var", tk.StringVar(value=""))
-            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
-            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
-            ttk.Label(
-                summary_frame,
-                textvariable=self.txt2img_summary_var,
-                style="Dark.TLabel",
-                font=("Consolas", 9),
-            ).pack(side=tk.LEFT)
-        except Exception:
-            pass
-
-        # Attach traces and initialize summary text
-        try:
-            self._attach_summary_traces()
-            self._update_live_config_summary()
-        except Exception:
-            pass
-
-    def _build_img2img_config_tab(self, notebook):
-        """Build img2img configuration form"""
-        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
-        notebook.add(tab_frame, text="🧹 img2img")
-
-        # Create scrollable frame
-        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
-        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")
-
-        scrollable_frame.bind(
-            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
-        )
-
-        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
-
-        # Initialize config variables
-        self.img2img_vars = {}
-        self.img2img_widgets = {}
-
-        # Generation Settings
-        gen_frame = ttk.LabelFrame(
-            scrollable_frame, text="Generation Settings", style="Dark.TLabelframe", padding=5
-        )
-        gen_frame.pack(fill=tk.X, pady=2)
-
-        # Steps
-        steps_row = ttk.Frame(gen_frame, style="Dark.TFrame")
-        steps_row.pack(fill=tk.X, pady=2)
-        ttk.Label(steps_row, text="Steps:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["steps"] = tk.IntVar(value=15)
-        steps_spin = ttk.Spinbox(
-            steps_row, from_=1, to=150, width=8, textvariable=self.img2img_vars["steps"]
-        )
-        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
-        self.img2img_widgets["steps"] = steps_spin
-
-        # Denoising Strength
-        denoise_row = ttk.Frame(gen_frame, style="Dark.TFrame")
-        denoise_row.pack(fill=tk.X, pady=2)
-        ttk.Label(denoise_row, text="Denoising:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["denoising_strength"] = tk.DoubleVar(value=0.3)
-        denoise_slider = EnhancedSlider(
-            denoise_row,
-            from_=0.0,
-            to=1.0,
-            variable=self.img2img_vars["denoising_strength"],
-            resolution=0.01,
-            width=120,
-        )
-        denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.img2img_widgets["denoising_strength"] = denoise_slider
-
-        # Sampler
-        sampler_row = ttk.Frame(gen_frame, style="Dark.TFrame")
-        sampler_row.pack(fill=tk.X, pady=2)
-        ttk.Label(sampler_row, text="Sampler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
-        sampler_combo = ttk.Combobox(
-            sampler_row,
-            textvariable=self.img2img_vars["sampler_name"],
-            values=[
-                "Euler a",
-                "Euler",
-                "LMS",
-                "Heun",
-                "DPM2",
-                "DPM2 a",
-                "DPM++ 2S a",
-                "DPM++ 2M",
-                "DPM++ SDE",
-                "DPM fast",
-                "DPM adaptive",
-                "LMS Karras",
-                "DPM2 Karras",
-                "DPM2 a Karras",
-                "DPM++ 2S a Karras",
-                "DPM++ 2M Karras",
-                "DPM++ SDE Karras",
-                "DDIM",
-                "PLMS",
-            ],
-            width=18,
-            state="readonly",
-        )
-        sampler_combo.pack(side=tk.LEFT, padx=(5, 0))
-        self.img2img_widgets["sampler_name"] = sampler_combo
-
-        # CFG Scale
-        cfg_row = ttk.Frame(gen_frame, style="Dark.TFrame")
-        cfg_row.pack(fill=tk.X, pady=2)
-        ttk.Label(cfg_row, text="CFG Scale:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
-        cfg_slider = EnhancedSlider(
-            cfg_row,
-            from_=1.0,
-            to=20.0,
-            variable=self.img2img_vars["cfg_scale"],
-            resolution=0.5,
-            length=150,
-        )
-        cfg_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.img2img_widgets["cfg_scale"] = cfg_slider
-
-        # Advanced Settings
-        advanced_frame = ttk.LabelFrame(
-            scrollable_frame, text="Advanced Settings", style="Dark.TLabelframe", padding=5
-        )
-        advanced_frame.pack(fill=tk.X, pady=2)
-
-        # Seed
-        seed_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
-        seed_row.pack(fill=tk.X, pady=2)
-        ttk.Label(seed_row, text="Seed:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["seed"] = tk.IntVar(value=-1)
-        seed_spin = ttk.Spinbox(
-            seed_row, from_=-1, to=2147483647, width=12, textvariable=self.img2img_vars["seed"]
-        )
-        seed_spin.pack(side=tk.LEFT, padx=(5, 5))
-        self.img2img_widgets["seed"] = seed_spin
-        ttk.Button(
-            seed_row,
-            text="🎲 Random",
-            command=lambda: self.img2img_vars["seed"].set(-1),
-            width=10,
-            style="Dark.TButton",
-        ).pack(side=tk.LEFT, padx=(5, 0))
-
-        # CLIP Skip
-        clip_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
-        clip_row.pack(fill=tk.X, pady=2)
-        ttk.Label(clip_row, text="CLIP Skip:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["clip_skip"] = tk.IntVar(value=2)
-        clip_spin = ttk.Spinbox(
-            clip_row, from_=1, to=12, width=8, textvariable=self.img2img_vars["clip_skip"]
-        )
-        clip_spin.pack(side=tk.LEFT, padx=(5, 0))
-        self.img2img_widgets["clip_skip"] = clip_spin
-
-        # Scheduler
-        scheduler_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
-        scheduler_row.pack(fill=tk.X, pady=2)
-        ttk.Label(scheduler_row, text="Scheduler:", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        self.img2img_vars["scheduler"] = tk.StringVar(value="normal")
-        scheduler_combo = ttk.Combobox(
-            scheduler_row,
-            textvariable=self.img2img_vars["scheduler"],
-            values=[
-                "normal",
-                "Karras",
-                "exponential",
-                "sgm_uniform",
-                "simple",
-                "ddim_uniform",
-                "beta",
-                "linear",
-                "cosine",
-            ],
-            width=15,
-            state="readonly",
-        )
-        scheduler_combo.pack(side=tk.LEFT, padx=(5, 0))
-        self.img2img_widgets["scheduler"] = scheduler_combo
-
-        # Model Selection
-        model_frame = ttk.LabelFrame(
-            scrollable_frame, text="Model & VAE Selection", style="Dark.TLabelframe", padding=5
-        )
-        model_frame.pack(fill=tk.X, pady=2)
-
-        # SD Model
-        model_row = ttk.Frame(model_frame, style="Dark.TFrame")
-        model_row.pack(fill=tk.X, pady=2)
-        ttk.Label(model_row, text="SD Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["model"] = tk.StringVar(value="")
-        self.img2img_model_combo = ttk.Combobox(
-            model_row, textvariable=self.img2img_vars["model"], width=40, state="readonly"
-        )
-        self.img2img_model_combo.pack(side=tk.LEFT, padx=(5, 5))
-        self.img2img_widgets["model"] = self.img2img_model_combo
-        ttk.Button(
-            model_row, text="🔄", command=self._refresh_models, width=3, style="Dark.TButton"
-        ).pack(side=tk.LEFT)
-
-        # VAE Model
-        vae_row = ttk.Frame(model_frame, style="Dark.TFrame")
-        vae_row.pack(fill=tk.X, pady=2)
-        ttk.Label(vae_row, text="VAE Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.img2img_vars["vae"] = tk.StringVar(value="")
-        self.img2img_vae_combo = ttk.Combobox(
-            vae_row, textvariable=self.img2img_vars["vae"], width=40, state="readonly"
-        )
-        self.img2img_vae_combo.pack(side=tk.LEFT, padx=(5, 5))
-        self.img2img_widgets["vae"] = self.img2img_vae_combo
-        ttk.Button(
-            vae_row, text="🔄", command=self._refresh_vae_models, width=3, style="Dark.TButton"
-        ).pack(side=tk.LEFT)
-
-        canvas.pack(fill="both", expand=True)
-
-        # Live summary for next run (upscale)
-        try:
-            self.upscale_summary_var = getattr(self, "upscale_summary_var", tk.StringVar(value=""))
-            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
-            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
-            ttk.Label(
-                summary_frame,
-                textvariable=self.upscale_summary_var,
-                style="Dark.TLabel",
-                font=("Consolas", 9),
-            ).pack(side=tk.LEFT)
-        except Exception:
-            pass
-
-        try:
-            self._attach_summary_traces()
-            self._update_live_config_summary()
-        except Exception:
-            pass
-
-        # Live summary for next run (img2img)
-        try:
-            self.img2img_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
-            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
-            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
-            ttk.Label(
-                summary_frame,
-                textvariable=self.img2img_summary_var,
-                style="Dark.TLabel",
-                font=("Consolas", 9),
-            ).pack(side=tk.LEFT)
-        except Exception:
-            pass
-
-        try:
-            self._attach_summary_traces()
-            self._update_live_config_summary()
-        except Exception:
-            pass
-
-    def _build_upscale_config_tab(self, notebook):
-        """Build upscale configuration form"""
-        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
-        notebook.add(tab_frame, text="📈 Upscale")
-
-        # Create scrollable frame
-        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
-        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")
-
-        scrollable_frame.bind(
-            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
-        )
-
-        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
-
-        # Initialize config variables
-        self.upscale_vars = {}
-        self.upscale_widgets = {}
-
-        # Upscaling Method
-        method_frame = ttk.LabelFrame(
-            scrollable_frame, text="Upscaling Method", style="Dark.TLabelframe", padding=5
-        )
-        method_frame.pack(fill=tk.X, pady=2)
-
-        method_row = ttk.Frame(method_frame, style="Dark.TFrame")
-        method_row.pack(fill=tk.X, pady=2)
-        ttk.Label(method_row, text="Method:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.upscale_vars["upscale_mode"] = tk.StringVar(value="single")
-        method_combo = ttk.Combobox(
-            method_row,
-            textvariable=self.upscale_vars["upscale_mode"],
-            values=["single", "img2img"],
-            width=20,
-            state="readonly",
-        )
-        method_combo.pack(side=tk.LEFT, padx=(5, 5))
-        try:
-            method_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_upscale_method_state())
-        except Exception:
-            pass
-        self.upscale_widgets["upscale_mode"] = method_combo
-        ttk.Label(method_row, text="ℹ️ img2img allows denoising", style="Dark.TLabel").pack(
-            side=tk.LEFT, padx=(10, 0)
-        )
-
-        # Basic Upscaling Settings
-        basic_frame = ttk.LabelFrame(
-            scrollable_frame, text="Basic Settings", style="Dark.TLabelframe", padding=5
-        )
-        basic_frame.pack(fill=tk.X, pady=2)
-
-        # Upscaler selection
-        upscaler_row = ttk.Frame(basic_frame, style="Dark.TFrame")
-        upscaler_row.pack(fill=tk.X, pady=2)
-        ttk.Label(upscaler_row, text="Upscaler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.upscale_vars["upscaler"] = tk.StringVar(value="R-ESRGAN 4x+")
-        self.upscaler_combo = ttk.Combobox(
-            upscaler_row, textvariable=self.upscale_vars["upscaler"], width=40, state="readonly"
-        )
-        self.upscaler_combo.pack(side=tk.LEFT, padx=(5, 5))
-        self.upscale_widgets["upscaler"] = self.upscaler_combo
-        ttk.Button(
-            upscaler_row, text="🔄", command=self._refresh_upscalers, width=3, style="Dark.TButton"
-        ).pack(side=tk.LEFT)
-
-        # Scale factor
-        scale_row = ttk.Frame(basic_frame, style="Dark.TFrame")
-        scale_row.pack(fill=tk.X, pady=2)
-        ttk.Label(scale_row, text="Scale Factor:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.upscale_vars["upscaling_resize"] = tk.DoubleVar(value=2.0)
-        scale_spin = ttk.Spinbox(
-            scale_row,
-            from_=1.1,
-            to=4.0,
-            increment=0.1,
-            width=8,
-            textvariable=self.upscale_vars["upscaling_resize"],
-        )
-        scale_spin.pack(side=tk.LEFT, padx=(5, 0))
-        self.upscale_widgets["upscaling_resize"] = scale_spin
-
-        # Steps for img2img mode
-        steps_row = ttk.Frame(basic_frame, style="Dark.TFrame")
-        steps_row.pack(fill=tk.X, pady=2)
-        ttk.Label(steps_row, text="Steps (img2img):", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        try:
-            self.upscale_vars["steps"]
-        except Exception:
-            self.upscale_vars["steps"] = tk.IntVar(value=20)
-        steps_spin = ttk.Spinbox(
-            steps_row,
-            from_=1,
-            to=150,
-            textvariable=self.upscale_vars["steps"],
-            width=8,
-        )
-        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
-        self.upscale_widgets["steps"] = steps_spin
-
-        # Denoising (for img2img mode)
-        denoise_row = ttk.Frame(basic_frame, style="Dark.TFrame")
-        denoise_row.pack(fill=tk.X, pady=2)
-        ttk.Label(denoise_row, text="Denoising:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.upscale_vars["denoising_strength"] = tk.DoubleVar(value=0.35)
-        denoise_slider = EnhancedSlider(
-            denoise_row,
-            from_=0.0,
-            to=1.0,
-            variable=self.upscale_vars["denoising_strength"],
-            resolution=0.05,
-            length=150,
-        )
-        denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.upscale_widgets["denoising_strength"] = denoise_slider
-
-        # Face Restoration
-        face_frame = ttk.LabelFrame(
-            scrollable_frame, text="Face Restoration", style="Dark.TLabelframe", padding=5
-        )
-        face_frame.pack(fill=tk.X, pady=2)
-
-        # GFPGAN
-        gfpgan_row = ttk.Frame(face_frame, style="Dark.TFrame")
-        gfpgan_row.pack(fill=tk.X, pady=2)
-        ttk.Label(gfpgan_row, text="GFPGAN:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
-        self.upscale_vars["gfpgan_visibility"] = tk.DoubleVar(value=0.5)  # Default to 0.5
-        gfpgan_slider = EnhancedSlider(
-            gfpgan_row,
-            from_=0.0,
-            to=1.0,
-            variable=self.upscale_vars["gfpgan_visibility"],
-            resolution=0.01,
-            width=120,
-        )
-        gfpgan_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.upscale_widgets["gfpgan_visibility"] = gfpgan_slider
-
-        # CodeFormer
-        codeformer_row = ttk.Frame(face_frame, style="Dark.TFrame")
-        codeformer_row.pack(fill=tk.X, pady=2)
-        ttk.Label(codeformer_row, text="CodeFormer:", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        self.upscale_vars["codeformer_visibility"] = tk.DoubleVar(value=0.0)
-        codeformer_slider = EnhancedSlider(
-            codeformer_row,
-            from_=0.0,
-            to=1.0,
-            variable=self.upscale_vars["codeformer_visibility"],
-            resolution=0.05,
-            length=150,
-        )
-        codeformer_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.upscale_widgets["codeformer_visibility"] = codeformer_slider
-
-        # CodeFormer Weight
-        cf_weight_row = ttk.Frame(face_frame, style="Dark.TFrame")
-        cf_weight_row.pack(fill=tk.X, pady=2)
-        ttk.Label(cf_weight_row, text="CF Fidelity:", style="Dark.TLabel", width=15).pack(
-            side=tk.LEFT
-        )
-        self.upscale_vars["codeformer_weight"] = tk.DoubleVar(value=0.5)
-        cf_weight_slider = EnhancedSlider(
-            cf_weight_row,
-            from_=0.0,
-            to=1.0,
-            variable=self.upscale_vars["codeformer_weight"],
-            resolution=0.05,
-            length=150,
-        )
-        cf_weight_slider.pack(side=tk.LEFT, padx=(5, 5))
-        self.upscale_widgets["codeformer_weight"] = cf_weight_slider
-
-        canvas.pack(fill="both", expand=True)
-
-        # Apply initial enabled/disabled state for img2img-only controls
-        try:
-            self._apply_upscale_method_state()
-        except Exception:
-            pass
-
-    def _apply_upscale_method_state(self) -> None:
-        """Enable/disable Upscale img2img-only controls based on selected method."""
-        try:
-            mode = str(self.upscale_vars.get("upscale_mode").get()).lower()
-        except Exception:
-            mode = "single"
-        use_img2img = mode == "img2img"
-        # Steps (standard widget)
-        steps_widget = self.upscale_widgets.get("steps")
-        if steps_widget is not None:
-            try:
-                steps_widget.configure(state=("normal" if use_img2img else "disabled"))
-            except Exception:
-                pass
-        # Denoising (EnhancedSlider supports .configure(state=...))
-        denoise_widget = self.upscale_widgets.get("denoising_strength")
-        if denoise_widget is not None:
-            try:
-                denoise_widget.configure(state=("normal" if use_img2img else "disabled"))
-            except Exception:
-                pass
-
-    def _build_api_config_tab(self, notebook):
-        """Build API configuration form"""
-        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
-        notebook.add(tab_frame, text="🔌 API")
-
-        # API settings
-        api_frame = ttk.LabelFrame(
-            tab_frame, text="API Connection", style="Dark.TLabelframe", padding=10
-        )
-        api_frame.pack(fill=tk.X, pady=5)
-
-        # Base URL
-        url_frame = ttk.Frame(api_frame, style="Dark.TFrame")
-        url_frame.pack(fill=tk.X, pady=5)
-        ttk.Label(url_frame, text="Base URL:", style="Dark.TLabel").pack(side=tk.LEFT)
-        self.api_vars = {}
-        self.api_vars["base_url"] = self.api_url_var  # Use the same variable
-        url_entry = ttk.Entry(url_frame, textvariable=self.api_vars["base_url"], width=30)
-        url_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
-
-        # Timeout
-        timeout_frame = ttk.Frame(api_frame, style="Dark.TFrame")
-        timeout_frame.pack(fill=tk.X, pady=5)
-        ttk.Label(timeout_frame, text="Timeout (s):", style="Dark.TLabel").pack(side=tk.LEFT)
-        self.api_vars["timeout"] = tk.IntVar(value=300)
-        timeout_spin = ttk.Spinbox(
-            timeout_frame, from_=30, to=3600, width=10, textvariable=self.api_vars["timeout"]
-        )
-        timeout_spin.pack(side=tk.LEFT, padx=5)
-
-    def _save_all_config(self):
-        """Save all configuration changes"""
-        try:
-            # Build full config via form binder
-            config = self._get_config_from_forms()
-
-            # When packs are selected and not in override mode, persist to each selected pack
-            selected = []
-            if hasattr(self, "prompt_pack_panel") and hasattr(
-                self.prompt_pack_panel, "packs_listbox"
-            ):
-                selected = [
-                    self.prompt_pack_panel.packs_listbox.get(i)
-                    for i in self.prompt_pack_panel.packs_listbox.curselection()
-                ]
-            # Fallback: if UI focus cleared the visual selection, use last-known pack
-            if (not selected) and hasattr(self, "_last_selected_pack") and self._last_selected_pack:
-                selected = [self._last_selected_pack]
-
-            if selected and not (
-                hasattr(self, "override_pack_var") and self.override_pack_var.get()
-            ):
-                saved_any = False
-                for pack_name in selected:
-                    if self.config_manager.save_pack_config(pack_name, config):
-                        saved_any = True
-                if saved_any:
-                    self.log_message(
-                        f"Saved configuration for {len(selected)} selected pack(s)", "SUCCESS"
-                    )
-                    self._show_config_status(
-                        f"Configuration saved for {len(selected)} selected pack(s)"
-                    )
-                    try:
-                        messagebox.showinfo(
-                            "Config Saved",
-                            f"Saved configuration for {len(selected)} selected pack(s)",
-                        )
-                    except Exception:
-                        pass
-                    try:
-                        if hasattr(self, "config_panel"):
-                            self.config_panel.show_save_indicator("Saved")
-                    except Exception:
-                        pass
-                    try:
-                        self.show_top_save_indicator("Saved")
-                    except Exception:
-                        pass
-                else:
-                    self.log_message("Failed to save configuration for selected packs", "ERROR")
-            else:
-                # Save as current config and optionally preset (override/preset path)
-                self.current_config = config
-                preset_name = tk.simpledialog.askstring(
-                    "Save Preset", "Enter preset name (optional):"
-                )
-                if preset_name:
-                    self.config_manager.save_preset(preset_name, config)
-                    self.log_message(f"Saved configuration as preset: {preset_name}", "SUCCESS")
-                    try:
-                        messagebox.showinfo(
-                            "Preset Saved",
-                            f"Saved configuration as preset: {preset_name}",
-                        )
-                    except Exception:
-                        pass
-                    try:
-                        if hasattr(self, "config_panel"):
-                            self.config_panel.show_save_indicator("Saved")
-                    except Exception:
-                        pass
-                    try:
-                        self.show_top_save_indicator("Saved")
-                    except Exception:
-                        pass
-                else:
-                    self.log_message("Configuration updated (not saved as preset)", "INFO")
-                    self._show_config_status("Configuration updated (not saved as preset)")
-                    try:
-                        if hasattr(self, "config_panel"):
-                            self.config_panel.show_save_indicator("Saved")
-                    except Exception:
-                        pass
-                    try:
-                        self.show_top_save_indicator("Saved")
-                    except Exception:
-                        pass
-
-        except Exception as e:
-            self.log_message(f"Failed to save configuration: {e}", "ERROR")
-
-    def _reset_all_config(self):
-        """Reset all configuration to defaults"""
-        defaults = self.config_manager.get_default_config()
-        self._load_config_into_forms(defaults)
-        self.log_message("Configuration reset to defaults", "INFO")
-
-    def on_config_save(self, _config: dict) -> None:
-        """Coordinator callback from ConfigPanel to save current settings."""
-        try:
-            self._save_all_config()
-            if hasattr(self, "config_panel"):
-                self.config_panel.show_save_indicator("Saved")
-            self.show_top_save_indicator("Saved")
-        except Exception:
-            pass
-
-    def show_top_save_indicator(self, text: str = "Saved", duration_ms: int = 2000) -> None:
-        """Show a colored indicator next to the top Save button."""
-        try:
-            color = "#00c853" if (text or "").lower() == "saved" else "#ffa500"
-            try:
-                self.top_save_indicator.configure(foreground=color)
-            except Exception:
-                pass
-            self.top_save_indicator_var.set(text)
-            if duration_ms and (text or "").lower() == "saved":
-                self.root.after(duration_ms, lambda: self.top_save_indicator_var.set(""))
-        except Exception:
-            pass
-
-    def _on_preset_changed(self, event=None):
-        """Handle preset dropdown selection changes"""
-        preset_name = self.preset_var.get()
-        if preset_name:
-            self.log_message(f"Preset selected: {preset_name} (click Load to apply)", "INFO")
-
-    def _on_preset_dropdown_changed(self):
-        """Handle preset dropdown selection changes"""
-        preset_name = self.preset_var.get()
-        if not preset_name:
-            return
-
-        config = self.config_manager.load_preset(preset_name)
-        if not config:
-            self.log_message(f"Failed to load preset: {preset_name}", "ERROR")
-            return
-
-        self.current_preset = preset_name
-
-        # Load the preset into the visible forms
-        self._load_config_into_forms(config)
-
-        # If override mode is enabled, this becomes the new override config
-        if hasattr(self, "override_pack_var") and self.override_pack_var.get():
-            self.current_config = config
-            self.log_message(
-                f"✓ Loaded preset '{preset_name}' (Pipeline + Randomization + General)",
-                "SUCCESS",
-            )
-        else:
-            # Not in override mode - preset loaded but not persisted until Save is clicked
-            self.current_config = config
-            self.log_message(
-                f"✓ Loaded preset '{preset_name}' (Pipeline + Randomization + General). Click Save to apply to selected pack",
-                "INFO",
-            )
-
-    def _apply_default_to_selected_packs(self):
-        """Apply the default preset to currently selected pack(s)"""
-        default_config = self.config_manager.load_preset("default")
-        if not default_config:
-            self.log_message("Failed to load default preset", "ERROR")
-            return
-
-        # Load into forms
-        self._load_config_into_forms(default_config)
-        self.current_config = default_config
-        self.preset_var.set("default")
-        self.current_preset = "default"
-
-        self.log_message(
-            "✓ Loaded default preset (click Save to apply to selected pack)", "SUCCESS"
-        )
-
-    def _save_config_to_packs(self):
-        """Save current configuration to selected pack(s)"""
-        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
-        if not selected_indices:
-            self.log_message("No packs selected", "WARNING")
-            return
-
-        selected_packs = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
-        current_config = self._get_config_from_forms()
-
-        saved_count = 0
-        for pack_name in selected_packs:
-            if self.config_manager.save_pack_config(pack_name, current_config):
-                saved_count += 1
-
-        if saved_count > 0:
-            if len(selected_packs) == 1:
-                self.log_message(f"✓ Saved config to pack: {selected_packs[0]}", "SUCCESS")
-            else:
-                self.log_message(
-                    f"✓ Saved config to {saved_count}/{len(selected_packs)} pack(s)", "SUCCESS"
-                )
-        else:
-            self.log_message("Failed to save config to packs", "ERROR")
-
-    def _load_selected_preset(self):
-        """Load the currently selected preset into the form"""
-        preset_name = self.preset_var.get()
-        if not preset_name:
-            self.log_message("No preset selected", "WARNING")
-            return
-
-        config = self.config_manager.load_preset(preset_name)
-        if config:
-            self.current_preset = preset_name
-            if not (hasattr(self, "override_pack_var") and self.override_pack_var.get()):
-                self._load_config_into_forms(config)
-            self.current_config = config
-            self.log_message(f"✓ Loaded preset: {preset_name}", "SUCCESS")
-            self._refresh_config()
-            # Refresh pack list asynchronously to reflect any changes
-            try:
-                self._refresh_prompt_packs_async()
-            except Exception:
-                pass
-        else:
-            self.log_message(f"Failed to load preset: {preset_name}", "ERROR")
-
-    def _save_preset_as(self):
-        """Save current configuration as a new preset with user-provided name"""
-        from tkinter import simpledialog
-
-        current_config = self._get_config_from_forms()
-
-        preset_name = simpledialog.askstring(
-            "Save Preset As",
-            "Enter a name for the new preset:",
-            initialvalue="",
-        )
-
-        if not preset_name:
-            return
-
-        # Clean up the name
-        preset_name = preset_name.strip()
-        if not preset_name:
-            self.log_message("Preset name cannot be empty", "WARNING")
-            return
-
-        # Check if preset already exists
-        if preset_name in self.config_manager.list_presets():
-            from tkinter import messagebox
-
-            overwrite = messagebox.askyesno(
-                "Preset Exists",
-                f"Preset '{preset_name}' already exists. Overwrite it?",
-            )
-            if not overwrite:
-                return
-
-        if self.config_manager.save_preset(preset_name, current_config):
-            self.log_message(f"✓ Saved preset as: {preset_name}", "SUCCESS")
-            # Refresh dropdown
-            self.preset_dropdown["values"] = self.config_manager.list_presets()
-            # Select the new preset
-            self.preset_var.set(preset_name)
-            self.current_preset = preset_name
-        else:
-            self.log_message(f"Failed to save preset: {preset_name}", "ERROR")
-
-    def _delete_selected_preset(self):
-        """Delete the currently selected preset after confirmation"""
-        from tkinter import messagebox
-
-        preset_name = self.preset_var.get()
-        if not preset_name:
-            self.log_message("No preset selected", "WARNING")
-            return
-
-        if preset_name == "default":
-            messagebox.showwarning(
-                "Cannot Delete Default",
-                "The 'default' preset is protected and cannot be deleted.\n\nYou can overwrite it with different settings, but it cannot be removed.",
-            )
-            return
-
-        confirm = messagebox.askyesno(
-            "Delete Preset",
-            f"Are you sure you want to delete the '{preset_name}' preset forever?",
-        )
-
-        if not confirm:
-            return
-
-        if self.config_manager.delete_preset(preset_name):
-            self.log_message(f"✓ Deleted preset: {preset_name}", "SUCCESS")
-            # Refresh dropdown
-            self.preset_dropdown["values"] = self.config_manager.list_presets()
-            # Select default
-            self.preset_var.set("default")
-            self.current_preset = "default"
-            # Load default into forms
-            self._on_preset_dropdown_changed()
-        else:
-            self.log_message(f"Failed to delete preset: {preset_name}", "ERROR")
-
-    def _set_as_default_preset(self):
-        """Mark the currently selected preset as the default (auto-loads on startup)"""
-        from tkinter import messagebox
-
-        preset_name = self.preset_var.get()
-        if not preset_name:
-            self.log_message("No preset selected", "WARNING")
-            return
-
-        # Check if there's already a default
-        current_default = self.config_manager.get_default_preset()
-        if current_default == preset_name:
-            messagebox.showinfo(
-                "Already Default",
-                f"'{preset_name}' is already marked as the default preset.",
-            )
-            return
-
-        if self.config_manager.set_default_preset(preset_name):
-            self.log_message(f"⭐ Marked '{preset_name}' as default preset", "SUCCESS")
-            messagebox.showinfo(
-                "Default Preset Set",
-                f"'{preset_name}' will now auto-load when the application starts.",
-            )
-        else:
-            self.log_message(f"Failed to set default preset: {preset_name}", "ERROR")
-
-    def _save_override_preset(self):
-        """Save current configuration as the override preset (updates selected preset)"""
-        current_config = self._get_config_from_forms()
-        preset_name = self.preset_var.get()
-
-        if not preset_name:
-            self.log_message("No preset selected to update", "WARNING")
-            return
-
-        if self.config_manager.save_preset(preset_name, current_config):
-            self.log_message(f"✓ Updated preset: {preset_name}", "SUCCESS")
-        else:
-            self.log_message(f"Failed to update preset: {preset_name}", "ERROR")
-
-    def _on_override_changed(self):
-        """Handle override checkbox changes"""
-        # Refresh configuration display based on new override state
-        self._refresh_config()
-
-        if hasattr(self, "override_pack_var") and self.override_pack_var.get():
-            self.log_message(
-                "📝 Override mode enabled - current config will apply to all selected packs", "INFO"
-            )
-        else:
-            self.log_message("📝 Override mode disabled - packs will use individual configs", "INFO")
-
-    def _preserve_pack_selection(self):
-        """Preserve pack selection when config changes"""
-        if hasattr(self, "_last_selected_pack") and self._last_selected_pack:
-            # Find and reselect the last selected pack
-            current_selection = self.prompt_pack_panel.packs_listbox.curselection()
-            if not current_selection:  # Only restore if nothing is selected
-                for i in range(self.prompt_pack_panel.packs_listbox.size()):
-                    if self.prompt_pack_panel.packs_listbox.get(i) == self._last_selected_pack:
-                        self.prompt_pack_panel.packs_listbox.selection_set(i)
-                        self.prompt_pack_panel.packs_listbox.activate(i)
-                        # Pack selection restored silently - no need to log every restore
-                        break
-
-    def _load_config_into_forms(self, config):
-        """Load configuration values into form widgets"""
-        if getattr(self, "_diag_enabled", False):
-            logger.info("[DIAG] _load_config_into_forms: start", extra={"flush": True})
-        # Preserve current pack selection before updating forms
-        current_selection = self.prompt_pack_panel.packs_listbox.curselection()
-        selected_pack = None
-        if current_selection:
-            selected_pack = self.prompt_pack_panel.packs_listbox.get(current_selection[0])
-
-        try:
-            if hasattr(self, "config_panel"):
-                if getattr(self, "_diag_enabled", False):
-                    logger.info(
-                        "[DIAG] _load_config_into_forms: calling config_panel.set_config",
-                        extra={"flush": True},
-                    )
-                self.config_panel.set_config(config)
-                if getattr(self, "_diag_enabled", False):
-                    logger.info(
-                        "[DIAG] _load_config_into_forms: config_panel.set_config returned",
-                        extra={"flush": True},
-                    )
-            if hasattr(self, "adetailer_panel") and self.adetailer_panel:
-                if getattr(self, "_diag_enabled", False):
-                    logger.info(
-                        "[DIAG] _load_config_into_forms: calling adetailer_panel.set_config",
-                        extra={"flush": True},
-                    )
-                self._apply_adetailer_config_section(config.get("adetailer", {}))
-            if getattr(self, "_diag_enabled", False):
-                logger.info(
-                    "[DIAG] _load_config_into_forms: calling _load_randomization_config",
-                    extra={"flush": True},
-                )
-            self._load_randomization_config(config)
-            if getattr(self, "_diag_enabled", False):
-                logger.info(
-                    "[DIAG] _load_config_into_forms: calling _load_aesthetic_config",
-                    extra={"flush": True},
-                )
-            self._load_aesthetic_config(config)
-        except Exception as e:
-            self.log_message(f"Error loading config into forms: {e}", "ERROR")
-            if getattr(self, "_diag_enabled", False):
-                logger.error(
-                    f"[DIAG] _load_config_into_forms: exception {e}",
-                    exc_info=True,
-                    extra={"flush": True},
-                )
-
-        # Restore pack selection if it was lost during form updates
-        if selected_pack and not self.prompt_pack_panel.packs_listbox.curselection():
-            if getattr(self, "_diag_enabled", False):
-                logger.info(
-                    "[DIAG] _load_config_into_forms: restoring pack selection",
-                    extra={"flush": True},
-                )
-            for i in range(self.prompt_pack_panel.packs_listbox.size()):
-                if self.prompt_pack_panel.packs_listbox.get(i) == selected_pack:
-                    # Use unwrapped selection_set to avoid triggering callback recursively
-                    if hasattr(self.prompt_pack_panel, "_orig_selection_set"):
-                        self.prompt_pack_panel._orig_selection_set(i)
-                    else:
-                        self.prompt_pack_panel.packs_listbox.selection_set(i)
-                    self.prompt_pack_panel.packs_listbox.activate(i)
-                    break
-        if getattr(self, "_diag_enabled", False):
-            logger.info("[DIAG] _load_config_into_forms: end", extra={"flush": True})
-
-    def _apply_saved_preferences(self):
-        """Apply persisted preferences to the current UI session."""
-
-        prefs = getattr(self, "preferences", None)
-        if not prefs:
-            return
-
-        try:
-            # Restore preset selection and override mode
-            self.current_preset = prefs.get("preset", "default")
-            if hasattr(self, "preset_var"):
-                self.preset_var.set(self.current_preset)
-            if hasattr(self, "override_pack_var"):
-                self.override_pack_var.set(prefs.get("override_pack", False))
-
-            # Restore pipeline control toggles
-            pipeline_state = prefs.get("pipeline_controls")
-            if pipeline_state and hasattr(self, "pipeline_controls_panel"):
-                try:
-                    self.pipeline_controls_panel.set_state(pipeline_state)
-                except Exception as exc:
-                    logger.warning(f"Failed to restore pipeline preferences: {exc}")
-
-            # Restore pack selections
-            selected_packs = prefs.get("selected_packs", [])
-            if selected_packs and hasattr(self, "packs_listbox"):
-                self.prompt_pack_panel.packs_listbox.selection_clear(0, tk.END)
-                for pack_name in selected_packs:
-                    for index in range(self.prompt_pack_panel.packs_listbox.size()):
-                        if self.prompt_pack_panel.packs_listbox.get(index) == pack_name:
-                            self.prompt_pack_panel.packs_listbox.selection_set(index)
-                            self.prompt_pack_panel.packs_listbox.activate(index)
-                self._update_selection_highlights()
-                self.selected_packs = selected_packs
-                if selected_packs:
-                    self._last_selected_pack = selected_packs[0]
-
-            # Restore configuration values into forms
-            config = prefs.get("config")
-            if config:
-                self._load_config_into_forms(config)
-                self.current_config = config
-        except Exception as exc:  # pragma: no cover - defensive logging path
-            logger.warning(f"Failed to apply saved preferences: {exc}")
-
-    def _collect_preferences(self) -> dict[str, Any]:
-        """Collect current UI preferences for persistence."""
-
-        preferences = {
-            "preset": self.preset_var.get() if hasattr(self, "preset_var") else "default",
-            "selected_packs": [],
-            "override_pack": (
-                bool(self.override_pack_var.get()) if hasattr(self, "override_pack_var") else False
-            ),
-            "pipeline_controls": self.preferences_manager.default_pipeline_controls(),
-            "config": self._get_config_from_forms(),
-        }
-
-        if hasattr(self, "packs_listbox"):
-            preferences["selected_packs"] = [
-                self.prompt_pack_panel.packs_listbox.get(i)
-                for i in self.prompt_pack_panel.packs_listbox.curselection()
-            ]
-
-        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
-            try:
-                preferences["pipeline_controls"] = self.pipeline_controls_panel.get_state()
-            except Exception as exc:  # pragma: no cover - defensive logging path
-                logger.warning(f"Failed to capture pipeline controls state: {exc}")
-
-        return preferences
-
-    def _build_settings_tab(self, parent):
-        """Build settings tab"""
-        settings_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD)
-        settings_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
-
-        # Show current preset
-        presets = self.config_manager.list_presets()
-        settings_text.insert(1.0, "Available Presets:")
-        for preset in presets:
-            settings_text.insert(tk.END, f"- {preset}")
-
-        settings_text.insert(tk.END, "Default Configuration:")
-        default_config = self.config_manager.get_default_config()
-        settings_text.insert(tk.END, json.dumps(default_config, indent=2))
-
-        settings_text.config(state=tk.DISABLED)
-
-    def _build_log_tab(self, parent):
-        """Build log tab"""
-        self.log_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD, state=tk.DISABLED)
-        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
-
-        # Add a handler to redirect logs to the text widget
-        # This is a simple implementation - could be enhanced
-        self._add_log_message("Log viewer initialized")
-
-    def _add_log_message(self, message: str):
-        """Add message to log viewer"""
-        self.log_text.config(state=tk.NORMAL)
-        self.log_text.insert(tk.END, message + "")
-        self.log_text.see(tk.END)
-        self.log_text.config(state=tk.DISABLED)
-
-    def _refresh_presets(self):
-        """Refresh preset list"""
-        presets = self.config_manager.list_presets()
-        self.preset_combo["values"] = presets
-        if presets and not self.preset_var.get():
-            self.preset_var.set(presets[0])
-
-    def _run_pipeline(self):
-        """Run the full pipeline using controller"""
-        if not self.client or not self.pipeline:
-            messagebox.showerror("Error", "Please check API connection first")
-            return
-
-        prompt = self.prompt_text.get(1.0, tk.END).strip()
-        if not prompt:
-            messagebox.showerror("Error", "Please enter a prompt")
-            return
-
-        # Get configuration from GUI forms (current user settings)
-        config = self._get_config_from_forms()
-        if not config:
-            messagebox.showerror("Error", "Failed to read configuration from forms")
-            return
-
-        # Modify config based on options
-        if not self.enable_img2img_var.get():
-            config.pop("img2img", None)
-        if not self.enable_upscale_var.get():
-            config.pop("upscale", None)
-
-        batch_size = self.batch_size_var.get()
-        run_name = self.run_name_var.get() or None
-
-        self.controller.report_progress("Running pipeline...", 0.0, "ETA: --")
-        lifecycle_event = threading.Event()
-        try:
-            self.controller.lifecycle_event = lifecycle_event
-        except Exception:
-            pass
-
-        # Define pipeline function that checks cancel token
-        # Snapshot Tk-backed values on the main thread (thread-safe)
-        try:
-            config_snapshot = self._get_config_from_forms()
-        except Exception:
-            config_snapshot = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
-        try:
-            batch_size_snapshot = int(self.images_per_prompt_var.get())
-        except Exception:
-            batch_size_snapshot = 1
-
-        pipeline_failed = False
-
-        def pipeline_func():
-            try:
-                # Pass cancel_token to pipeline
-                results = self.pipeline.run_full_pipeline(
-                    prompt, config, run_name, batch_size, cancel_token=self.controller.cancel_token
-                )
-                return results
-            except CancellationError:
-                # Signal completion and prefer Ready status after cancellation
-                if lifecycle_event is not None:
-                    lifecycle_event.set()
-                else:
-                    self._signal_pipeline_finished()
-                try:
-                    self._force_error_status = False
-                    if hasattr(self, "progress_message_var"):
-                        # Schedule on Tk to mirror normal status handling
-                        self.root.after(0, lambda: self.progress_message_var.set("Ready"))
-                except Exception:
-                    pass
-                raise
-            except Exception:
-                logger.exception("Pipeline execution error")
-                nonlocal pipeline_failed
-                pipeline_failed = True
-                # Build error text up-front
-                try:
-                    import sys
-
-                    ex_type, ex, _ = sys.exc_info()
-                    err_text = (
-                        f"Pipeline failed: {ex_type.__name__}: {ex}"
-                        if (ex_type and ex)
-                        else "Pipeline failed"
-                    )
-                except Exception:
-                    err_text = "Pipeline failed"
-
-                # Log friendly error line to app log first (test captures this)
-                try:
-                    self.log_message(f"? {err_text}", "ERROR")
-                except Exception:
-                    pass
-
-                # Marshal error dialog to Tk thread (or bypass if env says so)
-                def _show_err():
-                    try:
-                        import os
-
-                        if os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {"1", "true", "TRUE"}:
-                            return
-                        if not getattr(self, "_error_dialog_shown", False):
-                            messagebox.showerror("Pipeline Error", err_text)
-                            self._error_dialog_shown = True
-                    except Exception:
-                        logger.exception("Unable to display error dialog")
-
-                try:
-                    self.root.after(0, _show_err)
-                except Exception:
-                    # Fallback for test harnesses without a real root loop
-                    _show_err()
-
-                # Ensure tests waiting on lifecycle_event are not blocked
-                try:
-                    if lifecycle_event is not None:
-                        lifecycle_event.set()
-                    else:
-                        self._signal_pipeline_finished()
-                except Exception:
-                    logger.debug(
-                        "Failed to signal lifecycle_event after pipeline error",
-                        exc_info=True,
-                    )
-
-                # Force visible error state/status
-                self._force_error_status = True
-                try:
-                    if hasattr(self, "progress_message_var"):
-                        self.progress_message_var.set("Error")
-                except Exception:
-                    pass
-                try:
-                    from .state import GUIState
-
-                    # Schedule transition on Tk thread for deterministic callback behavior
-                    self.root.after(0, lambda: self.state_manager.transition_to(GUIState.ERROR))
-                except Exception:
-                    pass
-
-                # (Already logged above)
-                raise
-
-        # Completion callback
-        def on_complete(results):
-            output_dir = results.get("run_dir", "Unknown")
-            num_images = len(results.get("summary", []))
-
-            self.root.after(
-                0,
-                lambda: self.log_message(
-                    f"✓ Pipeline completed: {num_images} images generated", "SUCCESS"
-                ),
-            )
-            self.root.after(0, lambda: self.log_message(f"Output directory: {output_dir}", "INFO"))
-            self.root.after(
-                0,
-                lambda: messagebox.showinfo(
-                    "Success",
-                    f"Pipeline completed!{num_images} images generatedOutput: {output_dir}",
-                ),
-            )
-            # Reset error-control flags for the next run
-            try:
-                self._force_error_status = False
-                self._error_dialog_shown = False
-            except Exception:
-                pass
-            # Ensure lifecycle_event is signaled for tests waiting on completion
-            if lifecycle_event is not None:
-                lifecycle_event.set()
-            else:
-                self._signal_pipeline_finished()
-
-        # Error callback
-        def on_error(e):
-            # Log and alert immediately (safe for tests with mocked messagebox)
-            try:
-                err_text = f"Pipeline failed: {type(e).__name__}: {e}"
-                self.log_message(f"? {err_text}", "ERROR")
-                try:
-                    if hasattr(self, "progress_message_var"):
-                        self.progress_message_var.set("Error")
-                except Exception:
-                    pass
-                try:
-                    if not getattr(self, "_error_dialog_shown", False):
-                        messagebox.showerror("Pipeline Error", err_text)
-                        self._error_dialog_shown = True
-                except Exception:
-                    pass
-                try:
-                    # Also schedule to ensure it wins over any queued 'Running' updates
-                    self.root.after(
-                        0,
-                        lambda: hasattr(self, "progress_message_var")
-                        and self.progress_message_var.set("Error"),
-                    )
-                    # Schedule explicit ERROR transition to drive status callbacks
-                    from .state import GUIState
-
-                    self.root.after(0, lambda: self.state_manager.transition_to(GUIState.ERROR))
-                except Exception:
-                    pass
-            except Exception:
-                pass
-
-            # Also schedule the standard UI error handler
-            def _show_err():
-                import os
-
-                if os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {"1", "true", "TRUE"}:
-                    return
-                try:
-                    if not getattr(self, "_error_dialog_shown", False):
-                        messagebox.showerror("Pipeline Error", str(e))
-                        self._error_dialog_shown = True
-                except Exception:
-                    logger.exception("Unable to display error dialog")
-
-            try:
-                self.root.after(0, _show_err)
-            except Exception:
-                _show_err()
-            # Ensure lifecycle_event is signaled promptly on error
-            try:
-                if lifecycle_event is not None:
-                    lifecycle_event.set()
-                else:
-                    self._signal_pipeline_finished()
-            except Exception:
-                pass
-
-        # Start pipeline using controller (tests may toggle _sync_cleanup themselves)
-        started = self.controller.start_pipeline(
-            pipeline_func, on_complete=on_complete, on_error=on_error
-        )
-        if started and is_gui_test_mode():
-            try:
-                event = getattr(self.controller, "lifecycle_event", None)
-                if event is not None and not event.wait(timeout=5.0):
-                    event.set()
-                try:
-                    for _ in range(5):
-                        self.root.update_idletasks()
-                        self.root.update()
-                except Exception:
-                    pass
-                if pipeline_failed:
-                    try:
-                        from .state import GUIState
-
-                        if not self.state_manager.is_state(GUIState.ERROR):
-                            self.state_manager.transition_to(GUIState.ERROR)
-                    except Exception:
-                        pass
-            except Exception:
-                pass
-
-    def _handle_pipeline_error(self, error: Exception) -> None:
-        """Log and surface pipeline errors to the user.
-
-        This method may be called from a worker thread, so GUI operations
-        must be marshaled to the main thread using root.after().
-        """
-
-        error_message = f"Pipeline failed: {type(error).__name__}: {error}\nA fatal error occurred. Please restart StableNew to continue."
-        self.log_message(f"✗ {error_message}", "ERROR")
-
-        # Marshal messagebox to main thread to avoid Tkinter threading violations
-        def show_error_dialog():
-            try:
-                if not getattr(self, "_error_dialog_shown", False):
-                    messagebox.showerror("Pipeline Error", error_message)
-                    self._error_dialog_shown = True
-            except tk.TclError:
-                logger.error("Unable to display error dialog", exc_info=True)
-
-        import os
-        import sys
-        import threading
-
-        def exit_app():
-            try:
-                self.root.destroy()
-            except Exception:
-                pass
-            try:
-                sys.exit(1)
-            except SystemExit:
-                pass
-
-        def force_exit_thread():
-            import time
-
-            time.sleep(1)
-            os._exit(1)
-
-        threading.Thread(target=force_exit_thread, daemon=True).start()
-
-        try:
-            self.root.after(0, show_error_dialog)
-            self.root.after(100, exit_app)
-        except Exception:
-            show_error_dialog()
-            exit_app()
-        # Progress message update is handled by state transition callback; redundant here.
-
-    def _create_video(self):
-        """Create video from output images"""
-        # Ask user to select output directory
-        output_dir = filedialog.askdirectory(title="Select output directory containing images")
-
-        if not output_dir:
-            return
-
-        output_path = Path(output_dir)
-
-        # Try to find upscaled images first, then img2img, then txt2img
-        for subdir in ["upscaled", "img2img", "txt2img"]:
-            image_dir = output_path / subdir
-            if image_dir.exists():
-                video_path = output_path / "video" / f"{subdir}_video.mp4"
-                video_path.parent.mkdir(exist_ok=True)
-
-                self._add_log_message(f"Creating video from {subdir}...")
-
-                if self.video_creator.create_video_from_directory(image_dir, video_path):
-                    self._add_log_message(f"✓ Video created: {video_path}")
-                    messagebox.showinfo("Success", f"Video created:{video_path}")
-                else:
-                    self._add_log_message(f"✗ Failed to create video from {subdir}")
-
-                return
-
-        messagebox.showerror("Error", "No image directories found")
-
-    def _refresh_models(self):
-        """Refresh the list of available SD models (main thread version)"""
-        if self.client is None:
-            messagebox.showerror("Error", "API client not connected")
-            return
-
-        try:
-            models = self.client.get_models()
-            model_names = [""] + [
-                model.get("title", model.get("model_name", "")) for model in models
-            ]
-
-            if hasattr(self, "config_panel"):
-                self.config_panel.set_model_options(model_names)
-
-            self.log_message(f"🔄 Loaded {len(models)} SD models")
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to refresh models: {e}")
-
-    def _refresh_models_async(self):
-        """Refresh the list of available SD models (thread-safe version)"""
-        from functools import partial
-
-        if self.client is None:
-            # Schedule error message on main thread
-            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
-            return
-
-        try:
-            # Perform API call in worker thread
-            models = self.client.get_models()
-            model_names = [""] + [
-                model.get("title", model.get("model_name", "")) for model in models
-            ]
-
-            # Marshal widget updates back to main thread
-            def update_widgets():
-                if hasattr(self, "model_combo"):
-                    self.model_combo["values"] = tuple(model_names)
-                if hasattr(self, "img2img_model_combo"):
-                    self.img2img_model_combo["values"] = tuple(model_names)
-                self._add_log_message(f"🔄 Loaded {len(models)} SD models")
-
-            self.root.after(0, update_widgets)
-
-            # Also update unified ConfigPanel if present using partial to capture value
-            if hasattr(self, "config_panel"):
-                self.root.after(0, partial(self.config_panel.set_model_options, list(model_names)))
-
-        except Exception as exc:
-            # Marshal error message back to main thread
-            # Capture exception in default argument to avoid closure issues
-            self.root.after(
-                0,
-                lambda err=exc: messagebox.showerror("Error", f"Failed to refresh models: {err}"),
-            )
-
-    def _refresh_hypernetworks_async(self):
-        """Refresh available hypernetworks (thread-safe)."""
-
-        if self.client is None:
-            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
-            return
-
-        def worker():
-            try:
-                entries = self.client.get_hypernetworks()
-                names = ["None"]
-                for entry in entries:
-                    name = ""
-                    if isinstance(entry, dict):
-                        name = entry.get("name") or entry.get("title") or ""
-                    else:
-                        name = str(entry)
-                    name = name.strip()
-                    if name and name not in names:
-                        names.append(name)
-
-                self.available_hypernetworks = names
-
-                def update_widgets():
-                    if hasattr(self, "config_panel"):
-                        try:
-                            self.config_panel.set_hypernetwork_options(names)
-                        except Exception:
-                            pass
-
-                self.root.after(0, update_widgets)
-                self._add_log_message(f"🔄 Loaded {len(names) - 1} hypernetwork(s)")
-            except Exception as exc:  # pragma: no cover - Tk loop dispatch
-                self.root.after(
-                    0,
-                    lambda err=exc: messagebox.showerror(
-                        "Error", f"Failed to refresh hypernetworks: {err}"
-                    ),
-                )
-
-        threading.Thread(target=worker, daemon=True).start()
-
-    def _refresh_vae_models(self):
-        """Refresh the list of available VAE models (main thread version)"""
-        if self.client is None:
-            messagebox.showerror("Error", "API client not connected")
-            return
-
-        try:
-            vae_models = self.client.get_vae_models()
-            vae_names = [""] + [vae.get("model_name", "") for vae in vae_models]
-
-            if hasattr(self, "config_panel"):
-                self.config_panel.set_vae_options(vae_names)
-
-            self.log_message(f"🔄 Loaded {len(vae_models)} VAE models")
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to refresh VAE models: {e}")
-
-    def _refresh_vae_models_async(self):
-        """Refresh the list of available VAE models (thread-safe version)"""
-        from functools import partial
-
-        if self.client is None:
-            # Schedule error message on main thread
-            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
-            return
-
-        try:
-            # Perform API call in worker thread
-            vae_models = self.client.get_vae_models()
-            vae_names_local = [""] + [vae.get("model_name", "") for vae in vae_models]
-
-            # Store in instance attribute
-            self.vae_names = list(vae_names_local)
-
-            # Marshal widget updates back to main thread
-            def update_widgets():
-                if hasattr(self, "vae_combo"):
-                    self.vae_combo["values"] = tuple(self.vae_names)
-                if hasattr(self, "img2img_vae_combo"):
-                    self.img2img_vae_combo["values"] = tuple(self.vae_names)
-                self._add_log_message(f"🔄 Loaded {len(vae_models)} VAE models")
-
-            self.root.after(0, update_widgets)
-
-            # Also update config panel if present using partial to capture value
-            if hasattr(self, "config_panel"):
-                self.root.after(0, partial(self.config_panel.set_vae_options, list(self.vae_names)))
-
-        except Exception as exc:
-            # Marshal error message back to main thread
-            # Capture exception in default argument to avoid closure issues
-            self.root.after(
-                0,
-                lambda err=exc: messagebox.showerror(
-                    "Error", f"Failed to refresh VAE models: {err}"
-                ),
-            )
-
-    def _refresh_samplers(self):
-        """Refresh the list of available samplers (main thread version)."""
-        if self.client is None:
-            messagebox.showerror("Error", "API client not connected")
-            return
-
-        try:
-            samplers = self.client.get_samplers()
-            sampler_names = sorted(
-                {s.get("name", "") for s in samplers if s.get("name")},
-                key=str.lower,
-            )
-            self.sampler_names = list(sampler_names)
-            if hasattr(self, "config_panel"):
-                self.config_panel.set_sampler_options(self.sampler_names)
-            if hasattr(self, "pipeline_controls_panel"):
-                panel = self.pipeline_controls_panel
-                if hasattr(panel, "set_sampler_options"):
-                    panel.set_sampler_options(self.sampler_names)
-                elif hasattr(panel, "refresh_dynamic_lists_from_api"):
-                    panel.refresh_dynamic_lists_from_api(self.client)
-            self._add_log_message(f"✅ Loaded {len(samplers)} samplers from API")
-        except Exception as exc:
-            messagebox.showerror("Error", f"Failed to refresh samplers: {exc}")
-
-    def _refresh_samplers_async(self):
-        """Refresh the list of available samplers (thread-safe version)."""
-        if self.client is None:
-            # Schedule error message on main thread
-            self.root.after(
-                0,
-                lambda: messagebox.showerror("Error", "API client not connected"),
-            )
-            return
-
-        def worker():
-            try:
-                samplers = self.client.get_samplers()
-                names = sorted(
-                    {s.get("name", "") for s in samplers if s.get("name")},
-                    key=str.lower,
-                )
-                # Keep a local cache if needed later
-                self.sampler_names = list(names)
-
-                def update_widgets():
-                    self._add_log_message(f"✅ Loaded {len(samplers)} samplers from API")
-                    if hasattr(self, "config_panel"):
-                        self.config_panel.set_sampler_options(self.sampler_names)
-                    if hasattr(self, "pipeline_controls_panel"):
-                        panel = self.pipeline_controls_panel
-                        if hasattr(panel, "set_sampler_options"):
-                            panel.set_sampler_options(self.sampler_names)
-                        elif hasattr(panel, "refresh_dynamic_lists_from_api"):
-                            panel.refresh_dynamic_lists_from_api(self.client)
-
-                self.root.after(0, update_widgets)
-            except Exception as exc:
-                self.root.after(
-                    0,
-                    lambda err=exc: messagebox.showerror(
-                        "Error", f"Failed to refresh samplers: {err}"
-                    ),
-                )
-
-        threading.Thread(target=worker, daemon=True).start()
-
-    def _refresh_upscalers(self):
-        """Refresh the list of available upscalers (main thread version)"""
-        if self.client is None:
-            messagebox.showerror("Error", "API client not connected")
-            return
-
-        try:
-            upscalers = self.client.get_upscalers()
-            upscaler_names = sorted(
-                {u.get("name", "") for u in upscalers if u.get("name")},
-                key=str.lower,
-            )
-            self.upscaler_names = list(upscaler_names)
-            if hasattr(self, "config_panel"):
-                self.config_panel.set_upscaler_options(self.upscaler_names)
-            if hasattr(self, "pipeline_controls_panel"):
-                panel = self.pipeline_controls_panel
-                if hasattr(panel, "set_upscaler_options"):
-                    panel.set_upscaler_options(self.upscaler_names)
-                elif hasattr(panel, "refresh_dynamic_lists_from_api"):
-                    panel.refresh_dynamic_lists_from_api(self.client)
-            if hasattr(self, "upscaler_combo"):
-                self.upscaler_combo["values"] = tuple(self.upscaler_names)
-            self._add_log_message(f"✅ Loaded {len(upscalers)} upscalers from API")
-        except Exception as exc:
-            messagebox.showerror("Error", f"Failed to refresh upscalers: {exc}")
-
-    def _refresh_upscalers_async(self):
-        """Refresh the list of available upscalers (thread-safe version)"""
-        if self.client is None:
-            # Schedule error message on main thread
-            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
-            return
-
-        try:
-            upscalers = self.client.get_upscalers()
-            upscaler_names_local = sorted(
-                {u.get("name", "") for u in upscalers if u.get("name")},
-                key=str.lower,
-            )
-            self.upscaler_names = list(upscaler_names_local)
-
-            def update_widgets():
-                if hasattr(self, "upscaler_combo"):
-                    self.upscaler_combo["values"] = tuple(self.upscaler_names)
-                self._add_log_message(f"✅ Loaded {len(upscalers)} upscalers from API")
-                if hasattr(self, "config_panel"):
-                    self.config_panel.set_upscaler_options(self.upscaler_names)
-                if hasattr(self, "pipeline_controls_panel"):
-                    panel = self.pipeline_controls_panel
-                    if hasattr(panel, "set_upscaler_options"):
-                        panel.set_upscaler_options(self.upscaler_names)
-                    elif hasattr(panel, "refresh_dynamic_lists_from_api"):
-                        panel.refresh_dynamic_lists_from_api(self.client)
-
-            self.root.after(0, update_widgets)
-
-        except Exception as exc:
-            # Marshal error message back to main thread
-            # Capture exception in default argument to avoid closure issues
-            self.root.after(
-                0,
-                lambda err=exc: messagebox.showerror(
-                    "Error", f"Failed to refresh upscalers: {err}"
-                ),
-            )
-
-    def _refresh_schedulers(self):
-        """Refresh the list of available schedulers (main thread version)"""
-        if not self.client:
-            messagebox.showerror("Error", "API client not connected")
-            return
-
-        try:
-            schedulers = self.client.get_schedulers()
-
-            if hasattr(self, "config_panel"):
-                self.config_panel.set_scheduler_options(schedulers)
-
-            self.log_message(f"🔄 Loaded {len(schedulers)} schedulers")
-        except Exception as e:
-            messagebox.showerror("Error", f"Failed to refresh schedulers: {e}")
-
-    def _refresh_schedulers_async(self):
-        """Refresh the list of available schedulers (thread-safe version)"""
-        from functools import partial
-
-        if not self.client:
-            # Schedule error message on main thread
-            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
-            return
-
-        try:
-            # Perform API call in worker thread
-            schedulers = self.client.get_schedulers()
-
-            # Store in instance attribute
-            self.schedulers = list(schedulers)
-
-            # Marshal widget updates back to main thread using partial
-            def update_widgets():
-                if hasattr(self, "scheduler_combo"):
-                    self.scheduler_combo["values"] = tuple(self.schedulers)
-                if hasattr(self, "img2img_scheduler_combo"):
-                    self.img2img_scheduler_combo["values"] = tuple(self.schedulers)
-                self._add_log_message(f"🔄 Loaded {len(self.schedulers)} schedulers")
-
-            self.root.after(0, update_widgets)
-
-            # Also update config panel if present using partial to capture value
-            if hasattr(self, "config_panel"):
-                self.root.after(
-                    0, partial(self.config_panel.set_scheduler_options, list(self.schedulers))
-                )
-
-        except Exception as exc:
-            # Marshal error message back to main thread
-            # Capture exception in default argument to avoid closure issues
-            self.root.after(
-                0,
-                lambda err=exc: messagebox.showerror(
-                    "Error", f"Failed to refresh schedulers: {err}"
-                ),
-            )
-
-    def _on_hires_toggle(self):
-        """Handle hires.fix enable/disable toggle"""
-        # This method can be used to enable/disable hires.fix related controls
-        # For now, just log the change
-        enabled = self.txt2img_vars.get("enable_hr", tk.BooleanVar()).get()
-        self.log_message(f"📏 Hires.fix {'enabled' if enabled else 'disabled'}")
-
-    def _randomize_seed(self, var_dict_name):
-        """Generate a random seed for the specified variable dictionary"""
-        import random
-
-        random_seed = random.randint(1, 2147483647)  # Max int32 value
-        var_dict = getattr(self, f"{var_dict_name}_vars", {})
-        if "seed" in var_dict:
-            var_dict["seed"].set(random_seed)
-            self.log_message(f"🎲 Random seed generated: {random_seed}")
-
-    def _randomize_txt2img_seed(self):
-        """Generate random seed for txt2img"""
-        self._randomize_seed("txt2img")
-
-    def _randomize_img2img_seed(self):
-        """Generate random seed for img2img"""
-        self._randomize_seed("img2img")
-
-
-# Public alias for entrypoint wiring to the V2 GUI.
-ENTRYPOINT_GUI_CLASS = StableNewGUI
+ENTRYPOINT_GUI_CLASS = MainWindowV2

```

---

## Patch: add `archive/gui_v1/main_window.py` with archived legacy implementation

```diff
--- /dev/null
+++ b/archive/gui_v1/main_window.py
@@ -0,0 +1,7388 @@
+# Archived legacy GUI shell (StableNewGUI)
+# This file is no longer used by Phase-1 or later.
+# It is retained only for reference during cleanup.
+
+from __future__ import annotations
+
+import json
+import logging
+import os
+import re
+import subprocess
+import sys
+import threading
+import time
+import tkinter as tk
+from copy import deepcopy
+from enum import Enum, auto
+from pathlib import Path
+from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
+from typing import Any, Callable
+
+from src.api.client import SDWebUIClient, find_webui_api_port, validate_webui_health
+from src.controller.pipeline_controller import PipelineController
+from src.controller.learning_execution_controller import LearningExecutionController
+from src.gui.advanced_prompt_editor import AdvancedPromptEditor
+from src.gui.api_status_panel import APIStatusPanel
+from src.gui.config_panel import ConfigPanel
+from src.gui.enhanced_slider import EnhancedSlider
+from src.gui.engine_settings_dialog import EngineSettingsDialog
+from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
+from src.gui.log_panel import LogPanel, TkinterLogHandler
+from src.gui.pipeline_controls_panel import PipelineControlsPanel
+from src.gui.prompt_pack_panel import PromptPackPanel
+from src.gui.panels_v2 import PipelinePanelV2, PreviewPanelV2, RandomizerPanelV2, SidebarPanelV2, StatusBarV2
+from src.gui.app_layout_v2 import AppLayoutV2
+from src.gui_v2.adapters.pipeline_adapter_v2 import build_effective_config
+from src.gui_v2.adapters.randomizer_adapter_v2 import compute_variant_count
+from src.gui_v2.adapters.status_adapter_v2 import StatusAdapterV2
+from src.controller.settings_suggestion_controller import SettingsSuggestionController
+from src.ai.settings_generator_contract import SuggestionIntent
+from src.gui.scrolling import enable_mousewheel, make_scrollable
+from src.gui.state import GUIState, StateManager
+from src.gui.theme_v2 import Theme
+from src.gui.main_window_v2 import MainWindowV2
+
+# V2 GUI alias for entrypoint wiring
+StableNewGUI = MainWindowV2
+ENTRYPOINT_GUI_CLASS = StableNewGUI
+from src.gui.tooltip import Tooltip
+from src.api.webui_process_manager import WebUIProcessManager
+from src.pipeline.executor import Pipeline
+from src.services.config_service import ConfigService
+from src.utils import StructuredLogger
+from src.utils.aesthetic_detection import detect_aesthetic_extension
+from src.utils.config import ConfigManager
+from src.utils.file_io import get_prompt_packs, read_prompt_pack
+from src.utils.preferences import PreferencesManager
+from src.utils.randomizer import (
+    PromptRandomizer,
+    PromptVariant,
+    apply_variant_to_config,
+    build_variant_plan,
+)
+from src.utils.state import CancellationError
+from src.utils.webui_discovery import WebUIDiscovery
+from src.utils.webui_launcher import launch_webui_safely
+from src.controller.webui_connection_controller import WebUIConnectionState
+from src.config.app_config import (
+    learning_enabled_default,
+    get_learning_enabled,
+    is_queue_execution_enabled,
+    set_queue_execution_enabled,
+)
+
+
+# Config source state machine
+class ConfigSource(Enum):
+    PACK = auto()
+    PRESET = auto()
+    GLOBAL_LOCK = auto()
+
+
+class ConfigContext:
+    def __init__(
+        self,
+        source=ConfigSource.PACK,
+        editor_cfg=None,
+        locked_cfg=None,
+        active_preset=None,
+        active_list=None,
+    ):
+        self.source = source
+        self.editor_cfg = editor_cfg or {}
+        self.locked_cfg = locked_cfg
+        self.active_preset = active_preset
+        self.active_list = active_list
+
+
+logger = logging.getLogger(__name__)
+
+_FORCE_GUI_TEST_MODE: bool | None = None
+
+
+def enable_gui_test_mode() -> None:
+    """Explicit hook for tests to force GUI test behavior."""
+
+    global _FORCE_GUI_TEST_MODE
+    _FORCE_GUI_TEST_MODE = True
+
+
+def disable_gui_test_mode() -> None:
+    """Forcefully disable GUI test mode regardless of environment."""
+
+    global _FORCE_GUI_TEST_MODE
+    _FORCE_GUI_TEST_MODE = False
+
+
+def reset_gui_test_mode() -> None:
+    """Return GUI test mode detection to the environment-based default."""
+
+    global _FORCE_GUI_TEST_MODE
+    _FORCE_GUI_TEST_MODE = None
+
+
+def is_gui_test_mode() -> bool:
+    """Return True when running under automated GUI test harness."""
+
+    if _FORCE_GUI_TEST_MODE is not None:
+        return _FORCE_GUI_TEST_MODE
+    return os.environ.get("STABLENEW_GUI_TEST_MODE") == "1"
+
+
+def sanitize_prompt(text: str) -> str:
+    """Strip leftover [[slot]] / __wildcard__ tokens before sending to WebUI."""
+    if not text:
+        return text
+    cleaned = re.sub(r"\[\[[^\]]+\]\]", "", text)
+    cleaned = re.sub(r"__\w+__", "", cleaned)
+    return " ".join(cleaned.split())
+
+class StableNewGUI:
+    def __init__(
+        self,
+        root: tk.Tk | None = None,
+        config_manager: ConfigManager | None = None,
+        preferences: PreferencesManager | None = None,
+        state_manager: StateManager | None = None,
+        controller: PipelineController | None = None,
+        webui_discovery: WebUIDiscovery | None = None,
+        webui_process_manager: WebUIProcessManager | None = None,
+        title: str = "StableNew",
+        geometry: str = "1360x900",
+        default_preset_name: str | None = None,
+    ) -> None:
+        self.config_manager = config_manager or ConfigManager()
+        self.preferences_manager = preferences or PreferencesManager()
+        self.state_manager = state_manager or StateManager(initial_state=GUIState.IDLE)
+        self.layout_version = "v2"
+        self._run_button_validation_locked = False
+        self._last_txt2img_validation_result = None
+        self.api_connected = False
+        try:
+            self._learning_enabled_flag = get_learning_enabled()
+        except Exception:
+            self._learning_enabled_flag = learning_enabled_default()
+
+        # Single StructuredLogger instance owned by the GUI and shared with the controller.
+        self.structured_logger = StructuredLogger()
+
+        self.controller = controller or PipelineController(self.state_manager)
+        try:
+            self.controller.structured_logger = self.structured_logger
+        except Exception:
+            setattr(self.controller, "structured_logger", self.structured_logger)
+        self.job_history_service = None
+        getter = getattr(self.controller, "get_job_history_service", None)
+        if callable(getter):
+            try:
+                self.job_history_service = getter()
+            except Exception:
+                self.job_history_service = None
+        self.settings_suggestion_controller = SettingsSuggestionController()
+        self.webui = webui_discovery or WebUIDiscovery()
+        self.webui_process_manager = webui_process_manager
+        self._refreshing_config = False
+        self.learning_execution_controller = LearningExecutionController()
+        try:
+            self.controller.set_learning_enabled(self.learning_enabled_var.get())
+        except Exception:
+            pass
+        try:
+            self.learning_execution_controller.set_learning_enabled(self.learning_enabled_var.get())
+        except Exception:
+            pass
+        if root is not None:
+            self.root = root
+        else:
+            self.root = tk.Tk()
+        self.learning_enabled_var = tk.BooleanVar(master=self.root, value=self._learning_enabled_flag)
+        self.root.title(title)
+        self.root.geometry(geometry)
+        self.window_min_size = (1200, 780)
+        self.root.minsize(*self.window_min_size)
+        self._build_menu_bar()
+
+        # Initialize theme
+        self.theme = Theme()
+        self.theme.apply_root(self.root)
+
+        # Initialize ttk style and theme colors
+        self.style = ttk.Style()
+        self.theme.apply_ttk_styles(self.style)
+
+        # --- ConfigService and ConfigContext wiring ---
+        packs_dir = Path("packs")
+        presets_dir = Path("presets")
+        lists_dir = Path("lists")
+        self.config_service = ConfigService(packs_dir, presets_dir, lists_dir)
+        self.ctx = ConfigContext()
+        self.config_source_banner = None
+        self.current_selected_packs = []
+        self.is_locked = False
+        self.previous_source = None
+        self.previous_banner_text = "Using: Global Config"
+        self.current_preset_name = None
+
+        # Initialize API-related variables
+        self.api_url_var = tk.StringVar(value="http://127.0.0.1:7860")
+        self.preset_var = tk.StringVar(value="default")
+        self._wrappable_labels: list[tk.Widget] = []
+        self.scrollable_sections: dict[str, dict[str, tk.Widget | None]] = {}
+        self._log_min_lines = 7
+        self._image_warning_threshold = 250
+        self.upscaler_names: list[str] = []
+        self.sampler_names: list[str] = []
+
+        # Initialize aesthetic/randomization defaults before building UI
+        self.aesthetic_script_available = False
+        self.aesthetic_extension_root: Path | None = None
+        self.aesthetic_embeddings: list[str] = ["None"]
+        self.aesthetic_embedding_var = tk.StringVar(value="None")
+        self.aesthetic_status_var = tk.StringVar(value="Aesthetic extension not detected")
+        self.aesthetic_widgets: dict[str, list[tk.Widget]] = {
+            "all": [],
+            "script": [],
+            "prompt": [],
+        }
+
+        # Stage toggles used by multiple panels
+        self.txt2img_enabled = tk.BooleanVar(value=True)
+        self.img2img_enabled = tk.BooleanVar(value=True)
+        self.adetailer_enabled = tk.BooleanVar(value=False)
+        self.upscale_enabled = tk.BooleanVar(value=True)
+        self.video_enabled = tk.BooleanVar(value=False)
+        self._config_dirty = False
+        self._config_panel_prefs_bound = False
+        self._preferences_ready = False
+        self._new_features_dialog_shown = False
+
+        # Initialize progress-related attributes
+        self._progress_eta_default = "ETA: --:--"
+        self._progress_idle_message = "Ready"
+        self._last_randomizer_plan_result = None
+        self._randomizer_variant_update_job: int | None = None
+        self._ai_settings_enabled = bool(os.environ.get("ENABLE_AI_SETTINGS_GENERATOR"))
+
+        # Load preferences before building UI
+        default_config = self.config_manager.get_default_config()
+        try:
+            self.preferences = self.preferences_manager.load_preferences(default_config)
+        except Exception as exc:
+            logger.error(
+                "Failed to load preferences; falling back to defaults: %s", exc, exc_info=True
+            )
+            self.preferences = self.preferences_manager.default_preferences(default_config)
+            self._handle_preferences_load_failure(exc)
+
+        # Build the user interface
+        if self.layout_version == "v2":
+            self._build_ui_v2()
+        else:
+            self._build_ui()
+        self._wire_progress_callbacks()
+        try:
+            self.root.bind("<Configure>", self._on_root_resize, add="+")
+        except Exception:
+            pass
+        self._reset_config_dirty_state()
+        self._preferences_ready = True
+
+        # Initialize summary variables for live config display
+        self.txt2img_summary_var = tk.StringVar(value="")
+        self.img2img_summary_var = tk.StringVar(value="")
+        self.upscale_summary_var = tk.StringVar(value="")
+        self._maybe_show_new_features_dialog()
+
+    def _apply_webui_status(self, status) -> None:
+        # Update any labels/combos based on discovered status.
+        # (Implement specific UI updates in your controls panel)
+        try:
+            self.pipeline_controls_panel.on_webui_status(status)
+        except Exception:
+            logger.exception("Failed to apply WebUI status")
+
+    def _apply_webui_error(self, e: Exception) -> None:
+        logger.warning("WebUI error: %s", e)
+        # Optionally update UI to reflect disconnected state
+        try:
+            self.pipeline_controls_panel.on_webui_error(e)
+        except Exception:
+            logger.exception("Failed to apply WebUI error")
+
+    def _update_config_source_banner(self, text: str) -> None:
+        """Update the config source banner with the given text."""
+        self.config_source_banner.config(text=text)
+
+    def _effective_cfg_for_pack(self, pack: str) -> dict[str, Any]:
+        """Get the effective config for a pack based on current ctx.source."""
+        if self.ctx.source is ConfigSource.GLOBAL_LOCK and self.ctx.locked_cfg is not None:
+            return deepcopy(self.ctx.locked_cfg)
+        if self.ctx.source is ConfigSource.PRESET:
+            return deepcopy(self.ctx.editor_cfg)
+        cfg = self.config_service.load_pack_config(pack)
+        return cfg if cfg else deepcopy(self.ctx.editor_cfg)  # fallback to editor defaults
+
+    def _preview_payload_dry_run(self) -> None:
+        """
+        Dry-run the selected packs and report how many prompts/variants would be produced.
+        """
+        selected_packs = self._get_selected_packs()
+        if not selected_packs:
+            self.log_message("No prompt packs selected for dry run", "WARNING")
+            return
+        selected_copy = list(selected_packs)
+
+        def worker():
+            config_snapshot = self._get_config_snapshot()
+            rand_cfg = deepcopy(config_snapshot.get("randomization") or {})
+
+            total_prompts = 0
+            total_variants = 0
+            sample_variants: list[PromptVariant] = []
+            pack_summaries: list[str] = []
+
+            for pack_path in selected_copy:
+                prompts = read_prompt_pack(pack_path)
+                if not prompts:
+                    self.log_message(
+                        f"[DRY RUN] No prompts found in {pack_path.name}", "WARNING"
+                    )
+                    continue
+
+                total_prompts += len(prompts)
+                pack_variants, pack_samples = self._estimate_pack_variants(
+                    prompts, deepcopy(rand_cfg)
+                )
+                total_variants += pack_variants
+                pack_summaries.append(
+                    f"[DRY RUN] Pack {pack_path.name}: {len(prompts)} prompt(s) -> {pack_variants} variant(s)"
+                )
+                for variant in pack_samples:
+                    if len(sample_variants) >= 10:
+                        break
+                    sample_variants.append(variant)
+
+            images_per_prompt = self._safe_int_from_var(self.images_per_prompt_var, 1)
+            loop_multiplier = self._safe_int_from_var(self.loop_count_var, 1)
+            predicted_images = total_variants * images_per_prompt * loop_multiplier
+
+            summary = (
+                f"[DRY RUN] {len(selected_copy)} pack(s) • "
+                f"{total_prompts} prompt(s) • "
+                f"{total_variants} variant(s) × {images_per_prompt} img/prompt × loops={loop_multiplier} "
+                f"→ ≈ {predicted_images} image(s)"
+            )
+            self.log_message(summary, "INFO")
+
+            for line in pack_summaries:
+                self.log_message(line, "INFO")
+
+            for idx, variant in enumerate(sample_variants[:5], start=1):
+                label_part = f" ({variant.label})" if variant.label else ""
+                preview_text = (variant.text or "")[:200]
+                self.log_message(f"[DRY RUN] ex {idx}{label_part}: {preview_text}", "INFO")
+
+            self._maybe_warn_large_output(predicted_images, "dry run preview")
+
+        threading.Thread(target=worker, daemon=True).start()
+
+    def _safe_int_from_var(self, var: tk.Variable | None, default: int = 1) -> int:
+        try:
+            value = int(var.get()) if var is not None else default
+        except Exception:
+            value = default
+        return value if value > 0 else default
+
+    def _estimate_pack_variants(
+        self, prompts: list[dict[str, str]], rand_cfg: dict[str, Any]
+    ) -> tuple[int, list[PromptVariant]]:
+        total = 0
+        samples: list[PromptVariant] = []
+        if not prompts:
+            return 0, samples
+
+        simulator: PromptRandomizer | None = None
+        rand_enabled = bool(rand_cfg.get("enabled")) if isinstance(rand_cfg, dict) else False
+        if rand_enabled:
+            try:
+                simulator = PromptRandomizer(deepcopy(rand_cfg))
+            except Exception:
+                simulator = None
+
+        for prompt_data in prompts:
+            prompt_text = prompt_data.get("positive", "") or ""
+            if simulator:
+                variants = simulator.generate(prompt_text)
+                if not variants:
+                    variants = [PromptVariant(text=prompt_text, label=None)]
+            else:
+                variants = [PromptVariant(text=prompt_text, label=None)]
+
+            total += len(variants)
+            if len(samples) < 10:
+                samples.extend(variants[:2])
+
+        return total, samples
+
+    def _maybe_warn_large_output(self, count: int, context: str) -> bool:
+        """Warn about very large runs while avoiding modal dialogs off the Tk thread."""
+
+        threshold = getattr(self, "_image_warning_threshold", 0) or 0
+        if not threshold or count < threshold:
+            return True
+
+        self.log_message(
+            f"⚠️ Expected to generate approximately {count} image(s) for {context}. "
+            "Adjust Randomization or Images/Prompt if this is unintended.",
+            "WARNING",
+        )
+
+        suppress = is_gui_test_mode() or os.environ.get("STABLENEW_NO_DIALOGS") in {
+            "1",
+            "true",
+            "TRUE",
+        }
+        if suppress:
+            logger.warning(
+                "Large run estimate (%d images for %s) but dialogs suppressed; proceeding automatically.",
+                count,
+                context,
+            )
+            return True
+
+        if threading.current_thread() is not threading.main_thread():
+            logger.warning(
+                "Large run estimate (%d images for %s) but warning invoked off Tk thread; "
+                "skipping dialog to avoid deadlock.",
+                count,
+                context,
+            )
+            return True
+
+        message = (
+            f"This run may generate approximately {count} image(s) for {context}. "
+            "This could take a long time. Do you want to continue?"
+        )
+        try:
+            return messagebox.askyesno("Large Run Warning", message)
+        except Exception:
+            logger.exception("Failed to display large-run warning dialog")
+            return True
+
+
+    # -------- mediator selection -> config refresh --------
+    def _on_pack_selection_changed_mediator(self, packs: list[str]) -> None:
+        """
+        Mediator callback from PromptPackPanel; always UI thread.
+        We keep this handler strictly non-blocking and UI-only.
+        """
+        try:
+            self.current_selected_packs = packs
+            count = len(packs)
+            if count == 0:
+                logger.info("📦 No pack selected")
+            else:
+                logger.info("📦 Selected pack: %s", packs[0] if count == 1 else f"{count} packs")
+            # Update banner instead of refreshing config
+            if packs:
+                if len(packs) == 1:
+                    text = "Using: Pack Config"
+                else:
+                    text = "Using: Multi-Pack Config"
+            else:
+                text = "Using: Global Config"
+            self._update_config_source_banner(text)
+        except Exception:
+            logger.exception("Mediator selection handler failed")
+
+    def _refresh_config(self, packs: list[str]) -> None:
+        """
+        Load pack config and apply to controls. UI-thread only. Non-reentrant.
+        """
+        if self._refreshing_config:
+            logger.debug("[DIAG] _refresh_config: re-entry detected; skipping")
+            return
+
+        self._refreshing_config = True
+        try:
+            # We currently apply config for first selected pack
+            pack = packs[0]
+            cfg = self.config_manager.load_pack_config(pack)  # disk read is fine; cheap
+            logger.debug("Loaded pack config: %s", pack)
+
+            # Push config to controls panel (must be UI-only logic)
+            self.pipeline_controls_panel.apply_config(cfg)
+            logger.info("Loaded config for pack: %s", pack)
+
+        except Exception as e:
+            logger.exception("Failed to refresh config: %s", e)
+            self._safe_messagebox("error", "Config Error", f"{type(e).__name__}: {e}")
+        finally:
+            self._refreshing_config = False
+
+    # -------- run pipeline --------
+    def _on_run_clicked(self) -> None:
+        """Handler for RUN button; delegates to the canonical pipeline starter."""
+        try:
+            try:
+                selected = self.prompt_pack_panel.get_selected_packs()
+            except Exception:
+                selected = []
+            if not selected:
+                self._safe_messagebox(
+                    "warning", "No Pack Selected", "Please select a prompt pack first."
+                )
+                return
+
+            packs_str = selected[0] if len(selected) == 1 else f"{len(selected)} packs"
+            logger.info("▶️ Starting pipeline execution for %s", packs_str)
+
+            # Delegate to the canonical runner that wires controller callbacks.
+            self._run_full_pipeline()
+
+        except Exception as e:
+            logger.exception("Run click failed: %s", e)
+            self._safe_messagebox("error", "Run Failed", f"{type(e).__name__}: {e}")
+
+    def _on_cancel_clicked(self) -> None:
+        """Handler for STOP/CANCEL button."""
+        try:
+            stopping = self.controller.stop_pipeline()
+        except Exception as exc:
+            self.log_message(f"⏹️ Stop failed: {exc}", "ERROR")
+            return
+
+        if stopping:
+            self.log_message("⏹️ Stop requested - cancelling pipeline...", "WARNING")
+        else:
+            self.log_message("⏹️ No pipeline running", "INFO")
+    # -------- utilities --------
+    def on_error(self, error: Exception | str) -> None:
+        """Expose a public error handler for legacy controller/test hooks."""
+        if isinstance(error, Exception):
+            message = f"{type(error).__name__}: {error}"
+        else:
+            message = str(error) if error else "Pipeline error"
+
+        try:
+            self.state_manager.transition_to(GUIState.ERROR)
+        except Exception:
+            logger.exception("Failed to transition GUI state to ERROR after pipeline error")
+
+        self._signal_pipeline_finished()
+
+        def handle_error() -> None:
+            self._handle_pipeline_error_main_thread(message, error)
+
+        try:
+            self.root.after(0, handle_error)
+        except Exception:
+            handle_error()
+
+    def _handle_pipeline_error_main_thread(self, message: str, error: Exception | str) -> None:
+        """Perform UI-safe pipeline error handling on the Tk thread."""
+
+        self.log_message(f"? Pipeline error: {message}", "ERROR")
+
+        suppress_dialog = is_gui_test_mode() or os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {
+            "1",
+            "true",
+            "TRUE",
+        }
+        if not suppress_dialog:
+            self._safe_messagebox("error", "Pipeline Error", message)
+
+    # Duplicate _setup_theme and other duplicate/unused methods removed for linter/ruff compliance
+
+    def _launch_webui(self):
+        """Request WebUI startup via the configured process manager (non-blocking)."""
+        if os.environ.get("STABLENEW_NO_WEBUI", "").lower() in {"1", "true", "yes"}:
+            logger.info("Auto-launch of WebUI disabled by STABLENEW_NO_WEBUI")
+            return
+
+        def discovery_and_launch():
+            def safe_after(delay_ms: int, func):
+                try:
+                    self.root.after(delay_ms, func)
+                except RuntimeError:
+                    logger.debug("Tk not ready for after() in discovery_and_launch", exc_info=True)
+
+            manager = getattr(self, "webui_process_manager", None)
+            if manager is None:
+                logger.info("No WebUI process manager configured; skipping autostart")
+                safe_after(0, self._check_api_connection)
+                return
+
+            try:
+                manager.start()
+                self.log_message("?? Launching Stable Diffusion WebUI via process manager...", "INFO")
+            except Exception as exc:
+                self.log_message(f"? WebUI launch failed: {exc}", "ERROR")
+                return
+
+            safe_after(1000, self._check_api_connection)
+            safe_after(10_000, self._check_api_connection)
+            safe_after(13_000, self._check_api_connection)
+
+            def final_notice():
+                if not getattr(self, "api_connected", False):
+                    self.log_message(
+                        "? Unable to connect to WebUI after auto-start attempts. Please start WebUI manually.",
+                        "ERROR",
+                    )
+                    suppress = is_gui_test_mode() or os.environ.get("STABLENEW_NO_DIALOGS") in {
+                        "1",
+                        "true",
+                        "TRUE",
+                    }
+                    if not suppress:
+                        try:
+                            messagebox.showerror(
+                                "WebUI Connection",
+                                "Unable to connect to Stable Diffusion WebUI after auto-start attempts.\n"
+                                "Please start WebUI manually and click 'Check API'.",
+                            )
+                        except Exception:
+                            logger.debug("Failed to display WebUI connection error dialog", exc_info=True)
+
+            safe_after(14_500, final_notice)
+
+        try:
+            self.root.after(50, discovery_and_launch)
+        except Exception:
+            logger.exception("Failed to schedule WebUI discovery/launch")
+
+    def _ensure_default_preset(self):
+        """Ensure default preset exists and load it if set as startup default"""
+        if "default" not in self.config_manager.list_presets():
+            default_config = self.config_manager.get_default_config()
+            self.config_manager.save_preset("default", default_config)
+
+        # Check if a default preset is configured for startup
+        default_preset_name = self.config_manager.get_default_preset()
+        if default_preset_name:
+            logger.info(f"Loading default preset on startup: {default_preset_name}")
+            preset_config = self.config_manager.load_preset(default_preset_name)
+            if preset_config:
+                self.current_preset = default_preset_name
+                self.current_config = preset_config
+                # preset_var will be set in __init__ after this call
+                self.preferences["preset"] = default_preset_name
+            else:
+                logger.warning(f"Failed to load default preset '{default_preset_name}'")
+
+    def _build_ui_v2(self) -> None:
+        """Explicit V2 entrypoint (currently delegates to the unified builder)."""
+        self._build_ui()
+
+    def _build_ui(self):
+        """Build the modern user interface"""
+        # Create main container with minimal padding for space efficiency
+        main_frame = ttk.Frame(self.root, style="Dark.TFrame")
+        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
+
+        # Config source banner at the top
+        self.config_source_banner = ttk.Label(
+            main_frame, text="Using: Pack Config", style="Dark.TLabel"
+        )
+        self.config_source_banner.pack(anchor=tk.W, padx=5, pady=(0, 5))
+
+        # Action bar for explicit config loading
+        self._build_action_bar(main_frame)
+
+        # Main content + log splitter so the bottom panel stays visible
+        vertical_split = ttk.Panedwindow(main_frame, orient=tk.VERTICAL, style="Dark.TPanedwindow")
+        self._vertical_split = vertical_split
+        vertical_split.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
+
+        # Main content frame - optimized layout
+        content_frame = ttk.Frame(vertical_split, style="Dark.TFrame")
+
+        # Bottom shell reserved for logs/status; create early so AppLayoutV2 can hook status bar
+        bottom_shell = ttk.Frame(vertical_split, style="Dark.TFrame")
+        self._bottom_pane = bottom_shell
+        self.bottom_zone = bottom_shell
+
+        vertical_split.add(content_frame, weight=5)
+        vertical_split.add(bottom_shell, weight=2)
+
+        # Configure grid for better space utilization
+        content_frame.columnconfigure(0, weight=1, minsize=280)
+        content_frame.columnconfigure(1, weight=3)
+        content_frame.columnconfigure(2, weight=1, minsize=260)
+        content_frame.rowconfigure(0, weight=1)
+
+        # Define layout zones; AppLayoutV2 owns panel composition
+        self.left_zone = ttk.Frame(content_frame, style="Dark.TFrame")
+        self.left_zone.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
+
+        self.center_zone = ttk.Frame(content_frame, style="Dark.TFrame")
+        self.center_zone.grid(row=0, column=1, sticky=tk.NSEW)
+        self.center_zone.columnconfigure(0, weight=1)
+
+        self.center_stack = ttk.Frame(self.center_zone, style="Dark.TFrame")
+        self.center_stack.pack(fill=tk.BOTH, expand=True)
+
+        self.right_zone = ttk.Frame(content_frame, style="Dark.TFrame")
+        self.right_zone.grid(row=0, column=2, sticky=tk.NSEW, padx=(5, 0))
+
+        # Let AppLayoutV2 create and attach V2 panels and the run button alias
+        self._layout_v2 = AppLayoutV2(self, theme=self.theme)
+        self._layout_v2.build_layout(getattr(self, "root", None))
+        try:
+            # Ensure status bar created by AppLayout can be re-packed after bottom panel scaffolding
+            if hasattr(self, "status_bar_v2"):
+                self.status_bar_v2.pack_forget()
+        except Exception:
+            pass
+
+        self._wire_pipeline_command_bar()
+
+        self._build_bottom_panel(bottom_shell)
+        if self._layout_v2:
+            self._layout_v2.attach_run_button(getattr(self, "run_pipeline_btn", None))
+
+        # Populate panels now that layout is composed
+        if getattr(self, "sidebar_panel_v2", None) is not None:
+            self._build_prompt_pack_panel(self.sidebar_panel_v2.body)
+        if getattr(self, "pipeline_panel_v2", None) is not None:
+            self.pipeline_panel_v2.set_txt2img_change_callback(self._on_pipeline_txt2img_updated)
+            self._build_config_pipeline_panel(self.pipeline_panel_v2.body)
+        if getattr(self, "randomizer_panel_v2", None) is not None:
+            self.randomizer_panel_v2.set_change_callback(self._on_randomizer_panel_changed)
+        self._initialize_pipeline_panel_config()
+        self._initialize_randomizer_panel_config()
+
+        # Defer all heavy UI state initialization until after Tk mainloop starts
+        try:
+            self.root.after(0, self._initialize_ui_state_async)
+        except Exception as exc:
+            logger.warning("Failed to schedule UI state init: %s", exc)
+
+        # Setup state callbacks
+        self._setup_state_callbacks()
+
+        # Attempt to auto-launch WebUI / discover API on startup via process manager
+        try:
+            self._launch_webui()
+        except Exception:
+            logger.exception("Failed to launch WebUI")
+
+        try:
+            self.root.after(1500, self._check_api_connection)
+        except Exception:
+            logger.warning("Unable to schedule API connection check")
+
+    def _wire_pipeline_command_bar(self) -> None:
+        """Route run/stop/queue controls through the new command bar."""
+
+        panel = getattr(self, "pipeline_panel_v2", None)
+        command_bar = getattr(panel, "command_bar", None)
+        if command_bar is None:
+            return
+
+        try:
+            command_bar.run_button.configure(command=self._run_full_pipeline)
+        except Exception:
+            pass
+        try:
+            command_bar.stop_button.configure(command=self._on_cancel_clicked)
+        except Exception:
+            pass
+
+        try:
+            command_bar.set_queue_mode(is_queue_execution_enabled())
+        except Exception:
+            pass
+        try:
+            command_bar.set_queue_toggle_callback(self._on_queue_mode_toggled)
+        except Exception:
+            pass
+
+        self.run_pipeline_btn = command_bar.run_button
+        self.run_button = self.run_pipeline_btn
+        self.stop_button = command_bar.stop_button
+        try:
+            self._attach_tooltip(
+                self.run_pipeline_btn,
+                "Process every highlighted pack sequentially using the current configuration. Override mode applies when enabled.",
+            )
+        except Exception:
+            pass
+        self._apply_run_button_state()
+
+    def _update_webui_state(self, state) -> None:
+        panel = getattr(self, "api_status_panel", None)
+        if panel and hasattr(panel, "set_webui_state"):
+            try:
+                panel.set_webui_state(state)
+            except Exception:
+                pass
+        if state == WebUIConnectionState.READY:
+            self.api_connected = True
+        elif state in {WebUIConnectionState.ERROR, WebUIConnectionState.DISCONNECTED, WebUIConnectionState.DISABLED}:
+            self.api_connected = False
+        self._apply_run_button_state()
+
+    def _ensure_webui_connection(self, autostart: bool) -> WebUIConnectionState:
+        state = None
+        ctrl = getattr(self, "controller", None)
+        if ctrl is not None and hasattr(ctrl, "_webui_connection"):
+            try:
+                state = ctrl._webui_connection.ensure_connected(autostart=autostart)
+            except Exception:
+                state = WebUIConnectionState.ERROR
+        if state is None:
+            state = WebUIConnectionState.ERROR
+        self._update_webui_state(state)
+        return state
+
+    def _on_webui_launch(self):
+        manager = getattr(self, "webui_process_manager", None)
+        if manager is not None:
+            try:
+                manager.start()
+            except Exception as exc:
+                self.log_message(f"? Failed to start WebUI: {exc}", "ERROR")
+        self._ensure_webui_connection(autostart=True)
+
+    def _on_webui_retry(self):
+        self._ensure_webui_connection(autostart=False)
+
+    def _on_webui_reconnect(self):
+        self._ensure_webui_connection(autostart=True)
+
+
+    def _build_api_status_frame(self, parent):
+        """Build the API status frame using APIStatusPanel."""
+        # Prefer the status bar's embedded WebUI panel when available to avoid duplicates.
+        existing_panel = getattr(getattr(self, "status_bar_v2", None), "webui_panel", None)
+        if existing_panel is not None:
+            self.api_status_panel = existing_panel
+            try:
+                self.api_status_panel.set_launch_callback(self._on_webui_launch)
+                self.api_status_panel.set_retry_callback(self._on_webui_retry)
+            except Exception:
+                pass
+            try:
+                state = None
+                ctrl = getattr(self, "controller", None)
+                if ctrl and hasattr(ctrl, "get_webui_connection_state"):
+                    state = ctrl.get_webui_connection_state()
+                if state is None:
+                    state = WebUIConnectionState.DISCONNECTED
+                self._update_webui_state(state)
+            except Exception:
+                pass
+            return
+
+        frame = ttk.Frame(
+            parent,
+            style=getattr(self.theme, "SURFACE_FRAME_STYLE", "Dark.TFrame"),
+            relief=tk.SUNKEN,
+        )
+        frame.pack(fill=tk.X, padx=5, pady=(4, 0))
+        frame.configure(height=48)
+        frame.pack_propagate(False)
+
+        self.api_status_panel = APIStatusPanel(
+            frame,
+            coordinator=self,
+            style=getattr(self.theme, "SURFACE_FRAME_STYLE", "Dark.TFrame"),
+        )
+        self.api_status_panel.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
+        try:
+            self.api_status_panel.set_launch_callback(self._on_webui_launch)
+            self.api_status_panel.set_retry_callback(self._on_webui_retry)
+        except Exception:
+            pass
+        try:
+            state = None
+            ctrl = getattr(self, "controller", None)
+            if ctrl and hasattr(ctrl, "get_webui_connection_state"):
+                state = ctrl.get_webui_connection_state()
+            if state is None:
+                state = WebUIConnectionState.DISCONNECTED
+            self._update_webui_state(state)
+        except Exception:
+            pass
+
+    def _build_prompt_pack_panel(self, parent):
+        """Build the prompt pack selection panel."""
+        # Create PromptPackPanel
+        self.prompt_pack_panel = PromptPackPanel(
+            parent,
+            coordinator=self,
+            on_selection_changed=self._on_pack_selection_changed_mediator,
+            style="Dark.TFrame",
+        )
+        self.prompt_pack_panel.pack(fill=tk.BOTH, expand=True)
+
+    def _build_config_pipeline_panel(self, parent):
+        """Build the consolidated configuration notebook with Pipeline, Randomization, and General tabs."""
+        # Create main notebook for center panel
+        self.center_notebook = ttk.Notebook(parent, style="Dark.TNotebook")
+        self.center_notebook.pack(fill=tk.BOTH, expand=True)
+
+        # Pipeline tab - configuration
+        pipeline_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
+        self.center_notebook.add(pipeline_tab, text="Pipeline")
+
+        self._build_info_box(
+            pipeline_tab,
+            "Pipeline Configuration",
+            "Configure txt2img, img2img, and upscale behavior for the next run. "
+            "Use override mode to apply these settings to every selected pack.",
+        ).pack(fill=tk.X, padx=10, pady=(10, 4))
+
+        try:
+            override_header = ttk.Frame(pipeline_tab, style="Dark.TFrame")
+            override_header.pack(fill=tk.X, padx=10, pady=(0, 4))
+            override_checkbox = ttk.Checkbutton(
+                override_header,
+                text="Override pack settings with current config",
+                variable=self.override_pack_var,
+                style="Dark.TCheckbutton",
+                command=self._on_override_changed,
+            )
+            override_checkbox.pack(side=tk.LEFT)
+            self._attach_tooltip(
+                override_checkbox,
+                "When enabled, the visible configuration is applied to every selected pack. Disable to use each pack's saved config.",
+            )
+        except Exception:
+            pass
+
+        config_scroll = ttk.Frame(pipeline_tab, style="Dark.TFrame")
+        config_scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
+        pipeline_canvas, config_body = make_scrollable(config_scroll, style="Dark.TFrame")
+        self._register_scrollable_section("pipeline", pipeline_canvas, config_body)
+
+        self.config_panel = ConfigPanel(config_body, coordinator=self, style="Dark.TFrame")
+        self.config_panel.pack(fill=tk.BOTH, expand=True)
+
+        self.txt2img_vars = self.config_panel.txt2img_vars
+        self.img2img_vars = self.config_panel.img2img_vars
+        self.upscale_vars = self.config_panel.upscale_vars
+        self.api_vars = self.config_panel.api_vars
+        self.config_status_label = self.config_panel.config_status_label
+        self.adetailer_panel = getattr(self.config_panel, "adetailer_panel", None)
+
+        try:
+            summary_frame = ttk.LabelFrame(
+                pipeline_tab, text="Next Run Summary", style="Dark.TLabelframe", padding=5
+            )
+            summary_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
+
+            self.txt2img_summary_var = getattr(self, "txt2img_summary_var", tk.StringVar(value=""))
+            self.img2img_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
+            self.upscale_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
+            self.upscale_summary_var = getattr(self, "upscale_summary_var", tk.StringVar(value=""))
+
+            for var in (
+                self.txt2img_summary_var,
+                self.img2img_summary_var,
+                self.upscale_summary_var,
+            ):
+                ttk.Label(
+                    summary_frame,
+                    textvariable=var,
+                    style="Dark.TLabel",
+                    font=("Consolas", 9),
+                ).pack(anchor=tk.W, pady=1)
+
+            self._attach_summary_traces()
+            self._update_live_config_summary()
+        except Exception:
+            pass
+
+        # Randomization tab
+        randomization_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
+        self.center_notebook.add(randomization_tab, text="Randomization")
+        self._build_randomization_tab(randomization_tab)
+
+        # General tab - pipeline controls and API settings
+        general_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
+        self.center_notebook.add(general_tab, text="General")
+
+        general_split = ttk.Frame(general_tab, style="Dark.TFrame")
+        general_split.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))
+
+        general_scroll_container = ttk.Frame(general_split, style="Dark.TFrame")
+        general_scroll_container.pack(fill=tk.BOTH, expand=True)
+        general_canvas, general_body = make_scrollable(general_scroll_container, style="Dark.TFrame")
+        self._register_scrollable_section("general", general_canvas, general_body)
+
+        self._build_info_box(
+            general_body,
+            "General Settings",
+            "Manage batch size, looping behavior, and API connectivity. "
+            "These settings apply to every run regardless of prompt pack.",
+        ).pack(fill=tk.X, pady=(0, 6))
+
+        video_frame = ttk.Frame(general_body, style="Dark.TFrame")
+        video_frame.pack(fill=tk.X, pady=(0, 4))
+        ttk.Checkbutton(
+            video_frame,
+            text="Enable video stage",
+            variable=self.video_enabled,
+            style="Dark.TCheckbutton",
+        ).pack(anchor=tk.W)
+
+        # Pipeline controls in General tab
+        self._build_pipeline_controls_panel(general_body)
+        if self._ai_settings_enabled:
+            self._build_ai_settings_button(general_body)
+
+        api_frame = ttk.LabelFrame(
+            general_body, text="API Configuration", style="Dark.TLabelframe", padding=8
+        )
+        api_frame.pack(fill=tk.X, pady=(10, 10))
+        ttk.Label(api_frame, text="Base URL:", style="Dark.TLabel").grid(
+            row=0, column=0, sticky=tk.W, pady=2
+        )
+        ttk.Entry(
+            api_frame,
+            textvariable=self.api_vars.get("base_url"),
+            style="Dark.TEntry",
+        ).grid(row=0, column=1, sticky=tk.EW, pady=2, padx=(5, 0))
+        api_frame.columnconfigure(1, weight=1)
+
+        ttk.Label(api_frame, text="Timeout (s):", style="Dark.TLabel").grid(
+            row=1, column=0, sticky=tk.W, pady=2
+        )
+        ttk.Entry(
+            api_frame,
+            textvariable=self.api_vars.get("timeout"),
+            style="Dark.TEntry",
+        ).grid(row=1, column=1, sticky=tk.EW, pady=2, padx=(5, 0))
+
+        # Advanced editor tab for legacy editor access
+        advanced_tab = ttk.Frame(self.center_notebook, style="Dark.TFrame")
+        self.center_notebook.add(advanced_tab, text="Advanced Editor")
+        self._build_advanced_editor_tab(advanced_tab)
+
+    def _initialize_pipeline_panel_config(self) -> None:
+        panel = getattr(self, "pipeline_panel_v2", None)
+        if panel is None:
+            return
+        try:
+            initial_config = getattr(self, "current_config", None)
+            if not initial_config and getattr(self, "config_manager", None):
+                initial_config = self.config_manager.get_default_config()
+            if initial_config:
+                panel.load_from_config(initial_config)
+                self._refresh_txt2img_validation(broadcast_status=False)
+        except Exception:
+            logger.debug("Unable to initialize PipelinePanelV2 config", exc_info=True)
+
+    def _initialize_randomizer_panel_config(self) -> None:
+        panel = getattr(self, "randomizer_panel_v2", None)
+        if panel is None:
+            return
+        try:
+            initial_config = getattr(self, "current_config", None)
+            if not initial_config and getattr(self, "config_manager", None):
+                initial_config = self.config_manager.get_default_config()
+            if initial_config:
+                panel.load_from_config(initial_config)
+            self._refresh_randomizer_variant_count()
+        except Exception:
+            logger.debug("Unable to initialize RandomizerPanelV2 config", exc_info=True)
+
+    def _apply_pipeline_panel_overrides(self, config_snapshot: dict) -> dict:
+        panel = getattr(self, "pipeline_panel_v2", None)
+        if panel is None:
+            return config_snapshot
+        try:
+            delta = panel.to_config_delta() or {}
+        except Exception:
+            logger.debug("PipelinePanelV2 delta failed", exc_info=True)
+            delta = {}
+        return build_effective_config(
+            config_snapshot or {},
+            txt2img_overrides=delta.get("txt2img"),
+            img2img_overrides=delta.get("img2img"),
+            upscale_overrides=delta.get("upscale"),
+            pipeline_overrides=delta.get("pipeline"),
+        )
+
+    def get_gui_overrides(self) -> dict[str, object]:
+        """Expose current GUI core overrides for the controller/assembler path."""
+        overrides: dict[str, object] = {}
+        panel = getattr(self, "pipeline_panel_v2", None)
+        if panel:
+            try:
+                overrides["prompt"] = panel.get_prompt()
+            except Exception:
+                overrides["prompt"] = ""
+        sidebar = getattr(self, "sidebar_panel_v2", None)
+        if sidebar:
+            try:
+                overrides.update(sidebar.get_model_overrides())
+            except Exception:
+                pass
+            try:
+                overrides.update(sidebar.get_core_overrides())
+            except Exception:
+                pass
+            try:
+                overrides["negative_prompt"] = sidebar.get_negative_prompt()
+            except Exception:
+                pass
+            try:
+                width, height = sidebar.get_resolution()
+                overrides["width"] = width
+                overrides["height"] = height
+                overrides["resolution_preset"] = sidebar.get_resolution_preset()
+            except Exception:
+                pass
+            try:
+                overrides.update(sidebar.get_output_overrides())
+            except Exception:
+                pass
+        return overrides
+
+    def _build_randomizer_plan_result(self, config_snapshot: dict):
+        panel = getattr(self, "randomizer_panel_v2", None)
+        if panel is None or config_snapshot is None:
+            return None
+        try:
+            plan_result = panel.build_variant_plan(config_snapshot)
+            self._last_randomizer_plan_result = plan_result
+            return plan_result
+        except Exception:
+            logger.debug("Randomizer plan evaluation failed", exc_info=True)
+            return None
+
+    def _on_randomizer_panel_changed(self) -> None:
+        if getattr(self, "root", None) is None:
+            return
+        if self._randomizer_variant_update_job:
+            try:
+                self.root.after_cancel(self._randomizer_variant_update_job)
+            except Exception:
+                pass
+        try:
+            self._randomizer_variant_update_job = self.root.after(
+                0, self._refresh_randomizer_variant_count
+            )
+        except Exception:
+            self._refresh_randomizer_variant_count()
+
+    def _refresh_randomizer_variant_count(self) -> None:
+        self._randomizer_variant_update_job = None
+        panel = getattr(self, "randomizer_panel_v2", None)
+        if panel is None:
+            return
+        base_config = self._current_randomizer_base_config()
+        options = panel.get_randomizer_options()
+        try:
+            count = compute_variant_count(base_config, options)
+        except Exception:
+            count = 1
+        panel.update_variant_count(count)
+
+    def _current_randomizer_base_config(self) -> dict:
+        try:
+            snapshot = self._get_config_from_forms()
+            if snapshot:
+                return snapshot
+        except Exception:
+            pass
+        try:
+            if getattr(self, "current_config", None):
+                return deepcopy(self.current_config)
+        except Exception:
+            pass
+        if getattr(self, "config_manager", None):
+            try:
+                return self.config_manager.get_default_config()
+            except Exception:
+                pass
+        return {}
+
+    def _on_pipeline_txt2img_updated(self) -> None:
+        self._refresh_txt2img_validation()
+
+    def _refresh_txt2img_validation(self, *, broadcast_status: bool = True) -> bool:
+        panel = getattr(self, "pipeline_panel_v2", None)
+        if panel is None:
+            return True
+        try:
+            result = panel.validate_txt2img()
+        except Exception:
+            logger.debug("txt2img validation failed", exc_info=True)
+            return True
+
+        self._last_txt2img_validation_result = result
+        is_valid = bool(getattr(result, "is_valid", True))
+        self._run_button_validation_locked = not is_valid
+        self._apply_run_button_state()
+
+        status_bar = getattr(self, "status_bar_v2", None)
+        if status_bar is not None:
+            if is_valid:
+                status_bar.clear_validation_error()
+            elif broadcast_status:
+                status_bar.set_validation_error(self._describe_validation_error(result))
+        return is_valid
+
+    @staticmethod
+    def _describe_validation_error(result) -> str:
+        errors = getattr(result, "errors", None) or {}
+        try:
+            return next(iter(errors.values()))
+        except StopIteration:
+            return "Invalid configuration."
+
+    def _apply_run_button_state(self) -> None:
+        button = getattr(self, "run_pipeline_btn", None)
+        if button is None:
+            return
+        allowed_states = {GUIState.IDLE, GUIState.ERROR}
+        current_state = getattr(self.state_manager, "current_state", GUIState.IDLE)
+        state_allows = current_state in allowed_states
+        connected = getattr(self, "api_connected", False)
+        enabled = state_allows and connected and not self._run_button_validation_locked
+        button.config(state=tk.NORMAL if enabled else tk.DISABLED)
+
+    def _on_queue_mode_toggled(self, enabled: bool | None = None) -> None:
+        try:
+            value = bool(enabled) if enabled is not None else False
+        except Exception:
+            value = False
+        try:
+            set_queue_execution_enabled(value)
+        except Exception:
+            pass
+        controller = getattr(self, "controller", None)
+        if controller is not None:
+            try:
+                setattr(controller, "_queue_execution_enabled", value)
+            except Exception:
+                pass
+
+    def _on_learning_toggle(self, enabled: bool) -> None:
+        try:
+            self.controller.set_learning_enabled(bool(enabled))
+        except Exception:
+            pass
+        try:
+            self.learning_execution_controller.set_learning_enabled(bool(enabled))
+        except Exception:
+            pass
+        try:
+            self.learning_enabled_var.set(bool(enabled))
+        except Exception:
+            pass
+
+    def _open_learning_review_dialog(self) -> None:
+        try:
+            records = self.learning_execution_controller.list_recent_records(limit=10)
+            LearningReviewDialogV2(self.root, self.learning_execution_controller, records)
+        except Exception:
+            logger.debug("Failed to open learning review dialog", exc_info=True)
+
+    def _handle_preferences_load_failure(self, exc: Exception) -> None:
+        """Notify the user that preferences failed to load and backup the corrupt file."""
+
+        warning_text = (
+            "Your last settings could not be loaded. StableNew has reset to safe defaults.\n\n"
+            "The previous settings file was moved aside (or removed) to prevent future issues."
+        )
+        try:
+            messagebox.showwarning("StableNew", warning_text)
+        except Exception:
+            logger.exception("Failed to display corrupt preferences warning dialog")
+
+        try:
+            self.preferences_manager.backup_corrupt_preferences()
+        except Exception:
+            logger.exception("Failed to backup corrupt preferences file")
+
+        self._reset_randomization_to_defaults()
+
+    def _initialize_ui_state_async(self):
+        """Initialize UI state asynchronously after mainloop starts."""
+        # Restore UI state from preferences
+        self._restore_ui_state_from_preferences()
+
+    def _initialize_ui_state(self):
+        """Legacy synchronous initialization hook retained for tests."""
+
+        self._initialize_ui_state_async()
+
+    def _restore_ui_state_from_preferences(self):
+        """Restore UI state from loaded preferences."""
+        try:
+            if "preset" in self.preferences:
+                self.preset_var.set(self.preferences["preset"])
+
+            if "selected_packs" in self.preferences:
+                self.current_selected_packs = self.preferences["selected_packs"]
+                if hasattr(self, "prompt_pack_panel"):
+                    self.prompt_pack_panel.set_selected_packs(self.current_selected_packs)
+
+            if "override_pack" in self.preferences and hasattr(self, "override_pack_var"):
+                self.override_pack_var.set(self.preferences["override_pack"])
+
+            if "pipeline_controls" in self.preferences and hasattr(self, "pipeline_controls_panel"):
+                self.pipeline_controls_panel.set_state(self.preferences["pipeline_controls"])
+
+            if "config" in self.preferences:
+                self.current_config = self.preferences["config"]
+                if hasattr(self, "config_panel"):
+                    self._load_config_into_forms(self.current_config)
+        except Exception as exc:
+            logger.error("Failed to restore preferences to UI; reverting to defaults: %s", exc)
+            try:
+                fallback_cfg = self.config_manager.get_default_config()
+                self.preferences = self.preferences_manager.default_preferences(fallback_cfg)
+                self.preset_var.set(self.preferences.get("preset", "default"))
+                self.current_selected_packs = []
+                if hasattr(self, "prompt_pack_panel"):
+                    self.prompt_pack_panel.set_selected_packs([])
+                if hasattr(self, "override_pack_var"):
+                    self.override_pack_var.set(False)
+                if hasattr(self, "pipeline_controls_panel"):
+                    self.pipeline_controls_panel.set_state(
+                        self.preferences.get("pipeline_controls", {})
+                    )
+                if hasattr(self, "config_panel"):
+                    self._load_config_into_forms(self.preferences.get("config", {}))
+                self._reset_randomization_to_defaults()
+            except Exception:
+                logger.exception("Failed to apply fallback preferences after restore failure")
+
+    def _reset_randomization_to_defaults(self) -> None:
+        """Reset randomization config to defaults and update UI if available."""
+
+        try:
+            default_cfg = self.config_manager.get_default_config() or {}
+            random_defaults = deepcopy(default_cfg.get("randomization", {}) or {})
+        except Exception as exc:
+            logger.error("Failed to obtain default randomization config: %s", exc)
+            return
+
+        self.preferences.setdefault("config", {})["randomization"] = random_defaults
+
+        if hasattr(self, "randomization_vars"):
+            try:
+                self._load_randomization_config({"randomization": random_defaults})
+            except Exception:
+                logger.exception("Failed to apply default randomization settings to UI")
+
+    def _build_action_bar(self, parent):
+        """Build the action bar with explicit load controls."""
+        action_bar = ttk.Frame(parent, style="Dark.TFrame")
+        action_bar.pack(fill=tk.X, padx=5, pady=(0, 5))
+
+        button_width = 28
+
+        def add_toolbar_button(container, column, text, command, tooltip=None, style="Dark.TButton"):
+            btn = ttk.Button(container, text=text, command=command, style=style, width=button_width)
+            btn.grid(row=0, column=column, padx=4, pady=2, sticky="ew")
+            container.grid_columnconfigure(column, weight=1)
+            if tooltip:
+                self._attach_tooltip(btn, tooltip)
+            return btn
+
+        row1 = ttk.Frame(action_bar, style="Dark.TFrame")
+        row1.pack(fill=tk.X, pady=(0, 4))
+        row2 = ttk.Frame(action_bar, style="Dark.TFrame")
+        row2.pack(fill=tk.X)
+
+        add_toolbar_button(
+            row1,
+            0,
+            "Load Pack Config",
+            self._ui_load_pack_config,
+            "Load the selected pack's saved configuration into the editor.",
+        )
+
+        preset_container = ttk.Frame(row1, style="Dark.TFrame")
+        preset_container.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
+        row1.grid_columnconfigure(1, weight=2)
+        ttk.Label(preset_container, text="Preset:", style="Dark.TLabel").pack(side=tk.LEFT)
+        self.preset_combobox = ttk.Combobox(
+            preset_container,
+            textvariable=self.preset_var,
+            values=self.config_service.list_presets(),
+            state="readonly",
+            width=30,
+            style="Dark.TCombobox",
+        )
+        self.preset_combobox.pack(side=tk.LEFT, padx=(5, 6))
+        preset_load_btn = ttk.Button(
+            preset_container, text="Load Preset", command=self._ui_load_preset, style="Dark.TButton"
+        )
+        preset_load_btn.pack(side=tk.LEFT)
+        self._attach_tooltip(preset_load_btn, "Load the selected preset into the editor.")
+
+        add_toolbar_button(
+            row1,
+            2,
+            "Save Editor → Preset",
+            self._ui_save_preset,
+            "Persist the current editor configuration to the active preset slot.",
+        )
+        add_toolbar_button(
+            row1,
+            3,
+            "Delete Preset",
+            self._ui_delete_preset,
+            "Remove the selected preset from disk.",
+            style="Danger.TButton",
+        )
+
+        list_container = ttk.Frame(row2, style="Dark.TFrame")
+        list_container.grid(row=0, column=0, padx=4, pady=2, sticky="ew")
+        row2.grid_columnconfigure(0, weight=2)
+        ttk.Label(list_container, text="List:", style="Dark.TLabel").pack(side=tk.LEFT)
+        self.list_combobox = ttk.Combobox(
+            list_container,
+            values=self.config_service.list_lists(),
+            state="readonly",
+            width=24,
+            style="Dark.TCombobox",
+        )
+        self.list_combobox.pack(side=tk.LEFT, padx=(5, 6))
+        list_load_btn = ttk.Button(
+            list_container, text="Load List", command=self._ui_load_list, style="Dark.TButton"
+        )
+        list_load_btn.pack(side=tk.LEFT)
+        self._attach_tooltip(list_load_btn, "Load saved pack selections from the chosen list.")
+
+        add_toolbar_button(
+            row2,
+            1,
+            "Save Selection as List",
+            self._ui_save_list,
+            "Persist the current pack selection as a reusable list.",
+        )
+        add_toolbar_button(
+            row2,
+            2,
+            "Overwrite List",
+            self._ui_overwrite_list,
+            "Replace the chosen list with the current selection.",
+        )
+        add_toolbar_button(
+            row2,
+            3,
+            "Delete List",
+            self._ui_delete_list,
+            "Remove the chosen list from disk.",
+            style="Danger.TButton",
+        )
+        self.lock_button = add_toolbar_button(
+            row2,
+            4,
+            "Lock This Config",
+            self._ui_toggle_lock,
+            "Prevent accidental edits by locking the current configuration.",
+        )
+        add_toolbar_button(
+            row2,
+            5,
+            "Apply Editor → Pack(s)",
+            self._ui_apply_editor_to_packs,
+            "Push the editor settings into the selected pack(s).",
+        )
+        add_toolbar_button(
+            row2,
+            6,
+            "Preview Payload (Dry Run)",
+            self._preview_payload_dry_run,
+            "Simulate a run and show prompt/variant counts without calling WebUI.",
+        )
+
+    def _build_menu_bar(self) -> None:
+        """Construct the top-level menu bar."""
+
+        menubar = tk.Menu(self.root)
+        settings_menu = tk.Menu(menubar, tearoff=0)
+        settings_menu.add_command(
+            label="Engine settings...",
+            command=self._open_engine_settings_dialog,
+        )
+        settings_menu.add_checkbutton(
+            label="Enable learning (record runs for review)",
+            variable=self.learning_enabled_var,
+            command=lambda: self._on_learning_toggle(self.learning_enabled_var.get()),
+        )
+        settings_menu.add_command(
+            label="Review recent runs...",
+            command=self._open_learning_review_dialog,
+        )
+        menubar.add_cascade(label="Settings", menu=settings_menu)
+        self.root.config(menu=menubar)
+        self._menubar = menubar
+        self._settings_menu = settings_menu
+
+    def _apply_editor_from_cfg(self, cfg: dict) -> None:
+        """Apply config to the editor (config panel)."""
+        if not cfg:
+            return
+        if hasattr(self, "config_panel"):
+            self.config_panel.set_config(cfg)
+        try:
+            self.pipeline_controls_panel.apply_config(cfg)
+        except Exception:
+            logger.debug("Pipeline controls apply_config skipped", exc_info=True)
+        try:
+            self._apply_adetailer_config_section(cfg.get("adetailer", {}))
+        except Exception:
+            logger.debug("ADetailer config apply skipped", exc_info=True)
+        try:
+            self._load_randomization_config(cfg)
+        except Exception:
+            logger.debug("Randomization config apply skipped", exc_info=True)
+        try:
+            self._load_aesthetic_config(cfg)
+        except Exception:
+            logger.debug("Aesthetic config apply skipped", exc_info=True)
+
+    def _apply_adetailer_config_section(self, adetailer_cfg: dict | None) -> None:
+        """Apply ADetailer config to the panel, normalizing scheduler defaults."""
+        panel = getattr(self, "adetailer_panel", None)
+        if not panel:
+            return
+        cfg = dict(adetailer_cfg or {})
+        scheduler_value = cfg.get("adetailer_scheduler", cfg.get("scheduler", "inherit")) or "inherit"
+        cfg["adetailer_scheduler"] = scheduler_value
+        cfg["scheduler"] = scheduler_value
+        panel.set_config(cfg)
+
+    def _ui_toggle_lock(self) -> None:
+        """Toggle the config lock state."""
+        if self.is_locked:
+            self._unlock_config()
+        else:
+            self._lock_config()
+
+    def _open_engine_settings_dialog(self) -> None:
+        """Open the Engine Settings dialog wired to WebUI options."""
+
+        if self.client is None:
+            messagebox.showerror(
+                "Engine Settings",
+                "Connect to the Stable Diffusion API before editing engine settings.",
+            )
+            return
+
+        try:
+            self._add_log_message("⚙️ Opening Engine Settings dialog…")
+        except Exception:
+            pass
+
+        try:
+            EngineSettingsDialog(self.root, self.client)
+        except Exception as exc:
+            messagebox.showerror("Engine Settings", f"Unable to open dialog: {exc}")
+
+    def _lock_config(self) -> None:
+        """Lock the current config."""
+        self.previous_source = self.ctx.source
+        self.previous_banner_text = self.config_source_banner.cget("text")
+        self.ctx.source = ConfigSource.GLOBAL_LOCK
+        self.ctx.locked_cfg = deepcopy(self.pipeline_controls_panel.get_settings())
+        self.is_locked = True
+        self.lock_button.config(text="Unlock Config")
+        self._update_config_source_banner("Using: Global Lock")
+
+    def _unlock_config(self) -> None:
+        """Unlock the config."""
+        self.ctx.source = self.previous_source
+        self.ctx.locked_cfg = None
+        self.is_locked = False
+        self.lock_button.config(text="Lock This Config")
+        self._update_config_source_banner(self.previous_banner_text)
+
+    def _ui_load_pack_config(self) -> None:
+        """Load config from the first selected pack into the editor."""
+        if self._check_lock_before_load():
+            if not self.current_selected_packs:
+                return
+            pack = self.current_selected_packs[0]
+            cfg = self.config_service.load_pack_config(pack)
+            if not cfg:
+                self._safe_messagebox(
+                    "info",
+                    "No Saved Config",
+                    f"No config saved for '{pack}'. Showing defaults.",
+                )
+                return
+            self._apply_editor_from_cfg(cfg)
+            self._update_config_source_banner("Using: Pack Config (view)")
+            self._reset_config_dirty_state()
+
+    def _ui_load_preset(self) -> None:
+        """Load selected preset into the editor."""
+        if self._check_lock_before_load():
+            name = self.preset_combobox.get()
+            if not name:
+                return
+            cfg = self.config_service.load_preset(name)
+            self._apply_editor_from_cfg(cfg)
+            self.current_preset_name = name
+            self._update_config_source_banner(f"Using: Preset: {name}")
+            self._reset_config_dirty_state()
+
+    def _check_lock_before_load(self) -> bool:
+        """Check if locked and prompt to unlock. Returns True if should proceed."""
+        if not self.is_locked:
+            return True
+        result = messagebox.askyesno("Config Locked", "Unlock to proceed?")
+        if result:
+            self._unlock_config()
+            return True
+        return False
+
+    def _ui_apply_editor_to_packs(self) -> None:
+        """Apply current editor config to selected packs."""
+        if not self.current_selected_packs:
+            messagebox.showwarning("No Selection", "Please select one or more packs first.")
+            return
+
+        num_packs = len(self.current_selected_packs)
+        result = messagebox.askyesno(
+            "Confirm Overwrite",
+            f"Overwrite configs for {num_packs} pack{'s' if num_packs > 1 else ''}?",
+        )
+        if not result:
+            return
+
+        # Capture the full editor config (txt2img/img2img/upscale/pipeline/randomization/etc.)
+        editor_cfg = self._get_config_from_forms()
+        if not editor_cfg:
+            messagebox.showerror("Error", "Unable to read the current editor configuration.")
+            return
+
+        # Save in worker thread
+        def save_worker():
+            try:
+                for pack in self.current_selected_packs:
+                    self.config_service.save_pack_config(pack, editor_cfg)
+                # Success callback on UI thread
+                def _on_success():
+                    messagebox.showinfo(
+                        "Success", f"Applied to {num_packs} pack{'s' if num_packs > 1 else ''}."
+                    )
+                    self._reset_config_dirty_state()
+
+                self.root.after(0, _on_success)
+            except Exception as exc:
+                error_msg = str(exc)
+                # Error callback on UI thread
+                self.root.after(
+                    0, lambda: messagebox.showerror("Error", f"Failed to save configs: {error_msg}")
+                )
+
+        threading.Thread(target=save_worker, daemon=True).start()
+
+    def _refresh_preset_dropdown(self) -> None:
+        """Refresh the preset dropdown with current presets."""
+        self.preset_combobox["values"] = self.config_service.list_presets()
+
+    def _refresh_list_dropdown(self) -> None:
+        """Refresh the list dropdown with current lists."""
+        self.list_combobox["values"] = self.config_service.list_lists()
+
+    def _ui_save_preset(self) -> None:
+        """Save current editor config as a new preset."""
+        name = simpledialog.askstring("Save Preset", "Enter preset name:")
+        if not name:
+            return
+        if name in self.config_service.list_presets():
+            if not messagebox.askyesno(
+                "Overwrite Preset", f"Preset '{name}' already exists. Overwrite?"
+            ):
+                return
+        editor_cfg = self.pipeline_controls_panel.get_settings()
+        try:
+            self.config_service.save_preset(name, editor_cfg, overwrite=True)
+            self._refresh_preset_dropdown()
+            messagebox.showinfo("Success", f"Preset '{name}' saved.")
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to save preset: {e}")
+
+    def _ui_delete_preset(self) -> None:
+        """Delete the selected preset."""
+        name = self.preset_combobox.get()
+        if not name:
+            messagebox.showwarning("No Selection", "Please select a preset to delete.")
+            return
+        if not messagebox.askyesno("Delete Preset", f"Delete preset '{name}'?"):
+            return
+        try:
+            self.config_service.delete_preset(name)
+            self._refresh_preset_dropdown()
+            # Clear selection
+            self.preset_combobox.set("")
+            # If it was the current preset, revert banner
+            if self.current_preset_name == name:
+                self.current_preset_name = None
+                if self.current_selected_packs:
+                    self._update_config_source_banner("Using: Pack Config (view)")
+                else:
+                    self._update_config_source_banner("Using: Pack Config")
+            messagebox.showinfo("Success", f"Preset '{name}' deleted.")
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to delete preset: {e}")
+
+    def _ui_load_list(self) -> None:
+        """Load selected list and set pack selection."""
+        name = self.list_combobox.get()
+        if not name:
+            messagebox.showwarning("No Selection", "Please select a list to load.")
+            return
+        try:
+            packs = self.config_service.load_list(name)
+            if not packs:
+                messagebox.showinfo("Empty List", f"List '{name}' has no packs saved.")
+                return
+            available = list(self.prompt_pack_panel.packs_listbox.get(0, tk.END))
+            valid_packs = [p for p in packs if p in available]
+            if not valid_packs:
+                messagebox.showwarning(
+                    "No Matching Packs",
+                    f"None of the packs from '{name}' are available in this workspace.",
+                )
+                return
+            self.prompt_pack_panel.set_selected_packs(valid_packs)
+            try:
+                self.root.update_idletasks()
+            except Exception:
+                pass
+            selected_after = self.prompt_pack_panel.get_selected_packs()
+            self.current_selected_packs = selected_after or valid_packs
+            self.ctx.active_list = name
+            messagebox.showinfo("Success", f"List '{name}' loaded ({len(valid_packs)} packs).")
+            self._reset_config_dirty_state()
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to load list: {e}")
+
+    def _ui_save_list(self) -> None:
+        """Save current pack selection as a new list."""
+        if not self.current_selected_packs:
+            messagebox.showwarning("No Selection", "Please select packs to save as list.")
+            return
+        name = simpledialog.askstring("Save List", "Enter list name:")
+        if not name:
+            return
+        if name in self.config_service.list_lists():
+            if not messagebox.askyesno(
+                "Overwrite List", f"List '{name}' already exists. Overwrite?"
+            ):
+                return
+        try:
+            self.config_service.save_list(name, self.current_selected_packs, overwrite=True)
+            self.ctx.active_list = name
+            self._refresh_list_dropdown()
+            messagebox.showinfo(
+                "Success", f"List '{name}' saved ({len(self.current_selected_packs)} packs)."
+            )
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to save list: {e}")
+
+    def _ui_overwrite_list(self) -> None:
+        """Overwrite the current active list with current selection."""
+        if not self.ctx.active_list:
+            messagebox.showwarning(
+                "No Active List", "No list is currently active. Use 'Save Selection as List' first."
+            )
+            return
+        if not self.current_selected_packs:
+            messagebox.showwarning("No Selection", "Please select packs to save.")
+            return
+        if not messagebox.askyesno(
+            "Overwrite List", f"Overwrite list '{self.ctx.active_list}' with current selection?"
+        ):
+            return
+        try:
+            self.config_service.save_list(
+                self.ctx.active_list, self.current_selected_packs, overwrite=True
+            )
+            messagebox.showinfo(
+                "Success",
+                f"List '{self.ctx.active_list}' updated ({len(self.current_selected_packs)} packs).",
+            )
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to overwrite list: {e}")
+
+    def _ui_delete_list(self) -> None:
+        """Delete the selected list."""
+        name = self.list_combobox.get()
+        if not name:
+            messagebox.showwarning("No Selection", "Please select a list to delete.")
+            return
+        if not messagebox.askyesno("Delete List", f"Delete list '{name}'?"):
+            return
+        try:
+            self.config_service.delete_list(name)
+            self._refresh_list_dropdown()
+            self.list_combobox.set("")
+            if self.ctx.active_list == name:
+                self.ctx.active_list = None
+            messagebox.showinfo("Success", f"List '{name}' deleted.")
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to delete list: {e}")
+
+    def _setup_theme(self):
+        self.style.configure(
+            "Dark.TCheckbutton",
+            background=self.bg_color,
+            foreground=self.fg_color,
+            focuscolor="none",
+            font=("Segoe UI", 9),
+        )
+        self.style.configure(
+            "Dark.TRadiobutton",
+            background=self.bg_color,
+            foreground=self.fg_color,
+            focuscolor="none",
+            font=("Segoe UI", 9),
+        )
+        self.style.configure("Dark.TNotebook", background=self.bg_color, borderwidth=0)
+        self.style.configure(
+            "Dark.TNotebook.Tab",
+            background=self.button_bg,
+            foreground=self.fg_color,
+            padding=[20, 8],
+            borderwidth=0,
+        )
+
+        # Accent button styles for CTAs
+        self.style.configure(
+            "Accent.TButton",
+            background="#0078d4",
+            foreground=self.fg_color,
+            borderwidth=1,
+            focuscolor="none",
+            font=("Segoe UI", 9, "bold"),
+        )
+        self.style.configure(
+            "Danger.TButton",
+            background="#dc3545",
+            foreground=self.fg_color,
+            borderwidth=1,
+            focuscolor="none",
+            font=("Segoe UI", 9, "bold"),
+        )
+
+        # Map states
+        self.style.map(
+            "Dark.TCombobox",
+            fieldbackground=[("readonly", self.entry_bg)],
+            selectbackground=[("readonly", "#0078d4")],
+        )
+        self.style.map(
+            "Accent.TButton",
+            background=[("active", "#106ebe"), ("pressed", "#005a9e")],
+            foreground=[("active", self.fg_color)],
+        )
+        self.style.map(
+            "Dark.TNotebook.Tab",
+            background=[("selected", "#0078d4"), ("active", self.button_active)],
+        )
+
+    def _layout_panels(self):
+        # Example layout for preset bar and dropdown
+        preset_bar = ttk.Frame(self.root, style="Dark.TFrame")
+        preset_bar.grid(row=0, column=0, sticky=tk.W)
+        ttk.Label(preset_bar, text="Preset:", style="Dark.TLabel").grid(
+            row=0, column=0, sticky=tk.W, padx=(2, 4)
+        )
+        self.preset_dropdown = ttk.Combobox(
+            preset_bar,
+            textvariable=self.preset_var,
+            state="readonly",
+            width=28,
+            values=self.config_manager.list_presets(),
+        )
+        self.preset_dropdown.grid(row=0, column=1, sticky=tk.W)
+        self.preset_dropdown.grid(row=0, column=1, sticky=tk.W)
+        self.preset_dropdown.bind(
+            "<<ComboboxSelected>>", lambda _e: self._on_preset_dropdown_changed()
+        )
+        self._attach_tooltip(
+            self.preset_dropdown,
+            "Select a preset to load its settings into the active configuration (spans all tabs).",
+        )
+
+        apply_default_btn = ttk.Button(
+            preset_bar,
+            text="Apply Default",
+            command=self._apply_default_to_selected_packs,
+            width=14,
+            style="Dark.TButton",
+        )
+        apply_default_btn.grid(row=0, column=2, padx=(8, 4))
+        self._attach_tooltip(
+            apply_default_btn,
+            "Load the 'default' preset into the form (not saved until you click Save to Pack(s)).",
+        )
+
+        # Right-aligned action strip
+        actions_strip = ttk.Frame(preset_bar, style="Dark.TFrame")
+        actions_strip.grid(row=0, column=3, sticky=tk.E, padx=(10, 4))
+
+        save_packs_btn = ttk.Button(
+            actions_strip,
+            text="Save to Pack(s)",
+            command=self._save_config_to_packs,
+            style="Accent.TButton",
+            width=18,
+        )
+        save_packs_btn.pack(side=tk.LEFT, padx=2)
+        self._attach_tooltip(
+            save_packs_btn,
+            "Persist current configuration to selected pack(s). Single selection saves that pack; multi-selection saves all.",
+        )
+
+        save_as_btn = ttk.Button(
+            actions_strip,
+            text="Save As Preset…",
+            command=self._save_preset_as,
+            width=16,
+        )
+        save_as_btn.pack(side=tk.LEFT, padx=2)
+        self._attach_tooltip(
+            save_as_btn, "Create a new preset from the current configuration state."
+        )
+
+        set_default_btn = ttk.Button(
+            actions_strip,
+            text="Set Default",
+            command=self._set_as_default_preset,
+            width=12,
+        )
+        set_default_btn.pack(side=tk.LEFT, padx=2)
+        self._attach_tooltip(set_default_btn, "Mark the selected preset as the startup default.")
+
+        del_preset_btn = ttk.Button(
+            actions_strip,
+            text="Delete",
+            command=self._delete_selected_preset,
+            style="Danger.TButton",
+            width=10,
+        )
+        del_preset_btn.pack(side=tk.LEFT, padx=2)
+        self._attach_tooltip(
+            del_preset_btn, "Delete the selected preset (cannot delete 'default')."
+        )
+
+        # Notebook sits below preset bar
+
+    def _build_randomization_tab(self, parent: tk.Widget) -> None:
+        """Build the randomization tab UI and data bindings."""
+
+        scroll_shell = ttk.Frame(parent, style="Dark.TFrame")
+        scroll_shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 10))
+        canvas, body = make_scrollable(scroll_shell, style="Dark.TFrame")
+        self._register_scrollable_section("randomization", canvas, body)
+
+        self._build_info_box(
+            body,
+            "Prompt Randomization & Aesthetic Tools",
+            "Enable randomized prompt variations using AUTOMATIC1111-style syntax. "
+            "Combine Prompt S/R rules, wildcard tokens, matrices, and optional aesthetic gradients.",
+        ).pack(fill=tk.X, padx=10, pady=(0, 6))
+
+        self.randomization_vars = {
+            "enabled": tk.BooleanVar(value=False),
+            "prompt_sr_enabled": tk.BooleanVar(value=False),
+            "prompt_sr_mode": tk.StringVar(value="random"),
+            "wildcards_enabled": tk.BooleanVar(value=False),
+            "wildcard_mode": tk.StringVar(value="random"),
+            "matrix_enabled": tk.BooleanVar(value=False),
+            "matrix_mode": tk.StringVar(value="fanout"),
+            "matrix_prompt_mode": tk.StringVar(value="replace"),
+            "matrix_limit": tk.IntVar(value=8),
+        }
+        self.randomization_widgets = {}
+
+        self.aesthetic_vars = {
+            "enabled": tk.BooleanVar(value=False),
+            "mode": tk.StringVar(value="script" if self.aesthetic_script_available else "prompt"),
+            "weight": tk.DoubleVar(value=0.9),
+            "steps": tk.IntVar(value=5),
+            "learning_rate": tk.StringVar(value="0.0001"),
+            "slerp": tk.BooleanVar(value=False),
+            "slerp_angle": tk.DoubleVar(value=0.1),
+            "text": tk.StringVar(value=""),
+            "text_is_negative": tk.BooleanVar(value=False),
+            "fallback_prompt": tk.StringVar(value=""),
+        }
+        self.aesthetic_widgets = {"all": [], "script": [], "prompt": []}
+
+        master_frame = ttk.Frame(body, style="Dark.TFrame")
+        master_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
+        ttk.Checkbutton(
+            master_frame,
+            text="Enable randomization for the next run",
+            variable=self.randomization_vars["enabled"],
+            style="Dark.TCheckbutton",
+            command=self._update_randomization_states,
+        ).pack(side=tk.LEFT)
+
+        ttk.Label(
+            master_frame,
+            text="Randomization expands prompts before the pipeline starts, so counts multiply per stage.",
+            style="Dark.TLabel",
+            wraplength=600,
+        ).pack(side=tk.LEFT, padx=(10, 0))
+
+        # Prompt S/R section
+        sr_frame = ttk.LabelFrame(body, text="Prompt S/R", style="Dark.TLabelframe", padding=10)
+        sr_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
+
+        sr_header = ttk.Frame(sr_frame, style="Dark.TFrame")
+        sr_header.pack(fill=tk.X)
+        ttk.Checkbutton(
+            sr_header,
+            text="Enable Prompt S/R replacements",
+            variable=self.randomization_vars["prompt_sr_enabled"],
+            style="Dark.TCheckbutton",
+            command=self._update_randomization_states,
+        ).pack(side=tk.LEFT)
+
+        sr_mode_frame = ttk.Frame(sr_frame, style="Dark.TFrame")
+        sr_mode_frame.pack(fill=tk.X, pady=(4, 2))
+        ttk.Label(sr_mode_frame, text="Selection mode:", style="Dark.TLabel").pack(side=tk.LEFT)
+        ttk.Radiobutton(
+            sr_mode_frame,
+            text="Random per prompt",
+            variable=self.randomization_vars["prompt_sr_mode"],
+            value="random",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+        ttk.Radiobutton(
+            sr_mode_frame,
+            text="Round robin",
+            variable=self.randomization_vars["prompt_sr_mode"],
+            value="round_robin",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+
+        ttk.Label(
+            sr_frame,
+            text="Format: search term => replacement A | replacement B. One rule per line. "
+            "Matches are case-sensitive and apply before wildcard/matrix expansion.",
+            style="Dark.TLabel",
+            wraplength=700,
+        ).pack(fill=tk.X, pady=(2, 4))
+
+        sr_text = scrolledtext.ScrolledText(sr_frame, height=6, wrap=tk.WORD)
+        sr_text.pack(fill=tk.BOTH, expand=True)
+        self.randomization_widgets["prompt_sr_text"] = sr_text
+        enable_mousewheel(sr_text)
+        # Persist on edits
+        self._bind_autosave_text(sr_text)
+
+        # Wildcards section
+        wildcard_frame = ttk.LabelFrame(
+            body, text="Wildcards (__token__ syntax)", style="Dark.TFrame", padding=10
+        )
+        wildcard_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
+
+        wildcard_header = ttk.Frame(wildcard_frame, style="Dark.TFrame")
+        wildcard_header.pack(fill=tk.X)
+        ttk.Checkbutton(
+            wildcard_header,
+            text="Enable wildcard replacements",
+            variable=self.randomization_vars["wildcards_enabled"],
+            style="Dark.TCheckbutton",
+            command=self._update_randomization_states,
+        ).pack(side=tk.LEFT)
+
+        ttk.Label(
+            wildcard_frame,
+            text="Use __token__ in your prompts (same as AUTOMATIC1111 wildcards). "
+            "Provide values below using token: option1 | option2.",
+            style="Dark.TLabel",
+            wraplength=700,
+        ).pack(fill=tk.X, pady=(4, 4))
+
+        wildcard_mode_frame = ttk.Frame(wildcard_frame, style="Dark.TFrame")
+        wildcard_mode_frame.pack(fill=tk.X, pady=(0, 4))
+        ttk.Label(wildcard_mode_frame, text="Selection mode:", style="Dark.TLabel").pack(
+            side=tk.LEFT
+        )
+        ttk.Radiobutton(
+            wildcard_mode_frame,
+            text="Random per prompt",
+            variable=self.randomization_vars["wildcard_mode"],
+            value="random",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+        ttk.Radiobutton(
+            wildcard_mode_frame,
+            text="Sequential (loop through values)",
+            variable=self.randomization_vars["wildcard_mode"],
+            value="sequential",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+
+        wildcard_text = scrolledtext.ScrolledText(wildcard_frame, height=6, wrap=tk.WORD)
+        wildcard_text.pack(fill=tk.BOTH, expand=True)
+        self.randomization_widgets["wildcard_text"] = wildcard_text
+        enable_mousewheel(wildcard_text)
+        self._bind_autosave_text(wildcard_text)
+
+        # Prompt matrix section
+        matrix_frame = ttk.LabelFrame(
+            body, text="Prompt Matrix ([[Slot]] syntax)", style="Dark.TFrame", padding=10
+        )
+        matrix_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
+
+        matrix_header = ttk.Frame(matrix_frame, style="Dark.TFrame")
+        matrix_header.pack(fill=tk.X)
+        ttk.Checkbutton(
+            matrix_header,
+            text="Enable prompt matrix expansion",
+            variable=self.randomization_vars["matrix_enabled"],
+            style="Dark.TCheckbutton",
+            command=self._update_randomization_states,
+        ).pack(side=tk.LEFT)
+
+        matrix_mode_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
+        matrix_mode_frame.pack(fill=tk.X, pady=(4, 2))
+        ttk.Label(matrix_mode_frame, text="Expansion mode:", style="Dark.TLabel").pack(side=tk.LEFT)
+        ttk.Radiobutton(
+            matrix_mode_frame,
+            text="Fan-out (all combos)",
+            variable=self.randomization_vars["matrix_mode"],
+            value="fanout",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+        ttk.Radiobutton(
+            matrix_mode_frame,
+            text="Rotate per prompt",
+            variable=self.randomization_vars["matrix_mode"],
+            value="rotate",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+
+        # Prompt mode: how base_prompt relates to pack prompt
+        prompt_mode_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
+        prompt_mode_frame.pack(fill=tk.X, pady=(2, 2))
+        ttk.Label(prompt_mode_frame, text="Prompt mode:", style="Dark.TLabel").pack(side=tk.LEFT)
+        ttk.Radiobutton(
+            prompt_mode_frame,
+            text="Replace pack",
+            variable=self.randomization_vars["matrix_prompt_mode"],
+            value="replace",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+        ttk.Radiobutton(
+            prompt_mode_frame,
+            text="Append to pack",
+            variable=self.randomization_vars["matrix_prompt_mode"],
+            value="append",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+        ttk.Radiobutton(
+            prompt_mode_frame,
+            text="Prepend before pack",
+            variable=self.randomization_vars["matrix_prompt_mode"],
+            value="prepend",
+            style="Dark.TRadiobutton",
+        ).pack(side=tk.LEFT, padx=(8, 0))
+
+        limit_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
+        limit_frame.pack(fill=tk.X, pady=(2, 4))
+        ttk.Label(limit_frame, text="Combination cap:", style="Dark.TLabel").pack(side=tk.LEFT)
+        ttk.Spinbox(
+            limit_frame,
+            from_=1,
+            to=64,
+            width=5,
+            textvariable=self.randomization_vars["matrix_limit"],
+        ).pack(side=tk.LEFT, padx=(4, 0))
+        ttk.Label(
+            limit_frame,
+            text="(prevents runaway combinations when many slots are defined)",
+            style="Dark.TLabel",
+        ).pack(side=tk.LEFT, padx=(6, 0))
+
+        # Base prompt field
+        base_prompt_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
+        base_prompt_frame.pack(fill=tk.X, pady=(4, 2))
+        ttk.Label(
+            base_prompt_frame,
+            text="Base prompt:",
+            style="Dark.TLabel",
+            width=14,
+        ).pack(side=tk.LEFT)
+        base_prompt_entry = ttk.Entry(base_prompt_frame)
+        base_prompt_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
+        self.randomization_widgets["matrix_base_prompt"] = base_prompt_entry
+        self._bind_autosave_entry(base_prompt_entry)
+
+        ttk.Label(
+            matrix_frame,
+            text="Add [[Slot Name]] markers in your base prompt. Define combination slots below:",
+            style="Dark.TLabel",
+            wraplength=700,
+        ).pack(fill=tk.X, pady=(2, 4))
+
+        # Scrollable container for slot rows
+        slots_container = ttk.Frame(matrix_frame, style="Dark.TFrame")
+        slots_container.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
+
+        slots_canvas = tk.Canvas(
+            slots_container,
+            bg="#2b2b2b",
+            highlightthickness=0,
+            height=150,
+        )
+        slots_scrollbar = ttk.Scrollbar(
+            slots_container,
+            orient=tk.VERTICAL,
+            command=slots_canvas.yview,
+        )
+        slots_scrollable_frame = ttk.Frame(slots_canvas, style="Dark.TFrame")
+
+        slots_scrollable_frame.bind(
+            "<Configure>",
+            lambda e: slots_canvas.configure(scrollregion=slots_canvas.bbox("all")),
+        )
+
+        slots_canvas.create_window((0, 0), window=slots_scrollable_frame, anchor="nw")
+        slots_canvas.configure(yscrollcommand=slots_scrollbar.set)
+
+        slots_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
+        slots_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
+
+        self.randomization_widgets["matrix_slots_frame"] = slots_scrollable_frame
+        self.randomization_widgets["matrix_slots_canvas"] = slots_canvas
+        self.randomization_widgets["matrix_slot_rows"] = []
+
+        # Add slot button
+        add_slot_btn = ttk.Button(
+            matrix_frame,
+            text="+ Add Combination Slot",
+            command=self._add_matrix_slot_row,
+        )
+        add_slot_btn.pack(fill=tk.X, pady=(0, 4))
+
+        # Legacy text view (hidden by default, for advanced users)
+        legacy_frame = ttk.Frame(matrix_frame, style="Dark.TFrame")
+        legacy_frame.pack(fill=tk.BOTH, expand=True)
+
+        self.randomization_vars["matrix_show_legacy"] = tk.BooleanVar(value=False)
+        ttk.Checkbutton(
+            legacy_frame,
+            text="Show advanced text editor (legacy format)",
+            variable=self.randomization_vars["matrix_show_legacy"],
+            style="Dark.TCheckbutton",
+            command=self._toggle_matrix_legacy_view,
+        ).pack(fill=tk.X, pady=(0, 2))
+
+        legacy_text_container = ttk.Frame(legacy_frame, style="Dark.TFrame")
+        self.randomization_widgets["matrix_legacy_container"] = legacy_text_container
+
+        matrix_text = scrolledtext.ScrolledText(
+            legacy_text_container,
+            height=6,
+            wrap=tk.WORD,
+        )
+        matrix_text.pack(fill=tk.BOTH, expand=True)
+        self.randomization_widgets["matrix_text"] = matrix_text
+        enable_mousewheel(matrix_text)
+        self._bind_autosave_text(matrix_text)
+
+        # Aesthetic gradient section
+        aesthetic_frame = ttk.LabelFrame(
+            body, text="Aesthetic Gradient", style="Dark.TLabelframe", padding=10
+        )
+        aesthetic_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
+
+        aesthetic_header = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
+        aesthetic_header.pack(fill=tk.X)
+        ttk.Checkbutton(
+            aesthetic_header,
+            text="Enable aesthetic gradient adjustments",
+            variable=self.aesthetic_vars["enabled"],
+            style="Dark.TCheckbutton",
+            command=self._update_aesthetic_states,
+        ).pack(side=tk.LEFT)
+
+        ttk.Label(
+            aesthetic_header,
+            textvariable=self.aesthetic_status_var,
+            style="Dark.TLabel",
+            wraplength=400,
+        ).pack(side=tk.LEFT, padx=(12, 0))
+
+        mode_frame = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
+        mode_frame.pack(fill=tk.X, pady=(6, 4))
+        ttk.Label(mode_frame, text="Mode:", style="Dark.TLabel").pack(side=tk.LEFT)
+        script_radio = ttk.Radiobutton(
+            mode_frame,
+            text="Use Aesthetic Gradient script",
+            variable=self.aesthetic_vars["mode"],
+            value="script",
+            style="Dark.TRadiobutton",
+            state=tk.NORMAL if self.aesthetic_script_available else tk.DISABLED,
+            command=self._update_aesthetic_states,
+        )
+        script_radio.pack(side=tk.LEFT, padx=(6, 0))
+        prompt_radio = ttk.Radiobutton(
+            mode_frame,
+            text="Fallback prompt / embedding",
+            variable=self.aesthetic_vars["mode"],
+            value="prompt",
+            style="Dark.TRadiobutton",
+            command=self._update_aesthetic_states,
+        )
+        prompt_radio.pack(side=tk.LEFT, padx=(6, 0))
+        self.aesthetic_widgets["all"].extend([script_radio, prompt_radio])
+
+        embedding_row = ttk.Frame(aesthetic_frame, style="Dark.TFrame")
+        embedding_row.pack(fill=tk.X, pady=(2, 4))
+        ttk.Label(embedding_row, text="Embedding:", style="Dark.TLabel", width=14).pack(
+            side=tk.LEFT
+        )
+        self.aesthetic_embedding_combo = ttk.Combobox(
+            embedding_row,
+            textvariable=self.aesthetic_embedding_var,
+            state="readonly",
+            width=24,
+            values=self.aesthetic_embeddings,
+        )
+        self.aesthetic_embedding_combo.pack(side=tk.LEFT, padx=(4, 0))
+        refresh_btn = ttk.Button(
+            embedding_row, text="Refresh", command=self._refresh_aesthetic_embeddings, width=8
+        )
+        refresh_btn.pack(side=tk.LEFT, padx=(6, 0))
+        self.aesthetic_widgets["all"].extend([self.aesthetic_embedding_combo, refresh_btn])
+
+        script_box = ttk.LabelFrame(
+            aesthetic_frame, text="Script Parameters", style="Dark.TLabelframe", padding=6
+        )
+        script_box.pack(fill=tk.X, pady=(4, 4))
+
+        weight_row = ttk.Frame(script_box, style="Dark.TFrame")
+        weight_row.pack(fill=tk.X, pady=2)
+        ttk.Label(weight_row, text="Weight:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
+        weight_slider = EnhancedSlider(
+            weight_row,
+            from_=0.0,
+            to=1.0,
+            resolution=0.01,
+            variable=self.aesthetic_vars["weight"],
+            width=140,
+        )
+        weight_slider.pack(side=tk.LEFT, padx=(4, 10))
+
+        steps_row = ttk.Frame(script_box, style="Dark.TFrame")
+        steps_row.pack(fill=tk.X, pady=2)
+        ttk.Label(steps_row, text="Steps:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
+        steps_slider = EnhancedSlider(
+            steps_row,
+            from_=0,
+            to=50,
+            resolution=1,
+            variable=self.aesthetic_vars["steps"],
+            width=140,
+        )
+        steps_slider.pack(side=tk.LEFT, padx=(4, 10))
+
+        lr_row = ttk.Frame(script_box, style="Dark.TFrame")
+        lr_row.pack(fill=tk.X, pady=2)
+        ttk.Label(lr_row, text="Learning rate:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
+        lr_entry = ttk.Entry(lr_row, textvariable=self.aesthetic_vars["learning_rate"], width=12)
+        lr_entry.pack(side=tk.LEFT, padx=(4, 10))
+
+        slerp_row = ttk.Frame(script_box, style="Dark.TFrame")
+        slerp_row.pack(fill=tk.X, pady=2)
+        slerp_check = ttk.Checkbutton(
+            slerp_row,
+            text="Enable slerp interpolation",
+            variable=self.aesthetic_vars["slerp"],
+            style="Dark.TCheckbutton",
+            command=self._update_aesthetic_states,
+        )
+        slerp_check.pack(side=tk.LEFT)
+        ttk.Label(slerp_row, text="Angle:", style="Dark.TLabel", width=8).pack(
+            side=tk.LEFT, padx=(10, 0)
+        )
+        slerp_angle_slider = EnhancedSlider(
+            slerp_row,
+            from_=0.0,
+            to=1.0,
+            resolution=0.01,
+            variable=self.aesthetic_vars["slerp_angle"],
+            width=120,
+        )
+        slerp_angle_slider.pack(side=tk.LEFT, padx=(4, 0))
+
+        text_row = ttk.Frame(script_box, style="Dark.TFrame")
+        text_row.pack(fill=tk.X, pady=2)
+        ttk.Label(text_row, text="Text prompt:", style="Dark.TLabel", width=14).pack(side=tk.LEFT)
+        text_entry = ttk.Entry(text_row, textvariable=self.aesthetic_vars["text"])
+        text_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
+        text_neg_check = ttk.Checkbutton(
+            text_row,
+            text="Apply as negative text",
+            variable=self.aesthetic_vars["text_is_negative"],
+            style="Dark.TCheckbutton",
+        )
+        text_neg_check.pack(side=tk.LEFT, padx=(6, 0))
+
+        self.aesthetic_widgets["script"].extend(
+            [
+                weight_slider,
+                steps_slider,
+                lr_entry,
+                slerp_check,
+                slerp_angle_slider,
+                text_entry,
+                text_neg_check,
+            ]
+        )
+
+        prompt_box = ttk.LabelFrame(
+            aesthetic_frame, text="Fallback Prompt Injection", style="Dark.TLabelframe", padding=6
+        )
+        prompt_box.pack(fill=tk.X, pady=(4, 0))
+
+        ttk.Label(
+            prompt_box,
+            text="Optional phrase appended to the positive prompt when using fallback mode.",
+            style="Dark.TLabel",
+            wraplength=700,
+        ).pack(fill=tk.X, pady=(0, 4))
+        fallback_entry = ttk.Entry(prompt_box, textvariable=self.aesthetic_vars["fallback_prompt"])
+        fallback_entry.pack(fill=tk.X, padx=2)
+
+        self.aesthetic_widgets["prompt"].append(fallback_entry)
+        self.aesthetic_widgets["all"].append(fallback_entry)
+        self.aesthetic_widgets["all"].extend(
+            [
+                weight_slider,
+                steps_slider,
+                lr_entry,
+                slerp_check,
+                slerp_angle_slider,
+                text_entry,
+                text_neg_check,
+            ]
+        )
+
+        for key in ("enabled", "prompt_sr_enabled", "wildcards_enabled", "matrix_enabled"):
+            try:
+
+                def _rand_trace_cb(*_args, _k=key):
+                    self._update_randomization_states()
+                    if _k.endswith("enabled"):
+                        self._autosave_preferences_if_needed()
+
+                self.randomization_vars[key].trace_add("write", _rand_trace_cb)
+            except Exception:
+                pass
+        # Persist changes to modes/limits too
+        for key in (
+            "prompt_sr_mode",
+            "wildcard_mode",
+            "matrix_mode",
+            "matrix_prompt_mode",
+            "matrix_limit",
+        ):
+            try:
+                self.randomization_vars[key].trace_add(
+                    "write", lambda *_: self._autosave_preferences_if_needed()
+                )
+            except Exception:
+                pass
+
+        try:
+            self.aesthetic_vars["enabled"].trace_add(
+                "write", lambda *_: self._aesthetic_autosave_handler()
+            )
+            self.aesthetic_vars["mode"].trace_add(
+                "write", lambda *_: self._aesthetic_autosave_handler()
+            )
+            self.aesthetic_vars["slerp"].trace_add(
+                "write", lambda *_: self._aesthetic_autosave_handler()
+            )
+            # Also persist other aesthetic fields on change
+            for _k, _var in self.aesthetic_vars.items():
+                try:
+                    _var.trace_add("write", lambda *_: self._autosave_preferences_if_needed())
+                except Exception:
+                    pass
+        except Exception:
+            pass
+
+        self._update_randomization_states()
+        self._refresh_aesthetic_embeddings()
+        self._update_aesthetic_states()
+
+    def _update_randomization_states(self) -> None:
+        """Enable/disable randomization widgets based on current toggles."""
+
+        vars_dict = getattr(self, "randomization_vars", None)
+        widgets = getattr(self, "randomization_widgets", None)
+        if not vars_dict or not widgets:
+            return
+
+        master = bool(vars_dict.get("enabled", tk.BooleanVar(value=False)).get())
+        section_enabled = {
+            "prompt_sr_text": master
+            and bool(vars_dict.get("prompt_sr_enabled", tk.BooleanVar()).get()),
+            "wildcard_text": master
+            and bool(vars_dict.get("wildcards_enabled", tk.BooleanVar()).get()),
+            "matrix_text": master and bool(vars_dict.get("matrix_enabled", tk.BooleanVar()).get()),
+        }
+
+        for key, widget in widgets.items():
+            if widget is None or isinstance(widget, list):
+                continue
+            state = tk.NORMAL if section_enabled.get(key, master) else tk.DISABLED
+            try:
+                widget.configure(state=state)
+            except (tk.TclError, AttributeError):
+                pass
+        # Throttled autosave to keep last_settings.json aligned with UI
+        self._autosave_preferences_if_needed()
+
+    def _autosave_preferences_if_needed(self, force: bool = False) -> None:
+        """Autosave preferences (including randomization enabled flag) with 2s throttle."""
+        if not getattr(self, "_preferences_ready", False) and not force:
+            return
+        now = time.time()
+        last = getattr(self, "_last_pref_autosave", 0.0)
+        if not force and now - last < 2.0:
+            return
+        self._last_pref_autosave = now
+        try:
+            prefs = self._collect_preferences()
+            if self.preferences_manager.save_preferences(prefs):
+                self.preferences = prefs
+        except Exception:
+            pass
+
+    def _bind_autosave_text(self, widget: tk.Text) -> None:
+        """Bind common events on a Text widget to autosave preferences (throttled)."""
+        try:
+            widget.bind("<KeyRelease>", lambda _e: self._autosave_preferences_if_needed())
+            widget.bind("<FocusOut>", lambda _e: self._autosave_preferences_if_needed())
+        except Exception:
+            pass
+
+    def _bind_autosave_entry(self, widget: tk.Entry) -> None:
+        """Bind common events on an Entry widget to autosave preferences (throttled)."""
+        try:
+            widget.bind("<KeyRelease>", lambda _e: self._autosave_preferences_if_needed())
+            widget.bind("<FocusOut>", lambda _e: self._autosave_preferences_if_needed())
+        except Exception:
+            pass
+
+    def _aesthetic_autosave_handler(self) -> None:
+        """Handler for aesthetic state changes that also triggers autosave."""
+        self._update_aesthetic_states()
+        self._autosave_preferences_if_needed()
+
+    def _get_randomization_text(self, key: str) -> str:
+        """Return trimmed contents of a randomization text widget."""
+
+        widget = self.randomization_widgets.get(key)
+        if widget is None:
+            return ""
+        try:
+            current_state = widget["state"]
+        except (tk.TclError, KeyError):
+            current_state = tk.NORMAL
+
+        try:
+            if current_state == tk.DISABLED:
+                widget.configure(state=tk.NORMAL)
+                value = widget.get("1.0", tk.END)
+                widget.configure(state=tk.DISABLED)
+            else:
+                value = widget.get("1.0", tk.END)
+        except tk.TclError:
+            value = ""
+        return value.strip()
+
+    def _set_randomization_text(self, key: str, value: str) -> None:
+        """Populate a randomization text widget with new content."""
+
+        widget = self.randomization_widgets.get(key)
+        if widget is None:
+            return
+        try:
+            current_state = widget["state"]
+        except (tk.TclError, KeyError):
+            current_state = tk.NORMAL
+
+        try:
+            widget.configure(state=tk.NORMAL)
+            widget.delete("1.0", tk.END)
+            if value:
+                widget.insert(tk.END, value)
+        except tk.TclError:
+            pass
+        finally:
+            try:
+                widget.configure(state=current_state)
+            except tk.TclError:
+                pass
+
+    def _update_aesthetic_states(self) -> None:
+        """Enable/disable aesthetic widgets based on mode and availability."""
+
+        vars_dict = getattr(self, "aesthetic_vars", None)
+        widgets = getattr(self, "aesthetic_widgets", None)
+        if not vars_dict or not widgets:
+            return
+
+        enabled = bool(vars_dict.get("enabled", tk.BooleanVar(value=False)).get())
+        mode = vars_dict.get("mode", tk.StringVar(value="prompt")).get()
+        if mode == "script" and not self.aesthetic_script_available:
+            mode = "prompt"
+            vars_dict["mode"].set("prompt")
+
+        def set_state(target_widgets: list[tk.Widget], active: bool) -> None:
+            for widget in target_widgets:
+                if widget is None:
+                    continue
+                state = tk.NORMAL if active else tk.DISABLED
+                try:
+                    widget.configure(state=state)
+                except (tk.TclError, AttributeError):
+                    if hasattr(widget, "configure_state"):
+                        try:
+                            widget.configure_state("normal" if active else "disabled")
+                        except Exception:
+                            continue
+
+        set_state(widgets.get("all", []), enabled)
+        set_state(widgets.get("script", []), enabled and mode == "script")
+        set_state(widgets.get("prompt", []), enabled and mode == "prompt")
+
+        if self.aesthetic_script_available:
+            status = "Aesthetic extension detected"
+        else:
+            status = "Extension not detected – fallback mode only"
+        if len(self.aesthetic_embeddings) <= 1:
+            status += " (no embeddings found)"
+        self.aesthetic_status_var.set(status)
+
+    def _detect_aesthetic_extension_root(self):
+        """Locate the Aesthetic Gradient extension directory if present."""
+
+        candidates: list[Path] = []
+        env_root = os.environ.get("WEBUI_ROOT")
+        if env_root:
+            candidates.append(Path(env_root))
+        candidates.append(Path.home() / "stable-diffusion-webui")
+        repo_candidate = Path(__file__).resolve().parents[3] / "stable-diffusion-webui"
+        candidates.append(repo_candidate)
+        local_candidate = Path("..") / "stable-diffusion-webui"
+        candidates.append(local_candidate.resolve())
+
+        detected, extension_dir = detect_aesthetic_extension(candidates)
+        if detected and extension_dir:
+            return True, extension_dir
+        return False, None
+
+    def _refresh_aesthetic_embeddings(self, *_):
+        """Reload available aesthetic embedding names from disk."""
+
+        embeddings = ["None"]
+        if self.aesthetic_extension_root:
+            embed_dir = self.aesthetic_extension_root / "aesthetic_embeddings"
+            if embed_dir.exists():
+                for file in sorted(embed_dir.glob("*.pt")):
+                    embeddings.append(file.stem)
+        self.aesthetic_embeddings = sorted(
+            dict.fromkeys(embeddings), key=lambda name: (name != "None", name.lower())
+        )
+
+        if self.aesthetic_embedding_var.get() not in self.aesthetic_embeddings:
+            self.aesthetic_embedding_var.set("None")
+
+        if hasattr(self, "aesthetic_embedding_combo"):
+            try:
+                self.aesthetic_embedding_combo["values"] = self.aesthetic_embeddings
+            except Exception:
+                pass
+
+        if self.aesthetic_script_available:
+            status = "Aesthetic extension detected"
+        else:
+            status = "Extension not detected – fallback mode only"
+        if len(self.aesthetic_embeddings) <= 1:
+            status += " (no embeddings found)"
+        self.aesthetic_status_var.set(status)
+
+    def _collect_randomization_config(self) -> dict[str, Any]:
+        """Collect randomization settings into a serializable dict."""
+
+        vars_dict = getattr(self, "randomization_vars", None)
+        if not vars_dict:
+            return {}
+
+        sr_text = self._get_randomization_text("prompt_sr_text")
+        wildcard_text = self._get_randomization_text("wildcard_text")
+
+        # Collect matrix data from UI fields (not legacy text)
+        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
+        base_prompt = base_prompt_widget.get() if base_prompt_widget else ""
+
+        matrix_slots = []
+        for row in self.randomization_widgets.get("matrix_slot_rows", []):
+            name = row["name_entry"].get().strip()
+            values_text = row["values_entry"].get().strip()
+            if name and values_text:
+                values = [v.strip() for v in values_text.split("|") if v.strip()]
+                if values:
+                    matrix_slots.append({"name": name, "values": values})
+
+        # Build raw_text for backward compatibility
+        matrix_raw_lines = []
+        if base_prompt:
+            matrix_raw_lines.append(f"# Base: {base_prompt}")
+        matrix_raw_lines.append(self._format_matrix_lines(matrix_slots))
+        matrix_raw_text = "\n".join(matrix_raw_lines)
+
+        return {
+            "enabled": bool(vars_dict["enabled"].get()),
+            "prompt_sr": {
+                "enabled": bool(vars_dict["prompt_sr_enabled"].get()),
+                "mode": vars_dict["prompt_sr_mode"].get(),
+                "rules": self._parse_prompt_sr_rules(sr_text),
+                "raw_text": sr_text,
+            },
+            "wildcards": {
+                "enabled": bool(vars_dict["wildcards_enabled"].get()),
+                "mode": vars_dict["wildcard_mode"].get(),
+                "tokens": self._parse_token_lines(wildcard_text),
+                "raw_text": wildcard_text,
+            },
+            "matrix": {
+                "enabled": bool(vars_dict["matrix_enabled"].get()),
+                "mode": vars_dict["matrix_mode"].get(),
+                "prompt_mode": vars_dict["matrix_prompt_mode"].get(),
+                "limit": int(vars_dict["matrix_limit"].get() or 0),
+                "slots": matrix_slots,
+                "raw_text": matrix_raw_text,
+                "base_prompt": base_prompt,
+            },
+        }
+
+    def _load_randomization_config(self, config: dict[str, Any]) -> None:
+        """Populate randomization UI from configuration values."""
+
+        vars_dict = getattr(self, "randomization_vars", None)
+        if not vars_dict:
+            return
+
+        try:
+            data = (config or {}).get("randomization", {})
+            vars_dict["enabled"].set(bool(data.get("enabled", False)))
+
+            sr = data.get("prompt_sr", {})
+            vars_dict["prompt_sr_enabled"].set(bool(sr.get("enabled", False)))
+            vars_dict["prompt_sr_mode"].set(sr.get("mode", "random"))
+            sr_text = sr.get("raw_text") or self._format_prompt_sr_rules(sr.get("rules", []))
+            self._set_randomization_text("prompt_sr_text", sr_text)
+
+            wildcards = data.get("wildcards", {})
+            vars_dict["wildcards_enabled"].set(bool(wildcards.get("enabled", False)))
+            vars_dict["wildcard_mode"].set(wildcards.get("mode", "random"))
+            wildcard_text = wildcards.get("raw_text") or self._format_token_lines(
+                wildcards.get("tokens", [])
+            )
+            self._set_randomization_text("wildcard_text", wildcard_text)
+
+            matrix = data.get("matrix", {})
+            vars_dict["matrix_enabled"].set(bool(matrix.get("enabled", False)))
+            vars_dict["matrix_mode"].set(matrix.get("mode", "fanout"))
+            vars_dict["matrix_prompt_mode"].set(matrix.get("prompt_mode", "replace"))
+            vars_dict["matrix_limit"].set(int(matrix.get("limit", 8)))
+
+            base_prompt = matrix.get("base_prompt", "")
+            base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
+            if base_prompt_widget:
+                base_prompt_widget.delete(0, tk.END)
+                base_prompt_widget.insert(0, base_prompt)
+
+            slots = matrix.get("slots", [])
+            self._clear_matrix_slot_rows()
+            for slot in slots:
+                name = slot.get("name", "")
+                values = slot.get("values", [])
+                if name and values:
+                    values_str = " | ".join(values)
+                    self._add_matrix_slot_row(name, values_str)
+
+            matrix_text = matrix.get("raw_text") or self._format_matrix_lines(slots)
+            self._set_randomization_text("matrix_text", matrix_text)
+
+            self._update_randomization_states()
+        except Exception as exc:
+            logger.error("Failed to load randomization config: %s", exc)
+
+    def _collect_aesthetic_config(self) -> dict[str, Any]:
+        """Collect aesthetic gradient settings."""
+
+        vars_dict = getattr(self, "aesthetic_vars", None)
+        if not vars_dict:
+            return {}
+
+        mode = vars_dict["mode"].get()
+        if mode == "script" and not self.aesthetic_script_available:
+            mode = "prompt"
+
+        def _safe_float(value: Any, default: float) -> float:
+            try:
+                return float(value)
+            except (TypeError, ValueError):
+                return default
+
+        config = {
+            "enabled": bool(vars_dict["enabled"].get()),
+            "mode": mode,
+            "weight": _safe_float(vars_dict["weight"].get(), 0.9),
+            "steps": int(vars_dict["steps"].get() or 0),
+            "learning_rate": _safe_float(vars_dict["learning_rate"].get(), 0.0001),
+            "slerp": bool(vars_dict["slerp"].get()),
+            "slerp_angle": _safe_float(vars_dict["slerp_angle"].get(), 0.1),
+            "embedding": self.aesthetic_embedding_var.get() or "None",
+            "text": vars_dict["text"].get().strip(),
+            "text_is_negative": bool(vars_dict["text_is_negative"].get()),
+            "fallback_prompt": vars_dict["fallback_prompt"].get().strip(),
+        }
+        return config
+
+    def _load_aesthetic_config(self, config: dict[str, Any]) -> None:
+        """Populate aesthetic gradient UI from stored configuration."""
+
+        vars_dict = getattr(self, "aesthetic_vars", None)
+        if not vars_dict:
+            return
+
+        data = (config or {}).get("aesthetic", {})
+        vars_dict["enabled"].set(bool(data.get("enabled", False)))
+        desired_mode = data.get("mode", "script")
+        if desired_mode == "script" and not self.aesthetic_script_available:
+            desired_mode = "prompt"
+        vars_dict["mode"].set(desired_mode)
+        vars_dict["weight"].set(float(data.get("weight", 0.9)))
+        vars_dict["steps"].set(int(data.get("steps", 5)))
+        vars_dict["learning_rate"].set(str(data.get("learning_rate", 0.0001)))
+        vars_dict["slerp"].set(bool(data.get("slerp", False)))
+        vars_dict["slerp_angle"].set(float(data.get("slerp_angle", 0.1)))
+        vars_dict["text"].set(data.get("text", ""))
+        vars_dict["text_is_negative"].set(bool(data.get("text_is_negative", False)))
+        vars_dict["fallback_prompt"].set(data.get("fallback_prompt", ""))
+
+        embedding = data.get("embedding", "None") or "None"
+        if embedding not in self.aesthetic_embeddings:
+            embedding = "None"
+        self.aesthetic_embedding_var.set(embedding)
+        self._update_aesthetic_states()
+
+    @staticmethod
+    def _parse_prompt_sr_rules(text: str) -> list[dict[str, Any]]:
+        """Parse Prompt S/R rule definitions."""
+
+        rules: list[dict[str, Any]] = []
+        for raw_line in text.splitlines():
+            line = raw_line.strip()
+            if not line or line.startswith("#") or "=>" not in line:
+                continue
+            search, replacements = line.split("=>", 1)
+            search = search.strip()
+            replacement_values = [item.strip() for item in replacements.split("|") if item.strip()]
+            if search and replacement_values:
+                rules.append({"search": search, "replacements": replacement_values})
+        return rules
+
+    @staticmethod
+    def _format_prompt_sr_rules(rules: list[dict[str, Any]]) -> str:
+        """Format Prompt S/R rules back into editable text."""
+
+        lines: list[str] = []
+        for entry in rules or []:
+            search = entry.get("search", "")
+            replacements = entry.get("replacements", [])
+            if not search or not replacements:
+                continue
+            lines.append(f"{search} => {' | '.join(replacements)}")
+        return "\n".join(lines)
+
+    @staticmethod
+    def _parse_token_lines(text: str) -> list[dict[str, Any]]:
+        """Parse wildcard token definitions."""
+
+        tokens: list[dict[str, Any]] = []
+        for raw_line in text.splitlines():
+            line = raw_line.strip()
+            if not line or line.startswith("#") or ":" not in line:
+                continue
+            token, values = line.split(":", 1)
+            base_name = token.strip().strip("_")
+            value_list = [item.strip() for item in values.split("|") if item.strip()]
+            if base_name and value_list:
+                tokens.append({"token": f"__{base_name}__", "values": value_list})
+        return tokens
+
+    @staticmethod
+    def _format_token_lines(tokens: list[dict[str, Any]]) -> str:
+        """Format wildcard tokens back into editable text."""
+
+        lines: list[str] = []
+        for token in tokens or []:
+            name = token.get("token", "")
+            values = token.get("values", [])
+            if not name or not values:
+                continue
+            stripped_name = (
+                name.strip("_") if name.startswith("__") and name.endswith("__") else name
+            )
+            lines.append(f"{stripped_name}: {' | '.join(values)}")
+        return "\n".join(lines)
+
+    @staticmethod
+    def _parse_matrix_lines(text: str) -> list[dict[str, Any]]:
+        """Parse matrix slot definitions."""
+
+        slots: list[dict[str, Any]] = []
+        for raw_line in text.splitlines():
+            line = raw_line.strip()
+            if not line or line.startswith("#") or ":" not in line:
+                continue
+            slot, values = line.split(":", 1)
+            slot_name = slot.strip()
+            value_list = [item.strip() for item in values.split("|") if item.strip()]
+            if slot_name and value_list:
+                slots.append({"name": slot_name, "values": value_list})
+        return slots
+
+    @staticmethod
+    def _format_matrix_lines(slots: list[dict[str, Any]]) -> str:
+        """Format matrix slots back into editable text."""
+
+        lines: list[str] = []
+        for slot in slots or []:
+            name = slot.get("name", "")
+            values = slot.get("values", [])
+            if not name or not values:
+                continue
+            lines.append(f"{name}: {' | '.join(values)}")
+        return "\n".join(lines)
+
+    def _add_matrix_slot_row(self, slot_name: str = "", slot_values: str = "") -> None:
+        """Add a new matrix slot row to the UI."""
+
+        slots_frame = self.randomization_widgets.get("matrix_slots_frame")
+        if not slots_frame:
+            return
+
+        row_frame = ttk.Frame(slots_frame, style="Dark.TFrame")
+        row_frame.pack(fill=tk.X, pady=2)
+
+        # Slot name entry
+        ttk.Label(row_frame, text="Slot:", style="Dark.TLabel", width=6).pack(side=tk.LEFT)
+        name_entry = ttk.Entry(row_frame, width=15)
+        name_entry.pack(side=tk.LEFT, padx=(2, 4))
+        if slot_name:
+            name_entry.insert(0, slot_name)
+        # Autosave when editing slot name
+        self._bind_autosave_entry(name_entry)
+
+        # Values entry
+        ttk.Label(row_frame, text="Options (| separated):", style="Dark.TLabel").pack(
+            side=tk.LEFT, padx=(4, 2)
+        )
+        values_entry = ttk.Entry(row_frame)
+        values_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 4))
+        if slot_values:
+            values_entry.insert(0, slot_values)
+        # Autosave when editing slot values
+        self._bind_autosave_entry(values_entry)
+
+        # Remove button
+        remove_btn = ttk.Button(
+            row_frame,
+            text="−",
+            width=3,
+            command=lambda: self._remove_matrix_slot_row(row_frame),
+        )
+        remove_btn.pack(side=tk.LEFT)
+
+        # Store row data
+        row_data = {
+            "frame": row_frame,
+            "name_entry": name_entry,
+            "values_entry": values_entry,
+        }
+        self.randomization_widgets["matrix_slot_rows"].append(row_data)
+
+        # Update scroll region
+        canvas = self.randomization_widgets.get("matrix_slots_canvas")
+        if canvas:
+            canvas.configure(scrollregion=canvas.bbox("all"))
+
+    def _remove_matrix_slot_row(self, row_frame: tk.Widget) -> None:
+        """Remove a matrix slot row from the UI."""
+
+        slot_rows = self.randomization_widgets.get("matrix_slot_rows", [])
+        self.randomization_widgets["matrix_slot_rows"] = [
+            row for row in slot_rows if row["frame"] != row_frame
+        ]
+        row_frame.destroy()
+
+        # Update scroll region
+        canvas = self.randomization_widgets.get("matrix_slots_canvas")
+        if canvas:
+            canvas.configure(scrollregion=canvas.bbox("all"))
+
+    def _clear_matrix_slot_rows(self) -> None:
+        """Clear all matrix slot rows from the UI."""
+
+        for row in self.randomization_widgets.get("matrix_slot_rows", []):
+            row["frame"].destroy()
+        self.randomization_widgets["matrix_slot_rows"] = []
+
+        # Update scroll region
+        canvas = self.randomization_widgets.get("matrix_slots_canvas")
+        if canvas:
+            canvas.configure(scrollregion=canvas.bbox("all"))
+
+    def _toggle_matrix_legacy_view(self) -> None:
+        """Toggle between modern UI and legacy text editor for matrix config."""
+
+        show_legacy = self.randomization_vars.get("matrix_show_legacy", tk.BooleanVar()).get()
+        legacy_container = self.randomization_widgets.get("matrix_legacy_container")
+
+        if legacy_container:
+            if show_legacy:
+                # Sync from UI to legacy text before showing
+                self._sync_matrix_ui_to_text()
+                legacy_container.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
+            else:
+                # Sync from legacy text to UI before hiding
+                self._sync_matrix_text_to_ui()
+                legacy_container.pack_forget()
+
+    def _sync_matrix_ui_to_text(self) -> None:
+        """Sync matrix UI fields to the legacy text widget."""
+
+        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
+        base_prompt = base_prompt_widget.get() if base_prompt_widget else ""
+
+        slots = []
+        for row in self.randomization_widgets.get("matrix_slot_rows", []):
+            name = row["name_entry"].get().strip()
+            values_text = row["values_entry"].get().strip()
+            if name and values_text:
+                slots.append(
+                    {
+                        "name": name,
+                        "values": [v.strip() for v in values_text.split("|") if v.strip()],
+                    }
+                )
+
+        # Build legacy format: base prompt on first line, then slots
+        lines = []
+        if base_prompt:
+            lines.append(f"# Base: {base_prompt}")
+        lines.append(self._format_matrix_lines(slots))
+
+        matrix_text = self.randomization_widgets.get("matrix_text")
+        if matrix_text:
+            matrix_text.delete("1.0", tk.END)
+            matrix_text.insert("1.0", "\n".join(lines))
+
+    def _sync_matrix_text_to_ui(self) -> None:
+        """Sync legacy text widget to matrix UI fields."""
+
+        matrix_text = self.randomization_widgets.get("matrix_text")
+        if not matrix_text:
+            return
+
+        text = matrix_text.get("1.0", tk.END).strip()
+        lines = text.splitlines()
+
+        # Check for base prompt marker
+        base_prompt = ""
+        slot_lines = []
+        for line in lines:
+            line_stripped = line.strip()
+            if line_stripped.startswith("# Base:"):
+                base_prompt = line_stripped[7:].strip()
+            elif line_stripped and not line_stripped.startswith("#"):
+                slot_lines.append(line_stripped)
+
+        # Update base prompt
+        base_prompt_widget = self.randomization_widgets.get("matrix_base_prompt")
+        if base_prompt_widget:
+            base_prompt_widget.delete(0, tk.END)
+            base_prompt_widget.insert(0, base_prompt)
+
+        # Parse slots and rebuild UI
+        slots = self._parse_matrix_lines("\n".join(slot_lines))
+        self._clear_matrix_slot_rows()
+        for slot in slots:
+            values_str = " | ".join(slot.get("values", []))
+            self._add_matrix_slot_row(slot.get("name", ""), values_str)
+        return "\n".join(lines)
+
+    def _build_pipeline_controls_panel(self, parent):
+        """Build compact pipeline controls panel using PipelineControlsPanel component, with state restore."""
+        # Save previous state if panel exists
+        prev_state = None
+        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
+            try:
+                prev_state = self.pipeline_controls_panel.get_state()
+            except Exception as e:
+                logger.warning(f"Failed to get PipelineControlsPanel state: {e}")
+        # Destroy old panel if present
+        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
+            self.pipeline_controls_panel.destroy()
+        # Determine initial state for the new panel
+        initial_state = (
+            prev_state if prev_state is not None else self.preferences.get("pipeline_controls")
+        )
+
+        # Create the PipelineControlsPanel component
+        stage_vars = {
+            "txt2img": self.txt2img_enabled,
+            "img2img": self.img2img_enabled,
+            "adetailer": self.adetailer_enabled,
+            "upscale": self.upscale_enabled,
+            "video": self.video_enabled,
+        }
+
+        self.pipeline_controls_panel = PipelineControlsPanel(
+            parent,
+            initial_state=initial_state,
+            stage_vars=stage_vars,
+            show_variant_controls=False,
+            on_change=self._on_pipeline_controls_changed,
+            style="Dark.TFrame",
+        )
+        # Place inside parent with pack for consistency with surrounding layout
+        self.pipeline_controls_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
+        # Restore previous state if available
+        if prev_state:
+            try:
+                self.pipeline_controls_panel.set_state(prev_state)
+            except Exception as e:
+                logger.warning(f"Failed to restore PipelineControlsPanel state: {e}")
+        # Keep shared references for non-stage settings
+        self.video_enabled = self.pipeline_controls_panel.video_enabled
+        self.loop_type_var = self.pipeline_controls_panel.loop_type_var
+        self.loop_count_var = self.pipeline_controls_panel.loop_count_var
+        self.pack_mode_var = self.pipeline_controls_panel.pack_mode_var
+        self.images_per_prompt_var = self.pipeline_controls_panel.images_per_prompt_var
+
+    def _build_config_display_tab(self, notebook):
+        """Build interactive configuration tabs using ConfigPanel"""
+
+        config_frame = ttk.Frame(notebook, style="Dark.TFrame")
+        notebook.add(config_frame, text="⚙️ Configuration")
+
+        # Create ConfigPanel component
+        self.config_panel = ConfigPanel(config_frame, coordinator=self, style="Dark.TFrame")
+        self.config_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
+
+        # Set up variable references for backward compatibility
+        self.txt2img_vars = self.config_panel.txt2img_vars
+        self.img2img_vars = self.config_panel.img2img_vars
+        self.upscale_vars = self.config_panel.upscale_vars
+        self.api_vars = self.config_panel.api_vars
+        self._bind_config_panel_persistence_hooks()
+
+    def _build_bottom_panel(self, parent):
+        """Build bottom panel with logs and action buttons"""
+        bottom_frame = ttk.Frame(
+            parent, style=getattr(self.theme, "SURFACE_FRAME_STYLE", "Dark.TFrame")
+        )
+        bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
+
+        # Compact action buttons frame
+        actions_frame = ttk.Frame(bottom_frame, style="Dark.TFrame")
+        actions_frame.pack(fill=tk.X, pady=(0, 5))
+
+        # Main execution buttons with accent colors
+        main_buttons = ttk.Frame(actions_frame, style="Dark.TFrame")
+        main_buttons.pack(side=tk.LEFT)
+
+        if getattr(self, "run_pipeline_btn", None) is None:
+            self.run_pipeline_btn = ttk.Button(
+                main_buttons,
+                text="Run Full Pipeline",
+                command=self._run_full_pipeline,
+                style="Success.TButton",
+            )
+            self.run_pipeline_btn.pack(side=tk.LEFT, padx=(0, 10))
+            self._attach_tooltip(
+                self.run_pipeline_btn,
+                "Process every highlighted pack sequentially using the current configuration. Override mode applies when enabled.",
+            )
+            self.run_button = self.run_pipeline_btn
+
+        txt2img_only_btn = ttk.Button(
+            main_buttons,
+            text="txt2img Only",
+            command=self._run_txt2img_only,
+            style="Dark.TButton",
+        )
+        txt2img_only_btn.pack(side=tk.LEFT, padx=(0, 10))
+        self._attach_tooltip(
+            txt2img_only_btn,
+            "Generate txt2img outputs for the selected pack(s) only.",
+        )
+
+        upscale_only_btn = ttk.Button(
+            main_buttons,
+            text="Upscale Only",
+            command=self._run_upscale_only,
+            style="Dark.TButton",
+        )
+        upscale_only_btn.pack(side=tk.LEFT, padx=(0, 10))
+        self._attach_tooltip(
+            upscale_only_btn,
+            "Run only the upscale stage for the currently selected outputs (skips txt2img/img2img).",
+        )
+
+        create_video_btn = ttk.Button(
+            main_buttons, text="Create Video", command=self._create_video, style="Dark.TButton"
+        )
+        create_video_btn.pack(side=tk.LEFT, padx=(0, 10))
+        self._attach_tooltip(create_video_btn, "Combine rendered images into a video file.")
+
+        # Utility buttons
+        util_buttons = ttk.Frame(actions_frame, style="Dark.TFrame")
+        util_buttons.pack(side=tk.RIGHT)
+
+        open_output_btn = ttk.Button(
+            util_buttons,
+            text="Open Output",
+            command=self._open_output_folder,
+            style="Dark.TButton",
+        )
+        open_output_btn.pack(side=tk.LEFT, padx=(0, 10))
+        self._attach_tooltip(
+            open_output_btn, "Open the output directory in your system file browser."
+        )
+
+        if getattr(self, "stop_button", None) is None:
+            stop_btn = ttk.Button(
+                util_buttons, text="Stop", command=self._on_cancel_clicked, style="Danger.TButton"
+            )
+            stop_btn.pack(side=tk.LEFT, padx=(0, 10))
+            self._attach_tooltip(
+                stop_btn,
+                "Request cancellation of the pipeline run. The current stage finishes before stopping.",
+            )
+            self.stop_button = stop_btn
+
+        exit_btn = ttk.Button(
+            util_buttons, text="Exit", command=self._graceful_exit, style="Danger.TButton"
+        )
+        exit_btn.pack(side=tk.LEFT)
+        self._attach_tooltip(exit_btn, "Gracefully stop background work and close StableNew.")
+
+        # Reparent early log panel to bottom_frame
+        # (log_panel was created early in __init__ to avoid AttributeError)
+        # Create log panel directly with bottom_frame as parent
+        self.log_panel = LogPanel(bottom_frame, coordinator=self, height=18, style="Dark.TFrame")
+        self.log_panel.pack(fill=tk.BOTH, expand=True)
+        self.log_panel.pack_propagate(False)
+        self.add_log = self.log_panel.append
+        self.log_text = getattr(self.log_panel, "log_text", None)
+        if self.log_text is not None:
+            enable_mousewheel(self.log_text)
+        self._ensure_log_panel_min_height()
+
+        # Attach logging handler to redirect standard logging to GUI
+        if not hasattr(self, "gui_log_handler"):
+            self.gui_log_handler = TkinterLogHandler(self.log_panel)
+            logging.getLogger().addHandler(self.gui_log_handler)
+
+        self._build_api_status_frame(bottom_frame)
+        self._build_status_bar(bottom_frame)
+        self._refresh_txt2img_validation()
+
+    def _ensure_log_panel_min_height(self) -> None:
+        """Ensure the log panel retains a minimum visible height."""
+        if not hasattr(self, "log_panel"):
+            return
+        min_lines = max(1, getattr(self, "_log_min_lines", 7))
+        text_widget = getattr(self.log_panel, "log_text", None)
+        if text_widget is not None:
+            try:
+                current_height = int(text_widget.cget("height"))
+            except Exception:
+                current_height = min_lines
+            if current_height < min_lines:
+                try:
+                    text_widget.configure(height=min_lines)
+                except Exception:
+                    pass
+
+        def _apply_min_height():
+            try:
+                self.log_panel.update_idletasks()
+                line_height = 18
+                try:
+                    if text_widget is not None:
+                        info = text_widget.dlineinfo("1.0")
+                        if info:
+                            line_height = info[3] or line_height
+                except Exception:
+                    pass
+                min_height = int(line_height * min_lines + 60)
+                self.log_panel.configure(height=min_height)
+                self.log_panel.pack_propagate(False)
+                if (
+                    hasattr(self, "_vertical_split")
+                    and hasattr(self, "_bottom_pane")
+                    and getattr(self, "_vertical_split", None) is not None
+                ):
+                    try:
+                        self._vertical_split.paneconfigure(self._bottom_pane, minsize=min_height + 120)
+                    except Exception:
+                        pass
+            except Exception:
+                pass
+
+        try:
+            self.root.after(0, _apply_min_height)
+        except Exception:
+            _apply_min_height()
+
+    def _build_status_bar(self, parent):
+        """Build status bar showing current state"""
+        status_bar = getattr(self, "status_bar_v2", None)
+        if status_bar is None:
+            status_bar = StatusBarV2(parent, controller=self.controller, theme=self.theme)
+            self.status_bar_v2 = status_bar
+        try:
+            status_bar.pack_forget()
+        except Exception:
+            pass
+        try:
+            status_bar.pack(fill=tk.X, pady=(4, 0))
+        except Exception:
+            pass
+
+        status_frame = getattr(status_bar, "body", status_bar)
+        status_frame.configure(height=52)
+        status_frame.pack_propagate(False)
+        try:
+            status_bar.set_idle()
+        except Exception:
+            pass
+        self._status_adapter = StatusAdapterV2(status_bar)
+
+        self.progress_message_var = tk.StringVar(value=self._progress_idle_message)
+        self.progress_status_var = self.progress_message_var
+        ttk.Label(status_frame, textvariable=self.progress_message_var, style="Dark.TLabel").pack(
+            side=tk.LEFT, padx=10
+        )
+
+    def _build_ai_settings_button(self, parent) -> None:
+        """Optional AI settings button guarded by feature flag."""
+        try:
+            btn = ttk.Button(
+                parent,
+                text="Ask AI for Settings",
+                command=self._on_ask_ai_for_settings_clicked,
+                state="normal",
+            )
+            btn.pack(anchor=tk.W, pady=(10, 0))
+            self._ai_settings_button = btn
+        except Exception:
+            self._ai_settings_button = None
+
+    def _setup_state_callbacks(self):
+        """Setup callbacks for state transitions"""
+
+        def on_state_change(old_state, new_state):
+            """Called when state changes"""
+            mapped = {
+                GUIState.IDLE: "idle",
+                GUIState.RUNNING: "running",
+                GUIState.STOPPING: "running",
+                GUIState.ERROR: "error",
+            }
+            self._on_pipeline_state_change(mapped.get(new_state, "idle"))
+            if new_state == GUIState.RUNNING:
+                self.progress_message_var.set("Running pipeline...")
+            elif new_state == GUIState.STOPPING:
+                self.progress_message_var.set("Cancelling pipeline...")
+            elif new_state == GUIState.ERROR:
+                self.progress_message_var.set("Error")
+            elif new_state == GUIState.IDLE and old_state == GUIState.STOPPING:
+                self.progress_message_var.set("Ready")
+            elif new_state == GUIState.IDLE:
+                self.progress_message_var.set("Ready")
+
+            # Update button states
+            if new_state == GUIState.RUNNING:
+                self._apply_run_button_state()
+            elif new_state == GUIState.STOPPING:
+                self._apply_run_button_state()
+            elif new_state == GUIState.IDLE:
+                self._apply_run_button_state()
+            elif new_state == GUIState.ERROR:
+                self._apply_run_button_state()
+
+        self.state_manager.on_transition(on_state_change)
+
+    def _wire_progress_callbacks(self) -> None:
+        controller = getattr(self, "controller", None)
+        if controller is None:
+            return
+
+        callbacks = {
+            "on_progress": self._on_pipeline_progress,
+            "on_state_change": self._on_pipeline_state_change,
+        }
+
+        for name in (
+            "configure_progress_callbacks",
+            "register_progress_callbacks",
+            "set_progress_callbacks",
+        ):
+            method = getattr(controller, name, None)
+            if not callable(method):
+                continue
+            try:
+                method(**callbacks)
+                return
+            except TypeError:
+                try:
+                    code = method.__code__
+                    param_names = code.co_varnames[: code.co_argcount]
+                    filtered = {k: v for k, v in callbacks.items() if k in param_names}
+                    if filtered:
+                        method(**filtered)
+                        return
+                except Exception:
+                    continue
+
+    def _on_pipeline_progress(
+        self,
+        progress: float | None = None,
+        total: float | None = None,
+        eta_seconds: float | None = None,
+    ) -> None:
+        try:
+            progress_val = float(progress) if progress is not None else None
+        except (TypeError, ValueError):
+            progress_val = None
+        try:
+            total_val = float(total) if total is not None else None
+        except (TypeError, ValueError):
+            total_val = None
+
+        fraction = None
+        if progress_val is not None and total_val and total_val > 0:
+            fraction = progress_val / total_val
+
+        try:
+            eta_val = float(eta_seconds) if eta_seconds is not None else None
+        except (TypeError, ValueError):
+            eta_val = None
+
+        def apply():
+            if hasattr(self, "_status_adapter"):
+                self._status_adapter.on_progress(
+                    {"percent": (fraction * 100) if fraction is not None else None, "eta_seconds": eta_val}
+                )
+
+        apply()
+        try:
+            self.root.after(0, apply)
+        except Exception:
+            pass
+
+    def _on_ask_ai_for_settings_clicked(self) -> None:
+        try:
+            baseline = self._get_config_from_forms()
+            pack = None
+            if hasattr(self, "current_selected_packs") and self.current_selected_packs:
+                pack = getattr(self.current_selected_packs[0], "name", None) or str(
+                    self.current_selected_packs[0]
+                )
+            suggestion = self.settings_suggestion_controller.request_suggestion(
+                SuggestionIntent.HIGH_DETAIL,
+                pack,
+                baseline,
+                dataset_snapshot=None,
+            )
+            new_config = self.settings_suggestion_controller.apply_suggestion_to_config(
+                baseline, suggestion
+            )
+            self._load_config_into_forms(new_config)
+            self.log_message("Applied AI settings suggestion (stub).", "INFO")
+        except Exception as exc:
+            self.log_message(f"AI settings suggestion failed: {exc}", "WARNING")
+
+    def _on_pipeline_state_change(self, state: str | None) -> None:
+        normalized = (state or "").lower()
+
+        def apply():
+            if hasattr(self, "_status_adapter"):
+                self._status_adapter.on_state_change(normalized)
+
+        apply()
+        try:
+            self.root.after(0, apply)
+        except Exception:
+            pass
+
+    def _signal_pipeline_finished(self, event=None) -> None:
+        """Notify tests waiting on lifecycle_event that the run has terminated."""
+
+        event = event or getattr(self.controller, "lifecycle_event", None)
+        if event is None:
+            logger.debug("No lifecycle_event available to signal")
+            return
+        try:
+            event.set()
+        except Exception:
+            logger.debug("Failed to signal lifecycle_event", exc_info=True)
+
+    def _normalize_api_url(self, value: Any) -> str:
+        """Ensure downstream API clients always receive a fully-qualified URL."""
+        if isinstance(value, (int, float)):
+            return f"http://127.0.0.1:{int(value)}"
+        url = str(value or "").strip()
+        if not url:
+            return "http://127.0.0.1:7860"
+        lowered = url.lower()
+        if lowered.startswith(("http://", "https://")):
+            return url
+        if lowered.startswith("://"):
+            return f"http{url}"
+        if lowered.startswith(("127.", "localhost")):
+            return f"http://{url}"
+        if lowered.startswith(":"):
+            return f"http://127.0.0.1{url}"
+        return f"http://{url}"
+
+    def _set_api_url_var(self, value: Any) -> None:
+        if hasattr(self, "api_url_var"):
+            self.api_url_var.set(self._normalize_api_url(value))
+
+    def _poll_controller_logs(self):
+        """Poll controller for log messages and display them"""
+        messages = self.controller.get_log_messages()
+        for msg in messages:
+            self.log_message(msg.message, msg.level)
+            self._apply_status_text(msg.message)
+
+        # Schedule next poll
+        self.root.after(100, self._poll_controller_logs)
+
+    # Class-level API check method
+    def _check_api_connection(self):
+        """Check API connection status with improved diagnostics."""
+
+        if is_gui_test_mode():
+            return
+        if os.environ.get("STABLENEW_NO_WEBUI", "").lower() in {"1", "true", "yes"}:
+            return
+
+        try:
+            initial_api_url = self._normalize_api_url(self.api_url_var.get())
+        except Exception:
+            initial_api_url = self._normalize_api_url("")
+        timeout_value: int | None = None
+        if hasattr(self, "api_vars") and "timeout" in self.api_vars:
+            try:
+                timeout_value = int(self.api_vars["timeout"].get() or 30)
+            except Exception:
+                timeout_value = None
+
+        def check_in_thread(initial_url: str, timeout: int | None):
+            api_url = initial_url
+
+            # Try the specified URL first
+            self.log_message("?? Checking API connection...", "INFO")
+
+            # First try direct connection
+            client = SDWebUIClient(api_url)
+            # Apply configured timeout from API tab (keeps UI responsive on failures)
+            if timeout:
+                try:
+                    client.timeout = timeout
+                except Exception:
+                    pass
+            if client.check_api_ready():
+                # Perform health check
+                health = validate_webui_health(api_url)
+
+                self.api_connected = True
+                self.client = client
+                self.pipeline = Pipeline(client, self.structured_logger)
+                self.controller.set_pipeline(self.pipeline)
+
+                self.root.after(0, lambda: self._update_api_status(True, api_url))
+
+                if health["models_loaded"]:
+                    self.log_message(
+                        f"? API connected! Found {health.get('model_count', 0)} models", "SUCCESS"
+                    )
+                else:
+                    self.log_message("?? API connected but no models loaded", "WARNING")
+                return
+
+            # If direct connection failed, try port discovery
+            self.log_message("?? Trying port discovery...", "INFO")
+            discovered_url = find_webui_api_port()
+
+            if discovered_url:
+                # Test the discovered URL
+                client = SDWebUIClient(discovered_url)
+                if timeout:
+                    try:
+                        client.timeout = timeout
+                    except Exception:
+                        pass
+                if client.check_api_ready():
+                    health = validate_webui_health(discovered_url)
+
+                    self.api_connected = True
+                    self.client = client
+                    self.pipeline = Pipeline(client, self.structured_logger)
+                    self.controller.set_pipeline(self.pipeline)
+
+                    # Update URL field and status
+                    self.root.after(0, lambda: self._set_api_url_var(discovered_url))
+                    self.root.after(1000, self._check_api_connection)
+
+                    if health["models_loaded"]:
+                        self.log_message(
+                            f"? API found at {discovered_url}! Found {health.get('model_count', 0)} models",
+                            "SUCCESS",
+                        )
+                    else:
+                        self.log_message("?? API found but no models loaded", "WARNING")
+                    return
+
+            # Connection failed
+            self.api_connected = False
+            self.root.after(0, lambda: self._update_api_status(False))
+            self.log_message(
+                "? API connection failed. Please ensure WebUI is running with --api", "ERROR"
+            )
+            self.log_message("?? Tip: Check ports 7860-7864, restart WebUI if needed", "INFO")
+        threading.Thread(
+            target=check_in_thread, args=(initial_api_url, timeout_value), daemon=True
+        ).start()
+        # Note: previously this method started two identical threads; that was redundant and has been removed
+
+    def _update_api_status(self, connected: bool, url: str = None):
+        """Update API status indicator"""
+        if connected:
+            if hasattr(self, "api_status_panel"):
+                self.api_status_panel.set_status("Connected", "green")
+            self._apply_run_button_state()
+
+            # Update URL field if we found a different working port
+            normalized_url = self._normalize_api_url(url) if url else None
+            if normalized_url and normalized_url != self.api_url_var.get():
+                self._set_api_url_var(normalized_url)
+                self.log_message(f"Updated API URL to working port: {normalized_url}", "INFO")
+
+            # Refresh models, VAE, samplers, upscalers, and schedulers when connected
+            def refresh_all():
+                try:
+                    # Perform API calls in worker thread
+                    self._refresh_models_async()
+                    self._refresh_vae_models_async()
+                    self._refresh_samplers_async()
+                    self._refresh_hypernetworks_async()
+                    self._refresh_upscalers_async()
+                    self._refresh_schedulers_async()
+                except Exception as exc:
+                    # Marshal error message back to main thread
+                    # Capture exception in default argument to avoid closure issues
+                    self.root.after(
+                        0,
+                        lambda err=exc: self.log_message(
+                            f"⚠️ Failed to refresh model lists: {err}", "WARNING"
+                        ),
+                    )
+
+            # Run refresh in a separate thread to avoid blocking UI
+            threading.Thread(target=refresh_all, daemon=True).start()
+        else:
+            if hasattr(self, "api_status_panel"):
+                self.api_status_panel.set_status("Disconnected", "red")
+            self._apply_run_button_state()
+
+    def _on_pack_selection_changed_mediator(self, selected_packs: list[str]):
+        """
+        Mediator callback for pack selection changes from PromptPackPanel.
+
+        Args:
+            selected_packs: List of selected pack names
+        """
+        if getattr(self, "_diag_enabled", False):
+            logger.info(
+                f"[DIAG] mediator _on_pack_selection_changed_mediator start; packs={selected_packs}"
+            )
+        # Update internal state
+        self.selected_packs = selected_packs
+        self.current_selected_packs = selected_packs
+
+        if selected_packs:
+            pack_name = selected_packs[0]
+            self.log_message(f"📦 Selected pack: {pack_name}")
+            self._last_selected_pack = pack_name
+        else:
+            self.log_message("No pack selected")
+            self._last_selected_pack = None
+
+        # NOTE: Pack selection no longer auto-loads config - use Load Pack Config button instead
+        if getattr(self, "_diag_enabled", False):
+            logger.info("[DIAG] mediator _on_pack_selection_changed_mediator end")
+
+    # ...existing code...
+
+    # ...existing code...
+
+    # ...existing code...
+
+    def _refresh_prompt_packs(self):
+        """Refresh the prompt packs list"""
+        if hasattr(self, "prompt_pack_panel"):
+            self.prompt_pack_panel.refresh_packs(silent=False)
+            self.log_message("Refreshed prompt packs", "INFO")
+
+    def _refresh_prompt_packs_silent(self):
+        """Refresh the prompt packs list without logging (for initialization)"""
+        if hasattr(self, "prompt_pack_panel"):
+            self.prompt_pack_panel.refresh_packs(silent=True)
+
+    def _refresh_prompt_packs_async(self):
+        """Scan packs directory on a worker thread and populate asynchronously."""
+        if not hasattr(self, "prompt_pack_panel"):
+            return
+
+        def scan_and_populate():
+            try:
+                packs_dir = Path("packs")
+                pack_files = get_prompt_packs(packs_dir)
+                self.root.after(0, lambda: self.prompt_pack_panel.populate(pack_files))
+                self.root.after(
+                    0, lambda: self.log_message(f"?? Loaded {len(pack_files)} prompt packs", "INFO")
+                )
+            except Exception as exc:
+                self.root.after(
+                    0, lambda err=exc: self.log_message(f"? Failed to load packs: {err}", "WARNING")
+                )
+
+        threading.Thread(target=scan_and_populate, daemon=True).start()
+
+    def _refresh_config(self):
+        """Refresh configuration based on pack selection and override state"""
+        if getattr(self, "_diag_enabled", False):
+            logger.info("[DIAG] _refresh_config start")
+        # Prevent recursive refreshes
+        if self._refreshing_config:
+            if getattr(self, "_diag_enabled", False):
+                logger.info("[DIAG] _refresh_config skipped (already refreshing)")
+            return
+
+        self._refreshing_config = True
+        try:
+            selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
+            selected_packs = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
+
+            # Update UI state based on selection and override mode
+            override_mode = hasattr(self, "override_pack_var") and self.override_pack_var.get()
+            if override_mode:
+                # Override mode: use current GUI config for all selected packs
+                self._handle_override_mode(selected_packs)
+            elif len(selected_packs) == 1:
+                # Single pack: show that pack's individual config
+                self._handle_single_pack_mode(selected_packs[0])
+            elif len(selected_packs) > 1:
+                # Multiple packs: grey out config, show status message
+                self._handle_multi_pack_mode(selected_packs)
+            else:
+                # No packs selected: show preset config
+                self._handle_no_pack_mode()
+
+        finally:
+            self._refreshing_config = False
+            if getattr(self, "_diag_enabled", False):
+                logger.info("[DIAG] _refresh_config end")
+
+    def _handle_override_mode(self, selected_packs):
+        """Handle override mode: current config applies to all selected packs"""
+        # Enable all config controls
+        self._set_config_editable(True)
+
+        # Update status messages
+        if hasattr(self, "current_pack_label"):
+            self.current_pack_label.configure(
+                text=f"Override mode: {len(selected_packs)} packs selected", foreground="#ffa500"
+            )
+
+        # Show override message in config area
+        self._show_config_status(
+            "Override mode active - current config will be used for all selected packs"
+        )
+
+        self.log_message(f"Override mode: Config will apply to {len(selected_packs)} packs", "INFO")
+
+    def _handle_single_pack_mode(self, pack_name):
+        """Handle single pack selection: show pack's individual config"""
+        if getattr(self, "_diag_enabled", False):
+            logger.info(f"[DIAG] _handle_single_pack_mode start; pack={pack_name}")
+        # If override mode is NOT enabled, load the pack's config
+        if not (hasattr(self, "override_pack_var") and self.override_pack_var.get()):
+            # Ensure pack has a config file
+            pack_config = self.config_manager.ensure_pack_config(
+                pack_name, self.preset_var.get() or "default"
+            )
+
+            # Load pack's individual config into forms
+            self._load_config_into_forms(pack_config)
+            self.current_config = pack_config
+
+            self.log_message(f"Loaded config for pack: {pack_name}", "INFO")
+        else:
+            # Override mode: keep current config visible (don't reload from pack)
+            self.log_message(f"Override mode: keeping current config for pack: {pack_name}", "INFO")
+
+        # Enable config controls
+        self._set_config_editable(True)
+
+        # Update status
+        if hasattr(self, "current_pack_label"):
+            override_enabled = hasattr(self, "override_pack_var") and self.override_pack_var.get()
+            if override_enabled:
+                self.current_pack_label.configure(
+                    text=f"Pack: {pack_name} (Override)", foreground="#ffa500"
+                )
+            else:
+                self.current_pack_label.configure(text=f"Pack: {pack_name}", foreground="#00ff00")
+
+        if override_enabled:
+            self._show_config_status(f"Override mode: current config will apply to {pack_name}")
+        else:
+            self._show_config_status(f"Showing config for pack: {pack_name}")
+        if getattr(self, "_diag_enabled", False):
+            logger.info(f"[DIAG] _handle_single_pack_mode end; pack={pack_name}")
+
+    def _handle_multi_pack_mode(self, selected_packs):
+        """Handle multiple pack selection: show first pack's config, save applies to all"""
+        # If override mode is NOT enabled, load the first pack's config
+        if not self.override_pack_var.get():
+            first_pack = selected_packs[0]
+            pack_config = self.config_manager.ensure_pack_config(
+                first_pack, self.preset_var.get() or "default"
+            )
+
+            # Load first pack's config into forms
+            self._load_config_into_forms(pack_config)
+            self.current_config = pack_config
+
+            self.log_message(f"Showing config from first selected pack: {first_pack}", "INFO")
+        else:
+            # Override mode: keep current config visible
+            self.log_message(
+                f"Override mode: current config will apply to {len(selected_packs)} packs", "INFO"
+            )
+
+        # Enable config controls
+        self._set_config_editable(True)
+
+        # Update status
+        if hasattr(self, "current_pack_label"):
+            override_enabled = hasattr(self, "override_pack_var") and self.override_pack_var.get()
+            if override_enabled:
+                self.current_pack_label.configure(
+                    text=f"{len(selected_packs)} packs (Override)", foreground="#ffa500"
+                )
+            else:
+                self.current_pack_label.configure(
+                    text=f"{len(selected_packs)} packs selected", foreground="#ffff00"
+                )
+
+        if override_enabled:
+            self._show_config_status(
+                f"Override mode: current config will apply to all {len(selected_packs)} packs"
+            )
+        else:
+            self._show_config_status(
+                f"Showing config from first pack ({selected_packs[0]}). Click Save to apply to all {len(selected_packs)} pack(s)."
+            )
+
+    def _handle_no_pack_mode(self):
+        """Handle no pack selection: show preset config"""
+        # Enable config controls
+        self._set_config_editable(True)
+
+        # Load preset config
+        preset_config = self.config_manager.load_preset(self.preset_var.get())
+        if preset_config:
+            self._load_config_into_forms(preset_config)
+            self.current_config = preset_config
+
+        # Update status
+        if hasattr(self, "current_pack_label"):
+            self.current_pack_label.configure(text="No pack selected", foreground="#ff6666")
+
+        self._show_config_status(f"Showing preset config: {self.preset_var.get()}")
+
+    def _set_config_editable(self, editable: bool):
+        """Enable/disable config form controls"""
+        if hasattr(self, "config_panel"):
+            self.config_panel.set_editable(editable)
+
+    def _show_config_status(self, message: str):
+        """Show configuration status message in the config area"""
+        if hasattr(self, "config_panel"):
+            self.config_panel.set_status_message(message)
+
+    def _get_config_from_forms(self) -> dict[str, Any]:
+        """Extract current configuration from GUI forms"""
+        config = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
+        # 1) Start with ConfigPanel values if present
+        if hasattr(self, "config_panel") and self.config_panel is not None:
+            try:
+                config = self.config_panel.get_config()
+            except Exception as exc:
+                self.log_message(f"Error reading config from panel: {exc}", "ERROR")
+        # 2) Overlay with values from this form if available (authoritative when present)
+        try:
+            if hasattr(self, "txt2img_vars"):
+                for k, v in self.txt2img_vars.items():
+                    config.setdefault("txt2img", {})[k] = v.get()
+            if hasattr(self, "img2img_vars"):
+                for k, v in self.img2img_vars.items():
+                    config.setdefault("img2img", {})[k] = v.get()
+            if hasattr(self, "upscale_vars"):
+                for k, v in self.upscale_vars.items():
+                    config.setdefault("upscale", {})[k] = v.get()
+        except Exception as exc:
+            self.log_message(f"Error overlaying config from main form: {exc}", "ERROR")
+
+        # 3) Pipeline controls
+        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
+            try:
+                config["pipeline"] = self.pipeline_controls_panel.get_settings()
+            except Exception:
+                pass
+
+        if hasattr(self, "adetailer_panel") and self.adetailer_panel is not None:
+            try:
+                config["adetailer"] = self.adetailer_panel.get_config()
+            except Exception:
+                pass
+
+        try:
+            config["randomization"] = self._collect_randomization_config()
+        except Exception:
+            config["randomization"] = {}
+
+        try:
+            config["aesthetic"] = self._collect_aesthetic_config()
+        except Exception:
+            config["aesthetic"] = {}
+
+        return config
+
+    def _get_config_snapshot(self) -> dict[str, Any]:
+        """Capture a deep copy of the current form configuration."""
+        try:
+            snapshot = self._get_config_from_forms()
+        except Exception as exc:
+            self.log_message(f"Failed to capture config snapshot: {exc}", "WARNING")
+            snapshot = {}
+        return deepcopy(snapshot or {})
+
+    def _attach_summary_traces(self) -> None:
+        """Attach change traces to update live summaries."""
+        if getattr(self, "_summary_traces_attached", False):
+            return
+        try:
+
+            def attach_dict(dct: dict):
+                for var in dct.values():
+                    try:
+                        var.trace_add("write", lambda *_: self._update_live_config_summary())
+                    except Exception:
+                        pass
+
+            if hasattr(self, "txt2img_vars"):
+                attach_dict(self.txt2img_vars)
+            if hasattr(self, "img2img_vars"):
+                attach_dict(self.img2img_vars)
+            if hasattr(self, "upscale_vars"):
+                attach_dict(self.upscale_vars)
+            if hasattr(self, "pipeline_controls_panel"):
+                p = self.pipeline_controls_panel
+                for v in (
+                    getattr(p, "txt2img_enabled", None),
+                    getattr(p, "img2img_enabled", None),
+                    getattr(p, "upscale_enabled", None),
+                ):
+                    try:
+                        v and v.trace_add("write", lambda *_: self._update_live_config_summary())
+                    except Exception:
+                        pass
+            self._summary_traces_attached = True
+        except Exception:
+            pass
+
+    def _update_live_config_summary(self) -> None:
+        """Compute and render the per-tab "next run" summaries from current vars."""
+        try:
+            # txt2img summary
+            if hasattr(self, "txt2img_vars") and hasattr(self, "txt2img_summary_var"):
+                t = self.txt2img_vars
+                steps = t.get("steps").get() if "steps" in t else "-"
+                sampler = t.get("sampler_name").get() if "sampler_name" in t else "-"
+                cfg = t.get("cfg_scale").get() if "cfg_scale" in t else "-"
+                width = t.get("width").get() if "width" in t else "-"
+                height = t.get("height").get() if "height" in t else "-"
+                self.txt2img_summary_var.set(
+                    f"Next run: steps {steps}, sampler {sampler}, cfg {cfg}, size {width}x{height}"
+                )
+
+            # img2img summary
+            if hasattr(self, "img2img_vars") and hasattr(self, "img2img_summary_var"):
+                i2i = self.img2img_vars
+                steps = i2i.get("steps").get() if "steps" in i2i else "-"
+                denoise = (
+                    i2i.get("denoising_strength").get() if "denoising_strength" in i2i else "-"
+                )
+                sampler = i2i.get("sampler_name").get() if "sampler_name" in i2i else "-"
+                self.img2img_summary_var.set(
+                    f"Next run: steps {steps}, denoise {denoise}, sampler {sampler}"
+                )
+
+            # upscale summary
+            if hasattr(self, "upscale_vars") and hasattr(self, "upscale_summary_var"):
+                up = self.upscale_vars
+                mode = (up.get("upscale_mode").get() if "upscale_mode" in up else "single").lower()
+                scale = up.get("upscaling_resize").get() if "upscaling_resize" in up else "-"
+                if mode == "img2img":
+                    steps = up.get("steps").get() if "steps" in up else "-"
+                    denoise = (
+                        up.get("denoising_strength").get() if "denoising_strength" in up else "-"
+                    )
+                    sampler = up.get("sampler_name").get() if "sampler_name" in up else "-"
+                    self.upscale_summary_var.set(
+                        f"Mode: img2img — steps {steps}, denoise {denoise}, sampler {sampler}, scale {scale}x"
+                    )
+                else:
+                    upscaler = up.get("upscaler").get() if "upscaler" in up else "-"
+                    self.upscale_summary_var.set(
+                        f"Mode: single — upscaler {upscaler}, scale {scale}x"
+                    )
+        except Exception:
+            pass
+
+    def _save_current_pack_config(self):
+        """Save current configuration to the selected pack (single pack mode only)"""
+        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
+        if len(selected_indices) == 1 and not (
+            hasattr(self, "override_pack_var") and self.override_pack_var.get()
+        ):
+            pack_name = self.prompt_pack_panel.packs_listbox.get(selected_indices[0])
+            current_config = self._get_config_from_forms()
+
+            if self.config_manager.save_pack_config(pack_name, current_config):
+                self.log_message(f"Saved configuration for pack: {pack_name}", "SUCCESS")
+                self._show_config_status(f"Configuration saved for pack: {pack_name}")
+            else:
+                self.log_message(f"Failed to save configuration for pack: {pack_name}", "ERROR")
+
+    def log_message(self, message: str, level: str = "INFO"):
+        """Add message to live log with safe console fallback."""
+        import datetime
+        import sys
+        import threading
+
+        if threading.current_thread() is not threading.main_thread():
+            try:
+                self.root.after(0, lambda: self.log_message(message, level))
+                return
+            except Exception:
+                # If we cannot schedule onto Tk, fall back to console logging below.
+                pass
+
+        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
+        log_entry = f"[{timestamp}] {message}"
+
+        # Prefer GUI log panel once available
+        try:
+            add_log = getattr(self, "add_log", None)
+            if callable(add_log):
+                add_log(log_entry.strip(), level)
+            elif getattr(self, "log_panel", None) is not None:
+                self.log_panel.log(log_entry.strip(), level)
+            else:
+                raise RuntimeError("GUI log not ready")
+        except Exception:
+            # Safe console fallback that won't crash on Windows codepages
+            try:
+                enc = getattr(sys.stdout, "encoding", None) or "utf-8"
+                safe_line = f"[{level}] {log_entry.strip()}".encode(enc, errors="replace").decode(
+                    enc, errors="replace"
+                )
+                print(safe_line)
+            except Exception:
+                # Last-resort: swallow to avoid crashing the GUI init
+                pass
+
+        # Mirror to standard logger
+        if level == "ERROR":
+            logger.error(message)
+        elif level == "WARNING":
+            logger.warning(message)
+        else:
+            logger.info(message)
+
+    def _attach_tooltip(self, widget: tk.Widget, text: str, delay: int = 1500) -> None:
+        """Attach a tooltip to a widget if possible."""
+        try:
+            Tooltip(widget, text, delay=delay)
+        except Exception:
+            pass
+
+    def _run_full_pipeline(self):
+        if not self._refresh_txt2img_validation():
+            return
+        if not self._confirm_run_with_dirty():
+            return
+        self._run_full_pipeline_impl()
+
+    def _start_learning_run_stub(self) -> None:
+        """Placeholder for future learning-mode entry point."""
+
+        self.log_message("Learning mode is not enabled yet.", "INFO")
+
+    def _collect_learning_feedback_stub(self) -> None:
+        """Placeholder for future learning-mode feedback collection."""
+
+        self.log_message("Learning feedback collection is not implemented yet.", "INFO")
+
+    def _run_full_pipeline_impl(self):
+        """Run the complete pipeline"""
+        if not self.api_connected:
+            messagebox.showerror("API Error", "Please connect to API first")
+            return
+
+        # Controller-based, cancellable implementation (bypasses legacy thread path below)
+        from src.utils.file_io import read_prompt_pack
+
+        from .state import CancellationError
+
+        selected_packs = self._get_selected_packs()
+        if not selected_packs:
+            self.log_message("No prompt packs selected", "WARNING")
+            return
+
+        pack_summary = ", ".join(pack.name for pack in selected_packs)
+        self.log_message(
+            f"▶️ Starting pipeline execution for {len(selected_packs)} pack(s): {pack_summary}",
+            "INFO",
+        )
+        try:
+            override_mode = bool(self.override_pack_var.get())
+        except Exception:
+            override_mode = False
+
+        # Snapshot Tk-backed values on the main thread (thread-safe)
+        try:
+            config_snapshot = self._get_config_from_forms()
+        except Exception:
+            config_snapshot = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
+        try:
+            batch_size_snapshot = int(self.images_per_prompt_var.get())
+        except Exception:
+            batch_size_snapshot = 1
+
+        try:
+            loop_multiplier_snapshot = self._safe_int_from_var(self.loop_count_var, 1)
+        except Exception:
+            loop_multiplier_snapshot = 1
+
+        config_snapshot = config_snapshot or {
+            "txt2img": {},
+            "img2img": {},
+            "upscale": {},
+            "api": {},
+        }
+        config_snapshot = self._apply_pipeline_panel_overrides(config_snapshot)
+        randomizer_plan_result = self._build_randomizer_plan_result(config_snapshot)
+        controller_run_config = deepcopy(config_snapshot)
+        if randomizer_plan_result and getattr(randomizer_plan_result, "configs", None):
+            controller_run_config = deepcopy(randomizer_plan_result.configs[0])
+            if randomizer_plan_result.variant_count > 1:
+                logger.info(
+                    "Randomizer plan produced %d variants; TODO: multi-variant execution",
+                    randomizer_plan_result.variant_count,
+                )
+        pipeline_overrides = deepcopy(config_snapshot.get("pipeline", {}))
+        api_overrides = deepcopy(config_snapshot.get("api", {}))
+        try:
+            preset_snapshot = self.preset_var.get()
+        except Exception:
+            preset_snapshot = "default"
+
+        def resolve_config_for_pack(pack_file: Path) -> dict[str, Any]:
+            """Return per-pack configuration honoring override mode."""
+            if override_mode:
+                return deepcopy(config_snapshot)
+
+            pack_config: dict[str, Any] = {}
+            if hasattr(self, "config_manager") and self.config_manager:
+                try:
+                    pack_config = self.config_manager.ensure_pack_config(
+                        pack_file.name, preset_snapshot or "default"
+                    )
+                except Exception as exc:
+                    self.log_message(
+                        f"⚠️ Failed to load config for {pack_file.name}: {exc}. Using current form values.",
+                        "WARNING",
+                    )
+
+            merged = deepcopy(pack_config) if pack_config else {}
+            if pipeline_overrides:
+                merged.setdefault("pipeline", {}).update(pipeline_overrides)
+            if api_overrides:
+                merged.setdefault("api", {}).update(api_overrides)
+            # Always honor runtime-only sections from the current form (they are not stored per-pack)
+            for runtime_key in ("randomization", "aesthetic"):
+                snapshot_section = (
+                    deepcopy(config_snapshot.get(runtime_key)) if config_snapshot else None
+                )
+                if snapshot_section:
+                    merged[runtime_key] = snapshot_section
+
+            # Overlay live model / VAE selections from the form in non-override mode if present.
+            # Packs often persist a model/vae, but user dropdown changes should take effect for the run.
+            try:
+                live_txt2img = (config_snapshot or {}).get("txt2img", {})
+                if live_txt2img:
+                    for k in ("model", "sd_model_checkpoint", "vae"):
+                        val = live_txt2img.get(k)
+                        if isinstance(val, str) and val.strip():
+                            merged.setdefault("txt2img", {})[k] = val.strip()
+                live_img2img = (config_snapshot or {}).get("img2img", {})
+                if live_img2img:
+                    for k in ("model", "sd_model_checkpoint", "vae"):
+                        val = live_img2img.get(k)
+                        if isinstance(val, str) and val.strip():
+                            merged.setdefault("img2img", {})[k] = val.strip()
+            except Exception as exc:
+                self.log_message(
+                    f"⚠️ Failed to overlay live model/VAE selections: {exc}", "WARNING"
+                )
+
+            if merged:
+                return merged
+            return deepcopy(config_snapshot)
+
+        def pipeline_func():
+            cancel = self.controller.cancel_token
+            session_run_dir = self.structured_logger.create_run_directory()
+            self.log_message(f"📁 Session directory: {session_run_dir.name}", "INFO")
+
+            logger.info("[pipeline] ENTER pack loop (packs=%d)", len(selected_packs))
+
+            total_generated = 0
+            for pack_file in list(selected_packs):
+                pack_name = getattr(pack_file, "name", str(pack_file))
+                if cancel.is_cancelled():
+                    raise CancellationError("User cancelled before pack start")
+                self.log_message(f"[pipeline] PACK START: {pack_name}", "INFO")
+
+                read_start = time.time()
+                self.log_message(f"[pipeline] PACK {pack_name}: reading prompts", "INFO")
+                prompts = read_prompt_pack(pack_file)
+                self.log_message(
+                    f"[pipeline] PACK {pack_name}: read {len(prompts)} prompt(s) in "
+                    f"{time.time() - read_start:.2f}s",
+                    "INFO",
+                )
+                if not prompts:
+                    self.log_message(
+                        f"[pipeline] PACK {pack_name}: no prompts found; skipping", "WARNING"
+                    )
+                    continue
+
+                cfg_start = time.time()
+                self.log_message(f"[pipeline] PACK {pack_name}: resolving config", "INFO")
+                config = resolve_config_for_pack(pack_file)
+                self.log_message(
+                    f"[pipeline] PACK {pack_name}: config resolved in {time.time() - cfg_start:.2f}s",
+                    "INFO",
+                )
+                config_mode = "override" if override_mode else "pack"
+                self.log_message(
+                    f"⚙️ Using {config_mode} configuration for {pack_name}", "INFO"
+                )
+                rand_cfg = config.get("randomization", {}) or {}
+                matrix_cfg = (rand_cfg.get("matrix", {}) or {})
+                if rand_cfg.get("enabled"):
+                    sr_count = len((rand_cfg.get("prompt_sr", {}) or {}).get("rules", []) or [])
+                    wc_count = len((rand_cfg.get("wildcards", {}) or {}).get("tokens", []) or [])
+                    mx_slots = len(matrix_cfg.get("slots", []) or [])
+                    mx_base = matrix_cfg.get("base_prompt", "")
+                    mx_prompt_mode = matrix_cfg.get("prompt_mode", "replace")
+                    self.log_message(
+                        f"🎲 Randomization active: S/R={sr_count}, wildcards={wc_count}, matrix slots={mx_slots}",
+                        "INFO",
+                    )
+                    seed_val = rand_cfg.get("seed", None)
+                    if seed_val is not None:
+                        self.log_message(f"🎲 Randomization seed: {seed_val}", "INFO")
+                    if mx_base:
+                        mode_verb = {
+                            "replace": "replace",
+                            "append": "append to",
+                            "prepend": "prepend to",
+                        }
+                        verb = mode_verb.get(mx_prompt_mode, "replace")
+                        self.log_message(
+                            f"🎯 Matrix base_prompt will {verb} pack prompts: {mx_base[:60]}...",
+                            "INFO",
+                        )
+                    slot_names = [slot.get("name", "?") for slot in matrix_cfg.get("slots", [])]
+                    logger.info(
+                        "[pipeline] Randomizer matrix: mode=%s slots=%s limit=%s",
+                        matrix_cfg.get("mode", "fanout"),
+                        ",".join(slot_names) if slot_names else "-",
+                        matrix_cfg.get("limit", "n/a"),
+                    )
+                pack_variant_estimate, _ = self._estimate_pack_variants(
+                    prompts, deepcopy(rand_cfg)
+                )
+                approx_images = pack_variant_estimate * batch_size_snapshot
+                loop_multiplier = loop_multiplier_snapshot
+                if loop_multiplier > 1:
+                    approx_images *= loop_multiplier
+                self.log_message(
+                    f"?? Prediction for {pack_file.name}: {pack_variant_estimate} variant(s) -> "
+                    f"≈ {approx_images} image(s) at {batch_size_snapshot} img/prompt (loops={loop_multiplier})",
+                    "INFO",
+                )
+                self._maybe_warn_large_output(approx_images, f"pack {pack_file.name}")
+                try:
+                    randomizer = PromptRandomizer(rand_cfg)
+                except Exception as exc:
+                    self.log_message(
+                        f"?? Randomization disabled for {pack_file.name}: {exc}", "WARNING"
+                    )
+                    randomizer = PromptRandomizer({})
+                variant_plan = build_variant_plan(config)
+                if variant_plan.active:
+                    self.log_message(
+                        f"🎛️ Variant plan ({variant_plan.mode}) with {len(variant_plan.variants)} combo(s)",
+                        "INFO",
+                    )
+                batch_size = batch_size_snapshot
+                rotate_cursor = 0
+                prompt_run_index = 0
+
+                logger.info(
+                    "[pipeline] Pack %s contains %d prompt(s)",
+                    pack_file.name,
+                    len(prompts),
+                )
+
+                for i, prompt_data in enumerate(prompts):
+                    if cancel.is_cancelled():
+                        raise CancellationError("User cancelled during prompt loop")
+                    prompt_text = (prompt_data.get("positive") or "").strip()
+                    negative_override = (prompt_data.get("negative") or "").strip()
+                    self.log_message(
+                        f"📝 Prompt {i+1}/{len(prompts)}: {prompt_text[:50]}...",
+                        "INFO",
+                    )
+
+                    logger.info(
+                        "[pipeline] pack=%s prompt=%d/%d: building variants",
+                        pack_file.name,
+                        i + 1,
+                        len(prompts),
+                    )
+                    matrix_enabled = bool((rand_cfg.get("matrix", {}) or {}).get("enabled"))
+                    if matrix_enabled:
+                        logger.info("[pipeline] Calling randomizer.generate(...)")
+                        randomized_variants = randomizer.generate(prompt_text)
+                        logger.info(
+                            "[pipeline] randomizer.generate returned %d variant(s)",
+                            len(randomized_variants),
+                        )
+                    else:
+                        randomized_variants = randomizer.generate(prompt_text)
+                    if rand_cfg.get("enabled") and len(randomized_variants) == 1:
+                        self.log_message(
+                            "ℹ️ Randomization produced only one variant. Ensure prompt contains tokens (e.g. __mood__, [[slot]]) and rules have matches.",
+                            "INFO",
+                        )
+                    if not randomized_variants:
+                        randomized_variants = [PromptVariant(text=prompt_text, label=None)]
+
+                    sanitized_negative = sanitize_prompt(negative_override) if negative_override else ""
+
+                    for random_variant in randomized_variants:
+                        random_label = random_variant.label
+                        variant_prompt_text = sanitize_prompt(random_variant.text)
+                        if random_label:
+                            self.log_message(f"🎲 Randomization: {random_label}", "INFO")
+
+                        if variant_plan.active and variant_plan.variants:
+                            if variant_plan.mode == "fanout":
+                                variants_to_run = variant_plan.variants
+                            else:
+                                variant = variant_plan.variants[
+                                    rotate_cursor % len(variant_plan.variants)
+                                ]
+                                variants_to_run = [variant]
+                                rotate_cursor += 1
+                        else:
+                            variants_to_run = [None]
+
+                        logger.info(
+                            "[pipeline] pack=%s prompt=%d: running %d variant slot(s)",
+                            pack_file.name,
+                            i + 1,
+                            len(variants_to_run),
+                        )
+                        for variant in variants_to_run:
+                            if cancel.is_cancelled():
+                                raise CancellationError("User cancelled during prompt loop")
+
+                            stage_variant_label = None
+                            variant_index = 0
+                            if variant is not None:
+                                stage_variant_label = variant.label
+                                variant_index = variant.index
+                                self.log_message(
+                                    f"?? Variant {variant.index + 1}/{len(variant_plan.variants)}: {stage_variant_label}",
+                                    "INFO",
+                                )
+
+                            effective_config = apply_variant_to_config(config, variant)
+                            try:
+                                t2i_cfg = effective_config.setdefault("txt2img", {}) or {}
+                                t2i_cfg["prompt"] = variant_prompt_text
+                                if sanitized_negative:
+                                    t2i_cfg["negative_prompt"] = sanitized_negative
+                            except Exception:
+                                logger.exception("Failed to inject randomized prompt into txt2img config")
+                            # Log effective model/VAE selections for visibility in live log
+                            try:
+                                t2i_cfg = (effective_config or {}).get("txt2img", {}) or {}
+                                model_name = (
+                                    t2i_cfg.get("model") or t2i_cfg.get("sd_model_checkpoint") or ""
+                                )
+                                vae_name = t2i_cfg.get("vae") or ""
+                                if model_name or vae_name:
+                                    self.log_message(
+                                        f"🎛️ txt2img weights → model: {model_name or '(unchanged)'}; VAE: {vae_name or '(unchanged)'}",
+                                        "INFO",
+                                    )
+                                i2i_enabled = bool(
+                                    (effective_config or {})
+                                    .get("pipeline", {})
+                                    .get("img2img_enabled", False)
+                                )
+                                if i2i_enabled:
+                                    i2i_cfg = (effective_config or {}).get("img2img", {}) or {}
+                                    i2i_model = (
+                                        i2i_cfg.get("model")
+                                        or i2i_cfg.get("sd_model_checkpoint")
+                                        or ""
+                                    )
+                                    i2i_vae = i2i_cfg.get("vae") or ""
+                                    if i2i_model or i2i_vae:
+                                        self.log_message(
+                                            f"🎛️ img2img weights → model: {i2i_model or '(unchanged)'}; VAE: {i2i_vae or '(unchanged)'}",
+                                            "INFO",
+                                        )
+                            except Exception:
+                                pass
+                            logger.info(
+                                "[pipeline] Calling run_pack_pipeline (variant %d/%d)",
+                                variant_index + 1 if variant is not None else 1,
+                                len(variants_to_run),
+                            )
+                            result = self.pipeline.run_pack_pipeline(
+                                pack_name=pack_file.stem,
+                                prompt=variant_prompt_text,
+                                config=effective_config,
+                                run_dir=session_run_dir,
+                                prompt_index=prompt_run_index,
+                                batch_size=batch_size,
+                                variant_index=variant_index,
+                                variant_label=stage_variant_label,
+                            )
+                            prompt_run_index += 1
+
+                            if cancel.is_cancelled():
+                                raise CancellationError("User cancelled after pack stage")
+
+                            if result and result.get("summary"):
+                                logger.info(
+                                    "[pipeline] run_pack_pipeline returned summary=%d",
+                                    len(result.get("summary", [])),
+                                )
+                                gen = len(result["summary"])
+                                total_generated += gen
+                                suffix_parts = []
+                                if random_label:
+                                    suffix_parts.append(f"random: {random_label}")
+                                if stage_variant_label:
+                                    suffix_parts.append(f"variant {variant_index + 1}")
+                                suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
+                                self.log_message(
+                                    f"✅ Generated {gen} image(s) for prompt {i+1}{suffix}",
+                                    "SUCCESS",
+                                )
+                            else:
+                                logger.info("[pipeline] run_pack_pipeline returned no summary")
+                                suffix_parts = []
+                                if random_label:
+                                    suffix_parts.append(f"random: {random_label}")
+                                if stage_variant_label:
+                                    suffix_parts.append(f"variant {variant_index + 1}")
+                                suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
+                                self.log_message(
+                                    f"❌ Failed to generate images for prompt {i+1}{suffix}",
+                                    "ERROR",
+                                )
+                self.log_message(f"✅ Completed pack '{pack_file.stem}'", "SUCCESS")
+            return {"images_generated": total_generated, "output_dir": str(session_run_dir)}
+
+        def on_complete(result: dict):
+            try:
+                num_images = int(result.get("images_generated", 0)) if result else 0
+                output_dir = result.get("output_dir", "") if result else ""
+            except Exception:
+                num_images, output_dir = 0, ""
+            self.log_message(f"?? Pipeline completed: {num_images} image(s)", "SUCCESS")
+            if output_dir:
+                self.log_message(f"?? Output: {output_dir}", "INFO")
+            # Combined summary of effective weights
+            try:
+                model = getattr(self.pipeline, "_current_model", None)
+                vae = getattr(self.pipeline, "_current_vae", None)
+                hyper = getattr(self.pipeline, "_current_hypernetwork", None)
+                hn_strength = getattr(self.pipeline, "_current_hn_strength", None)
+                self.log_message(
+                    f"?? Run summary  model={model or '(none)'}; vae={vae or '(none)'}; hypernetwork={hyper or '(none)'}; strength={hn_strength if hn_strength is not None else '(n/a)'}",
+                    "INFO",
+                )
+            except Exception:
+                pass
+
+        def on_error(e: Exception):
+            self._handle_pipeline_error(e)
+
+        final_run_config = deepcopy(controller_run_config)
+        try:
+            setattr(self.controller, "last_run_config", final_run_config)
+        except Exception:
+            pass
+        record_hook = getattr(self.controller, "record_run_config", None)
+        if callable(record_hook):
+            try:
+                record_hook(final_run_config)
+            except Exception:
+                logger.debug("record_run_config hook failed", exc_info=True)
+
+        started = self.controller.start_pipeline(
+            pipeline_func, on_complete=on_complete, on_error=on_error
+        )
+        if started and is_gui_test_mode():
+            try:
+                event = getattr(self.controller, "lifecycle_event", None)
+                if event is not None:
+                    if not event.wait(timeout=5.0):
+                        self._signal_pipeline_finished(event)
+            except Exception:
+                pass
+        return
+
+        def run_pipeline_thread():
+            try:
+                # Create single session run directory for all packs
+                session_run_dir = self.structured_logger.create_run_directory()
+                self.log_message(f"📁 Created session directory: {session_run_dir.name}", "INFO")
+
+                # Get selected prompt packs
+                selected_packs = self._get_selected_packs()
+                if not selected_packs:
+                    self.log_message("No prompt packs selected", "WARNING")
+                    return
+
+                # Process each pack
+                for pack_file in selected_packs:
+                    self.log_message(f"Processing pack: {pack_file.name}", "INFO")
+
+                    # Read prompts from pack
+                    prompts = read_prompt_pack(pack_file)
+                    if not prompts:
+                        self.log_message(f"No prompts found in {pack_file.name}", "WARNING")
+                        continue
+
+                    # Always read the latest form values to ensure UI changes are respected
+                    config = self._get_config_from_forms()
+
+                    # Process each prompt in the pack
+                    images_generated = 0
+                    for i, prompt_data in enumerate(prompts):
+                        try:
+                            self.log_message(
+                                f"Processing prompt {i+1}/{len(prompts)}: {prompt_data['positive'][:50]}...",
+                                "INFO",
+                            )
+
+                            # Run pipeline with new directory structure
+                            result = self.pipeline.run_pack_pipeline(
+                                pack_name=pack_file.stem,
+                                prompt=prompt_data["positive"],
+                                config=config,
+                                run_dir=session_run_dir,
+                                prompt_index=i,
+                                batch_size=int(self.images_per_prompt_var.get()),
+                            )
+
+                            if result and result.get("summary"):
+                                images_generated += len(result["summary"])
+                                self.log_message(
+                                    f"✅ Generated {len(result['summary'])} images for prompt {i+1}",
+                                    "SUCCESS",
+                                )
+                            else:
+                                self.log_message(
+                                    f"❌ Failed to generate images for prompt {i+1}", "ERROR"
+                                )
+
+                        except Exception as e:
+                            self.log_message(f"❌ Error processing prompt {i+1}: {str(e)}", "ERROR")
+                            continue
+
+                    self.log_message(
+                        f"Completed pack {pack_file.name}: {images_generated} images", "SUCCESS"
+                    )
+
+                self.log_message("🎉 Pipeline execution completed!", "SUCCESS")
+
+            except Exception as e:
+                self.log_message(f"Pipeline execution failed: {e}", "ERROR")
+
+        # Run in separate thread to avoid blocking UI
+        self.log_message("🚀 Starting pipeline execution...", "INFO")
+        threading.Thread(target=run_pipeline_thread, daemon=True).start()
+
+    def _run_txt2img_only(self):
+        """Run only txt2img generation"""
+        if not self.api_connected:
+            messagebox.showerror("API Error", "Please connect to API first")
+            return
+
+        selected = self._get_selected_packs()
+        if not selected:
+            messagebox.showerror("Selection Error", "Please select at least one prompt pack")
+            return
+
+        self.log_message("🎨 Running txt2img only...", "INFO")
+
+        def txt2img_thread():
+            try:
+                run_dir = self.structured_logger.create_run_directory("txt2img_only")
+                images_per_prompt = self._safe_int_from_var(self.images_per_prompt_var, 1)
+                try:
+                    preset_name = self.preset_var.get() or "default"
+                except Exception:
+                    preset_name = "default"
+
+                for pack_path in selected:
+                    pack_name = pack_path.name
+                    self.log_message(f"Processing pack: {pack_name}", "INFO")
+
+                    prompts = read_prompt_pack(pack_path)
+                    if not prompts:
+                        self.log_message(f"No prompts found in {pack_name}", "WARNING")
+                        continue
+
+                    try:
+                        pack_config = self.config_manager.ensure_pack_config(pack_name, preset_name)
+                    except Exception as exc:
+                        self.log_message(
+                            f"?? Failed to load config for {pack_name}: {exc}. Using default settings.",
+                            "WARNING",
+                        )
+                        pack_config = {}
+
+                    rand_cfg = deepcopy(pack_config.get("randomization") or {})
+                    randomizer = None
+                    if isinstance(rand_cfg, dict) and rand_cfg.get("enabled"):
+                        try:
+                            randomizer = PromptRandomizer(rand_cfg)
+                        except Exception as exc:
+                            self.log_message(
+                                f"?? Randomization disabled for {pack_name}: {exc}", "WARNING"
+                            )
+                            randomizer = None
+
+                    txt2img_base_cfg = deepcopy(pack_config.get("txt2img", {}) or {})
+                    total_variants = 0
+
+                    for idx, prompt_data in enumerate(prompts):
+                        prompt_text = (prompt_data.get("positive") or "").strip()
+                        negative_override = (prompt_data.get("negative") or "").strip()
+                        sanitized_negative = (
+                            sanitize_prompt(negative_override) if negative_override else ""
+                        )
+                        variants = (
+                            randomizer.generate(prompt_text)
+                            if randomizer
+                            else [PromptVariant(text=prompt_text, label=None)]
+                        )
+                        total_variants += len(variants)
+
+                        if randomizer and len(variants) == 1:
+                            self.log_message(
+                                "?? Randomization produced only one variant. Ensure prompt contains tokens (e.g. __mood__, [[slot]]) and rules have matches.",
+                                "INFO",
+                            )
+
+                        for variant in variants:
+                            variant_prompt = sanitize_prompt(variant.text)
+                            cfg = deepcopy(txt2img_base_cfg)
+                            cfg["prompt"] = variant_prompt
+                            if sanitized_negative:
+                                cfg["negative_prompt"] = sanitized_negative
+                            if variant.label:
+                                self.log_message(f"?? Randomization: {variant.label}", "INFO")
+
+                            try:
+                                results = self.pipeline.run_txt2img(
+                                    prompt=variant_prompt,
+                                    config=cfg,
+                                    run_dir=run_dir,
+                                    batch_size=images_per_prompt,
+                                )
+                                if results:
+                                    self.log_message(
+                                        f"✅ Generated {len(results)} image(s) for prompt {idx+1}",
+                                        "SUCCESS",
+                                    )
+                                else:
+                                    self.log_message(
+                                        f"❌ Failed to generate image {idx+1}", "ERROR"
+                                    )
+                            except Exception as exc:
+                                self.log_message(
+                                    f"❌ Error generating image {idx+1}: {exc}", "ERROR"
+                                )
+
+                    approx_images = total_variants * images_per_prompt
+                    self._maybe_warn_large_output(
+                        approx_images, f"txt2img-only pack {pack_name}"
+                    )
+
+                self.log_message("🎉 Txt2img generation completed!", "SUCCESS")
+
+            except Exception as exc:
+                self.log_message(f"❌ Txt2img generation failed: {exc}", "ERROR")
+
+        thread = threading.Thread(target=txt2img_thread, daemon=True)
+        thread.start()
+
+    def _run_upscale_only(self):
+        """Run upscaling on existing images"""
+        if not self.api_connected:
+            messagebox.showerror("API Error", "Please connect to API first")
+            return
+
+        # Open file dialog to select images
+        file_paths = filedialog.askopenfilenames(
+            title="Select Images to Upscale",
+            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff")],
+        )
+
+        if not file_paths:
+            return
+
+        def upscale_thread():
+            try:
+                config = self.current_config or self.config_manager.get_default_config()
+                run_dir = self.structured_logger.create_run_directory("upscale_only")
+
+                for file_path in file_paths:
+                    image_path = Path(file_path)
+                    self.log_message(f"Upscaling: {image_path.name}", "INFO")
+
+                    result = self.pipeline.run_upscale(image_path, config["upscale"], run_dir)
+                    if result:
+                        self.log_message(f"✅ Upscaled: {image_path.name}", "SUCCESS")
+                    else:
+                        self.log_message(f"❌ Failed to upscale: {image_path.name}", "ERROR")
+
+                self.log_message("Upscaling completed!", "SUCCESS")
+
+            except Exception as e:
+                self.log_message(f"Upscaling failed: {e}", "ERROR")
+
+        threading.Thread(target=upscale_thread, daemon=True).start()
+
+    def _create_video(self):
+        """Create video from image sequence"""
+        # Open folder dialog to select image directory
+        folder_path = filedialog.askdirectory(title="Select Image Directory")
+        if not folder_path:
+            return
+
+        def video_thread():
+            try:
+                image_dir = Path(folder_path)
+                image_files = []
+
+                for ext in ["*.png", "*.jpg", "*.jpeg"]:
+                    image_files.extend(image_dir.glob(ext))
+
+                if not image_files:
+                    self.log_message("No images found in selected directory", "WARNING")
+                    return
+
+                # Create output video path
+                video_path = image_dir / "output_video.mp4"
+                video_path.parent.mkdir(exist_ok=True)
+
+                self.log_message(f"Creating video from {len(image_files)} images...", "INFO")
+
+                success = self.video_creator.create_video_from_images(
+                    image_files, video_path, fps=24
+                )
+
+                if success:
+                    self.log_message(f"✅ Video created: {video_path}", "SUCCESS")
+                else:
+                    self.log_message("❌ Video creation failed", "ERROR")
+
+            except Exception as e:
+                self.log_message(f"Video creation failed: {e}", "ERROR")
+
+        threading.Thread(target=video_thread, daemon=True).start()
+
+    def _get_selected_packs(self) -> list[Path]:
+        """Resolve the currently selected prompt packs in UI order."""
+        pack_names: list[str] = []
+
+        if getattr(self, "selected_packs", None):
+            pack_names = list(dict.fromkeys(self.selected_packs))
+        elif hasattr(self, "prompt_pack_panel") and hasattr(
+            self.prompt_pack_panel, "get_selected_packs"
+        ):
+            try:
+                pack_names = list(self.prompt_pack_panel.get_selected_packs())
+            except Exception:
+                pack_names = []
+
+        if (
+            not pack_names
+            and hasattr(self, "prompt_pack_panel")
+            and hasattr(self.prompt_pack_panel, "packs_listbox")
+        ):
+            try:
+                selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
+                pack_names = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
+            except Exception:
+                pack_names = []
+
+        packs_dir = Path("packs")
+        resolved: list[Path] = []
+        for pack_name in pack_names:
+            pack_path = packs_dir / pack_name
+            if pack_path.exists():
+                resolved.append(pack_path)
+            else:
+                self.log_message(f"⚠️ Pack not found on disk: {pack_path}", "WARNING")
+
+        return resolved
+
+    def _build_info_box(self, parent, title: str, text: str):
+        """Reusable helper for informational sections within tabs."""
+        frame = ttk.LabelFrame(parent, text=title, style="Dark.TLabelframe", padding=6)
+        label = ttk.Label(
+            frame,
+            text=text,
+            style="Dark.TLabel",
+            wraplength=self._current_wraplength(),
+            justify=tk.LEFT,
+        )
+        label.pack(fill=tk.X)
+        self._register_wrappable_label(label)
+        return frame
+
+    def _build_advanced_editor_tab(self, parent: tk.Widget) -> None:
+        shell = ttk.Frame(parent, style="Dark.TFrame")
+        shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
+        canvas, body = make_scrollable(shell, style="Dark.TFrame")
+        self._register_scrollable_section("advanced_editor", canvas, body)
+
+        self._build_info_box(
+            body,
+            "Advanced Prompt Editor",
+            "Manage prompt packs, validate syntax, and edit long-form content in the Advanced "
+            "Prompt Editor. Use this tab to launch the editor without digging through menus.",
+        ).pack(fill=tk.X, pady=(0, 6))
+
+        launch_frame = ttk.Frame(body, style="Dark.TFrame")
+        launch_frame.pack(fill=tk.X, pady=(0, 10))
+        ttk.Button(
+            launch_frame,
+            text="Open Advanced Prompt Editor",
+            style="Primary.TButton",
+            command=self._open_prompt_editor,
+        ).pack(side=tk.LEFT, padx=(0, 12))
+        helper_label = ttk.Label(
+            launch_frame,
+            text="Opens a new window with multi-tab editing, validation, and global negative tools.",
+            style="Dark.TLabel",
+            wraplength=self._current_wraplength(),
+            justify=tk.LEFT,
+        )
+        helper_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
+        self._register_wrappable_label(helper_label)
+
+        features_label = ttk.Label(
+            body,
+            text="Features:\n• Block-based and TSV editing modes.\n• Global negative prompt manager.\n"
+            "• Validation for missing embeddings/LoRAs.\n• Model browser with quick insert actions.",
+            style="Dark.TLabel",
+            justify=tk.LEFT,
+            wraplength=self._current_wraplength(),
+        )
+        features_label.pack(fill=tk.X, pady=(0, 10))
+        self._register_wrappable_label(features_label)
+
+    def _bind_config_panel_persistence_hooks(self) -> None:
+        """Ensure key config fields trigger preference persistence when changed."""
+        if getattr(self, "_config_panel_prefs_bound", False):
+            return
+        if not hasattr(self, "config_panel"):
+            return
+
+        tracked_vars = []
+        for key in ("model", "refiner_checkpoint"):
+            var = self.config_panel.txt2img_vars.get(key)
+            if isinstance(var, tk.Variable):
+                tracked_vars.append(var)
+
+        if not tracked_vars:
+            return
+
+        self._config_panel_prefs_bound = True
+        for var in tracked_vars:
+            try:
+                var.trace_add("write", lambda *_: self._on_config_panel_primary_change())
+            except Exception:
+                continue
+
+    def _on_config_panel_primary_change(self) -> None:
+        self._autosave_preferences_if_needed(force=True)
+
+    def _on_pipeline_controls_changed(self) -> None:
+        self._set_config_dirty(True)
+        self._autosave_preferences_if_needed(force=True)
+
+    def _set_config_dirty(self, dirty: bool) -> None:
+        self._config_dirty = bool(dirty)
+
+    def _reset_config_dirty_state(self) -> None:
+        self._set_config_dirty(False)
+
+    def _confirm_run_with_dirty(self) -> bool:
+        if not getattr(self, "_config_dirty", False):
+            return True
+        if is_gui_test_mode():
+            return True
+        return messagebox.askyesno(
+            "Unsaved Changes",
+            "The config has unsaved changes that won’t be applied to any pack. Continue anyway?",
+        )
+
+    def _maybe_show_new_features_dialog(self) -> None:
+        """Opt-in 'new features' dialog; suppressed unless explicitly enabled."""
+
+        if os.environ.get("STABLENEW_SHOW_NEW_FEATURES_DIALOG", "").lower() not in {
+            "1",
+            "true",
+            "yes",
+        }:
+            self._new_features_dialog_shown = True
+            return
+
+        if is_gui_test_mode():
+            return
+        if getattr(self, "_new_features_dialog_shown", False):
+            return
+        self._new_features_dialog_shown = True
+        self._show_new_features_dialog()
+
+    def _show_new_features_dialog(self) -> None:
+        """Display the latest feature highlights. Skips errors silently."""
+
+        try:
+            messagebox.showinfo(
+                "New Features Available",
+                (
+                    "New GUI enhancements have been added in this release.\n\n"
+                    "• Advanced prompt editor with validation tools.\n"
+                    "• Improved pack persistence and scheduler handling.\n"
+                    "• Faster pipeline startup diagnostics.\n\n"
+                    "See CHANGELOG.md for full details."
+                ),
+            )
+        except Exception:
+            logger.debug("Failed to display new features dialog", exc_info=True)
+
+    def _register_scrollable_section(
+        self, name: str, canvas: tk.Canvas, body: tk.Widget
+    ) -> None:
+        scrollbar = getattr(canvas, "_vertical_scrollbar", None)
+        self.scrollable_sections[name] = {
+            "canvas": canvas,
+            "body": body,
+            "scrollbar": scrollbar,
+        }
+
+    def _current_wraplength(self, width: int | None = None) -> int:
+        if width is None or width <= 0:
+            try:
+                width = self.root.winfo_width()
+            except Exception:
+                width = None
+        if not width or width <= 1:
+            width = self.window_min_size[0]
+        return max(int(width * 0.55), 360)
+
+    def _register_wrappable_label(self, label: tk.Widget) -> None:
+        self._wrappable_labels.append(label)
+        try:
+            label.configure(wraplength=self._current_wraplength())
+        except Exception:
+            pass
+
+    def _on_root_resize(self, event) -> None:
+        if getattr(event, "widget", None) is not self.root:
+            return
+        wrap = self._current_wraplength(event.width)
+        for label in list(self._wrappable_labels):
+            try:
+                label.configure(wraplength=wrap)
+            except Exception:
+                continue
+
+    def _open_output_folder(self):
+        """Open the output folder"""
+        output_dir = Path("output")
+        if output_dir.exists():
+            if sys.platform == "win32":
+                subprocess.run(["explorer", str(output_dir)])
+            elif sys.platform == "darwin":
+                subprocess.run(["open", str(output_dir)])
+            else:
+                subprocess.run(["xdg-open", str(output_dir)])
+        else:
+            messagebox.showinfo("No Output", "Output directory doesn't exist yet")
+
+
+
+    def _stop_execution(self):
+        """Backward-compatible alias for legacy callers."""
+        self._on_cancel_clicked()
+
+    def _open_prompt_editor(self):
+        """Open the advanced prompt pack editor"""
+        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
+        pack_path = None
+
+        if selected_indices:
+            pack_name = self.prompt_pack_panel.packs_listbox.get(selected_indices[0])
+            pack_path = Path("packs") / pack_name
+
+        # Initialize advanced editor if not already done
+        if not hasattr(self, "advanced_editor"):
+            self.advanced_editor = AdvancedPromptEditor(
+                parent_window=self.root,
+                config_manager=self.config_manager,
+                on_packs_changed=self._refresh_prompt_packs,
+                on_validation=self._handle_editor_validation,
+            )
+
+        # Open editor with selected pack
+        self.advanced_editor.open_editor(pack_path)
+
+    def _handle_editor_validation(self, results):
+        """Handle validation results from the prompt editor"""
+        # Log validation summary
+        error_count = len(results.get("errors", []))
+        warning_count = len(results.get("warnings", []))
+        # info_count = len(results.get("info", []))  # Removed unused variable
+
+        if error_count == 0 and warning_count == 0:
+            self.log_message("✅ Pack validation passed - no issues found", "SUCCESS")
+        else:
+            if error_count > 0:
+                self.log_message(f"❌ Pack validation found {error_count} error(s)", "ERROR")
+                for error in results["errors"][:3]:  # Show first 3 errors
+                    self.log_message(f"  • {error}", "ERROR")
+                if error_count > 3:
+                    self.log_message(f"  ... and {error_count - 3} more", "ERROR")
+
+            if warning_count > 0:
+                self.log_message(f"⚠️  Pack has {warning_count} warning(s)", "WARNING")
+                for warning in results["warnings"][:2]:  # Show first 2 warnings
+                    self.log_message(f"  • {warning}", "WARNING")
+                if warning_count > 2:
+                    self.log_message(f"  ... and {warning_count - 2} more", "WARNING")
+
+        # Show stats
+        stats = results.get("stats", {})
+        self.log_message(
+            f"📊 Pack stats: {stats.get('prompt_count', 0)} prompts, "
+            f"{stats.get('embedding_count', 0)} embeddings, "
+            f"{stats.get('lora_count', 0)} LoRAs",
+            "INFO",
+        )
+
+    def _open_advanced_editor(self):
+        """Wrapper method for opening advanced editor (called by button)"""
+        self._open_prompt_editor()
+
+    def _graceful_exit(self):
+        """Gracefully exit the application and guarantee process termination."""
+        self.log_message("Shutting down gracefully...", "INFO")
+
+        try:
+            self.log_message("✅ Graceful shutdown complete", "SUCCESS")
+        except Exception as exc:  # pragma: no cover - defensive logging path
+            logger.error("Error during shutdown logging: %s", exc)
+
+        try:
+            preferences = self._collect_preferences()
+            if self.preferences_manager.save_preferences(preferences):
+                self.preferences = preferences
+        except Exception as exc:  # pragma: no cover
+            logger.error("Failed to save preferences: %s", exc)
+
+        try:
+            if (
+                hasattr(self, "controller")
+                and self.controller is not None
+                and not self.controller.is_terminal
+            ):
+                try:
+                    self.controller.stop_pipeline()
+                except Exception:
+                    logger.exception("Error while stopping pipeline during exit")
+                try:
+                    self.controller.lifecycle_event.wait(timeout=5.0)
+                except Exception:
+                    logger.exception("Error waiting for controller cleanup during exit")
+        except Exception:
+            logger.exception("Unexpected error during controller shutdown")
+
+        try:
+            self.root.quit()
+            self.root.destroy()
+        except Exception:
+            logger.exception("Error tearing down Tk root during exit")
+
+        os._exit(0)
+
+    def run(self):
+        """Start the GUI application"""
+        # Start initial config refresh
+        self._refresh_config()
+
+        # Now refresh prompt packs asynchronously to avoid blocking
+        self._refresh_prompt_packs_async()
+
+        # Set up proper window closing
+        self.root.protocol("WM_DELETE_WINDOW", self._graceful_exit)
+
+        self.log_message("🚀 StableNew GUI started", "SUCCESS")
+        self.log_message("Please connect to WebUI API to begin", "INFO")
+
+        # Ensure window is visible and focused before starting mainloop
+        self.root.deiconify()  # Make sure window is not minimized
+        self.root.lift()  # Bring to front
+        self.root.focus_force()  # Force focus
+
+        # Log window state for debugging
+        self.log_message("🖥️ GUI window should now be visible", "INFO")
+
+        # Add a periodic check to ensure window stays visible
+        def check_window_visibility():
+            if self.root.state() == "iconic":  # Window is minimized
+                self.log_message("⚠️ Window was minimized, restoring...", "WARNING")
+                self.root.deiconify()
+                self.root.lift()
+            # Schedule next check in 30 seconds
+            self.root.after(30000, check_window_visibility)
+
+        # Start the visibility checker
+        self.root.after(5000, check_window_visibility)  # First check after 5 seconds
+
+    def run(self):
+        """Start the Tkinter main loop with diagnostics."""
+        logger.info("[DIAG] About to enter Tkinter mainloop", extra={"flush": True})
+        self.root.mainloop()
+
+    def _build_txt2img_config_tab(self, notebook):
+        """Build txt2img configuration form"""
+        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
+        notebook.add(tab_frame, text="🎨 txt2img")
+
+        # Pack status header
+        pack_status_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
+        pack_status_frame.pack(fill=tk.X, padx=10, pady=5)
+
+        ttk.Label(
+            pack_status_frame, text="Current Pack:", style="Dark.TLabel", font=("Arial", 9, "bold")
+        ).pack(side=tk.LEFT)
+        self.current_pack_label = ttk.Label(
+            pack_status_frame,
+            text="No pack selected",
+            style="Dark.TLabel",
+            font=("Arial", 9),
+            foreground="#ffa500",
+        )
+        self.current_pack_label.pack(side=tk.LEFT, padx=(5, 0))
+
+        # Override controls
+        override_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
+
+        self.override_pack_var = tk.BooleanVar(value=False)
+        override_checkbox = ttk.Checkbutton(
+            override_frame,
+            text="Override pack settings with current config",
+            variable=self.override_pack_var,
+            style="Dark.TCheckbutton",
+            command=self._on_override_changed,
+        )
+        override_checkbox.pack(side=tk.LEFT)
+
+        ttk.Separator(tab_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)
+
+        # Create scrollable frame
+        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
+        scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=canvas.yview)
+        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")
+
+        scrollable_frame.bind(
+            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
+        )
+
+        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
+        canvas.configure(yscrollcommand=scrollbar.set)
+
+        # Initialize config variables and widget references
+        self.txt2img_vars = {}
+        self.txt2img_widgets = {}
+
+        # Compact generation settings
+        gen_frame = ttk.LabelFrame(
+            scrollable_frame, text="Generation Settings", style="Dark.TLabelframe", padding=5
+        )
+        gen_frame.pack(fill=tk.X, pady=2)
+
+        # Steps - compact inline
+        steps_row = ttk.Frame(gen_frame, style="Dark.TFrame")
+        steps_row.pack(fill=tk.X, pady=2)
+        ttk.Label(steps_row, text="Generation Steps:", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        self.txt2img_vars["steps"] = tk.IntVar(value=20)
+        steps_spin = ttk.Spinbox(
+            steps_row, from_=1, to=150, width=8, textvariable=self.txt2img_vars["steps"]
+        )
+        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
+        self.txt2img_widgets["steps"] = steps_spin
+
+        # Sampler - compact inline
+        sampler_row = ttk.Frame(gen_frame, style="Dark.TFrame")
+        sampler_row.pack(fill=tk.X, pady=2)
+        ttk.Label(sampler_row, text="Sampler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.txt2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
+        sampler_combo = ttk.Combobox(
+            sampler_row,
+            textvariable=self.txt2img_vars["sampler_name"],
+            values=[
+                "Euler a",
+                "Euler",
+                "LMS",
+                "Heun",
+                "DPM2",
+                "DPM2 a",
+                "DPM++ 2S a",
+                "DPM++ 2M",
+                "DPM++ SDE",
+                "DPM fast",
+                "DPM adaptive",
+                "LMS Karras",
+                "DPM2 Karras",
+                "DPM2 a Karras",
+                "DPM++ 2S a Karras",
+                "DPM++ 2M Karras",
+                "DPM++ SDE Karras",
+                "DDIM",
+                "PLMS",
+            ],
+            width=18,
+            state="readonly",
+        )
+        sampler_combo.pack(side=tk.LEFT, padx=(5, 0))
+        self.txt2img_widgets["sampler_name"] = sampler_combo
+
+        # CFG Scale - compact inline
+        cfg_row = ttk.Frame(gen_frame, style="Dark.TFrame")
+        cfg_row.pack(fill=tk.X, pady=2)
+        ttk.Label(cfg_row, text="CFG Scale:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.txt2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
+        cfg_slider = EnhancedSlider(
+            cfg_row,
+            from_=1.0,
+            to=20.0,
+            variable=self.txt2img_vars["cfg_scale"],
+            resolution=0.1,
+            width=120,
+        )
+        cfg_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.txt2img_widgets["cfg_scale"] = cfg_slider
+
+        # Dimensions - compact single row
+        dims_frame = ttk.LabelFrame(
+            scrollable_frame, text="Image Dimensions", style="Dark.TLabelframe", padding=5
+        )
+        dims_frame.pack(fill=tk.X, pady=2)
+
+        dims_row = ttk.Frame(dims_frame, style="Dark.TFrame")
+        dims_row.pack(fill=tk.X)
+
+        ttk.Label(dims_row, text="Width:", style="Dark.TLabel", width=8).pack(side=tk.LEFT)
+        self.txt2img_vars["width"] = tk.IntVar(value=512)
+        width_combo = ttk.Combobox(
+            dims_row,
+            textvariable=self.txt2img_vars["width"],
+            values=[256, 320, 384, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024],
+            width=8,
+        )
+        width_combo.pack(side=tk.LEFT, padx=(2, 10))
+        self.txt2img_widgets["width"] = width_combo
+
+        ttk.Label(dims_row, text="Height:", style="Dark.TLabel", width=8).pack(side=tk.LEFT)
+        self.txt2img_vars["height"] = tk.IntVar(value=512)
+        height_combo = ttk.Combobox(
+            dims_row,
+            textvariable=self.txt2img_vars["height"],
+            values=[256, 320, 384, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024],
+            width=8,
+        )
+        height_combo.pack(side=tk.LEFT, padx=2)
+        self.txt2img_widgets["height"] = height_combo
+
+        # Advanced Settings
+        advanced_frame = ttk.LabelFrame(
+            scrollable_frame, text="Advanced Settings", style="Dark.TLabelframe", padding=5
+        )
+        advanced_frame.pack(fill=tk.X, pady=2)
+
+        # Seed controls
+        seed_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
+        seed_row.pack(fill=tk.X, pady=2)
+        ttk.Label(seed_row, text="Seed:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.txt2img_vars["seed"] = tk.IntVar(value=-1)
+        seed_spin = ttk.Spinbox(
+            seed_row, from_=-1, to=2147483647, width=12, textvariable=self.txt2img_vars["seed"]
+        )
+        seed_spin.pack(side=tk.LEFT, padx=(5, 5))
+        self.txt2img_widgets["seed"] = seed_spin
+        ttk.Button(
+            seed_row,
+            text="🎲 Random",
+            command=lambda: self.txt2img_vars["seed"].set(-1),
+            width=10,
+            style="Dark.TButton",
+        ).pack(side=tk.LEFT, padx=(5, 0))
+
+        # CLIP Skip
+        clip_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
+        clip_row.pack(fill=tk.X, pady=2)
+        ttk.Label(clip_row, text="CLIP Skip:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.txt2img_vars["clip_skip"] = tk.IntVar(value=2)
+        clip_spin = ttk.Spinbox(
+            clip_row, from_=1, to=12, width=8, textvariable=self.txt2img_vars["clip_skip"]
+        )
+        clip_spin.pack(side=tk.LEFT, padx=(5, 0))
+        self.txt2img_widgets["clip_skip"] = clip_spin
+
+        # Scheduler
+        scheduler_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
+        scheduler_row.pack(fill=tk.X, pady=2)
+        ttk.Label(scheduler_row, text="Scheduler:", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        self.txt2img_vars["scheduler"] = tk.StringVar(value="normal")
+        scheduler_combo = ttk.Combobox(
+            scheduler_row,
+            textvariable=self.txt2img_vars["scheduler"],
+            values=[
+                "normal",
+                "Karras",
+                "exponential",
+                "sgm_uniform",
+                "simple",
+                "ddim_uniform",
+                "beta",
+                "linear",
+                "cosine",
+            ],
+            width=15,
+            state="readonly",
+        )
+        scheduler_combo.pack(side=tk.LEFT, padx=(5, 0))
+        self.txt2img_widgets["scheduler"] = scheduler_combo
+
+        # Model Selection
+        model_frame = ttk.LabelFrame(
+            scrollable_frame, text="Model & VAE Selection", style="Dark.TLabelframe", padding=5
+        )
+        model_frame.pack(fill=tk.X, pady=2)
+
+        # SD Model
+        model_row = ttk.Frame(model_frame, style="Dark.TFrame")
+        model_row.pack(fill=tk.X, pady=2)
+        ttk.Label(model_row, text="SD Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.txt2img_vars["model"] = tk.StringVar(value="")
+        self.model_combo = ttk.Combobox(
+            model_row, textvariable=self.txt2img_vars["model"], width=40, state="readonly"
+        )
+        self.model_combo.pack(side=tk.LEFT, padx=(5, 5))
+        self.txt2img_widgets["model"] = self.model_combo
+        ttk.Button(
+            model_row, text="🔄", command=self._refresh_models, width=3, style="Dark.TButton"
+        ).pack(side=tk.LEFT)
+
+        # VAE Model
+        vae_row = ttk.Frame(model_frame, style="Dark.TFrame")
+        vae_row.pack(fill=tk.X, pady=2)
+        ttk.Label(vae_row, text="VAE Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.txt2img_vars["vae"] = tk.StringVar(value="")
+        self.vae_combo = ttk.Combobox(
+            vae_row, textvariable=self.txt2img_vars["vae"], width=40, state="readonly"
+        )
+        self.vae_combo.pack(side=tk.LEFT, padx=(5, 5))
+        self.txt2img_widgets["vae"] = self.vae_combo
+        ttk.Button(
+            vae_row, text="🔄", command=self._refresh_vae_models, width=3, style="Dark.TButton"
+        ).pack(side=tk.LEFT)
+
+        # Hires.Fix Settings
+        hires_frame = ttk.LabelFrame(
+            scrollable_frame, text="High-Res Fix (Hires.fix)", style="Dark.TFrame", padding=5
+        )
+        hires_frame.pack(fill=tk.X, pady=2)
+
+        # Enable Hires.fix checkbox
+        hires_enable_row = ttk.Frame(hires_frame, style="Dark.TFrame")
+        hires_enable_row.pack(fill=tk.X, pady=2)
+        self.txt2img_vars["enable_hr"] = tk.BooleanVar(value=False)
+        hires_check = ttk.Checkbutton(
+            hires_enable_row,
+            text="Enable High-Resolution Fix",
+            variable=self.txt2img_vars["enable_hr"],
+            style="Dark.TCheckbutton",
+            command=self._on_hires_toggle,
+        )
+        hires_check.pack(side=tk.LEFT)
+        self.txt2img_widgets["enable_hr"] = hires_check
+
+        # Hires scale
+        scale_row = ttk.Frame(hires_frame, style="Dark.TFrame")
+        scale_row.pack(fill=tk.X, pady=2)
+        ttk.Label(scale_row, text="Scale Factor:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.txt2img_vars["hr_scale"] = tk.DoubleVar(value=2.0)
+        scale_spin = ttk.Spinbox(
+            scale_row,
+            from_=1.1,
+            to=4.0,
+            increment=0.1,
+            width=8,
+            textvariable=self.txt2img_vars["hr_scale"],
+        )
+        scale_spin.pack(side=tk.LEFT, padx=(5, 0))
+        self.txt2img_widgets["hr_scale"] = scale_spin
+
+        # Hires upscaler
+        upscaler_row = ttk.Frame(hires_frame, style="Dark.TFrame")
+        upscaler_row.pack(fill=tk.X, pady=2)
+        ttk.Label(upscaler_row, text="HR Upscaler:", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        self.txt2img_vars["hr_upscaler"] = tk.StringVar(value="Latent")
+        hr_upscaler_combo = ttk.Combobox(
+            upscaler_row,
+            textvariable=self.txt2img_vars["hr_upscaler"],
+            values=[
+                "Latent",
+                "Latent (antialiased)",
+                "Latent (bicubic)",
+                "Latent (bicubic antialiased)",
+                "Latent (nearest)",
+                "Latent (nearest-exact)",
+                "None",
+                "Lanczos",
+                "Nearest",
+                "LDSR",
+                "BSRGAN",
+                "ESRGAN_4x",
+                "R-ESRGAN General 4xV3",
+                "ScuNET GAN",
+                "ScuNET PSNR",
+                "SwinIR 4x",
+            ],
+            width=20,
+            state="readonly",
+        )
+        hr_upscaler_combo.pack(side=tk.LEFT, padx=(5, 0))
+        self.txt2img_widgets["hr_upscaler"] = hr_upscaler_combo
+
+        # Hires denoising strength
+        hr_denoise_row = ttk.Frame(hires_frame, style="Dark.TFrame")
+        hr_denoise_row.pack(fill=tk.X, pady=2)
+        ttk.Label(hr_denoise_row, text="HR Denoising:", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        self.txt2img_vars["denoising_strength"] = tk.DoubleVar(value=0.7)
+        hr_denoise_slider = EnhancedSlider(
+            hr_denoise_row,
+            from_=0.0,
+            to=1.0,
+            variable=self.txt2img_vars["denoising_strength"],
+            resolution=0.05,
+            length=150,
+        )
+        hr_denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.txt2img_widgets["denoising_strength"] = hr_denoise_slider
+
+        # Additional Positive Prompt - compact
+        pos_frame = ttk.LabelFrame(
+            scrollable_frame,
+            text="Additional Positive Prompt (appended to pack prompts)",
+            style="Dark.TFrame",
+            padding=5,
+        )
+        pos_frame.pack(fill=tk.X, pady=2)
+        self.txt2img_vars["prompt"] = tk.StringVar(value="")
+        self.pos_text = tk.Text(
+            pos_frame, height=2, bg="#3d3d3d", fg="#ffffff", wrap=tk.WORD, font=("Segoe UI", 9)
+        )
+        self.pos_text.pack(fill=tk.X, pady=2)
+
+        # Additional Negative Prompt - compact
+        neg_frame = ttk.LabelFrame(
+            scrollable_frame,
+            text="Additional Negative Prompt (appended to pack negative prompts)",
+            style="Dark.TFrame",
+            padding=5,
+        )
+        neg_frame.pack(fill=tk.X, pady=2)
+        self.txt2img_vars["negative_prompt"] = tk.StringVar(
+            value="blurry, bad quality, distorted, ugly, malformed"
+        )
+        self.neg_text = tk.Text(
+            neg_frame, height=2, bg="#3d3d3d", fg="#ffffff", wrap=tk.WORD, font=("Segoe UI", 9)
+        )
+        self.neg_text.pack(fill=tk.X, pady=2)
+        self.neg_text.insert(1.0, self.txt2img_vars["negative_prompt"].get())
+
+        canvas.pack(side="left", fill="both", expand=True)
+        scrollbar.pack(side="right", fill="y")
+        enable_mousewheel(canvas)
+        enable_mousewheel(canvas)
+        enable_mousewheel(canvas)
+
+        # Live summary for next run (txt2img)
+        try:
+            self.txt2img_summary_var = getattr(self, "txt2img_summary_var", tk.StringVar(value=""))
+            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
+            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
+            ttk.Label(
+                summary_frame,
+                textvariable=self.txt2img_summary_var,
+                style="Dark.TLabel",
+                font=("Consolas", 9),
+            ).pack(side=tk.LEFT)
+        except Exception:
+            pass
+
+        # Attach traces and initialize summary text
+        try:
+            self._attach_summary_traces()
+            self._update_live_config_summary()
+        except Exception:
+            pass
+
+    def _build_img2img_config_tab(self, notebook):
+        """Build img2img configuration form"""
+        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
+        notebook.add(tab_frame, text="🧹 img2img")
+
+        # Create scrollable frame
+        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
+        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")
+
+        scrollable_frame.bind(
+            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
+        )
+
+        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
+
+        # Initialize config variables
+        self.img2img_vars = {}
+        self.img2img_widgets = {}
+
+        # Generation Settings
+        gen_frame = ttk.LabelFrame(
+            scrollable_frame, text="Generation Settings", style="Dark.TLabelframe", padding=5
+        )
+        gen_frame.pack(fill=tk.X, pady=2)
+
+        # Steps
+        steps_row = ttk.Frame(gen_frame, style="Dark.TFrame")
+        steps_row.pack(fill=tk.X, pady=2)
+        ttk.Label(steps_row, text="Steps:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["steps"] = tk.IntVar(value=15)
+        steps_spin = ttk.Spinbox(
+            steps_row, from_=1, to=150, width=8, textvariable=self.img2img_vars["steps"]
+        )
+        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
+        self.img2img_widgets["steps"] = steps_spin
+
+        # Denoising Strength
+        denoise_row = ttk.Frame(gen_frame, style="Dark.TFrame")
+        denoise_row.pack(fill=tk.X, pady=2)
+        ttk.Label(denoise_row, text="Denoising:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["denoising_strength"] = tk.DoubleVar(value=0.3)
+        denoise_slider = EnhancedSlider(
+            denoise_row,
+            from_=0.0,
+            to=1.0,
+            variable=self.img2img_vars["denoising_strength"],
+            resolution=0.01,
+            width=120,
+        )
+        denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.img2img_widgets["denoising_strength"] = denoise_slider
+
+        # Sampler
+        sampler_row = ttk.Frame(gen_frame, style="Dark.TFrame")
+        sampler_row.pack(fill=tk.X, pady=2)
+        ttk.Label(sampler_row, text="Sampler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["sampler_name"] = tk.StringVar(value="Euler a")
+        sampler_combo = ttk.Combobox(
+            sampler_row,
+            textvariable=self.img2img_vars["sampler_name"],
+            values=[
+                "Euler a",
+                "Euler",
+                "LMS",
+                "Heun",
+                "DPM2",
+                "DPM2 a",
+                "DPM++ 2S a",
+                "DPM++ 2M",
+                "DPM++ SDE",
+                "DPM fast",
+                "DPM adaptive",
+                "LMS Karras",
+                "DPM2 Karras",
+                "DPM2 a Karras",
+                "DPM++ 2S a Karras",
+                "DPM++ 2M Karras",
+                "DPM++ SDE Karras",
+                "DDIM",
+                "PLMS",
+            ],
+            width=18,
+            state="readonly",
+        )
+        sampler_combo.pack(side=tk.LEFT, padx=(5, 0))
+        self.img2img_widgets["sampler_name"] = sampler_combo
+
+        # CFG Scale
+        cfg_row = ttk.Frame(gen_frame, style="Dark.TFrame")
+        cfg_row.pack(fill=tk.X, pady=2)
+        ttk.Label(cfg_row, text="CFG Scale:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["cfg_scale"] = tk.DoubleVar(value=7.0)
+        cfg_slider = EnhancedSlider(
+            cfg_row,
+            from_=1.0,
+            to=20.0,
+            variable=self.img2img_vars["cfg_scale"],
+            resolution=0.5,
+            length=150,
+        )
+        cfg_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.img2img_widgets["cfg_scale"] = cfg_slider
+
+        # Advanced Settings
+        advanced_frame = ttk.LabelFrame(
+            scrollable_frame, text="Advanced Settings", style="Dark.TLabelframe", padding=5
+        )
+        advanced_frame.pack(fill=tk.X, pady=2)
+
+        # Seed
+        seed_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
+        seed_row.pack(fill=tk.X, pady=2)
+        ttk.Label(seed_row, text="Seed:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["seed"] = tk.IntVar(value=-1)
+        seed_spin = ttk.Spinbox(
+            seed_row, from_=-1, to=2147483647, width=12, textvariable=self.img2img_vars["seed"]
+        )
+        seed_spin.pack(side=tk.LEFT, padx=(5, 5))
+        self.img2img_widgets["seed"] = seed_spin
+        ttk.Button(
+            seed_row,
+            text="🎲 Random",
+            command=lambda: self.img2img_vars["seed"].set(-1),
+            width=10,
+            style="Dark.TButton",
+        ).pack(side=tk.LEFT, padx=(5, 0))
+
+        # CLIP Skip
+        clip_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
+        clip_row.pack(fill=tk.X, pady=2)
+        ttk.Label(clip_row, text="CLIP Skip:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["clip_skip"] = tk.IntVar(value=2)
+        clip_spin = ttk.Spinbox(
+            clip_row, from_=1, to=12, width=8, textvariable=self.img2img_vars["clip_skip"]
+        )
+        clip_spin.pack(side=tk.LEFT, padx=(5, 0))
+        self.img2img_widgets["clip_skip"] = clip_spin
+
+        # Scheduler
+        scheduler_row = ttk.Frame(advanced_frame, style="Dark.TFrame")
+        scheduler_row.pack(fill=tk.X, pady=2)
+        ttk.Label(scheduler_row, text="Scheduler:", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        self.img2img_vars["scheduler"] = tk.StringVar(value="normal")
+        scheduler_combo = ttk.Combobox(
+            scheduler_row,
+            textvariable=self.img2img_vars["scheduler"],
+            values=[
+                "normal",
+                "Karras",
+                "exponential",
+                "sgm_uniform",
+                "simple",
+                "ddim_uniform",
+                "beta",
+                "linear",
+                "cosine",
+            ],
+            width=15,
+            state="readonly",
+        )
+        scheduler_combo.pack(side=tk.LEFT, padx=(5, 0))
+        self.img2img_widgets["scheduler"] = scheduler_combo
+
+        # Model Selection
+        model_frame = ttk.LabelFrame(
+            scrollable_frame, text="Model & VAE Selection", style="Dark.TLabelframe", padding=5
+        )
+        model_frame.pack(fill=tk.X, pady=2)
+
+        # SD Model
+        model_row = ttk.Frame(model_frame, style="Dark.TFrame")
+        model_row.pack(fill=tk.X, pady=2)
+        ttk.Label(model_row, text="SD Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["model"] = tk.StringVar(value="")
+        self.img2img_model_combo = ttk.Combobox(
+            model_row, textvariable=self.img2img_vars["model"], width=40, state="readonly"
+        )
+        self.img2img_model_combo.pack(side=tk.LEFT, padx=(5, 5))
+        self.img2img_widgets["model"] = self.img2img_model_combo
+        ttk.Button(
+            model_row, text="🔄", command=self._refresh_models, width=3, style="Dark.TButton"
+        ).pack(side=tk.LEFT)
+
+        # VAE Model
+        vae_row = ttk.Frame(model_frame, style="Dark.TFrame")
+        vae_row.pack(fill=tk.X, pady=2)
+        ttk.Label(vae_row, text="VAE Model:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.img2img_vars["vae"] = tk.StringVar(value="")
+        self.img2img_vae_combo = ttk.Combobox(
+            vae_row, textvariable=self.img2img_vars["vae"], width=40, state="readonly"
+        )
+        self.img2img_vae_combo.pack(side=tk.LEFT, padx=(5, 5))
+        self.img2img_widgets["vae"] = self.img2img_vae_combo
+        ttk.Button(
+            vae_row, text="🔄", command=self._refresh_vae_models, width=3, style="Dark.TButton"
+        ).pack(side=tk.LEFT)
+
+        canvas.pack(fill="both", expand=True)
+
+        # Live summary for next run (upscale)
+        try:
+            self.upscale_summary_var = getattr(self, "upscale_summary_var", tk.StringVar(value=""))
+            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
+            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
+            ttk.Label(
+                summary_frame,
+                textvariable=self.upscale_summary_var,
+                style="Dark.TLabel",
+                font=("Consolas", 9),
+            ).pack(side=tk.LEFT)
+        except Exception:
+            pass
+
+        try:
+            self._attach_summary_traces()
+            self._update_live_config_summary()
+        except Exception:
+            pass
+
+        # Live summary for next run (img2img)
+        try:
+            self.img2img_summary_var = getattr(self, "img2img_summary_var", tk.StringVar(value=""))
+            summary_frame = ttk.Frame(tab_frame, style="Dark.TFrame")
+            summary_frame.pack(fill=tk.X, padx=10, pady=(5, 8))
+            ttk.Label(
+                summary_frame,
+                textvariable=self.img2img_summary_var,
+                style="Dark.TLabel",
+                font=("Consolas", 9),
+            ).pack(side=tk.LEFT)
+        except Exception:
+            pass
+
+        try:
+            self._attach_summary_traces()
+            self._update_live_config_summary()
+        except Exception:
+            pass
+
+    def _build_upscale_config_tab(self, notebook):
+        """Build upscale configuration form"""
+        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
+        notebook.add(tab_frame, text="📈 Upscale")
+
+        # Create scrollable frame
+        canvas = tk.Canvas(tab_frame, bg="#2b2b2b")
+        scrollable_frame = ttk.Frame(canvas, style="Dark.TFrame")
+
+        scrollable_frame.bind(
+            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
+        )
+
+        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
+
+        # Initialize config variables
+        self.upscale_vars = {}
+        self.upscale_widgets = {}
+
+        # Upscaling Method
+        method_frame = ttk.LabelFrame(
+            scrollable_frame, text="Upscaling Method", style="Dark.TLabelframe", padding=5
+        )
+        method_frame.pack(fill=tk.X, pady=2)
+
+        method_row = ttk.Frame(method_frame, style="Dark.TFrame")
+        method_row.pack(fill=tk.X, pady=2)
+        ttk.Label(method_row, text="Method:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.upscale_vars["upscale_mode"] = tk.StringVar(value="single")
+        method_combo = ttk.Combobox(
+            method_row,
+            textvariable=self.upscale_vars["upscale_mode"],
+            values=["single", "img2img"],
+            width=20,
+            state="readonly",
+        )
+        method_combo.pack(side=tk.LEFT, padx=(5, 5))
+        try:
+            method_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_upscale_method_state())
+        except Exception:
+            pass
+        self.upscale_widgets["upscale_mode"] = method_combo
+        ttk.Label(method_row, text="ℹ️ img2img allows denoising", style="Dark.TLabel").pack(
+            side=tk.LEFT, padx=(10, 0)
+        )
+
+        # Basic Upscaling Settings
+        basic_frame = ttk.LabelFrame(
+            scrollable_frame, text="Basic Settings", style="Dark.TLabelframe", padding=5
+        )
+        basic_frame.pack(fill=tk.X, pady=2)
+
+        # Upscaler selection
+        upscaler_row = ttk.Frame(basic_frame, style="Dark.TFrame")
+        upscaler_row.pack(fill=tk.X, pady=2)
+        ttk.Label(upscaler_row, text="Upscaler:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.upscale_vars["upscaler"] = tk.StringVar(value="R-ESRGAN 4x+")
+        self.upscaler_combo = ttk.Combobox(
+            upscaler_row, textvariable=self.upscale_vars["upscaler"], width=40, state="readonly"
+        )
+        self.upscaler_combo.pack(side=tk.LEFT, padx=(5, 5))
+        self.upscale_widgets["upscaler"] = self.upscaler_combo
+        ttk.Button(
+            upscaler_row, text="🔄", command=self._refresh_upscalers, width=3, style="Dark.TButton"
+        ).pack(side=tk.LEFT)
+
+        # Scale factor
+        scale_row = ttk.Frame(basic_frame, style="Dark.TFrame")
+        scale_row.pack(fill=tk.X, pady=2)
+        ttk.Label(scale_row, text="Scale Factor:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.upscale_vars["upscaling_resize"] = tk.DoubleVar(value=2.0)
+        scale_spin = ttk.Spinbox(
+            scale_row,
+            from_=1.1,
+            to=4.0,
+            increment=0.1,
+            width=8,
+            textvariable=self.upscale_vars["upscaling_resize"],
+        )
+        scale_spin.pack(side=tk.LEFT, padx=(5, 0))
+        self.upscale_widgets["upscaling_resize"] = scale_spin
+
+        # Steps for img2img mode
+        steps_row = ttk.Frame(basic_frame, style="Dark.TFrame")
+        steps_row.pack(fill=tk.X, pady=2)
+        ttk.Label(steps_row, text="Steps (img2img):", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        try:
+            self.upscale_vars["steps"]
+        except Exception:
+            self.upscale_vars["steps"] = tk.IntVar(value=20)
+        steps_spin = ttk.Spinbox(
+            steps_row,
+            from_=1,
+            to=150,
+            textvariable=self.upscale_vars["steps"],
+            width=8,
+        )
+        steps_spin.pack(side=tk.LEFT, padx=(5, 0))
+        self.upscale_widgets["steps"] = steps_spin
+
+        # Denoising (for img2img mode)
+        denoise_row = ttk.Frame(basic_frame, style="Dark.TFrame")
+        denoise_row.pack(fill=tk.X, pady=2)
+        ttk.Label(denoise_row, text="Denoising:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.upscale_vars["denoising_strength"] = tk.DoubleVar(value=0.35)
+        denoise_slider = EnhancedSlider(
+            denoise_row,
+            from_=0.0,
+            to=1.0,
+            variable=self.upscale_vars["denoising_strength"],
+            resolution=0.05,
+            length=150,
+        )
+        denoise_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.upscale_widgets["denoising_strength"] = denoise_slider
+
+        # Face Restoration
+        face_frame = ttk.LabelFrame(
+            scrollable_frame, text="Face Restoration", style="Dark.TLabelframe", padding=5
+        )
+        face_frame.pack(fill=tk.X, pady=2)
+
+        # GFPGAN
+        gfpgan_row = ttk.Frame(face_frame, style="Dark.TFrame")
+        gfpgan_row.pack(fill=tk.X, pady=2)
+        ttk.Label(gfpgan_row, text="GFPGAN:", style="Dark.TLabel", width=15).pack(side=tk.LEFT)
+        self.upscale_vars["gfpgan_visibility"] = tk.DoubleVar(value=0.5)  # Default to 0.5
+        gfpgan_slider = EnhancedSlider(
+            gfpgan_row,
+            from_=0.0,
+            to=1.0,
+            variable=self.upscale_vars["gfpgan_visibility"],
+            resolution=0.01,
+            width=120,
+        )
+        gfpgan_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.upscale_widgets["gfpgan_visibility"] = gfpgan_slider
+
+        # CodeFormer
+        codeformer_row = ttk.Frame(face_frame, style="Dark.TFrame")
+        codeformer_row.pack(fill=tk.X, pady=2)
+        ttk.Label(codeformer_row, text="CodeFormer:", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        self.upscale_vars["codeformer_visibility"] = tk.DoubleVar(value=0.0)
+        codeformer_slider = EnhancedSlider(
+            codeformer_row,
+            from_=0.0,
+            to=1.0,
+            variable=self.upscale_vars["codeformer_visibility"],
+            resolution=0.05,
+            length=150,
+        )
+        codeformer_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.upscale_widgets["codeformer_visibility"] = codeformer_slider
+
+        # CodeFormer Weight
+        cf_weight_row = ttk.Frame(face_frame, style="Dark.TFrame")
+        cf_weight_row.pack(fill=tk.X, pady=2)
+        ttk.Label(cf_weight_row, text="CF Fidelity:", style="Dark.TLabel", width=15).pack(
+            side=tk.LEFT
+        )
+        self.upscale_vars["codeformer_weight"] = tk.DoubleVar(value=0.5)
+        cf_weight_slider = EnhancedSlider(
+            cf_weight_row,
+            from_=0.0,
+            to=1.0,
+            variable=self.upscale_vars["codeformer_weight"],
+            resolution=0.05,
+            length=150,
+        )
+        cf_weight_slider.pack(side=tk.LEFT, padx=(5, 5))
+        self.upscale_widgets["codeformer_weight"] = cf_weight_slider
+
+        canvas.pack(fill="both", expand=True)
+
+        # Apply initial enabled/disabled state for img2img-only controls
+        try:
+            self._apply_upscale_method_state()
+        except Exception:
+            pass
+
+    def _apply_upscale_method_state(self) -> None:
+        """Enable/disable Upscale img2img-only controls based on selected method."""
+        try:
+            mode = str(self.upscale_vars.get("upscale_mode").get()).lower()
+        except Exception:
+            mode = "single"
+        use_img2img = mode == "img2img"
+        # Steps (standard widget)
+        steps_widget = self.upscale_widgets.get("steps")
+        if steps_widget is not None:
+            try:
+                steps_widget.configure(state=("normal" if use_img2img else "disabled"))
+            except Exception:
+                pass
+        # Denoising (EnhancedSlider supports .configure(state=...))
+        denoise_widget = self.upscale_widgets.get("denoising_strength")
+        if denoise_widget is not None:
+            try:
+                denoise_widget.configure(state=("normal" if use_img2img else "disabled"))
+            except Exception:
+                pass
+
+    def _build_api_config_tab(self, notebook):
+        """Build API configuration form"""
+        tab_frame = ttk.Frame(notebook, style="Dark.TFrame")
+        notebook.add(tab_frame, text="🔌 API")
+
+        # API settings
+        api_frame = ttk.LabelFrame(
+            tab_frame, text="API Connection", style="Dark.TLabelframe", padding=10
+        )
+        api_frame.pack(fill=tk.X, pady=5)
+
+        # Base URL
+        url_frame = ttk.Frame(api_frame, style="Dark.TFrame")
+        url_frame.pack(fill=tk.X, pady=5)
+        ttk.Label(url_frame, text="Base URL:", style="Dark.TLabel").pack(side=tk.LEFT)
+        self.api_vars = {}
+        self.api_vars["base_url"] = self.api_url_var  # Use the same variable
+        url_entry = ttk.Entry(url_frame, textvariable=self.api_vars["base_url"], width=30)
+        url_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
+
+        # Timeout
+        timeout_frame = ttk.Frame(api_frame, style="Dark.TFrame")
+        timeout_frame.pack(fill=tk.X, pady=5)
+        ttk.Label(timeout_frame, text="Timeout (s):", style="Dark.TLabel").pack(side=tk.LEFT)
+        self.api_vars["timeout"] = tk.IntVar(value=300)
+        timeout_spin = ttk.Spinbox(
+            timeout_frame, from_=30, to=3600, width=10, textvariable=self.api_vars["timeout"]
+        )
+        timeout_spin.pack(side=tk.LEFT, padx=5)
+
+    def _save_all_config(self):
+        """Save all configuration changes"""
+        try:
+            # Build full config via form binder
+            config = self._get_config_from_forms()
+
+            # When packs are selected and not in override mode, persist to each selected pack
+            selected = []
+            if hasattr(self, "prompt_pack_panel") and hasattr(
+                self.prompt_pack_panel, "packs_listbox"
+            ):
+                selected = [
+                    self.prompt_pack_panel.packs_listbox.get(i)
+                    for i in self.prompt_pack_panel.packs_listbox.curselection()
+                ]
+            # Fallback: if UI focus cleared the visual selection, use last-known pack
+            if (not selected) and hasattr(self, "_last_selected_pack") and self._last_selected_pack:
+                selected = [self._last_selected_pack]
+
+            if selected and not (
+                hasattr(self, "override_pack_var") and self.override_pack_var.get()
+            ):
+                saved_any = False
+                for pack_name in selected:
+                    if self.config_manager.save_pack_config(pack_name, config):
+                        saved_any = True
+                if saved_any:
+                    self.log_message(
+                        f"Saved configuration for {len(selected)} selected pack(s)", "SUCCESS"
+                    )
+                    self._show_config_status(
+                        f"Configuration saved for {len(selected)} selected pack(s)"
+                    )
+                    try:
+                        messagebox.showinfo(
+                            "Config Saved",
+                            f"Saved configuration for {len(selected)} selected pack(s)",
+                        )
+                    except Exception:
+                        pass
+                    try:
+                        if hasattr(self, "config_panel"):
+                            self.config_panel.show_save_indicator("Saved")
+                    except Exception:
+                        pass
+                    try:
+                        self.show_top_save_indicator("Saved")
+                    except Exception:
+                        pass
+                else:
+                    self.log_message("Failed to save configuration for selected packs", "ERROR")
+            else:
+                # Save as current config and optionally preset (override/preset path)
+                self.current_config = config
+                preset_name = tk.simpledialog.askstring(
+                    "Save Preset", "Enter preset name (optional):"
+                )
+                if preset_name:
+                    self.config_manager.save_preset(preset_name, config)
+                    self.log_message(f"Saved configuration as preset: {preset_name}", "SUCCESS")
+                    try:
+                        messagebox.showinfo(
+                            "Preset Saved",
+                            f"Saved configuration as preset: {preset_name}",
+                        )
+                    except Exception:
+                        pass
+                    try:
+                        if hasattr(self, "config_panel"):
+                            self.config_panel.show_save_indicator("Saved")
+                    except Exception:
+                        pass
+                    try:
+                        self.show_top_save_indicator("Saved")
+                    except Exception:
+                        pass
+                else:
+                    self.log_message("Configuration updated (not saved as preset)", "INFO")
+                    self._show_config_status("Configuration updated (not saved as preset)")
+                    try:
+                        if hasattr(self, "config_panel"):
+                            self.config_panel.show_save_indicator("Saved")
+                    except Exception:
+                        pass
+                    try:
+                        self.show_top_save_indicator("Saved")
+                    except Exception:
+                        pass
+
+        except Exception as e:
+            self.log_message(f"Failed to save configuration: {e}", "ERROR")
+
+    def _reset_all_config(self):
+        """Reset all configuration to defaults"""
+        defaults = self.config_manager.get_default_config()
+        self._load_config_into_forms(defaults)
+        self.log_message("Configuration reset to defaults", "INFO")
+
+    def on_config_save(self, _config: dict) -> None:
+        """Coordinator callback from ConfigPanel to save current settings."""
+        try:
+            self._save_all_config()
+            if hasattr(self, "config_panel"):
+                self.config_panel.show_save_indicator("Saved")
+            self.show_top_save_indicator("Saved")
+        except Exception:
+            pass
+
+    def show_top_save_indicator(self, text: str = "Saved", duration_ms: int = 2000) -> None:
+        """Show a colored indicator next to the top Save button."""
+        try:
+            color = "#00c853" if (text or "").lower() == "saved" else "#ffa500"
+            try:
+                self.top_save_indicator.configure(foreground=color)
+            except Exception:
+                pass
+            self.top_save_indicator_var.set(text)
+            if duration_ms and (text or "").lower() == "saved":
+                self.root.after(duration_ms, lambda: self.top_save_indicator_var.set(""))
+        except Exception:
+            pass
+
+    def _on_preset_changed(self, event=None):
+        """Handle preset dropdown selection changes"""
+        preset_name = self.preset_var.get()
+        if preset_name:
+            self.log_message(f"Preset selected: {preset_name} (click Load to apply)", "INFO")
+
+    def _on_preset_dropdown_changed(self):
+        """Handle preset dropdown selection changes"""
+        preset_name = self.preset_var.get()
+        if not preset_name:
+            return
+
+        config = self.config_manager.load_preset(preset_name)
+        if not config:
+            self.log_message(f"Failed to load preset: {preset_name}", "ERROR")
+            return
+
+        self.current_preset = preset_name
+
+        # Load the preset into the visible forms
+        self._load_config_into_forms(config)
+
+        # If override mode is enabled, this becomes the new override config
+        if hasattr(self, "override_pack_var") and self.override_pack_var.get():
+            self.current_config = config
+            self.log_message(
+                f"✓ Loaded preset '{preset_name}' (Pipeline + Randomization + General)",
+                "SUCCESS",
+            )
+        else:
+            # Not in override mode - preset loaded but not persisted until Save is clicked
+            self.current_config = config
+            self.log_message(
+                f"✓ Loaded preset '{preset_name}' (Pipeline + Randomization + General). Click Save to apply to selected pack",
+                "INFO",
+            )
+
+    def _apply_default_to_selected_packs(self):
+        """Apply the default preset to currently selected pack(s)"""
+        default_config = self.config_manager.load_preset("default")
+        if not default_config:
+            self.log_message("Failed to load default preset", "ERROR")
+            return
+
+        # Load into forms
+        self._load_config_into_forms(default_config)
+        self.current_config = default_config
+        self.preset_var.set("default")
+        self.current_preset = "default"
+
+        self.log_message(
+            "✓ Loaded default preset (click Save to apply to selected pack)", "SUCCESS"
+        )
+
+    def _save_config_to_packs(self):
+        """Save current configuration to selected pack(s)"""
+        selected_indices = self.prompt_pack_panel.packs_listbox.curselection()
+        if not selected_indices:
+            self.log_message("No packs selected", "WARNING")
+            return
+
+        selected_packs = [self.prompt_pack_panel.packs_listbox.get(i) for i in selected_indices]
+        current_config = self._get_config_from_forms()
+
+        saved_count = 0
+        for pack_name in selected_packs:
+            if self.config_manager.save_pack_config(pack_name, current_config):
+                saved_count += 1
+
+        if saved_count > 0:
+            if len(selected_packs) == 1:
+                self.log_message(f"✓ Saved config to pack: {selected_packs[0]}", "SUCCESS")
+            else:
+                self.log_message(
+                    f"✓ Saved config to {saved_count}/{len(selected_packs)} pack(s)", "SUCCESS"
+                )
+        else:
+            self.log_message("Failed to save config to packs", "ERROR")
+
+    def _load_selected_preset(self):
+        """Load the currently selected preset into the form"""
+        preset_name = self.preset_var.get()
+        if not preset_name:
+            self.log_message("No preset selected", "WARNING")
+            return
+
+        config = self.config_manager.load_preset(preset_name)
+        if config:
+            self.current_preset = preset_name
+            if not (hasattr(self, "override_pack_var") and self.override_pack_var.get()):
+                self._load_config_into_forms(config)
+            self.current_config = config
+            self.log_message(f"✓ Loaded preset: {preset_name}", "SUCCESS")
+            self._refresh_config()
+            # Refresh pack list asynchronously to reflect any changes
+            try:
+                self._refresh_prompt_packs_async()
+            except Exception:
+                pass
+        else:
+            self.log_message(f"Failed to load preset: {preset_name}", "ERROR")
+
+    def _save_preset_as(self):
+        """Save current configuration as a new preset with user-provided name"""
+        from tkinter import simpledialog
+
+        current_config = self._get_config_from_forms()
+
+        preset_name = simpledialog.askstring(
+            "Save Preset As",
+            "Enter a name for the new preset:",
+            initialvalue="",
+        )
+
+        if not preset_name:
+            return
+
+        # Clean up the name
+        preset_name = preset_name.strip()
+        if not preset_name:
+            self.log_message("Preset name cannot be empty", "WARNING")
+            return
+
+        # Check if preset already exists
+        if preset_name in self.config_manager.list_presets():
+            from tkinter import messagebox
+
+            overwrite = messagebox.askyesno(
+                "Preset Exists",
+                f"Preset '{preset_name}' already exists. Overwrite it?",
+            )
+            if not overwrite:
+                return
+
+        if self.config_manager.save_preset(preset_name, current_config):
+            self.log_message(f"✓ Saved preset as: {preset_name}", "SUCCESS")
+            # Refresh dropdown
+            self.preset_dropdown["values"] = self.config_manager.list_presets()
+            # Select the new preset
+            self.preset_var.set(preset_name)
+            self.current_preset = preset_name
+        else:
+            self.log_message(f"Failed to save preset: {preset_name}", "ERROR")
+
+    def _delete_selected_preset(self):
+        """Delete the currently selected preset after confirmation"""
+        from tkinter import messagebox
+
+        preset_name = self.preset_var.get()
+        if not preset_name:
+            self.log_message("No preset selected", "WARNING")
+            return
+
+        if preset_name == "default":
+            messagebox.showwarning(
+                "Cannot Delete Default",
+                "The 'default' preset is protected and cannot be deleted.\n\nYou can overwrite it with different settings, but it cannot be removed.",
+            )
+            return
+
+        confirm = messagebox.askyesno(
+            "Delete Preset",
+            f"Are you sure you want to delete the '{preset_name}' preset forever?",
+        )
+
+        if not confirm:
+            return
+
+        if self.config_manager.delete_preset(preset_name):
+            self.log_message(f"✓ Deleted preset: {preset_name}", "SUCCESS")
+            # Refresh dropdown
+            self.preset_dropdown["values"] = self.config_manager.list_presets()
+            # Select default
+            self.preset_var.set("default")
+            self.current_preset = "default"
+            # Load default into forms
+            self._on_preset_dropdown_changed()
+        else:
+            self.log_message(f"Failed to delete preset: {preset_name}", "ERROR")
+
+    def _set_as_default_preset(self):
+        """Mark the currently selected preset as the default (auto-loads on startup)"""
+        from tkinter import messagebox
+
+        preset_name = self.preset_var.get()
+        if not preset_name:
+            self.log_message("No preset selected", "WARNING")
+            return
+
+        # Check if there's already a default
+        current_default = self.config_manager.get_default_preset()
+        if current_default == preset_name:
+            messagebox.showinfo(
+                "Already Default",
+                f"'{preset_name}' is already marked as the default preset.",
+            )
+            return
+
+        if self.config_manager.set_default_preset(preset_name):
+            self.log_message(f"⭐ Marked '{preset_name}' as default preset", "SUCCESS")
+            messagebox.showinfo(
+                "Default Preset Set",
+                f"'{preset_name}' will now auto-load when the application starts.",
+            )
+        else:
+            self.log_message(f"Failed to set default preset: {preset_name}", "ERROR")
+
+    def _save_override_preset(self):
+        """Save current configuration as the override preset (updates selected preset)"""
+        current_config = self._get_config_from_forms()
+        preset_name = self.preset_var.get()
+
+        if not preset_name:
+            self.log_message("No preset selected to update", "WARNING")
+            return
+
+        if self.config_manager.save_preset(preset_name, current_config):
+            self.log_message(f"✓ Updated preset: {preset_name}", "SUCCESS")
+        else:
+            self.log_message(f"Failed to update preset: {preset_name}", "ERROR")
+
+    def _on_override_changed(self):
+        """Handle override checkbox changes"""
+        # Refresh configuration display based on new override state
+        self._refresh_config()
+
+        if hasattr(self, "override_pack_var") and self.override_pack_var.get():
+            self.log_message(
+                "📝 Override mode enabled - current config will apply to all selected packs", "INFO"
+            )
+        else:
+            self.log_message("📝 Override mode disabled - packs will use individual configs", "INFO")
+
+    def _preserve_pack_selection(self):
+        """Preserve pack selection when config changes"""
+        if hasattr(self, "_last_selected_pack") and self._last_selected_pack:
+            # Find and reselect the last selected pack
+            current_selection = self.prompt_pack_panel.packs_listbox.curselection()
+            if not current_selection:  # Only restore if nothing is selected
+                for i in range(self.prompt_pack_panel.packs_listbox.size()):
+                    if self.prompt_pack_panel.packs_listbox.get(i) == self._last_selected_pack:
+                        self.prompt_pack_panel.packs_listbox.selection_set(i)
+                        self.prompt_pack_panel.packs_listbox.activate(i)
+                        # Pack selection restored silently - no need to log every restore
+                        break
+
+    def _load_config_into_forms(self, config):
+        """Load configuration values into form widgets"""
+        if getattr(self, "_diag_enabled", False):
+            logger.info("[DIAG] _load_config_into_forms: start", extra={"flush": True})
+        # Preserve current pack selection before updating forms
+        current_selection = self.prompt_pack_panel.packs_listbox.curselection()
+        selected_pack = None
+        if current_selection:
+            selected_pack = self.prompt_pack_panel.packs_listbox.get(current_selection[0])
+
+        try:
+            if hasattr(self, "config_panel"):
+                if getattr(self, "_diag_enabled", False):
+                    logger.info(
+                        "[DIAG] _load_config_into_forms: calling config_panel.set_config",
+                        extra={"flush": True},
+                    )
+                self.config_panel.set_config(config)
+                if getattr(self, "_diag_enabled", False):
+                    logger.info(
+                        "[DIAG] _load_config_into_forms: config_panel.set_config returned",
+                        extra={"flush": True},
+                    )
+            if hasattr(self, "adetailer_panel") and self.adetailer_panel:
+                if getattr(self, "_diag_enabled", False):
+                    logger.info(
+                        "[DIAG] _load_config_into_forms: calling adetailer_panel.set_config",
+                        extra={"flush": True},
+                    )
+                self._apply_adetailer_config_section(config.get("adetailer", {}))
+            if getattr(self, "_diag_enabled", False):
+                logger.info(
+                    "[DIAG] _load_config_into_forms: calling _load_randomization_config",
+                    extra={"flush": True},
+                )
+            self._load_randomization_config(config)
+            if getattr(self, "_diag_enabled", False):
+                logger.info(
+                    "[DIAG] _load_config_into_forms: calling _load_aesthetic_config",
+                    extra={"flush": True},
+                )
+            self._load_aesthetic_config(config)
+        except Exception as e:
+            self.log_message(f"Error loading config into forms: {e}", "ERROR")
+            if getattr(self, "_diag_enabled", False):
+                logger.error(
+                    f"[DIAG] _load_config_into_forms: exception {e}",
+                    exc_info=True,
+                    extra={"flush": True},
+                )
+
+        # Restore pack selection if it was lost during form updates
+        if selected_pack and not self.prompt_pack_panel.packs_listbox.curselection():
+            if getattr(self, "_diag_enabled", False):
+                logger.info(
+                    "[DIAG] _load_config_into_forms: restoring pack selection",
+                    extra={"flush": True},
+                )
+            for i in range(self.prompt_pack_panel.packs_listbox.size()):
+                if self.prompt_pack_panel.packs_listbox.get(i) == selected_pack:
+                    # Use unwrapped selection_set to avoid triggering callback recursively
+                    if hasattr(self.prompt_pack_panel, "_orig_selection_set"):
+                        self.prompt_pack_panel._orig_selection_set(i)
+                    else:
+                        self.prompt_pack_panel.packs_listbox.selection_set(i)
+                    self.prompt_pack_panel.packs_listbox.activate(i)
+                    break
+        if getattr(self, "_diag_enabled", False):
+            logger.info("[DIAG] _load_config_into_forms: end", extra={"flush": True})
+
+    def _apply_saved_preferences(self):
+        """Apply persisted preferences to the current UI session."""
+
+        prefs = getattr(self, "preferences", None)
+        if not prefs:
+            return
+
+        try:
+            # Restore preset selection and override mode
+            self.current_preset = prefs.get("preset", "default")
+            if hasattr(self, "preset_var"):
+                self.preset_var.set(self.current_preset)
+            if hasattr(self, "override_pack_var"):
+                self.override_pack_var.set(prefs.get("override_pack", False))
+
+            # Restore pipeline control toggles
+            pipeline_state = prefs.get("pipeline_controls")
+            if pipeline_state and hasattr(self, "pipeline_controls_panel"):
+                try:
+                    self.pipeline_controls_panel.set_state(pipeline_state)
+                except Exception as exc:
+                    logger.warning(f"Failed to restore pipeline preferences: {exc}")
+
+            # Restore pack selections
+            selected_packs = prefs.get("selected_packs", [])
+            if selected_packs and hasattr(self, "packs_listbox"):
+                self.prompt_pack_panel.packs_listbox.selection_clear(0, tk.END)
+                for pack_name in selected_packs:
+                    for index in range(self.prompt_pack_panel.packs_listbox.size()):
+                        if self.prompt_pack_panel.packs_listbox.get(index) == pack_name:
+                            self.prompt_pack_panel.packs_listbox.selection_set(index)
+                            self.prompt_pack_panel.packs_listbox.activate(index)
+                self._update_selection_highlights()
+                self.selected_packs = selected_packs
+                if selected_packs:
+                    self._last_selected_pack = selected_packs[0]
+
+            # Restore configuration values into forms
+            config = prefs.get("config")
+            if config:
+                self._load_config_into_forms(config)
+                self.current_config = config
+        except Exception as exc:  # pragma: no cover - defensive logging path
+            logger.warning(f"Failed to apply saved preferences: {exc}")
+
+    def _collect_preferences(self) -> dict[str, Any]:
+        """Collect current UI preferences for persistence."""
+
+        preferences = {
+            "preset": self.preset_var.get() if hasattr(self, "preset_var") else "default",
+            "selected_packs": [],
+            "override_pack": (
+                bool(self.override_pack_var.get()) if hasattr(self, "override_pack_var") else False
+            ),
+            "pipeline_controls": self.preferences_manager.default_pipeline_controls(),
+            "config": self._get_config_from_forms(),
+        }
+
+        if hasattr(self, "packs_listbox"):
+            preferences["selected_packs"] = [
+                self.prompt_pack_panel.packs_listbox.get(i)
+                for i in self.prompt_pack_panel.packs_listbox.curselection()
+            ]
+
+        if hasattr(self, "pipeline_controls_panel") and self.pipeline_controls_panel is not None:
+            try:
+                preferences["pipeline_controls"] = self.pipeline_controls_panel.get_state()
+            except Exception as exc:  # pragma: no cover - defensive logging path
+                logger.warning(f"Failed to capture pipeline controls state: {exc}")
+
+        return preferences
+
+    def _build_settings_tab(self, parent):
+        """Build settings tab"""
+        settings_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD)
+        settings_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
+
+        # Show current preset
+        presets = self.config_manager.list_presets()
+        settings_text.insert(1.0, "Available Presets:")
+        for preset in presets:
+            settings_text.insert(tk.END, f"- {preset}")
+
+        settings_text.insert(tk.END, "Default Configuration:")
+        default_config = self.config_manager.get_default_config()
+        settings_text.insert(tk.END, json.dumps(default_config, indent=2))
+
+        settings_text.config(state=tk.DISABLED)
+
+    def _build_log_tab(self, parent):
+        """Build log tab"""
+        self.log_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD, state=tk.DISABLED)
+        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
+
+        # Add a handler to redirect logs to the text widget
+        # This is a simple implementation - could be enhanced
+        self._add_log_message("Log viewer initialized")
+
+    def _add_log_message(self, message: str):
+        """Add message to log viewer"""
+        self.log_text.config(state=tk.NORMAL)
+        self.log_text.insert(tk.END, message + "")
+        self.log_text.see(tk.END)
+        self.log_text.config(state=tk.DISABLED)
+
+    def _refresh_presets(self):
+        """Refresh preset list"""
+        presets = self.config_manager.list_presets()
+        self.preset_combo["values"] = presets
+        if presets and not self.preset_var.get():
+            self.preset_var.set(presets[0])
+
+    def _run_pipeline(self):
+        """Run the full pipeline using controller"""
+        if not self.client or not self.pipeline:
+            messagebox.showerror("Error", "Please check API connection first")
+            return
+
+        prompt = self.prompt_text.get(1.0, tk.END).strip()
+        if not prompt:
+            messagebox.showerror("Error", "Please enter a prompt")
+            return
+
+        # Get configuration from GUI forms (current user settings)
+        config = self._get_config_from_forms()
+        if not config:
+            messagebox.showerror("Error", "Failed to read configuration from forms")
+            return
+
+        # Modify config based on options
+        if not self.enable_img2img_var.get():
+            config.pop("img2img", None)
+        if not self.enable_upscale_var.get():
+            config.pop("upscale", None)
+
+        batch_size = self.batch_size_var.get()
+        run_name = self.run_name_var.get() or None
+
+        self.controller.report_progress("Running pipeline...", 0.0, "ETA: --")
+        lifecycle_event = threading.Event()
+        try:
+            self.controller.lifecycle_event = lifecycle_event
+        except Exception:
+            pass
+
+        # Define pipeline function that checks cancel token
+        # Snapshot Tk-backed values on the main thread (thread-safe)
+        try:
+            config_snapshot = self._get_config_from_forms()
+        except Exception:
+            config_snapshot = {"txt2img": {}, "img2img": {}, "upscale": {}, "api": {}}
+        try:
+            batch_size_snapshot = int(self.images_per_prompt_var.get())
+        except Exception:
+            batch_size_snapshot = 1
+
+        pipeline_failed = False
+
+        def pipeline_func():
+            try:
+                # Pass cancel_token to pipeline
+                results = self.pipeline.run_full_pipeline(
+                    prompt, config, run_name, batch_size, cancel_token=self.controller.cancel_token
+                )
+                return results
+            except CancellationError:
+                # Signal completion and prefer Ready status after cancellation
+                if lifecycle_event is not None:
+                    lifecycle_event.set()
+                else:
+                    self._signal_pipeline_finished()
+                try:
+                    self._force_error_status = False
+                    if hasattr(self, "progress_message_var"):
+                        # Schedule on Tk to mirror normal status handling
+                        self.root.after(0, lambda: self.progress_message_var.set("Ready"))
+                except Exception:
+                    pass
+                raise
+            except Exception:
+                logger.exception("Pipeline execution error")
+                nonlocal pipeline_failed
+                pipeline_failed = True
+                # Build error text up-front
+                try:
+                    import sys
+
+                    ex_type, ex, _ = sys.exc_info()
+                    err_text = (
+                        f"Pipeline failed: {ex_type.__name__}: {ex}"
+                        if (ex_type and ex)
+                        else "Pipeline failed"
+                    )
+                except Exception:
+                    err_text = "Pipeline failed"
+
+                # Log friendly error line to app log first (test captures this)
+                try:
+                    self.log_message(f"? {err_text}", "ERROR")
+                except Exception:
+                    pass
+
+                # Marshal error dialog to Tk thread (or bypass if env says so)
+                def _show_err():
+                    try:
+                        import os
+
+                        if os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {"1", "true", "TRUE"}:
+                            return
+                        if not getattr(self, "_error_dialog_shown", False):
+                            messagebox.showerror("Pipeline Error", err_text)
+                            self._error_dialog_shown = True
+                    except Exception:
+                        logger.exception("Unable to display error dialog")
+
+                try:
+                    self.root.after(0, _show_err)
+                except Exception:
+                    # Fallback for test harnesses without a real root loop
+                    _show_err()
+
+                # Ensure tests waiting on lifecycle_event are not blocked
+                try:
+                    if lifecycle_event is not None:
+                        lifecycle_event.set()
+                    else:
+                        self._signal_pipeline_finished()
+                except Exception:
+                    logger.debug(
+                        "Failed to signal lifecycle_event after pipeline error",
+                        exc_info=True,
+                    )
+
+                # Force visible error state/status
+                self._force_error_status = True
+                try:
+                    if hasattr(self, "progress_message_var"):
+                        self.progress_message_var.set("Error")
+                except Exception:
+                    pass
+                try:
+                    from .state import GUIState
+
+                    # Schedule transition on Tk thread for deterministic callback behavior
+                    self.root.after(0, lambda: self.state_manager.transition_to(GUIState.ERROR))
+                except Exception:
+                    pass
+
+                # (Already logged above)
+                raise
+
+        # Completion callback
+        def on_complete(results):
+            output_dir = results.get("run_dir", "Unknown")
+            num_images = len(results.get("summary", []))
+
+            self.root.after(
+                0,
+                lambda: self.log_message(
+                    f"✓ Pipeline completed: {num_images} images generated", "SUCCESS"
+                ),
+            )
+            self.root.after(0, lambda: self.log_message(f"Output directory: {output_dir}", "INFO"))
+            self.root.after(
+                0,
+                lambda: messagebox.showinfo(
+                    "Success",
+                    f"Pipeline completed!{num_images} images generatedOutput: {output_dir}",
+                ),
+            )
+            # Reset error-control flags for the next run
+            try:
+                self._force_error_status = False
+                self._error_dialog_shown = False
+            except Exception:
+                pass
+            # Ensure lifecycle_event is signaled for tests waiting on completion
+            if lifecycle_event is not None:
+                lifecycle_event.set()
+            else:
+                self._signal_pipeline_finished()
+
+        # Error callback
+        def on_error(e):
+            # Log and alert immediately (safe for tests with mocked messagebox)
+            try:
+                err_text = f"Pipeline failed: {type(e).__name__}: {e}"
+                self.log_message(f"? {err_text}", "ERROR")
+                try:
+                    if hasattr(self, "progress_message_var"):
+                        self.progress_message_var.set("Error")
+                except Exception:
+                    pass
+                try:
+                    if not getattr(self, "_error_dialog_shown", False):
+                        messagebox.showerror("Pipeline Error", err_text)
+                        self._error_dialog_shown = True
+                except Exception:
+                    pass
+                try:
+                    # Also schedule to ensure it wins over any queued 'Running' updates
+                    self.root.after(
+                        0,
+                        lambda: hasattr(self, "progress_message_var")
+                        and self.progress_message_var.set("Error"),
+                    )
+                    # Schedule explicit ERROR transition to drive status callbacks
+                    from .state import GUIState
+
+                    self.root.after(0, lambda: self.state_manager.transition_to(GUIState.ERROR))
+                except Exception:
+                    pass
+            except Exception:
+                pass
+
+            # Also schedule the standard UI error handler
+            def _show_err():
+                import os
+
+                if os.environ.get("STABLENEW_NO_ERROR_DIALOG") in {"1", "true", "TRUE"}:
+                    return
+                try:
+                    if not getattr(self, "_error_dialog_shown", False):
+                        messagebox.showerror("Pipeline Error", str(e))
+                        self._error_dialog_shown = True
+                except Exception:
+                    logger.exception("Unable to display error dialog")
+
+            try:
+                self.root.after(0, _show_err)
+            except Exception:
+                _show_err()
+            # Ensure lifecycle_event is signaled promptly on error
+            try:
+                if lifecycle_event is not None:
+                    lifecycle_event.set()
+                else:
+                    self._signal_pipeline_finished()
+            except Exception:
+                pass
+
+        # Start pipeline using controller (tests may toggle _sync_cleanup themselves)
+        started = self.controller.start_pipeline(
+            pipeline_func, on_complete=on_complete, on_error=on_error
+        )
+        if started and is_gui_test_mode():
+            try:
+                event = getattr(self.controller, "lifecycle_event", None)
+                if event is not None and not event.wait(timeout=5.0):
+                    event.set()
+                try:
+                    for _ in range(5):
+                        self.root.update_idletasks()
+                        self.root.update()
+                except Exception:
+                    pass
+                if pipeline_failed:
+                    try:
+                        from .state import GUIState
+
+                        if not self.state_manager.is_state(GUIState.ERROR):
+                            self.state_manager.transition_to(GUIState.ERROR)
+                    except Exception:
+                        pass
+            except Exception:
+                pass
+
+    def _handle_pipeline_error(self, error: Exception) -> None:
+        """Log and surface pipeline errors to the user.
+
+        This method may be called from a worker thread, so GUI operations
+        must be marshaled to the main thread using root.after().
+        """
+
+        error_message = f"Pipeline failed: {type(error).__name__}: {error}\nA fatal error occurred. Please restart StableNew to continue."
+        self.log_message(f"✗ {error_message}", "ERROR")
+
+        # Marshal messagebox to main thread to avoid Tkinter threading violations
+        def show_error_dialog():
+            try:
+                if not getattr(self, "_error_dialog_shown", False):
+                    messagebox.showerror("Pipeline Error", error_message)
+                    self._error_dialog_shown = True
+            except tk.TclError:
+                logger.error("Unable to display error dialog", exc_info=True)
+
+        import os
+        import sys
+        import threading
+
+        def exit_app():
+            try:
+                self.root.destroy()
+            except Exception:
+                pass
+            try:
+                sys.exit(1)
+            except SystemExit:
+                pass
+
+        def force_exit_thread():
+            import time
+
+            time.sleep(1)
+            os._exit(1)
+
+        threading.Thread(target=force_exit_thread, daemon=True).start()
+
+        try:
+            self.root.after(0, show_error_dialog)
+            self.root.after(100, exit_app)
+        except Exception:
+            show_error_dialog()
+            exit_app()
+        # Progress message update is handled by state transition callback; redundant here.
+
+    def _create_video(self):
+        """Create video from output images"""
+        # Ask user to select output directory
+        output_dir = filedialog.askdirectory(title="Select output directory containing images")
+
+        if not output_dir:
+            return
+
+        output_path = Path(output_dir)
+
+        # Try to find upscaled images first, then img2img, then txt2img
+        for subdir in ["upscaled", "img2img", "txt2img"]:
+            image_dir = output_path / subdir
+            if image_dir.exists():
+                video_path = output_path / "video" / f"{subdir}_video.mp4"
+                video_path.parent.mkdir(exist_ok=True)
+
+                self._add_log_message(f"Creating video from {subdir}...")
+
+                if self.video_creator.create_video_from_directory(image_dir, video_path):
+                    self._add_log_message(f"✓ Video created: {video_path}")
+                    messagebox.showinfo("Success", f"Video created:{video_path}")
+                else:
+                    self._add_log_message(f"✗ Failed to create video from {subdir}")
+
+                return
+
+        messagebox.showerror("Error", "No image directories found")
+
+    def _refresh_models(self):
+        """Refresh the list of available SD models (main thread version)"""
+        if self.client is None:
+            messagebox.showerror("Error", "API client not connected")
+            return
+
+        try:
+            models = self.client.get_models()
+            model_names = [""] + [
+                model.get("title", model.get("model_name", "")) for model in models
+            ]
+
+            if hasattr(self, "config_panel"):
+                self.config_panel.set_model_options(model_names)
+
+            self.log_message(f"🔄 Loaded {len(models)} SD models")
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to refresh models: {e}")
+
+    def _refresh_models_async(self):
+        """Refresh the list of available SD models (thread-safe version)"""
+        from functools import partial
+
+        if self.client is None:
+            # Schedule error message on main thread
+            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
+            return
+
+        try:
+            # Perform API call in worker thread
+            models = self.client.get_models()
+            model_names = [""] + [
+                model.get("title", model.get("model_name", "")) for model in models
+            ]
+
+            # Marshal widget updates back to main thread
+            def update_widgets():
+                if hasattr(self, "model_combo"):
+                    self.model_combo["values"] = tuple(model_names)
+                if hasattr(self, "img2img_model_combo"):
+                    self.img2img_model_combo["values"] = tuple(model_names)
+                self._add_log_message(f"🔄 Loaded {len(models)} SD models")
+
+            self.root.after(0, update_widgets)
+
+            # Also update unified ConfigPanel if present using partial to capture value
+            if hasattr(self, "config_panel"):
+                self.root.after(0, partial(self.config_panel.set_model_options, list(model_names)))
+
+        except Exception as exc:
+            # Marshal error message back to main thread
+            # Capture exception in default argument to avoid closure issues
+            self.root.after(
+                0,
+                lambda err=exc: messagebox.showerror("Error", f"Failed to refresh models: {err}"),
+            )
+
+    def _refresh_hypernetworks_async(self):
+        """Refresh available hypernetworks (thread-safe)."""
+
+        if self.client is None:
+            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
+            return
+
+        def worker():
+            try:
+                entries = self.client.get_hypernetworks()
+                names = ["None"]
+                for entry in entries:
+                    name = ""
+                    if isinstance(entry, dict):
+                        name = entry.get("name") or entry.get("title") or ""
+                    else:
+                        name = str(entry)
+                    name = name.strip()
+                    if name and name not in names:
+                        names.append(name)
+
+                self.available_hypernetworks = names
+
+                def update_widgets():
+                    if hasattr(self, "config_panel"):
+                        try:
+                            self.config_panel.set_hypernetwork_options(names)
+                        except Exception:
+                            pass
+
+                self.root.after(0, update_widgets)
+                self._add_log_message(f"🔄 Loaded {len(names) - 1} hypernetwork(s)")
+            except Exception as exc:  # pragma: no cover - Tk loop dispatch
+                self.root.after(
+                    0,
+                    lambda err=exc: messagebox.showerror(
+                        "Error", f"Failed to refresh hypernetworks: {err}"
+                    ),
+                )
+
+        threading.Thread(target=worker, daemon=True).start()
+
+    def _refresh_vae_models(self):
+        """Refresh the list of available VAE models (main thread version)"""
+        if self.client is None:
+            messagebox.showerror("Error", "API client not connected")
+            return
+
+        try:
+            vae_models = self.client.get_vae_models()
+            vae_names = [""] + [vae.get("model_name", "") for vae in vae_models]
+
+            if hasattr(self, "config_panel"):
+                self.config_panel.set_vae_options(vae_names)
+
+            self.log_message(f"🔄 Loaded {len(vae_models)} VAE models")
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to refresh VAE models: {e}")
+
+    def _refresh_vae_models_async(self):
+        """Refresh the list of available VAE models (thread-safe version)"""
+        from functools import partial
+
+        if self.client is None:
+            # Schedule error message on main thread
+            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
+            return
+
+        try:
+            # Perform API call in worker thread
+            vae_models = self.client.get_vae_models()
+            vae_names_local = [""] + [vae.get("model_name", "") for vae in vae_models]
+
+            # Store in instance attribute
+            self.vae_names = list(vae_names_local)
+
+            # Marshal widget updates back to main thread
+            def update_widgets():
+                if hasattr(self, "vae_combo"):
+                    self.vae_combo["values"] = tuple(self.vae_names)
+                if hasattr(self, "img2img_vae_combo"):
+                    self.img2img_vae_combo["values"] = tuple(self.vae_names)
+                self._add_log_message(f"🔄 Loaded {len(vae_models)} VAE models")
+
+            self.root.after(0, update_widgets)
+
+            # Also update config panel if present using partial to capture value
+            if hasattr(self, "config_panel"):
+                self.root.after(0, partial(self.config_panel.set_vae_options, list(self.vae_names)))
+
+        except Exception as exc:
+            # Marshal error message back to main thread
+            # Capture exception in default argument to avoid closure issues
+            self.root.after(
+                0,
+                lambda err=exc: messagebox.showerror(
+                    "Error", f"Failed to refresh VAE models: {err}"
+                ),
+            )
+
+    def _refresh_samplers(self):
+        """Refresh the list of available samplers (main thread version)."""
+        if self.client is None:
+            messagebox.showerror("Error", "API client not connected")
+            return
+
+        try:
+            samplers = self.client.get_samplers()
+            sampler_names = sorted(
+                {s.get("name", "") for s in samplers if s.get("name")},
+                key=str.lower,
+            )
+            self.sampler_names = list(sampler_names)
+            if hasattr(self, "config_panel"):
+                self.config_panel.set_sampler_options(self.sampler_names)
+            if hasattr(self, "pipeline_controls_panel"):
+                panel = self.pipeline_controls_panel
+                if hasattr(panel, "set_sampler_options"):
+                    panel.set_sampler_options(self.sampler_names)
+                elif hasattr(panel, "refresh_dynamic_lists_from_api"):
+                    panel.refresh_dynamic_lists_from_api(self.client)
+            self._add_log_message(f"✅ Loaded {len(samplers)} samplers from API")
+        except Exception as exc:
+            messagebox.showerror("Error", f"Failed to refresh samplers: {exc}")
+
+    def _refresh_samplers_async(self):
+        """Refresh the list of available samplers (thread-safe version)."""
+        if self.client is None:
+            # Schedule error message on main thread
+            self.root.after(
+                0,
+                lambda: messagebox.showerror("Error", "API client not connected"),
+            )
+            return
+
+        def worker():
+            try:
+                samplers = self.client.get_samplers()
+                names = sorted(
+                    {s.get("name", "") for s in samplers if s.get("name")},
+                    key=str.lower,
+                )
+                # Keep a local cache if needed later
+                self.sampler_names = list(names)
+
+                def update_widgets():
+                    self._add_log_message(f"✅ Loaded {len(samplers)} samplers from API")
+                    if hasattr(self, "config_panel"):
+                        self.config_panel.set_sampler_options(self.sampler_names)
+                    if hasattr(self, "pipeline_controls_panel"):
+                        panel = self.pipeline_controls_panel
+                        if hasattr(panel, "set_sampler_options"):
+                            panel.set_sampler_options(self.sampler_names)
+                        elif hasattr(panel, "refresh_dynamic_lists_from_api"):
+                            panel.refresh_dynamic_lists_from_api(self.client)
+
+                self.root.after(0, update_widgets)
+            except Exception as exc:
+                self.root.after(
+                    0,
+                    lambda err=exc: messagebox.showerror(
+                        "Error", f"Failed to refresh samplers: {err}"
+                    ),
+                )
+
+        threading.Thread(target=worker, daemon=True).start()
+
+    def _refresh_upscalers(self):
+        """Refresh the list of available upscalers (main thread version)"""
+        if self.client is None:
+            messagebox.showerror("Error", "API client not connected")
+            return
+
+        try:
+            upscalers = self.client.get_upscalers()
+            upscaler_names = sorted(
+                {u.get("name", "") for u in upscalers if u.get("name")},
+                key=str.lower,
+            )
+            self.upscaler_names = list(upscaler_names)
+            if hasattr(self, "config_panel"):
+                self.config_panel.set_upscaler_options(self.upscaler_names)
+            if hasattr(self, "pipeline_controls_panel"):
+                panel = self.pipeline_controls_panel
+                if hasattr(panel, "set_upscaler_options"):
+                    panel.set_upscaler_options(self.upscaler_names)
+                elif hasattr(panel, "refresh_dynamic_lists_from_api"):
+                    panel.refresh_dynamic_lists_from_api(self.client)
+            if hasattr(self, "upscaler_combo"):
+                self.upscaler_combo["values"] = tuple(self.upscaler_names)
+            self._add_log_message(f"✅ Loaded {len(upscalers)} upscalers from API")
+        except Exception as exc:
+            messagebox.showerror("Error", f"Failed to refresh upscalers: {exc}")
+
+    def _refresh_upscalers_async(self):
+        """Refresh the list of available upscalers (thread-safe version)"""
+        if self.client is None:
+            # Schedule error message on main thread
+            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
+            return
+
+        try:
+            upscalers = self.client.get_upscalers()
+            upscaler_names_local = sorted(
+                {u.get("name", "") for u in upscalers if u.get("name")},
+                key=str.lower,
+            )
+            self.upscaler_names = list(upscaler_names_local)
+
+            def update_widgets():
+                if hasattr(self, "upscaler_combo"):
+                    self.upscaler_combo["values"] = tuple(self.upscaler_names)
+                self._add_log_message(f"✅ Loaded {len(upscalers)} upscalers from API")
+                if hasattr(self, "config_panel"):
+                    self.config_panel.set_upscaler_options(self.upscaler_names)
+                if hasattr(self, "pipeline_controls_panel"):
+                    panel = self.pipeline_controls_panel
+                    if hasattr(panel, "set_upscaler_options"):
+                        panel.set_upscaler_options(self.upscaler_names)
+                    elif hasattr(panel, "refresh_dynamic_lists_from_api"):
+                        panel.refresh_dynamic_lists_from_api(self.client)
+
+            self.root.after(0, update_widgets)
+
+        except Exception as exc:
+            # Marshal error message back to main thread
+            # Capture exception in default argument to avoid closure issues
+            self.root.after(
+                0,
+                lambda err=exc: messagebox.showerror(
+                    "Error", f"Failed to refresh upscalers: {err}"
+                ),
+            )
+
+    def _refresh_schedulers(self):
+        """Refresh the list of available schedulers (main thread version)"""
+        if not self.client:
+            messagebox.showerror("Error", "API client not connected")
+            return
+
+        try:
+            schedulers = self.client.get_schedulers()
+
+            if hasattr(self, "config_panel"):
+                self.config_panel.set_scheduler_options(schedulers)
+
+            self.log_message(f"🔄 Loaded {len(schedulers)} schedulers")
+        except Exception as e:
+            messagebox.showerror("Error", f"Failed to refresh schedulers: {e}")
+
+    def _refresh_schedulers_async(self):
+        """Refresh the list of available schedulers (thread-safe version)"""
+        from functools import partial
+
+        if not self.client:
+            # Schedule error message on main thread
+            self.root.after(0, lambda: messagebox.showerror("Error", "API client not connected"))
+            return
+
+        try:
+            # Perform API call in worker thread
+            schedulers = self.client.get_schedulers()
+
+            # Store in instance attribute
+            self.schedulers = list(schedulers)
+
+            # Marshal widget updates back to main thread using partial
+            def update_widgets():
+                if hasattr(self, "scheduler_combo"):
+                    self.scheduler_combo["values"] = tuple(self.schedulers)
+                if hasattr(self, "img2img_scheduler_combo"):
+                    self.img2img_scheduler_combo["values"] = tuple(self.schedulers)
+                self._add_log_message(f"🔄 Loaded {len(self.schedulers)} schedulers")
+
+            self.root.after(0, update_widgets)
+
+            # Also update config panel if present using partial to capture value
+            if hasattr(self, "config_panel"):
+                self.root.after(
+                    0, partial(self.config_panel.set_scheduler_options, list(self.schedulers))
+                )
+
+        except Exception as exc:
+            # Marshal error message back to main thread
+            # Capture exception in default argument to avoid closure issues
+            self.root.after(
+                0,
+                lambda err=exc: messagebox.showerror(
+                    "Error", f"Failed to refresh schedulers: {err}"
+                ),
+            )
+
+    def _on_hires_toggle(self):
+        """Handle hires.fix enable/disable toggle"""
+        # This method can be used to enable/disable hires.fix related controls
+        # For now, just log the change
+        enabled = self.txt2img_vars.get("enable_hr", tk.BooleanVar()).get()
+        self.log_message(f"📏 Hires.fix {'enabled' if enabled else 'disabled'}")
+
+    def _randomize_seed(self, var_dict_name):
+        """Generate a random seed for the specified variable dictionary"""
+        import random
+
+        random_seed = random.randint(1, 2147483647)  # Max int32 value
+        var_dict = getattr(self, f"{var_dict_name}_vars", {})
+        if "seed" in var_dict:
+            var_dict["seed"].set(random_seed)
+            self.log_message(f"🎲 Random seed generated: {random_seed}")
+
+    def _randomize_txt2img_seed(self):
+        """Generate random seed for txt2img"""
+        self._randomize_seed("txt2img")
+
+    def _randomize_img2img_seed(self):
+        """Generate random seed for img2img"""
+        self._randomize_seed("img2img")
+
+
+# Public alias for entrypoint wiring to the V2 GUI.
+ENTRYPOINT_GUI_CLASS = StableNewGUI

```

---

## Patch: add `archive/gui_v1/app_layout_v2.py` with archived layout engine

```diff
--- /dev/null
+++ b/archive/gui_v1/app_layout_v2.py
@@ -0,0 +1,193 @@
+# Archived hybrid V1/V2 layout engine (AppLayoutV2)
+# Retained for reference only.
+
+# Moved to archive/gui_v1/app_layout_v2.py on November 28, 2025
+# This file is now a stub. See archive for legacy code.
+
+# Moved to archive/gui_v1/app_layout_v2.py on November 28, 2025
+# This file is now a stub. See archive for legacy code.
+
+"""V2 application layout builder for StableNewGUI.
+
+This helper centralizes panel instantiation and attachment for the V2 GUI shell.
+It is intentionally limited to Tk layout concerns and does not touch controller,
+pipeline, or learning logic.
+"""
+
+from __future__ import annotations
+
+from typing import Any
+from tkinter import ttk
+
+from src.gui.panels_v2 import (
+    PipelinePanelV2,
+    PreviewPanelV2,
+    RandomizerPanelV2,
+    SidebarPanelV2,
+    StatusBarV2,
+)
+from src.gui.prompt_pack_adapter_v2 import PromptPackAdapterV2, PromptPackSummary
+from src.gui.job_history_panel_v2 import JobHistoryPanelV2
+
+
+class AppLayoutV2:
+    """Builds and attaches V2 panels to a StableNewGUI owner."""
+
+    def __init__(self, owner: Any, theme: Any = None) -> None:
+        self.owner = owner
+        self.theme = theme
+        self._frame_style = getattr(theme, "SURFACE_FRAME_STYLE", "Dark.TFrame")
+        try:
+            self.prompt_pack_adapter = getattr(owner, "prompt_pack_adapter_v2")
+        except Exception:
+            self.prompt_pack_adapter = None
+        if self.prompt_pack_adapter is None:
+            try:
+                self.prompt_pack_adapter = PromptPackAdapterV2()
+                setattr(owner, "prompt_pack_adapter_v2", self.prompt_pack_adapter)
+            except Exception:
+                self.prompt_pack_adapter = None
+
+    def build_layout(self, root_frame: Any | None = None) -> None:
+        """Instantiate panels and attach them to the owner if not already present."""
+
+        owner = self.owner
+        root_frame = getattr(owner, "root", None)
+        self.left_zone = self._ensure_zone("left_zone", root_frame)
+        self.center_zone = self._ensure_zone("center_zone", root_frame)
+        self.center_stack = getattr(owner, "center_stack", None) or self.center_zone
+        self.right_zone = self._ensure_zone("right_zone", root_frame)
+        self.bottom_zone = self._ensure_zone("bottom_zone", getattr(owner, "_bottom_pane", root_frame))
+
+        # Pipeline / center panel
+        center_parent = self.center_stack or self.center_zone
+        if not hasattr(owner, "pipeline_panel_v2") and center_parent is not None:
+            owner.pipeline_panel_v2 = PipelinePanelV2(
+                center_parent,
+                controller=getattr(owner, "controller", None),
+                theme=self.theme,
+                config_manager=getattr(owner, "config_manager", None),
+            )
+            try:
+                owner.pipeline_panel_v2.pack(fill="both", expand=True)
+            except Exception:
+                pass
+
+        # Sidebar (depends on prompt pack adapter and apply callback)
+        if not hasattr(owner, "sidebar_panel_v2") and self.left_zone is not None:
+            owner.sidebar_panel_v2 = SidebarPanelV2(
+                self.left_zone,
+                controller=getattr(owner, "controller", None),
+                theme=self.theme,
+                prompt_pack_adapter=self.prompt_pack_adapter,
+                on_apply_pack=self._apply_pack_to_prompt,
+            )
+            try:
+                owner.sidebar_panel_v2.pack(fill="both", expand=True)
+            except Exception:
+                pass
+        if hasattr(owner, "sidebar_panel_v2"):
+            try:
+                owner.model_manager_panel_v2 = getattr(owner.sidebar_panel_v2, "model_manager_panel", None)
+                owner.core_config_panel_v2 = owner.sidebar_panel_v2.core_config_panel
+                owner.negative_prompt_panel_v2 = owner.sidebar_panel_v2.negative_prompt_panel
+                owner.resolution_panel_v2 = getattr(owner.sidebar_panel_v2.core_config_panel, "resolution_panel", None)
+            except Exception:
+                pass
+
+        if (
+            not hasattr(owner, "randomizer_panel_v2")
+            and center_parent is not None
+            and hasattr(owner, "pipeline_panel_v2")
+        ):
+            owner.randomizer_panel_v2 = RandomizerPanelV2(
+                center_parent, controller=getattr(owner, "controller", None), theme=self.theme
+            )
+            try:
+                owner.randomizer_panel_v2.pack(fill="both", expand=True, pady=(5, 0))
+            except Exception:
+                pass
+
+        # Right-side panels: preview
+        if not hasattr(owner, "preview_panel_v2") and self.right_zone is not None:
+            owner.preview_panel_v2 = PreviewPanelV2(
+                self.right_zone,
+                controller=getattr(owner, "controller", None),
+                theme=self.theme,
+            )
+            try:
+                owner.preview_panel_v2.pack(fill="both", expand=True)
+            except Exception:
+                pass
+
+        # Jobs / history panel (optional, read-only)
+        if not hasattr(owner, "job_history_panel_v2") and self.right_zone is not None:
+            history_service = getattr(owner, "job_history_service", None)
+            if history_service is None:
+                ctrl = getattr(owner, "controller", None)
+                getter = getattr(ctrl, "get_job_history_service", None)
+                if callable(getter):
+                    try:
+                        history_service = getter()
+                    except Exception:
+                        history_service = None
+            if history_service:
+                owner.job_history_panel_v2 = JobHistoryPanelV2(
+                    owner.right_zone, job_history_service=history_service, theme=self.theme
+                )
+                try:
+                    owner.job_history_panel_v2.pack(fill="both", expand=True, pady=(5, 0))
+                except Exception:
+                    pass
+        elif hasattr(owner, "job_history_panel_v2"):
+            history_service = getattr(owner, "job_history_service", None)
+            if history_service:
+                try:
+                    owner.job_history_panel_v2._service = history_service
+                except Exception:
+                    pass
+
+        # Status bar
+        if not hasattr(owner, "status_bar_v2") and self.bottom_zone is not None:
+            owner.status_bar_v2 = StatusBarV2(
+                self.bottom_zone,
+                controller=getattr(owner, "controller", None),
+                theme=self.theme,
+            )
+            try:
+                owner.status_bar_v2.pack(fill="x", pady=(4, 0))
+            except Exception:
+                pass
+
+    def attach_run_button(self, run_button: Any | None = None) -> None:
+        """Expose the run button reference consistently."""
+
+        if run_button is not None:
+            self.owner.run_button = run_button
+
+    def _apply_pack_to_prompt(self, prompt_text: str, summary: PromptPackSummary | None = None) -> None:
+        pipeline_panel = getattr(self.owner, "pipeline_panel_v2", None)
+        if pipeline_panel is None:
+            return
+        pipeline_panel.set_prompt(prompt_text or "")
+        editor = getattr(pipeline_panel, "_editor", None)
+        editor_window = getattr(pipeline_panel, "_editor_window", None)
+        if editor and editor_window and getattr(editor_window, "winfo_exists", lambda: False)():
+            try:
+                editor.prompt_text.delete("1.0", "end")
+                if prompt_text:
+                    editor.prompt_text.insert("1.0", prompt_text)
+            except Exception:
+                pass
+
+    def _ensure_zone(self, attr: str, parent: Any | None) -> Any | None:
+        """Guarantee a frame exists for the given zone so panels have a target."""
+        zone = getattr(self.owner, attr, None)
+        if zone is None and parent is not None:
+            try:
+                zone = ttk.Frame(parent, style=self._frame_style)
+                zone.pack(fill="both", expand=True)
+                setattr(self.owner, attr, zone)
+            except Exception:
+                zone = None
+        return zone

```

---

## Patch: stub out `src/gui/app_layout_v2.py`

```diff
--- a/src/gui/app_layout_v2.py
+++ b/src/gui/app_layout_v2.py
@@ -1,190 +1,2 @@
-# Moved to archive/gui_v1/app_layout_v2.py on November 28, 2025
-# This file is now a stub. See archive for legacy code.
-
-# Moved to archive/gui_v1/app_layout_v2.py on November 28, 2025
-# This file is now a stub. See archive for legacy code.
-
-"""V2 application layout builder for StableNewGUI.
-
-This helper centralizes panel instantiation and attachment for the V2 GUI shell.
-It is intentionally limited to Tk layout concerns and does not touch controller,
-pipeline, or learning logic.
-"""
-
-from __future__ import annotations
-
-from typing import Any
-from tkinter import ttk
-
-from src.gui.panels_v2 import (
-    PipelinePanelV2,
-    PreviewPanelV2,
-    RandomizerPanelV2,
-    SidebarPanelV2,
-    StatusBarV2,
-)
-from src.gui.prompt_pack_adapter_v2 import PromptPackAdapterV2, PromptPackSummary
-from src.gui.job_history_panel_v2 import JobHistoryPanelV2
-
-
-class AppLayoutV2:
-    """Builds and attaches V2 panels to a StableNewGUI owner."""
-
-    def __init__(self, owner: Any, theme: Any = None) -> None:
-        self.owner = owner
-        self.theme = theme
-        self._frame_style = getattr(theme, "SURFACE_FRAME_STYLE", "Dark.TFrame")
-        try:
-            self.prompt_pack_adapter = getattr(owner, "prompt_pack_adapter_v2")
-        except Exception:
-            self.prompt_pack_adapter = None
-        if self.prompt_pack_adapter is None:
-            try:
-                self.prompt_pack_adapter = PromptPackAdapterV2()
-                setattr(owner, "prompt_pack_adapter_v2", self.prompt_pack_adapter)
-            except Exception:
-                self.prompt_pack_adapter = None
-
-    def build_layout(self, root_frame: Any | None = None) -> None:
-        """Instantiate panels and attach them to the owner if not already present."""
-
-        owner = self.owner
-        root_frame = getattr(owner, "root", None)
-        self.left_zone = self._ensure_zone("left_zone", root_frame)
-        self.center_zone = self._ensure_zone("center_zone", root_frame)
-        self.center_stack = getattr(owner, "center_stack", None) or self.center_zone
-        self.right_zone = self._ensure_zone("right_zone", root_frame)
-        self.bottom_zone = self._ensure_zone("bottom_zone", getattr(owner, "_bottom_pane", root_frame))
-
-        # Pipeline / center panel
-        center_parent = self.center_stack or self.center_zone
-        if not hasattr(owner, "pipeline_panel_v2") and center_parent is not None:
-            owner.pipeline_panel_v2 = PipelinePanelV2(
-                center_parent,
-                controller=getattr(owner, "controller", None),
-                theme=self.theme,
-                config_manager=getattr(owner, "config_manager", None),
-            )
-            try:
-                owner.pipeline_panel_v2.pack(fill="both", expand=True)
-            except Exception:
-                pass
-
-        # Sidebar (depends on prompt pack adapter and apply callback)
-        if not hasattr(owner, "sidebar_panel_v2") and self.left_zone is not None:
-            owner.sidebar_panel_v2 = SidebarPanelV2(
-                self.left_zone,
-                controller=getattr(owner, "controller", None),
-                theme=self.theme,
-                prompt_pack_adapter=self.prompt_pack_adapter,
-                on_apply_pack=self._apply_pack_to_prompt,
-            )
-            try:
-                owner.sidebar_panel_v2.pack(fill="both", expand=True)
-            except Exception:
-                pass
-        if hasattr(owner, "sidebar_panel_v2"):
-            try:
-                owner.model_manager_panel_v2 = getattr(owner.sidebar_panel_v2, "model_manager_panel", None)
-                owner.core_config_panel_v2 = owner.sidebar_panel_v2.core_config_panel
-                owner.negative_prompt_panel_v2 = owner.sidebar_panel_v2.negative_prompt_panel
-                owner.resolution_panel_v2 = getattr(owner.sidebar_panel_v2.core_config_panel, "resolution_panel", None)
-            except Exception:
-                pass
-
-        if (
-            not hasattr(owner, "randomizer_panel_v2")
-            and center_parent is not None
-            and hasattr(owner, "pipeline_panel_v2")
-        ):
-            owner.randomizer_panel_v2 = RandomizerPanelV2(
-                center_parent, controller=getattr(owner, "controller", None), theme=self.theme
-            )
-            try:
-                owner.randomizer_panel_v2.pack(fill="both", expand=True, pady=(5, 0))
-            except Exception:
-                pass
-
-        # Right-side panels: preview
-        if not hasattr(owner, "preview_panel_v2") and self.right_zone is not None:
-            owner.preview_panel_v2 = PreviewPanelV2(
-                self.right_zone,
-                controller=getattr(owner, "controller", None),
-                theme=self.theme,
-            )
-            try:
-                owner.preview_panel_v2.pack(fill="both", expand=True)
-            except Exception:
-                pass
-
-        # Jobs / history panel (optional, read-only)
-        if not hasattr(owner, "job_history_panel_v2") and self.right_zone is not None:
-            history_service = getattr(owner, "job_history_service", None)
-            if history_service is None:
-                ctrl = getattr(owner, "controller", None)
-                getter = getattr(ctrl, "get_job_history_service", None)
-                if callable(getter):
-                    try:
-                        history_service = getter()
-                    except Exception:
-                        history_service = None
-            if history_service:
-                owner.job_history_panel_v2 = JobHistoryPanelV2(
-                    owner.right_zone, job_history_service=history_service, theme=self.theme
-                )
-                try:
-                    owner.job_history_panel_v2.pack(fill="both", expand=True, pady=(5, 0))
-                except Exception:
-                    pass
-        elif hasattr(owner, "job_history_panel_v2"):
-            history_service = getattr(owner, "job_history_service", None)
-            if history_service:
-                try:
-                    owner.job_history_panel_v2._service = history_service
-                except Exception:
-                    pass
-
-        # Status bar
-        if not hasattr(owner, "status_bar_v2") and self.bottom_zone is not None:
-            owner.status_bar_v2 = StatusBarV2(
-                self.bottom_zone,
-                controller=getattr(owner, "controller", None),
-                theme=self.theme,
-            )
-            try:
-                owner.status_bar_v2.pack(fill="x", pady=(4, 0))
-            except Exception:
-                pass
-
-    def attach_run_button(self, run_button: Any | None = None) -> None:
-        """Expose the run button reference consistently."""
-
-        if run_button is not None:
-            self.owner.run_button = run_button
-
-    def _apply_pack_to_prompt(self, prompt_text: str, summary: PromptPackSummary | None = None) -> None:
-        pipeline_panel = getattr(self.owner, "pipeline_panel_v2", None)
-        if pipeline_panel is None:
-            return
-        pipeline_panel.set_prompt(prompt_text or "")
-        editor = getattr(pipeline_panel, "_editor", None)
-        editor_window = getattr(pipeline_panel, "_editor_window", None)
-        if editor and editor_window and getattr(editor_window, "winfo_exists", lambda: False)():
-            try:
-                editor.prompt_text.delete("1.0", "end")
-                if prompt_text:
-                    editor.prompt_text.insert("1.0", prompt_text)
-            except Exception:
-                pass
-
-    def _ensure_zone(self, attr: str, parent: Any | None) -> Any | None:
-        """Guarantee a frame exists for the given zone so panels have a target."""
-        zone = getattr(self.owner, attr, None)
-        if zone is None and parent is not None:
-            try:
-                zone = ttk.Frame(parent, style=self._frame_style)
-                zone.pack(fill="both", expand=True)
-                setattr(self.owner, attr, zone)
-            except Exception:
-                zone = None
-        return zone
+# This file has been archived to archive/gui_v1/app_layout_v2.py
+# It is kept as a stub to avoid accidental imports in new code paths.

```

---

## Validation

After applying this PR:

1. `ENTRYPOINT_GUI_CLASS` in both `src/gui/main_window.py` and `src/main.py` should resolve to `MainWindowV2`.
2. No active code path should reference `StableNewGUI` or `AppLayoutV2` (only the archived copies under `archive/gui_v1/` keep the legacy code for reference).
3. GUI V2 tests and entrypoint should still pass:

   ```bash
   pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q
   pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
   pytest -q
   python -m src.main
   ```
