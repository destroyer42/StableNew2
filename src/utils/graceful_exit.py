"""Centralized graceful exit helper for the StableNew V2 GUI."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, NoReturn

from src.config.app_config import is_debug_shutdown_inspector_enabled
from src.controller.app_controller import AppController
from src.utils.debug_shutdown_inspector import log_shutdown_state
from src.utils.single_instance import SingleInstanceLock

_shutdown_lock = threading.Lock()
_shutdown_committed = False


def graceful_exit(
    controller: AppController | None,
    root: Any | None,
    single_instance_lock: SingleInstanceLock | None,
    logger: logging.Logger,
    *,
    window=None,
    reason: str | None = None,
) -> NoReturn:
    """Perform an orderly shutdown and force the process to exit quickly."""

    global _shutdown_committed
    with _shutdown_lock:
        if _shutdown_committed:
            if single_instance_lock and single_instance_lock.is_acquired():
                try:
                    single_instance_lock.release()
                except Exception:
                    pass
            os._exit(0)
        _shutdown_committed = True

    label = reason or "graceful-exit"
    shutdown_timeout = float(os.environ.get("STABLENEW_SHUTDOWN_TIMEOUT", "2.0"))
    logger.info("[graceful_exit] Initiating (%s)", label)

    # CRITICAL: Shutdown controller BEFORE destroying Tk root
    # If root is destroyed first, process exits before cleanup completes
    logger.info("[graceful_exit] Step 1: Shutting down app controller...")
    if controller is not None:
        try:
            controller.shutdown_app(label)
            logger.info("[graceful_exit] Step 1: Controller shutdown complete")
        except Exception:
            logger.exception("graceful_exit: controller.shutdown_app failed")
    else:
        logger.info("[graceful_exit] Step 1: No controller to shutdown")

    logger.info("[graceful_exit] Step 2: Cleaning up window...")
    if window is not None:
        try:
            window.cleanup()
            logger.info("[graceful_exit] Step 2: Window cleanup complete")
        except Exception:
            logger.exception("graceful_exit: window.cleanup failed")
    else:
        logger.info("[graceful_exit] Step 2: No window to cleanup")

    logger.info("[graceful_exit] Step 3: Destroying Tk root...")
    if root is not None:
        try:
            root.quit()
            logger.info("[graceful_exit] Step 3a: root.quit() complete")
        except Exception:
            logger.exception("graceful_exit: root.quit() failed")
        try:
            root.destroy()
            logger.info("[graceful_exit] Step 3b: root.destroy() complete")
        except Exception:
            logger.exception("graceful_exit: root.destroy() failed")
    else:
        logger.info("[graceful_exit] Step 3: No root to destroy")

    deadline = time.time() + shutdown_timeout
    while time.time() < deadline:
        try:
            if controller is None or getattr(controller, "_shutdown_completed", False):
                break
        except Exception:
            break
        time.sleep(0.05)

    if single_instance_lock is not None:
        try:
            single_instance_lock.release()
        except Exception:
            logger.exception("graceful_exit: failed to release single-instance lock")

    if is_debug_shutdown_inspector_enabled():
        try:
            log_shutdown_state(logger, label)
        except Exception:
            logger.exception("graceful_exit: shutdown inspector failed")

    logger.info("graceful_exit: forcing process exit (timeout=%.1fs)", shutdown_timeout)
    os._exit(0)
