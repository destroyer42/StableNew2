"""Open a file in the system viewer or reveal it in the file manager (PR-VID-UX-314).

Both helpers hand the path to the operating system as an argument vector (never through a shell), refuse a
path that does not exist, and report a failure as a value so a GUI can show it inline.  The launchers are
injectable so tests never start a real process or viewer.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

Launcher = Callable[[Sequence[str]], None]


@dataclass(frozen=True)
class ShellResult:
    ok: bool
    message: str = ""


def _existing(path: str | Path) -> Path | None:
    """The absolute path of an existing file, or ``None``.

    Always absolute, so a name that begins with ``-`` can never be read as an option by the launched tool."""

    text = str(path or "").strip()
    if not text:
        return None
    target = Path(text).expanduser().absolute()
    return target if target.exists() else None


def _spawn(command: Sequence[str]) -> None:
    subprocess.Popen(list(command))  # noqa: S603 - fixed argument vector, no shell


def _startfile(path: str) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only; guarded by the caller


def _default_opener(path: str) -> None:
    if sys.platform.startswith("win"):
        _startfile(path)
    else:
        _spawn(["open" if sys.platform == "darwin" else "xdg-open", path])


def open_file(path: str | Path, *, opener: Callable[[str], None] | None = None) -> ShellResult:
    """Open ``path`` with the system default application."""

    target = _existing(path)
    if target is None:
        return ShellResult(False, f"The file no longer exists: {path or '(none)'}")
    try:
        (opener or _default_opener)(str(target))
    except OSError as exc:
        return ShellResult(False, f"Could not open the file: {exc}")
    return ShellResult(True)


def reveal_in_file_manager(
    path: str | Path, *, launcher: Launcher | None = None, platform: str | None = None
) -> ShellResult:
    """Show ``path`` selected in the file manager (its folder where selection is unsupported)."""

    target = _existing(path)
    if target is None:
        return ShellResult(False, f"The file no longer exists: {path or '(none)'}")
    system = platform or sys.platform
    if system.startswith("win"):
        command: list[str] = ["explorer", f"/select,{target}"]
    elif system == "darwin":
        command = ["open", "-R", str(target)]
    else:
        command = ["xdg-open", str(target if target.is_dir() else target.parent)]
    try:
        (launcher or _spawn)(command)
    except OSError as exc:
        return ShellResult(False, f"Could not open the file manager: {exc}")
    return ShellResult(True)


__all__ = ["Launcher", "ShellResult", "open_file", "reveal_in_file_manager"]
