


# --- Standard library imports ---
import builtins
import importlib
import logging
import os
import socket
import sys
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any

# --- Third-party imports ---
try:
    import tkinter as tk
    from tkinter import messagebox
except Exception:  # pragma: no cover - Tk not ready
    tk = None
    messagebox = None

# --- Local imports ---




from .app_factory import build_v2_app
from .api.webui_process_manager import WebUIProcessConfig
from .api.webui_process_manager import WebUIProcessManager
from .api.webui_process_manager import build_default_webui_process_config
from .utils import setup_logging
from .utils.file_access_log_v2_5_2025_11_26 import FileAccessLogger
from src.gui.main_window_v2 import MainWindowV2
from src.utils.graceful_exit import graceful_exit
from src.utils.single_instance import SingleInstanceLock

# Used by tests and entrypoint contract
ENTRYPOINT_GUI_CLASS = MainWindowV2

# --- Thin wrapper for healthcheck ---
def wait_for_webui_ready(
    base_url: str,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    """
    Thin wrapper around src.api.healthcheck.wait_for_webui_ready.

    This exists so:
    - Production code uses a single canonical healthcheck implementation.
    - Tests can monkeypatch main.wait_for_webui_ready without touching the
      global src.api.healthcheck function.
    """
    from .api.healthcheck import wait_for_webui_ready as _healthcheck_wait_for_webui_ready
    return _healthcheck_wait_for_webui_ready(
        base_url,
        timeout=timeout,
        poll_interval=poll_interval,
    )
ENTRYPOINT_GUI_CLASS = MainWindowV2

# --- Thin wrapper for healthcheck ---

_INSTANCE_PORT = 47631


def _acquire_single_instance_lock() -> socket.socket | None:
    """Attempt to bind a localhost TCP port as a simple process lock."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", _INSTANCE_PORT))
        sock.listen(1)
    except OSError:
        return None
    return sock

def bootstrap_webui(config: dict[str, Any]) -> WebUIProcessManager | None:
    """Bootstrap WebUI using the proper connection controller framework."""

    proc_config: WebUIProcessConfig | None = config.get("process_config")
    if proc_config is None and config.get("webui_command"):
        proc_config = WebUIProcessConfig(
            command=list(config.get("webui_command") or []),
            working_dir=config.get("webui_workdir"),
            startup_timeout_seconds=float(config.get("webui_startup_timeout_seconds") or 60.0),
            autostart_enabled=bool(config.get("webui_autostart_enabled")),
            base_url=config.get("webui_base_url"),
        )

    if proc_config is None:
        logging.info("No WebUI configuration available")
        # Still call healthcheck if base_url is present (for test compatibility)
        base_url = config.get("webui_base_url")
        if base_url:
            wait_for_webui_ready(base_url)
        return None

    manager = WebUIProcessManager(proc_config)
    if proc_config.autostart_enabled:
        manager.start()
    wait_for_webui_ready(config.get("webui_base_url"), timeout=proc_config.startup_timeout_seconds, poll_interval=0.5)
    return manager


def _load_webui_config() -> dict[str, Any]:
    cfg = {
        "webui_base_url": os.getenv("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
    }

    proc_config = build_default_webui_process_config()
    if proc_config:
        env_override_cmd = os.getenv("STABLENEW_WEBUI_COMMAND", "").split()
        if env_override_cmd:
            proc_config.command = env_override_cmd
        workdir_override = os.getenv("STABLENEW_WEBUI_WORKDIR")
        if workdir_override:
            proc_config.working_dir = workdir_override
        autostart_env = os.getenv("STABLENEW_WEBUI_AUTOSTART")
        if autostart_env is not None:
            proc_config.autostart_enabled = autostart_env.lower() in {"1", "true", "yes"}
        timeout_override = os.getenv("STABLENEW_WEBUI_TIMEOUT")
        if timeout_override:
            try:
                proc_config.startup_timeout_seconds = float(timeout_override)
            except Exception:
                pass
        cfg["process_config"] = proc_config
    return cfg



def _async_bootstrap_webui(root: Any, app_state, window) -> None:
    """Asynchronously bootstrap WebUI after GUI is loaded."""
    import threading
    
    def _bootstrap_worker():
        try:
            config = _load_webui_config()
            webui_manager = bootstrap_webui(config)
            if webui_manager:
                # Update the window with the WebUI manager
                root.after(0, lambda: _update_window_webui_manager(window, webui_manager))
                logging.info("WebUI bootstrap completed asynchronously")
        except Exception as e:
            logging.warning(f"Async WebUI bootstrap failed: {e}")
    
    # Start bootstrap in background thread
    thread = threading.Thread(target=_bootstrap_worker, daemon=True)
    thread.start()


def _update_window_webui_manager(window, webui_manager: WebUIProcessManager) -> None:
    """Update the window with the WebUI manager (called from main thread)."""
    window.webui_process_manager = webui_manager
    controller = getattr(window, "app_controller", None)
    if controller:
        controller.webui_process_manager = webui_manager
    
    # Set up WebUI status monitoring using the proper framework
    if hasattr(window, 'status_bar_v2') and window.status_bar_v2:
        try:
            webui_panel = getattr(window.status_bar_v2, 'webui_panel', None)
            if webui_panel:
                # Create a proper WebUI connection controller
                from src.controller.webui_connection_controller import WebUIConnectionController
                from src.controller.webui_connection_controller import WebUIConnectionState

                connection_controller = WebUIConnectionController()

                # Connect the status panel to the controller
                status_bar = window.status_bar_v2
                if hasattr(status_bar, "attach_webui_connection_controller"):
                    try:
                        status_bar.attach_webui_connection_controller(connection_controller)
                    except Exception:
                        pass
                last_logged_state = None
                consecutive_failures = 0
                error_logged = False
                core_config_refreshed = False

                def trigger_sidebar_refresh() -> None:
                    sidebar = getattr(window, "sidebar_panel_v2", None)
                    if sidebar is None:
                        return
                    refresh = getattr(sidebar, "refresh_core_config_from_webui", None)
                    if callable(refresh):
                        try:
                            refresh()
                        except Exception:
                            pass

                def sync_state(state: WebUIConnectionState) -> None:
                    if status_bar and hasattr(status_bar, "update_webui_state"):
                        try:
                            status_bar.update_webui_state(state)
                            return
                        except Exception:
                            pass
                    try:
                        webui_panel.set_webui_state(state)
                    except Exception:
                        pass

                def update_status(log_changes: bool = True) -> None:
                    """Update the status panel with current connection state."""
                    nonlocal last_logged_state, consecutive_failures, error_logged, core_config_refreshed
                    try:
                        state = connection_controller.get_state()
                        if state != last_logged_state and log_changes:
                            logging.info(f"WebUI status update: state = {state}")
                            last_logged_state = state

                        if state == WebUIConnectionState.DISCONNECTED:
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0
                            error_logged = False
                            if core_config_refreshed and state in {
                                WebUIConnectionState.DISCONNECTED,
                                WebUIConnectionState.ERROR,
                            }:
                                core_config_refreshed = False

                        if consecutive_failures >= 3:
                            try:
                                new_state = connection_controller.ensure_connected(autostart=True)
                                if new_state != state:
                                    state = new_state
                                    last_logged_state = None  # force log on change
                            except Exception as exc:
                                if not error_logged:
                                    logging.warning("WebUI autostart retry failed after 3 disconnects: %s", exc)
                                    error_logged = True
                                state = WebUIConnectionState.ERROR
                                consecutive_failures = 0

                        sync_state(state)
                        last_logged_state = state
                        if state == WebUIConnectionState.READY and not core_config_refreshed:
                            trigger_sidebar_refresh()
                            core_config_refreshed = True
                    except Exception as e:
                        if not error_logged:
                            logging.warning(f"Status update failed: {e}")
                            error_logged = True
                        sync_state(WebUIConnectionState.ERROR)

                # Set up callbacks for the buttons
                def launch_callback() -> None:
                    nonlocal consecutive_failures, error_logged, last_logged_state
                    try:
                        logging.info("Launch WebUI button clicked")
                        new_state = connection_controller.ensure_connected(autostart=True)
                        sync_state(new_state)
                        if new_state == WebUIConnectionState.READY:
                            try:
                                base_url = connection_controller.get_base_url()
                                logging.info("Opening WebUI in browser at %s", base_url)
                                webbrowser.open_new_tab(base_url)
                            except Exception as exc:
                                logging.warning("Failed to open WebUI browser tab: %s", exc)
                        consecutive_failures = 0
                        error_logged = False
                        last_logged_state = None
                    except Exception as e:
                        logging.warning(f"Failed to launch WebUI: {e}")

                def retry_callback() -> None:
                    nonlocal consecutive_failures, error_logged, last_logged_state
                    try:
                        logging.info("Retry WebUI connection button clicked")
                        new_state = connection_controller.reconnect()
                        sync_state(new_state)
                        consecutive_failures = 0
                        error_logged = False
                        last_logged_state = None
                    except Exception as e:
                        logging.warning(f"Failed to retry WebUI connection: {e}")

                webui_panel.set_launch_callback(launch_callback)
                webui_panel.set_retry_callback(retry_callback)

                # Initial status check
                update_status()

                # Set up periodic status checking
                def periodic_check() -> None:
                    update_status(log_changes=True)
                    window.after(5000, periodic_check)  # Check every 5 seconds

                window.after(1000, periodic_check)  # Start checking after 1 second
                
        except Exception as e:
            logging.debug(f"Failed to set up WebUI status monitoring: {e}")

# --- File Access Logger V2.5 hooks ---
def _install_file_access_hooks(logger: 'FileAccessLogger') -> None:
    """
    Monkeypatch open / Path.open / importlib.import_module so that we can
    record which files are touched at runtime.

    This should only be called when STABLENEW_FILE_ACCESS_LOG=1.
    """
    # 1) Wrap builtins.open
    _orig_open = builtins.open

    def tracking_open(file, *args, **kwargs):
        try:
            p = Path(file)
        except TypeError:
            # not a path-like object, just call original
            return _orig_open(file, *args, **kwargs)

        try:
            if getattr(logger, "_is_writing", False):
                return _orig_open(file, *args, **kwargs)
            if p.resolve() == logger.log_path.resolve():
                return _orig_open(file, *args, **kwargs)
        except Exception:
            # If anything goes wrong in checks, fall back to logging
            pass

        logger.record(p, reason="open", stack="".join(traceback.format_stack(limit=8)))
        return _orig_open(file, *args, **kwargs)

    builtins.open = tracking_open  # type: ignore[assignment]

    # 2) Wrap Path.open
    _orig_path_open = Path.open

    def tracking_path_open(self, *args, **kwargs):
        try:
            if getattr(logger, "_is_writing", False):
                return _orig_path_open(self, *args, **kwargs)
            if self.resolve() == logger.log_path.resolve():
                return _orig_path_open(self, *args, **kwargs)
        except Exception:
            # If resolution fails for any reason, just continue and log
            pass

        logger.record(self, reason="path_open", stack="".join(traceback.format_stack(limit=8)))
        return _orig_path_open(self, *args, **kwargs)

    Path.open = tracking_path_open  # type: ignore[assignment]

    # 3) Wrap importlib.import_module
    _orig_import_module = importlib.import_module

    def tracking_import_module(name, package=None):
        module = _orig_import_module(name, package)
        file = getattr(module, "__file__", None)
        if file:
            try:
                logger.record(Path(file), reason="import", stack=None)
            except Exception:
                # Logging must never break imports
                pass
        return module

    importlib.import_module = tracking_import_module  # type: ignore[assignment]
# --- logging bypass ---


def main() -> None:
    """Main function"""
    setup_logging("INFO")

    # Optional V2.5 file-access logging, controlled by env var
    file_access_logger = None
    if os.environ.get("STABLENEW_FILE_ACCESS_LOG") == "1":
        logs_dir = Path("logs") / "file_access"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"file_access-{int(time.time())}.jsonl"
        file_access_logger = FileAccessLogger(log_path)
        _install_file_access_hooks(file_access_logger)

    logging.info("Starting StableNew V2 GUI (MainWindowV2)")
    # Don't bootstrap WebUI synchronously - do it asynchronously after GUI loads
    webui_manager = None

    single_instance_lock = SingleInstanceLock()
    if not single_instance_lock.acquire():
        msg = (
            "StableNew is already running.\n\n"
            "Please close the existing window before starting a new one."
        )
        if messagebox is not None:
            try:
                messagebox.showerror("StableNew", msg)
            except Exception:
                print(msg, file=sys.stderr)
        else:
            print(msg, file=sys.stderr)
        return

    if tk is None:
        print("Tkinter is not available; cannot start StableNew GUI.", file=sys.stderr)
        single_instance_lock.release()
        return

    auto_exit_seconds = 0.0
    auto_exit_env = os.environ.get("STABLENEW_AUTO_EXIT_SECONDS")
    if auto_exit_env:
        try:
            auto_exit_seconds = float(auto_exit_env)
        except Exception:
            auto_exit_seconds = 0.0

    root, app_state, app_controller, window = build_v2_app(root=tk.Tk(), webui_manager=webui_manager)
    window.set_graceful_exit_handler(
        lambda reason=None: graceful_exit(
            app_controller,
            root,
            single_instance_lock,
            logging.getLogger(__name__),
            window=window,
            reason=reason,
        )
    )

    if auto_exit_seconds > 0:
        try:
            window.schedule_auto_exit(auto_exit_seconds)
        except Exception:
            pass

    root.after(500, lambda: _async_bootstrap_webui(root, app_state, window))

    try:
        root.mainloop()
    except BaseException as exc:
        logger = logging.getLogger(__name__)
        logger.exception("Fatal exception in main loop", exc_info=exc)
        graceful_exit(app_controller, root, single_instance_lock, logger, window=window, reason="fatal-error")
    finally:
        if single_instance_lock.is_acquired():
            single_instance_lock.release()


if __name__ == "__main__":
    main()
