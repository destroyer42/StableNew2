from __future__ import annotations

from datetime import datetime
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from src.queue.job_history_store import JobHistoryEntry, JSONLJobHistoryStore
from src.queue.job_model import JobStatus
from src.runtime_host import (
    RuntimeHostProtocolMessage,
    RuntimeHostServer,
    RuntimeHostJobExecutor,
    build_protocol_message,
    build_runtime_host_bootstrap,
    serve_runtime_host_connection,
)
from src.services.queue_store_v2 import QueueSnapshotV1, SCHEMA_VERSION
from tests.helpers.job_helpers import make_test_job_from_njr, make_test_njr


class StubPipelineRunner:
    def __init__(self, *, result: Any | None = None, error: Exception | None = None) -> None:
        self._result = {"success": True, "metadata": {"origin": "stub"}} if result is None else result
        self._error = error
        self.records: list[Any] = []

    def run_njr(self, record: Any) -> Any:
        self.records.append(record)
        if self._error is not None:
            raise self._error
        return self._result


class FakeConnection:
    def __init__(self, incoming: list[dict[str, Any]]) -> None:
        self._incoming = list(incoming)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def recv(self) -> dict[str, Any]:
        if not self._incoming:
            raise EOFError()
        return self._incoming.pop(0)

    def send(self, value: dict[str, Any]) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.closed = True


class BrokenPipeOnSendConnection(FakeConnection):
    def send(self, value: dict[str, Any]) -> None:
        raise BrokenPipeError(109, "The pipe has been ended")


def test_runtime_host_bootstrap_uses_injected_pipeline_runner(tmp_path) -> None:
    runner = StubPipelineRunner()

    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=runner,
    )

    assert bootstrap.kernel.pipeline_runner is runner
    assert bootstrap.history_path == tmp_path / "runtime-host-history.jsonl"
    assert bootstrap.runtime_host.job_service is bootstrap.job_service
    assert bootstrap.job_service.runner is not None


def test_runtime_host_job_executor_runs_njr_payloads(tmp_path) -> None:
    record = SimpleNamespace(job_id="njr-1")
    runner = StubPipelineRunner(result={"success": True, "metadata": {"marker": "ok"}})
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=runner,
    )
    executor = RuntimeHostJobExecutor(bootstrap.kernel)

    result = executor(SimpleNamespace(job_id="queue-job-1", _normalized_record=record))

    assert runner.records == [record]
    assert result["success"] is True
    assert result["run_id"] == "queue-job-1"
    assert result["metadata"]["marker"] == "ok"


def test_runtime_host_bootstrap_restores_and_persists_queue_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    restored_record = make_test_njr(job_id="restored-job")
    entry = {
        "queue_id": "restored-job",
        "njr_snapshot": {"normalized_job": asdict(restored_record)},
        "priority": 1,
        "status": "queued",
        "created_at": "2025-07-01T12:00:00Z",
        "queue_schema": SCHEMA_VERSION,
        "metadata": {"run_mode": "queue", "source": "gui", "prompt_source": "pack"},
    }
    saved_snapshots: list[QueueSnapshotV1] = []
    run_next_calls: list[list[str]] = []

    monkeypatch.setattr(
        "src.runtime_host.bootstrap.load_queue_snapshot",
        lambda *_, **__: QueueSnapshotV1(jobs=[entry], auto_run_enabled=True, paused=False),
    )
    monkeypatch.setattr(
        "src.runtime_host.bootstrap.save_queue_snapshot",
        lambda snapshot, *_, **__: saved_snapshots.append(snapshot) or True,
    )

    def _record_run_next(self) -> None:
        run_next_calls.append([job.job_id for job in self.job_queue.list_jobs()])

    monkeypatch.setattr(
        "src.runtime_host.bootstrap.JobService.run_next_now",
        _record_run_next,
    )

    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )

    assert [job.job_id for job in bootstrap.job_queue.list_jobs()] == ["restored-job"]
    assert bootstrap.job_service.auto_run_enabled is True
    assert run_next_calls == [["restored-job"]]
    assert saved_snapshots
    assert saved_snapshots[-1].jobs[0]["queue_id"] == "restored-job"

    bootstrap.job_queue.submit(make_test_job_from_njr(make_test_njr(job_id="new-job")))

    assert any(
        any(item["queue_id"] == "new-job" for item in snapshot.jobs)
        for snapshot in saved_snapshots
    )


def test_runtime_host_bootstrap_restores_named_priority_values(tmp_path, monkeypatch) -> None:
    restored_record = make_test_njr(job_id="restored-job")
    entry = {
        "queue_id": "restored-job",
        "njr_snapshot": {"normalized_job": asdict(restored_record)},
        "priority": "NORMAL",
        "status": "queued",
        "created_at": "2025-07-01T12:00:00Z",
        "queue_schema": SCHEMA_VERSION,
        "metadata": {"run_mode": "queue", "source": "gui", "prompt_source": "pack"},
    }

    monkeypatch.setattr(
        "src.runtime_host.bootstrap.load_queue_snapshot",
        lambda *_, **__: QueueSnapshotV1(jobs=[entry], auto_run_enabled=False, paused=False),
    )
    monkeypatch.setattr(
        "src.runtime_host.bootstrap.save_queue_snapshot",
        lambda *_, **__: True,
    )

    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )

    restored_jobs = bootstrap.job_queue.list_jobs()
    assert [job.job_id for job in restored_jobs] == ["restored-job"]
    assert restored_jobs[0].priority == 1


def test_runtime_host_server_serves_handshake_diagnostics_and_shutdown(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    stop_calls: list[str] = []
    owner_stop_calls: list[str] = []

    def tracking_stop() -> None:
        stop_calls.append("stop")

    bootstrap.job_service.stop = tracking_stop  # type: ignore[method-assign]
    bootstrap.managed_runtime_owner.stop = lambda: owner_stop_calls.append("stop")  # type: ignore[method-assign]
    server = RuntimeHostServer(bootstrap)
    connection = FakeConnection(
        [
            build_protocol_message("command", "handshake").to_dict(),
            build_protocol_message("command", "diagnostics_snapshot").to_dict(),
            build_protocol_message("command", "shutdown").to_dict(),
        ]
    )

    serve_runtime_host_connection(connection, server)

    handshake = RuntimeHostProtocolMessage.from_dict(connection.sent[0])
    diagnostics = RuntimeHostProtocolMessage.from_dict(connection.sent[1])
    shutdown = RuntimeHostProtocolMessage.from_dict(connection.sent[2])

    assert handshake.kind == "response"
    assert handshake.payload["transport"] == "local-child"
    assert handshake.payload["host_pid"]
    assert diagnostics.kind == "snapshot"
    assert diagnostics.payload["transport"] == "local-child"
    assert "queue" in diagnostics.payload
    assert shutdown.kind == "response"
    assert shutdown.payload["accepted"] is True
    assert server.shutdown_requested is True
    assert stop_calls == ["stop"]
    assert owner_stop_calls == ["stop"]
    assert connection.closed is True


def test_runtime_host_server_rejects_unknown_commands(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    server = RuntimeHostServer(bootstrap)

    response = server.handle_message(build_protocol_message("command", "unknown").to_dict())

    assert response.kind == "error"
    assert response.name == "unknown"
    assert "unknown runtime-host command" in str(response.payload["message"])


def test_runtime_host_server_handles_managed_runtime_commands(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    bootstrap.managed_runtime_owner.get_snapshot = lambda: {  # type: ignore[method-assign]
        "webui": {"state": "disconnected", "pid": 321},
        "comfy": {"state": "ready", "pid": 654},
    }
    bootstrap.managed_runtime_owner.ensure_webui_ready = (  # type: ignore[method-assign]
        lambda *, autostart=True: {"state": "ready", "pid": 321, "autostart": autostart}
    )
    bootstrap.managed_runtime_owner.retry_webui_connection = (  # type: ignore[method-assign]
        lambda: {"state": "ready", "pid": 321}
    )
    bootstrap.managed_runtime_owner.get_recent_webui_output_tail = (  # type: ignore[method-assign]
        lambda: {"stdout_tail": ["ready"], "stderr_tail": []}
    )
    server = RuntimeHostServer(bootstrap)

    ensure = server.handle_message(
        build_protocol_message("command", "ensure_webui_ready", {"autostart": True}).to_dict()
    )
    retry = server.handle_message(build_protocol_message("command", "retry_webui_connection").to_dict())
    diagnostics = server.handle_message(build_protocol_message("command", "diagnostics_snapshot").to_dict())

    assert ensure.kind == "response"
    assert ensure.payload["state"] == "ready"
    assert ensure.payload["autostart"] is True
    assert retry.kind == "response"
    assert retry.payload["pid"] == 321
    assert diagnostics.kind == "snapshot"
    assert diagnostics.payload["managed_runtimes"]["comfy"]["pid"] == 654
    assert diagnostics.payload["webui_tail"]["stdout_tail"] == ["ready"]


def test_runtime_host_server_persists_auto_run_updates(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    persist_calls: list[str] = []
    bootstrap.job_service.persist_queue_state = lambda: persist_calls.append("persist")  # type: ignore[attr-defined]
    server = RuntimeHostServer(bootstrap)

    response = server.handle_message(
        build_protocol_message("command", "set_auto_run", {"enabled": True}).to_dict()
    )

    assert response.kind == "response"
    assert response.payload["enabled"] is True
    assert persist_calls == ["persist"]


def test_runtime_host_server_queue_remove_returns_removed_job_payload(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    bootstrap.job_queue.submit(make_test_job_from_njr(make_test_njr(job_id="job-remove")))
    server = RuntimeHostServer(bootstrap)

    response = server.handle_message(
        build_protocol_message(
            "command",
            "queue_action",
            {"action": "remove", "job_id": "job-remove"},
        ).to_dict()
    )

    assert response.kind == "response"
    result = dict(response.payload["result"])
    assert result["job_id"] == "job-remove"
    assert result["status"] == "cancelled"


def test_runtime_snapshot_uses_cached_history_listing_when_available(tmp_path, monkeypatch) -> None:
    history_path = tmp_path / "runtime-host-history.jsonl"
    entry1 = JobHistoryEntry(
        job_id="job-1",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        payload_summary="first",
    )
    history_path.write_text(entry1.to_json() + "\n", encoding="utf-8")

    bootstrap = build_runtime_host_bootstrap(
        history_path=history_path,
        pipeline_runner=StubPipelineRunner(),
    )
    store = bootstrap.history_store
    assert isinstance(store, JSONLJobHistoryStore)
    assert [entry.job_id for entry in store.list_jobs(limit=20)] == ["job-1"]

    entry2 = JobHistoryEntry(
        job_id="job-2",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        payload_summary="second",
    )
    with patch("src.services.persistence_worker.get_persistence_worker") as mock_get_worker:
        mock_worker = Mock()
        mock_worker.enqueue.return_value = True
        mock_get_worker.return_value = mock_worker
        store._append(entry2)

    monkeypatch.setattr(
        store,
        "list_jobs",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("runtime_snapshot should stay on the cache-first history path")
        ),
    )
    server = RuntimeHostServer(bootstrap)

    response = server.handle_message(
        build_protocol_message(
            "command",
            "runtime_snapshot",
            {"history_job_ids": ["job-2", "job-1"]},
        ).to_dict()
    )

    assert response.kind == "snapshot"
    assert [entry["job_id"] for entry in response.payload["history_updates"]] == ["job-2", "job-1"]


def test_runtime_snapshot_omits_heavy_active_job_fields(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    job = make_test_job_from_njr(make_test_njr(job_id="job-runtime"))
    job.result = {"images": ["big-payload"]}
    job.config_snapshot = {"prompt": "should-not-cross-poll"}
    job.execution_metadata.return_to_queue_count = 2
    bootstrap.job_queue.submit(job)
    server = RuntimeHostServer(bootstrap)

    response = server.handle_message(
        build_protocol_message("command", "runtime_snapshot", {}).to_dict()
    )

    assert response.kind == "snapshot"
    payload = response.payload["jobs"][0]
    assert payload["job_id"] == "job-runtime"
    assert "result" not in payload
    assert "config_snapshot" not in payload
    assert "execution_metadata" not in payload


def test_history_snapshot_uses_full_history_listing(tmp_path, monkeypatch) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    store = bootstrap.history_store
    entries = [
        JobHistoryEntry(
            job_id="job-a",
            created_at=datetime.utcnow(),
            status=JobStatus.COMPLETED,
            payload_summary="A",
        )
    ]

    monkeypatch.setattr(store, "list_jobs_cached", lambda *args, **kwargs: [])
    monkeypatch.setattr(store, "list_jobs", lambda *args, **kwargs: list(entries))
    server = RuntimeHostServer(bootstrap)

    response = server.handle_message(
        build_protocol_message(
            "command",
            "history_snapshot",
            {"history_limit": 20},
        ).to_dict()
    )

    assert response.kind == "snapshot"
    assert [entry["job_id"] for entry in response.payload["history"]] == ["job-a"]


def test_runtime_host_server_stops_on_parent_disconnect(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    stop_calls: list[str] = []
    owner_stop_calls: list[str] = []

    bootstrap.job_service.stop = lambda: stop_calls.append("stop")  # type: ignore[method-assign]
    bootstrap.managed_runtime_owner.stop = lambda: owner_stop_calls.append("stop")  # type: ignore[method-assign]
    server = RuntimeHostServer(bootstrap)
    connection = FakeConnection([])

    serve_runtime_host_connection(connection, server)

    assert server.shutdown_requested is True
    assert stop_calls == ["stop"]
    assert owner_stop_calls == ["stop"]
    assert connection.closed is True


def test_runtime_host_server_stops_on_send_broken_pipe(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    stop_calls: list[str] = []
    owner_stop_calls: list[str] = []

    bootstrap.job_service.stop = lambda: stop_calls.append("stop")  # type: ignore[method-assign]
    bootstrap.managed_runtime_owner.stop = lambda: owner_stop_calls.append("stop")  # type: ignore[method-assign]
    server = RuntimeHostServer(bootstrap)
    connection = BrokenPipeOnSendConnection([
        build_protocol_message("command", "handshake").to_dict(),
    ])

    serve_runtime_host_connection(connection, server)

    assert server.shutdown_requested is True
    assert stop_calls == ["stop"]
    assert owner_stop_calls == ["stop"]
    assert connection.closed is True
    assert connection.sent == []