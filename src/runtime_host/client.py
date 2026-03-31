from __future__ import annotations

import multiprocessing as mp
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from src.config.app_config import (
    get_runtime_host_handshake_timeout,
    get_runtime_host_poll_interval,
)
from src.queue.job_history_store import JobHistoryEntry, JobHistoryStore
from src.queue.job_model import Job, JobStatus
from src.runtime_host.messages import RuntimeHostProtocolMessage, build_protocol_message
from src.runtime_host.port import (
    RUNTIME_HOST_EVENT_DISCONNECTED,
    RUNTIME_HOST_EVENT_JOB_FAILED,
    RUNTIME_HOST_EVENT_JOB_FINISHED,
    RUNTIME_HOST_EVENT_JOB_STARTED,
    RUNTIME_HOST_EVENT_MANAGED_RUNTIMES_UPDATED,
    RUNTIME_HOST_EVENT_QUEUE_EMPTY,
    RUNTIME_HOST_EVENT_QUEUE_STATUS,
    RUNTIME_HOST_EVENT_QUEUE_UPDATED,
    RuntimeHostPort,
)
from src.runtime_host.serialization import (
    deserialize_history_entry,
    deserialize_job,
    serialize_job,
    serialize_normalized_job_snapshot,
    serialize_run_request,
)
from src.runtime_host.server import run_child_runtime_host


class RuntimeHostLaunchError(RuntimeError):
    """Raised when the GUI-owned runtime host cannot be launched or handshaked."""


class RemoteQueueMirror:
    def __init__(self, client: ChildRuntimeHostClient) -> None:
        self._client = client
        self._history_store: JobHistoryStore | None = None
        self._state_listeners: list[Callable[[], None]] = []

    def register_state_listener(self, callback: Callable[[], None]) -> None:
        self._state_listeners.append(callback)

    def coalesce_state_notifications(self) -> AbstractContextManager[None]:
        return self._client._coalesce_remote_refreshes()

    def list_jobs(self, status_filter: JobStatus | None = None) -> list[Job]:
        jobs = list(self._client._jobs_by_id.values())
        if status_filter is None:
            return jobs
        return [job for job in jobs if job.status == status_filter]

    def list_active_jobs_ordered(self) -> list[Job]:
        ordered: list[Job] = []
        current_job_id = self._client._queue_state.get("current_job_id")
        if current_job_id and current_job_id in self._client._jobs_by_id:
            ordered.append(self._client._jobs_by_id[current_job_id])
        for job_id in self._client._queue_state.get("queued_job_ids") or []:
            job = self._client._jobs_by_id.get(str(job_id))
            if job is not None:
                ordered.append(job)
        seen = {job.job_id for job in ordered}
        for job in self._client._jobs_by_id.values():
            if job.job_id not in seen:
                ordered.append(job)
        return ordered

    def get_job(self, job_id: str) -> Job | None:
        return self._client._jobs_by_id.get(job_id)

    def is_paused(self) -> bool:
        return bool(self._client._queue_state.get("paused", False))

    def pause(self) -> None:
        self._client.pause()

    def resume(self) -> None:
        self._client.resume()

    def pause_running_job(self) -> Job | None:
        self.pause()
        current_job_id = self._client._queue_state.get("current_job_id")
        return self.get_job(str(current_job_id)) if current_job_id else None

    def resume_running_job(self) -> Job | None:
        self.resume()
        current_job_id = self._client._queue_state.get("current_job_id")
        return self.get_job(str(current_job_id)) if current_job_id else None

    def move_up(self, job_id: str) -> bool:
        return bool(self._client._queue_action("move_up", job_id=job_id))

    def move_down(self, job_id: str) -> bool:
        return bool(self._client._queue_action("move_down", job_id=job_id))

    def move_to_front(self, job_id: str) -> bool:
        return bool(self._client._queue_action("move_to_front", job_id=job_id))

    def move_to_back(self, job_id: str) -> bool:
        return bool(self._client._queue_action("move_to_back", job_id=job_id))

    def remove(self, job_id: str) -> Job | None:
        removed = self._client._queue_action("remove", job_id=job_id)
        if isinstance(removed, Mapping):
            return deserialize_job(removed)
        if not removed:
            return None
        return self.get_job(job_id)

    def clear(self) -> int:
        return int(self._client._queue_action("clear"))


class RemoteHistoryStoreMirror:
    def __init__(self, client: ChildRuntimeHostClient) -> None:
        self._client = client
        self._callbacks: list[Callable[[JobHistoryEntry], None]] = []
        self._cache_initialized = False
        self._cache_stale = True

    def _ensure_cache(self, *, history_limit: int) -> None:
        if self._cache_initialized and not self._cache_stale:
            return
        self._client._refresh_history_from_remote(history_limit=history_limit)
        self._cache_initialized = True
        self._cache_stale = False

    def _mark_cache_fresh(self) -> None:
        self._cache_initialized = True
        self._cache_stale = False

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobHistoryEntry]:
        self._ensure_cache(history_limit=max(limit + offset, 50))
        entries = list(self._client._history_entries)
        if status is not None:
            entries = [entry for entry in entries if entry.status == status]
        return entries[offset : offset + limit]

    def get_job(self, job_id: str) -> JobHistoryEntry | None:
        if self._cache_initialized and not self._cache_stale:
            return self._client._history_by_id.get(job_id)
        snapshot_entry = self._client._snapshot_history_by_id.get(job_id)
        if snapshot_entry is not None:
            return snapshot_entry
        self._ensure_cache(history_limit=50)
        return self._client._history_by_id.get(job_id)

    def register_callback(self, callback: Callable[[JobHistoryEntry], None]) -> None:
        self._callbacks.append(callback)

    def invalidate_cache(self) -> None:
        self._cache_stale = True

    def shutdown(self) -> None:
        return None

    def _emit(self, entry: JobHistoryEntry) -> None:
        for callback in list(self._callbacks):
            try:
                self._client._dispatch_call(callback, entry)
            except Exception:
                continue


class RemoteRunnerMirror:
    def __init__(self, client: ChildRuntimeHostClient) -> None:
        self._client = client

    @property
    def current_job(self) -> Job | None:
        current_job_id = self._client._queue_state.get("current_job_id")
        if not current_job_id:
            return None
        return self._client._jobs_by_id.get(str(current_job_id))

    def start(self) -> None:
        self._client.run_next_now()

    def stop(self) -> None:
        return None

    def is_running(self) -> bool:
        return bool(self._client._queue_state.get("runner_running", False))

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        self._client.cancel_current(return_to_queue=return_to_queue)


class ChildRuntimeHostClient(RuntimeHostPort):
    """GUI-side runtime host client for a GUI-owned child process."""

    def __init__(
        self,
        process: Any,
        connection: Any,
        *,
        handshake_timeout: float,
        poll_interval: float,
    ) -> None:
        self._process = process
        self._connection = connection
        self._handshake_timeout = float(handshake_timeout)
        self._poll_interval = float(poll_interval)
        self._request_lock = threading.RLock()
        self._refresh_batch_lock = threading.Lock()
        self._refresh_context = threading.local()
        self._remote_refresh_suppressed = 0
        self._remote_refresh_pending = False
        self._remote_refresh_history_limit = 50
        self._callbacks: dict[str, list[Callable[..., None]]] = {}
        self._status_callbacks: dict[str, Callable[[Job, JobStatus], None]] = {}
        self._completion_handlers: list[Callable[[Any, Any], None]] = []
        self._event_dispatcher: Callable[[Callable[[], None]], None] | None = None
        self._job_lifecycle_logger: Any | None = None
        self._on_queue_activity: Callable[[], None] | None = None
        self._on_runner_activity: Callable[[], None] | None = None
        self._protocol_info: dict[str, Any] = {}
        self._queue_state: dict[str, Any] = {
            "status": "idle",
            "paused": False,
            "runner_running": False,
            "queued_job_ids": [],
            "current_job_id": None,
            "auto_run_enabled": False,
        }
        self._jobs_by_id: dict[str, Job] = {}
        self._history_entries: list[JobHistoryEntry] = []
        self._history_by_id: dict[str, JobHistoryEntry] = {}
        self._snapshot_history_by_id: dict[str, JobHistoryEntry] = {}
        self._managed_runtime_state: dict[str, Any] = {}
        self._connected = False
        self._startup_error: str | None = None
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self.queue = RemoteQueueMirror(self)
        self.job_queue = self.queue
        self.runner = RemoteRunnerMirror(self)
        self.history_store = RemoteHistoryStoreMirror(self)

    @property
    def auto_run_enabled(self) -> bool:
        return bool(self._queue_state.get("auto_run_enabled", False))

    @auto_run_enabled.setter
    def auto_run_enabled(self, value: bool) -> None:
        self._request("set_auto_run", {"enabled": bool(value)})
        self._schedule_remote_refresh()

    def connect(self) -> None:
        response = self._request("handshake", timeout=self._handshake_timeout)
        self._protocol_info = dict(response.payload)
        self._connected = True
        self._startup_error = None
        self._refresh_from_remote(history_limit=50)
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="RuntimeHostClientPoll",
            daemon=True,
        )
        self._poll_thread.start()

    def describe_protocol(self) -> dict[str, Any]:
        if self._protocol_info:
            return dict(self._protocol_info)
        return {"transport": "local-child"}

    def register_callback(self, event: str, callback: Callable[..., None]) -> None:
        self._callbacks.setdefault(event, []).append(callback)

    def set_status_callback(self, name: str, callback: Callable[[Job, JobStatus], None]) -> None:
        self._status_callbacks[name] = callback

    def set_event_dispatcher(self, dispatch_fn: Callable[[Callable[[], None]], None]) -> None:
        self._event_dispatcher = dispatch_fn

    def set_job_lifecycle_logger(self, logger: Any | None) -> None:
        self._job_lifecycle_logger = logger

    def set_activity_hooks(self, *, on_queue_activity=None, on_runner_activity=None) -> None:
        self._on_queue_activity = on_queue_activity
        self._on_runner_activity = on_runner_activity

    def register_completion_handler(self, handler: Callable[[Any, Any], None]) -> None:
        self._completion_handlers.append(handler)

    def submit_job_with_run_mode(self, job: Any, *, emit_queue_updated: bool = True) -> None:
        self._request(
            "submit_job",
            {
                "job": serialize_job(job),
                "emit_queue_updated": bool(emit_queue_updated),
            },
        )
        self._schedule_remote_refresh()

    def submit_queued(self, job: Any, *, emit_queue_updated: bool = True) -> None:
        self.submit_job_with_run_mode(job, emit_queue_updated=emit_queue_updated)

    def enqueue(self, job: Any, *, emit_queue_updated: bool = True) -> None:
        self.submit_job_with_run_mode(job, emit_queue_updated=emit_queue_updated)

    def run_now(self, job: Any) -> None:
        self._request("run_now", {"job": serialize_job(job)})
        self._schedule_remote_refresh()

    def enqueue_njrs(self, njrs: list[Any], run_request: Any) -> list[str]:
        response = self._request(
            "enqueue_njrs",
            {
                "njrs": [serialize_normalized_job_snapshot(record) for record in njrs],
                "run_request": serialize_run_request(run_request),
            },
        )
        self._schedule_remote_refresh()
        raw_job_ids = response.payload.get("job_ids")
        if not isinstance(raw_job_ids, list):
            return []
        return [str(job_id) for job_id in raw_job_ids]

    def run_next_now(self) -> None:
        self._request("run_next_now")
        self._schedule_remote_refresh()

    def cancel_current(self, *, return_to_queue: bool = False) -> Any:
        response = self._request(
            "cancel_current",
            {"return_to_queue": bool(return_to_queue)},
        )
        self._schedule_remote_refresh()
        return response.payload.get("job_id")

    def pause(self) -> None:
        self._request("pause_queue")
        self._schedule_remote_refresh()

    def resume(self) -> None:
        self._request("resume_queue")
        self._schedule_remote_refresh()

    def replace_runner(self, value: Any) -> None:
        raise RuntimeError("Child runtime host manages its own runner; replacement is unsupported")

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        response = self._request("diagnostics_snapshot")
        payload = dict(response.payload)
        payload["runtime_host_client"] = {
            "connected": self._connected,
            "startup_error": self._startup_error,
            "host_pid": self._protocol_info.get("host_pid"),
            "transport": self.describe_protocol().get("transport", "local-child"),
            "protocol": self._protocol_info.get("protocol"),
            "version": self._protocol_info.get("version"),
        }
        return payload

    def get_managed_runtime_snapshot(self) -> dict[str, Any]:
        response = self._request("managed_runtime_snapshot")
        payload = dict(response.payload)
        self._managed_runtime_state = payload
        return payload

    def get_cached_managed_runtime_snapshot(self) -> dict[str, Any]:
        return dict(self._managed_runtime_state)

    def ensure_webui_ready(self, *, autostart: bool = True) -> dict[str, Any]:
        response = self._request(
            "ensure_webui_ready",
            {"autostart": bool(autostart)},
        )
        payload = dict(response.payload)
        managed = dict(self._managed_runtime_state)
        managed["webui"] = payload
        self._managed_runtime_state = managed
        return payload

    def retry_webui_connection(self) -> dict[str, Any]:
        response = self._request("retry_webui_connection")
        payload = dict(response.payload)
        managed = dict(self._managed_runtime_state)
        managed["webui"] = payload
        self._managed_runtime_state = managed
        return payload

    def stop(self) -> None:
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=max(0.1, self._poll_interval * 2.0))
            self._poll_thread = None
        try:
            self._request("shutdown", timeout=min(self._handshake_timeout, 2.0))
        except Exception:
            pass
        try:
            self._connection.close()
        except Exception:
            pass
        try:
            self._process.join(timeout=2.0)
        except Exception:
            pass
        try:
            if hasattr(self._process, "is_alive") and self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
        except Exception:
            pass
        self._connected = False

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            try:
                self._refresh_from_remote(history_limit=50)
            except Exception as exc:
                error_message = str(exc) or "runtime host disconnected"
                self._startup_error = error_message
                self._connected = False
                queue_state = dict(self._queue_state)
                queue_state["status"] = "disconnected"
                queue_state["runner_running"] = False
                queue_state["current_job_id"] = None
                self._queue_state = queue_state
                self._emit(RUNTIME_HOST_EVENT_QUEUE_STATUS, "disconnected")
                self._emit(
                    RUNTIME_HOST_EVENT_DISCONNECTED,
                    {
                        "connected": False,
                        "error": error_message,
                        "host_pid": self._protocol_info.get("host_pid"),
                        "transport": self.describe_protocol().get("transport", "local-child"),
                    },
                )
                break

    def _dispatch(self, fn: Callable[[], None]) -> None:
        dispatch = self._event_dispatcher
        if callable(dispatch):
            dispatch(fn)
        else:
            fn()

    def _dispatch_call(self, callback: Callable[..., None], *args: Any) -> None:
        def _invoke() -> None:
            callback(*args)

        self._dispatch(_invoke)

    def _emit(self, event: str, *args: Any) -> None:
        for callback in list(self._callbacks.get(event, [])):
            try:
                self._dispatch_call(callback, *args)
            except Exception:
                continue

    def _emit_status_callbacks(self, job: Job, status: JobStatus) -> None:
        for callback in list(self._status_callbacks.values()):
            try:
                self._dispatch_call(callback, job, status)
            except Exception:
                continue

    def _notify_completion_handlers(self, job: Job, success: bool) -> None:
        payload = {
            "success": success,
            "status": job.status,
            "error": job.error_message,
            "result": job.result,
        }
        for handler in list(self._completion_handlers):
            try:
                self._dispatch_call(handler, job, payload)
            except Exception:
                continue

    def _request(
        self,
        name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> RuntimeHostProtocolMessage:
        message = build_protocol_message("command", name, payload or {})
        wait_timeout = self._handshake_timeout if timeout is None else float(timeout)
        with self._request_lock:
            try:
                self._connection.send(message.to_dict())
            except Exception as exc:
                raise RuntimeHostLaunchError(f"runtime host send failed: {exc}") from exc
            if not self._connection.poll(wait_timeout):
                raise RuntimeHostLaunchError(
                    f"runtime host command '{name}' timed out after {wait_timeout:.2f}s"
                )
            try:
                response = RuntimeHostProtocolMessage.from_dict(self._connection.recv())
            except EOFError as exc:
                raise RuntimeHostLaunchError("runtime host connection closed unexpectedly") from exc
        if response.kind == "error":
            message_text = str(response.payload.get("message") or f"runtime host command failed: {name}")
            raise RuntimeHostLaunchError(message_text)
        return response

    def _queue_action(self, action: str, *, job_id: str | None = None) -> Any:
        payload: dict[str, Any] = {"action": action}
        if job_id is not None:
            payload["job_id"] = job_id
        response = self._request("queue_action", payload)
        self._schedule_remote_refresh()
        return response.payload.get("result")

    def _coalesce_remote_refreshes(self) -> AbstractContextManager[None]:
        return _RemoteRefreshBatch(self)

    def _schedule_remote_refresh(self, *, history_limit: int = 50) -> None:
        should_refresh = False
        with self._refresh_batch_lock:
            if self._remote_refresh_suppressed > 0:
                self._remote_refresh_pending = True
                self._remote_refresh_history_limit = max(
                    int(history_limit),
                    int(self._remote_refresh_history_limit),
                )
            else:
                should_refresh = True
        if should_refresh:
            self._refresh_from_remote(history_limit=history_limit)

    def _enter_remote_refresh_batch(self) -> None:
        with self._refresh_batch_lock:
            self._remote_refresh_suppressed += 1

    def _exit_remote_refresh_batch(self) -> None:
        history_limit = 50
        should_refresh = False
        with self._refresh_batch_lock:
            self._remote_refresh_suppressed = max(0, self._remote_refresh_suppressed - 1)
            if self._remote_refresh_suppressed == 0 and self._remote_refresh_pending:
                should_refresh = True
                history_limit = int(self._remote_refresh_history_limit)
                self._remote_refresh_pending = False
                self._remote_refresh_history_limit = 50
        if should_refresh:
            self._refresh_from_remote(history_limit=history_limit)

    def _refresh_from_remote(self, *, history_limit: int = 50) -> None:
        refresh_context = self._refresh_context
        if getattr(refresh_context, "active", False):
            return
        refresh_context.active = True
        try:
            response = self._request(
                "runtime_snapshot",
                {"history_job_ids": list(self._jobs_by_id)},
            )
            self._apply_runtime_snapshot(dict(response.payload))
        finally:
            refresh_context.active = False

    def _refresh_history_from_remote(self, *, history_limit: int = 50) -> None:
        response = self._request("history_snapshot", {"history_limit": int(history_limit)})
        self._apply_history_snapshot(dict(response.payload))

    def _apply_history_snapshot(self, payload: Mapping[str, Any]) -> None:
        history_entries = [
            deserialize_history_entry(item)
            for item in payload.get("history") or []
            if isinstance(item, Mapping)
        ]
        self._history_entries = history_entries
        self._history_by_id = {entry.job_id: entry for entry in history_entries}
        self._snapshot_history_by_id.update(self._history_by_id)
        self.history_store._mark_cache_fresh()

    def _apply_runtime_snapshot(self, payload: Mapping[str, Any]) -> None:
        previous_jobs = dict(self._jobs_by_id)
        previous_history = dict(self._history_by_id)
        previous_snapshot_history = dict(self._snapshot_history_by_id)
        previous_queue_state = dict(self._queue_state)
        previous_managed_runtime_state = dict(self._managed_runtime_state)

        jobs = [
            deserialize_job(item)
            for item in payload.get("jobs") or []
            if isinstance(item, Mapping)
        ]
        history_updates = [
            deserialize_history_entry(item)
            for item in (payload.get("history_updates") or payload.get("history") or [])
            if isinstance(item, Mapping)
        ]
        self._jobs_by_id = {job.job_id: job for job in jobs}
        for entry in history_updates:
            self._snapshot_history_by_id[entry.job_id] = entry
            if self.history_store._cache_initialized:
                self._history_by_id[entry.job_id] = entry
        if self.history_store._cache_initialized:
            self._history_entries = sorted(
                self._history_by_id.values(),
                key=lambda entry: entry.created_at,
                reverse=True,
            )
        self._queue_state = dict(payload.get("queue") or {})
        self._managed_runtime_state = dict(payload.get("managed_runtimes") or {})
        self._protocol_info.setdefault("host_pid", payload.get("host_pid"))
        self._protocol_info.setdefault("transport", payload.get("transport", "local-child"))

        if previous_managed_runtime_state != self._managed_runtime_state:
            self._emit(
                RUNTIME_HOST_EVENT_MANAGED_RUNTIMES_UPDATED,
                dict(self._managed_runtime_state),
            )

        if previous_queue_state != self._queue_state:
            if callable(self._on_queue_activity):
                try:
                    self._on_queue_activity()
                except Exception:
                    pass
            queue_status = str(self._queue_state.get("status") or "idle")
            self._emit(RUNTIME_HOST_EVENT_QUEUE_STATUS, queue_status)

        previous_active = set(previous_jobs)
        current_active = set(self._jobs_by_id)
        if previous_active != current_active or previous_queue_state.get("queued_job_ids") != self._queue_state.get("queued_job_ids"):
            summaries = [job.get_display_summary() for job in self.queue.list_active_jobs_ordered()]
            self._emit(RUNTIME_HOST_EVENT_QUEUE_UPDATED, summaries)
            if not current_active:
                self._emit(RUNTIME_HOST_EVENT_QUEUE_EMPTY)

        for job_id, job in self._jobs_by_id.items():
            previous = previous_jobs.get(job_id)
            previous_status = previous.status if previous is not None else None
            if previous_status == job.status:
                continue
            self._emit_status_callbacks(job, job.status)
            if job.status == JobStatus.RUNNING:
                if callable(self._on_runner_activity):
                    try:
                        self._on_runner_activity()
                    except Exception:
                        pass
                self._emit(RUNTIME_HOST_EVENT_JOB_STARTED, job)

        for job_id, previous in previous_jobs.items():
            if job_id in self._jobs_by_id:
                continue
            history_entry = self._snapshot_history_by_id.get(job_id) or self._history_by_id.get(job_id)
            if history_entry is None:
                continue
            finished = previous
            finished.status = history_entry.status
            finished.completed_at = history_entry.completed_at
            finished.result = history_entry.result
            finished.error_message = history_entry.error_message
            self._emit_status_callbacks(finished, finished.status)
            if finished.status == JobStatus.COMPLETED:
                self._emit(RUNTIME_HOST_EVENT_JOB_FINISHED, finished)
                self._notify_completion_handlers(finished, True)
            else:
                self._emit(RUNTIME_HOST_EVENT_JOB_FAILED, finished)
                self._notify_completion_handlers(finished, False)

        previous_known_history = dict(previous_history)
        previous_known_history.update(previous_snapshot_history)
        for entry in history_updates:
            previous_entry = previous_known_history.get(entry.job_id)
            if (
                previous_entry is not None
                and previous_entry.status == entry.status
                and previous_entry.completed_at == entry.completed_at
            ):
                continue
            self.history_store._emit(entry)


class _RemoteRefreshBatch(AbstractContextManager[None]):
    def __init__(self, client: ChildRuntimeHostClient) -> None:
        self._client = client

    def __enter__(self) -> None:
        self._client._enter_remote_refresh_batch()
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._client._exit_remote_refresh_batch()
        return False


def launch_child_runtime_host_client(
    *,
    history_path: str | None = None,
    handshake_timeout: float | None = None,
    poll_interval: float | None = None,
) -> ChildRuntimeHostClient:
    context = mp.get_context("spawn")
    parent_conn, child_conn = context.Pipe(duplex=True)
    process = context.Process(
        target=run_child_runtime_host,
        args=(child_conn,),
        kwargs={"history_path": history_path},
        name="StableNewRuntimeHost",
        daemon=True,
    )
    process.start()
    child_conn.close()
    client = ChildRuntimeHostClient(
        process=process,
        connection=parent_conn,
        handshake_timeout=(
            get_runtime_host_handshake_timeout()
            if handshake_timeout is None
            else float(handshake_timeout)
        ),
        poll_interval=(
            get_runtime_host_poll_interval()
            if poll_interval is None
            else float(poll_interval)
        ),
    )
    try:
        client.connect()
        return client
    except Exception:
        client.stop()
        raise


__all__ = [
    "ChildRuntimeHostClient",
    "RuntimeHostLaunchError",
    "launch_child_runtime_host_client",
]