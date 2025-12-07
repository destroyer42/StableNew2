"""Lightweight tests for process container helpers."""

from __future__ import annotations

from src.utils.process_container_v2 import NullProcessContainer, ProcessContainerConfig, build_process_container


def test_build_process_container_disabled() -> None:
    config = ProcessContainerConfig(enabled=False)
    container = build_process_container("job-id", config)
    assert isinstance(container, NullProcessContainer)
