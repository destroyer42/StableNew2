"""Keep a test run's verdict independent of what the host machine happens to be running or have installed.

**Operator runtimes (always on).** A live Forge, A1111, ComfyUI or Ollama on this machine answered the read-only
endpoint probes of the runtime-transition code, so dozens of tests refused a dispatch that is accepted on a hosted
runner, and a test could have posted to the operator's runtime. A connection from the test process to one of those
loopback ports is refused here exactly as it is when nothing listens. A server the test process binds itself on such a
port stays reachable. Child processes are not covered (the operator-journey harness points its own children at
loopback stand-ins).

**Host tools (opt-in, ``STABLENEW_TESTS_CI_PARITY=1``).** The hosted runner has no FFmpeg, RIFE or ``nvidia-smi``. In
parity mode they cannot be found either, so a test that silently needs one fails here instead of after a push. Without
the switch the host's tools stay usable and the tests that need real FFmpeg keep running locally.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", "::", ""})
_SETTINGS = Path(__file__).resolve().parents[2] / "presets" / "settings.json"
_ENDPOINT_VARIABLES = ("STABLENEW_WEBUI_BASE_URL", "STABLENEW_COMFY_BASE_URL")


def configured_ports(settings: Path = _SETTINGS) -> frozenset[int]:
    """Loopback ports named by the repository's settings and the endpoint variables (an unreadable file names none)."""

    try:
        values = list(json.loads(settings.read_text(encoding="utf-8-sig")).values())
    except (OSError, ValueError, AttributeError):
        values = []
    values += [os.environ.get(name, "") for name in _ENDPOINT_VARIABLES]
    ports = set()
    for value in values:
        if not isinstance(value, str) or "://" not in value:
            continue
        try:
            url = urlsplit(value.strip())
            if url.hostname in _LOOPBACK_HOSTS and url.port:
                ports.add(url.port)
        except ValueError:
            continue
    return frozenset(ports)


#: A1111 (7860), managed Forge Neo (7871), ComfyUI (8188), a local Ollama (11434) and whatever the settings name
#: (the owner's ComfyUI listens on 8000).
OPERATOR_RUNTIME_PORTS = frozenset({7860, 7871, 8000, 8188, 11434}) | configured_ports()

CI_PARITY_ENV = "STABLENEW_TESTS_CI_PARITY"
#: Set to 1 for a deliberate run against the operator's own runtimes (never in the gate or CI).
ALLOW_RUNTIMES_ENV = "STABLENEW_TESTS_ALLOW_LIVE_RUNTIMES"
HOSTED_RUNNER_MISSING_TOOLS = frozenset({"ffmpeg", "ffprobe", "rife-ncnn-vulkan", "nvidia-smi"})

_bound_ports: set[int] = set()
_installed_network_guard = False


def ci_parity() -> bool:
    return os.environ.get(CI_PARITY_ENV) == "1"


def refuses(address: Any) -> bool:
    """Whether a connection to ``address`` is a test reaching for one of the operator's runtimes."""

    if not isinstance(address, tuple) or len(address) < 2:
        return False  # a named pipe or other non-IP address
    host, port = address[0], address[1]
    return (
        port in OPERATOR_RUNTIME_PORTS
        and port not in _bound_ports
        and str(host).lower() in _LOOPBACK_HOSTS
    )


def install_network_guard() -> None:
    """Patch ``socket.socket`` once for the whole session (background threads included)."""

    global _installed_network_guard
    if _installed_network_guard or os.environ.get(ALLOW_RUNTIMES_ENV) == "1":
        return
    _installed_network_guard = True
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_bind = socket.socket.bind

    def connect(self: socket.socket, address: Any) -> None:
        if refuses(address):
            raise ConnectionRefusedError(errno.ECONNREFUSED, f"tests may not reach {address}")
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        if refuses(address):
            return errno.ECONNREFUSED
        return real_connect_ex(self, address)

    def bind(self: socket.socket, address: Any) -> None:
        real_bind(self, address)
        if isinstance(address, tuple) and len(address) >= 2 and address[1]:
            _bound_ports.add(address[1])

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.socket.bind = bind  # type: ignore[method-assign]


def _is_hidden_tool(command: object) -> bool:
    name = Path(str(command)).name.lower()
    return (name[:-4] if name.endswith(".exe") else name) in HOSTED_RUNNER_MISSING_TOOLS


def hide_host_tools(setattr_: Callable[..., None], delenv: Callable[..., None]) -> None:
    """Make FFmpeg, FFprobe, RIFE and ``nvidia-smi`` unfindable, through every lookup the application uses.

    ``setattr_``/``delenv`` are a ``MonkeyPatch``'s; a test that supplies its own stand-in tool still wins.
    """

    real_which = shutil.which

    def which(command: str, *args: Any, **kwargs: Any) -> str | None:
        return None if _is_hidden_tool(command) else real_which(command, *args, **kwargs)

    setattr_(shutil, "which", which)
    for variable in ("STABLENEW_FFMPEG_PATH", "STABLENEW_RIFE_EXE"):
        delenv(variable, raising=False)

    from src.pipeline import video
    from src.video import rife_runtime

    # Hide the installs that exist on this machine (their well-known folders included); a test's own fake ones, under
    # its temporary folder, are still found.
    real_candidates = video._candidate_ffmpeg_paths
    installed = {path for path in real_candidates() if path.is_file()}

    def ffmpeg_candidates() -> list[Path]:
        return [path for path in real_candidates() if path not in installed]

    real_tools_dir = rife_runtime.default_rife_tools_dir

    def rife_tools_dir(repo_root: Path | None = None) -> Path:
        # The checkout's own ``tools/rife`` is this machine's install; a root a test names is the test's.
        return real_tools_dir(repo_root) if repo_root is not None else Path(os.devnull) / "rife"

    setattr_(video, "_candidate_ffmpeg_paths", ffmpeg_candidates)
    setattr_(rife_runtime, "default_rife_tools_dir", rife_tools_dir)
