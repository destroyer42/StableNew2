"""Best-effort, durable survivor telemetry for active GPU pipeline jobs.

The recorder is intentionally outside queue, repository, process-lifecycle,
and execution-control authority.  It cannot cancel, retry, start, stop, or
adopt a runtime.  Its purpose is to leave a flushed record immediately before
an operating-system or display-driver failure where normal diagnostics may not
complete.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.process_inspector_v2 import (
    collect_gpu_survivor_snapshot,
    collect_process_risk_snapshot,
)
from src.utils.thread_registry import get_thread_registry

SCHEMA = "stablenew.gpu-survivor.v1"
DEFAULT_OUTPUT_DIR = Path("reports") / "diagnostics" / "gpu_survivor"

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
        interval_s: float = 1.0,
        max_bytes: int = 2_000_000,
        backup_count: int = 3,
        snapshot_provider: SnapshotProvider | None = None,
        presence_provider: PresenceProvider | None = None,
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
        self._snapshot_provider = snapshot_provider or collect_gpu_survivor_snapshot
        self._presence_provider = presence_provider or collect_process_risk_snapshot
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
            self._record_event("job_started", include_presence=True)
            try:
                self._thread = get_thread_registry().spawn(
                    target=self._sample_loop,
                    name=f"GpuSurvivorTelemetry-{self._job_id[:8]}",
                    daemon=False,
                    purpose="Durable observation of an active GPU pipeline job",
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
            self._record_event("job_finished", outcome=str(outcome))

    def _sample_loop(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._record_sample()

    def _record_sample(self) -> None:
        payload = self._base_record(kind="sample")
        payload["gpu"] = self._safe_snapshot()
        self._append(payload)

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
        payload["gpu"] = self._safe_snapshot()
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

    def _safe_snapshot(self) -> Mapping[str, Any] | None:
        try:
            snapshot = self._snapshot_provider()
            return dict(snapshot) if snapshot is not None else None
        except Exception:
            return None

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
