"""Deterministic canonical-path harness: NJR -> JobService -> SQLite -> run_njr.

Executes an immutable NormalizedJobRecord through the real JobService,
SQLite-backed queue/repository, and PipelineRunner, mocking only the HTTP
transport (``requests.Session.request``) so no WebUI is needed. This is a
deterministic integration helper, not a GUI/operator journey.
"""

from __future__ import annotations

import base64
import tempfile
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
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
) -> JobHistoryEntry:
    """Execute NJR through the canonical runner path with mocked HTTP transport.

    Submit through ``JobService`` and the SQLite repository; the queue worker then executes the full
    pipeline stack (run_njr → executor → stages) while mocking only at the HTTP
    transport layer to avoid real WebUI dependencies.

    Args:
        njr: The NormalizedJobRecord to execute.
        api_client: The SDWebUIClient instance (will be mocked at HTTP layer).
        timeout_seconds: Maximum time to wait for execution.
        mock_http_response: Optional dict to use as mock HTTP response.
                           If None, generates a minimal success response.

    Returns:
        JobHistoryEntry representing the completed execution.

    Example:
        ```python
        njr = builder.build_jobs_from_pack(pack)[0]

        with patch.object(api_client._session, 'request') as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "images": ["data:image/png;base64,fake"],
                "parameters": {...}
            }
            mock_request.return_value = mock_response

            entry = run_njr_journey(njr, api_client)
            assert entry.status == JobStatus.COMPLETED
        ```
    """
    from src.utils import StructuredLogger

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

        original_request = getattr(api_client._session, "request", None)

        def _request_with_normalized_response(*args, **kwargs):
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
            if callable(original_request):
                api_client._session.request = _request_with_normalized_response
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
            if callable(original_request):
                api_client._session.request = original_request

    if entry is None:
        raise TimeoutError(
            f"Job {njr.job_id} did not reach a repository terminal state in {timeout_seconds}s."
        )
    return entry
