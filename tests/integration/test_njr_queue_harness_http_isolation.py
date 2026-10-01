"""The canonical-path harness owns its HTTP transport and never reaches the network."""

from __future__ import annotations

from unittest.mock import patch

import requests

from src.api.client import SDWebUIClient
from src.queue.job_model import JobStatus
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.njr_queue_harness import (
    _HarnessResponse,
    _payload_for,
    run_njr_via_queue,
)

_TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _njr(job_id: str):
    return make_test_njr(
        job_id=job_id,
        prompt="isolation prompt",
        base_model="sdxl",
        config={"sampler": "Euler", "steps": 10, "width": 512, "height": 512, "batch_size": 1},
    )


def _forbid_network():
    """Class-level patch: any real ``requests.Session.request`` call fails the test."""

    return patch.object(
        requests.Session,
        "request",
        side_effect=AssertionError("real HTTP request escaped the harness"),
    )


def test_unpatched_client_never_reaches_the_network_and_default_payload_completes() -> None:
    client = SDWebUIClient(base_url="http://127.0.0.1:7860")
    log: list[tuple[str, str]] = []

    with _forbid_network() as real_request:
        entry = run_njr_via_queue(
            _njr("iso-default"), client, timeout_seconds=15.0, transport_log=log
        )

    real_request.assert_not_called()
    assert entry.job_id == "iso-default"
    assert entry.status is JobStatus.COMPLETED
    assert any(m == "POST" and url.endswith("/sdapi/v1/txt2img") for m, url in log)
    assert "request" not in vars(client._session)  # helper restored the session


def test_caller_supplied_payload_is_what_the_transport_returns() -> None:
    client = SDWebUIClient(base_url="http://127.0.0.1:7860")
    payload = {"images": [_TINY_PNG], "parameters": {"marker": "caller-supplied"}, "info": "{}"}
    log: list[tuple[str, str]] = []

    with _forbid_network() as real_request:
        entry = run_njr_via_queue(
            _njr("iso-supplied"),
            client,
            timeout_seconds=15.0,
            mock_http_response=payload,
            transport_log=log,
        )

    real_request.assert_not_called()
    assert entry.status is JobStatus.COMPLETED
    assert log  # the helper's own transport served the run

    # Transport seam: the very object supplied is returned for generation POSTs.
    response = _HarnessResponse(_payload_for("POST", "http://h/sdapi/v1/txt2img", payload))
    assert response.json() is payload
    assert response.status_code == 200 and response.raise_for_status() is None
    assert _payload_for("GET", "http://h/sdapi/v1/progress", payload)["progress"] == 0.0
    assert _payload_for("GET", "http://h/sdapi/v1/options", payload) == {}
