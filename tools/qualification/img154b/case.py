"""D8 (154B): the one-case coordinator, written against ports so every path is exercised with fakes.

It performs NO real I/O of its own: a runtime, an HTTP client, a sampler factory, fault snapshots and the operator prompt are
injected. Nothing here can build those real ports; only ``physical`` (disabled by default) can, and only after it mints a
``physical`` execution authority. A coordinator run with the ``synthetic`` authority can never produce
``TECHNICAL_PASS_CONSTRAINED``.

Order of one case (each ``*_attempted`` record and ``generation_dispatched`` is made durable BEFORE its action)::

    gates -> operator confirmation + owner passphrase -> fresh re-measure (baseline, fault snapshot, resources) ->
    sampler proven healthy -> claim -> managed_start_attempted -> start -> boot-window ownership + readiness ->
    endpoint ownership -> startup_observed -> option defaults -> selection_attempted -> selection (supervised) ->
    selection_confirmed -> pre-dispatch gates -> generation_dispatched -> ONE POST (supervised) -> owned shutdown ->
    settle -> fault snapshot -> adjudication -> terminal_evidence + outcome

There is no loop around the POST, no retry, no second request and no re-claim.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from tools.qualification.img154.core import Finding, Observation, valid_time
from tools.qualification.img154.evidence import (
    FAULT_SETTLE_S,
    FAULT_SOURCES,
    NO_NEW_EVENTS_COMPLETE_COVERAGE,
    UNKNOWN_COVERAGE_GAP,
    DurableJsonlWriter,
    FaultSnapshot,
    classify_faults,
    coverage_summary,
    read_jsonl,
)
from tools.qualification.img154.manifest import QualificationManifest, build_manifest
from tools.qualification.img154.monitor import (
    CANNOT_VERIFY_SAFE_STATE,
    HARNESS_FAULT,
    NONE,
    REQUEST_OWNER_STOP,
    WARN,
    MonitorConfig,
    SafetyMonitor,
)
from tools.qualification.img154.preflight import (
    PREPARED,
    PreflightInputs,
    PreflightPolicy,
    PreflightResult,
    QuiescentBaselineEvidence,
    ValidatedBaseline,
    evaluate_preflight,
    validate_quiescent_baseline,
)
from tools.qualification.img154b.adjudication import (
    AUTHORITY_PHYSICAL,
    AUTHORITY_SYNTHETIC,
    CaseFacts,
    CaseResult,
    ResponseValidation,
    classify_case,
    evaluate_telemetry_coverage,
    validate_response,
)
from tools.qualification.img154b.authorization import (
    CodeRevision,
    OwnerAuthorization,
    confirmation_phrase,
    verify_authorization,
    verify_passphrase,
)
from tools.qualification.img154b.bundle import BundleError, EvidenceBundle
from tools.qualification.img154b.fence import CaseFence, FenceRefusal
from tools.qualification.img154b.request import (
    OPTIONS_ENDPOINT,
    PROGRESS_ENDPOINT,
    TXT2IMG_ENDPOINT,
    FrozenPayload,
    selection_payload,
    verify_payload,
    verify_sampling_options,
    verify_selection,
)
from tools.qualification.img154b.runtime import (
    RECOVERY_INSTRUCTIONS,
    OwnershipFacts,
    ShutdownResult,
)
from tools.qualification.img154b.sampler import StageInfo

# --------------------------------------------------------------------------------------------------------- authority


class AuthorityError(RuntimeError):
    """A physical execution authority was requested without the physical activation path."""


_PHYSICAL_KEY = object()


@dataclass(frozen=True)
class ExecutionAuthority:
    """``synthetic`` (fakes, tests, dry runs) or ``owner_authorized_physical`` (only ``physical`` can mint it)."""

    kind: str
    record_digest: str | None = None
    _key: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.kind not in (AUTHORITY_SYNTHETIC, AUTHORITY_PHYSICAL):
            raise AuthorityError("unknown authority kind")
        if self.kind == AUTHORITY_PHYSICAL and self._key is not _PHYSICAL_KEY:
            raise AuthorityError(
                "physical authority can only be minted by the gated physical activation path"
            )

    @classmethod
    def synthetic(cls) -> ExecutionAuthority:
        return cls(AUTHORITY_SYNTHETIC)


def mint_physical_authority(record_digest: str) -> ExecutionAuthority:
    """Called by ``physical`` after every activation gate has passed. No other module may call it (a test enforces this)."""

    return ExecutionAuthority(AUTHORITY_PHYSICAL, record_digest, _PHYSICAL_KEY)


# ------------------------------------------------------------------------------------------------------------ ports


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    body: object | None = None
    error: str | None = None
    elapsed_s: float = 0.0


class HttpPort(Protocol):
    def get_json(self, path: str, *, timeout_s: float = 10.0) -> HttpResult: ...

    def post_json(self, path: str, body: bytes, *, timeout_s: float) -> HttpResult: ...


class RuntimePort(Protocol):
    def start(self) -> Mapping[str, Any]: ...

    def verify_ownership(self, *, require_listener: bool = True) -> OwnershipFacts: ...

    def stop(self) -> ShutdownResult: ...

    def output_tail(self) -> Mapping[str, Any]: ...


class SamplerPort(Protocol):
    halt_event: threading.Event
    halt: Any
    harness_fault: str | None
    provenance: dict[str, str]
    #: number of samples evaluated by the monitor so far (a fresh sample is evidence the sampler is delivering)
    sample_count: int
    #: consecutive samples with every essential field ok and no latched stop or uncertainty
    clean_streak: int

    def start(self) -> None: ...

    def stop(self, timeout_s: float = 5.0) -> None: ...

    def watchdog_tick(self) -> None: ...

    def write_header(self, **facts: Any) -> None: ...


@dataclass(frozen=True)
class ClockPort:
    mono: Callable[[], float] = time.monotonic
    utc: Callable[[], str] = lambda: datetime.now(UTC).isoformat()
    sleep: Callable[[float], None] = time.sleep


@dataclass
class Collected:
    """Everything a live preflight gathers (the live collector reads the host; a fake supplies crafted values)."""

    inputs: PreflightInputs
    code: CodeRevision
    fault_before: FaultSnapshot | None = None
    boot_id: str | None = None
    device_id: str | None = None
    workspace_ledger_state: str = "none"
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Remeasured:
    """What is taken again after the operator's (unbounded) confirmation and immediately before the claim."""

    observations: Mapping[str, Observation]
    quiescent_baseline: QuiescentBaselineEvidence | None = None
    fault_before: FaultSnapshot | None = None
    sections: Mapping[str, list[Finding] | None] = field(default_factory=dict)
    runtime_observed_mono_s: float | None = None


class PreflightCollector(Protocol):
    def collect(self) -> Collected: ...

    def remeasure(self) -> Remeasured: ...

    def recheck_served(self) -> list[Finding]: ...

    def recheck_code(self) -> CodeRevision: ...

    def recheck_runtime(self) -> tuple[float, Mapping[str, list[Finding] | None]]: ...


SamplerFactory = Callable[
    [SafetyMonitor, DurableJsonlWriter, Callable[[], StageInfo], Callable[[], str]], SamplerPort
]


@dataclass(frozen=True)
class CaseConfig:
    ready_timeout_s: float = 300.0
    options_timeout_s: float = 600.0
    generation_timeout_s: float = 1800.0
    supervision_interval_s: float = 1.0
    settle_s: float = FAULT_SETTLE_S
    abort_join_s: float = 30.0
    preflight_max_age_s: float = 30.0


@dataclass
class CasePorts:
    collector: PreflightCollector
    fence: CaseFence
    runtime: RuntimePort
    http: HttpPort
    sampler_factory: SamplerFactory
    faults: Callable[[], FaultSnapshot | None]
    confirm: Callable[[Mapping[str, Any]], str]
    #: the owner's passphrase, read without echo (compared with the record's salted verifier)
    passphrase: Callable[[], str]
    clock: ClockPort
    bundle: EvidenceBundle
    sample_path: Path
    served_paths: Mapping[str, str]
    #: confirms byte and file identity continuity of the originally approved owner record; unwired refuses
    authorization_current: Callable[[OwnerAuthorization], bool] | None = None


@dataclass
class CaseReport:
    result: CaseResult
    executed: bool
    claimed: bool
    stages: tuple[str, ...] = ()
    refusals: tuple[str, ...] = ()
    preflight: dict[str, Any] | None = None
    shutdown: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    telemetry: dict[str, Any] | None = None
    faults: dict[str, Any] | None = None
    halt: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    recovery_instructions: tuple[str, ...] = ()
    exception: str | None = None
    requests: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.as_dict(),
            "executed": self.executed,
            "claimed": self.claimed,
            "stages": list(self.stages),
            "refusals": list(self.refusals),
            "preflight": self.preflight,
            "shutdown": self.shutdown,
            "output": self.output,
            "telemetry": self.telemetry,
            "faults": self.faults,
            "halt": self.halt,
            "evidence": self.evidence,
            "recovery_instructions": list(self.recovery_instructions),
            "exception": self.exception,
            "requests": list(self.requests),
        }


# ----------------------------------------------------------------------------------------------------------- stages


def stage_from_progress(progress: object) -> StageInfo:
    """The only phase attribution this package makes from the runtime: the sampling loop is demonstrably running.

    ``state.sampling_steps`` is set when the sampler launches and ``state.sampling_step`` is written by its callback (both
    are anchored to the pinned source). While at least one further callback must still occur the loop is running, so the
    stage is ``denoise``. At the last step the final denoise iteration and the VAE decode are indistinguishable, so the stage is
    ``unknown`` there and everywhere else: encoder load, transformer load and VAE decode have no verified signal.
    """

    if not isinstance(progress, Mapping):
        return StageInfo()
    state = progress.get("state")
    if not isinstance(state, Mapping):
        return StageInfo()
    steps, step, jobs = (
        state.get("sampling_steps"),
        state.get("sampling_step"),
        state.get("job_count"),
    )
    if (
        isinstance(steps, bool)
        or isinstance(step, bool)
        or isinstance(jobs, bool)
        or not isinstance(steps, int)
        or not isinstance(step, int)
        or not isinstance(jobs, int)
    ):
        return StageInfo()
    if jobs > 0 and steps > 1 and 0 <= step < steps - 1:
        return StageInfo("denoise", "forge_api")
    return StageInfo()


# ------------------------------------------------------------------------------------------------------ coordinator


@dataclass
class _Run:
    """Mutable facts of one run (kept apart from the report so classification reads one place)."""

    stage: StageInfo = field(default_factory=lambda: StageInfo("preflight", "operator"))
    claimed: bool = False
    startup_observed: bool = False
    selection_confirmed: bool = False
    dispatched: bool = False
    response: HttpResult | None = None
    validation: ResponseValidation | None = None
    loader_failed: bool = False
    exception: str | None = None
    shutdown: ShutdownResult | None = None
    ownership: OwnershipFacts | None = None
    phases: list[dict[str, Any]] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    started_mono: float | None = None
    ended_mono: float | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)


class CaseCoordinator:
    def __init__(
        self,
        ports: CasePorts,
        *,
        manifest: QualificationManifest | None = None,
        payload: FrozenPayload,
        config: CaseConfig | None = None,
        policy: PreflightPolicy | None = None,
        monitor_config: MonitorConfig | None = None,
    ) -> None:
        self.ports = ports
        self.manifest = manifest or build_manifest()
        self.payload = payload
        self.config = config or CaseConfig()
        self.policy = policy or PreflightPolicy()
        self._monitor_config = monitor_config
        self._run = _Run()
        self._endpoint_state = "not_started"
        self._authority_kind = AUTHORITY_SYNTHETIC
        self._request_writer = DurableJsonlWriter(
            ports.sample_path.with_name("requests.jsonl"), redact=False, rotate=False
        )

    # ---------------------------------------------------------------------------------------------- helpers
    def _mark(self, stage: str, source: str, **facts: Any) -> None:
        self._run.stage = StageInfo(stage, source)
        self._run.phases.append(
            {
                "kind": "phase",
                "stage": stage,
                "source": source,
                "mono_s": self.ports.clock.mono(),
                "utc": self.ports.clock.utc(),
                **facts,
            }
        )

    def _refuse(self, *codes: str) -> None:
        self._run.refusals.extend(code for code in codes if code not in self._run.refusals)

    def _report(self, result: CaseResult, **kw: Any) -> CaseReport:
        return CaseReport(
            result=result,
            executed=self._run.dispatched,
            claimed=self._run.claimed,
            refusals=tuple(self._run.refusals),
            **kw,
        )

    # --------------------------------------------------------------------------------------------- the case
    def run(
        self, authority: ExecutionAuthority, authorization: OwnerAuthorization | None
    ) -> CaseReport:
        clock = self.ports.clock
        self._authority_kind = authority.kind
        collected = self.ports.collector.collect()
        gates = self._gate_findings(authority, authorization, collected)
        inputs = replace(
            collected.inputs,
            manifest_digest=self.manifest.digest(),
            residual_gpu_risk_accepted=True if not gates else None,
            ledger_state=self._merged_ledger_state(collected),
        )
        decision = evaluate_preflight(
            inputs,
            now_mono_s=clock.mono(),
            now_utc=clock.utc(),
            policy=self.policy,
            manifest=self.manifest,
        )
        summary = self._preflight_summary(decision, gates)
        if gates or decision.decision != PREPARED:
            self._refuse(*[g.code for g in gates], decision.decision, *decision.reason_codes)
            return self._finish_unclaimed(summary)

        expected = confirmation_phrase(self.manifest, self.payload)
        typed = self.ports.confirm(self._case_summary(collected))
        if typed != expected:
            self._refuse("OPERATOR_CONFIRMATION_MISMATCH")
            return self._finish_unclaimed(summary)

        # the secret only the owner holds; the record stores a salted verifier, never the passphrase
        if authorization is None or not verify_passphrase(authorization, self.ports.passphrase()):
            self._refuse("OWNER_PASSPHRASE_MISMATCH")
            return self._finish_unclaimed(summary)

        try:
            fresh = self.ports.collector.remeasure()
        except Exception as exc:  # noqa: BLE001 - no claim or runtime action on inaccessible final observations
            self._refuse(f"FINAL_REMEASURE_UNAVAILABLE:{type(exc).__name__}")
            return self._finish_unclaimed(summary)
        device = fresh.observations.get("gpu_device_id")
        if device is None or device.value != inputs.launch_device_id or device.status != "ok":
            self._refuse("DEVICE_IDENTITY_NOT_REVERIFIED")
            return self._finish_unclaimed(summary)
        merged = replace(
            inputs,
            sections={
                **inputs.sections,
                **{name: fresh.sections.get(name) for name in ("processes", "endpoint")},
            },
            quiescent_baseline=fresh.quiescent_baseline or inputs.quiescent_baseline,
            fault_baseline_coverage=_fault_coverage(fresh.fault_before)
            if fresh.fault_before is not None
            else inputs.fault_baseline_coverage,
            observations={
                **inputs.observations,
                **{k: v for k, v in fresh.observations.items() if k != "gpu_device_id"},
            },
        )
        if fresh.fault_before is not None:
            collected = replace(collected, fault_before=fresh.fault_before)
        final = evaluate_preflight(
            merged,
            now_mono_s=clock.mono(),
            now_utc=clock.utc(),
            policy=self.policy,
            manifest=self.manifest,
        )
        try:
            served_findings = self.ports.collector.recheck_served()
        except Exception as exc:  # noqa: BLE001 - an inaccessible served proof is not a pass
            served_findings = [
                Finding("SERVED_RECHECK_UNAVAILABLE", "inconclusive", type(exc).__name__)
            ]
        if (
            final.decision != PREPARED
            or not final.is_current(
                now_mono_s=clock.mono(),
                max_age_s=self.config.preflight_max_age_s,
                manifest=self.manifest,
            )
            or [f for f in served_findings if f.severity != "info"]
        ):
            self._refuse(
                "FINAL_REMEASURE_REFUSED",
                final.decision,
                *final.reason_codes,
                *(f.code for f in served_findings),
            )
            return self._finish_unclaimed(self._preflight_summary(final, gates))

        baseline, _ = validate_quiescent_baseline(
            merged.quiescent_baseline,
            now_mono_s=clock.mono(),
            launch_device_id=merged.launch_device_id,
            launch_boot_id=merged.launch_boot_id,
            policy=self.policy.baseline,
        )
        return self._execute(
            authority,
            authorization,
            collected,
            final,
            baseline,
            merged,
            fresh.runtime_observed_mono_s,
        )

    # -------------------------------------------------------------------------------------------- gating
    def _merged_ledger_state(self, collected: Collected) -> str:
        fence_state = self.ports.fence.state().preflight_state()
        order = {"none": 0, "dispatched": 1, "ambiguous": 2, "unknown": 3}
        worst = max((fence_state, collected.workspace_ledger_state), key=lambda s: order.get(s, 3))
        return worst

    def _gate_findings(
        self,
        authority: ExecutionAuthority,
        authorization: OwnerAuthorization | None,
        collected: Collected,
    ) -> list[Finding]:
        # The authority kind does not gate the flow (fakes run the whole path); it gates the CLASSIFICATION: only a
        # physical authority can ever be awarded TECHNICAL_PASS_CONSTRAINED.
        findings: list[Finding] = []
        findings.extend(
            verify_authorization(
                authorization,
                manifest=self.manifest,
                payload=self.payload,
                code=collected.code,
                now_utc=self.ports.clock.utc(),
            )
        )
        findings.extend(verify_payload(dict(self.payload.body), self.manifest))
        return [f for f in findings if f.severity != "info"]

    def _preflight_summary(
        self, decision: PreflightResult, gates: Sequence[Finding]
    ) -> dict[str, Any]:
        return {**decision.as_dict(), "gate_findings": [g.code for g in gates]}

    def _case_summary(self, collected: Collected) -> dict[str, Any]:
        return {
            "case": self.manifest.attempt_identity()[:12],
            "manifest": self.manifest.digest()[:12],
            "payload": self.payload.payload_digest[:12],
            "port": 7886,
            "models": {role: spec.filename for role, spec in self.manifest.assets.items()},
            "code": collected.code.sha,
            "expected_phrase": confirmation_phrase(self.manifest, self.payload),
        }

    def _finish_unclaimed(self, summary: dict[str, Any]) -> CaseReport:
        """A refusal before the claim consumes nothing: the same case may be assessed again."""

        facts = CaseFacts(authority=AUTHORITY_SYNTHETIC, preflight_prepared=False)
        result = classify_case(facts)
        return self._report(result, preflight=summary)

    # ---------------------------------------------------------------------------------------- execution
    def _execute(
        self,
        authority: ExecutionAuthority,
        authorization: OwnerAuthorization | None,
        collected: Collected,
        decision: PreflightResult,
        baseline: ValidatedBaseline | None,
        final_inputs: PreflightInputs,
        runtime_observed_mono_s: float | None,
    ) -> CaseReport:
        ports, run, clock = self.ports, self._run, self.ports.clock
        fence = ports.fence
        provenance = {
            "authorization": authorization.record_digest() if authorization else None,
            "payload_digest": self.payload.payload_digest,
            "manifest_digest": self.manifest.digest(),
            "code_sha": collected.code.sha,
            "source_sha256": collected.code.source_sha256,
            "policy_revision": self.manifest.policy_revision,
        }
        monitor = SafetyMonitor(
            self._monitor_config
            or MonitorConfig(
                shared_baseline_bytes=baseline.shared_vram_bytes if baseline else None
            ),
            clock=clock.mono,
        )
        writer = DurableJsonlWriter(
            ports.sample_path, max_bytes=4 * 1024 * 1024, max_files=8, redact=False
        )
        # The sampler is built and PROVEN healthy before the case is consumed: a sampler that cannot deliver must not burn the
        # single authorized attempt, and no process may start without proven-good telemetry.
        sampler: SamplerPort | None = None
        try:
            sampler = ports.sampler_factory(
                monitor, writer, lambda: self._run.stage, lambda: self._endpoint_state
            )
            sampler.write_header(
                case=self.manifest.attempt_identity()[:12],
                payload_digest=self.payload.payload_digest,
                baseline=baseline.as_dict() if baseline else None,
            )
            sampler.start()
            healthy = self._sampler_is_healthy(sampler)
        except Exception as exc:  # noqa: BLE001 - nothing was claimed, started or sent
            self._refuse(f"SAMPLER_UNAVAILABLE:{type(exc).__name__}")
            self._stop_sampler(sampler)
            return self._finish_unclaimed(self._preflight_summary(decision, ()))
        if not healthy:
            self._refuse("SAMPLER_NOT_HEALTHY")
            self._stop_sampler(sampler)
            return self._finish_unclaimed(self._preflight_summary(decision, ()))
        # No operator/sampler wait may sit between the final authorization gate and the atomic claim.
        # Refresh runtime findings after sampler-health proof too; no process inventory is carried across that wait.
        try:
            claim_runtime_time, claim_sections = ports.collector.recheck_runtime()
        except Exception:  # noqa: BLE001 - unavailable inventory is never a clean runtime assessment
            claim_runtime_time, claim_sections = None, {}
        final_inputs = replace(
            final_inputs,
            sections={
                **final_inputs.sections,
                **{name: claim_sections.get(name) for name in ("processes", "endpoint")},
            },
        )
        # Re-read code and the approved record, then obtain UTC AFTER those potentially slow reads.
        try:
            current_code = ports.collector.recheck_code()
        except Exception:  # noqa: BLE001 - an unreadable identity is never trusted
            current_code = CodeRevision("unverifiable", None, None)
        try:
            record_current = bool(
                authorization is not None
                and ports.authorization_current is not None
                and ports.authorization_current(authorization)
            )
        except Exception:  # noqa: BLE001 - disappearance, replacement or inaccessible record refuses
            record_current = False
        gate_time = clock.mono()
        gates = verify_authorization(
            authorization,
            manifest=self.manifest,
            payload=self.payload,
            code=current_code,
            now_utc=clock.utc(),
        )
        gates.extend(verify_payload(dict(self.payload.body), self.manifest))
        if not record_current:
            gates.append(
                Finding(
                    "AUTHORIZATION_RECORD_NOT_CURRENT",
                    "refuse",
                    "approved record changed or cannot be reverified",
                )
            )
        runtime_current = (
            runtime_observed_mono_s is not None
            and valid_time(runtime_observed_mono_s)
            and claim_runtime_time is not None
            and valid_time(claim_runtime_time)
            and 0 <= gate_time - claim_runtime_time <= self.config.preflight_max_age_s
            and valid_time(gate_time)
            and 0 <= gate_time - runtime_observed_mono_s <= self.config.preflight_max_age_s
        )
        refreshed = evaluate_preflight(
            final_inputs,
            now_mono_s=gate_time,
            now_utc=clock.utc(),
            policy=self.policy,
            manifest=self.manifest,
        )
        if (
            not runtime_current
            or not decision.is_current(
                now_mono_s=gate_time,
                max_age_s=self.config.preflight_max_age_s,
                manifest=self.manifest,
            )
            or refreshed.decision != PREPARED
        ):
            self._refuse("FINAL_PREFLIGHT_STALE", *refreshed.reason_codes)
        if gates or run.refusals:
            self._refuse(*(f.code for f in gates))
            self._stop_sampler(sampler)
            return self._finish_unclaimed(self._preflight_summary(refreshed, gates))
        collected = replace(collected, code=current_code, inputs=final_inputs)
        decision = refreshed
        try:
            fence.claim(provenance=provenance)
        except FenceRefusal as exc:
            self._refuse(exc.code)
            self._stop_sampler(sampler)
            return self._finish_unclaimed(self._preflight_summary(decision, ()))
        run.claimed = True
        run.started_mono = clock.mono()
        try:
            self._lifecycle(sampler, collected)
        except BaseException as exc:  # noqa: BLE001 - always tear down and record, then re-raise interrupts
            run.exception = type(exc).__name__
            if not isinstance(exc, Exception):
                self._teardown(sampler)
                self._stop_sampler(sampler)
                self._record_terminal(collected, decision, baseline, sampler)
                raise
        return self._teardown_and_adjudicate(sampler, collected, decision, baseline)

    def _stop_sampler(self, sampler: SamplerPort | None) -> None:
        if sampler is None:
            return
        try:
            sampler.stop()
        except Exception as exc:  # noqa: BLE001 - the record of the run matters more than the thread
            self._refuse(f"SAMPLER_STOP_FAILED:{type(exc).__name__}")

    def _sampler_is_healthy(self, sampler: SamplerPort) -> bool:
        """Three consecutive clean samples (every essential field ok, nothing latched) before anything is consumed."""

        deadline = self.ports.clock.mono() + 20.0
        while self.ports.clock.mono() < deadline:
            if self._halted(sampler) or sampler.harness_fault:
                return False
            if sampler.clean_streak >= 3:
                return True
            self.ports.clock.sleep(0.5)
        return False

    def _halted(self, sampler: SamplerPort) -> bool:
        sampler.watchdog_tick()
        return bool(sampler.halt_event.is_set())

    def _lifecycle(self, sampler: SamplerPort, collected: Collected) -> None:
        ports, run, clock, cfg = self.ports, self._run, self.ports.clock, self.config
        fence, http, runtime = ports.fence, ports.http, ports.runtime
        # ---- managed start (record first, then act)
        self._mark("managed_start", "manager")
        fence.record_stage("managed_start_attempted", port=7886)
        if self._halted(sampler):
            return
        try:
            started = runtime.start()
        except Exception as exc:  # noqa: BLE001
            run.loader_failed = True
            run.exception = type(exc).__name__
            self._endpoint_state = "start_failed"
            return
        # ---- boot window: the manager returns right after the process is created; the endpoint binds tens of seconds
        # later. The process identity must hold the whole time; a listener is required only once the endpoint answers,
        # and a listener OUTSIDE the owned tree is a refusal at every moment.
        deadline = clock.mono() + cfg.ready_timeout_s
        options: Mapping[str, Any] | None = None
        while clock.mono() < deadline:
            if self._halted(sampler):
                return
            boot = runtime.verify_ownership(require_listener=False)
            run.ownership = boot
            if not boot.owned:
                run.loader_failed = True
                self._refuse("OWNERSHIP_NOT_VERIFIED", *boot.problems)
                return
            probe = http.get_json(OPTIONS_ENDPOINT, timeout_s=5.0)
            if probe.status == 200 and isinstance(probe.body, Mapping):
                options = probe.body
                break
            clock.sleep(1.0)
        if options is None:
            run.loader_failed = True
            self._refuse("READINESS_TIMEOUT")
            return
        # ---- the endpoint that answered must be the owned tree's (never selection against a process we do not own)
        endpoint = runtime.verify_ownership(require_listener=True)
        run.ownership = endpoint
        if not (endpoint.owned and endpoint.endpoint_in_tree):
            run.loader_failed = True
            self._refuse("ENDPOINT_NOT_OWNED", *endpoint.problems)
            return
        self._endpoint_state = "responding"
        fence.record_stage(
            "startup_observed", pid=started.get("pid"), ownership=endpoint.as_dict(), ready=True
        )
        run.startup_observed = True
        # ---- the sampling-path options must be at their pinned defaults BEFORE the selection
        findings = verify_sampling_options(options)
        if [f for f in findings if f.severity != "info"]:
            run.loader_failed = True
            self._refuse(*[f.code for f in findings])
            return
        # ---- selection (record first, then act, then read back); the ownership is re-verified immediately before
        self._mark("model_selection", "operator")
        again_owned = runtime.verify_ownership(require_listener=True)
        run.ownership = again_owned
        if not (again_owned.owned and again_owned.endpoint_in_tree):
            run.loader_failed = True
            self._refuse("ENDPOINT_NOT_OWNED_BEFORE_SELECTION", *again_owned.problems)
            return
        fence.record_stage("selection_attempted", endpoint=OPTIONS_ENDPOINT)
        if self._halted(sampler):
            return
        posted, aborted = self._supervised_request(
            sampler,
            OPTIONS_ENDPOINT,
            _json_bytes(selection_payload(ports.served_paths)),
            timeout_s=cfg.options_timeout_s,
            progress=False,
        )
        if aborted:
            return  # a monitor halt during the selection: the owned stop was requested and nothing else is sent
        if posted is None or posted.status != 200:
            run.loader_failed = True
            self._refuse("SELECTION_REJECTED")
            return
        readback = http.get_json(OPTIONS_ENDPOINT, timeout_s=30.0)
        body = readback.body if isinstance(readback.body, Mapping) else None
        problems = [
            f
            for f in (*verify_selection(body, ports.served_paths), *verify_sampling_options(body))
            if f.severity != "info"
        ]
        if readback.status != 200 or problems:
            run.loader_failed = True
            self._refuse("SELECTION_NOT_CONFIRMED", *[f.code for f in problems])
            return
        fence.record_stage("selection_confirmed")
        run.selection_confirmed = True
        # ---- pre-dispatch gates
        gate = self._predispatch(sampler)
        if gate:
            self._refuse(*gate)
            return
        # ---- the single dispatch: durable record, then exactly one POST
        self._mark(
            "unknown",
            "unknown",
            note="generation in flight; no verified phase signal until sampling starts",
        )
        fence.record_stage(
            "generation_dispatched",
            endpoint=TXT2IMG_ENDPOINT,
            payload_digest=self.payload.payload_digest,
        )
        run.dispatched = True
        self._generate(sampler)

    def _predispatch(self, sampler: SamplerPort) -> list[str]:
        ports, run = self.ports, self._run
        problems: list[str] = []
        # Two fresh CLEAN samples after the selection: the violation streak rules need consecutive readings, and a stale,
        # silent or incomplete sampler must not be mistaken for a quiet machine.
        wanted = sampler.sample_count + 2
        deadline = self.ports.clock.mono() + 15.0
        while self.ports.clock.mono() < deadline:
            if self._halted(sampler):
                break
            if sampler.sample_count >= wanted and sampler.clean_streak >= 2:
                break
            self.ports.clock.sleep(0.5)
        if self._halted(sampler):
            problems.append("HALT_BEFORE_DISPATCH")
        if sampler.sample_count < wanted:
            problems.append("NO_FRESH_SAMPLES_BEFORE_DISPATCH")
        elif sampler.clean_streak < 2:
            problems.append("NO_CLEAN_SAMPLES_BEFORE_DISPATCH")
        if sampler.harness_fault:
            problems.append("SAMPLER_FAULT_BEFORE_DISPATCH")
        owned = ports.runtime.verify_ownership(require_listener=True)
        if not (owned.owned and owned.endpoint_in_tree):
            problems.append("OWNERSHIP_LOST_BEFORE_DISPATCH")
        run.ownership = owned
        problems.extend(f.code for f in ports.collector.recheck_served())
        problems.extend(f.code for f in verify_payload(dict(self.payload.body), self.manifest))
        return problems

    def _supervised_request(
        self,
        sampler: SamplerPort,
        path: str,
        body: bytes,
        *,
        timeout_s: float,
        progress: bool,
    ) -> tuple[HttpResult | None, bool]:
        """One POST with an independent monotonic budget. An abort never accepts a late result or sends again."""

        ports, run, cfg = self.ports, self._run, self.config
        holder: dict[str, Any] = {}
        deadline = ports.clock.mono() + timeout_s

        def send() -> None:
            try:
                holder["result"] = ports.http.post_json(path, body, timeout_s=timeout_s)
            except BaseException as exc:  # noqa: BLE001 - outcome unknown, never re-sent
                holder["error"] = type(exc).__name__
            finally:
                holder["completed_mono_s"] = ports.clock.mono()

        worker = threading.Thread(target=send, name="img154b-supervised-post", daemon=True)
        worker.start()
        reason: str | None = None
        progress_worker: threading.Thread | None = None
        progress_holder: dict[str, HttpResult | None] = {}
        while True:
            halted = self._halted(sampler) or sampler.harness_fault
            now = ports.clock.mono()
            if halted:
                reason = "monitor_halt"
                break
            if now >= deadline:
                reason = "overall_deadline"
                break
            if progress_worker is not None and not progress_worker.is_alive():
                observed = progress_holder.get("result")
                if observed is not None:
                    self._apply_progress(observed)
                progress_worker = None
                progress_holder = {}
            if not worker.is_alive():
                if holder.get("completed_mono_s", now) >= deadline:
                    reason = "overall_deadline"
                    break
                if "result" in holder:
                    return holder["result"], False
                return HttpResult(None, None, holder.get("error", "no_response")), False
            if progress and progress_worker is None:
                # A socket inactivity timeout cannot bound a trickling GET. Keep a single observation worker;
                # it cannot block the watchdog/deadline or mutate the case after this supervisor exits.
                observation_timeout = min(3.0, deadline - now)
                observation_holder = progress_holder

                def observe_progress(
                    holder: dict[str, HttpResult | None] = observation_holder,
                    timeout: float = observation_timeout,
                ) -> None:
                    holder["result"] = self._poll_progress(timeout_s=timeout)

                progress_worker = threading.Thread(
                    target=observe_progress, name="img154b-progress-observation", daemon=True
                )
                progress_worker.start()
            remaining = deadline - ports.clock.mono()
            if remaining > 0:
                worker.join(min(cfg.supervision_interval_s, remaining))

        self._refuse(
            "POST_OVERALL_TIMEOUT" if reason == "overall_deadline" else "POST_MONITOR_ABORT"
        )
        self._mark("stopping", "operator", reason=reason, endpoint=path)
        self._request_event(
            path,
            reason=reason,
            timeout_s=timeout_s,
            ambiguous=True,
            worker_outstanding=worker.is_alive(),
        )
        try:
            run.shutdown = ports.runtime.stop()  # sole manager-owned lifecycle authority
        except Exception as exc:  # noqa: BLE001 - failed stop retains uncertainty
            run.shutdown = ShutdownResult(
                True, False, False, False, detail=f"stop raised {type(exc).__name__}"
            )
        join_deadline = ports.clock.mono() + cfg.abort_join_s
        worker.join(cfg.abort_join_s)
        if progress_worker is not None:
            progress_worker.join(max(0.0, join_deadline - ports.clock.mono()))
        if progress_worker is not None and progress_worker.is_alive():
            self._refuse("PROGRESS_OBSERVER_MAY_BE_OUTSTANDING")
        if worker.is_alive():
            self._refuse("POST_WORKER_MAY_BE_OUTSTANDING")
        self._request_event(
            path,
            reason="abort_shutdown",
            progress_worker_outstanding=bool(
                progress_worker is not None and progress_worker.is_alive()
            ),
            shutdown=run.shutdown.as_dict(),
            ambiguous=True,
            worker_outstanding=worker.is_alive(),
        )
        # Even a successful response after the abort cannot resurrect the case.
        return HttpResult(None, None, reason), True

    def _request_event(self, path: str, **facts: Any) -> None:
        event = {
            "kind": "request_abort",
            "endpoint": path,
            "mono_s": self.ports.clock.mono(),
            "utc": self.ports.clock.utc(),
            **facts,
        }
        self._run.requests.append(event)
        try:
            self._request_writer.append(event)  # flush/fsync BEFORE requesting owned shutdown
        except OSError as exc:
            self._refuse("POST_ABORT_RECORD_FAILED")
            self._run.exception = type(exc).__name__

    def _generate(self, sampler: SamplerPort) -> None:
        run = self._run
        response, aborted = self._supervised_request(
            sampler,
            TXT2IMG_ENDPOINT,
            self.payload.wire_bytes,
            timeout_s=self.config.generation_timeout_s,
            progress=True,
        )
        run.response = response
        if not aborted and response is not None and response.status is not None:
            run.validation = validate_response(response.status, response.body, self.manifest)

    def _poll_progress(self, *, timeout_s: float = 3.0) -> HttpResult | None:
        try:
            return self.ports.http.get_json(
                PROGRESS_ENDPOINT + "?skip_current_image=true", timeout_s=timeout_s
            )
        except Exception:  # noqa: BLE001 - observation only
            return None

    def _apply_progress(self, result: HttpResult) -> None:
        if result.status == 200:
            stage = stage_from_progress(result.body)
            current = self._run.stage
            # only the two attributable states are ever written: a running sampling loop, and "unknown" when it no longer is
            if stage != current and (stage.stage == "denoise" or current.stage == "denoise"):
                self._mark(stage.stage, stage.source)

    # ------------------------------------------------------------------------------------------ teardown
    def _teardown(self, sampler: SamplerPort | None) -> None:
        run = self._run
        if run.shutdown is None:
            self._mark("stopping", "operator")
            try:
                run.shutdown = self.ports.runtime.stop()
            except Exception as exc:  # noqa: BLE001
                run.shutdown = ShutdownResult(
                    True, False, False, False, detail=f"stop raised {type(exc).__name__}"
                )
        run.ended_mono = self.ports.clock.mono()

    def _teardown_and_adjudicate(
        self,
        sampler: SamplerPort | None,
        collected: Collected,
        decision: PreflightResult,
        baseline: ValidatedBaseline | None,
    ) -> CaseReport:
        ports, run, clock, cfg = self.ports, self._run, self.ports.clock, self.config
        self._teardown(sampler)
        # keep sampling briefly after the stop (the release of VRAM is evidence), then the fault settle interval
        self._mark("post_fault_check", "operator", note="settle")
        waited = 0.0
        while waited < cfg.settle_s:
            step = min(1.0, cfg.settle_s - waited)
            clock.sleep(step)
            waited += step
            if sampler is not None:
                sampler.watchdog_tick()
        self._stop_sampler(sampler)
        try:
            after = ports.faults()
        except Exception as exc:  # noqa: BLE001 - an unreadable snapshot is an unknown, never a clean claim
            after = None
            self._refuse(f"FAULT_SNAPSHOT_FAILED:{type(exc).__name__}")
        seconds_after = max(0.0, clock.mono() - (run.ended_mono or clock.mono()))
        classification = classify_faults(
            collected.fault_before, after, seconds_after_run=seconds_after
        )
        return self._record_terminal(
            collected, decision, baseline, sampler, after=after, classification=classification
        )

    def _record_terminal(
        self,
        collected: Collected,
        decision: PreflightResult,
        baseline: ValidatedBaseline | None,
        sampler: SamplerPort | None,
        *,
        after: FaultSnapshot | None = None,
        classification: Any = None,
    ) -> CaseReport:
        ports, run = self.ports, self._run
        records = _read_stream(ports.sample_path)
        samples = [r for r in records if r.get("kind") == "sample"]
        coverage = evaluate_telemetry_coverage(records)
        validation = run.validation
        halt = (
            sampler.halt.as_dict()
            if sampler is not None and getattr(sampler, "halt", None)
            else None
        )
        codes = tuple(halt["codes"]) if halt else ()
        latched = halt["action"] if halt else _latched_of(samples)
        shutdown = run.shutdown
        shutdown_outcome = shutdown.outcome if shutdown is not None else "not_attempted"
        bundle = self._bundle(
            collected,
            decision,
            baseline,
            records,
            coverage.as_dict(),
            after,
            classification,
            halt,
            shutdown,
        )
        facts = CaseFacts(
            authority=self._authority_kind,
            preflight_prepared=True,
            claimed=run.claimed,
            startup_observed=run.startup_observed,
            selection_confirmed=run.selection_confirmed,
            dispatched=run.dispatched,
            response_received=bool(run.response is not None and run.response.status is not None),
            loader_failed=run.loader_failed,
            monitor_codes=codes,
            monitor_latched=latched,
            shutdown=shutdown_outcome,
            unexplained_survivors=_survivors(shutdown),
            telemetry_complete=coverage.complete
            and not (sampler is not None and sampler.harness_fault),
            fault_status=classification.status
            if classification is not None
            else UNKNOWN_COVERAGE_GAP,
            output_valid=validation.facts.valid if validation is not None else None,
            identity_complete=bool(validation and validation.facts.identity_complete),
            ledger_terminal_recorded=False,
            evidence_complete=bundle["complete"],
        )
        # The terminal record carries the outcome, so the classification is made as if it will be recorded; if the record
        # cannot be made durable the case is downgraded and the ledger is left ambiguous (never re-opened, never "clean").
        result = classify_case(replace(facts, ledger_terminal_recorded=True))
        try:
            ports.fence.finish(
                result.result_class, also=list(result.also), reasons=list(result.reasons)
            )
        except FenceRefusal as exc:
            self._refuse(f"TERMINAL_RECORD_FAILED:{exc.code}")
            result = classify_case(facts)
        instructions: tuple[str, ...] = ()
        if (
            shutdown is not None and shutdown.outcome in ("timed_out", "requested_unverified")
        ) or any(
            code in run.refusals
            for code in ("POST_WORKER_MAY_BE_OUTSTANDING", "PROGRESS_OBSERVER_MAY_BE_OUTSTANDING")
        ):
            instructions = RECOVERY_INSTRUCTIONS
        return CaseReport(
            result=result,
            executed=run.dispatched,
            claimed=run.claimed,
            stages=ports.fence.state().stages,
            refusals=tuple(run.refusals),
            preflight=decision.as_dict(),
            shutdown=shutdown.as_dict() if shutdown is not None else None,
            output=validation.facts.as_dict() if validation is not None else None,
            telemetry=coverage.as_dict(),
            faults=_fault_dict(classification, after),
            halt=halt,
            evidence=bundle["index"],
            recovery_instructions=instructions,
            exception=run.exception,
            requests=tuple(run.requests),
        )

    def _bundle(
        self,
        collected: Collected,
        decision: PreflightResult,
        baseline: ValidatedBaseline | None,
        records: list[dict[str, Any]],
        coverage: dict[str, Any],
        after: FaultSnapshot | None,
        classification: Any,
        halt: dict[str, Any] | None,
        shutdown: ShutdownResult | None,
    ) -> dict[str, Any]:
        b, run, ports = self.ports.bundle, self._run, self.ports
        try:
            b.put_json("manifest", self.manifest.as_dict(), item="manifest")
            b.note_item("manifest_sha256", self.manifest.digest())
            b.put_json("effective_request", self.payload.as_dict())
            b.put_json("preflight", decision.as_dict())
            b.put_json("phases", run.phases)
            b.put_json("requests", run.requests)
            b.put_json(
                "code_revision",
                {
                    "sha": collected.code.sha,
                    "state": collected.code.state,
                    "source_sha256": collected.code.source_sha256,
                },
                item="log_and_source_hashes",
            )
            b.put_json("environment", dict(collected.facts), item="environment_snapshot")
            b.put_json(
                "boot",
                {"boot_id": collected.boot_id, "device_id": collected.device_id},
                item="boot_identity",
            )
            b.note_item(
                "timezone",
                str(
                    dict(collected.facts).get(
                        "timezone_utc_offset_minutes", "recorded_in_environment"
                    )
                ),
            )
            b.put_json(
                "ownership",
                run.ownership.as_dict() if run.ownership else {},
                item="process_ownership",
            )
            b.put_json("quiescent_baseline", baseline.as_dict() if baseline else {})
            b.put_json(
                "fault_before", _snapshot_dict(collected.fault_before), item="fault_baseline_before"
            )
            b.put_json("fault_after", _snapshot_dict(after), item="fault_baseline_after")
            b.put_json("fault_classification", _fault_dict(classification, after) or {})
            b.put_json("shutdown", shutdown.as_dict() if shutdown else {})
            b.put_json("coverage", coverage, item="coverage_gaps")
            b.put_json(
                "sample_stream",
                {"records": len(records), "path_name": ports.sample_path.name},
                item="sample_stream",
            )
            b.put_json("event_stream", run.phases, item="event_stream")
            b.put_json("ledger", {"stages": list(ports.fence.state().stages)}, item="ledger")
            tail = ports.runtime.output_tail()
            b.put_text(
                "console_tail",
                "\n".join(str(tail.get(k, "")) for k in ("stdout_tail", "stderr_tail")),
            )
            if run.validation is not None:
                b.put_json("response_validation", run.validation.facts.as_dict())
                if run.validation.png:
                    b.put_artifact("output.png", run.validation.png)
            b.put_json("halt", halt or {})
            b.put_json("exception", {"class": run.exception, "refusals": run.refusals})
            index = b.finalize(extra={"complete_items": b.complete()})
            return {"index": index, "complete": b.complete()}
        except (BundleError, OSError) as exc:
            self._refuse(f"EVIDENCE_BUNDLE_FAILED:{type(exc).__name__}")
            return {"index": {"error": type(exc).__name__, "gaps": b.gaps()}, "complete": False}


# --------------------------------------------------------------------------------------------------------- helpers


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _read_stream(path: Path) -> list[dict[str, Any]]:
    """The sample stream, oldest rotated file first; an unreadable or absent stream is an empty list (incomplete)."""

    records: list[dict[str, Any]] = []
    candidates = [path.with_name(f"{path.name}.{n}") for n in range(8, 0, -1)] + [path]
    for candidate in candidates:
        if candidate.exists():
            try:
                found, _, _ = read_jsonl(candidate)
            except OSError:
                continue
            records.extend(found)
    return records


def _latched_of(samples: Sequence[Mapping[str, Any]]) -> str:
    order = {NONE: 0, WARN: 1, REQUEST_OWNER_STOP: 2, CANNOT_VERIFY_SAFE_STATE: 3, HARNESS_FAULT: 4}
    top = NONE
    for sample in samples:
        monitor = sample.get("monitor")
        value = monitor.get("latched") if isinstance(monitor, Mapping) else None
        if isinstance(value, str) and order.get(value, 0) > order[top]:
            top = value
    return top


def _fault_coverage(snapshot: FaultSnapshot) -> dict[str, str]:
    return {
        name: (snapshot.sources[name].coverage if name in snapshot.sources else "not_collected")
        for name in FAULT_SOURCES
    }


def _snapshot_dict(snapshot: FaultSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {"collected": False}
    return {
        "collected": True,
        "taken_utc": snapshot.taken_utc,
        "boot_id": snapshot.boot_id,
        "coverage": snapshot.coverage(),
        "record_counts": {name: len(src.record_ids) for name, src in snapshot.sources.items()},
    }


def _fault_dict(classification: Any, after: FaultSnapshot | None) -> dict[str, Any] | None:
    if classification is None:
        return None
    return {
        "status": classification.status,
        "new_records": {k: list(v) for k, v in classification.new_records.items()},
        "gaps": list(classification.gaps),
        "boot_changed": classification.boot_changed,
        "after_coverage": coverage_summary(after),
        "clean_claim_allowed": classification.status == NO_NEW_EVENTS_COMPLETE_COVERAGE,
    }


def _survivors(shutdown: ShutdownResult | None) -> bool | None:
    """``False`` only for a verified clean stop; ``True`` when a survivor is known; otherwise unknown."""

    if shutdown is None:
        return None
    if shutdown.survivors:
        return True
    return False if shutdown.verified else None
