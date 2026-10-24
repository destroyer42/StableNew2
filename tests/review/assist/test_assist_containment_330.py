"""Timeout and cancel through the real contained runner leave no child tree and no job directory (IMG-QUAL-330).

The 320 adapter tests drive ``ChildSegmentAdapter`` with a fake process runner, and ``tests/utils/test_managed_process.py``
proves tree termination below the seam. These tests join the two: the production adapter, ``run_worker`` and the real
``run_bounded`` run a stand-in worker that starts a grandchild and idles, with no model, GPU or network involved.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from src.conditioning.reference_map import auxiliary
from src.conditioning.reference_map.contracts import ReferenceMapError
from src.conditioning.reference_map.providers import Context, run_worker
from src.review.assist import providers
from src.review.assist.contracts import CAPABILITY_SEGMENT, AssistError, PointPrompt, SourceIdentity
from src.review.assist.identity import LoadedSource

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

_STAND_IN = """\
import subprocess, sys, time
from pathlib import Path

job = Path(sys.argv[1])
subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)",
        str(job.parent / "grandchild.pid"),
    ]
)
time.sleep(60)
"""


def _alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _wait(predicate, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def stand_in(tmp_path: Path) -> Path:
    path = tmp_path / "stand_in_worker.py"
    path.write_text(_STAND_IN, encoding="utf-8")
    return path


@windows_only
@pytest.mark.parametrize("how", ["timeout", "cancel"])
def test_adapter_timeout_and_cancel_kill_the_tree_and_remove_the_job_directory(
    monkeypatch, tmp_path, stand_in, how
):
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    verified = auxiliary.VerifiedResource("sam-2-1-small", ())
    monkeypatch.setattr(providers, "runtime_reasons", lambda capability: ())
    monkeypatch.setattr(providers, "WORKER_PATH", stand_in)
    monkeypatch.setattr(
        auxiliary, "verify_resource", lambda registry, modality, cancelled=None: verified
    )

    def stage(resource, root, destination, cancelled=None):
        destination.mkdir(parents=True)
        (destination / "model.safetensors").write_bytes(b"w" * 4096)
        return {"weights": destination / "model.safetensors"}

    monkeypatch.setattr(auxiliary, "stage_resource", stage)
    registry = type("Registry", (), {"webui_root": tmp_path})()
    identity = SourceIdentity("0" * 64, 1, 8, 8, 1, "PNG")
    source = LoadedSource(identity, np.zeros((8, 8, 3), np.uint8))
    stop = threading.Event()
    adapter = providers.ChildSegmentAdapter(
        lambda: registry,
        timeouts={CAPABILITY_SEGMENT: 8.0 if how == "timeout" else 120.0},
        temp_root=str(temp_root),
    )
    pid_file = temp_root / "grandchild.pid"
    if how == "cancel":
        threading.Thread(
            target=lambda: (_wait(pid_file.exists), stop.set()), name="cancel-after-grandchild"
        ).start()

    started = time.monotonic()
    with pytest.raises(AssistError) as raised:
        adapter.segment(source, [PointPrompt(1, 1, True)], [], stop.is_set)

    assert raised.value.code == ("timeout" if how == "timeout" else "cancelled")
    assert time.monotonic() - started < 60, "the call must return promptly, not wait out the child"
    assert pid_file.exists(), "the grandchild never started; the test proves nothing"
    assert _wait(lambda: not _alive(int(pid_file.read_text()))), "a grandchild outlived its parent"
    assert list(temp_root.glob("stablenew-assist-*")) == [], (
        "the private job directory was left behind"
    )


@windows_only
def test_reference_map_run_worker_timeout_kills_the_tree(tmp_path, stand_in):
    job = tmp_path / "stablenew-refmap-job"
    job.mkdir()
    context = Context(registry=None, cancel=lambda: False, timeouts={"depth": 8.0})
    with pytest.raises(ReferenceMapError) as raised:
        run_worker(
            job, "depth", "depth", {}, np.zeros((4, 4, 3), np.uint8), context, worker_path=stand_in
        )
    assert raised.value.code == "timeout"
    pid_file = job.parent / "grandchild.pid"
    assert pid_file.exists(), "the grandchild never started; the test proves nothing"
    assert _wait(lambda: not _alive(int(pid_file.read_text()))), "a grandchild outlived its parent"
