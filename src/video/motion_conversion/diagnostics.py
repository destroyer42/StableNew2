"""Why a Blender conversion step failed, in words an operator can act on (PR-VID-MOTION-356).

A Blender child can fail in ways that all used to read "Blender exited with code 1": the file is bad, the rig is wrong for the
plan, the renderer lacks a capability, Blender crashed or ran out of memory, or it simply took too long.  This module turns the
child's exit status, the report the render script writes, and the *tail* of its console output into one classified failure and
a bounded, redacted JSON report.  Reports live in a per-user folder outside the repository, keep only the newest few, and never
contain the user's profile path or anything that looks like a credential.  Nothing here starts a process or reads a media file.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_text

DIAGNOSTIC_SCHEMA = "stablenew.motion-conversion-diagnostic.v1"
DIAGNOSTICS_DIRNAME = "motion_conversion_diagnostics"
#: Newest reports kept, and the most disk they may use together.  Older ones are deleted when a new one is written.
MAX_REPORTS = 25
MAX_TOTAL_BYTES = 4 * 1024 * 1024
#: How much of each console stream goes into a report (the end of it: that is where a crash explains itself).
TAIL_BYTES = 6 * 1024
MAX_EXCERPT_LINES = 4
_REPORT_NAME = re.compile(r"^diag-\d{8}T\d{6}Z-[0-9a-f]{8}\.json$")

KIND_ASSET = "asset_failure"
KIND_RIG = "invalid_rig"
KIND_CAPABILITY = "missing_renderer_capability"
KIND_CRASH = "blender_crash"
KIND_MEMORY = "out_of_memory"
KIND_TIMEOUT = "timeout"
KIND_CANCELLED = "cancelled"
KIND_OUTPUT = "output_verification"
KIND_ENCODE = "encode_failure"
KIND_LAUNCH = "launch_failure"
KIND_SOURCE = "source_changed"
KIND_STORAGE = "storage_failure"
KIND_REFUSED = "plan_refused"
KIND_LABELS = {
    KIND_ASSET: "The animation file could not be read or has no usable animation",
    KIND_RIG: "The rig does not suit this conversion",
    KIND_CAPABILITY: "This Blender cannot do the required rendering",
    KIND_CRASH: "Blender stopped unexpectedly",
    KIND_MEMORY: "The computer ran out of memory",
    KIND_TIMEOUT: "Blender did not finish in time",
    KIND_CANCELLED: "Cancelled",
    KIND_OUTPUT: "The render did not pass verification",
    KIND_ENCODE: "The video could not be encoded or verified",
    KIND_LAUNCH: "Blender could not be started",
    KIND_SOURCE: "The input file changed",
    KIND_STORAGE: "The output folder could not be used",
    KIND_REFUSED: "The conversion was refused before rendering",
}

# Windows NTSTATUS codes a process can exit with when it is killed by the OS rather than by its own code.
_NT_MEMORY = {0xC0000017, 0xC000009A, 0xC000012D}  # no memory, insufficient resources, commit limit
_NT_FAULT_MASK = 0xC0000000
_MEMORY_WORDS = re.compile(
    r"out of memory|memoryerror|bad_alloc|cannot allocate|failed to allocate|not enough memory|insufficient memory|"
    r"commit limit|unable to allocate",
    re.IGNORECASE,
)
_RIG_WORDS = re.compile(
    r"rest pose|armature|not present under the same name|no skeleton|no data that can drive|retarget|bone ",
    re.IGNORECASE,
)
_CAPABILITY_WORDS = re.compile(
    r"no fbx importer|cpu-only rendering|render kernels|cycles|no module named|has no attribute|unknown operator|"
    r"not (?:available|supported) in this blender",
    re.IGNORECASE,
)
_ASSET_WORDS = re.compile(
    r"no animation action|cannot read|failed to read|corrupt|unsupported|not a (?:valid )?(?:fbx|bvh)|unexpected end|"
    r"invalid (?:file|fbx|bvh)|nothing visible to frame|needs a character mesh|frame rate .* differs",
    re.IGNORECASE,
)
_ERROR_LINE = re.compile(r"(?:^|\s)(?:error|exception|traceback|fatal|crash)\b", re.IGNORECASE)
_SECRET = re.compile(
    r"(?i)\b(token|secret|passw(?:or)?d|api[_-]?key|authorization)\b(\s*[=:]\s*)(?:(?:bearer|basic)\s+)?\S+"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")
_USER_PROFILE = re.compile(r"(?i)\b([A-Z]:[\\/]+Users[\\/]+)[^\\/\s\"'<>|:*?]+")
_POSIX_HOME = re.compile(r"(/(?:home|Users)/)[^/\s\"']+")


@dataclass(frozen=True, slots=True)
class FailureInfo:
    """A classified failure: ``kind`` for software, ``message`` for the operator, ``detail`` for the report."""

    kind: str
    message: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


def _tail_text(data: bytes | str, limit: int = TAIL_BYTES) -> str:
    raw = data if isinstance(data, bytes) else data.encode("utf-8", "replace")
    return raw[-limit:].decode("utf-8", "replace")


def error_excerpt(*streams: bytes | str, limit: int = MAX_EXCERPT_LINES) -> str:
    """The last few lines of the given output that look like errors, joined; empty when none do."""

    picked: list[str] = []
    for stream in streams:
        for line in _tail_text(stream).splitlines():
            text = line.strip()
            if text and _ERROR_LINE.search(text) and text not in picked:
                picked.append(text[:200])
    return " | ".join(picked[-limit:])


def exit_code_text(code: int | None) -> str:
    if code is None:
        return "none"
    if code < 0:
        code &= 0xFFFFFFFF
    return f"{code} (0x{code:08X})" if code > 255 else str(code)


def _is_os_fault(code: int | None) -> bool:
    if code is None:
        return False
    return (code & 0xFFFFFFFF) >= _NT_FAULT_MASK or code < 0


def classify_script_error(text: str) -> str:
    """The kind of a failure the render script itself reported (``Type: message`` text); defaults to the asset."""

    if _MEMORY_WORDS.search(text):
        return KIND_MEMORY
    if _CAPABILITY_WORDS.search(text) and not _RIG_WORDS.search(text):
        return KIND_CAPABILITY
    if _RIG_WORDS.search(text):
        return KIND_RIG
    return KIND_ASSET


def classify_blender_failure(
    action: str,
    *,
    returncode: int | None,
    timed_out: bool,
    cancelled: bool,
    launch_error: str,
    report: Mapping[str, Any] | None,
    stdout: bytes,
    stderr: bytes,
    timeout_seconds: float,
) -> FailureInfo:
    """Turn one failed Blender child into an operator-readable cause.  Never invents a cause it cannot see."""

    detail: dict[str, Any] = {"action": action, "exit_code": exit_code_text(returncode)}
    if launch_error:
        return FailureInfo(KIND_LAUNCH, f"Blender could not be started: {launch_error}", detail)
    if cancelled:
        return FailureInfo(KIND_CANCELLED, "Cancelled.", detail)
    if timed_out:
        return FailureInfo(
            KIND_TIMEOUT,
            f"Blender did not finish within {int(timeout_seconds)} s and was stopped.",
            detail,
        )
    excerpt = error_excerpt(stderr, stdout)
    if report is not None and not report.get("ok", False) and report.get("error"):
        error = str(report["error"])
        kind = classify_script_error(error)
        detail["script_error"] = error[:400]
        return FailureInfo(kind, _with_hint(kind, error), detail)
    combined = _tail_text(stderr) + "\n" + _tail_text(stdout)
    if _MEMORY_WORDS.search(combined) or (
        returncode is not None and (returncode & 0xFFFFFFFF) in _NT_MEMORY
    ):
        detail["output_excerpt"] = excerpt
        return FailureInfo(
            KIND_MEMORY,
            "Blender ran out of memory"
            + (f" ({excerpt})" if excerpt else "")
            + ". Close other programs (such as Comfy or Forge) or choose a shorter segment or a smaller frame size.",
            detail,
        )
    if report is None:
        # Blender ended without writing its report: it never reached the script, or it died inside it.
        detail["output_excerpt"] = excerpt
        if _is_os_fault(returncode):
            return FailureInfo(
                KIND_CRASH,
                f"Blender crashed (exit code {exit_code_text(returncode)}) before it wrote a result"
                + (f": {excerpt}" if excerpt else "."),
                detail,
            )
        return FailureInfo(
            KIND_CRASH,
            f"Blender exited with code {exit_code_text(returncode)} before it wrote a result"
            + (f": {excerpt}" if excerpt else " and printed no error."),
            detail,
        )
    detail["output_excerpt"] = excerpt
    return FailureInfo(
        KIND_ASSET,
        f"Blender reported a problem with no detail (exit code {exit_code_text(returncode)}).",
        detail,
    )


def _with_hint(kind: str, error: str) -> str:
    text = error.strip()
    if kind == KIND_MEMORY:
        return f"{text}. Close other programs or choose a shorter segment or a smaller frame size."
    if kind == KIND_CAPABILITY:
        return f"{text} This Blender build cannot do what the conversion needs; install Blender 4.2 or newer."
    return text


# ------------------------------------------------------------------ redaction


def redactor(extra_paths: Iterable[tuple[str | Path, str]] = ()) -> Callable[[str], str]:
    """A function that removes the user's profile path, named folders and credential-like words from text."""

    pairs: list[tuple[str, str]] = []
    for path, label in extra_paths:
        text = str(path).strip()
        if len(text) > 3:
            pairs.append((text, label))
            pairs.append((text.replace("\\", "/"), label))
    for home in {str(Path.home()), os.environ.get("USERPROFILE", "")}:
        if home and len(home) > 3:
            pairs.append((home, "<home>"))
            pairs.append((home.replace("\\", "/"), "<home>"))
    pairs.sort(
        key=lambda pair: len(pair[0]), reverse=True
    )  # the longest folder first, so a subfolder keeps its own label
    name = os.environ.get("USERNAME") or os.environ.get("USER") or ""

    def apply(value: str) -> str:
        text = value
        for needle, label in pairs:
            text = re.sub(re.escape(needle), label, text, flags=re.IGNORECASE)
        text = _USER_PROFILE.sub(r"\1<user>", text)
        text = _POSIX_HOME.sub(r"\1<user>", text)
        text = _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", text)
        text = _BEARER.sub(lambda m: f"{m.group(1)} <redacted>", text)
        if len(name) >= 4:
            text = re.sub(rf"(?i)\b{re.escape(name)}\b", "<user>", text)
        return text

    return apply


def redact_value(value: Any, apply: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return apply(value)
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, apply) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v, apply) for v in value]
    return value


# ------------------------------------------------------------------ report


def _memory_snapshot() -> dict[str, Any]:
    try:
        import psutil

        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {
            "physical_total_mb": int(memory.total / 1048576),
            "physical_available_mb": int(memory.available / 1048576),
            "physical_percent_used": float(memory.percent),
            "swap_percent_used": float(swap.percent),
        }
    except Exception:  # noqa: BLE001 - a diagnostic aid, never a reason to fail the report
        return {}


def build_report(
    failure: FailureInfo,
    *,
    context: Mapping[str, Any],
    process: Mapping[str, Any],
    stdout: bytes | str = b"",
    stderr: bytes | str = b"",
    script_report: Mapping[str, Any] | None = None,
    redact: Callable[[str], str],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """The JSON-safe, redacted report for one failure.  ``context`` and ``process`` are small mappings of plain facts."""

    script: dict[str, Any] = {}
    if script_report:
        script = {
            "ok": bool(script_report.get("ok")),
            "error": str(script_report.get("error", ""))[:600],
            "trace": str(script_report.get("trace", ""))[-1500:],
        }
    report = {
        "schema": DIAGNOSTIC_SCHEMA,
        "created_at": clock().isoformat(),
        "kind": failure.kind,
        "summary": failure.label,
        "message": failure.message,
        "detail": dict(failure.detail),
        "context": dict(context),
        "process": dict(process),
        "script_report": script,
        "memory": _memory_snapshot(),
        "stdout_tail": _tail_text(stdout),
        "stderr_tail": _tail_text(stderr),
        "redacted": True,
    }
    redacted: dict[str, Any] = redact_value(report, redact)
    return redacted


def write_report(directory: str | Path, report: Mapping[str, Any]) -> Path:
    """Write ``report`` atomically as a new file in ``directory`` and prune old ones; raises ``OSError`` on failure."""

    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    token = os.urandom(4).hex()
    path = folder / f"diag-{stamp}-{token}.json"
    atomic_write_text(path, json.dumps(report, indent=2, sort_keys=True))
    prune_reports(folder)
    return path


def prune_reports(
    directory: str | Path, *, keep: int = MAX_REPORTS, max_bytes: int = MAX_TOTAL_BYTES
) -> int:
    """Delete the oldest report files beyond the count or byte budget (only files this module names).  Returns removed."""

    folder = Path(directory)
    try:
        found = [
            (p.stat().st_mtime, p, p.stat().st_size)
            for p in folder.iterdir()
            if p.is_file() and _REPORT_NAME.match(p.name)
        ]
    except OSError:
        return 0
    found.sort(key=lambda row: row[0], reverse=True)
    removed, total = 0, 0
    for index, (_, path, size) in enumerate(found):
        total += size
        if index >= keep or total > max_bytes:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def report_text(path: str | Path, *, limit: int = 128 * 1024) -> str:
    """The report a result names, for Copy.  Only a file this module wrote (by name) is read; otherwise empty."""

    target = Path(path)
    if not _REPORT_NAME.match(target.name) or not target.is_file():
        return ""
    try:
        with target.open("rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def default_directory() -> Path:
    """The per-user folder for reports, beside the Motion Library pointer file (outside any repository)."""

    from src.video.motion_library.config import config_path

    return config_path().with_name(DIAGNOSTICS_DIRNAME)


__all__ = [
    "DIAGNOSTIC_SCHEMA",
    "FailureInfo",
    "KIND_ASSET",
    "KIND_CANCELLED",
    "KIND_CAPABILITY",
    "KIND_CRASH",
    "KIND_ENCODE",
    "KIND_LABELS",
    "KIND_LAUNCH",
    "KIND_MEMORY",
    "KIND_OUTPUT",
    "KIND_REFUSED",
    "KIND_RIG",
    "KIND_SOURCE",
    "KIND_STORAGE",
    "KIND_TIMEOUT",
    "build_report",
    "classify_blender_failure",
    "classify_script_error",
    "default_directory",
    "error_excerpt",
    "prune_reports",
    "redactor",
    "report_text",
    "write_report",
]
