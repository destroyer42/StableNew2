"""PR-RUNTIME-FORGE-IDENTITY-150: the bounded initial identity-establishment settle (deterministic, no wall-clock wait).

General WebUI readiness can be proven a moment before the endpoint serves enough evidence to classify Forge. For an
owned, still-current session with no valid attestation, the first Forge stage may therefore wait a small, finite time
for the first REAL positive classification. It never relaxes the requirement for that proof, never retries through
contradiction, re-validates the exact session before every probe, never runs for external endpoints or A1111, and never
runs again once the session has an attestation. Time is a fake clock; the sleeper only advances it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.api.webui_identity_attestation import (
    INITIAL_IDENTITY_POLL_SECONDS,
    INITIAL_IDENTITY_SETTLE_SECONDS,
    SETTLE_CONTRADICTION,
    SETTLE_ESTABLISHED,
    SETTLE_SESSION_CHANGED,
    SETTLE_TIMEOUT,
    SOURCE_CONTRADICTORY,
    SOURCE_LIVE_POSITIVE,
    SOURCE_NO_ATTESTATION,
    SOURCE_SAME_SESSION,
    SOURCE_SESSION_CHANGED,
)
from src.api.webui_runtime_identity import (
    A1111_WEBUI_IDENTITY,
    WebUIRuntimeIdentity,
    WebUIRuntimeIdentityMismatch,
    classify_runtime_identity,
)
from tests.api.test_managed_forge_identity_attestation import (
    A1111,
    ENDPOINT,
    FORGE,
    UNKNOWN,
    FakeManager,
    Stack,
)

START = 1000.0


def _gap_identity(**kwargs: Any) -> WebUIRuntimeIdentity:
    return classify_runtime_identity(kwargs.get("flags"), kwargs.get("modules"), kwargs.get("vae"), options=kwargs.get("options"))


class Hooked:
    """A scripted probe that can run a callback on each call (to change the world mid-settle or watch dispatches)."""

    def __init__(self, stack: Stack, *script: WebUIRuntimeIdentity, hook: Any = None) -> None:
        self.stack = stack
        self.script = list(script)
        self.hook = hook
        self.calls = 0

    def __call__(self) -> WebUIRuntimeIdentity:
        self.calls += 1
        if self.hook is not None:
            self.hook(self.calls)
        return self.script[min(self.calls - 1, len(self.script) - 1)]


def _install(stack: Stack, *script: WebUIRuntimeIdentity, hook: Any = None) -> Hooked:
    probe = Hooked(stack, *script, hook=hook)
    stack.client.probe_runtime_identity = probe
    return probe


def _reject(stack: Stack) -> WebUIRuntimeIdentityMismatch:
    with pytest.raises(WebUIRuntimeIdentityMismatch) as excinfo:
        stack.run_forge_stage()
    return excinfo.value


# ---------------------------------------------------------------------------------------------------------------
# the production bound
# ---------------------------------------------------------------------------------------------------------------


def test_the_production_bound_is_a_few_seconds_with_a_short_poll() -> None:
    assert 0 < INITIAL_IDENTITY_SETTLE_SECONDS <= 10.0
    assert 0 < INITIAL_IDENTITY_POLL_SECONDS <= 1.0


# ---------------------------------------------------------------------------------------------------------------
# 1 / 13: eventual positive proof, dispatch only afterwards
# ---------------------------------------------------------------------------------------------------------------


def test_unknown_unknown_forge_establishes_exactly_one_attestation_and_dispatches_only_after_the_positive(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    seen_dispatches: list[int] = []
    probe = _install(stack, UNKNOWN, UNKNOWN, FORGE, hook=lambda _n: seen_dispatches.append(stack.dispatches))

    stack.run_forge_stage()

    decision = stack.forge.last_identity_decision
    assert probe.calls == 3
    assert decision.source == SOURCE_LIVE_POSITIVE and decision.allowed
    assert decision.settle.outcome == SETTLE_ESTABLISHED and decision.settle.attempts == 3
    assert decision.settle.elapsed_seconds == pytest.approx(2 * INITIAL_IDENTITY_POLL_SECONDS)
    assert stack.clock.sleeps == [INITIAL_IDENTITY_POLL_SECONDS] * 2
    assert seen_dispatches == [0, 0, 0], "no generation method may run before the first real positive proof"
    assert stack.dispatches == 1
    session = stack.attestor.attested_session()
    assert session is not None and (session.pid, session.ready_epoch) == (4100, 1)


@pytest.mark.parametrize(
    "gap_identity",
    [
        UNKNOWN,  # complete endpoint loss
        _gap_identity(modules=[]),  # /options unavailable
        _gap_identity(options=["malformed"], modules=[]),  # /options malformed
        _gap_identity(options={"forge_preset": "flux"}),  # /sd-modules unavailable
        _gap_identity(options={"forge_preset": "flux"}, modules={"malformed": 1}),  # /sd-modules malformed
        _gap_identity(options={"forge_preset": "flux"}, modules=[], flags=None),  # optional /cmd-flags unavailable (positive)
    ],
)
def test_every_missing_or_malformed_evidence_class_settles_to_a_real_positive(tmp_path: Path, gap_identity: Any) -> None:
    stack = Stack(tmp_path)
    probe = _install(stack, gap_identity, FORGE)

    stack.run_forge_stage()

    assert stack.dispatches == 1 and stack.attestor.attested_session() is not None
    assert probe.calls == (1 if gap_identity.is_forge else 2)


def test_the_first_unknown_is_still_rejected_when_no_positive_proof_ever_arrives(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    _install(stack, UNKNOWN)

    error = _reject(stack)

    assert stack.dispatches == 0 and stack.attestor.attested_session() is None
    assert stack.forge.last_identity_decision.source == SOURCE_NO_ATTESTATION  # a manager declaration never converts it
    assert "initial_identity_settle_timeout" in str(error)


# ---------------------------------------------------------------------------------------------------------------
# 2: the bound is enforced
# ---------------------------------------------------------------------------------------------------------------


def test_repeated_transient_unknown_exhausts_the_bound_and_rejects_before_generation(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    probe = _install(stack, UNKNOWN)

    _reject(stack)

    decision = stack.forge.last_identity_decision
    assert decision.settle.outcome == SETTLE_TIMEOUT
    assert sum(stack.clock.sleeps) == pytest.approx(INITIAL_IDENTITY_SETTLE_SECONDS)
    assert stack.clock.now - START == pytest.approx(INITIAL_IDENTITY_SETTLE_SECONDS)
    assert probe.calls == decision.settle.attempts == 1 + len(stack.clock.sleeps)
    assert decision.gap == "complete_endpoint_loss"
    assert stack.dispatches == 0


def test_the_bound_and_poll_are_independently_configurable_and_the_last_sleep_is_clamped(tmp_path: Path) -> None:
    stack = Stack(tmp_path, settle_seconds=1.2, poll_seconds=0.5)
    probe = _install(stack, UNKNOWN)

    _reject(stack)

    assert stack.clock.sleeps == pytest.approx([0.5, 0.5, 0.2])
    assert probe.calls == 4 and stack.dispatches == 0


def test_a_zero_bound_never_waits(tmp_path: Path) -> None:
    stack = Stack(tmp_path, settle_seconds=0.0)
    probe = _install(stack, UNKNOWN, FORGE)

    _reject(stack)

    assert probe.calls == 1 and stack.clock.sleeps == []


# ---------------------------------------------------------------------------------------------------------------
# 3: contradiction ends it at once
# ---------------------------------------------------------------------------------------------------------------


def test_a_positive_a1111_during_the_settle_aborts_immediately(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    probe = _install(stack, UNKNOWN, A1111, FORGE)

    _reject(stack)

    decision = stack.forge.last_identity_decision
    assert decision.source == SOURCE_CONTRADICTORY and decision.settle.outcome == SETTLE_CONTRADICTION
    assert probe.calls == 2 and len(stack.clock.sleeps) == 1, "no attempt after the contradiction"
    assert stack.dispatches == 0 and stack.attestor.attested_session() is None


@pytest.mark.parametrize(
    "contradiction",
    [
        _gap_identity(options={"forge_preset": "flux"}, modules=[], vae=[]),  # A1111-style /sd-vae list on a would-be Forge
        _gap_identity(options={"sd_model_checkpoint": "x"}),  # readable /options with no forge_* key
    ],
)
def test_contradicting_evidence_never_settles_at_all(tmp_path: Path, contradiction: WebUIRuntimeIdentity) -> None:
    stack = Stack(tmp_path)
    probe = _install(stack, contradiction, FORGE)

    _reject(stack)

    assert probe.calls == 1 and stack.clock.sleeps == []
    assert stack.forge.last_identity_decision.source == SOURCE_CONTRADICTORY and stack.dispatches == 0


def test_contradiction_arriving_after_a_gap_during_the_settle_also_aborts(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    probe = _install(stack, UNKNOWN, _gap_identity(options={"sd_model_checkpoint": "x"}), FORGE)

    _reject(stack)

    assert probe.calls == 2 and stack.forge.last_identity_decision.settle.outcome == SETTLE_CONTRADICTION


# ---------------------------------------------------------------------------------------------------------------
# 4-9: the session is re-validated before every attempt
# ---------------------------------------------------------------------------------------------------------------


def _restart(stack: Stack) -> None:
    stack.manager.restart(pid=4200)


def _epoch(stack: Stack) -> None:
    stack.manager.ready_epoch += 1


def _pid(stack: Stack) -> None:
    stack.manager.pid = 9999
    stack.manager.process.pid = 9999


def _ownership(stack: Stack) -> None:
    stack.manager.owns_process = False


def _stopped(stack: Stack) -> None:
    stack.manager._running = False


def _endpoint(stack: Stack) -> None:
    stack.manager.endpoint = "http://127.0.0.1:7999"
    stack.client.base_url = "http://127.0.0.1:7999"


def _manager_endpoint_only(stack: Stack) -> None:
    stack.manager.endpoint = "http://127.0.0.1:7999"


def _replace_manager(stack: Stack) -> None:
    replacement = FakeManager(pid=4100, epoch=1, endpoint=ENDPOINT)
    replacement.process = stack.manager.process  # superficially identical facts
    stack.manager = replacement


def _no_manager(stack: Stack) -> None:
    stack.manager = None


@pytest.mark.parametrize(
    "change",
    [_restart, _epoch, _pid, _ownership, _stopped, _endpoint, _manager_endpoint_only, _replace_manager, _no_manager],
    ids=lambda f: f.__name__.strip("_"),
)
def test_any_session_change_between_attempts_aborts_before_the_next_probe(tmp_path: Path, change: Any) -> None:
    stack = Stack(tmp_path)
    stack.clock.on_sleep = lambda n: change(stack) if n == 2 else None  # between attempt 2 and attempt 3
    probe = _install(stack, UNKNOWN, UNKNOWN, FORGE)

    _reject(stack)

    decision = stack.forge.last_identity_decision
    assert decision.settle.outcome == SETTLE_SESSION_CHANGED and decision.source == SOURCE_SESSION_CHANGED
    assert probe.calls == 2, "the changed session was never probed"
    assert stack.dispatches == 0 and stack.attestor.attested_session() is None


def test_a_session_change_during_a_probe_discards_even_a_positive_result(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    probe = _install(stack, UNKNOWN, FORGE, hook=lambda n: _restart(stack) if n == 2 else None)

    _reject(stack)

    assert stack.forge.last_identity_decision.settle.outcome == SETTLE_SESSION_CHANGED
    assert probe.calls == 2 and stack.dispatches == 0
    assert stack.attestor.attested_session() is None  # a probe that straddled a restart proves nothing


def test_a_restarted_session_gets_its_own_settle_and_never_reuses_the_old_proof(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()
    assert stack.attestor.attested_session().ready_epoch == 1

    _restart(stack)
    stack.clock.sleeps.clear()
    probe = _install(stack, UNKNOWN, UNKNOWN, FORGE)
    stack.run_forge_stage()

    decision = stack.forge.last_identity_decision
    assert decision.source == SOURCE_LIVE_POSITIVE and decision.settle.outcome == SETTLE_ESTABLISHED
    assert probe.calls == 3 and stack.dispatches == 2
    session = stack.attestor.attested_session()
    assert (session.pid, session.ready_epoch) == (4200, 2)


def test_a_restarted_session_whose_proof_never_arrives_is_rejected_as_session_changed(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    _restart(stack)
    _install(stack, UNKNOWN)
    _reject(stack)

    decision = stack.forge.last_identity_decision
    assert decision.source == SOURCE_SESSION_CHANGED and decision.settle.outcome == SETTLE_TIMEOUT
    assert stack.dispatches == 1 and stack.attestor.attested_session() is None


# ---------------------------------------------------------------------------------------------------------------
# 10 / 11: external runtimes and A1111 never settle
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("manager", [None, FakeManager(owned=False), FakeManager(running=False)])
def test_an_external_unknown_gets_zero_settle_retries(tmp_path: Path, manager: Any) -> None:
    stack = Stack(tmp_path, manager=manager)
    probe = _install(stack, UNKNOWN, FORGE)

    _reject(stack)

    assert probe.calls == 1 and stack.clock.sleeps == []
    assert stack.forge.last_identity_decision.settle is None and stack.dispatches == 0


def test_an_external_live_positive_still_passes_without_settling_or_attesting(tmp_path: Path) -> None:
    stack = Stack(tmp_path, manager=None)
    probe = _install(stack, FORGE)

    stack.run_forge_stage()

    assert probe.calls == 1 and stack.clock.sleeps == [] and stack.attestor.attested_session() is None


def test_a_manager_that_declares_a1111_gets_no_forge_settle(tmp_path: Path) -> None:
    stack = Stack(tmp_path, manager=FakeManager(identity=A1111_WEBUI_IDENTITY))
    probe = _install(stack, UNKNOWN, FORGE)

    _reject(stack)

    assert probe.calls == 1 and stack.clock.sleeps == []


def test_the_a1111_path_has_no_new_settle_behavior(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    probe = _install(stack, UNKNOWN)

    stack.run_a1111_stage()  # still tolerates an unclassifiable endpoint, exactly once, without waiting

    assert probe.calls == 1 and stack.clock.sleeps == [] and stack.dispatches == 1
    assert stack.a1111.last_identity_decision.settle is None

    _install(stack, FORGE)
    with pytest.raises(WebUIRuntimeIdentityMismatch):
        stack.run_a1111_stage()  # a positive Forge still blocks A1111


# ---------------------------------------------------------------------------------------------------------------
# 12: no settle once a session has an attestation
# ---------------------------------------------------------------------------------------------------------------


def test_after_establishment_a_transient_unknown_uses_the_attestation_and_is_not_repolled(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    _install(stack, UNKNOWN, FORGE)
    stack.run_forge_stage()
    sleeps_after_establishment = list(stack.clock.sleeps)

    probe = _install(stack, UNKNOWN)
    stack.run_forge_stage()

    decision = stack.forge.last_identity_decision
    assert decision.source == SOURCE_SAME_SESSION and decision.settle is None
    assert probe.calls == 1 and stack.clock.sleeps == sleeps_after_establishment


# ---------------------------------------------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------------------------------------------


def test_the_settle_is_logged_with_attempts_elapsed_and_gap_without_payloads(tmp_path: Path, caplog) -> None:
    stack = Stack(tmp_path)
    _install(stack, _gap_identity(modules=[]), UNKNOWN, FORGE)

    with caplog.at_level(logging.INFO, logger="src.api.webui_identity_attestation"):
        stack.run_forge_stage()

    text = caplog.text
    assert "initial_identity_settle begin" in text
    assert "initial_identity_settle=initial_identity_established attempts=3 elapsed=1.00s" in text
    assert "last_gap=None" in text and "pid=4100" in text


def test_a_rejection_message_reports_the_settle_outcome_attempts_and_latest_gap(tmp_path: Path) -> None:
    stack = Stack(tmp_path, settle_seconds=1.0)
    _install(stack, _gap_identity(modules=[]))

    text = str(_reject(stack))

    assert "initial_identity_settle=initial_identity_settle_timeout" in text
    assert "attempts=3" in text and "last_gap=options_unavailable" in text
    assert "source=no_valid_attestation" in text


def test_a_probe_that_raises_is_just_another_unavailable_attempt(tmp_path: Path) -> None:
    stack = Stack(tmp_path)
    calls = {"n": 0}

    def flaky() -> WebUIRuntimeIdentity:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("endpoint warming up")
        return FORGE

    stack.client = SimpleNamespace(**{**vars(stack.client), "probe_runtime_identity": flaky})
    stack.pipeline.client = stack.client

    stack.run_forge_stage()

    assert calls["n"] == 3 and stack.attestor.attested_session() is not None
