"""PR-RUNTIME-WEBUI-LIFECYCLE-130: queue execution is never globally gated on the WebUI family.

A native/Comfy-style video job runs through the ordinary JobService -> SQLite queue -> PipelineRunner.run_njr path
while the WebUI runtime is completely unavailable and its readiness backoff is poisoned. Nothing may consult the
WebUI manager, the WebUI connection controller or the WebUI readiness probe on that path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from src.api import healthcheck
from src.api import webui_process_manager as wpm
from src.controller.webui_connection_controller import WebUIConnectionController
from src.queue.job_model import JobStatus
from src.video.video_backend_types import CONTROL_SOURCE_IMAGE, VIDEO_TASK_IMAGE_TO_VIDEO
from tests.integration.test_pr_vid_120_neutral_video_queue import (
    _build_stack,
    _FakeVideoBackend,
    _submit,
)

FORGE_URL = "http://127.0.0.1:7871"


@pytest.fixture
def webui_is_down_and_nothing_may_ask(monkeypatch):
    """WebUI unavailable + poisoned backoff; any WebUI lifecycle/readiness consultation fails the test."""

    wpm.clear_global_webui_process_manager()
    healthcheck.clear_readiness_failure_state()
    for _ in range(3):
        healthcheck._record_readiness_failure(FORGE_URL, RequestsConnectionError("actively refused"))
    assert healthcheck.get_readiness_failure_state(FORGE_URL)["cooldown_remaining_s"] > 0

    consulted: list[str] = []

    def _forbidden(name):
        def _raise(*_a, **_k):
            consulted.append(name)
            raise AssertionError(f"non-WebUI work consulted the WebUI family: {name}")

        return _raise

    monkeypatch.setattr(WebUIConnectionController, "ensure_connected", _forbidden("ensure_connected"))
    monkeypatch.setattr("src.api.healthcheck.wait_for_webui_ready", _forbidden("wait_for_webui_ready"))
    monkeypatch.setattr(
        "src.queue.single_node_runner.get_global_webui_process_manager", _forbidden("global_manager")
    )
    yield consulted
    healthcheck.clear_readiness_failure_state()


def test_a_video_job_completes_while_the_webui_family_is_down_and_never_consults_it(
    tmp_path: Path, webui_is_down_and_nothing_may_ask
) -> None:
    backend = _FakeVideoBackend("fake_video", (CONTROL_SOURCE_IMAGE,), tmp_path / "out")
    repository, queue, service, _controller = _build_stack(tmp_path, [backend])
    job_id = _submit(
        service,
        tmp_path,
        {"backend_id": "fake_video", "task": VIDEO_TASK_IMAGE_TO_VIDEO, "controls": []},
    )

    service.runner.run_once(queue.get_job(job_id))

    done = repository.get_job(job_id)
    assert done is not None and done.status is JobStatus.COMPLETED
    assert len(backend.requests) == 1
    assert webui_is_down_and_nothing_may_ask == []
    service.runner.stop()
    repository.close()
