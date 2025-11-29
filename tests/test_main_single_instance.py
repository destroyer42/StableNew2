import socket

import pytest

import src.main as main_module


@pytest.fixture
def unique_lock_port(monkeypatch):
    """Use a high, likely-unused port to avoid colliding with a real instance."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    monkeypatch.setattr(main_module, "_INSTANCE_PORT", port)
    return port


def test_single_instance_lock_allows_first_and_blocks_second(unique_lock_port):
    first = main_module._acquire_single_instance_lock()
    try:
        assert first is not None
        # With the port still held, a second call should fail
        second = main_module._acquire_single_instance_lock()
        assert second is None
    finally:
        if first is not None:
            first.close()
