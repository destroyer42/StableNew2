from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol

from src.queue.job_model import JobStatus
from src.runtime_host.bootstrap import RuntimeHostBootstrap, build_runtime_host_bootstrap
from src.runtime_host.messages import RuntimeHostProtocolMessage, build_protocol_message
from src.runtime_host.serialization import (
    deserialize_job,
    deserialize_run_request,
    serialize_history_entry,
    serialize_job,
    serialize_runtime_snapshot_job,
)
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot


def _queue_status_payload(runtime_host: Any) -> dict[str, Any]:
    queue = getattr(runtime_host, "job_queue", None) or getattr(runtime_host, "queue", None)
    runner = getattr(runtime_host, "runner", None)
    running_job = getattr(runner, "current_job", None) if runner is not None else None
    paused = False
    if queue is not None and hasattr(queue, "is_paused"):
        try:
            paused = bool(queue.is_paused())
        except Exception:
            paused = False
    queued_job_ids: list[str] = []
    jobs = []
    if queue is not None and hasattr(queue, "list_active_jobs_ordered"):
        try:
            jobs = list(queue.list_active_jobs_ordered())
        except Exception:
            jobs = []
    for job in jobs:
        if getattr(job, "status", None) == JobStatus.QUEUED:
            queued_job_ids.append(job.job_id)
    runner_running = bool(runner.is_running()) if runner and hasattr(runner, "is_running") else False
    if paused:
        status = "paused"
    elif runner_running or running_job is not None:
        status = "running"
    else:
        status = "idle"
    return {
        "auto_run_enabled": bool(getattr(runtime_host, "auto_run_enabled", False)),
        "paused": paused,
        "runner_running": runner_running,
        "current_job_id": getattr(running_job, "job_id", None),
        "queued_job_ids": queued_job_ids,
        "job_count": len(jobs),
        "status": status,
    }


def _build_runtime_snapshot_payload(
    runtime_host: Any,
    *,
    history_job_ids: list[str] | None = None,
    managed_runtimes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    queue = getattr(runtime_host, "job_queue", None) or getattr(runtime_host, "queue", None)
    history_store = getattr(runtime_host, "history_store", None)
    jobs = []
    if queue is not None and hasattr(queue, "list_active_jobs_ordered"):
        try:
            jobs = [serialize_runtime_snapshot_job(job) for job in queue.list_active_jobs_ordered()]
        except Exception:
            jobs = []
    history_updates: list[dict[str, Any]] = []
    requested_job_ids = [str(job_id) for job_id in history_job_ids or [] if str(job_id or "").strip()]
    if requested_job_ids:
        get_jobs_cached = getattr(history_store, "get_jobs_cached", None)
        get_job = getattr(history_store, "get_job", None)
        try:
            if callable(get_jobs_cached):
                history_updates = [
                    serialize_history_entry(entry)
                    for entry in get_jobs_cached(requested_job_ids)
                ]
            elif callable(get_job):
                entries = []
                for job_id in requested_job_ids:
                    entry = get_job(job_id)
                    if entry is not None:
                        entries.append(entry)
                history_updates = [serialize_history_entry(entry) for entry in entries]
        except Exception:
            history_updates = []
    return {
        "transport": "local-child",
        "host_pid": os.getpid(),
        "queue": _queue_status_payload(runtime_host),
        "jobs": jobs,
        "history_updates": history_updates,
        "managed_runtimes": dict(managed_runtimes or {}),
    }


def _build_history_snapshot_payload(
    runtime_host: Any,
    *,
    history_limit: int = 50,
) -> dict[str, Any]:
    history_store = getattr(runtime_host, "history_store", None)
    history: list[dict[str, Any]] = []
    history_list_jobs = getattr(history_store, "list_jobs", None)
    if callable(history_list_jobs):
        try:
            history = [
                serialize_history_entry(entry)
                for entry in history_list_jobs(limit=history_limit)
            ]
        except Exception:
            history = []
    return {
        "transport": "local-child",
        "host_pid": os.getpid(),
        "history": history,
    }


class RuntimeHostConnection(Protocol):
    def recv(self) -> Any: ...
    def send(self, value: Any) -> None: ...
    def close(self) -> None: ...


class RuntimeHostServer:
    """Command/response server for a GUI-owned child runtime host process."""

    def __init__(self, bootstrap: RuntimeHostBootstrap) -> None:
        self._bootstrap = bootstrap
        self._shutdown_requested = False

    @property
    def runtime_host(self) -> Any:
        return self._bootstrap.runtime_host

    @property
    def managed_runtime_owner(self) -> Any:
        return self._bootstrap.managed_runtime_owner

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def build_handshake_payload(self) -> dict[str, Any]:
        payload = dict(self.runtime_host.describe_protocol())
        payload.update(
            {
                "transport": "local-child",
                "host_pid": os.getpid(),
                "auto_run_enabled": bool(getattr(self.runtime_host, "auto_run_enabled", False)),
                "commands": [
                    "handshake",
                    "describe_protocol",
                    "runtime_snapshot",
                    "history_snapshot",
                    "diagnostics_snapshot",
                    "managed_runtime_snapshot",
                    "ensure_webui_ready",
                    "retry_webui_connection",
                    "submit_job",
                    "enqueue_njrs",
                    "run_now",
                    "run_next_now",
                    "cancel_current",
                    "pause_queue",
                    "resume_queue",
                    "set_auto_run",
                    "queue_action",
                    "shutdown",
                ],
            }
        )
        payload["managed_runtimes"] = self.managed_runtime_owner.get_snapshot()
        return payload

    def stop(self) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        stop = getattr(self.runtime_host, "stop", None)
        if callable(stop):
            stop()
        owner_stop = getattr(self.managed_runtime_owner, "stop", None)
        if callable(owner_stop):
            owner_stop()

    def handle_message(
        self,
        message: RuntimeHostProtocolMessage | Mapping[str, Any],
    ) -> RuntimeHostProtocolMessage:
        envelope = (
            message
            if isinstance(message, RuntimeHostProtocolMessage)
            else RuntimeHostProtocolMessage.from_dict(message)
        )
        if envelope.kind != "command":
            return build_protocol_message(
                "error",
                envelope.name or "invalid_message",
                {"message": "runtime host only accepts command messages"},
            )

        if envelope.name == "handshake":
            return build_protocol_message("response", "handshake", self.build_handshake_payload())
        if envelope.name == "describe_protocol":
            return build_protocol_message(
                "snapshot",
                "describe_protocol",
                self.build_handshake_payload(),
            )
        if envelope.name == "runtime_snapshot":
            raw_history_job_ids = envelope.payload.get("history_job_ids")
            history_job_ids = (
                [str(job_id) for job_id in raw_history_job_ids if job_id]
                if isinstance(raw_history_job_ids, list)
                else []
            )
            return build_protocol_message(
                "snapshot",
                "runtime_snapshot",
                _build_runtime_snapshot_payload(
                    self.runtime_host,
                    history_job_ids=history_job_ids,
                    managed_runtimes=self.managed_runtime_owner.get_snapshot(),
                ),
            )
        if envelope.name == "history_snapshot":
            raw_history_limit = envelope.payload.get("history_limit")
            history_limit = int(raw_history_limit) if isinstance(raw_history_limit, (str, int, float)) else 50
            return build_protocol_message(
                "snapshot",
                "history_snapshot",
                _build_history_snapshot_payload(
                    self.runtime_host,
                    history_limit=history_limit,
                ),
            )
        if envelope.name == "diagnostics_snapshot":
            payload = dict(self.runtime_host.get_diagnostics_snapshot())
            payload.update(
                {
                    "host_pid": os.getpid(),
                    "transport": "local-child",
                    "managed_runtimes": self.managed_runtime_owner.get_snapshot(),
                }
            )
            webui_tail = self.managed_runtime_owner.get_recent_webui_output_tail()
            if webui_tail is not None:
                payload["webui_tail"] = webui_tail
            return build_protocol_message("snapshot", "diagnostics_snapshot", payload)
        if envelope.name == "managed_runtime_snapshot":
            return build_protocol_message(
                "snapshot",
                "managed_runtime_snapshot",
                self.managed_runtime_owner.get_snapshot(),
            )
        if envelope.name == "ensure_webui_ready":
            return build_protocol_message(
                "response",
                "ensure_webui_ready",
                self.managed_runtime_owner.ensure_webui_ready(
                    autostart=bool(envelope.payload.get("autostart", True))
                ),
            )
        if envelope.name == "retry_webui_connection":
            return build_protocol_message(
                "response",
                "retry_webui_connection",
                self.managed_runtime_owner.retry_webui_connection(),
            )
        if envelope.name == "submit_job":
            job_payload = envelope.payload.get("job") or {}
            job = deserialize_job(job_payload if isinstance(job_payload, Mapping) else {})
            emit_queue_updated = bool(envelope.payload.get("emit_queue_updated", True))
            self.runtime_host.submit_job_with_run_mode(job, emit_queue_updated=emit_queue_updated)
            return build_protocol_message(
                "response",
                "submit_job",
                {"accepted": True, "job_id": job.job_id},
            )
        if envelope.name == "run_now":
            job_payload = envelope.payload.get("job") or {}
            job = deserialize_job(job_payload if isinstance(job_payload, Mapping) else {})
            self.runtime_host.run_now(job)
            return build_protocol_message(
                "response",
                "run_now",
                {"accepted": True, "job_id": job.job_id},
            )
        if envelope.name == "enqueue_njrs":
            raw_njrs = envelope.payload.get("njrs")
            raw_njr_items = raw_njrs if isinstance(raw_njrs, list) else []
            njrs = []
            for item in raw_njr_items:
                if not isinstance(item, Mapping):
                    continue
                record = normalized_job_from_snapshot(item)
                if record is not None:
                    njrs.append(record)
            run_request_payload = envelope.payload.get("run_request") or {}
            run_request = deserialize_run_request(
                run_request_payload if isinstance(run_request_payload, Mapping) else {}
            )
            job_ids = self.runtime_host.enqueue_njrs(njrs, run_request)
            return build_protocol_message(
                "response",
                "enqueue_njrs",
                {"accepted": True, "job_ids": list(job_ids)},
            )
        if envelope.name == "run_next_now":
            self.runtime_host.run_next_now()
            return build_protocol_message("response", "run_next_now", {"accepted": True})
        if envelope.name == "cancel_current":
            job = self.runtime_host.cancel_current(
                return_to_queue=bool(envelope.payload.get("return_to_queue", False))
            )
            return build_protocol_message(
                "response",
                "cancel_current",
                {"job_id": getattr(job, "job_id", None)},
            )
        if envelope.name == "pause_queue":
            self.runtime_host.pause()
            persist_queue_state = getattr(self.runtime_host, "persist_queue_state", None)
            if callable(persist_queue_state):
                persist_queue_state()
            return build_protocol_message("response", "pause_queue", {"accepted": True})
        if envelope.name == "resume_queue":
            self.runtime_host.resume()
            persist_queue_state = getattr(self.runtime_host, "persist_queue_state", None)
            if callable(persist_queue_state):
                persist_queue_state()
            return build_protocol_message("response", "resume_queue", {"accepted": True})
        if envelope.name == "set_auto_run":
            self.runtime_host.auto_run_enabled = bool(envelope.payload.get("enabled", False))
            persist_queue_state = getattr(self.runtime_host, "persist_queue_state", None)
            if callable(persist_queue_state):
                persist_queue_state()
            return build_protocol_message(
                "response",
                "set_auto_run",
                {"accepted": True, "enabled": bool(self.runtime_host.auto_run_enabled)},
            )
        if envelope.name == "queue_action":
            action = str(envelope.payload.get("action") or "")
            queue = getattr(self.runtime_host, "job_queue", None) or getattr(self.runtime_host, "queue", None)
            result: Any = None
            if action and queue is not None:
                if action == "clear" and hasattr(queue, "clear"):
                    result = queue.clear()
                else:
                    job_id = str(envelope.payload.get("job_id") or "")
                    method = getattr(queue, action, None)
                    if callable(method):
                        result = method(job_id)
                        if action == "remove" and result is not None:
                            result = serialize_job(result)
            return build_protocol_message(
                "response",
                "queue_action",
                {"accepted": True, "result": result},
            )
        if envelope.name == "shutdown":
            self.stop()
            return build_protocol_message(
                "response",
                "shutdown",
                {
                    "accepted": True,
                    "host_pid": os.getpid(),
                },
            )
        return build_protocol_message(
            "error",
            envelope.name,
            {"message": f"unknown runtime-host command: {envelope.name}"},
        )


def serve_runtime_host_connection(
    connection: RuntimeHostConnection,
    server: RuntimeHostServer,
) -> None:
    try:
        while not server.shutdown_requested:
            try:
                incoming = connection.recv()
            except EOFError:
                break
            response = server.handle_message(incoming)
            try:
                connection.send(response.to_dict())
            except BrokenPipeError:
                break
            if server.shutdown_requested:
                break
    finally:
        if not server.shutdown_requested:
            server.stop()
        try:
            connection.close()
        except Exception:
            pass


def run_child_runtime_host(
    connection: RuntimeHostConnection,
    *,
    history_path: str | None = None,
    pipeline_runner: Any | None = None,
) -> None:
    bootstrap = build_runtime_host_bootstrap(
        history_path=history_path,
        pipeline_runner=pipeline_runner,
        start_managed_runtimes=True,
    )
    server = RuntimeHostServer(bootstrap)
    serve_runtime_host_connection(connection, server)


__all__ = [
    "RuntimeHostConnection",
    "RuntimeHostServer",
    "run_child_runtime_host",
    "serve_runtime_host_connection",
]