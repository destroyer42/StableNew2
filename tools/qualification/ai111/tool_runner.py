"""PR-AI-QUAL-114E: run a short OS tool (``tracerpt``, ``logman query``, ``icacls``) through the bounded runner, standard-user.

This is deliberately NOT part of ``capture_control.py``: that file is the elevated surface and imports only the standard
library, so the one file an operator reviews and SHA-pins is everything that runs with the administrator token.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from src.utils.managed_process import ProcessOutcome, run_bounded
from tools.qualification.ai111.capture_control import CaptureRefused

_TOOL_TIMEOUT_SECONDS = 60.0
_TOOL_OUTPUT_BYTES = 256 * 1024


def bounded_tool(command: Sequence[str]) -> tuple[int, str]:
    outcome: ProcessOutcome = run_bounded(
        command, timeout_seconds=_TOOL_TIMEOUT_SECONDS, max_stdout_bytes=_TOOL_OUTPUT_BYTES
    )
    if outcome.launch_error:
        raise CaptureRefused(f"{Path(command[0]).name}: {outcome.launch_error}")
    text = (outcome.stdout + outcome.stderr).decode("utf-8", "replace")
    if outcome.timed_out:
        raise CaptureRefused(f"{Path(command[0]).name} timed out")
    return int(outcome.returncode or 0), text
