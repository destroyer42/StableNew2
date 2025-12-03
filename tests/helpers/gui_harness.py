from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from src.app_factory import build_v2_app
from tests.journeys.utils.tk_root_factory import create_root


@dataclass
class PipelineHarness:
    root: Any
    app_state: Any
    controller: Any
    window: Any
    pipeline_tab: Any


@contextmanager
def pipeline_harness(*, threaded: bool = False) -> Iterator[PipelineHarness]:
    """Create a fresh V2 GUI harness suitable for journey tests."""

    root = create_root()
    window = None
    try:
        root, app_state, controller, window = build_v2_app(root=root, threaded=threaded)
        pipeline_tab = getattr(window, "pipeline_tab", None)
        harness = PipelineHarness(root=root, app_state=app_state, controller=controller, window=window, pipeline_tab=pipeline_tab)
        yield harness
    finally:
        if window is not None and hasattr(window, "cleanup"):
            try:
                window.cleanup()
            except Exception:
                pass
        if root is not None and hasattr(root, "destroy"):
            try:
                root.destroy()
            except Exception:
                pass
