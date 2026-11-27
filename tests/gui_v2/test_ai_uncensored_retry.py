"""ASSIST-FIX: after a refusal, one explicit press resends that request to the approved uncensored model."""

from __future__ import annotations

import pytest

from src.ai_assist.contracts import AssistOutcome, OutcomeCode, SuggestionKind
from src.ai_assist.remote_preview import (
    DEFAULT_MODEL,
    ENDPOINT,
    RUNTIME_VERSION,
    UNCENSORED_MODEL,
    RemoteApproval,
)

from .test_ai_suggestions_112 import journey, start  # noqa: F401 - fixture

pytestmark = pytest.mark.gui

OTHER = RemoteApproval(ENDPOINT, UNCENSORED_MODEL, "c" * 64, RUNTIME_VERSION)


def refusal(request_id, model=DEFAULT_MODEL):
    return AssistOutcome(
        OutcomeCode.REFUSED_BY_MODEL,
        request_id,
        details={"provider": "remote", "model_name": model},
    )


@pytest.fixture
def retrying(journey):  # noqa: F811
    j = journey
    j.sent = []
    plain = j.service.submit

    def submit(request, done, *, one_off=None):
        j.sent.append(one_off)
        return plain(request, done)

    j.service.submit = submit
    j.owner.refusal_retry_model = lambda outcome: (
        OTHER if outcome.code is OutcomeCode.REFUSED_BY_MODEL else None
    )
    return j


def deliver(j, outcome):
    j.service.callbacks[-1](outcome)
    j.scheduled.pop(0)()
    j.root.update_idletasks()


def shown(dialog):
    return bool(dialog.retry_button.winfo_manager())


def test_the_button_appears_only_after_a_refusal_and_resends_that_request(retrying):
    j = retrying
    dialog = start(j)
    assert not shown(dialog) and len(j.service.requests) == 1
    deliver(j, refusal(j.service.requests[0].request_id))
    assert shown(dialog)
    assert len(j.service.requests) == 1  # nothing is automatic

    dialog.retry_button.invoke()
    first, second = j.service.requests
    assert j.sent == [None, OTHER]
    assert second.request_id != first.request_id
    assert (second.kind, second.positive_text) == (first.kind, first.positive_text)
    assert not shown(dialog)


def test_the_next_ordinary_request_goes_to_the_selected_model_again(retrying):
    j = retrying
    dialog = start(j)
    deliver(j, refusal(j.service.requests[-1].request_id))
    j.flow.request(SuggestionKind.PROMPT_REWRITE)
    assert j.sent == [None, None] and not shown(dialog)


def test_a_changed_prompt_sends_nothing(retrying):
    j = retrying
    dialog = start(j)
    deliver(j, refusal(j.service.requests[-1].request_id))
    j.frame.workspace_state.set_slot_text(0, "a different barn")
    j.frame._refresh_editor()
    dialog.retry_button.invoke()
    assert len(j.service.requests) == 1
    assert "nothing was sent" in dialog.status_var.get()


def test_other_outcomes_offer_nothing(retrying):
    j = retrying
    dialog = start(j)
    deliver(j, AssistOutcome(OutcomeCode.TIMEOUT, j.service.requests[-1].request_id))
    assert not shown(dialog)
    j.flow.retry_uncensored()
    assert len(j.service.requests) == 1


def test_the_owner_offers_it_only_for_a_remote_refusal_by_another_model(journey, monkeypatch):  # noqa: F811
    owner = journey.owner
    settings = type("S", (), {"preferred": True, "approvals": (OTHER,)})()
    monkeypatch.setattr(owner._remote, "settings", lambda: settings)
    assert owner.refusal_retry_model(refusal("a")) == OTHER
    assert owner.refusal_retry_model(refusal("a", UNCENSORED_MODEL)) is None
    assert owner.refusal_retry_model(AssistOutcome(OutcomeCode.TIMEOUT, "a")) is None
    local = AssistOutcome(OutcomeCode.REFUSED_BY_MODEL, "a", details={"provider": "local"})
    assert owner.refusal_retry_model(local) is None
    settings.approvals = ()
    assert owner.refusal_retry_model(refusal("a")) is None
