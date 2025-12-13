from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Mapping, Optional

from src.utils.diagnostics_bundle_v2 import build_crash_bundle


class DiagnosticsServiceV2:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        *,
        reason: str,
        log_handler: Any = None,
        job_service: Any = None,
        extra_context: Optional[Mapping[str, Any]] = None,
    ) -> Optional[Path]:
        return build_crash_bundle(
            output_dir=self.output_dir,
            reason=reason,
            log_handler=log_handler,
            job_service=job_service,
            extra_context=extra_context or {},
        )

    def build_async(
        self,
        *,
        reason: str,
        log_handler: Any = None,
        job_service: Any = None,
        extra_context: Optional[Mapping[str, Any]] = None,
        include_process_state: bool = False,
        include_queue_state: bool = False,
        **kwargs: Any,
    ) -> None:
        def worker() -> None:
            self.build(
                reason=reason,
                log_handler=log_handler,
                job_service=job_service,
                extra_context=extra_context,
            )

        threading.Thread(target=worker, daemon=True, name="DiagnosticsServiceV2-build").start()
