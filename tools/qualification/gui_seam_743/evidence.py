"""Validators, aggregation and the predeclared screening rules for GUI-SEAM-743. Pure: a record is rejected, never repaired.

The screening constants are fixed before any native run and are review triggers for a research verdict. They are not
production thresholds and do not authorize a default change.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from tools.qualification.gui_port_742.evidence import (
    EvidenceError,
    summarize,
    validate_process_record,
    validate_visibility,
)
from tools.qualification.gui_seam_743.config import (
    CONTROL,
    MATRIX,
    MAX_CONFIRMATIONS,
    MIN_SAMPLES,
    WORKLOAD,
    PumpConfig,
)

# ----- predeclared screening rules ---------------------------------------------------------------------------------------
BURST_REDUCTION_MIN = 0.50  # burst median AND p95 between-run medians, each vs the control
HEARTBEAT_P95_REVIEW_MS = 2.0  # loaded-heartbeat p95 rise that triggers specific appraisal
HEARTBEAT_MAX_REVIEW_MS = 5.0  # loaded-heartbeat worst-gap rise that triggers specific appraisal
REFRESH_REDUCTION_MIN = 0.10  # operator-relevant benefit: worker-refresh-to-visible median
IDLE_CPU_REVIEW_PP = (
    0.5  # idle process CPU rise (percentage points of one core) that flags wasted scheduling
)
IDLE_PUMP_RATE_NOTE = 1.5  # idle pump-rate multiple recorded as a scheduling-cost note

LIFECYCLE_CHECKS = (
    "pending_dropped_at_close",
    "no_python_worker_leak",
    "pyside_absent",
    "single_dispatcher_per_root",
    "dispatcher_disposed",
    "dispatcher_queue_empty",
    "dispatcher_timers_empty",
    "no_late_mutations",
)
SCALAR_KEYS = (
    "burst_median_ms",
    "burst_p95_ms",
    "burst_max_ms",
    "burst_total_ms",
    "burst_peak_backlog",
    "burst_callback_median_ms",
    "burst_pumps_used",
    "burst_max_batch",
    "burst_pump_max_ms",
    "sustained_hb_median_ms",
    "sustained_hb_p95_ms",
    "sustained_hb_max_ms",
    "sustained_renders",
    "sustained_pump_max_ms",
    "refresh_to_visible_ms",
    "refresh_hb_median_ms",
    "refresh_hb_max_ms",
    "filter_visible_ms",
    "select_visible_ms",
    "idle_pump_hz",
    "idle_period_median_ms",
    "idle_cpu_percent",
    "idle_host_cpu_percent",
)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require_finite(mapping: Mapping[str, Any], keys: Sequence[str], label: str) -> None:
    for key in keys:
        if not _finite(mapping.get(key)) or mapping[key] < 0:
            raise EvidenceError(
                f"{label}.{key}: missing, nonfinite or negative ({mapping.get(key)!r})"
            )


def _require_summary(value: object, label: str, *, p95: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{label}: missing summary")
    _require_finite(value, ("n", "min", "median", "max"), label)
    if p95:
        _require_finite(value, ("p95",), label)
    if not value["min"] <= value["median"] <= value["max"]:
        raise EvidenceError(f"{label}: inconsistent min/median/max")
    return value


# ----- one run -------------------------------------------------------------------------------------------------------------
def validate_run(
    record: Mapping[str, Any], config: PumpConfig, defaults: Mapping[str, Any]
) -> None:
    """Reject a child record that cannot support a conclusion for ``config`` under the production defaults."""

    validate_process_record(record)
    validate_visibility(record.get("first_visible"), record.get("result"), "tk")
    result = record["result"]
    if result.get("toolkit") != "tk":
        raise EvidenceError("not a Tk record")
    cfg = result.get("config") or {}
    if cfg.get("name") != config.name:
        raise EvidenceError(
            f"record is for condition {cfg.get('name')!r}, expected {config.name!r}"
        )
    if cfg.get("requested") != config.parameters():
        raise EvidenceError(f"requested parameters {cfg.get('requested')} differ from the plan")
    if cfg.get("effective") != config.parameters():
        raise EvidenceError(
            f"effective parameters {cfg.get('effective')} differ from requested {config.parameters()}"
        )
    if cfg.get("production_defaults") != dict(defaults):
        raise EvidenceError("the child saw production defaults other than the parent's")
    if result.get("workload") != WORKLOAD:
        raise EvidenceError("workload identity differs from the experiment definition")
    if not result.get("fixture"):
        raise EvidenceError("fixture fingerprint missing")

    burst = result.get("burst") or {}
    expected = WORKLOAD["burst_callbacks"]
    if burst.get("arrived") is not True:
        raise EvidenceError("burst did not finish")
    if burst.get("problem"):
        raise EvidenceError(f"burst sequence invalid: {burst['problem']}")
    for key, want in (
        ("expected", expected),
        ("delivered", expected),
        ("missing", 0),
        ("duplicates", 0),
        ("out_of_order", 0),
        ("wrong_thread", 0),
    ):
        if burst.get(key) != want:
            raise EvidenceError(f"burst.{key}={burst.get(key)!r}, required {want!r}")
    _require_summary(burst.get("latency_ms"), "burst.latency_ms")
    _require_summary(burst.get("callback_ms"), "burst.callback_ms")
    _require_summary(burst.get("batch_sizes"), "burst.batch_sizes", p95=False)
    _require_summary(burst.get("pump_ms"), "burst.pump_ms", p95=False)
    _require_finite(burst, ("total_ms", "peak_backlog", "pumps_used"), "burst")
    if burst["latency_ms"]["n"] != expected:
        raise EvidenceError("burst latency sample count is not the burst size")

    sustained = result.get("sustained") or {}
    _require_summary(sustained.get("heartbeat"), "sustained.heartbeat")
    _require_summary(sustained.get("pump_ms"), "sustained.pump_ms", p95=False)
    if not sustained.get("publishes") or not sustained.get("renders"):
        raise EvidenceError("sustained workload published or rendered nothing")

    refresh = result.get("refresh") or {}
    if refresh.get("arrived") is not True or refresh.get("selection_kept") is not True:
        raise EvidenceError("worker refresh did not arrive or lost the selection")
    _require_finite(refresh, ("to_visible_ms",), "refresh")
    # a 12-revision refresh yields about 16 heartbeat gaps: median/max only (p95 needs n >= 20)
    _require_summary(refresh.get("heartbeat"), "refresh.heartbeat", p95=False)

    interaction = result.get("interaction") or {}
    _require_finite(interaction, ("filter_visible_ms", "select_visible_ms"), "interaction")

    idle = result.get("idle") or {}
    _require_finite(
        idle,
        ("window_s", "pump_count", "pump_hz", "process_cpu_percent", "host_cpu_percent"),
        "idle",
    )
    if idle["pump_count"] < 2:
        raise EvidenceError("idle window observed too few pumps to estimate a period")
    _require_summary(idle.get("period_ms"), "idle.period_ms", p95=False)

    lifecycle = result.get("lifecycle") or {}
    for key in LIFECYCLE_CHECKS:
        if lifecycle.get(key) is not True:
            raise EvidenceError(f"lifecycle check failed or missing: {key}")
    if result.get("status") != "PASS":
        raise EvidenceError("child result is not PASS")


def run_scalars(record: Mapping[str, Any]) -> dict[str, float]:
    """Flatten one validated record into the numbers that are aggregated across runs."""

    r = record["result"]
    burst, sustained, refresh = r["burst"], r["sustained"], r["refresh"]
    scalars = {
        "burst_median_ms": burst["latency_ms"]["median"],
        "burst_p95_ms": burst["latency_ms"]["p95"],
        "burst_max_ms": burst["latency_ms"]["max"],
        "burst_total_ms": burst["total_ms"],
        "burst_peak_backlog": burst["peak_backlog"],
        "burst_callback_median_ms": burst["callback_ms"]["median"],
        "burst_pumps_used": burst["pumps_used"],
        "burst_max_batch": burst["batch_sizes"]["max"],
        "burst_pump_max_ms": burst["pump_ms"]["max"],
        "sustained_hb_median_ms": sustained["heartbeat"]["median"],
        "sustained_hb_p95_ms": sustained["heartbeat"]["p95"],
        "sustained_hb_max_ms": sustained["heartbeat"]["max"],
        "sustained_renders": sustained["renders"],
        "sustained_pump_max_ms": sustained["pump_ms"]["max"],
        "refresh_to_visible_ms": refresh["to_visible_ms"],
        "refresh_hb_median_ms": refresh["heartbeat"]["median"],
        "refresh_hb_max_ms": refresh["heartbeat"]["max"],
        "filter_visible_ms": r["interaction"]["filter_visible_ms"],
        "select_visible_ms": r["interaction"]["select_visible_ms"],
        "idle_pump_hz": r["idle"]["pump_hz"],
        "idle_period_median_ms": r["idle"]["period_ms"]["median"],
        "idle_cpu_percent": r["idle"]["process_cpu_percent"],
        "idle_host_cpu_percent": r["idle"]["host_cpu_percent"],
    }
    missing = [k for k in SCALAR_KEYS if k not in scalars]
    if missing:
        raise EvidenceError(f"scalar extraction incomplete: {missing}")
    return {k: float(scalars[k]) for k in SCALAR_KEYS}


# ----- aggregation across the repeated runs of one condition ------------------------------------------------------------
def aggregate(
    runs: Sequence[Mapping[str, float]], *, expected_n: int, label: str
) -> dict[str, Any]:
    """Between-run spread of each scalar (min/median/max). Within-run p95 values are scalars of their own."""

    if len(runs) != expected_n:
        raise EvidenceError(f"{label}: {len(runs)} valid runs, expected {expected_n}")
    return {
        key: summarize([run[key] for run in runs], expected_n=expected_n, label=f"{label}.{key}")
        for key in SCALAR_KEYS
    }


def _med(runs: Sequence[Mapping[str, float]], key: str) -> float:
    return float(statistics.median(run[key] for run in runs))


def _reduction(base: float, cand: float) -> float | None:
    return None if base <= 0 else (base - cand) / base


# ----- predeclared screening --------------------------------------------------------------------------------------------
def screen(
    baseline: Sequence[Mapping[str, float]], candidate: Sequence[Mapping[str, float]]
) -> dict[str, Any]:
    """Benefit and regression evidence for one candidate against the control runs. No gate is waived by another."""

    if len(baseline) < MIN_SAMPLES or len(candidate) < MIN_SAMPLES:
        raise EvidenceError("screening needs at least the minimum repeated runs on both sides")
    med_cut = _reduction(_med(baseline, "burst_median_ms"), _med(candidate, "burst_median_ms"))
    p95_cut = _reduction(_med(baseline, "burst_p95_ms"), _med(candidate, "burst_p95_ms"))
    consistent = max(r["burst_median_ms"] for r in candidate) < min(
        r["burst_median_ms"] for r in baseline
    )
    burst_pass = (
        med_cut is not None
        and p95_cut is not None
        and med_cut >= BURST_REDUCTION_MIN
        and p95_cut >= BURST_REDUCTION_MIN
        and consistent
    )
    hb_p95 = _med(candidate, "sustained_hb_p95_ms") - _med(baseline, "sustained_hb_p95_ms")
    hb_max = _med(candidate, "sustained_hb_max_ms") - _med(baseline, "sustained_hb_max_ms")
    hb_worst = max(r["sustained_hb_max_ms"] for r in candidate) - max(
        r["sustained_hb_max_ms"] for r in baseline
    )
    refresh_hb_max = _med(candidate, "refresh_hb_max_ms") - _med(baseline, "refresh_hb_max_ms")
    responsiveness_pass = (
        hb_p95 <= HEARTBEAT_P95_REVIEW_MS
        and hb_max <= HEARTBEAT_MAX_REVIEW_MS
        and refresh_hb_max <= HEARTBEAT_MAX_REVIEW_MS
    )
    refresh_cut = _reduction(
        _med(baseline, "refresh_to_visible_ms"), _med(candidate, "refresh_to_visible_ms")
    )
    refresh_pass = (
        refresh_cut is not None
        and refresh_cut >= REFRESH_REDUCTION_MIN
        and _med(candidate, "refresh_to_visible_ms")
        < min(r["refresh_to_visible_ms"] for r in baseline)
    )
    cpu_delta = _med(candidate, "idle_cpu_percent") - _med(baseline, "idle_cpu_percent")
    rate_ratio = _med(candidate, "idle_pump_hz") / max(_med(baseline, "idle_pump_hz"), 1e-9)
    resource_pass = cpu_delta <= IDLE_CPU_REVIEW_PP
    gates = {
        "burst": burst_pass,
        "responsiveness": responsiveness_pass,
        "representative_refresh": refresh_pass,
        "resource": resource_pass,
    }
    return {
        "burst_median_reduction": med_cut,
        "burst_p95_reduction": p95_cut,
        "burst_worst_candidate_vs_best_baseline": [
            max(r["burst_median_ms"] for r in candidate),
            min(r["burst_median_ms"] for r in baseline),
        ],
        "heartbeat_p95_delta_ms": hb_p95,
        "heartbeat_max_delta_ms_median_of_runs": hb_max,
        "heartbeat_worst_gap_delta_ms": hb_worst,
        "refresh_heartbeat_max_delta_ms": refresh_hb_max,
        "refresh_reduction": refresh_cut,
        "idle_cpu_delta_pp": cpu_delta,
        "idle_pump_rate_ratio": rate_ratio,
        "idle_pump_rate_note": rate_ratio >= IDLE_PUMP_RATE_NOTE,
        "gates": gates,
        "promising": all(gates.values()),
        "burst_only": burst_pass and not all(gates.values()),
    }


def verdict(
    screens: Mapping[str, Mapping[str, Any]], confirmation_names: Sequence[str] = ()
) -> dict[str, Any]:
    """GO needs a candidate promising in the primary matrix AND in a predeclared confirmation built from it;
    CONDITIONAL GO needs a promising candidate that is not yet confirmed; otherwise NO-GO."""

    if not screens:
        raise EvidenceError("an empty candidate set cannot produce a verdict")
    primary = {k: v for k, v in screens.items() if k not in confirmation_names}
    confirmed = {k: v for k, v in screens.items() if k in confirmation_names}
    promising_primary = sorted(k for k, v in primary.items() if v["promising"])
    promising_confirmed = sorted(k for k, v in confirmed.items() if v["promising"])
    if promising_confirmed and promising_primary:
        outcome = "GO"
    elif promising_confirmed or promising_primary:
        outcome = "CONDITIONAL GO"
    else:
        outcome = "NO-GO"
    return {
        "outcome": outcome,
        "promising_primary": promising_primary,
        "promising_confirmation": promising_confirmed,
        "burst_only": sorted(k for k, v in screens.items() if v["burst_only"]),
    }


# ----- whole experiment ---------------------------------------------------------------------------------------------------
def validate_experiment(report: Mapping[str, Any]) -> list[str]:
    """Problems that prevent any PASS. An empty report, missing phase, short sample or unbound identity fails."""

    problems: list[str] = []
    identity = report.get("identity") or {}
    for key in ("source_sha", "fingerprint", "windows", "parent", "seed", "production_defaults"):
        if not identity.get(key):
            problems.append(f"identity.{key} missing")
    if identity.get("production_defaults") != CONTROL.parameters():
        problems.append(
            f"production defaults {identity.get('production_defaults')} are not the declared control"
        )
    if identity.get("worktree_clean") is not True:
        problems.append("worktree was not clean when the experiment started")
    samples = identity.get("samples")
    if not isinstance(samples, int) or samples < MIN_SAMPLES:
        problems.append(f"fewer than {MIN_SAMPLES} measured runs per candidate")
        samples = MIN_SAMPLES
    phases = report.get("phases") or {}
    if not phases:
        problems.append("no phase was executed")
    for name, phase in phases.items():
        conditions = phase.get("conditions") or {}
        if not conditions:
            problems.append(f"{name}: zero candidates")
        if name == "confirmation" and len(conditions) > MAX_CONFIRMATIONS:
            problems.append(f"{name}: more than {MAX_CONFIRMATIONS} confirmation configurations")
        if name == "primary" and set(conditions) != {c.name for c in MATRIX}:
            problems.append(
                f"{name}: candidate set {sorted(conditions)} is not the declared matrix"
            )
        for cname, cond in conditions.items():
            if len(cond.get("runs", [])) != samples:
                problems.append(
                    f"{name}/{cname}: {len(cond.get('runs', []))} valid runs, expected {samples}"
                )
            if not cond.get("warmup"):
                problems.append(f"{name}/{cname}: warm-up missing")
        ids = [r.get("run_id") for c in conditions.values() for r in c.get("runs", [])]
        if len(set(ids)) != len(ids):
            problems.append(f"{name}: duplicate run identities")
    for failure in (report.get("validity") or {}).get("failures", []):
        problems.append(f"invalid run: {failure}")
    return problems
