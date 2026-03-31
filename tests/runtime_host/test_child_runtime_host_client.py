from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.queue.job_model import Job
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
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


def test_remote_history_store_reuses_cache_during_reentrant_refresh() -> None:
    client = ChildRuntimeHostClient(
        process=DummyProcess(),
        connection=DummyConnection(),
        handshake_timeout=0.1,
        poll_interval=0.0,
    )
    history_entry = JobHistoryEntry(
        job_id="job-1",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        snapshot={"normalized_job": {"stage_chain": ["txt2img"]}},
        duration_ms=1200,
    )
    snapshot_payload = {
        "jobs": [],
        "history": [json.loads(history_entry.to_json())],
        "queue": {
            "status": "idle",
            "paused": False,
            "runner_running": False,
            "queued_job_ids": [],
            "current_job_id": None,
            "auto_run_enabled": False,
        },
        "managed_runtimes": {},
        "host_pid": 321,
        "transport": "local-child",
    }
    request_count = 0
    callback_job_ids: list[str] = []

    class DummyResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

    def fake_request(
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> DummyResponse:
        nonlocal request_count
        assert name == "runtime_snapshot"
        request_count += 1
        return DummyResponse(snapshot_payload)

    client._request = fake_request  # type: ignore[method-assign]

    def on_history(_entry: JobHistoryEntry) -> None:
        callback_job_ids.extend(item.job_id for item in client.history_store.list_jobs(limit=20))

    client.history_store.register_callback(on_history)

    entries = client.history_store.list_jobs(limit=20)

    assert request_count == 1
    assert [entry.job_id for entry in entries] == ["job-1"]
    assert callback_job_ids == ["job-1"]


def test_remote_history_store_uses_cached_snapshot_until_invalidated() -> None:
    client = ChildRuntimeHostClient(
        process=DummyProcess(),
        connection=DummyConnection(),
        handshake_timeout=0.1,
        poll_interval=0.0,
    )
    history_entry = JobHistoryEntry(
        job_id="job-1",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        snapshot={"normalized_job": {"stage_chain": ["txt2img"]}},
        duration_ms=1200,
    )
    snapshot_payload = {
        "jobs": [],
        "history": [json.loads(history_entry.to_json())],
        "queue": {
            "status": "idle",
            "paused": False,
            "runner_running": False,
            "queued_job_ids": [],
            "current_job_id": None,
            "auto_run_enabled": False,
        },
        "managed_runtimes": {},
        "host_pid": 321,
        "transport": "local-child",
    }
    request_count = 0

    class DummyResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

    def fake_request(
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> DummyResponse:
        nonlocal request_count
        assert name == "runtime_snapshot"
        request_count += 1
        return DummyResponse(snapshot_payload)

    client._request = fake_request  # type: ignore[method-assign]

    first = client.history_store.list_jobs(limit=20)
    second = client.history_store.list_jobs(limit=20)
    client.history_store.invalidate_cache()
    third = client.history_store.list_jobs(limit=20)

    assert [entry.job_id for entry in first] == ["job-1"]
    assert [entry.job_id for entry in second] == ["job-1"]
    assert [entry.job_id for entry in third] == ["job-1"]
    assert request_count == 2


def test_child_runtime_host_client_batches_remote_refreshes_during_queue_submit() -> None:
    client = ChildRuntimeHostClient(
        process=DummyProcess(),
        connection=DummyConnection(),
        handshake_timeout=0.1,
        poll_interval=0.0,
    )
    requested_commands: list[str] = []

    class DummyResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

    def fake_request(
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> DummyResponse:
        requested_commands.append(name)
        if name == "runtime_snapshot":
            return DummyResponse(
                {
                    "jobs": [],
                    "history": [],
                    "queue": {
                        "status": "idle",
                        "paused": False,
                        "runner_running": False,
                        "queued_job_ids": [],
                        "current_job_id": None,
                        "auto_run_enabled": False,
                    },
                    "managed_runtimes": {},
                    "host_pid": 321,
                    "transport": "local-child",
                }
            )
        return DummyResponse({"accepted": True})

    client._request = fake_request  # type: ignore[method-assign]
    job_1 = Job(job_id="job-1")
    job_2 = Job(job_id="job-2")

    with client.queue.coalesce_state_notifications():
        client.submit_job_with_run_mode(job_1, emit_queue_updated=False)
        client.submit_job_with_run_mode(job_2, emit_queue_updated=False)

    assert requested_commands == ["submit_job", "submit_job", "runtime_snapshot"]


def test_remote_queue_remove_deserializes_removed_job_payload() -> None:
    client = ChildRuntimeHostClient(
        process=DummyProcess(),
        connection=DummyConnection(),
        handshake_timeout=0.1,
        poll_interval=0.0,
    )
    client._queue_action = lambda action, *, job_id=None: {  # type: ignore[method-assign]
        "job_id": job_id,
        "priority": 1,
        "run_mode": "queue",
        "source": "gui",
        "prompt_source": "manual",
        "status": "cancelled",
        "snapshot": {"normalized_job": {"job_id": job_id, "config": {}, "seed": 1}},
        "config_snapshot": {},
        "randomizer_metadata": None,
        "variant_index": None,
        "variant_total": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "progress": 0.0,
        "eta_seconds": None,
        "execution_metadata": {
            "external_pids": [],
            "retry_attempts": [],
            "stage_checkpoints": [],
            "last_control_action": None,
            "return_to_queue_count": 0,
        },
    }

    removed = client.queue.remove("job-1")

    assert removed is not None
    assert removed.job_id == "job-1"
    assert removed.status == JobStatus.CANCELLED