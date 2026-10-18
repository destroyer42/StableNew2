"""A cancelled Comfy job stops promptly and stops only its own prompt (audit B7, P3-4)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
import requests

from src.api.http_transport import DispatchOutcomeUnknown
from src.controller.runtime_state import CancellationError, CancelToken
from src.video import ComfyWorkflowVideoBackend
from src.video.comfy_api_client import ComfyApiClient

PROMPT = "prompt-1"


class _Clock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def time(self) -> float:
        return 1_000.0 + self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


class _Comfy:
    def __init__(self, *, queue: Any, cancel_after_polls: int, token: CancelToken) -> None:
        self.queue = queue
        self.cancel_after_polls = cancel_after_polls
        self.token = token
        self.polls = 0
        self.interrupts: list[Any] = []
        self.deleted: list[Any] = []

    def get_history(self, prompt_id=None, **_kwargs):
        self.polls += 1
        if self.polls >= self.cancel_after_polls:
            self.token.cancel()
        return {}

    def get_queue(self, **_kwargs):
        if isinstance(self.queue, Exception):
            raise self.queue
        return self.queue

    def interrupt(self, prompt_id=None, **_kwargs):
        self.interrupts.append(prompt_id)

    def delete_from_queue(self, prompt_ids, **_kwargs):
        self.deleted.append(list(prompt_ids))


def _wait(monkeypatch, comfy: _Comfy, token: CancelToken | None) -> None:
    clock = _Clock()
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.time",
        SimpleNamespace(time=clock.time, sleep=clock.sleep),
    )
    backend = ComfyWorkflowVideoBackend(history_poll_interval=1.0)
    backend._wait_for_history_entry(comfy, prompt_id=PROMPT, timeout=1200.0, cancel_token=token)


def test_cancelling_a_running_prompt_interrupts_exactly_that_prompt_within_one_poll(
    monkeypatch,
) -> None:
    token = CancelToken()
    running = {"queue_running": [[0, PROMPT, {}, {}, []]], "queue_pending": []}
    comfy = _Comfy(queue=running, cancel_after_polls=3, token=token)
    with pytest.raises(CancellationError):
        _wait(monkeypatch, comfy, token)
    assert comfy.interrupts == [PROMPT]
    assert comfy.deleted == []
    assert comfy.polls == 3  # noticed on the very next iteration, long before the 1200 s bound


def test_cancelling_a_pending_prompt_removes_it_from_the_queue_without_an_interrupt(
    monkeypatch,
) -> None:
    token = CancelToken()
    queue = {
        "queue_running": [[0, "someone-elses", {}, {}, []]],
        "queue_pending": [[1, PROMPT, {}, {}, []]],
    }
    comfy = _Comfy(queue=queue, cancel_after_polls=1, token=token)
    with pytest.raises(CancellationError):
        _wait(monkeypatch, comfy, token)
    assert comfy.deleted == [[PROMPT]]
    assert comfy.interrupts == []  # another client's running prompt is never the target


def test_a_prompt_that_is_not_in_the_queue_needs_no_comfy_call(monkeypatch) -> None:
    token = CancelToken()
    comfy = _Comfy(
        queue={"queue_running": [], "queue_pending": []}, cancel_after_polls=1, token=token
    )
    with pytest.raises(CancellationError):
        _wait(monkeypatch, comfy, token)
    assert comfy.interrupts == [] and comfy.deleted == []


def test_cancellation_still_completes_when_comfy_is_unreachable(monkeypatch) -> None:
    token = CancelToken()
    comfy = _Comfy(queue=ConnectionError("down"), cancel_after_polls=1, token=token)
    with pytest.raises(CancellationError):
        _wait(monkeypatch, comfy, token)


def test_a_failing_interrupt_does_not_mask_the_cancellation(monkeypatch) -> None:
    token = CancelToken()
    running = {"queue_running": [[0, PROMPT, {}, {}, []]], "queue_pending": []}
    comfy = _Comfy(queue=running, cancel_after_polls=1, token=token)
    comfy.interrupt = mock.Mock(side_effect=RuntimeError("refused"))
    with pytest.raises(CancellationError):
        _wait(monkeypatch, comfy, token)


def test_without_a_token_the_wait_is_unchanged(monkeypatch) -> None:
    token = CancelToken()
    comfy = _Comfy(queue={}, cancel_after_polls=10**9, token=token)
    with pytest.raises(TimeoutError):
        _wait(monkeypatch, comfy, None)


# --- the client's wire behavior ---------------------------------------------------------------------


def _ok(payload: dict[str, Any] | None = None) -> mock.Mock:
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = payload or {}
    return response


def test_interrupt_names_the_prompt_and_delete_posts_the_queue_delete_body() -> None:
    session = mock.Mock()
    session.post.return_value = _ok()
    client = ComfyApiClient(base_url="http://127.0.0.1:8188", session=session)
    client.interrupt(PROMPT)
    client.delete_from_queue([PROMPT])
    (interrupt_call, delete_call) = session.post.call_args_list
    assert interrupt_call.args == ("http://127.0.0.1:8188/interrupt",)
    assert interrupt_call.kwargs["json"] == {"prompt_id": PROMPT}
    assert delete_call.args == ("http://127.0.0.1:8188/queue",)
    assert delete_call.kwargs["json"] == {"delete": [PROMPT]}


def test_queue_prompt_is_never_retried_and_an_unknown_outcome_is_typed() -> None:
    session = mock.Mock()
    session.post.side_effect = requests.exceptions.ReadTimeout("slow")
    client = ComfyApiClient(base_url="http://127.0.0.1:8188", session=session)
    with pytest.raises(DispatchOutcomeUnknown):
        client.queue_prompt({"prompt": {}})
    assert session.post.call_count == 1
