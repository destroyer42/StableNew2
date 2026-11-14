"""One bounded, contained, CPU-only inference as a short-lived child (owner decision D2).

The only process facility used is :func:`src.utils.managed_process.run_bounded`: the child joins its own anonymous OS
container before it runs, a timeout, cancellation or output overflow kills its whole tree, and the call returns even if a
descendant escaped. This module adds no process manager, no listening socket and no lifecycle authority.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from src.ai_assist.argv import (
    PRODUCTION_ALLOWED_FLAGS,
    RunLimits,
    Sampling,
    assert_argv_allowed,
    build_environment,
    build_production_argv,
)
from src.ai_assist.contracts import (
    MAX_RUNTIME_DETAIL_BYTES,
    AssistRequest,
    OutcomeCode,
    RuntimeDetail,
)
from src.ai_assist.framing import FramingError, build_json_schema, render_prompt
from src.ai_assist.manifests import Verification
from src.ai_assist.paths import runtime_dir, work_dir
from src.utils.managed_process import OwnedChildObservation, ProcessOutcome, run_bounded

logger = logging.getLogger(__name__)

#: A request's scratch directory is removed when it ends, so one this old is a leftover of a hard kill, a power loss or a
#: locked file. ``RunLimits.timeout_seconds`` is at most 600 s, so no live request can be this old.
STALE_SCRATCH_SECONDS = 3600.0

CommandFactory = Callable[[Path, list[str]], Sequence[str]]
Runner = Callable[..., ProcessOutcome]
ArgvBuilder = Callable[[Path, Path, Path, RunLimits, Sampling], list[str]]


def default_command(executable: Path, argv: list[str]) -> Sequence[str]:
    return [str(executable), *argv]


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """``code`` is ``None`` when the child produced output to validate; otherwise it is the terminal outcome."""

    code: OutcomeCode | None
    reason: str = ""
    stdout: bytes = b""
    elapsed_ms: int = 0
    exit_code: int | None = None
    #: Raw runtime output for the operator's "Show runtime detail" control; in memory only (see ``RuntimeDetail``).
    detail: RuntimeDetail | None = field(default=None, repr=False, compare=False)


#: ``llama-completion`` ends a generation that stopped on an end-of-generation token with this line on stdout
#: (``LOG(" [end of text]\n")`` in ``tools/completion/completion.cpp``, both pinned tags). It is not model output.
_END_OF_TEXT = b"[end of text]"


def strip_end_of_text(stdout: bytes) -> bytes:
    """Drop the tool's trailing ``[end of text]`` line (and the whitespace around it); nothing else is touched.

    On Windows the line ends in CR LF. Only one marker at the very end is removed, so text the model itself wrote inside
    its JSON can never be mistaken for it."""

    trimmed = stdout.rstrip()
    if trimmed.endswith(_END_OF_TEXT):
        return trimmed[: -len(_END_OF_TEXT)].rstrip()
    return stdout


def _printable(raw: bytes) -> str:
    """Decode bounded raw runtime output for display: replacement for bad UTF-8, control characters shown as ``?``."""

    text = raw.decode("utf-8", errors="replace")
    return "".join(
        ch if ch in "\n\t" or ch.isprintable() else "?" for ch in text.replace("\r\n", "\n")
    )


def runtime_detail(
    exit_code: int | None, stderr: bytes, stdout: bytes, *, with_stdout: bool
) -> RuntimeDetail:
    """The bounded, in-memory detail: the last 2 KB of stderr and, when asked, the first 2 KB of stdout."""

    tail = stderr[-MAX_RUNTIME_DETAIL_BYTES:] if stderr else b""
    head = stdout[:MAX_RUNTIME_DETAIL_BYTES] if with_stdout and stdout else b""
    return RuntimeDetail(exit_code, _printable(tail), _printable(head))


class AiRuntime:
    def __init__(
        self,
        root: Path,
        *,
        command_factory: CommandFactory = default_command,
        environ: Mapping[str, str] | None = None,
        runner: Runner = run_bounded,
        clock: Callable[[], float] = time.monotonic,
        argv_builder: ArgvBuilder = build_production_argv,
        allowed_flags: frozenset[str] = PRODUCTION_ALLOWED_FLAGS,
    ) -> None:
        self._root = root
        self._command_factory = command_factory
        self._environ = os.environ if environ is None else environ
        self._runner = runner
        self._clock = clock
        self._argv_builder = argv_builder
        self._allowed_flags = allowed_flags

    def run_once(
        self,
        verification: Verification,
        request: AssistRequest,
        limits: RunLimits,
        sampling: Sampling,
        cancel: Callable[[], bool],
        cancelled_outcome: Callable[[], tuple[OutcomeCode, str]],
        *,
        observe: Callable[[OwnedChildObservation], None] | None = None,
    ) -> RuntimeResult:
        """Run the pinned runtime once for ``request``. ``verification`` must be ``ok`` (the caller checked)."""

        if (
            not verification.ok
            or verification.executable is None
            or verification.model_path is None
        ):
            return RuntimeResult(OutcomeCode.INTEGRITY_FAILED, "verification_not_ok")
        assert verification.build is not None
        try:
            prompt = render_prompt(request)
        except FramingError:
            return RuntimeResult(OutcomeCode.INVALID_REQUEST, "reserved_marker_in_text")
        schema = build_json_schema(request)

        scratch = work_dir(self._root, request.request_id)
        started = self._clock()
        try:
            scratch.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            # Another request owns this directory; it must not be cleaned up by this one.
            return RuntimeResult(OutcomeCode.BUSY, "request_id_in_use")
        except OSError:
            logger.warning("AI assist could not create its scratch directory", exc_info=True)
            return RuntimeResult(OutcomeCode.UNAVAILABLE, "scratch_unavailable")
        try:
            prompt_file = scratch / "prompt.txt"
            schema_file = scratch / "schema.json"
            prompt_file.write_text(prompt, encoding="utf-8", newline="\n")
            schema_file.write_text(
                json.dumps(schema, sort_keys=True), encoding="utf-8", newline="\n"
            )
            argv = self._argv_builder(
                verification.model_path, prompt_file, schema_file, limits, sampling
            )
            assert_argv_allowed(argv, self._allowed_flags)
            command = self._command_factory(verification.executable, argv)
            runtime_root = runtime_dir(self._root, verification.build.build_id)
            observation_options = {"observe": observe} if observe is not None else {}
            outcome = self._runner(
                command,
                timeout_seconds=limits.timeout_seconds,
                max_stdout_bytes=limits.max_stdout_bytes,
                cancel=cancel,
                cwd=scratch,
                env=build_environment(runtime_root, self._environ, scratch),
                **observation_options,
            )
        except OSError:
            logger.warning("AI assist could not prepare its scratch directory", exc_info=True)
            return RuntimeResult(OutcomeCode.UNAVAILABLE, "scratch_unavailable")
        finally:
            self._cleanup(scratch)

        elapsed_ms = int((self._clock() - started) * 1000)
        if outcome.launch_error:
            reason = (
                "containment_unavailable"
                if outcome.launch_error.startswith("containment unavailable")
                else "launch_failed"
            )
            return RuntimeResult(OutcomeCode.UNAVAILABLE, reason, elapsed_ms=elapsed_ms)
        code_value = outcome.returncode
        if outcome.cancelled:
            code, reason = cancelled_outcome()
            return RuntimeResult(code, reason, elapsed_ms=elapsed_ms, exit_code=code_value)
        if outcome.timed_out:
            return RuntimeResult(
                OutcomeCode.TIMEOUT,
                "wall_clock_limit",
                elapsed_ms=elapsed_ms,
                exit_code=code_value,
                detail=runtime_detail(code_value, outcome.stderr, b"", with_stdout=False),
            )
        if outcome.output_truncated:
            return RuntimeResult(
                OutcomeCode.MALFORMED,
                "output_too_large",
                elapsed_ms=elapsed_ms,
                exit_code=code_value,
                detail=runtime_detail(code_value, outcome.stderr, outcome.stdout, with_stdout=True),
            )
        if code_value != 0:
            return RuntimeResult(
                OutcomeCode.UNAVAILABLE,
                "child_exit_nonzero",
                elapsed_ms=elapsed_ms,
                exit_code=code_value,
                detail=runtime_detail(code_value, outcome.stderr, b"", with_stdout=False),
            )
        stdout = strip_end_of_text(outcome.stdout)
        return RuntimeResult(
            None,
            "",
            stdout=stdout,
            elapsed_ms=elapsed_ms,
            exit_code=code_value,
            # Kept so a MALFORMED verdict can show the start of the output; the service drops it for a suggestion.
            detail=runtime_detail(code_value, outcome.stderr, stdout, with_stdout=True),
        )

    def sweep_stale_scratch(
        self,
        max_age_seconds: float = STALE_SCRATCH_SECONDS,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> int:
        """Remove leftover per-request scratch directories (they hold prompt text). Returns how many were removed.

        Only direct children (never a symlink or junction) of ``<root>/work`` older than ``max_age_seconds`` are touched, so another live
        request (this process's or another's) is never disturbed. A directory that cannot be removed is logged and left
        for the next sweep; nothing here ever raises.
        """

        base = self._root / "work"
        removed = 0
        try:
            children = list(base.iterdir()) if base.is_dir() else []
        except OSError:
            logger.warning("AI assist scratch area could not be listed", exc_info=True)
            return 0
        for child in children:
            try:
                if child.is_symlink() or child.is_junction() or not child.is_dir():
                    continue
                if wall_clock() - child.stat().st_mtime < max_age_seconds:
                    continue
                shutil.rmtree(child)
                removed += 1
            except OSError:
                logger.warning(
                    "A stale AI assist scratch directory could not be removed", exc_info=True
                )
        return removed

    @staticmethod
    def _cleanup(scratch: Path) -> None:
        if not scratch.exists():
            return
        try:
            shutil.rmtree(scratch)
        except OSError:
            logger.warning("AI assist scratch directory could not be removed", exc_info=True)


__all__ = [
    "AiRuntime",
    "CommandFactory",
    "RuntimeResult",
    "default_command",
    "runtime_detail",
    "strip_end_of_text",
]
