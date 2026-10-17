"""Best-effort, durable survivor telemetry for active GPU pipeline jobs.

The recorder is intentionally outside queue, repository, process-lifecycle,
and execution-control authority.  It cannot cancel, retry, start, stop, or
adopt a runtime.  Its purpose is to leave a flushed record immediately before
an operating-system or display-driver failure where normal diagnostics may not
complete.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.process_inspector_v2 import (
    collect_process_risk_snapshot,
    query_gpu_survivor_snapshot,
)
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)

SCHEMA = "stablenew.gpu-survivor.v1"
DEFAULT_OUTPUT_DIR = Path("reports") / "diagnostics" / "gpu_survivor"
# Job recorders sample fast enough to bracket a device loss that takes well under a second to show.
JOB_SAMPLE_INTERVAL_S = 0.5
# The app-session recorder keeps the lead-up to a loss that happens outside any job (startup, model load, idle).
SESSION_OUTPUT_SUBDIR = "session"
SESSION_SAMPLE_INTERVAL_S = 5.0
SESSION_MAX_BYTES = 4_000_000
SESSION_BACKUP_COUNT = 6
SESSION_ENV_FLAG = "STABLENEW_GPU_SESSION_TELEMETRY"
_SESSION_DISABLED_VALUES = frozenset({"0", "false", "off", "no", "disabled"})

SnapshotProvider = Callable[[], Mapping[str, Any] | None]
PresenceProvider = Callable[[], Mapping[str, Any] | None]


class GpuSurvivorTelemetry:
    """Write compact, fsynced samples while one GPU-capable NJR is active."""

    def __init__(
        self,
        *,
        job_id: str,
        run_id: str,
        workflow: list[str],
        backend_id: str | None,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        output_dir: Path | str = DEFAULT_OUTPUT_DIR,
        interval_s: float = JOB_SAMPLE_INTERVAL_S,
        max_bytes: int = 2_000_000,
        backup_count: int = 3,
        snapshot_provider: SnapshotProvider | None = None,
        presence_provider: PresenceProvider | None = None,
        lifecycle: str = "job",
    ) -> None:
        self._job_id = str(job_id)
        self._run_id = str(run_id)
        self._workflow = [str(stage) for stage in workflow]
        self._backend_id = str(backend_id or "") or None
        self._workflow_id = str(workflow_id or "") or None
        self._workflow_version = str(workflow_version or "") or None
        self._stage: str | None = None
        self._output_dir = Path(output_dir)
        self._path = self._output_dir / "survivor.jsonl"
        self._interval_s = max(0.2, float(interval_s))
        self._max_bytes = max(1024, int(max_bytes))
        self._backup_count = max(1, int(backup_count))
        # The default path keeps the reason a query returned nothing (gpu_lost, timeout, ...); an injected provider
        # only returns a snapshot, so no query status is recorded for it.
        self._snapshot_provider = snapshot_provider
        self._presence_provider = presence_provider or collect_process_risk_snapshot
        self._lifecycle = str(lifecycle or "job")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def path(self) -> Path:
        return self._path

    def start(self) -> None:
        """Start observation.  Recorder failure never affects job execution."""

        with self._lock:
            if self._thread is not None:
                return
            self._record_event(f"{self._lifecycle}_started", include_presence=True)
            try:
                self._thread = get_thread_registry().spawn(
                    target=self._sample_loop,
                    name=f"GpuSurvivorTelemetry-{self._job_id[:8]}",
                    daemon=False,
                    purpose="Durable observation of GPU state for an active job or app session",
                )
            except Exception:
                self._thread = None

    def enter_stage(self, stage: str, *, backend_id: str | None = None) -> None:
        """Record a stage boundary immediately, without changing stage execution."""

        with self._lock:
            self._stage = str(stage)
            if backend_id:
                self._backend_id = str(backend_id)
            self._record_event("stage_started", include_presence=True)

    def leave_stage(self, stage: str) -> None:
        with self._lock:
            self._stage = str(stage)
            self._record_event("stage_finished")

    def update_execution_context(
        self,
        *,
        backend_id: str | None = None,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
    ) -> None:
        """Record the canonical backend/workflow resolved for the next dispatch."""

        with self._lock:
            if backend_id:
                self._backend_id = str(backend_id)
            if workflow_id:
                self._workflow_id = str(workflow_id)
            if workflow_version:
                self._workflow_version = str(workflow_version)
            self._record_event("backend_resolved")

    def record_event(
        self,
        event: str,
        *,
        outcome: str | None = None,
        include_presence: bool = False,
    ) -> None:
        """Record an observer-only execution boundary without changing runtime state."""

        with self._lock:
            self._record_event(
                str(event), outcome=outcome, include_presence=include_presence
            )

    def close(self, *, outcome: str) -> None:
        """Stop sampling and add one final best-effort job event."""

        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            try:
                thread.join(timeout=self._interval_s + 1.0)
            except Exception:
                pass
            if not thread.is_alive():
                try:
                    get_thread_registry().unregister(thread)
                except Exception:
                    pass
        with self._lock:
            self._record_event(f"{self._lifecycle}_finished", outcome=str(outcome))

    def _sample_loop(self) -> None:
        registry = get_thread_registry()
        while not self._stop.wait(self._interval_s):
            # ThreadRegistry.shutdown_all joins non-daemon threads one by one; leave promptly when it asks.
            if registry.is_shutdown_requested():
                break
            self._record_sample()

    def _record_sample(self) -> None:
        payload = self._base_record(kind="sample")
        self._attach_gpu(payload)
        self._append(payload)

    def _attach_gpu(self, payload: dict[str, Any]) -> None:
        """Add the GPU observation, and why it is missing when the default query returned nothing."""

        snapshot, query = self._observe_gpu()
        payload["gpu"] = snapshot
        if query is not None:
            payload["gpu_query"] = query

    def _record_event(
        self,
        event: str,
        *,
        outcome: str | None = None,
        include_presence: bool = False,
    ) -> None:
        payload = self._base_record(kind="job_event")
        payload["event"] = event
        if outcome:
            payload["outcome"] = outcome
        self._attach_gpu(payload)
        if include_presence:
            payload["process_presence"] = self._safe_presence()
        self._append(payload)

    def _base_record(self, *, kind: str) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": SCHEMA,
                "kind": kind,
                "timestamp_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "monotonic_ns": time.monotonic_ns(),
                "job_id": self._job_id,
                "run_id": self._run_id,
                "backend_id": self._backend_id,
                "stage": self._stage,
                "workflow": list(self._workflow),
                "workflow_id": self._workflow_id,
                "workflow_version": self._workflow_version,
            }

    def _observe_gpu(self) -> tuple[Mapping[str, Any] | None, dict[str, str] | None]:
        """Return ``(snapshot, query_status)``; the status is None for an injected provider."""

        try:
            if self._snapshot_provider is not None:
                snapshot = self._snapshot_provider()
                return (dict(snapshot) if snapshot is not None else None), None
            result = query_gpu_survivor_snapshot()
            query = {"status": result.status}
            if result.detail:
                query["detail"] = result.detail
            return (dict(result.snapshot) if result.snapshot is not None else None), query
        except Exception:
            return None, None

    def _safe_presence(self) -> Mapping[str, Any] | None:
        try:
            snapshot = self._presence_provider()
            return dict(snapshot) if snapshot is not None else None
        except Exception:
            return None

    def _append(self, payload: Mapping[str, Any]) -> None:
        """Append and fsync one small record; all I/O failure is contained."""

        try:
            encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            with self._lock:
                self._output_dir.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(encoded))
                fd = os.open(str(self._path), os.O_APPEND | os.O_CREAT | os.O_WRONLY)
                try:
                    remaining = memoryview(encoded)
                    while remaining:
                        written = os.write(fd, remaining)
                        if written <= 0:
                            raise OSError("Unable to append survivor telemetry")
                        remaining = remaining[written:]
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except Exception:
            return

    def _rotate_if_needed(self, incoming_size: int) -> None:
        try:
            if not self._path.exists() or self._path.stat().st_size + incoming_size <= self._max_bytes:
                return
            for index in range(self._backup_count, 0, -1):
                source = self._path if index == 1 else self._path.with_suffix(f".jsonl.{index - 1}")
                target = self._path.with_suffix(f".jsonl.{index}")
                if source.exists():
                    os.replace(source, target)
        except Exception:
            return


_session_lock = threading.Lock()
_session: GpuSurvivorTelemetry | None = None


def start_gpu_session_telemetry(
    *,
    base_dir: Path | str = DEFAULT_OUTPUT_DIR,
    environ: Mapping[str, str] | None = None,
    factory: Callable[..., GpuSurvivorTelemetry] = GpuSurvivorTelemetry,
) -> GpuSurvivorTelemetry | None:
    """Start the app-session recorder once; it samples GPU state for as long as the app runs.

    Per-job recorders only cover a running job. A device loss during startup, model load or idle leaves no job
    record, so this keeps a slower, separately rotated record under ``<base_dir>/session``. It is observation
    only (no queue, repository, process-lifecycle or execution authority) and any failure returns ``None``.
    Set ``STABLENEW_GPU_SESSION_TELEMETRY=0`` to turn it off.
    """

    global _session
    env = os.environ if environ is None else environ
    if str(env.get(SESSION_ENV_FLAG, "1")).strip().lower() in _SESSION_DISABLED_VALUES:
        return None
    with _session_lock:
        if _session is not None:
            return _session
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        try:
            recorder = factory(
                job_id=f"session-{os.getpid()}",
                run_id=f"session-{stamp}",
                workflow=[],
                backend_id=None,
                output_dir=Path(base_dir) / SESSION_OUTPUT_SUBDIR,
                interval_s=SESSION_SAMPLE_INTERVAL_S,
                max_bytes=SESSION_MAX_BYTES,
                backup_count=SESSION_BACKUP_COUNT,
                lifecycle="session",
            )
            recorder.start()
        except Exception:
            logger.exception("GPU session telemetry could not start")
            return None
        _session = recorder
        return recorder


def stop_gpu_session_telemetry(outcome: str = "app_exit") -> None:
    """Stop the app-session recorder if one is running. Idempotent and never raises."""

    global _session
    with _session_lock:
        recorder, _session = _session, None
    if recorder is None:
        return
    try:
        recorder.close(outcome=str(outcome))
    except Exception:
        logger.exception("GPU session telemetry could not close cleanly")
