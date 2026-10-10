"""D4: the deterministic safety-monitoring state machine, driven by injected samples and an injected clock.

It evaluates simulated threshold rules and emits a decision; it executes NOTHING. It has no handle on any process, driver or
OS control, so a ``REQUEST_OWNER_STOP`` is a request for the owner and ``CANNOT_VERIFY_SAFE_STATE`` is an honest statement that
the machine can no longer be assessed. Passing these simulations does not establish that a real 1 Hz Windows sampler exists, that
a rule would fire in time during a driver hang, or that any stop is enforceable (see ``RULE_CLASSIFICATION``).

Semantics (all explicit so they can be reviewed):

* Comparators: ``<`` strict for RAM floor and commit headroom floor; ``>=`` for the VRAM ratio and temperature; ``>`` strict for
  the shared-memory delta and for the RAM hold duration ("over 10 seconds": exactly 10.0 s does not trip).
* Units: bytes, degrees Celsius, seconds on the sample's monotonic clock.
* Debounce: instantaneous rules need ``instant_debounce_samples`` consecutive violating samples; one clean sample resets.
* Sampling gaps: a gap above ``max_sample_gap_s`` between accepted samples, or a sample older than ``max_sample_age_s`` on the
  injected clock, is telemetry loss and can never be read as clear.
* Precedence: HARNESS_FAULT > CANNOT_VERIFY_SAFE_STATE (GPU fault event, device lost, telemetry loss) > REQUEST_OWNER_STOP >
  WARN > NONE. The highest level reached is latched until ``reset()``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from .core import CLOCK_SKEW_TOLERANCE_S, GIB, Finding, valid_time, valid_utc

NONE = "NONE"
WARN = "WARN"
REQUEST_OWNER_STOP = "REQUEST_OWNER_STOP"
CANNOT_VERIFY_SAFE_STATE = "CANNOT_VERIFY_SAFE_STATE"
HARNESS_FAULT = "HARNESS_FAULT"
LEVELS = {NONE: 0, WARN: 1, REQUEST_OWNER_STOP: 2, CANNOT_VERIFY_SAFE_STATE: 3, HARNESS_FAULT: 4}

STAGES = (
    "preflight",
    "managed_start",
    "model_selection",
    "encoder_load",
    "transformer_load",
    "denoise",
    "vae_decode",
    "stopping",
    "post_fault_check",
    "unknown",
)
STAGE_SOURCES = ("operator", "forge_api", "manager", "inferred", "unknown")

#: Which stage transitions the pinned public Forge API could be evidence for. NOT verified against the pin in Phase A: a
#: later package must prove each before any latency or phase attribution is claimed; ``unknown`` is always a valid value.
STAGE_OBSERVABILITY: Mapping[str, str] = {
    "preflight": "operator",
    "managed_start": "manager (process manager readiness; unproven)",
    "model_selection": "operator (the selection request and its acknowledgement; unproven)",
    "encoder_load": "not_observable (no phase marker identified in a public endpoint)",
    "transformer_load": "not_observable (no phase marker identified in a public endpoint)",
    "denoise": "forge_api candidate (progress state of the sampler; unproven for this pin)",
    "vae_decode": "not_observable (no phase marker identified in a public endpoint)",
    "stopping": "operator",
    "post_fault_check": "operator",
}

#: Counters a future sampler would read. ``Pages Input/sec`` counts pages read to resolve HARD faults; the broader
#: ``Page Faults/sec`` includes soft faults and must not be reported as paging pressure.
WINDOWS_COUNTERS: Mapping[str, str] = {
    "hard_fault_pages": "\\Memory\\Pages Input/sec",
    "shared_gpu_memory": "\\GPU Adapter Memory(*)\\Shared Usage",
    "commit": "GetPerformanceInfo (CommitTotal, CommitLimit)",
    "available_ram": "GetPerformanceInfo (PhysicalAvailable)",
}

#: Honest classification of every simulated stop rule. ``enforceable`` is False everywhere in Phase A: no control path exists.
RULE_CLASSIFICATION: Mapping[str, Mapping[str, Any]] = {
    "ram_available_below_floor": {
        "observable": "GetPerformanceInfo PhysicalAvailable (read-only, no privilege)",
        "status": "provisional_uncalibrated",
        "enforceable": False,
        "caveat": "The only clean baseline (PR-IMG-115) already reached 0.01 GB available RAM; the rule may fire on benign paging.",
    },
    "commit_headroom_below_floor": {
        "observable": "GetPerformanceInfo CommitTotal/CommitLimit (read-only, no privilege)",
        "status": "provisional",
        "enforceable": False,
        "caveat": "Commit exhaustion is the principal documented host-failure mode; the 4 GiB floor is a judgment.",
    },
    "vram_ratio": {
        "observable": "nvidia-smi memory.used / memory.total at a polling interval",
        "status": "provisional",
        "enforceable": False,
        "caveat": "Sampling is coarse; a spike between samples or a spill into shared memory can be missed.",
    },
    "shared_memory_delta": {
        "observable": "GPU Adapter Memory Shared Usage counter (requires a measured quiescent baseline)",
        "status": "provisional",
        "enforceable": False,
        "caveat": "Counter availability and per-adapter aggregation are not proven for this host in Phase A.",
    },
    "temperature": {
        "observable": "nvidia-smi temperature.gpu",
        "status": "provisional",
        "enforceable": False,
        "caveat": "Operator risk signal; a thermal rise is not what caused the recorded black-screen incidents.",
    },
    "gpu_fault_event": {
        "observable": "System/Application event logs (WHEA, Display, nvlddmkm) and WER/LiveKernel archives, read-only",
        "status": "provisional",
        "enforceable": False,
        "caveat": "Events are delayed or inaccessible; absence is unknown, not clean. A driver hang cannot be recovered by software.",
    },
    "telemetry_loss": {
        "observable": "sample age and gaps on a monotonic clock",
        "status": "provisional",
        "enforceable": False,
        "caveat": "Detects its own blindness only; it cannot stop a hung driver or restore a display.",
    },
    "stage_stall": {
        "observable": "stage dwell time (only when a stage is attributable)",
        "status": "unconfigured",
        "enforceable": False,
        "caveat": "No deadline is evidenced for this model on this host; the rule is inactive until one is explicitly set.",
    },
}


@dataclass(frozen=True)
class Sample:
    """One monitoring sample. ``None`` means the value was not obtained (never zero)."""

    seq: int
    mono_s: float
    utc: str
    ram_available_bytes: float | None = None
    commit_headroom_bytes: float | None = None
    vram_used_bytes: float | None = None
    vram_total_bytes: float | None = None
    shared_vram_bytes: float | None = None
    gpu_temperature_c: float | None = None
    gpu_device_present: bool | None = None
    fault_events: tuple[str, ...] = ()
    stage: str = "unknown"
    stage_source: str = "unknown"
    extra: Mapping[str, Any] = dataclass_field(
        default_factory=dict
    )  # utilization, power, process-tree sizes, pagefile, hard faults


@dataclass(frozen=True)
class MonitorConfig:
    ram_floor_bytes: float = 1 * GIB
    ram_floor_hold_s: float = 10.0
    commit_headroom_floor_bytes: float = 4 * GIB
    vram_ratio_stop: float = 0.95
    shared_delta_stop_bytes: float = 1 * GIB
    temperature_stop_c: float = 80.0
    instant_debounce_samples: int = 2
    max_sample_gap_s: float = 3.0
    max_sample_age_s: float = 3.0
    lost_samples_limit: int = 3
    max_unknown_data_s: float = 10.0
    ram_warn_bytes: float = 4 * GIB
    commit_warn_bytes: float = 8 * GIB
    vram_warn_ratio: float = 0.90
    temperature_warn_c: float = 75.0
    shared_baseline_bytes: float | None = None
    #: stage -> deadline seconds. EMPTY by default: no deadline is evidenced, so the stall rule is inactive.
    stall_deadlines_s: Mapping[str, float] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class MonitorDecision:
    action: str
    codes: tuple[str, ...]
    seq: int | None
    latched_action: str
    first_trigger: str | None
    stage: str = "unknown"
    stage_source: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "codes": list(self.codes),
            "seq": self.seq,
            "latched_action": self.latched_action,
            "first_trigger": self.first_trigger,
            "stage": self.stage,
            "stage_source": self.stage_source,
            "executes_anything": False,
        }


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


class SafetyMonitor:
    """Pure state machine. ``clock`` is an injected monotonic-seconds callable (a fake in every test)."""

    def __init__(self, config: MonitorConfig | None = None, *, clock: Callable[[], float]) -> None:
        self.config = config or MonitorConfig()
        if policy_findings(self.config):
            raise ValueError("invalid monitor policy")
        self._clock = clock
        self.reset()

    # ------------------------------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._latched = NONE
        self._first_trigger: str | None = None
        self._last_seq: int | None = None
        self._last_mono: float | None = None
        self._last_arrival: float | None = None
        self._started_at: float | None = None
        self._ram_violation_start: float | None = None
        self.observed_violations: dict[str, int] = {}
        self._unknown_since: dict[str, float] = {}
        self._pending_since: dict[str, float] = {}
        self._clock_last: float | None = None
        self._streaks = {"commit": 0, "vram": 0, "shared": 0, "temperature": 0}
        self._lost = 0
        self._stage = "unknown"
        self._stage_source = "unknown"
        self._stage_since: float | None = None

    def begin_observation(self) -> None:
        self._started_at = self._clock()

    def _valid_clock(self, now: object) -> bool:
        if not valid_time(now) or (self._clock_last is not None and now < self._clock_last):
            return False
        self._clock_last = now
        return True

    @property
    def latched_action(self) -> str:
        return self._latched

    @property
    def first_trigger(self) -> str | None:
        return self._first_trigger

    # ------------------------------------------------------------------------------------------ decisions
    def _decide(self, codes: list[tuple[str, str]], seq: int | None) -> MonitorDecision:
        """``codes`` are ``(level, code)``; the highest level wins and is latched."""

        top = NONE
        for level, _ in codes:
            if LEVELS[level] > LEVELS[top]:
                top = level
        ordered = tuple(code for _, code in sorted(codes, key=lambda item: -LEVELS[item[0]]))
        if LEVELS[top] > LEVELS[self._latched]:
            self._latched = top
            self._first_trigger = ordered[0] if ordered else None
        decision = MonitorDecision(
            top, ordered, seq, self._latched, self._first_trigger, self._stage, self._stage_source
        )
        if codes or LEVELS[top] > 0:
            self.events.append(decision.as_dict())
        return decision

    def tick(self) -> MonitorDecision:
        """Staleness check against the injected clock (no sample arrived)."""

        now = self._clock()
        cfg = self.config
        codes: list[tuple[str, str]] = []
        if not self._valid_clock(now) or (
            self._started_at is not None and not valid_time(self._started_at)
        ):
            return self._decide([(HARNESS_FAULT, "CLOCK_INVALID")], self._last_seq)
        for field, since in self._unknown_since.items():
            if now - since > cfg.max_unknown_data_s:
                codes.append((CANNOT_VERIFY_SAFE_STATE, f"UNKNOWN_DATA:{field}"))
        reference = self._last_arrival if self._last_arrival is not None else self._started_at
        if reference is None:
            codes.append((HARNESS_FAULT, "MONITOR_NOT_STARTED"))
        elif now - reference > cfg.max_sample_gap_s:
            code = (
                "TELEMETRY_STALE" if self._last_arrival is not None else "TELEMETRY_NEVER_RECEIVED"
            )
            codes.append((CANNOT_VERIFY_SAFE_STATE, code))
        return self._decide(codes, self._last_seq)

    def ingest(self, sample: Sample) -> MonitorDecision:
        cfg = self.config
        now = self._clock()
        codes: list[tuple[str, str]] = []

        if not self._valid_clock(now) or (
            self._started_at is not None and not valid_time(self._started_at)
        ):
            return self._decide([(HARNESS_FAULT, "CLOCK_INVALID")], sample.seq)

        if not valid_utc(sample.utc):
            return self._decide([(HARNESS_FAULT, "SAMPLE_UTC_INVALID")], sample.seq)

        # structural validation: a harness defect is not a device finding
        if not isinstance(sample.seq, int) or isinstance(sample.seq, bool):
            return self._decide([(HARNESS_FAULT, "SAMPLE_SEQUENCE_INVALID")], None)
        if self._last_seq is not None and sample.seq <= self._last_seq:
            return self._decide([(HARNESS_FAULT, "SAMPLE_SEQUENCE_INVALID")], sample.seq)
        mono = _number(sample.mono_s)
        if mono is None or (self._last_mono is not None and mono < self._last_mono):
            return self._decide([(HARNESS_FAULT, "SAMPLE_TIME_NOT_MONOTONIC")], sample.seq)
        if mono > now + CLOCK_SKEW_TOLERANCE_S:
            return self._decide([(HARNESS_FAULT, "SAMPLE_FROM_FUTURE")], sample.seq)

        sequence_gap = self._last_seq is not None and sample.seq > self._last_seq + 1
        prior_mono = self._last_mono
        stale = now - mono > cfg.max_sample_age_s
        gap = self._last_mono is not None and mono - self._last_mono > cfg.max_sample_gap_s
        self._last_seq, self._last_mono, self._last_arrival = sample.seq, mono, now

        if stale:
            codes.append((CANNOT_VERIFY_SAFE_STATE, "TELEMETRY_STALE"))
        if gap:
            codes.append((CANNOT_VERIFY_SAFE_STATE, "TELEMETRY_GAP"))
        if sequence_gap:
            codes.append((WARN, "SAMPLE_SEQUENCE_GAP"))
        if gap or stale or sequence_gap:
            # Unobserved samples cannot establish contiguous physical violations.
            self._ram_violation_start = None
            self._streaks = dict.fromkeys(self._streaks, 0)

        for event in sample.fault_events:
            codes.append((CANNOT_VERIFY_SAFE_STATE, f"GPU_FAULT_EVENT:{event}"))
        if sample.gpu_device_present is False:
            codes.append((CANNOT_VERIFY_SAFE_STATE, "GPU_DEVICE_LOST"))

        ram = _number(sample.ram_available_bytes)
        commit = _number(sample.commit_headroom_bytes)
        used = _number(sample.vram_used_bytes)
        total = _number(sample.vram_total_bytes)
        shared = _number(sample.shared_vram_bytes)
        temperature = _number(sample.gpu_temperature_c)
        essential_ok = (
            not stale
            and None not in (ram, commit, used, temperature)
            and total is not None
            and total > 0
            and isinstance(sample.gpu_device_present, bool)
        )
        if essential_ok:
            self._lost = 0
        else:
            self._lost += 1
            if self._lost >= cfg.lost_samples_limit:
                codes.append((CANNOT_VERIFY_SAFE_STATE, "TELEMETRY_LOST"))
            else:
                codes.append((WARN, "SAMPLE_INCOMPLETE"))

        ratio = used / total if used is not None and total else None
        states = {
            "ram_available_bytes": None if ram is None else ram < cfg.ram_floor_bytes,
            "commit_headroom_bytes": None
            if commit is None
            else commit < cfg.commit_headroom_floor_bytes,
            "vram_used_bytes": None if ratio is None else ratio >= cfg.vram_ratio_stop,
            "gpu_temperature_c": None
            if temperature is None
            else temperature >= cfg.temperature_stop_c,
            "gpu_device_present": None
            if not isinstance(sample.gpu_device_present, bool)
            else not sample.gpu_device_present,
        }
        if cfg.shared_baseline_bytes is not None:
            states["shared_vram_bytes"] = (
                None
                if shared is None
                else shared - cfg.shared_baseline_bytes > cfg.shared_delta_stop_bytes
            )
        for field, violation in states.items():
            if violation is True and not stale:
                # Preserve the actual reading even when an intervening sample was lost.
                self.observed_violations[field] = self.observed_violations.get(field, 0) + 1
                self.events.append(
                    {
                        "event": "observed_violation",
                        "field": field,
                        "seq": sample.seq,
                        "mono_s": mono,
                    }
                )
            if stale or gap or sequence_gap:
                violation = None
            if violation is False:
                # Only fresh, confirmed recovery clears unresolved evidence.
                self._unknown_since.pop(field, None)
                self._pending_since.pop(field, None)
            else:
                self._pending_since.setdefault(
                    field, prior_mono if sequence_gap and prior_mono is not None else mono
                )
                if violation is None:
                    self._unknown_since.setdefault(field, self._pending_since[field])
                since = self._unknown_since.get(field)
                if since is not None and mono - since > cfg.max_unknown_data_s:
                    codes.append((CANNOT_VERIFY_SAFE_STATE, f"UNKNOWN_DATA:{field}"))
        if not stale:
            self._evaluate_rules(codes, mono, ram, commit, used, total, shared, temperature)

        self._track_stage(codes, sample, mono)
        return self._decide(codes, sample.seq)

    # ------------------------------------------------------------------------------------------ rules
    def _streak(self, key: str, violated: bool | None) -> bool:
        """Debounce: ``True`` once the rule has been violated for the configured consecutive samples."""

        if violated is None:
            self._streaks[key] = 0
            return False
        self._streaks[key] = self._streaks[key] + 1 if violated else 0
        return self._streaks[key] >= self.config.instant_debounce_samples

    def _evaluate_rules(
        self,
        codes: list[tuple[str, str]],
        mono: float,
        ram: float | None,
        commit: float | None,
        used: float | None,
        total: float | None,
        shared: float | None,
        temperature: float | None,
    ) -> None:
        cfg = self.config
        if ram is None:
            self._ram_violation_start = None
        elif ram < cfg.ram_floor_bytes:
            if self._ram_violation_start is None:
                self._ram_violation_start = mono
            if mono - self._ram_violation_start > cfg.ram_floor_hold_s:
                codes.append((REQUEST_OWNER_STOP, "RAM_AVAILABLE_BELOW_FLOOR"))
            else:
                codes.append((WARN, "RAM_AVAILABLE_BELOW_FLOOR_PENDING"))
        else:
            self._ram_violation_start = None
            if ram < cfg.ram_warn_bytes:
                codes.append((WARN, "RAM_AVAILABLE_LOW"))

        if self._streak(
            "commit", None if commit is None else commit < cfg.commit_headroom_floor_bytes
        ):
            codes.append((REQUEST_OWNER_STOP, "COMMIT_HEADROOM_BELOW_FLOOR"))
        elif commit is not None and commit < cfg.commit_warn_bytes:
            codes.append((WARN, "COMMIT_HEADROOM_LOW"))

        ratio = used / total if used is not None and total else None
        if self._streak("vram", None if ratio is None else ratio >= cfg.vram_ratio_stop):
            codes.append((REQUEST_OWNER_STOP, "VRAM_AT_OR_ABOVE_RATIO"))
        elif ratio is not None and ratio >= cfg.vram_warn_ratio:
            codes.append((WARN, "VRAM_HIGH"))

        if cfg.shared_baseline_bytes is None:
            if shared is not None:
                codes.append((WARN, "SHARED_BASELINE_MISSING"))
            self._streaks["shared"] = 0
        else:
            delta = None if shared is None else shared - cfg.shared_baseline_bytes
            if self._streak(
                "shared", None if delta is None else delta > cfg.shared_delta_stop_bytes
            ):
                codes.append((REQUEST_OWNER_STOP, "SHARED_MEMORY_GROWTH"))

        if self._streak(
            "temperature", None if temperature is None else temperature >= cfg.temperature_stop_c
        ):
            codes.append((REQUEST_OWNER_STOP, "GPU_TEMPERATURE_AT_OR_ABOVE_LIMIT"))
        elif temperature is not None and temperature >= cfg.temperature_warn_c:
            codes.append((WARN, "GPU_TEMPERATURE_HIGH"))

    def _track_stage(self, codes: list[tuple[str, str]], sample: Sample, mono: float) -> None:
        stage, source = sample.stage, sample.stage_source
        if stage not in STAGES or source not in STAGE_SOURCES:
            codes.append((WARN, "STAGE_VALUE_INVALID"))
            stage, source = "unknown", "unknown"
        if stage == "unknown":
            source = "unknown"
        if stage != self._stage or source != self._stage_source:
            self._stage, self._stage_source, self._stage_since = stage, source, mono
            self.events.append(
                {"event": "stage", "stage": stage, "stage_source": source, "mono_s": mono}
            )
        deadline = self.config.stall_deadlines_s.get(stage)
        if deadline is not None and stage != "unknown" and self._stage_since is not None:
            if mono - self._stage_since > deadline:
                codes.append((REQUEST_OWNER_STOP, f"STAGE_STALL:{stage}"))


def policy_findings(config: MonitorConfig) -> list[Finding]:
    """Self-consistency of the proposed policy numbers (a review aid, not a safety claim)."""

    findings: list[Finding] = []
    numbers = [
        value
        for key, value in config.__dict__.items()
        if key not in ("stall_deadlines_s", "shared_baseline_bytes")
    ]
    numbers.extend(config.stall_deadlines_s.values())
    if config.shared_baseline_bytes is not None:
        numbers.append(config.shared_baseline_bytes)
    if not all(valid_time(v) for v in numbers):
        return [
            Finding(
                "POLICY_NUMBER_INVALID", "refuse", "policy values must be finite and nonnegative"
            )
        ]
    if any(
        not isinstance(v, int) or isinstance(v, bool)
        for v in (config.instant_debounce_samples, config.lost_samples_limit)
    ):
        return [Finding("DEBOUNCE_INVALID", "refuse", "sample counts must be integers")]
    if config.commit_warn_bytes <= config.commit_headroom_floor_bytes:
        findings.append(
            Finding(
                "WARN_NOT_ABOVE_STOP_COMMIT",
                "refuse",
                "commit warning must sit above the stop floor",
            )
        )
    if config.ram_warn_bytes <= config.ram_floor_bytes:
        findings.append(
            Finding(
                "WARN_NOT_ABOVE_STOP_RAM", "refuse", "RAM warning must sit above the stop floor"
            )
        )
    if config.vram_warn_ratio >= config.vram_ratio_stop:
        findings.append(
            Finding(
                "WARN_NOT_BELOW_STOP_VRAM", "refuse", "VRAM warning must sit below the stop ratio"
            )
        )
    if config.temperature_warn_c >= config.temperature_stop_c:
        findings.append(
            Finding(
                "WARN_NOT_BELOW_STOP_TEMPERATURE",
                "refuse",
                "temperature warning must sit below the stop",
            )
        )
    if config.instant_debounce_samples < 1 or config.lost_samples_limit < 1:
        findings.append(
            Finding("DEBOUNCE_INVALID", "refuse", "debounce counts must be at least one sample")
        )
    return findings
