from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.runtime_host import (
    RuntimeHostProtocolMessage,
    RuntimeHostServer,
    RuntimeHostJobExecutor,
    build_protocol_message,
    build_runtime_host_bootstrap,
    serve_runtime_host_connection,
)


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


def test_runtime_host_server_serves_handshake_diagnostics_and_shutdown(tmp_path) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=tmp_path / "runtime-host-history.jsonl",
        pipeline_runner=StubPipelineRunner(),
    )
    stop_calls: list[str] = []

    def tracking_stop() -> None:
        stop_calls.append("stop")

    bootstrap.job_service.stop = tracking_stop  # type: ignore[method-assign]
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