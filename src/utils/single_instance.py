"""Simple localhost socket lock to enforce single StableNew V2 instance.

This module provides a TCP-based single-instance lock mechanism that:
1. Prevents multiple StableNew GUI instances from running simultaneously
2. Allows orphaned processes to detect if the GUI is still running

The lock is acquired when StableNew GUI starts and released on proper shutdown.
Orphaned background processes can use is_gui_running() to check if they should
continue operating or terminate gracefully.
"""

from __future__ import annotations

import socket


class SingleInstanceLock:
    """A lightweight TCP lock enforcing single-instance execution."""

    def __init__(self, host: str = "127.0.0.1", port: int = 47631) -> None:
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None

    @staticmethod
    def is_gui_running(host: str = "127.0.0.1", port: int = 47631) -> bool:
        """Check if StableNew GUI is currently running by attempting to connect.
        
        Returns:
            True if GUI is running (port is bound), False otherwise
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # If we can connect, the GUI is running and holding the lock
            sock.connect((host, port))
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            # Port is not bound = GUI is not running
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

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
