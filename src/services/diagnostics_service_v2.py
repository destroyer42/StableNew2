from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.utils.diagnostics_bundle_v2 import build_async as bundle_build_async
from src.utils.diagnostics_bundle_v2 import build_crash_bundle
from src.utils.logger import get_structured_logger_registry_count


class DiagnosticsServiceV2:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active_threads: set[threading.Thread] = set()

    def build(
        self,
        *,
        reason: str,
        context: dict | None = None,
        webui_tail: Mapping[str, Any] | None = None,
    ) -> Path:
        return build_crash_bundle(
            output_dir=self.output_dir,
            reason=reason,
            context=context or {},
            webui_tail=webui_tail,
        )

    def build_async(
        self,
        *,
        reason: str,
        log_handler: Any = None,
        job_service: Any = None,
        extra_context: Mapping[str, Any] | None = None,
        include_process_state: bool = False,
        include_queue_state: bool = False,
        webui_tail: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        # Delegate to central bundle async with repo-specific output_dir.
        external_on_done = kwargs.get("on_done")

        def _on_done() -> None:
            with self._lock:
                self._active_threads = {thread for thread in self._active_threads if thread.is_alive()}
            if callable(external_on_done):
                try:
                    external_on_done()
                except Exception:
                    pass

        try:
            worker = bundle_build_async(
                reason=reason,
                log_handler=log_handler,
                job_service=job_service,
                extra_context=extra_context,
                include_process_state=include_process_state,
                include_queue_state=include_queue_state,
                webui_tail=webui_tail,
                output_dir=self.output_dir,
                on_done=_on_done,
            )
            if worker is not None:
                with self._lock:
                    self._active_threads.add(worker)
        except TypeError:
            # Fall back to a thread that calls the sync build
            context_dict = dict(extra_context) if extra_context else None

            def _worker() -> None:
                try:
                    self.build(reason=reason, context=context_dict, webui_tail=webui_tail)
                except Exception:
                    pass

            # PR-THREAD-001: Use ThreadRegistry for diagnostics worker
            from src.utils.thread_registry import get_thread_registry
            registry = get_thread_registry()
            worker = registry.spawn(
                target=_worker,
                name="DiagnosticsServiceV2-build",
                daemon=False,
                purpose="Build diagnostics bundle asynchronously"
            )
            with self._lock:
                self._active_threads.add(worker)

    def wait_for_idle(self, timeout_s: float = 5.0) -> None:
        current = threading.current_thread()
        finish_by = time.monotonic() + max(0.0, float(timeout_s))
        while True:
            with self._lock:
                threads = [
                    thread
                    for thread in self._active_threads
                    if thread.is_alive() and thread is not current
                ]
                self._active_threads = set(threads)
            if not threads:
                return
            remaining = finish_by - time.monotonic()
            if remaining <= 0:
                return
            for thread in threads:
                thread.join(timeout=min(remaining, 0.1))

    def lifecycle_snapshot(self) -> dict[str, Any]:
        """Capture snapshot of current lifecycle state for memory leak triage.

        Returns:
            Dictionary with:
            - thread_count: Total number of active threads
            - thread_names: List of thread names
            - structured_logger_registry_count: Number of tracked StructuredLogger instances
            - timestamp: ISO format timestamp of snapshot
        """
        import datetime

        threads = threading.enumerate()
        thread_names = [t.name for t in threads]

        return {
            "timestamp": datetime.datetime.now().isoformat(),
            "thread_count": len(threads),
            "thread_names": thread_names,
            "structured_logger_registry_count": get_structured_logger_registry_count(),
        }
