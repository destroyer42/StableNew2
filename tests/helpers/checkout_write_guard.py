"""Fail a test that writes into or deletes from the checkout's own runtime folders.

In the owner's checkout ``output/`` is the live Output folder, and a relative path in a test (or a ``Mock`` used as a
path) resolves against the checkout. The guard is a Python audit hook, so it sees only the pytest process: an app
running from the same checkout cannot trip it, and neither can a child process a test starts.

The hook only records; it never raises, so it cannot change what the code under test does. Refusing the write sent the
app into an error handler that opened a modal dialog, which blocks inside Tk where the census's per-test timeout
cannot reach it.

It sees what raises an audit event: opening for writing, creating, renaming, linking, truncating, deleting, a Windows
``CopyFile2`` copy and ``sqlite3.connect``. A name relative to a directory descriptor (``dir_fd``) is skipped, because
it cannot be resolved here; ``shutil.rmtree`` is seen by its own event instead.

A test whose subject resolves a relative path against the working directory uses the ``isolated_cwd`` fixture.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

GUARDED_FOLDERS = ("output", "outdir", "test_output", "MagicMock")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT
# event -> (position of a path it changes, position of the ``dir_fd`` that path is relative to)
_CHANGED_PATHS: dict[str, tuple[tuple[int, int | None], ...]] = {
    "os.mkdir": ((0, 2),),
    "os.remove": ((0, 1),),  # also ``os.unlink``
    "os.rmdir": ((0, 1),),
    "shutil.rmtree": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)),  # also ``os.replace``
    "os.link": ((1, 3),),
    "os.symlink": ((1, 2),),
    "os.truncate": ((0, None),),
    "_winapi.CopyFile2": ((1, None),),  # ``shutil.copy2`` on Windows
}


class CheckoutWriteGuard:
    def __init__(self, root: Path) -> None:
        self._root = _resolved(root) + os.sep
        self._guarded = {os.path.normcase(name) for name in GUARDED_FOLDERS}
        # ``StructuredLogger()`` creates a bare ``output`` folder in many tests. Anything inside it is recorded.
        self._allowed_folder = os.path.normcase("output")
        self._violations: list[str] = []

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            path, mode, flags = args
            writes = any(c in mode for c in "wax+") if mode is not None else flags & _WRITE_FLAGS
            paths = [path] if writes else []
        elif event == "sqlite3.connect":
            paths = [_writable_database(args[0])]
        elif event in _CHANGED_PATHS:
            paths = [
                args[index]
                for index, dir_fd in _CHANGED_PATHS[event]
                if dir_fd is None or args[dir_fd] in (None, -1)
            ]
        else:
            return
        for path in paths:
            inside = self._guarded_relative_path(path)
            if inside is None or (event == "os.mkdir" and inside == self._allowed_folder):
                continue
            self._violations.append(f"{event} {inside}")

    def take(self) -> list[str]:
        """The writes and deletes seen since the last call."""

        violations, self._violations = self._violations, []
        return violations

    def _guarded_relative_path(self, path: object) -> str | None:
        # A file descriptor, or ``None`` from a database that cannot write.
        if not isinstance(path, (str, bytes, os.PathLike)):
            return None
        try:
            # A path that cannot be resolved (a deleted working directory) is skipped: the hook must not raise.
            full = _resolved(path)
        except (OSError, ValueError):
            return None
        if not full.startswith(self._root):
            return None
        inside = full[len(self._root) :]
        return inside if inside.split(os.sep, 1)[0] in self._guarded else None


def _resolved(path: str | bytes | os.PathLike[Any]) -> str:
    """The comparable absolute form of a path, with any Windows long-path prefix removed."""

    text = os.path.normcase(os.fsdecode(path))
    # ``\\?\C:\x`` and ``\\?\UNC\server\share`` name the same files as ``C:\x`` and ``\\server\share``.
    if text.startswith("\\\\?\\unc\\"):
        text = "\\\\" + text[len("\\\\?\\unc\\") :]
    else:
        text = text.removeprefix("\\\\?\\")
    return os.path.normcase(os.path.abspath(text))


def _writable_database(database: object) -> str | None:
    """The file ``sqlite3.connect`` may write. The event does not say whether ``uri=True`` was passed."""

    if not isinstance(database, (str, bytes, os.PathLike)):
        return None
    text = os.fsdecode(database)
    if text.startswith("file:"):
        try:
            url = urlsplit(text)
        except ValueError:
            return None
        if parse_qs(url.query).get("mode", [""])[-1] in ("ro", "memory"):
            return None
        text = unquote(url.path)
        if url.netloc not in ("", "localhost"):
            text = f"//{url.netloc}{text}"
        elif os.name == "nt" and re.match(r"/[A-Za-z]:", text):
            text = text[1:]
    return None if text in ("", ":memory:") else text


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
