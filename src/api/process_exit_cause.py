"""Turn a managed process's exit code and output tail into one operator-readable cause (N11).

On Windows a crashed Python process usually ends with an NTSTATUS code (``3221225477`` is ``0xC0000005``, an access
violation) and a Python-level failure ends with code 1 after printing a traceback. The raw number alone told the
owner nothing after a walk-away batch. Pure functions; no I/O.
"""

from __future__ import annotations

import re
import signal

from src.utils.diagnostic_redaction import redact_text

MAX_CAUSE_CHARS = 400

# NTSTATUS / exception codes a crashed Windows process commonly ends with.
_WINDOWS_STATUS: dict[int, str] = {
    0xC0000005: "access violation (a native crash, often a GPU driver, CUDA or extension fault)",
    0xC00000FD: "stack overflow",
    0xC0000409: "fast fail / stack buffer overrun (a native library aborted the process)",
    0xC000013A: "stopped by Ctrl+C or its console window closing",
    0xC0000017: "out of memory (no system memory left)",
    0xC000012D: "out of virtual memory (the page-file commit limit was reached)",
    0xC0000142: "a DLL failed to initialize",
    0xC0000135: "a required DLL was not found",
    0xC000001D: "illegal CPU instruction",
    0xC0000094: "integer divide by zero",
    0xC0000374: "heap corruption",
    0xC0000420: "assertion failure",
    0xE06D7363: "an unhandled C++ exception",
    0x40010004: "terminated by a debugger or another process",
    0xCFFFFFFF: "the process was terminated abnormally",
}
_EXCEPTION_LINE = re.compile(
    r"^(?:[A-Za-z_][\w.]*\.)?[A-Za-z_]\w*(?:Error|Exception|Exit|Interrupt|Fault)\b.*"
)
_OOM = re.compile(
    r"(CUDA out of memory|OutOfMemoryError|CUDA error[^\n]*|DefaultCPUAllocator: not enough memory[^\n]*)"
)


def _status_text(exit_code: int) -> tuple[str, str] | None:
    unsigned = exit_code & 0xFFFFFFFF
    name = _WINDOWS_STATUS.get(unsigned)
    if name is None:
        return None
    return f"0x{unsigned:08X}", name


# POSIX names for the managed runtime in a Linux container (the ``signal`` module on Windows lacks most of them).
_POSIX_SIGNALS = {
    1: "SIGHUP",
    2: "SIGINT",
    6: "SIGABRT",
    9: "SIGKILL",
    11: "SIGSEGV",
    15: "SIGTERM",
}


def _signal_name(number: int) -> str:
    if number in _POSIX_SIGNALS:
        return _POSIX_SIGNALS[number]
    try:
        return signal.Signals(number).name
    except ValueError:
        return ""


def last_failure_line(*tails: str) -> str:
    """The most telling failure line in the output: the last Python exception line, else a CUDA/allocator message."""

    for tail in tails:
        lines = [line.strip() for line in str(tail or "").splitlines() if line.strip()]
        for line in reversed(lines):
            if _EXCEPTION_LINE.match(line):
                return line
        for line in reversed(lines):
            if _OOM.search(line):
                return line
    return ""


def describe_exit_cause(
    exit_code: int | None, *, stderr_tail: str = "", stdout_tail: str = ""
) -> str:
    """One bounded line: the exit code, what it means, and the last failure line printed (``""`` while alive)."""

    if exit_code is None:
        return ""
    status = _status_text(exit_code)
    if status is not None:
        text = f"exit code {status[0]}: {status[1]}"
    elif exit_code < 0:
        name = _signal_name(-exit_code)
        text = f"killed by signal {-exit_code}" + (f" ({name})" if name else "")
    elif exit_code == 0:
        text = "exited normally (code 0) without being asked to stop"
    else:
        text = f"exit code {exit_code}"
    failure = last_failure_line(stderr_tail, stdout_tail)
    if failure:
        text = f"{text}; last error: {failure}"
    line = redact_text(" ".join(text.split()))
    return line if len(line) <= MAX_CAUSE_CHARS else line[: MAX_CAUSE_CHARS - 3].rstrip() + "..."
