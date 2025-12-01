"""Utilities for logging detailed shutdown state diagnostics."""

from __future__ import annotations

import logging
import os
import threading
from typing import Iterable

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - best-effort instrumentation
    psutil = None  # type: ignore


def _log_thread_state(logger: logging.Logger, thread: threading.Thread) -> None:
    logger.info(
        "Thread: name=%s daemon=%s alive=%s ident=%s",
        thread.name,
        thread.daemon,
        thread.is_alive(),
        thread.ident,
    )


def _log_child_processes(logger: logging.Logger) -> None:
    if psutil is None:
        logger.debug("Shutdown inspector: psutil unavailable, skipping child process logging.")
        return
    try:
        current = psutil.Process(os.getpid())
        children = current.children(recursive=True)
    except Exception:
        logger.exception("Shutdown inspector: failed to enumerate child processes")
        return

    if not children:
        logger.info("Shutdown inspector: no child processes attached.")
        return

    for child in children:
        try:
            cmdline = " ".join(child.cmdline())
        except Exception:
            cmdline = "<unavailable>"
        logger.info(
            "Child process: pid=%s name=%s cmdline=%s",
            child.pid,
            child.name(),
            cmdline,
        )


def log_shutdown_state(logger: logging.Logger, label: str) -> None:
    """Log thread and child process state to help debug shutdown hangs."""
    logger.info("=== Shutdown inspector (%s) ===", label)
    for thread in threading.enumerate():
        _log_thread_state(logger, thread)
    _log_child_processes(logger)
