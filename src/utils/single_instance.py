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
import threading


class SingleInstanceLock:
    """A lightweight TCP lock enforcing single-instance execution."""

    def __init__(self, host: str = "127.0.0.1", port: int = 47631) -> None:
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop_accepting = threading.Event()

    @staticmethod
    def is_gui_running(host: str = "127.0.0.1", port: int = 47631) -> bool:
        """Check if StableNew GUI is currently running by attempting to connect.
        
        Returns:
            True if GUI is running (port is bound), False otherwise
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)  # 1 second timeout to prevent hanging
        try:
            # If we can connect, the GUI is running and holding the lock
            sock.connect((host, port))
            sock.close()
            return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            # Port is not bound or connection refused/timed out = GUI is not running
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _accept_loop(self) -> None:
        """Background thread that accepts and immediately closes connections.
        
        This allows is_gui_running() checks to succeed by accepting connections
        from the backlog.
        """
        if self._socket is None:
            return
        
        self._socket.settimeout(1.0)  # Non-blocking accept with timeout
        
        while not self._stop_accepting.is_set():
            try:
                client_sock, _addr = self._socket.accept()
                # Immediately close the connection - we just need to drain the backlog
                try:
                    client_sock.close()
                except Exception:
                    pass
            except socket.timeout:
                # Timeout is normal - just check stop flag and continue
                continue
            except Exception:
                # Socket closed or other error - exit loop
                break

    def acquire(self) -> bool:
        """Bind the socket; return False if another instance already owns it."""

        if self._socket is not None:
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self._host, self._port))
            sock.listen(5)  # Larger backlog to handle multiple check attempts
        except OSError:
            sock.close()
            return False
        self._socket = sock
        
        # Start accept loop thread to handle is_gui_running() checks
        # PR-THREAD-001: Use ThreadRegistry for accept loop
        self._stop_accepting.clear()
        from src.utils.thread_registry import get_thread_registry
        registry = get_thread_registry()
        self._accept_thread = registry.spawn(
            target=self._accept_loop,
            name="SingleInstanceLock-Accept",
            daemon=False,
            purpose="Accept socket connections for single instance lock"
        )
        
        return True

    def is_acquired(self) -> bool:
        """Check if this instance currently holds the lock.
        
        Returns:
            True if the lock is currently held by this instance, False otherwise
        """
        return self._socket is not None

    def release(self) -> None:
        """Release the lock so another instance can start."""

        # Stop accept thread first
        self._stop_accepting.set()
        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=2.0)
        
        # Close and clear the socket
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        
        self._accept_thread = None

