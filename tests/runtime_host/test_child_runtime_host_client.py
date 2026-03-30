from __future__ import annotations

from typing import Any

from src.runtime_host import (
    RUNTIME_HOST_EVENT_DISCONNECTED,
    RUNTIME_HOST_EVENT_QUEUE_STATUS,
    ChildRuntimeHostClient,
    RuntimeHostLaunchError,
)


class DummyProcess:
    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return False

    def terminate(self) -> None:
        return None


class DummyConnection:
    def send(self, value: Any) -> None:
        return None

    def poll(self, timeout: float) -> bool:
        return False

    def recv(self) -> Any:
        raise EOFError()

    def close(self) -> None:
        return None


def test_child_runtime_host_client_emits_disconnect_event_on_poll_failure() -> None:
    client = ChildRuntimeHostClient(
        process=DummyProcess(),
        connection=DummyConnection(),
        handshake_timeout=0.1,
        poll_interval=0.0,
    )
    client._connected = True
    client._protocol_info = {
        "host_pid": 777,
        "transport": "local-child",
        "protocol": "stablenew.runtime_host",
        "version": 1,
    }

    queue_status_events: list[str] = []
    disconnect_events: list[dict[str, Any]] = []
    client.register_callback(
        RUNTIME_HOST_EVENT_QUEUE_STATUS,
        lambda status: queue_status_events.append(status),
    )
    client.register_callback(
        RUNTIME_HOST_EVENT_DISCONNECTED,
        lambda payload: disconnect_events.append(dict(payload)),
    )
    client._refresh_from_remote = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeHostLaunchError("pipe closed")
    )

    client._poll_loop()

    assert client._connected is False
    assert client._startup_error == "pipe closed"
    assert client._queue_state["status"] == "disconnected"
    assert queue_status_events == ["disconnected"]
    assert disconnect_events == [
        {
            "connected": False,
            "error": "pipe closed",
            "host_pid": 777,
            "transport": "local-child",
        }
    ]