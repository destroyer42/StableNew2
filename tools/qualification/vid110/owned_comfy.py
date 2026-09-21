"""A qualification-owned, stock-nodes-only ComfyUI process (own port, own scratch dirs).

Used only when the operator's external ComfyUI cannot run the lane (it stays
untouched either way).  This module starts and stops *only* the process it spawned,
sharing the operator's model files read-only through ``--base-directory`` while
keeping input/output/temp/user state in a scratch directory.
"""

from __future__ import annotations

import subprocess
import time
import urllib.request
from pathlib import Path
from types import TracebackType

COMFY_MAIN = Path("E:/Users/rober/AppData/Local/Programs/ComfyUI/resources/ComfyUI/main.py")
COMFY_PYTHON = Path("E:/Users/rober/ComfyUI/.venv-explicit/Scripts/python.exe")
COMFY_BASE = Path("E:/Users/rober/ComfyUI")
OWNED_PORT = 8199


def build_command(scratch: Path, *, port: int = OWNED_PORT) -> list[str]:
    return [
        str(COMFY_PYTHON),
        str(COMFY_MAIN),
        "--listen",
        "127.0.0.1",
        "--port",
        str(port),
        "--base-directory",
        str(COMFY_BASE),
        "--input-directory",
        str(scratch / "input"),
        "--output-directory",
        str(scratch / "output"),
        "--temp-directory",
        str(scratch / "temp"),
        "--user-directory",
        str(scratch / "user"),
        "--disable-all-custom-nodes",
        "--disable-auto-launch",
    ]


class OwnedComfy:
    """Context manager owning exactly one spawned ComfyUI process."""

    def __init__(self, scratch: Path, *, port: int = OWNED_PORT) -> None:
        self.scratch = scratch.resolve()
        self.port = port
        self.process: subprocess.Popen[bytes] | None = None
        self.base_url = f"http://127.0.0.1:{port}"

    def __enter__(self) -> OwnedComfy:
        for name in ("input", "output", "temp", "user"):
            (self.scratch / name).mkdir(parents=True, exist_ok=True)
        log = (self.scratch / "comfy_owned.log").open("ab")
        self.process = subprocess.Popen(  # noqa: S603 - fixed, operator-installed interpreter
            build_command(self.scratch, port=self.port),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(COMFY_MAIN.parent),
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"owned ComfyUI exited early ({self.process.returncode})")
            try:
                urllib.request.urlopen(f"{self.base_url}/system_stats", timeout=3).read()  # noqa: S310
                return self
            except OSError:
                time.sleep(2)
        self.stop()
        raise RuntimeError("owned ComfyUI did not become ready in 180s")

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=20)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
