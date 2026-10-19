"""A job object must never be shared: one container's kill_all may only reach the processes assigned to that container.

Regression for the audit finding that every WebUIProcessManager opened the *same* named Windows job object, so a test
run, tool or second instance could terminate another instance's managed Forge.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from src.utils.process_container_v2 import (
    NullProcessContainer,
    ProcessContainerConfig,
    build_process_container,
)

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_exit(proc: subprocess.Popen, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return False


@windows_only
def test_two_containers_with_the_same_label_do_not_share_a_job_object() -> None:
    owner = build_process_container("shared-label", ProcessContainerConfig(enabled=True))
    other = build_process_container("shared-label", ProcessContainerConfig(enabled=True))
    child = _sleeper()
    try:
        owner.add_pid(child.pid)
        other.kill_all()  # a different container, even with an identical label, must not reach the owner's child
        other.teardown()
        assert not _wait_exit(child, 1.5), "another container terminated a process it never owned"
        owner.kill_all()
        assert _wait_exit(child), "the owning container must still terminate its own process"
    finally:
        if child.poll() is None:
            child.kill()
        owner.teardown()


@windows_only
def test_the_job_object_is_anonymous() -> None:
    from src.utils.win_jobobject import WindowsJobObject

    first = WindowsJobObject("same-name")
    second = WindowsJobObject("same-name")
    try:
        assert first._handle != second._handle
        assert first.inspect()["name"] == "same-name"  # a diagnostic label only
    finally:
        first.close()
        second.close()


def test_each_webui_launch_gets_a_unique_container_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container is built per launch (never at construction, never reused), each with its own label."""

    import src.api.webui_process_manager as wpm

    labels: list[str] = []

    def fake_build(job_id: str, config: ProcessContainerConfig):
        labels.append(job_id)
        return NullProcessContainer(job_id, config)

    monkeypatch.setattr(wpm, "build_process_container", fake_build)
    config = wpm.WebUIProcessConfig(command=["python", "--version"], working_dir=".")
    first = wpm.WebUIProcessManager(config)
    second = wpm.WebUIProcessManager(config)
    assert labels == []
    first._build_launch_container(required=False)
    second._build_launch_container(required=False)
    first._build_launch_container(required=False)
    assert len(labels) == 3 and len(set(labels)) == 3
    assert all(label.startswith("webui_process_manager-") for label in labels)
    del first, second
