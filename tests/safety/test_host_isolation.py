"""The host-isolation guard: a live runtime or installed tool on this machine cannot change a test's verdict."""

from __future__ import annotations

import errno
import os
import shutil
import socket
from pathlib import Path

import pytest

from src.api.healthcheck import probe_webui_endpoint
from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    get_global_webui_process_manager,
)
from src.pipeline.video import resolve_ffmpeg_executable
from src.video.comfy_healthcheck import probe_comfy_endpoint
from src.video.rife_runtime import find_rife_executable
from tests.helpers import host_isolation


@pytest.fixture
def live_runtime(monkeypatch: pytest.MonkeyPatch):
    """Something listening on a guarded port that this process did not bind, as far as the guard knows."""

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    monkeypatch.setattr(host_isolation, "OPERATOR_RUNTIME_PORTS", frozenset({port}))
    monkeypatch.setattr(host_isolation, "_bound_ports", set())
    try:
        yield port
    finally:
        server.close()


def test_the_guard_covers_the_default_and_the_configured_ports(tmp_path: Path) -> None:
    assert {7860, 7871, 8000, 8188} <= host_isolation.OPERATOR_RUNTIME_PORTS

    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"comfy_base_url": "http://127.0.0.1:8123", "webui_base_url": "http://192.0.2.1:9000", "n": 3}',
        encoding="utf-8",
    )
    assert 8123 in host_isolation.configured_ports(settings)
    assert 9000 not in host_isolation.configured_ports(settings)  # not this machine
    assert host_isolation.configured_ports(tmp_path / "absent.json") == frozenset()


def test_a_live_runtime_reads_as_absent_to_the_applications_probes(live_runtime: int) -> None:
    url = f"http://127.0.0.1:{live_runtime}"

    assert probe_webui_endpoint(url, timeout=0.5) == "free"
    assert probe_comfy_endpoint(url, timeout=0.5) == "free"
    with socket.socket() as client:
        assert client.connect_ex(("127.0.0.1", live_runtime)) == errno.ECONNREFUSED
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("localhost", live_runtime), timeout=0.5)


def test_a_server_the_test_process_bound_itself_stays_reachable(
    live_runtime: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_isolation, "_bound_ports", {live_runtime})

    socket.create_connection(("127.0.0.1", live_runtime), timeout=2.0).close()


def test_other_ports_and_hosts_are_left_alone() -> None:
    assert not host_isolation.refuses(("127.0.0.1", 50123))
    assert not host_isolation.refuses(("192.0.2.1", 7871))
    assert not host_isolation.refuses(r"\\.\pipe\name")


def test_a_webui_manager_a_test_leaves_registered() -> None:
    """First half of a pair that relies on in-file order (shards keep whole files together)."""

    manager = WebUIProcessManager(WebUIProcessConfig(command=["python", "-V"]))

    assert get_global_webui_process_manager() is manager


def test_does_not_reach_the_next_test() -> None:
    # PR #474: a leftover ``standard``-only manager changed the admission tests' verdict once shards regrouped.
    assert get_global_webui_process_manager() is None


def test_parity_mode_hides_the_tools_the_hosted_runner_does_not_have(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "ffmpeg.exe"
    configured.write_bytes(b"stand-in")
    host_isolation.hide_host_tools(monkeypatch.setattr, monkeypatch.delenv)

    assert resolve_ffmpeg_executable() is None
    assert find_rife_executable() is None
    for tool in ("ffmpeg", "ffprobe", "rife-ncnn-vulkan", "nvidia-smi", "nvidia-smi.exe"):
        assert shutil.which(tool) is None, tool
    assert shutil.which("git") is not None
    shim = tmp_path / ("nvidia-smi.cmd" if os.name == "nt" else "nvidia-smi")
    shim.write_text("exit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    assert shutil.which("nvidia-smi", path=str(tmp_path)) is not None  # a named folder is searched

    # A test that names its own stand-in still gets it.
    monkeypatch.setenv("STABLENEW_FFMPEG_PATH", str(configured))
    assert resolve_ffmpeg_executable() == configured
