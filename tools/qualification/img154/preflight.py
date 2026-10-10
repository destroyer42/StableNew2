"""D3: the pure, fail-closed preflight evaluator.

It consumes injected observations and the findings of the other pure validators and returns an assessment. It never starts,
loads, selects, posts or stops anything, and its vocabulary never says a workload is safe, ready or qualified:

    NOT_ASSESSED | REFUSED_<reason> | INCONCLUSIVE | PREPARED_FOR_OWNER_REVIEW

Numeric limits are PROVISIONAL candidates with their source and sensitivity written down; none is a proven safe operating limit.
Unknown, stale, errored, wrongly-united or missing readings are never treated as zero or as a pass, and an old assessment never
authorizes anything (``PreflightResult.is_current``).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .core import GIB, MIB, Finding, Observation, valid_time, valid_utc
from .evidence import FAULT_SOURCES
from .manifest import POLICY_REVISION, QualificationManifest, build_manifest

NOT_ASSESSED = "NOT_ASSESSED"
INCONCLUSIVE = "INCONCLUSIVE"
PREPARED = "PREPARED_FOR_OWNER_REVIEW"
REFUSED_ASSET_IDENTITY = "REFUSED_ASSET_IDENTITY"
REFUSED_RUNTIME_PIN = "REFUSED_RUNTIME_PIN"
REFUSED_INTENT_DRIFT = "REFUSED_INTENT_DRIFT"
REFUSED_ISOLATION = "REFUSED_ISOLATION"
REFUSED_RUNTIME_CONFLICT = "REFUSED_RUNTIME_CONFLICT"
REFUSED_PRIOR_DISPATCH = "REFUSED_PRIOR_DISPATCH"
REFUSED_RISK_NOT_ACCEPTED = "REFUSED_RISK_NOT_ACCEPTED"
REFUSED_EVIDENCE_PATH = "REFUSED_EVIDENCE_PATH"
REFUSED_RESOURCE_THRESHOLD = "REFUSED_RESOURCE_THRESHOLD"

#: Refusal precedence (first match names the decision; every code is still reported).
REFUSAL_PRECEDENCE = (
    REFUSED_ASSET_IDENTITY,
    REFUSED_RUNTIME_PIN,
    REFUSED_INTENT_DRIFT,
    REFUSED_ISOLATION,
    REFUSED_RUNTIME_CONFLICT,
    REFUSED_PRIOR_DISPATCH,
    REFUSED_RISK_NOT_ACCEPTED,
    REFUSED_EVIDENCE_PATH,
    REFUSED_RESOURCE_THRESHOLD,
)
ALL_DECISIONS = (NOT_ASSESSED, INCONCLUSIVE, PREPARED, *REFUSAL_PRECEDENCE)
#: Words a decision must never contain (whole underscore-delimited words).
FORBIDDEN_DECISION_WORDS = frozenset({"GO", "QUALIFIED", "SAFE", "READY"})

SECTION_REASON = {
    "assets": REFUSED_ASSET_IDENTITY,
    "served": REFUSED_ASSET_IDENTITY,
    "pin": REFUSED_RUNTIME_PIN,
    "intent": REFUSED_INTENT_DRIFT,
    "isolation": REFUSED_ISOLATION,
    "endpoint": REFUSED_RUNTIME_CONFLICT,
    "processes": REFUSED_RUNTIME_CONFLICT,
}

#: Telemetry a future run must be able to record before a dispatch is even considered.
ESSENTIAL_TELEMETRY = (
    "commit_headroom_bytes",
    "ram_available_bytes",
    "vram_used_bytes",
    "vram_total_bytes",
    "gpu_temperature_c",
    "gpu_device_present",
    "pagefile_status",
    "forge_process_tree",
)

PROVISIONAL = "provisional"
BASELINE_RELATIVE = "baseline_relative"

#: The only acquisition path whose quiescent windows may validate a baseline: the in-process native sampler of PR-154B.
#: An operator assertion, a number typed on a command line or a single reading never does.
BASELINE_PROVIDER = "native_sampler"


@dataclass(frozen=True)
class Threshold:
    name: str
    limit: float
    units: str
    comparator: str  # ">=": the observed value must be at least the limit; "<=": at most
    status: str
    source: str
    sensitivity: str

    def passes(self, value: float) -> bool:
        if (
            not valid_time(value)
            or not valid_time(self.limit)
            or self.comparator not in (">=", "<=")
        ):
            return False
        return value >= self.limit if self.comparator == ">=" else value <= self.limit

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "limit": self.limit,
            "limit_gib": round(self.limit / GIB, 3) if self.units == "bytes" else None,
            "units": self.units,
            "comparator": self.comparator,
            "status": self.status,
            "source": self.source,
            "sensitivity": self.sensitivity,
        }


@dataclass(frozen=True)
class BaselinePolicy:
    """What makes a window of samples a validated quiescent baseline. PROVISIONAL harness judgment, not a measured limit."""

    min_samples: int = 20
    min_window_s: float = 20.0
    max_age_s: float = 60.0
    max_gap_s: float = 3.0
    max_vram_spread_bytes: float = 128 * MIB
    max_shared_spread_bytes: float = 128 * MIB
    max_utilization_percent: float = 15.0
    status: str = PROVISIONAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "min_samples": self.min_samples,
            "min_window_s": self.min_window_s,
            "max_age_s": self.max_age_s,
            "max_gap_s": self.max_gap_s,
            "max_vram_spread_mib": self.max_vram_spread_bytes / MIB,
            "max_shared_spread_mib": self.max_shared_spread_bytes / MIB,
            "max_utilization_percent": self.max_utilization_percent,
            "provider": BASELINE_PROVIDER,
        }


@dataclass(frozen=True)
class BaselineSample:
    """One quiescent-window reading. ``None`` means the value was not obtained (never zero)."""

    mono_s: float
    vram_used_bytes: float | None
    shared_vram_bytes: float | None
    gpu_utilization_percent: float | None


@dataclass(frozen=True)
class QuiescentBaselineEvidence:
    """A window of samples taken by the harness's own sampler, bound to one device and one boot."""

    samples: tuple[BaselineSample, ...] = ()
    device_id: str | None = None
    boot_id: str | None = None
    acquired_by: str = "unspecified"
    competing_runtime_free: bool | None = None


@dataclass(frozen=True)
class ValidatedBaseline:
    vram_used_bytes: float
    shared_vram_bytes: float
    device_id: str
    boot_id: str
    samples: int
    window_s: float
    age_s: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "vram_used_mib": round(self.vram_used_bytes / MIB, 1),
            "shared_vram_mib": round(self.shared_vram_bytes / MIB, 1),
            "samples": self.samples,
            "window_s": round(self.window_s, 1),
            "age_s": round(self.age_s, 1),
            "bound_to_device_and_boot": True,
        }


def validate_quiescent_baseline(
    evidence: QuiescentBaselineEvidence | None,
    *,
    now_mono_s: float,
    launch_device_id: str | None,
    launch_boot_id: str | None,
    policy: BaselinePolicy | None = None,
) -> tuple[ValidatedBaseline | None, list[Finding]]:
    """Pure. A baseline is usable only when its provenance, device, boot, density, freshness and quiet are all proven."""

    rules = policy or BaselinePolicy()
    findings: list[Finding] = []
    if evidence is None:
        return None, [
            Finding(
                "VRAM_BASELINE_UNVERIFIED",
                "inconclusive",
                "no quiescent baseline window was acquired",
            )
        ]

    def refuse(code: str, detail: str) -> None:
        findings.append(Finding(code, "refuse", detail))

    def unproven(code: str, detail: str) -> None:
        findings.append(Finding(code, "inconclusive", detail))

    if evidence.acquired_by != BASELINE_PROVIDER:
        unproven(
            "BASELINE_PROVENANCE_UNVERIFIED",
            "the window was not acquired by the harness's own native sampler",
        )
    if not evidence.device_id or not launch_device_id:
        unproven(
            "BASELINE_DEVICE_UNKNOWN", "the baseline or the launch reading has no device identity"
        )
    elif evidence.device_id != launch_device_id:
        refuse(
            "BASELINE_DEVICE_MISMATCH",
            "the baseline was taken on a different GPU than the launch reading",
        )
    if not evidence.boot_id or not launch_boot_id:
        unproven("BASELINE_BOOT_UNKNOWN", "the baseline or the launch reading has no boot identity")
    elif evidence.boot_id != launch_boot_id:
        refuse("BASELINE_BOOT_MISMATCH", "the baseline was taken in a different boot session")
    if evidence.competing_runtime_free is not True:
        if evidence.competing_runtime_free is False:
            refuse(
                "BASELINE_COMPETING_RUNTIME",
                "a model runtime was present during the quiescent window",
            )
        else:
            unproven(
                "BASELINE_COMPETING_RUNTIME_UNKNOWN",
                "runtime absence during the window was not established",
            )
    if not valid_time(now_mono_s):
        unproven("BASELINE_CLOCK_INVALID", "freshness cannot be assessed")
        return None, findings
    times = [item.mono_s for item in evidence.samples]
    if any(not valid_time(t) for t in times) or any(
        b <= a for a, b in zip(times, times[1:], strict=False)
    ):
        refuse(
            "BASELINE_SAMPLE_ORDER_INVALID", "sample times are invalid or not strictly increasing"
        )
        return None, findings
    if len(times) < rules.min_samples:
        unproven("BASELINE_TOO_FEW_SAMPLES", f"{len(times)} samples, {rules.min_samples} required")
    window = (times[-1] - times[0]) if len(times) >= 2 else 0.0
    if window < rules.min_window_s:
        unproven("BASELINE_WINDOW_TOO_SHORT", "the window is shorter than the required duration")
    if times:
        age = now_mono_s - times[-1]
        if age < 0 or age > rules.max_age_s:
            refuse("BASELINE_STALE", "the baseline window ended too long ago (or in the future)")
    else:
        age = float("nan")
    if any(b - a > rules.max_gap_s for a, b in zip(times, times[1:], strict=False)):
        unproven("BASELINE_GAP", "the window has a sampling gap")
    raw = {
        "VRAM": [s.vram_used_bytes for s in evidence.samples],
        "SHARED": [s.shared_vram_bytes for s in evidence.samples],
        "UTILIZATION": [s.gpu_utilization_percent for s in evidence.samples],
    }
    series: dict[str, list[float]] = {}
    for name, values in raw.items():
        numbers = [
            float(v)
            for v in values
            if isinstance(v, int | float) and not isinstance(v, bool) and v >= 0 and v == v
        ]
        if len(numbers) != len(values):
            unproven(
                f"BASELINE_{name}_INCOMPLETE",
                f"{name.lower()} readings are missing, invalid or negative",
            )
        series[name] = numbers
    if findings:
        return None, findings
    used, shared, util = series["VRAM"], series["SHARED"], series["UTILIZATION"]
    if max(used) - min(used) > rules.max_vram_spread_bytes:
        refuse("BASELINE_NOT_QUIESCENT", "dedicated VRAM varied too much across the window")
    if max(shared) - min(shared) > rules.max_shared_spread_bytes:
        refuse("BASELINE_NOT_QUIESCENT", "shared GPU memory varied too much across the window")
    if max(util) > rules.max_utilization_percent:
        refuse("BASELINE_NOT_QUIESCENT", "the GPU was not idle during the window")
    if findings:
        return None, findings
    return (
        ValidatedBaseline(
            float(statistics.median(used)),
            float(statistics.median(shared)),
            str(evidence.device_id),
            str(evidence.boot_id),
            len(times),
            window,
            age,
        ),
        findings,
    )


@dataclass(frozen=True)
class PreflightPolicy:
    revision: str = POLICY_REVISION
    baseline: BaselinePolicy = BaselinePolicy()
    #: Provisional: one read-only probe pass takes several seconds (PowerShell start-up); a later launch re-measures anyway.
    max_observation_age_s: float = 30.0
    commit_headroom: Threshold = Threshold(
        "commit_headroom_bytes",
        37 * GIB,
        "bytes",
        ">=",
        PROVISIONAL,
        "PR-IMG-MODELS-153 high Forge-tree private-commit analogue 30.7 GiB x 1.2 reserve = 36.8 GiB, rounded up; one baseline",
        "Reachable only on a near-quiescent desktop (commit limit minus 37 GiB must exceed current commit). A different "
        "analogue or reserve moves this by several GiB.",
    )
    available_ram: Threshold = Threshold(
        "ram_available_bytes",
        20 * GIB,
        "bytes",
        ">=",
        PROVISIONAL,
        "Judgment: 13.5 GiB of principal weights plus working margin; not derived from a measurement of this model",
        "Windows counts standby cache as available, so the reading is optimistic about reclaimable pages.",
    )
    pagefile_volume_free: Threshold = Threshold(
        "pagefile_volume_free_bytes",
        30 * GIB,
        "bytes",
        ">=",
        PROVISIONAL,
        "Judgment; the allocated pagefile is a fixed 18 GiB, so the relevance of free space on its volume is unproven",
        "Becomes meaningful only if the pagefile is system-managed and may grow; evidence review required.",
    )
    vram_over_baseline: Threshold = Threshold(
        "vram_used_over_quiescent_baseline_bytes",
        512 * MIB,
        "bytes",
        "<=",
        BASELINE_RELATIVE,
        "A freshly MEASURED quiescent baseline is required; no historical desktop figure is assumed",
        "Depends entirely on the baseline measurement being taken immediately before, with the desktop idle.",
    )
    evidence_free: Threshold = Threshold(
        "evidence_volume_free_bytes",
        1 * GIB,
        "bytes",
        ">=",
        PROVISIONAL,
        "Judgment: bounded JSONL samples at 1 Hz plus a report are far smaller",
        "Low.",
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "max_observation_age_s": self.max_observation_age_s,
            "thresholds": [
                self.commit_headroom.as_dict(),
                self.available_ram.as_dict(),
                self.pagefile_volume_free.as_dict(),
                self.vram_over_baseline.as_dict(),
                self.evidence_free.as_dict(),
            ],
            "baseline_validation": self.baseline.as_dict(),
            "all_thresholds_proven": False,
            "equality_edge": "minimums pass at exact equality (>=); the VRAM maximum passes at exact equality (<=)",
        }


@dataclass(frozen=True)
class PreflightInputs:
    manifest_digest: str | None = None
    #: section name -> findings of the pure validator, or ``None`` when that validator was not run.
    sections: Mapping[str, list[Finding] | None] = field(default_factory=dict)
    observations: Mapping[str, Observation] = field(default_factory=dict)
    #: telemetry field -> ``available`` | ``unavailable`` (from the read-only probe).
    telemetry_coverage: Mapping[str, str] | None = None
    #: evidence source -> coverage (``complete`` | ``bounded_lookback`` | ``partial`` | ``inaccessible`` |
    #: ``not_collected``), or ``None``.
    fault_baseline_coverage: Mapping[str, str] | None = None
    #: ``True`` accepted, ``False`` explicitly declined, ``None`` still pending the owner.
    residual_gpu_risk_accepted: bool | None = None
    evidence_dir_valid: bool | None = None
    ledger_state: str | None = None  # "none" | "dispatched" | "ambiguous" | "unknown"
    #: PR-154B: a window acquired by the harness's native sampler, and the device/boot of the launch reading it must match.
    quiescent_baseline: QuiescentBaselineEvidence | None = None
    launch_device_id: str | None = None
    launch_boot_id: str | None = None


@dataclass(frozen=True)
class PreflightResult:
    decision: str
    reason_codes: tuple[str, ...]
    findings: tuple[Finding, ...]
    pending_owner_decisions: tuple[str, ...]
    manifest_digest: str | None
    policy_revision: str
    assessed_mono_s: float
    assessed_utc: str | None
    measurements: Mapping[str, Any] = field(default_factory=dict)

    @property
    def prepared(self) -> bool:
        return self.decision == PREPARED

    def is_current(
        self, *, now_mono_s: float, max_age_s: float, manifest: QualificationManifest | None = None
    ) -> bool:
        """A stale assessment, or one for a different manifest, never authorizes or supports anything."""

        plan = manifest or build_manifest()
        if not all(valid_time(v) for v in (now_mono_s, self.assessed_mono_s, max_age_s)):
            return False
        age = now_mono_s - self.assessed_mono_s
        return self.prepared and 0 <= age <= max_age_s and self.manifest_digest == plan.digest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "findings": [
                {"code": f.code, "severity": f.severity, "detail": f.detail} for f in self.findings
            ],
            "pending_owner_decisions": list(self.pending_owner_decisions),
            "manifest_digest": self.manifest_digest,
            "policy_revision": self.policy_revision,
            "assessed_utc": self.assessed_utc,
            "measurements": dict(self.measurements),
        }


def _numeric(
    inputs: PreflightInputs, name: str, units: str, now_mono_s: float, policy: PreflightPolicy
) -> tuple[float | None, str | None]:
    obs = inputs.observations.get(name)
    if obs is None:
        return None, "missing"
    return obs.number(units=units, now_mono_s=now_mono_s, max_age_s=policy.max_observation_age_s)


def _resource_findings(
    inputs: PreflightInputs, now: float, policy: PreflightPolicy, measurements: dict[str, Any]
) -> list[Finding]:
    findings: list[Finding] = []

    def inconclusive(prefix: str, reason: str) -> None:
        findings.append(
            Finding(
                f"{prefix}_{reason.upper()}",
                "inconclusive",
                f"{prefix}: reading unusable ({reason})",
            )
        )

    def refuse(code: str, detail: str) -> None:
        findings.append(Finding(code, "refuse", detail))

    headroom, why = _numeric(inputs, "commit_headroom_bytes", "bytes", now, policy)
    limit, limit_why = _numeric(inputs, "commit_limit_bytes", "bytes", now, policy)
    if headroom is None:
        inconclusive("COMMIT_HEADROOM", why or "missing")
    else:
        measurements["commit_headroom_gib"] = round(headroom / GIB, 2)
        if not policy.commit_headroom.passes(headroom):
            refuse(
                "COMMIT_HEADROOM_BELOW_THRESHOLD",
                "actual commit headroom is below the provisional launch threshold",
            )
    if limit is None:
        inconclusive("COMMIT_LIMIT", limit_why or "missing")
    else:
        measurements["commit_limit_gib"] = round(limit / GIB, 2)
        if limit < policy.commit_headroom.limit:
            refuse(
                "COMMIT_THRESHOLD_UNREACHABLE",
                "the system commit limit is below the headroom threshold; the policy is not lowered and no setting is changed",
            )
        if headroom is not None and headroom > limit:
            findings.append(
                Finding(
                    "COMMIT_READING_INCONSISTENT",
                    "inconclusive",
                    "headroom exceeds the commit limit",
                )
            )

    ram, why = _numeric(inputs, "ram_available_bytes", "bytes", now, policy)
    if ram is None:
        inconclusive("RAM_AVAILABLE", why or "missing")
    else:
        measurements["ram_available_gib"] = round(ram / GIB, 2)
        if not policy.available_ram.passes(ram):
            refuse(
                "RAM_AVAILABLE_BELOW_THRESHOLD",
                "available physical RAM is below the provisional launch threshold",
            )

    page_free, why = _numeric(inputs, "pagefile_volume_free_bytes", "bytes", now, policy)
    if page_free is None:
        inconclusive("PAGEFILE_VOLUME_FREE", why or "missing")
    else:
        measurements["pagefile_volume_free_gib"] = round(page_free / GIB, 2)
        if not policy.pagefile_volume_free.passes(page_free):
            refuse(
                "PAGEFILE_VOLUME_FREE_BELOW_THRESHOLD",
                "free space on the pagefile volume is below the provisional threshold",
            )

    used, used_why = _numeric(inputs, "vram_used_bytes", "bytes", now, policy)
    total, total_why = _numeric(inputs, "vram_total_bytes", "bytes", now, policy)
    base, base_why = _numeric(inputs, "vram_quiescent_baseline_bytes", "bytes", now, policy)
    if used_why:
        inconclusive("VRAM_USED", used_why)
    if total_why:
        inconclusive("VRAM_TOTAL", total_why)
    if used is not None and total is not None:
        measurements["vram_used_mib"] = round(used / MIB)
        measurements["vram_total_mib"] = round(total / MIB)
        if total <= 0 or used > total:
            findings.append(
                Finding(
                    "VRAM_READING_INCONSISTENT",
                    "inconclusive",
                    "used exceeds total or total is zero",
                )
            )
    if inputs.quiescent_baseline is not None:
        validated, baseline_findings = validate_quiescent_baseline(
            inputs.quiescent_baseline,
            now_mono_s=now,
            launch_device_id=inputs.launch_device_id,
            launch_boot_id=inputs.launch_boot_id,
            policy=policy.baseline,
        )
        findings.extend(baseline_findings)
        if validated is not None and used is not None:
            delta = max(0.0, used - validated.vram_used_bytes)
            measurements["vram_quiescent_baseline_mib"] = round(validated.vram_used_bytes / MIB)
            measurements["vram_over_baseline_mib"] = round(delta / MIB)
            if not policy.vram_over_baseline.passes(delta):
                refuse(
                    "VRAM_OVER_QUIESCENT_BASELINE",
                    "dedicated VRAM exceeds the validated quiescent baseline by more than the provisional margin",
                )
    elif base_why:
        inconclusive("VRAM_BASELINE", base_why)
    else:
        # Without a window acquired by the harness's own sampler there is no independently validated device/boot-bound
        # quiescent evidence. A numeric observation, even freshly timestamped, cannot establish that provenance.
        inconclusive("VRAM_BASELINE", "unverified")

    evidence_free, why = _numeric(inputs, "evidence_volume_free_bytes", "bytes", now, policy)
    if evidence_free is None:
        inconclusive("EVIDENCE_VOLUME_FREE", why or "missing")
    else:
        if not policy.evidence_free.passes(evidence_free):
            refuse(
                "EVIDENCE_VOLUME_FREE_BELOW_THRESHOLD", "not enough free space for durable evidence"
            )
    return findings


def evaluate_preflight(
    inputs: PreflightInputs | None,
    *,
    now_mono_s: float,
    now_utc: str | None = None,
    policy: PreflightPolicy | None = None,
    manifest: QualificationManifest | None = None,
) -> PreflightResult:
    plan = manifest or build_manifest()
    rules = policy or PreflightPolicy()
    if inputs is None or (not inputs.sections and not inputs.observations):
        return PreflightResult(
            NOT_ASSESSED, ("NOT_ASSESSED",), (), (), None, rules.revision, now_mono_s, now_utc
        )

    findings: list[Finding] = []
    if (
        not valid_time(now_mono_s)
        or not valid_time(rules.max_observation_age_s)
        or (now_utc is not None and not valid_utc(now_utc))
    ):
        findings.append(
            Finding(
                "FRESHNESS_CLOCK_OR_LIMIT_INVALID", "inconclusive", "freshness cannot be assessed"
            )
        )
    for threshold in (
        rules.commit_headroom,
        rules.available_ram,
        rules.pagefile_volume_free,
        rules.vram_over_baseline,
        rules.evidence_free,
    ):
        if not valid_time(threshold.limit) or threshold.comparator not in (">=", "<="):
            findings.append(
                Finding("THRESHOLD_INVALID", "inconclusive", "policy threshold is invalid")
            )
    refusal_reasons: list[str] = []
    measurements: dict[str, Any] = {}

    def add(reason: str, finding: Finding) -> None:
        findings.append(finding)
        if finding.severity == "refuse" and reason not in refusal_reasons:
            refusal_reasons.append(reason)

    if inputs.manifest_digest != plan.digest():
        add(
            REFUSED_INTENT_DRIFT,
            Finding("MANIFEST_DIGEST_MISMATCH", "refuse", "assessment is for a different manifest"),
        )

    for section, reason in SECTION_REASON.items():
        result = inputs.sections.get(section)
        if result is None:
            findings.append(
                Finding(
                    f"{section.upper()}_NOT_ASSESSED", "inconclusive", f"{section} was not assessed"
                )
            )
            continue
        for item in result:
            add(reason, item)

    for item in _resource_findings(inputs, now_mono_s, rules, measurements):
        add(REFUSED_RESOURCE_THRESHOLD, item)

    coverage = inputs.telemetry_coverage
    if coverage is None:
        findings.append(
            Finding(
                "TELEMETRY_COVERAGE_UNKNOWN", "inconclusive", "telemetry coverage was not assessed"
            )
        )
    else:
        for field_name in ESSENTIAL_TELEMETRY:
            if coverage.get(field_name) != "available":
                findings.append(
                    Finding(
                        "TELEMETRY_FIELD_UNAVAILABLE",
                        "inconclusive",
                        f"essential field {field_name!r} is not available",
                    )
                )

    baseline = inputs.fault_baseline_coverage
    if baseline is None:
        findings.append(
            Finding(
                "FAULT_BASELINE_NOT_RECORDED",
                "inconclusive",
                "no fault-event baseline was recorded",
            )
        )
    else:
        for source in FAULT_SOURCES:
            state = baseline.get(source, "not_collected")
            if state not in ("complete", "bounded_lookback"):
                findings.append(
                    Finding(
                        "FAULT_BASELINE_INCOMPLETE",
                        "inconclusive",
                        f"fault baseline source {source!r} is {state}",
                    )
                )

    if inputs.evidence_dir_valid is None:
        findings.append(
            Finding(
                "EVIDENCE_PATH_NOT_ASSESSED", "inconclusive", "the evidence path was not validated"
            )
        )
    elif not inputs.evidence_dir_valid:
        add(
            REFUSED_EVIDENCE_PATH,
            Finding("EVIDENCE_PATH_INVALID", "refuse", "the durable evidence path is not usable"),
        )

    if inputs.ledger_state == "none":
        pass
    elif inputs.ledger_state in ("dispatched", "ambiguous"):
        add(
            REFUSED_PRIOR_DISPATCH,
            Finding("LEDGER_PRIOR_DISPATCH", "refuse", "a case was already dispatched; no replay"),
        )
    else:
        findings.append(
            Finding("LEDGER_STATE_UNKNOWN", "inconclusive", "the dispatch ledger state is unknown")
        )

    pending: list[str] = []
    if inputs.residual_gpu_risk_accepted is False:
        add(
            REFUSED_RISK_NOT_ACCEPTED,
            Finding("RESIDUAL_RISK_DECLINED", "refuse", "residual GPU risk was declined"),
        )
    elif inputs.residual_gpu_risk_accepted is None:
        pending.append("RESIDUAL_GPU_RISK_ACCEPTANCE")
    pending.append("PHASE_B_PHYSICAL_QUALIFICATION_AUTHORIZATION")

    if refusal_reasons:
        decision = next(reason for reason in REFUSAL_PRECEDENCE if reason in refusal_reasons)
    elif any(item.severity == "inconclusive" for item in findings):
        decision = INCONCLUSIVE
    else:
        decision = PREPARED
    return PreflightResult(
        decision,
        tuple(item.code for item in findings if item.severity != "info"),
        tuple(findings),
        tuple(pending),
        inputs.manifest_digest,
        rules.revision,
        now_mono_s,
        now_utc,
        measurements,
    )
