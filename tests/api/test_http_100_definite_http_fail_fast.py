"""PR-HTTP-100: a definite HTTP error response from a generation POST is never auto-replayed.

Request counts are asserted at the ``requests.Session.request`` boundary. The server answered, so the job
was dispatched and refused; only retry-safe requests (resources, readiness, options writes) keep retrying.
Ambiguous transport loss after dispatch remains the separate, unchanged ``WebUIGenerationOutcomeUnknownError``
contract (tests/api/test_webui_retry_policy_v2.py).
"""

from __future__ import annotations

import json

import pytest
import requests

import src.api.client as client_module
from src.api.client import DEFINITE_HTTP_RESPONSE_FAIL_FAST, SDWebUIClient
from src.api.forge_client import ForgeWebUIClient
from src.api.types import GenerateErrorCode


class _Response(requests.Response):
    def __init__(self, status: int, payload: dict | None = None) -> None:
        super().__init__()
        self.status_code = status
        self._content = json.dumps(payload if payload is not None else {"detail": "refused"}).encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


GENERATION = [
    ("/sdapi/v1/txt2img", "txt2img"),
    ("/sdapi/v1/img2img", "img2img"),
    ("/sdapi/v1/img2img", "adetailer"),  # ADetailer rides img2img with its own single-attempt policy
    ("/sdapi/v1/extra-single-image", "upscale"),
]
STATUSES = [400, 404, 422, 500, 503]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch):
    """Session boundary stub plus recorders for retry callbacks and API failure records."""

    class Rec:
        calls: list[tuple[str, str]] = []
        status = 500
        payload: dict | None = None
        failures: list[dict] = []

    rec = Rec()
    rec.calls, rec.failures = [], []

    def _request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        rec.calls.append((method, url.split("://", 1)[-1].split("/", 1)[-1]))
        return _Response(rec.status, rec.payload)

    monkeypatch.setattr("src.api.client.requests.Session.request", _request)
    monkeypatch.setattr(client_module, "record_api_failure", lambda **kw: rec.failures.append(kw))
    return rec


def _client(cls=SDWebUIClient):
    client = cls()
    client._sleep = lambda _: None
    client.retry_events = []
    client._retry_callback = lambda **kw: client.retry_events.append(kw)
    return client


@pytest.mark.parametrize("cls", [SDWebUIClient, ForgeWebUIClient], ids=["a1111", "forge"])
@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize(("endpoint", "stage"), GENERATION)
def test_definite_http_error_from_a_generation_post_is_posted_exactly_once(recorder, cls, status, endpoint, stage) -> None:
    recorder.status = status
    client = _client(cls)

    with pytest.raises(requests.HTTPError) as exc_info:
        client._perform_request("post", endpoint, json={"prompt": "p"}, stage=stage)

    assert len(recorder.calls) == 1  # exactly one POST, not the stage policy's 2-3 attempts
    assert client.retry_events == []  # no retry callback / replay bookkeeping
    assert exc_info.value.fail_fast_reason == DEFINITE_HTTP_RESPONSE_FAIL_FAST
    assert exc_info.value.response.status_code == status  # status/body diagnostics survive
    assert exc_info.value.diagnostics_context["request_summary"]["status"] == status
    assert recorder.failures and recorder.failures[0]["status_code"] == status  # API failure recording kept
    assert recorder.failures[0]["endpoint"] == endpoint


def test_the_old_behavior_replayed_a_definite_500_up_to_the_stage_policy(recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization of the defect: with the rule disabled txt2img is POSTed three times."""

    monkeypatch.setattr(client_module, "_is_generation_post", lambda **_k: False)
    recorder.status = 500
    client = _client()

    with pytest.raises(requests.HTTPError):
        client._perform_request("post", "/sdapi/v1/txt2img", json={"prompt": "p"}, stage="txt2img")

    assert len(recorder.calls) == 3
    assert len(client.retry_events) == 3  # the callback fires per failed attempt


def test_structured_cuda_oom_keeps_its_specialized_classification(recorder) -> None:
    recorder.status = 500
    recorder.payload = {"error": "RuntimeError", "errors": "CUDA error: out of memory"}
    client = _client()

    with pytest.raises(requests.HTTPError) as exc_info:
        client._perform_request("post", "/sdapi/v1/txt2img", json={"prompt": "oom"}, stage="txt2img")

    assert len(recorder.calls) == 1
    assert exc_info.value.fail_fast_reason == "cuda_oom"  # not overwritten by the generic reason


def test_generate_images_surfaces_the_single_attempt_failure_with_its_details(recorder) -> None:
    recorder.status = 500
    recorder.payload = {"error": "RuntimeError", "detail": "", "message": "Error(s) in loading state_dict"}
    client = _client()

    outcome = client.generate_images(stage="txt2img", payload={"prompt": "p"})

    assert len(recorder.calls) == 1
    assert outcome.error is not None
    assert outcome.error.code != GenerateErrorCode.OUTCOME_UNKNOWN
    assert "state_dict" in json.dumps(outcome.error.details, default=str) + str(outcome.error.message)


@pytest.mark.parametrize(
    ("method", "endpoint", "stage", "expected"),
    [
        ("get", "/sdapi/v1/samplers", None, 3),
        ("get", "/sdapi/v1/options", None, 3),
        ("get", "/sdapi/v1/progress", None, 3),
        ("post", "/sdapi/v1/options", None, 3),  # idempotent settings write: still retry-safe
        ("post", "/sdapi/v1/interrogate", "interrogate", 3),
    ],
)
def test_retry_safe_non_generation_requests_keep_retrying_http_errors(recorder, method, endpoint, stage, expected) -> None:
    recorder.status = 500
    client = _client()

    with pytest.raises(requests.HTTPError) as exc_info:
        client._perform_request(method, endpoint, json={"x": 1} if method == "post" else None, stage=stage, max_retries=3)

    assert len(recorder.calls) == expected
    assert getattr(exc_info.value, "fail_fast_reason", None) is None


def test_a_generation_post_that_succeeds_is_unaffected(recorder) -> None:
    recorder.status = 200
    recorder.payload = {"images": [], "info": "{}", "parameters": {}}
    client = _client()

    assert client._perform_request("post", "/sdapi/v1/txt2img", json={"prompt": "p"}, stage="txt2img") is not None
    assert len(recorder.calls) == 1


def test_the_generation_post_set_is_derived_from_the_production_call_paths() -> None:
    import re
    from pathlib import Path

    source = Path(client_module.__file__).read_text(encoding="utf-8")
    posted = set(re.findall(r'"post",\s*"(/sdapi/v1/[a-z0-9-]+)"', source))
    dispatching = {p for p in posted if p in client_module._DISPATCHING_GENERATION_ENDPOINTS}
    assert dispatching == {"/sdapi/v1/txt2img", "/sdapi/v1/img2img", "/sdapi/v1/extra-single-image"}
    # the ambiguity (outcome-unknown) set is intentionally unchanged
    assert client_module._GENERATION_POST_ENDPOINTS == {"/sdapi/v1/txt2img", "/sdapi/v1/img2img"}
