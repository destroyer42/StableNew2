from __future__ import annotations

import threading
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
        try:
            bundle_build_async(
                reason=reason,
                log_handler=log_handler,
                job_service=job_service,
                extra_context=extra_context,
                include_process_state=include_process_state,
                include_queue_state=include_queue_state,
                webui_tail=webui_tail,
                output_dir=self.output_dir,
                on_done=kwargs.get("on_done"),
            )
        except TypeError:
            # Fall back to a thread that calls the sync build
            context_dict = dict(extra_context) if extra_context else None

            def _worker() -> None:
                try:
                    self.build(reason=reason, context=context_dict, webui_tail=webui_tail)
                except Exception:
                    pass

            threading.Thread(target=_worker, daemon=True, name="DiagnosticsServiceV2-build").start()

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
