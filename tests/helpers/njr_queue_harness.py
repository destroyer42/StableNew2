"""Deterministic canonical-path harness: NJR -> JobService -> SQLite -> run_njr.

Executes an immutable NormalizedJobRecord through the real JobService,
SQLite-backed queue/repository, and PipelineRunner, mocking only the HTTP
transport (``requests.Session.request``) so no WebUI is needed. This is a
deterministic integration helper, not a GUI/operator journey.
"""

from __future__ import annotations

import base64
import json
import tempfile
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock, patch

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner

if TYPE_CHECKING:
    from src.api.client import SDWebUIClient

_DEFAULT_TIMEOUT = 30.0


_GENERATION_PREFIX = "/sdapi/v1/"
_NON_GENERATION = ("/progress", "/options", "/samplers", "/schedulers", "/sd-models", "/sd-vae")


class _HarnessResponse:
    """Successful ``requests.Response`` stand-in whose ``json()`` returns ``payload``."""

    status_code = 200
    ok = True
    reason = "OK"

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = self.text.encode("utf-8")
        self.headers = {"content-type": "application/json"}

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> _HarnessResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _method_and_url(args: tuple, kwargs: dict) -> tuple[str, str]:
    method = str(args[0] if args else kwargs.get("method", "")).upper()
    url = str(args[1] if len(args) > 1 else kwargs.get("url", ""))
    return method, url


def _payload_for(method: str, url: str, generation_payload: dict) -> Any:
    """Generation POSTs get the chosen payload; everything else gets neutral success JSON."""

    if method == "POST" and _GENERATION_PREFIX in url:
        if not any(marker in url for marker in _NON_GENERATION) and any(
            stage in url for stage in ("/txt2img", "/img2img", "/extra-")
        ):
            return generation_payload
        return {}
    if method == "GET" and url.endswith("/progress"):
        return {"progress": 0.0, "eta_relative": 0.0, "state": {}}
    return {}


def _wait_for_job_completion(
    job_service, job_id: str, timeout: float = _DEFAULT_TIMEOUT
) -> JobHistoryEntry | None:
    """Wait for a job to reach a terminal status (COMPLETED, FAILED, CANCELLED)."""
    deadline = time.time() + timeout
    terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

    while time.time() < deadline:
        # Check job queue first
        job = job_service.job_queue.get_job(job_id)
        if job and job.status in terminal_statuses:
            break
        # Also check history store for completed jobs
        history_store = getattr(job_service, "history_store", None)
        if history_store:
            entry = history_store.get_job(job_id)
            if entry and entry.status in terminal_statuses:
                return entry
        time.sleep(0.1)

    history_store = getattr(job_service, "history_store", None)
    entry = history_store.get_job(job_id) if history_store else None
    if entry is not None and entry.status in terminal_statuses:
        return entry
    # Not terminal: report where every thread is so a slow or stuck job is explainable
    # from the failure output instead of surfacing as an opaque "running != completed".
    import faulthandler
    import sys

    sys.stderr.write(f"[njr_queue_harness] job {job_id} not terminal after {timeout}s" + chr(10))
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    return None


def run_njr_via_queue(
    njr: NormalizedJobRecord,
    api_client: SDWebUIClient,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT,
    mock_http_response: dict | None = None,
    artifact_root: Path | None = None,
    transport_log: list[tuple[str, str]] | None = None,
) -> JobHistoryEntry:
    """Execute NJR through the canonical runner path with mocked HTTP transport.

    Submit through ``JobService`` and the SQLite repository; the queue worker then executes the full
    pipeline stack (run_njr → executor → stages) while mocking only at the HTTP
    transport layer to avoid real WebUI dependencies.

    Args:
        njr: The NormalizedJobRecord to execute.
        api_client: The SDWebUIClient instance. This helper owns its HTTP transport:
            ``api_client._session.request`` is replaced for the duration of the run and no
            request ever reaches the network.
        timeout_seconds: Maximum time to wait for execution.
        mock_http_response: JSON payload returned (the same object) for generation POSTs
            under ``/sdapi/v1/``. When omitted, a minimal successful txt2img-style response
            is generated. Other calls (progress, options, ...) get neutral successful JSON.
        transport_log: Optional list that receives ``(METHOD, url)`` for every request.

    A caller that has *already* patched ``api_client._session.request`` on the instance and
    does not pass ``mock_http_response`` keeps ownership of its own responses (the helper
    only normalizes them); that patch is never allowed to fall through to the network
    either, because it replaces the real transport.

    Returns:
        JobHistoryEntry representing the completed execution.

    Example:
        ```python
        entry = run_njr_via_queue(njr, SDWebUIClient(base_url="http://127.0.0.1:7860"))
        assert entry.status == JobStatus.COMPLETED
        ```
    """
    from src.utils import StructuredLogger

    payload_supplied = mock_http_response is not None
    # Generate default mock response if not provided
    if mock_http_response is None:
        mock_http_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            ],
            "parameters": {
                "prompt": njr.positive_prompt,
                "negative_prompt": njr.negative_prompt or "",
                "seed": njr.seed,
                "steps": njr.config.get("steps", 20),
                "cfg_scale": njr.config.get("cfg_scale", 7.0),
                "sampler_name": njr.config.get("sampler", "Euler"),
                "scheduler": njr.config.get("scheduler", "automatic"),
                "width": njr.config.get("width", 512),
                "height": njr.config.get("height", 512),
            },
        }

    if artifact_root is None:
        workspace_context = tempfile.TemporaryDirectory(prefix="stablenew-journey-")
    else:
        artifact_root.mkdir(parents=True, exist_ok=True)
        workspace_context = nullcontext(str(artifact_root))
    with workspace_context as temp_root:
        root = Path(temp_root)
        output_root = root / "output"
        isolated_njr = replace(
            njr,
            output_plan=replace(njr.output_plan, base_output_dir=str(output_root)),
        )
        repository = JobRepository(root / "state" / "jobs.sqlite3")
        queue = JobQueue(repository=repository)
        queue_runner = SingleNodeJobRunner(queue, run_callable=None, poll_interval=0.01)
        job_service = JobService(queue, runner=queue_runner, history_store=repository)
        pipeline_runner = PipelineRunner(
            api_client=api_client,
            structured_logger=StructuredLogger(),
            runs_base_dir=str(output_root),
        )
        pipeline_controller = PipelineController(
            pipeline_runner=pipeline_runner,
            job_service=job_service,
        )
        # The production controller owns the NJR-to-runner bridge. The queue
        # worker invokes it only after JobService has submitted and claimed the job.
        queue_runner.run_callable = pipeline_controller._run_job
        job_service.auto_run_enabled = True

        session = api_client._session
        caller_patched = "request" in vars(session)
        original_request = vars(session).get("request")
        owns_transport = payload_supplied or not caller_patched

        def _request_with_normalized_response(*args, **kwargs):
            method, url = _method_and_url(args, kwargs)
            if transport_log is not None:
                transport_log.append((method, url))
            if owns_transport:
                return _HarnessResponse(_payload_for(method, url, mock_http_response))
            if not callable(original_request):
                raise RuntimeError("Journey API client has no HTTP transport")
            response = original_request(*args, **kwargs)
            if isinstance(response, Mock):
                response.content = b"{}"
                response.text = "{}"
                response.headers = {}
                response.raise_for_status = Mock()
                json_fn = getattr(response, "json", None)
                if callable(json_fn):
                    try:
                        payload = json_fn()
                        if isinstance(payload, dict) and isinstance(payload.get("images"), list):
                            tiny_png = (
                                "data:image/png;base64,"
                                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                            )
                            fixed = []
                            for item in payload["images"]:
                                value = str(item or "")
                                try:
                                    raw = value.split("base64,", 1)[1]
                                    valid = base64.b64decode(raw, validate=True).startswith(
                                        b"\x89PNG"
                                    )
                                except (IndexError, ValueError):
                                    valid = False
                                fixed.append(value if valid else tiny_png)
                            payload["images"] = fixed
                            response.json = Mock(return_value=payload)
                    except Exception:
                        pass
            return response

        try:
            session.request = _request_with_normalized_response
            from src.api.webui_api import WebUIAPI

            with (
                patch.object(WebUIAPI, "wait_until_true_ready", return_value=True),
                patch("src.api.client.wait_for_webui_ready", return_value=True),
                patch("src.api.client.validate_webui_health", return_value=True),
                patch.object(
                    api_client,
                    "get_current_model",
                    return_value=isolated_njr.base_model or "sdxl",
                ),
                patch.object(api_client, "set_model", return_value=True),
            ):
                job_ids = job_service.submit_njrs(
                    [isolated_njr], SubmissionPolicy(start_when_idle=True)
                )
                entry = _wait_for_job_completion(job_service, job_ids[0], timeout=timeout_seconds)
        finally:
            job_service.stop()
            repository.close()
            if caller_patched:
                session.request = original_request
            else:
                vars(session).pop("request", None)

    if entry is None:
        raise TimeoutError(
            f"Job {njr.job_id} did not reach a repository terminal state in {timeout_seconds}s."
        )
    return entry
