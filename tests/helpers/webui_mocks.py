from __future__ import annotations

import io
import os
from collections.abc import Iterable
from typing import Any

from src.utils.process_container_v2 import ProcessContainer, ProcessContainerConfig


class DummyProcess:
    """Simple subprocess-like stub used by WebUI process-manager tests."""

    def __init__(self, pid: int = 12345):
        self.pid = pid
        self._returncode: int | None = None
        self.stdout = io.BytesIO(b"")
        self.stderr = io.BytesIO(b"")

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self._returncode = 0

    def wait(self, timeout: float | None = None) -> int | None:
        return self._returncode


class DummyWebUIClient:
    """Minimal WebUI client stub to satisfy resource & API tests."""

    def __init__(
        self,
        *,
        models: Iterable[dict[str, Any]] | None = None,
        vaes: Iterable[dict[str, Any]] | None = None,
        hypernetworks: Iterable[dict[str, Any]] | None = None,
        upscalers: Iterable[dict[str, Any]] | None = None,
    ):
        self._models: list[dict[str, Any]] = list(models or [])
        self._vaes: list[dict[str, Any]] = list(vaes or [])
        self._hypernetworks: list[dict[str, Any]] = list(hypernetworks or [])
        self._upscalers: list[dict[str, Any]] = list(upscalers or [])

    def get_models(self) -> list[dict[str, Any]]:
        return list(self._models)

    def get_vae_models(self) -> list[dict[str, Any]]:
        return list(self._vaes)

    def get_hypernetworks(self) -> list[dict[str, Any]]:
        return list(self._hypernetworks)

    def get_upscalers(self) -> list[dict[str, Any]]:
        return list(self._upscalers)

    def generate_images(
        self, *, stage: str = "txt2img", payload: dict[str, Any] | None = None, **_kwargs: Any
    ) -> dict[str, Any]:
        payload = payload or {}
        return {
            "stage": stage,
            "payload": payload,
            "images": [f"{stage}_image.png"],
            "info": {"stage": stage},
        }


class FakeWebUIProcess:
    """A ``subprocess.Popen`` stand-in that stays alive until it is killed or terminated, and records what was done."""

    def __init__(self, pid: int = 40001, *, stdout: Any = None, stderr: Any = None) -> None:
        self.pid = pid
        self.stdout = io.BytesIO(b"") if stdout is None else stdout
        self.stderr = io.BytesIO(b"") if stderr is None else stderr
        self.returncode: int | None = None
        self.killed = False
        self.kill_count = 0
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.kill_count += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode

    def exit_naturally(self, code: int = 0) -> None:
        self.returncode = code


def _is_own_child(pid: int) -> bool:
    if os.name != "nt":
        return False
    try:
        import psutil

        return psutil.Process(pid).ppid() == os.getpid()
    except Exception:
        return False


class RecordingContainer(ProcessContainer):
    """A process container whose outcome the test chooses, and which never reaches the OS.

    The defaults describe *successful* containment (the OS accepts the pid and the resume); a test that needs
    refusal passes it explicitly. ``events`` records every call in order. A real child of the test process (created
    suspended on Windows) is really resumed so it can run; fake pids are only answered."""

    supports_suspended_start = True

    def __init__(
        self,
        job_id: str = "recording",
        config: ProcessContainerConfig | None = None,
        *,
        add_pid_result: bool = True,
        add_pid_error: BaseException | None = None,
        resume_result: bool = True,
        resume_error: BaseException | None = None,
    ) -> None:
        super().__init__(job_id, config or ProcessContainerConfig(enabled=True))
        self._add_pid_result = add_pid_result
        self._add_pid_error = add_pid_error
        self._resume_result = resume_result
        self._resume_error = resume_error
        self.events: list[str] = []
        self.pids: list[int] = []

    def add_pid(self, pid: int) -> bool:
        self.events.append("add_pid")
        if self._add_pid_error is not None:
            raise self._add_pid_error
        if self._add_pid_result:
            self.pids.append(pid)
        return self._add_pid_result

    def resume_suspended(self, pid: int) -> bool:
        self.events.append("resume")
        if self._resume_error is not None:
            raise self._resume_error
        if self._resume_result and _is_own_child(pid):
            # A real Popen child of this test process was created suspended: let it run, though nothing is contained.
            # Only a direct child is ever resumed, so a fake pid can never touch an unrelated process.
            from src.utils.win_jobobject import resume_suspended_process

            return resume_suspended_process(pid)
        return self._resume_result

    def kill_all(self) -> None:
        self.events.append("kill_all")

    def teardown(self) -> None:
        self.events.append("teardown")
