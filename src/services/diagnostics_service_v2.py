from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Mapping, Optional

from src.utils.diagnostics_bundle_v2 import build_crash_bundle, build_async as bundle_build_async


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
        extra_context: Optional[Mapping[str, Any]] = None,
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
