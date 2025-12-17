"""Simple localhost socket lock to enforce single StableNew V2 instance."""

from __future__ import annotations

import socket


class SingleInstanceLock:
    """A lightweight TCP lock enforcing single-instance execution."""

    def __init__(self, host: str = "127.0.0.1", port: int = 47631) -> None:
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None

    def acquire(self) -> bool:
        """Bind the socket; return False if another instance already owns it."""

        if self._socket is not None:
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self._host, self._port))
            sock.listen(1)
        except OSError:
            sock.close()
            return False
        self._socket = sock
        return True

    def release(self) -> None:
        """Release the lock so another instance can start."""

        sock = self._socket
        if sock is None:
            return
        try:
            sock.close()
        except Exception:
            pass
        finally:
            self._socket = None

    def is_acquired(self) -> bool:
        """Return whether the lock is currently held."""

        return self._socket is not None
