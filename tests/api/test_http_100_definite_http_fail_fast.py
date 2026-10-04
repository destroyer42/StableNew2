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
    generating = {"/sdapi/v1/txt2img", "/sdapi/v1/img2img", "/sdapi/v1/extra-single-image"}
    assert generating <= posted
    # one canonical identity shared by the definite-HTTP rule and the ambiguous-transport classifier
    assert client_module._GENERATION_POST_ENDPOINTS == generating
    assert not hasattr(client_module, "_DISPATCHING_GENERATION_ENDPOINTS")


def test_a_fail_fast_500_reports_the_actual_attempt_count(recorder, caplog: pytest.LogCaptureFixture) -> None:
    recorder.status = 500
    client = _client()
    with caplog.at_level("ERROR", logger="src.api.client"), pytest.raises(requests.HTTPError):
        client._perform_request("post", "/sdapi/v1/txt2img", json={"prompt": "p"}, stage="txt2img", max_retries=3)

    messages = [r.getMessage() for r in caplog.records if "failed after" in r.getMessage()]
    assert len(recorder.calls) == 1
    assert messages and "failed after 1 attempts" in messages[0]
    assert "failed after 3 attempts" not in messages[0]


@pytest.mark.parametrize(("endpoint", "stage"), [("/sdapi/v1/extra-single-image", "upscale"), ("/sdapi/v1/txt2img", "txt2img"), ("/sdapi/v1/img2img", "img2img"), ("/sdapi/v1/img2img", "adetailer")])
@pytest.mark.parametrize("exc_type", [requests.ReadTimeout, requests.ConnectionError])
def test_transport_loss_after_any_generation_post_is_one_post_and_outcome_unknown(monkeypatch, endpoint, stage, exc_type) -> None:
    from src.api.client import WebUIGenerationOutcomeUnknownError

    calls: list[str] = []

    def _request(self, method, url, **kwargs):
        calls.append(method)
        raise exc_type("response lost after dispatch")

    monkeypatch.setattr("src.api.client.requests.Session.request", _request)
    client = _client()
    with pytest.raises(WebUIGenerationOutcomeUnknownError):
        client._perform_request("post", endpoint, json={"x": 1}, stage=stage)
    assert calls == ["POST"]
    assert client.retry_events == []


def test_upscale_read_timeout_surfaces_outcome_unknown_with_request_may_have_executed(monkeypatch) -> None:
    from src.api.client import WebUIGenerationOutcomeUnknownError

    calls: list[str] = []

    def _request(self, method, url, **kwargs):
        calls.append(method)
        raise requests.ReadTimeout("upscale response lost")

    monkeypatch.setattr("src.api.client.requests.Session.request", _request)
    client = _client()
    with pytest.raises(WebUIGenerationOutcomeUnknownError) as exc_info:
        client._perform_request("post", "/sdapi/v1/extra-single-image", json={"x": 1}, stage="upscale")
    assert calls == ["POST"]
    assert exc_info.value.endpoint == "/sdapi/v1/extra-single-image"
    assert exc_info.value.attempt_count == 1
    assert exc_info.value.request_may_have_executed is True


def test_upscale_connect_timeout_keeps_its_safe_retry(monkeypatch) -> None:
    calls: list[str] = []

    def _request(self, method, url, **kwargs):
        calls.append(method)
        if len(calls) < 2:
            raise requests.ConnectTimeout("connection not established")
        return _Response(200, {"image": "ok"})

    monkeypatch.setattr("src.api.client.requests.Session.request", _request)
    client = _client()
    assert client._perform_request("post", "/sdapi/v1/extra-single-image", json={"x": 1}, stage="upscale") is not None
    assert calls == ["POST", "POST"]  # UPSCALE policy: 2 attempts, the second one proves the retry-safe case
