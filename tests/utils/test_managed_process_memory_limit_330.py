"""A verified memory ceiling for bounded children (IMG-QUAL-330).

``run_bounded(memory_limit_mb=...)`` asks the OS container for a committed-memory limit and refuses to start the child
unless the container reports exactly that limit. The model-backed reference-map and Smart Review children use it through
``providers.bounded_runner``. Without the argument nothing changes.
"""

from __future__ import annotations

import inspect
import math
import os
import sys
from typing import Any

import pytest

from src.conditioning.reference_map import providers
from src.review.assist import providers as assist_providers
from src.utils import managed_process
from src.utils.managed_process import ContainmentError, ProcessOutcome, run_bounded
from src.utils.process_container_v2 import (
    NullProcessContainer,
    ProcessContainer,
    ProcessContainerConfig,
)

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

_PY = sys.executable
_ALLOCATE_MB = "x = bytearray({mb} * 1024 * 1024); print(len(x))"


class _RecordingContainer(NullProcessContainer):
    """A container that claims whatever limit the test wants it to report."""

    def __init__(self, job_id: str, config: ProcessContainerConfig, reported: float | None) -> None:
        super().__init__(job_id, config, "test")
        self._reported = reported
        self.torn_down = False

    def inspect(self) -> dict[str, Any]:
        return {"memory_limit_mb": self._reported}

    def teardown(self) -> None:
        self.torn_down = True


def _fake_builder(reported: float | None, built: list[_RecordingContainer]):
    def build(job_id: str, config: ProcessContainerConfig) -> ProcessContainer:
        container = _RecordingContainer(job_id, config, reported)
        built.append(container)
        return container

    return build


def test_a_limit_the_container_cannot_confirm_means_no_child(monkeypatch) -> None:
    built: list[_RecordingContainer] = []
    launched: list[object] = []
    monkeypatch.setattr(managed_process, "build_process_container", _fake_builder(None, built))
    monkeypatch.setattr(
        managed_process, "launch_contained", lambda *a, **k: launched.append(a) or None
    )

    outcome = run_bounded(
        [_PY, "-c", "print(1)"], timeout_seconds=5, max_stdout_bytes=1024, memory_limit_mb=512
    )

    assert launched == [], "the child must not start without the confirmed limit"
    assert outcome.returncode is None and "512 MB memory limit" in (outcome.launch_error or "")
    assert built[0].config.memory_limit_mb == 512 and built[0].torn_down is True


def test_a_different_reported_limit_is_not_confirmation(monkeypatch) -> None:
    built: list[_RecordingContainer] = []
    monkeypatch.setattr(managed_process, "build_process_container", _fake_builder(1024, built))
    outcome = run_bounded(
        [_PY, "-c", "print(1)"], timeout_seconds=5, max_stdout_bytes=1024, memory_limit_mb=512
    )
    assert outcome.returncode is None and "could not be established" in (outcome.launch_error or "")
    assert built[0].torn_down is True


def test_spawn_raises_containment_error_when_the_limit_is_not_established(monkeypatch) -> None:
    monkeypatch.setattr(managed_process, "build_process_container", _fake_builder(None, []))
    with pytest.raises(ContainmentError):
        managed_process._spawn_contained(  # noqa: SLF001
            [_PY, "-c", "pass"],
            label="x",
            require_containment=False,
            cwd=None,
            env=None,
            memory_limit_mb=256,
        )


def test_without_a_limit_nothing_changes(monkeypatch) -> None:
    configs: list[ProcessContainerConfig] = []
    real = managed_process.build_process_container

    def spy(job_id: str, config: ProcessContainerConfig) -> ProcessContainer:
        configs.append(config)
        return real(job_id, config)

    monkeypatch.setattr(managed_process, "build_process_container", spy)
    outcome = run_bounded([_PY, "-c", "print(7)"], timeout_seconds=30, max_stdout_bytes=1024)
    assert outcome.returncode == 0 and outcome.stdout.strip() == b"7"
    assert [config.memory_limit_mb for config in configs] == [None]


@pytest.mark.parametrize("value", [0, -1, -0.5, math.nan, math.inf])
def test_a_nonsense_limit_is_refused_before_anything_is_built(monkeypatch, value) -> None:
    built: list[_RecordingContainer] = []
    monkeypatch.setattr(managed_process, "build_process_container", _fake_builder(None, built))
    with pytest.raises(ValueError):
        run_bounded(
            [_PY, "-c", "pass"], timeout_seconds=5, max_stdout_bytes=1024, memory_limit_mb=value
        )
    assert built == []


@windows_only
def test_a_child_inside_the_limit_runs_and_one_beyond_it_cannot() -> None:
    inside = run_bounded(
        [_PY, "-c", _ALLOCATE_MB.format(mb=16)],
        timeout_seconds=60,
        max_stdout_bytes=1024,
        memory_limit_mb=512,
    )
    assert not inside.launch_error and inside.returncode == 0 and inside.contained

    beyond = run_bounded(
        [_PY, "-c", _ALLOCATE_MB.format(mb=1536)],
        timeout_seconds=60,
        max_stdout_bytes=1024,
        memory_limit_mb=512,
    )
    assert not beyond.launch_error
    assert beyond.returncode != 0, "a child allocating 3x its limit must fail, not succeed"
    assert b"1610612736" not in beyond.stdout

    control = run_bounded(
        [_PY, "-c", _ALLOCATE_MB.format(mb=1536)], timeout_seconds=60, max_stdout_bytes=1024
    )
    assert control.returncode == 0, "the same allocation must succeed without a limit"


@windows_only
def test_a_real_job_object_confirms_the_limit_it_was_given() -> None:
    from src.utils.process_container_v2 import build_process_container

    container = build_process_container("memlimit-probe", ProcessContainerConfig(True, 256))
    try:
        assert container.inspect()["memory_limit_mb"] == 256
    finally:
        container.teardown()


def test_the_model_runner_passes_the_documented_ceiling(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake(command, **kwargs):
        captured.update(kwargs)
        return ProcessOutcome(0)

    monkeypatch.setattr(providers, "run_bounded", fake)
    providers.bounded_runner(
        ["python"], timeout_seconds=1.0, max_stdout_bytes=1, cancel=None, env={}
    )
    assert providers.WORKER_MEMORY_LIMIT_MB == 6144
    assert captured["memory_limit_mb"] == 6144


def test_every_model_child_uses_the_capped_runner_by_default() -> None:
    assert providers.Context.__dataclass_fields__["runner"].default is providers.bounded_runner
    default = (
        inspect.signature(assist_providers._ChildAdapter.__init__).parameters["runner"].default
    )  # noqa: SLF001
    assert default is providers.bounded_runner
    from src.conditioning.reference_map.service import ReferenceMapService

    service_default = inspect.signature(ReferenceMapService.__init__).parameters["runner"].default
    assert service_default is providers.bounded_runner
