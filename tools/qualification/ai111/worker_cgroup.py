"""Observe recursive population of one pinned qualification-owned cgroup v2."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

UNIT = re.compile(r"ai111-wcq-[0-9a-f]{32}\.service")
INVOCATION = re.compile(r"[0-9a-f]{32}")
ROOT = Path("/sys/fs/cgroup/system.slice")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


class Cgroup:
    """Keep the directory open across the lifecycle so a reused path cannot pass."""

    def __init__(self, path: Path, directory: int, boot_id: str, invocation: str):
        self.path = path
        self.directory = directory
        self.identity = os.fstat(directory)
        self.cgroup_sha256 = hashlib.sha256(
            f"{boot_id}:{invocation}:{path.name}:{self.identity.st_dev}:{self.identity.st_ino}".encode(
                "ascii"
            )
        ).hexdigest()

    def population(self) -> str:
        """An error or vanished cgroup is an incomplete observation."""
        events = os.open("cgroup.events", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.directory)
        with os.fdopen(events, "rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("oversize cgroup observation")
        population = [line for line in raw.splitlines() if line.startswith(b"populated ")]
        if population not in ([b"populated 0"], [b"populated 1"]):
            raise ValueError("missing or ambiguous recursive population")
        current = self.path.stat(follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
            self.identity.st_dev,
            self.identity.st_ino,
        ):
            raise ValueError("cgroup changed during observation")
        return "populated" if population == [b"populated 1"] else "empty"


@contextmanager
def pin(unit: str, invocation: str, *, root: Path = ROOT) -> Iterator[Cgroup]:
    """Use the invocation ID read by the qualification controller from systemd."""
    if UNIT.fullmatch(unit) is None or INVOCATION.fullmatch(invocation) is None:
        raise ValueError("expected a qualification-owned unit name and invocation")
    boot_id = BOOT_ID.read_text(encoding="ascii").strip().replace("-", "")
    if INVOCATION.fullmatch(boot_id) is None:
        raise ValueError("unavailable boot epoch")
    path = root / unit
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield Cgroup(path, directory, boot_id, invocation)
    finally:
        os.close(directory)
