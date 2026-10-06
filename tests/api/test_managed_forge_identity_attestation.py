"""PR-RUNTIME-FORGE-IDENTITY-150: same-session attestation of a StableNew-owned managed Forge (deterministic, no I/O).

A real positive Forge classification of the exact owned runtime session may be reused across a later transient
``unknown`` probe, and only then. Everything else stays fail-closed: a never-proven session, a changed
session (readiness epoch, PID, endpoint, manager, ownership, liveness), a positive A1111 / conflicting signature,
and every external endpoint. No generation POST may follow a rejection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.api.webui_identity_attestation import (
    SOURCE_CONTRADICTORY,
    SOURCE_LIVE_POSITIVE,
    SOURCE_NO_ATTESTATION,
    SOURCE_SAME_SESSION,
    SOURCE_SESSION_CHANGED,
    ManagedWebUIIdentityAttestor,
    identity_gap,
)
from src.api.webui_runtime_identity import (
    A1111_WEBUI_IDENTITY,
    FORGE_WEBUI_IDENTITY,
    UNKNOWN_RUNTIME_IDENTITY,
    WebUIRuntimeIdentity,
    WebUIRuntimeIdentityMismatch,
    classify_runtime_identity,
)
from src.image_backends import (
    A1111WebUIImageBackend,
    ForgeWebUIImageBackend,
    ImageBackendRegistry,
    ImageExecutionRequest,
)
from src.pipeline.pipeline_runner import PipelineRunner
from tests.helpers.njr_factory import make_pipeline_njr

ENDPOINT = "http://127.0.0.1:7871"
FORGE = WebUIRuntimeIdentity(FORGE_WEBUI_IDENTITY, {"options_readable": True})
A1111 = WebUIRuntimeIdentity(A1111_WEBUI_IDENTITY, {"options_readable": True})
UNKNOWN = UNKNOWN_RUNTIME_IDENTITY


class FakeManager:
    """The authoritative WebUIProcessManager's session facts (ownership, liveness, PID, endpoint, epoch)."""

    def __init__(
        self,
        *,
        identity: str = FORGE_WEBUI_IDENTITY,
        owned: bool = True,
        running: bool = True,
        pid: int = 4100,
        epoch: int = 1,
        endpoint: str = ENDPOINT,
    ) -> None:
        self.runtime_identity = identity
        self.owns_process = owned
        self._running = running
        self.pid = pid
        self.ready_epoch = epoch
        self.endpoint = endpoint
        self.process = SimpleNamespace(pid=pid)
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self._running

    def restart(self, *, pid: int) -> None:
        """An owned restart: a new process and a new proven-readiness epoch."""
        self.pid = pid
        self.process = SimpleNamespace(pid=pid)
        self.ready_epoch += 1

    def stop_webui(self) -> bool:  # must never be reached by identity logic
        self.stop_calls += 1
        return True


class Probe:
    """Scripted identity probes; the last scripted observation repeats."""

    def __init__(self, *script: WebUIRuntimeIdentity) -> None:
        self.script = list(script)
        self.calls = 0

    def __call__(self) -> WebUIRuntimeIdentity:
        self.calls += 1
        index = min(self.calls - 1, len(self.script) - 1)
        return self.script[index]

    def then(self, *script: WebUIRuntimeIdentity) -> None:
        self.script = list(script)
        self.calls = 0


class Stack:
    """One owned manager, one client and one pipeline: the production shape, with a recording pipeline."""

    def __init__(self, tmp_path: Path, *probe_script: WebUIRuntimeIdentity, manager: Any = "default") -> None:
        self.manager = FakeManager() if manager == "default" else manager
        self.probe = Probe(*probe_script)
        self.attestor = ManagedWebUIIdentityAttestor(manager_getter=lambda: self.manager)
        transition = Mock()
        transition.prepare_for.return_value = Mock(ready=True)
        self.forge = ForgeWebUIImageBackend(transition=transition, identity_attestor=self.attestor)
        self.a1111 = A1111WebUIImageBackend(transition=transition, identity_attestor=self.attestor)
        self.modules: list[str] = []
        self.client = SimpleNamespace(
            base_url=ENDPOINT,
            probe_runtime_identity=self.probe,
            get_additional_modules=lambda: list(self.modules),
            set_additional_modules=lambda selection: True,
        )
        self.pipeline = Mock()
        output = tmp_path / "txt2img.png"
        output.write_bytes(b"png")
        self.pipeline.run_txt2img_stage.return_value = {"path": str(output), "all_paths": [str(output)]}
        self.pipeline.client = self.client
        self.tmp_path = tmp_path

    def request(self, backend_id: str = FORGE_WEBUI_IDENTITY) -> ImageExecutionRequest:
        return ImageExecutionRequest(
            backend_id=backend_id,
            stage_name="txt2img",
            stage_config={},
            output_dir=self.tmp_path,
            image_name="x",
            prompt="p",
        )

    def run_forge_stage(self) -> Any:
        return self.forge.execute(self.pipeline, self.request())

    def run_a1111_stage(self) -> Any:
        return self.a1111.execute(self.pipeline, self.request(A1111_WEBUI_IDENTITY))

    @property
    def dispatches(self) -> int:
        return self.pipeline.run_txt2img_stage.call_count

    def assert_rejected_without_dispatch(self, before: int) -> None:
        with pytest.raises(WebUIRuntimeIdentityMismatch):
            self.run_forge_stage()
        assert self.dispatches == before, "a rejected identity must never reach a generation dispatch"


# ---------------------------------------------------------------------------------------------------------------
# A / B: establishment and first proof
# ---------------------------------------------------------------------------------------------------------------


def test_a_positive_probe_then_a_transient_unknown_runs_on_the_same_owned_session(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE, UNKNOWN)

    stack.run_forge_stage()
    stack.run_forge_stage()  # pre-fix: WebUIRuntimeIdentityMismatch ("classified 'unknown'")

    assert stack.dispatches == 2
    assert stack.probe.calls == 2  # the live probe is still taken every stage; the attestation only relaxes unknown
    assert stack.forge.last_identity_decision.source == SOURCE_SAME_SESSION


def test_the_first_probe_unknown_rejects_even_for_a_declared_owned_forge(tmp_path: Path) -> None:
    stack = Stack(tmp_path, UNKNOWN)

    stack.assert_rejected_without_dispatch(0)

    assert stack.forge.last_identity_decision.source == SOURCE_NO_ATTESTATION
    assert stack.attestor.attested_session() is None  # manager declaration / ownership / port never prove identity


def test_a_positive_probe_creates_the_attestation_and_a_live_positive_is_recorded_as_such(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)

    stack.run_forge_stage()

    assert stack.forge.last_identity_decision.source == SOURCE_LIVE_POSITIVE
    session = stack.attestor.attested_session()
    assert session is not None
    assert (session.pid, session.ready_epoch, session.endpoint) == (4100, 1, ENDPOINT)
    assert session.declared_identity == FORGE_WEBUI_IDENTITY


def test_a_manager_that_declares_a1111_never_attests_a_positive_forge_endpoint(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE, UNKNOWN, manager=FakeManager(identity=A1111_WEBUI_IDENTITY))

    stack.run_forge_stage()  # the live positive path keeps working exactly as before
    assert stack.attestor.attested_session() is None
    stack.assert_rejected_without_dispatch(1)


def test_attestation_requires_the_session_to_be_stable_across_the_probe(tmp_path: Path) -> None:
    """A probe that straddles a restart proves nothing about either session."""

    stack = Stack(tmp_path)

    def straddling_probe() -> WebUIRuntimeIdentity:
        stack.manager.restart(pid=4200)
        return FORGE

    stack.client.probe_runtime_identity = straddling_probe
    stack.run_forge_stage()  # live positive still admits this stage ...
    assert stack.attestor.attested_session() is None  # ... but cannot become evidence for either session
    stack.client.probe_runtime_identity = stack.probe
    stack.probe.then(UNKNOWN)
    stack.assert_rejected_without_dispatch(1)


# ---------------------------------------------------------------------------------------------------------------
# C / E / F / G: every session fact invalidates old proof
# ---------------------------------------------------------------------------------------------------------------


def test_a_restart_invalidates_the_attestation_until_a_fresh_positive_proof(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()
    assert stack.attestor.attested_session().ready_epoch == 1

    stack.manager.restart(pid=4200)  # epoch 2, new PID
    stack.probe.then(UNKNOWN)
    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_SESSION_CHANGED
    assert stack.attestor.attested_session() is None

    stack.probe.then(FORGE)  # a fresh real proof in epoch 2
    stack.run_forge_stage()
    assert stack.attestor.attested_session().ready_epoch == 2
    stack.probe.then(UNKNOWN)
    stack.run_forge_stage()  # and the new session now carries its own attestation
    assert stack.forge.last_identity_decision.source == SOURCE_SAME_SESSION


def test_a_new_readiness_epoch_alone_invalidates_the_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager.ready_epoch += 1  # same PID, same endpoint: only the proven-readiness epoch moved
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_SESSION_CHANGED


def test_a_pid_change_alone_invalidates_the_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager.pid = 9999
    stack.manager.process = SimpleNamespace(pid=9999)
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_SESSION_CHANGED


def test_a_pid_reported_differently_for_the_same_process_object_invalidates_the_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager.pid = 9999
    stack.manager.process.pid = 9999  # one process object, a different PID: still not the attested launch
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)


def test_the_same_pid_in_a_new_process_object_invalidates_the_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager.process = SimpleNamespace(pid=stack.manager.pid)  # PID reuse must not look like the same launch
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)


def test_an_endpoint_change_invalidates_the_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    other = "http://127.0.0.1:7999"
    stack.manager.endpoint = other
    stack.client.base_url = other
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_SESSION_CHANGED


def test_a_client_bound_to_a_different_endpoint_than_the_manager_is_not_the_attested_session(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.client.base_url = "http://127.0.0.1:7860"  # the manager still serves 7871
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)


@pytest.mark.parametrize("trailing", ["", "/"])
def test_endpoint_comparison_ignores_only_a_trailing_slash(tmp_path: Path, trailing: str) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.client.base_url = ENDPOINT + trailing
    stack.probe.then(UNKNOWN)

    stack.run_forge_stage()
    assert stack.forge.last_identity_decision.source == SOURCE_SAME_SESSION


def test_losing_ownership_invalidates_the_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager.owns_process = False
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_SESSION_CHANGED
    stack.manager.owns_process = True  # ownership coming back never resurrects dropped proof
    stack.assert_rejected_without_dispatch(1)


def test_a_process_that_is_no_longer_running_invalidates_the_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager._running = False
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)
    stack.manager._running = True
    stack.assert_rejected_without_dispatch(1)


def test_a_replacement_manager_with_matching_numbers_is_not_the_attested_session(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()
    old_process = stack.manager.process

    replacement = FakeManager(pid=4100, epoch=1, endpoint=ENDPOINT)  # superficially identical facts
    replacement.process = old_process
    stack.manager = replacement
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_SESSION_CHANGED


def test_no_manager_at_all_never_reuses_an_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager = None
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)


def test_a_manager_that_raises_while_reporting_facts_fails_closed(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()
    stack.manager.is_running = Mock(side_effect=RuntimeError("manager broke"))
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)


# ---------------------------------------------------------------------------------------------------------------
# D: contradiction always wins
# ---------------------------------------------------------------------------------------------------------------


def test_a_positive_a1111_probe_rejects_and_invalidates_the_forge_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.probe.then(A1111)
    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_CONTRADICTORY
    assert stack.attestor.attested_session() is None

    stack.probe.then(UNKNOWN)  # a following unknown cannot resurrect the dropped proof
    stack.assert_rejected_without_dispatch(1)
    assert stack.forge.last_identity_decision.source == SOURCE_NO_ATTESTATION


@pytest.mark.parametrize(
    ("evidence", "gap"),
    [
        ({"options_readable": True, "forge_option_keys": ["forge_preset"], "sd_modules_list": True, "sd_vae_list": True,
          "any_forge_option": True}, "conflicting_sd_vae"),
        ({"options_readable": True, "forge_option_keys": [], "sd_modules_list": False, "sd_vae_list": False,
          "any_forge_option": False}, "options_without_forge_keys"),
    ],
)
def test_an_unknown_probe_carrying_contradictory_evidence_is_not_a_transient_gap(
    tmp_path: Path, evidence: dict, gap: str
) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.probe.then(WebUIRuntimeIdentity(evidence=evidence))
    stack.assert_rejected_without_dispatch(1)

    assert stack.forge.last_identity_decision.source == SOURCE_CONTRADICTORY
    assert stack.forge.last_identity_decision.gap == gap
    assert stack.attestor.attested_session() is None


# ---------------------------------------------------------------------------------------------------------------
# H: external / unowned endpoints stay strict
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("manager", [None, FakeManager(owned=False), FakeManager(running=False)])
def test_an_external_endpoint_passes_only_on_a_live_positive_probe(tmp_path: Path, manager: Any) -> None:
    stack = Stack(tmp_path, FORGE, manager=manager)
    stack.run_forge_stage()  # existing policy: current live Forge proof is permitted
    assert stack.forge.last_identity_decision.source == SOURCE_LIVE_POSITIVE
    assert stack.attestor.attested_session() is None  # but an unowned endpoint is never attested

    stack.probe.then(UNKNOWN)
    stack.assert_rejected_without_dispatch(1)  # no carry-forward for something StableNew does not own
    stack.probe.then(A1111)
    stack.assert_rejected_without_dispatch(1)


def test_an_external_unknown_stays_rejected_even_after_an_owned_session_was_attested(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.manager = None  # the owned process is gone; whatever answers on the endpoint is not StableNew's
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(1)


def test_identity_logic_never_touches_process_lifecycle(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE, UNKNOWN)
    stack.run_forge_stage()
    stack.run_forge_stage()
    stack.manager.owns_process = False
    stack.assert_rejected_without_dispatch(2)

    assert stack.manager.stop_calls == 0


# ---------------------------------------------------------------------------------------------------------------
# A1111 semantics unchanged
# ---------------------------------------------------------------------------------------------------------------


def test_a1111_keeps_tolerating_an_unclassifiable_endpoint_and_blocking_a_positive_forge(tmp_path: Path) -> None:
    stack = Stack(tmp_path, UNKNOWN, manager=FakeManager(identity=A1111_WEBUI_IDENTITY))
    stack.run_a1111_stage()
    assert stack.dispatches == 1

    stack.probe.then(A1111)
    stack.run_a1111_stage()
    assert stack.dispatches == 2

    stack.probe.then(FORGE)
    with pytest.raises(WebUIRuntimeIdentityMismatch):
        stack.run_a1111_stage()
    assert stack.dispatches == 2


def test_an_a1111_stage_that_observes_a_positive_a1111_drops_a_forge_attestation(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    stack.run_forge_stage()

    stack.probe.then(A1111)
    stack.run_a1111_stage()
    stack.probe.then(UNKNOWN)

    stack.assert_rejected_without_dispatch(2)


# ---------------------------------------------------------------------------------------------------------------
# I: the production multi-stage shape through PipelineRunner
# ---------------------------------------------------------------------------------------------------------------


def _forge_njr():
    return make_pipeline_njr(backend_options={"image": {"backend_id": "forge_webui"}})


def _runner(stack: Stack, tmp_path: Path) -> PipelineRunner:
    registry = ImageBackendRegistry()
    registry.register(stack.a1111)
    registry.register(stack.forge)
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "out"), image_backend_registry=registry)
    runner._pipeline = stack.pipeline
    return runner


def test_two_jobs_on_one_pipeline_client_and_session_survive_a_transient_unknown(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE, UNKNOWN)
    runner = _runner(stack, tmp_path)

    first = runner.run_njr(_forge_njr())
    second = runner.run_njr(_forge_njr())

    assert first.success is True and second.success is True
    assert stack.dispatches == 2


def test_a_job_after_a_restart_with_an_unknown_probe_fails_before_any_dispatch(tmp_path: Path) -> None:
    stack = Stack(tmp_path, FORGE)
    runner = _runner(stack, tmp_path)
    assert runner.run_njr(_forge_njr()).success is True

    stack.manager.restart(pid=4300)
    stack.probe.then(UNKNOWN)
    result = runner.run_njr(_forge_njr())

    assert result.success is False
    assert "WebUI runtime identity mismatch" in str(result.error)
    assert stack.dispatches == 1


# ---------------------------------------------------------------------------------------------------------------
# The real WebUIProcessManager supplies the session facts (guards the FakeManager's attribute contract)
# ---------------------------------------------------------------------------------------------------------------


class _LivePopen:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.alive = True

    def poll(self) -> int | None:
        return None if self.alive else 1


def _real_owned_manager(monkeypatch: pytest.MonkeyPatch, *, pid: int = 5150) -> Any:
    import src.api.webui_process_manager as manager_module

    monkeypatch.setattr(manager_module, "_GLOBAL_WEBUI_PROCESS_MANAGER", None)  # restored on teardown
    manager = manager_module.WebUIProcessManager(
        manager_module.WebUIProcessConfig(command=["launch"], base_url=ENDPOINT, runtime_identity=FORGE_WEBUI_IDENTITY)
    )
    manager._process = _LivePopen(pid)
    manager._pid = pid
    manager._owns_process = True
    manager.mark_ready(source="startup")
    return manager


def test_the_real_manager_provides_every_session_fact_and_an_owned_restart_ends_the_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _real_owned_manager(monkeypatch)
    stack = Stack(tmp_path, FORGE, manager=manager)

    stack.run_forge_stage()
    session = stack.attestor.attested_session()
    assert (session.pid, session.ready_epoch, session.endpoint) == (5150, 1, ENDPOINT)

    stack.probe.then(UNKNOWN)
    stack.run_forge_stage()
    assert stack.forge.last_identity_decision.source == SOURCE_SAME_SESSION

    manager._process = _LivePopen(5151)  # an owned restart: new process, TRUE-READY publishes the next epoch
    manager._pid = 5151
    manager.mark_ready(source="restart")
    stack.assert_rejected_without_dispatch(2)
    assert stack.forge.last_identity_decision.source == SOURCE_SESSION_CHANGED


def test_a_real_manager_that_does_not_own_a_live_process_never_attests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _real_owned_manager(monkeypatch)
    manager._owns_process = False  # an external endpoint: the manager exists but never launched the process
    stack = Stack(tmp_path, UNKNOWN, manager=manager)

    stack.assert_rejected_without_dispatch(0)
    stack.probe.then(FORGE)
    stack.run_forge_stage()
    assert stack.attestor.attested_session() is None


# ---------------------------------------------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------------------------------------------


def _classify(*, options: Any = None, modules: Any = None, vae: Any = None, flags: Any = None) -> WebUIRuntimeIdentity:
    return classify_runtime_identity(flags, modules, vae, options=options)


@pytest.mark.parametrize(
    ("observed", "gap"),
    [
        (UNKNOWN_RUNTIME_IDENTITY, "complete_endpoint_loss"),
        (_classify(modules=[]), "options_unavailable"),
        (_classify(options=["not", "a", "mapping"], modules=[]), "options_malformed"),
        (_classify(options={"forge_preset": "flux"}), "sd_modules_unavailable"),
        (_classify(options={"forge_preset": "flux"}, modules={"not": "a list"}), "sd_modules_malformed"),
        (_classify(options={"forge_preset": "flux"}, modules=[], vae=[]), "conflicting_sd_vae"),
        (_classify(options={"sd_model_checkpoint": "x"}), "options_without_forge_keys"),
        (_classify(options={"forge_preset": "flux"}, modules=[]), None),  # positive Forge: no gap
        (_classify(options={"sd_model_checkpoint": "x"}, vae=[]), None),  # positive A1111: no gap
    ],
)
def test_the_evidence_distinguishes_which_component_was_unavailable_or_contradictory(
    observed: WebUIRuntimeIdentity, gap: str | None
) -> None:
    assert identity_gap(observed) == gap


def test_classification_evidence_reports_per_endpoint_state_without_raw_payloads() -> None:
    observed = _classify(options={"forge_preset": "flux", "secret_token": "s3cr3t"}, modules=[], vae="garbled")

    assert observed.evidence["endpoint_state"] == {
        "cmd_flags": "unavailable", "options": "ok", "sd_modules": "ok", "sd_vae": "malformed",
    }
    assert "s3cr3t" not in repr(dict(observed.evidence))


def test_the_decision_carries_the_session_gap_and_source_for_a_rejection(tmp_path: Path) -> None:
    stack = Stack(tmp_path, WebUIRuntimeIdentity(evidence=_classify(modules=[]).evidence))

    with pytest.raises(WebUIRuntimeIdentityMismatch) as excinfo:
        stack.run_forge_stage()

    assert stack.forge.last_identity_decision.gap == "options_unavailable"
    assert "options_unavailable" in str(excinfo.value)
    assert SOURCE_NO_ATTESTATION in str(excinfo.value)


def test_reusing_the_attestation_is_logged_with_the_session_and_gap(tmp_path: Path, caplog) -> None:
    stack = Stack(tmp_path, FORGE, UNKNOWN)
    stack.run_forge_stage()

    with caplog.at_level(logging.INFO, logger="src.api.webui_identity_attestation"):
        stack.run_forge_stage()

    text = caplog.text
    assert SOURCE_SAME_SESSION in text and "pid=4100" in text and "epoch=1" in text and "complete_endpoint_loss" in text
