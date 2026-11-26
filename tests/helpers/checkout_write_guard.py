"""Refuse, and fail, a test that writes into the checkout's own runtime folders.

In the owner's checkout ``output/`` is the live Output folder, and a relative path in a test (or a ``Mock`` used as a
path) resolves against the checkout. The guard is a Python audit hook, so it sees only the pytest process: an app
running from the same checkout cannot trip it, and neither can a child process a test starts.

A test whose subject resolves a relative path against the working directory uses the ``isolated_cwd`` fixture.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

GUARDED_FOLDERS = ("output", "outdir", "test_output", "MagicMock")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT


class CheckoutWriteGuard:
    def __init__(self, root: Path) -> None:
        self._root = os.path.normcase(os.path.abspath(root)) + os.sep
        self._guarded = {os.path.normcase(name) for name in GUARDED_FOLDERS}
        # ``StructuredLogger()`` creates a bare ``output`` folder in many tests. Anything inside it is refused.
        self._allowed_folder = os.path.normcase("output")
        self._violations: list[str] = []

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            path, mode, flags = args
            writes = any(c in mode for c in "wax+") if mode is not None else flags & _WRITE_FLAGS
            paths = (path,) if writes else ()
        elif event == "os.mkdir":
            paths = (args[0],)
        elif event == "os.rename":  # also ``os.replace``
            paths = args[:2]
        else:
            return
        for path in paths:
            inside = self._guarded_relative_path(path)
            if inside is None or (event == "os.mkdir" and inside == self._allowed_folder):
                continue
            self._violations.append(f"{event} {inside}")
            raise PermissionError(f"tests may not write into the checkout: {inside}")

    def take(self) -> list[str]:
        """The refusals since the last call; product code may swallow the exception, so each is kept."""

        violations, self._violations = self._violations, []
        return violations

    def _guarded_relative_path(self, path: object) -> str | None:
        if not isinstance(path, (str, bytes, os.PathLike)):  # a file descriptor
            return None
        full = os.path.normcase(os.path.abspath(os.fsdecode(path)))
        if not full.startswith(self._root):
            return None
        inside = full[len(self._root) :]
        return inside if inside.split(os.sep, 1)[0] in self._guarded else None


_session_guard: CheckoutWriteGuard | None = None


def install(root: Path) -> CheckoutWriteGuard:
    """Install the session's guard once (an audit hook cannot be removed)."""

    global _session_guard
    if _session_guard is None:
        _session_guard = CheckoutWriteGuard(root)
        sys.addaudithook(_session_guard.audit)
    return _session_guard


def session_guard() -> CheckoutWriteGuard | None:
    return _session_guard
