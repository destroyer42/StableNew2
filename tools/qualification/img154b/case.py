"""D8 (154B): the one-case coordinator, written against ports so every path is exercised with fakes.

It performs NO real I/O of its own: a runtime, an HTTP client, a sampler factory, fault snapshots and the operator prompt are
injected. Nothing here can build those real ports; only ``physical`` (disabled by default) can, and only after it mints a
``physical`` execution authority. A coordinator run with the ``synthetic`` authority can never produce
``TECHNICAL_PASS_CONSTRAINED``.

Order of one case (each ``*_attempted`` record and ``generation_dispatched`` is made durable BEFORE its action)::

    gates -> operator confirmation -> fresh re-measure -> claim -> sampler -> managed_start_attempted -> start ->
    ownership + readiness -> startup_observed -> option defaults -> selection_attempted -> selection -> selection_confirmed ->
    pre-dispatch gates -> generation_dispatched -> ONE POST (supervised) -> owned shutdown -> settle -> fault snapshot ->
    adjudication -> terminal_evidence + outcome

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

from tools.qualification.img154.core import Finding, Observation
from tools.qualification.img154.evidence import (
    FAULT_SETTLE_S,
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

    def verify_ownership(self) -> OwnershipFacts: ...

    def stop(self) -> ShutdownResult: ...

    def output_tail(self) -> Mapping[str, Any]: ...


class SamplerPort(Protocol):
    halt_event: threading.Event
    halt: Any
    harness_fault: str | None
    provenance: dict[str, str]
    #: number of samples evaluated by the monitor so far (a fresh sample is evidence the sampler is delivering)
    sample_count: int

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


class PreflightCollector(Protocol):
    def collect(self) -> Collected: ...

    def remeasure(self) -> Mapping[str, Observation]: ...

    def recheck_served(self) -> list[Finding]: ...


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
    clock: ClockPort
    bundle: EvidenceBundle
    sample_path: Path
    served_paths: Mapping[str, str]


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
    numbers = (steps, step, jobs)
    if any(isinstance(n, bool) or not isinstance(n, int) for n in numbers):
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

        fresh = self.ports.collector.remeasure()
        device = fresh.get("gpu_device_id")
        if device is None or device.value != inputs.launch_device_id or device.status != "ok":
            self._refuse("DEVICE_IDENTITY_NOT_REVERIFIED")
            return self._finish_unclaimed(summary)
        merged = replace(
            inputs,
            observations={
                **inputs.observations,
                **{k: v for k, v in fresh.items() if k != "gpu_device_id"},
            },
        )
        final = evaluate_preflight(
            merged,
            now_mono_s=clock.mono(),
            now_utc=clock.utc(),
            policy=self.policy,
            manifest=self.manifest,
        )
        served_findings = self.ports.collector.recheck_served()
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
        return self._execute(authority, authorization, collected, final, baseline)

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
    ) -> CaseReport:
        ports, run, clock, _cfg = self.ports, self._run, self.ports.clock, self.config
        fence = ports.fence
        provenance = {
            "authorization": authorization.record_digest() if authorization else None,
            "payload_digest": self.payload.payload_digest,
            "manifest_digest": self.manifest.digest(),
            "code_sha": collected.code.sha,
            "source_sha256": collected.code.source_sha256,
            "policy_revision": self.manifest.policy_revision,
        }
        try:
            fence.claim(provenance=provenance)
        except FenceRefusal as exc:
            self._refuse(exc.code)
            return self._finish_unclaimed(self._preflight_summary(decision, ()))
        run.claimed = True
        run.started_mono = clock.mono()
        sampler: SamplerPort | None = None
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
            self._lifecycle(sampler, collected)
        except BaseException as exc:  # noqa: BLE001 - always tear down and record, then re-raise interrupts
            run.exception = type(exc).__name__
            if not isinstance(exc, Exception):
                self._teardown(sampler)
                self._record_terminal(collected, decision, baseline, sampler)
                raise
        return self._teardown_and_adjudicate(sampler, collected, decision, baseline)

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
        ownership = runtime.verify_ownership()
        run.ownership = ownership
        if not ownership.owned:
            run.loader_failed = True
            self._refuse("OWNERSHIP_NOT_VERIFIED")
            return
        # ---- readiness (bounded; ownership and halt re-checked every iteration)
        deadline = clock.mono() + cfg.ready_timeout_s
        ready = False
        while clock.mono() < deadline:
            if self._halted(sampler):
                return
            probe = http.get_json(OPTIONS_ENDPOINT, timeout_s=5.0)
            if probe.status == 200 and isinstance(probe.body, Mapping):
                ready = True
                options = probe.body
                break
            if not runtime.verify_ownership().owned:
                run.loader_failed = True
                self._refuse("OWNED_PROCESS_LOST_BEFORE_READY")
                return
            clock.sleep(1.0)
        if not ready:
            run.loader_failed = True
            self._refuse("READINESS_TIMEOUT")
            return
        self._endpoint_state = "responding"
        run.ownership = runtime.verify_ownership()
        fence.record_stage(
            "startup_observed",
            pid=started.get("pid"),
            ownership=run.ownership.as_dict(),
            ready=True,
        )
        run.startup_observed = True
        # ---- the sampling-path options must be at their pinned defaults BEFORE the selection
        findings = verify_sampling_options(options)
        if [f for f in findings if f.severity != "info"]:
            run.loader_failed = True
            self._refuse(*[f.code for f in findings])
            return
        # ---- selection (record first, then act, then read back)
        self._mark("model_selection", "operator")
        fence.record_stage("selection_attempted", endpoint=OPTIONS_ENDPOINT)
        if self._halted(sampler):
            return
        posted = http.post_json(
            OPTIONS_ENDPOINT,
            _json_bytes(selection_payload(ports.served_paths)),
            timeout_s=cfg.options_timeout_s,
        )
        if posted.status != 200:
            run.loader_failed = True
            self._refuse("SELECTION_REJECTED")
            return
        readback = http.get_json(OPTIONS_ENDPOINT, timeout_s=30.0)
        selection = verify_selection(
            readback.body if isinstance(readback.body, Mapping) else None, ports.served_paths
        )
        again = verify_sampling_options(
            readback.body if isinstance(readback.body, Mapping) else None
        )
        problems = [f for f in (*selection, *again) if f.severity != "info"]
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
        run.stage = StageInfo()
        fence.record_stage(
            "generation_dispatched",
            endpoint=TXT2IMG_ENDPOINT,
            payload_digest=self.payload.payload_digest,
        )
        run.dispatched = True
        self._supervised_post(sampler)

    def _predispatch(self, sampler: SamplerPort) -> list[str]:
        ports, run = self.ports, self._run
        problems: list[str] = []
        # Two fresh samples after the selection: the violation streak rules need consecutive readings, and a stale or silent
        # sampler must not be mistaken for a quiet machine.
        wanted = sampler.sample_count + 2
        deadline = self.ports.clock.mono() + 15.0
        while sampler.sample_count < wanted and self.ports.clock.mono() < deadline:
            if self._halted(sampler):
                break
            self.ports.clock.sleep(0.5)
        if self._halted(sampler):
            problems.append("HALT_BEFORE_DISPATCH")
        if sampler.sample_count < wanted:
            problems.append("NO_FRESH_SAMPLES_BEFORE_DISPATCH")
        if sampler.harness_fault:
            problems.append("SAMPLER_FAULT_BEFORE_DISPATCH")
        owned = ports.runtime.verify_ownership()
        if not owned.owned:
            problems.append("OWNERSHIP_LOST_BEFORE_DISPATCH")
        run.ownership = owned
        problems.extend(f.code for f in ports.collector.recheck_served())
        problems.extend(f.code for f in verify_payload(dict(self.payload.body), self.manifest))
        return problems

    def _supervised_post(self, sampler: SamplerPort) -> None:
        ports, run, _clock, cfg = self.ports, self._run, self.ports.clock, self.config
        holder: dict[str, Any] = {}

        def send() -> None:
            try:
                holder["result"] = ports.http.post_json(
                    TXT2IMG_ENDPOINT, self.payload.wire_bytes, timeout_s=cfg.generation_timeout_s
                )
            except BaseException as exc:  # noqa: BLE001 - the outcome is unknown; it is never re-sent
                holder["error"] = type(exc).__name__

        worker = threading.Thread(target=send, name="img154b-generation-post", daemon=True)
        worker.start()
        while worker.is_alive():
            worker.join(cfg.supervision_interval_s)
            if not worker.is_alive():
                break
            self._poll_progress()
            if self._halted(sampler) or sampler.harness_fault:
                self._mark("stopping", "operator", reason="monitor halt during generation")
                run.shutdown = ports.runtime.stop()  # manager-owned only; never a second request
                worker.join(cfg.abort_join_s)
                break
        if "result" in holder:
            run.response = holder["result"]
        elif "error" in holder or worker.is_alive():
            run.response = HttpResult(None, None, holder.get("error", "no_response_before_abort"))
        if run.response is not None and run.response.status == 200:
            run.validation = validate_response(
                run.response.status, run.response.body, self.manifest
            )
        elif run.response is not None and run.response.status is not None:
            run.validation = validate_response(
                run.response.status, run.response.body, self.manifest
            )

    def _poll_progress(self) -> None:
        try:
            result = self.ports.http.get_json(
                PROGRESS_ENDPOINT + "?skip_current_image=true", timeout_s=3.0
            )
        except Exception:  # noqa: BLE001 - observation only
            return
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
        if sampler is not None:
            sampler.stop()
        after = ports.faults()
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
        if shutdown is not None and shutdown.outcome in ("timed_out", "requested_unverified"):
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
