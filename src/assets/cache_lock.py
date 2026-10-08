"""Serialize AssetRegistry cache transactions across instances and processes."""

from __future__ import annotations

import importlib
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def registry_cache_lock(
    path: Path, *, cancelled: Callable[[], bool] | None = None
) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 1200
    with path.with_suffix(path.suffix + ".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        while True:
            if cancelled and cancelled():
                raise InterruptedError("Checkpoint evidence refresh cancelled")
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl = importlib.import_module("fcntl")

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "AssetRegistry cache writer is busy; retry Preview"
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
