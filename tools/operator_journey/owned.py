"""Ownership-checked cleanup: a journey only stops what it started itself."""

from __future__ import annotations

import subprocess
from collections.abc import Callable


class OwnedResources:
    """Registry of test-owned resources; ``cleanup`` never touches anything else."""

    def __init__(self) -> None:
        self._items: list[tuple[str, Callable[[], None]]] = []
        self.owned_pids: set[int] = set()

    def register(self, name: str, stop: Callable[[], None]) -> None:
        self._items.append((name, stop))

    def register_process(self, process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
        self.owned_pids.add(process.pid)
        self.register(
            f"process:{process.pid}", lambda: terminate_owned_process(process, self.owned_pids)
        )

    def cleanup(self) -> list[str]:
        stopped: list[str] = []
        for name, stop in reversed(self._items):
            try:
                stop()
                stopped.append(name)
            except Exception:  # cleanup is best-effort and must not mask the verdict
                continue
        self._items.clear()
        return stopped


def terminate_owned_process(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    owned_pids: set[int],
    *,
    timeout: float = 5.0,
) -> bool:
    """Terminate ``process`` only if this journey started it (its pid is registered)."""

    if process.pid not in owned_pids:
        return False
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    return True
