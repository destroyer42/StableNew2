"""Helpers for consistent process logging messages."""

from __future__ import annotations

import shlex
import uuid
from collections.abc import Sequence

PROCESS_LOG_PREFIX = "[PROC]"


def build_run_session_id() -> str:
    """Return a short, pseudo-random identifier for a launcher session."""

    return uuid.uuid4().hex[:8]


def format_cmdline(cmdline: Sequence[str]) -> str:
    """Convert a command line into a quoted, space-delimited string."""

    if not cmdline:
        return "<empty>"

    parts: list[str] = []
    for piece in cmdline:
        if not piece:
            continue
        try:
            parts.append(shlex.quote(piece))
        except Exception:
            parts.append(str(piece))
    return " ".join(parts) or "<empty>"


def format_launch_message(
    *,
    run_session_id: str,
    pid: int | None,
    command: Sequence[str],
    cwd: str | None,
) -> str:
    """Build a short message describing a process launch event."""

    segments = [PROCESS_LOG_PREFIX, "launch", f"run_session={run_session_id}"]
    if pid is not None:
        segments.append(f"pid={pid}")
    cmd = format_cmdline(command)
    segments.append(f'cmd="{cmd}"')
    if cwd:
        segments.append(f'cwd="{cwd}"')
    return " ".join(segments)
