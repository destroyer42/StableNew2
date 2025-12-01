"""Centralized graceful exit helper for the StableNew V2 GUI."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, NoReturn, Optional

from src.config.app_config import is_debug_shutdown_inspector_enabled
from src.controller.app_controller import AppController
from src.utils.debug_shutdown_inspector import log_shutdown_state
from src.utils.single_instance import SingleInstanceLock

_shutdown_lock = threading.Lock()
_shutdown_committed = False


def graceful_exit(
    controller: Optional[AppController],
    root: Optional[Any],
    single_instance_lock: Optional[SingleInstanceLock],
    logger: logging.Logger,
    *,
    window=None,
    reason: str | None = None,
    shutdown_timeout: float = 0.1,
) -> NoReturn:
    """Perform an orderly shutdown and ensure the process exits."""

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
    logger.info("[graceful_exit] Initiating (%s)", label)

    if controller is not None:
        try:
            controller.shutdown_app(label)
        except Exception:
            logger.exception("graceful_exit: controller.shutdown_app failed")

    if window is not None:
        try:
            window.cleanup()
        except Exception:
            logger.exception("graceful_exit: window.cleanup failed")

    if root is not None:
        try:
            root.quit()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

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

    time.sleep(shutdown_timeout)
    os._exit(0)
