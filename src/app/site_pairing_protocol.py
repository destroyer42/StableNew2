"""One-use Windows protocol handoff for the private Site's loopback connection."""

from __future__ import annotations

import os
import re
import stat
import sys
import time
from collections.abc import Callable
from pathlib import Path

from src.assets.cache_lock import registry_cache_lock

SCHEME = "stablenew-operator"
TICKET_SECONDS = 75
NONCE = re.compile(r"[a-f0-9]{32}")
_URI = re.compile(rf"{SCHEME}://connect/([a-f0-9]{{32}})/?")


class PairingTickets:
    def __init__(self, root: Path) -> None:
        self.directory = root / ".venv" / "operator-site"

    def _path(self, nonce: str) -> Path:
        if not NONCE.fullmatch(nonce):
            raise ValueError("Invalid pairing request")
        return self.directory / (nonce + ".ticket")

    def offer(self, nonce: str) -> None:
        self.directory.mkdir(exist_ok=True)
        # Future issuance prunes old requests without opening any of their contents.
        now = time.time()
        for ticket in self.directory.glob("*.ticket"):
            try:
                if now - ticket.lstat().st_mtime > TICKET_SECONDS:
                    ticket.unlink(missing_ok=True)
            except OSError:
                continue
        with self._path(nonce).open("xb"):
            pass

    def consume(self, nonce: str) -> bool:
        path = self._path(nonce)
        try:
            info = path.lstat()
            path.unlink()
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and 0 <= time.time() - info.st_mtime <= TICKET_SECONDS


def handle_protocol(
    uri: str, tickets: PairingTickets, is_running: Callable[[], bool], launch: Callable[[], None]
) -> None:
    """The URI carries only a challenge. It never supplies arguments to the normal launcher."""
    request = _URI.fullmatch(uri)
    if request is None:
        raise ValueError("Invalid StableNew operator link")
    tickets.offer(request[1])
    marker = tickets.directory / "launch"
    deadline = time.monotonic() + 2
    with registry_cache_lock(marker, cancelled=lambda: time.monotonic() >= deadline):
        if is_running() or (marker.exists() and time.time() - marker.stat().st_mtime < 30):
            return
        marker.touch()
        try:
            launch()
        except OSError:
            marker.unlink(missing_ok=True)
            raise


def register_protocol(root: Path) -> bool:
    """Register the dedicated URI for the current Windows user from the canonical venv."""
    if sys.platform != "win32":
        return False
    import winreg

    source = root / "scripts" / "operator_site_protocol.py"
    python = root / ".venv" / "Scripts" / "pythonw.exe"
    launched_with = root / ".venv" / "Scripts" / "python.exe"
    if (
        Path(sys.executable).resolve() != launched_with.resolve()
        or not python.is_file()
        or not source.is_file()
    ):
        return False
    command = f'"{python}" "{source}" "%1"'
    location = rf"Software\Classes\{SCHEME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, location) as schema:
        winreg.SetValueEx(schema, "", 0, winreg.REG_SZ, "URL:StableNew Operator Site")
        winreg.SetValueEx(schema, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(schema, r"shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    return True


def dispatch_protocol(root: Path, uri: str) -> None:
    if sys.platform != "win32":
        raise OSError("StableNew Operator links require Windows")
    from src.utils.single_instance import SingleInstanceLock

    launcher = root / "scripts" / "launch_stablenew.bat"
    if not launcher.is_file():
        raise OSError("StableNew launcher is missing")
    handle_protocol(
        uri,
        PairingTickets(root),
        SingleInstanceLock.is_gui_running,
        lambda: os.startfile(str(launcher), cwd=str(root)),
    )
