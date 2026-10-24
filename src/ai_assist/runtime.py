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
from dataclasses import dataclass
from pathlib import Path

from src.ai_assist.argv import RunLimits, Sampling, build_argv, build_environment
from src.ai_assist.contracts import AssistRequest, OutcomeCode
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


class AiRuntime:
    def __init__(
        self,
        root: Path,
        *,
        command_factory: CommandFactory = default_command,
        environ: Mapping[str, str] | None = None,
        runner: Runner = run_bounded,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root = root
        self._command_factory = command_factory
        self._environ = os.environ if environ is None else environ
        self._runner = runner
        self._clock = clock

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
            argv = build_argv(verification.model_path, prompt_file, schema_file, limits, sampling)
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
        if outcome.cancelled:
            code, reason = cancelled_outcome()
            return RuntimeResult(code, reason, elapsed_ms=elapsed_ms, exit_code=outcome.returncode)
        if outcome.timed_out:
            return RuntimeResult(OutcomeCode.TIMEOUT, "wall_clock_limit", elapsed_ms=elapsed_ms)
        if outcome.output_truncated:
            return RuntimeResult(OutcomeCode.MALFORMED, "output_too_large", elapsed_ms=elapsed_ms)
        if outcome.returncode != 0:
            return RuntimeResult(
                OutcomeCode.UNAVAILABLE,
                "child_exit_nonzero",
                elapsed_ms=elapsed_ms,
                exit_code=outcome.returncode,
            )
        return RuntimeResult(
            None, "", stdout=outcome.stdout, elapsed_ms=elapsed_ms, exit_code=outcome.returncode
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


__all__ = ["AiRuntime", "CommandFactory", "RuntimeResult", "default_command"]
