"""D6: the bounded, redacted operator packet, the deterministic monitor dry run and the read-only CLI.

The CLI has exactly three subcommands: ``manifest`` (print the frozen proposed manifest), ``dry-run`` (offline, fakes only) and
``read-only-probe`` (opt-in read-only host facts). It has no command, flag or code path that launches, selects a model, posts a
request, cancels or terminates anything, and it never reads or writes outside the explicitly named paths.

Dispositions are ``REFUSED`` | ``HOLD`` | ``PREPARED_FOR_OWNER_REVIEW``. None of them means a workload is safe to run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core import GIB, MIB, Finding, Observation
from .evidence import (
    NOT_COLLECTED,
    DispatchLedger,
    FileLedgerStore,
    redact_value,
)
from .isolation import RealFs, validate_endpoint, validate_isolation, validate_process_conflicts
from .manifest import (
    FileMeasurement,
    QualificationManifest,
    build_manifest,
    verify_assets,
    verify_intent,
    verify_runtime_pin,
)
from .monitor import (
    CANNOT_VERIFY_SAFE_STATE,
    NONE,
    REQUEST_OWNER_STOP,
    RULE_CLASSIFICATION,
    STAGE_OBSERVABILITY,
    WARN,
    WINDOWS_COUNTERS,
    MonitorConfig,
    SafetyMonitor,
    Sample,
    policy_findings,
)
from .preflight import (
    ESSENTIAL_TELEMETRY,
    PREPARED,
    PreflightInputs,
    PreflightPolicy,
    PreflightResult,
    evaluate_preflight,
)
from .probes import Clocks, ProbeResult, collect_live_observations

PACKET_SCHEMA = "stablenew.img154.operator-packet.v1"
PHASE_A_PASS = "PASS_PREPARATION_ONLY"
PHASE_A_HOLD = "HOLD_PRECONDITION_UNPROVEN"

EXECUTION_BOUNDARY = {
    "launch": "absent",
    "model_selection": "absent",
    "generation_request": "absent",
    "cancellation_or_termination": "absent",
    "process_management": "absent (WebUIProcessManager is not imported or instantiated)",
    "production_src_changes": "none",
    "statement": "No callable physical pathway exists in this package; execution is a separate, separately authorized package.",
}

RESIDUAL_RISKS = (
    {
        "id": "GPU_HARD_FAILURE_FAMILY",
        "class": "unmitigated",
        "text": "DIAG-GPU-130 black-screen/live-kernel recurrences are unresolved and not attributed to this workload. "
        "No software monitor or stop request can recover a driver hang, black screen or machine reset.",
    },
    {
        "id": "THRESHOLDS_PROVISIONAL",
        "class": "unproven",
        "text": "Every preflight and stop number is a provisional candidate derived from one analogue (PR-IMG-115) or judgment.",
    },
    {
        "id": "RAM_STOP_RULE_UNCALIBRATED",
        "class": "unproven",
        "text": "The only clean baseline already reached 0.01 GB available RAM; the stop rule may fire on benign paging.",
    },
    {
        "id": "STAGE_ATTRIBUTION_UNPROVEN",
        "class": "unproven",
        "text": "Encoder, transformer and VAE phases are not shown to be observable through the pinned Forge API.",
    },
    {
        "id": "REQUEST_SEMANTICS_UNRECONCILED",
        "class": "unproven",
        "text": "Model card guidance 0.0 versus the pinned UI preset CFG 1.0 / shift 9.0 is not reconciled at the payload level.",
    },
    {
        "id": "PROVENANCE_UNVERIFIED",
        "class": "accepted_as_stated",
        "text": "Exact bytes are frozen; official provenance of the three files is not authenticated.",
    },
    {
        "id": "FAULT_EVIDENCE_DELAY",
        "class": "partially_mitigated",
        "text": "WER and live-kernel records post late or may be inaccessible; absence is reported as unknown, never as clean.",
    },
)

PHASE_B_CHECKLIST = (
    "Separate owner authorization for PR-IMG-MODELS-154B and independent review of this package.",
    "Reconcile the txt2img payload meaning (guidance, shift, scheduler) against the pinned runtime source.",
    "Re-measure every preflight counter immediately before dispatch; an old assessment authorizes nothing.",
    "Verify the three SERVED files (size and full SHA-256) at the isolated forge-data/models paths, not the downloads.",
    "Single case, one frozen request, no retry and no replay; the ledger attempt is recorded BEFORE any send.",
    "Lifecycle only through WebUIProcessManager ownership; no adoption, signal or termination of an external process.",
    "Baseline and post fault snapshots with an elapsed settle interval; unknown coverage is never reported as clean.",
    "Explicit owner acceptance of the residual GPU hard-failure risk recorded before dispatch.",
)

INVALIDATION_CONDITIONS = (
    "The manifest digest changes (any asset, pin, intent or policy revision).",
    "The preflight assessment is older than its freshness window.",
    "Any hashed or served file, the managed runtime marker, or the host's telemetry coverage changes.",
    "A different frozen request is presented, or any case has already been attempted.",
)


# ---------------------------------------------------------------------------------------------- deterministic dry run


class FakeClock:
    """The injected clock used by every dry run and test (never the wall clock)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _sample(seq: int, t: float, **overrides: Any) -> Sample:
    values: dict[str, Any] = {
        "seq": seq,
        "mono_s": t,
        "utc": f"2026-01-01T00:00:{int(t) % 60:02d}+00:00",
        "ram_available_bytes": 12 * GIB,
        "commit_headroom_bytes": 20 * GIB,
        "vram_used_bytes": 5 * GIB,
        "vram_total_bytes": 12 * GIB,
        "shared_vram_bytes": 0.5 * GIB,
        "gpu_temperature_c": 55.0,
        "gpu_device_present": True,
    }
    values.update(overrides)
    return Sample(**values)


def _drive(
    samples: Sequence[dict[str, Any]], config: MonitorConfig | None = None, *, base: float = 1000.0
) -> SafetyMonitor:
    clock = FakeClock(base)
    monitor = SafetyMonitor(config or MonitorConfig(shared_baseline_bytes=0.5 * GIB), clock=clock)
    monitor.begin_observation()
    for index, overrides in enumerate(samples, start=1):
        clock.now = base + float(overrides.get("_t", index))
        values = {k: v for k, v in overrides.items() if k != "_t"}
        monitor.ingest(_sample(index, base + float(overrides.get("_t", index)), **values))
    return monitor


def dry_run_scenarios() -> list[dict[str, Any]]:
    """Fake-sample proof of the simulated rules, precedence, debounce and gap handling. It exercises the state machine only."""

    ram_low = {"ram_available_bytes": 0.5 * GIB}
    scenarios: list[tuple[str, str, Sequence[dict[str, Any]], MonitorConfig | None]] = [
        ("nominal_30s", NONE, [{} for _ in range(30)], None),
        ("ram_low_exactly_10s_does_not_stop", WARN, [ram_low for _ in range(11)], None),
        ("ram_low_over_10s_requests_stop", REQUEST_OWNER_STOP, [ram_low for _ in range(12)], None),
        (
            "commit_headroom_below_floor",
            REQUEST_OWNER_STOP,
            [{"commit_headroom_bytes": 3 * GIB}] * 2,
            None,
        ),
        ("vram_at_95_percent", REQUEST_OWNER_STOP, [{"vram_used_bytes": 11.4 * GIB}] * 2, None),
        (
            "shared_memory_growth_over_1gib",
            REQUEST_OWNER_STOP,
            [{"shared_vram_bytes": 1.6 * GIB}] * 2,
            None,
        ),
        ("temperature_at_80c", REQUEST_OWNER_STOP, [{"gpu_temperature_c": 80.0}] * 2, None),
        (
            "fault_event_precedes_resource_stop",
            CANNOT_VERIFY_SAFE_STATE,
            [
                {"commit_headroom_bytes": 3 * GIB},
                {"commit_headroom_bytes": 3 * GIB, "fault_events": ("WHEA",)},
            ],
            None,
        ),
        ("gpu_device_lost", CANNOT_VERIFY_SAFE_STATE, [{}, {"gpu_device_present": False}], None),
        ("sampling_gap_is_not_clear", CANNOT_VERIFY_SAFE_STATE, [{}, {"_t": 9}], None),
        (
            "unobservable_stage_stays_unknown",
            NONE,
            [{"stage": "unknown", "stage_source": "inferred"} for _ in range(3)],
            None,
        ),
    ]
    results: list[dict[str, Any]] = []
    for name, expected, samples, config in scenarios:
        monitor = _drive(samples, config)
        latched = monitor.latched_action
        results.append(
            {
                "scenario": name,
                "expected_latched_action": expected,
                "latched_action": latched,
                "ok": latched == expected,
                "first_trigger": monitor.first_trigger,
            }
        )
    return results


# ------------------------------------------------------------------------------------------ feasibility and packet


def threshold_feasibility(
    policy: PreflightPolicy, probe: ProbeResult | None
) -> list[dict[str, Any]]:
    """Whether each provisional preflight number is reachable on this host (read from the probe), and whether it holds now."""

    rows: list[dict[str, Any]] = []
    observed: dict[str, Observation] = probe.observations if probe is not None else {}

    def value(name: str) -> float | None:
        item = observed.get(name)
        return (
            float(item.value)
            if item is not None and item.status == "ok" and isinstance(item.value, int | float)
            else None
        )

    limit, headroom = value("commit_limit_bytes"), value("commit_headroom_bytes")
    rows.append(
        {
            "name": policy.commit_headroom.name,
            "status": policy.commit_headroom.status,
            "limit_gib": round(policy.commit_headroom.limit / GIB, 2),
            "reachable_in_principle": None
            if limit is None
            else limit >= policy.commit_headroom.limit,
            "currently_met": None if headroom is None else headroom >= policy.commit_headroom.limit,
            "observed_gib": None if headroom is None else round(headroom / GIB, 2),
            "commit_limit_gib": None if limit is None else round(limit / GIB, 2),
            "implied_max_commit_total_gib": None
            if limit is None
            else round((limit - policy.commit_headroom.limit) / GIB, 2),
            "note": "requires a near-quiescent desktop before launch (current commit total must not exceed limit minus threshold)",
        }
    )
    total_ram = value("ram_total_bytes")
    for threshold, key, reachable in (
        (
            policy.available_ram,
            "ram_available_bytes",
            None if total_ram is None else total_ram >= policy.available_ram.limit,
        ),
        (policy.pagefile_volume_free, "pagefile_volume_free_bytes", None),
    ):
        now = value(key)
        rows.append(
            {
                "name": threshold.name,
                "status": threshold.status,
                "limit_gib": round(threshold.limit / GIB, 2),
                "reachable_in_principle": reachable,
                "currently_met": None if now is None else now >= threshold.limit,
                "observed_gib": None if now is None else round(now / GIB, 2),
                "note": threshold.sensitivity,
            }
        )
    return rows


def classify_package(
    scenarios: Sequence[dict[str, Any]],
    manifest: QualificationManifest,
    probe: ProbeResult | None,
) -> tuple[str, list[str]]:
    """``PASS_PREPARATION_ONLY`` only when the contracts hold AND every essential counter and fault source was obtained here.

    Anything else is ``HOLD_PRECONDITION_UNPROVEN`` with the reasons. Neither value says the workload is safe to run.
    """

    reasons: list[str] = []
    if not all(item["ok"] for item in scenarios):
        reasons.append("deterministic monitor dry run did not reproduce its expected outcomes")
    if policy_findings(MonitorConfig()):
        reasons.append("proposed stop policy is internally inconsistent")
    if probe is None:
        reasons.append("no read-only host probe was run: counter availability is unproven")
    else:
        reasons.extend(probe.gaps)
        for name in ESSENTIAL_TELEMETRY:
            if probe.telemetry_coverage.get(name) != "available":
                reasons.append(f"essential telemetry not available: {name}")
    blocking = list(dict.fromkeys(reasons))
    return (PHASE_A_PASS if not blocking else PHASE_A_HOLD), blocking


def _disposition(result: PreflightResult | None) -> str:
    if result is None or result.decision in ("NOT_ASSESSED", "INCONCLUSIVE"):
        return "HOLD"
    return "PREPARED_FOR_OWNER_REVIEW" if result.decision == PREPARED else "REFUSED"


def build_packet(
    *,
    manifest: QualificationManifest | None = None,
    preflight: PreflightResult | None = None,
    probe: ProbeResult | None = None,
    policy: PreflightPolicy | None = None,
    mode: str = "offline_dry_run",
    generated_utc: str | None = None,
) -> dict[str, Any]:
    plan = manifest or build_manifest()
    rules = policy or PreflightPolicy()
    scenarios = dry_run_scenarios()
    package_class, hold_reasons = classify_package(scenarios, plan, probe)
    available = {
        name: (
            probe.telemetry_coverage.get(name, "unavailable") if probe is not None else "not_probed"
        )
        for name in ESSENTIAL_TELEMETRY
    }
    packet: dict[str, Any] = {
        "schema": PACKET_SCHEMA,
        "generated_utc": generated_utc or datetime.now(UTC).isoformat(),
        "mode": mode,
        "disposition": _disposition(preflight),
        "preflight": preflight.as_dict() if preflight is not None else None,
        "phase_a_classification": package_class,
        "phase_a_hold_reasons": hold_reasons,
        "meaning": "Preparation evidence only. Nothing here states that any workload is safe, ready or qualified.",
        "execution_boundary": EXECUTION_BOUNDARY,
        "manifest": plan.as_dict(),
        "manifest_digest": plan.digest(),
        "intended_run": "frozen_not_executed",
        "policy": rules.as_dict(),
        "threshold_feasibility": threshold_feasibility(rules, probe),
        "stop_rules": {
            "classification": {k: dict(v) for k, v in RULE_CLASSIFICATION.items()},
            "config": MonitorConfig().__dict__ | {"stall_deadlines_s": {}},
            "stage_observability": dict(STAGE_OBSERVABILITY),
            "windows_counters": dict(WINDOWS_COUNTERS),
            "monitor_dry_run": scenarios,
        },
        "telemetry_availability": available,
        "probe_gaps": list(probe.gaps) if probe is not None else ["no read-only probe was run"],
        "environment": probe.environment if probe is not None else {},
        "residual_risks": [dict(item) for item in RESIDUAL_RISKS],
        "phase_b_acceptance_checklist": list(PHASE_B_CHECKLIST),
        "invalid_if": list(INVALIDATION_CONDITIONS),
    }
    return redact_value(packet)  # type: ignore[no-any-return]


PACKET_MAX_AGE_S = 300.0


def packet_is_current(
    packet: dict[str, Any],
    *,
    manifest: QualificationManifest | None = None,
    now_utc: datetime | None = None,
    max_age_s: float = PACKET_MAX_AGE_S,
) -> tuple[bool, list[str]]:
    """A changed manifest, a packet that never reached PREPARED, or a stale or untimed assessment invalidates the packet."""

    plan = manifest or build_manifest()
    problems: list[str] = []
    if packet.get("manifest_digest") != plan.digest():
        problems.append("manifest digest differs from the packet")
    if packet.get("disposition") != "PREPARED_FOR_OWNER_REVIEW":
        problems.append("packet disposition is not PREPARED_FOR_OWNER_REVIEW")
    assessed = (packet.get("preflight") or {}).get("assessed_utc")
    try:
        taken = datetime.fromisoformat(str(assessed))
        if taken.tzinfo is None:
            raise ValueError("naive timestamp")
        age = ((now_utc or datetime.now(UTC)) - taken).total_seconds()
    except (TypeError, ValueError):
        problems.append("preflight assessment has no usable timestamp")
    else:
        if age < 0 or age > max_age_s:
            problems.append("preflight assessment is stale")
    return (not problems), problems


def render_text(packet: dict[str, Any]) -> str:
    lines = [
        "PR-IMG-MODELS-154A safety preparation packet (preparation only; not a safety statement)",
        f"mode: {packet['mode']}    disposition: {packet['disposition']}",
        f"phase A classification: {packet['phase_a_classification']}",
        f"manifest digest: {packet['manifest_digest']}",
    ]
    for reason in packet["phase_a_hold_reasons"][:12]:
        lines.append(f"  hold: {reason}")
    pre = packet.get("preflight")
    if pre:
        lines.append(f"preflight decision: {pre['decision']}")
        for code in pre["reason_codes"][:16]:
            lines.append(f"  - {code}")
    lines.append("threshold feasibility (provisional numbers):")
    for row in packet["threshold_feasibility"]:
        lines.append(
            f"  {row['name']}: limit {row['limit_gib']} GiB, reachable={row['reachable_in_principle']}, "
            f"met now={row['currently_met']}, observed={row['observed_gib']}"
        )
    lines.append("monitor dry run:")
    for item in packet["stop_rules"]["monitor_dry_run"]:
        lines.append(
            f"  {'ok ' if item['ok'] else 'BAD'} {item['scenario']}: {item['latched_action']}"
        )
    lines.append("residual risks: " + ", ".join(r["id"] for r in packet["residual_risks"]))
    lines.append("execution boundary: " + EXECUTION_BOUNDARY["statement"])
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------------ CLI


@dataclass(frozen=True)
class _Args:
    command: str
    out: Path | None
    models_root: Path | None
    qualification_root: Path | None
    forge_install: Path | None
    reserve: tuple[str, ...]
    hash_files: bool
    vram_baseline_mib: float | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="img154", description="PR-IMG-MODELS-154A safety preparation (read-only)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest", help="print the frozen proposed manifest as JSON")
    dry = sub.add_parser("dry-run", help="offline packet from fakes only; reads no host state")
    probe = sub.add_parser(
        "read-only-probe", help="opt-in read-only host facts; writes only the named report"
    )
    for item in (dry, probe):
        item.add_argument(
            "--out",
            type=Path,
            help="report JSON path (an ignored local directory such as reports/)",
        )
    probe.add_argument(
        "--models-root", type=Path, help="existing library models directory holding the three files"
    )
    probe.add_argument(
        "--hash",
        dest="hash_files",
        action="store_true",
        help="read and SHA-256 the three named files",
    )
    probe.add_argument(
        "--qualification-root", type=Path, help="proposed isolated root (validated, never created)"
    )
    probe.add_argument("--forge-install", type=Path, help="managed Forge install (marker is read)")
    probe.add_argument(
        "--reserve", action="append", default=[], help="a reserved path the root must not overlap"
    )
    probe.add_argument(
        "--vram-baseline-mib", type=float, help="operator-supplied prior quiescent VRAM measurement"
    )
    return parser


def _parse(argv: Sequence[str] | None) -> _Args:
    ns = build_parser().parse_args(list(argv) if argv is not None else None)
    return _Args(
        command=ns.command,
        out=getattr(ns, "out", None),
        models_root=getattr(ns, "models_root", None),
        qualification_root=getattr(ns, "qualification_root", None),
        forge_install=getattr(ns, "forge_install", None),
        reserve=tuple(getattr(ns, "reserve", []) or []),
        hash_files=bool(getattr(ns, "hash_files", False)),
        vram_baseline_mib=getattr(ns, "vram_baseline_mib", None),
    )


def _measure_assets(
    models_root: Path, plan: QualificationManifest, *, hash_files: bool
) -> dict[str, FileMeasurement | None]:
    from .evidence import hash_files as _hash

    measured: dict[str, FileMeasurement | None] = {}
    for role, spec in plan.assets.items():
        path = models_root / spec.models_subdir / spec.filename
        if not path.is_file():
            measured[role] = None
            continue
        digest = _hash([path]).get(path.name) if hash_files else None
        measured[role] = FileMeasurement(spec.filename, path.stat().st_size, digest, None)
    return measured


def _pin_findings(install: Path, plan: QualificationManifest) -> list[Finding]:
    marker: dict[str, Any] = {}
    try:
        marker = json.loads(
            (install / ".stablenew-managed-forge.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        pass
    config_revision: str | None = None
    try:
        root = Path(__file__).resolve().parents[3]
        config = json.loads(
            (root / "config" / "managed_forge_runtime.json").read_text(encoding="utf-8")
        )
        config_revision = str(config["upstream"]["revision"])
    except (OSError, ValueError, KeyError):
        pass
    return verify_runtime_pin(marker.get("revision"), marker.get("status"), config_revision, plan)


def _read_only_inputs(
    args: _Args, plan: QualificationManifest, probe: ProbeResult, clocks: Clocks
) -> PreflightInputs:
    sections: dict[str, list[Finding] | None] = {
        "assets": None,
        "served": None,  # no isolated layout exists in Phase A and none may be created
        "pin": None,
        "intent": verify_intent(plan.intent.request_fields(), plan),
        "isolation": None,
        "endpoint": validate_endpoint(probe.port),
        "processes": validate_process_conflicts(probe.processes),
    }
    if args.models_root is not None:
        sections["assets"] = verify_assets(
            _measure_assets(args.models_root, plan, hash_files=args.hash_files), plan
        )
    if args.forge_install is not None:
        sections["pin"] = _pin_findings(args.forge_install, plan)
    evidence_valid: bool | None = None
    ledger_state: str | None = None
    observations = dict(probe.observations)
    if args.qualification_root is not None:
        reserved = {"repository": str(Path(__file__).resolve().parents[3])}
        reserved.update({f"reserved_{i}": value for i, value in enumerate(args.reserve)})
        if args.forge_install is not None:
            reserved["managed_forge_install"] = str(args.forge_install)
        if args.models_root is not None:
            reserved["model_library"] = str(args.models_root)
        sections["isolation"] = validate_isolation(
            str(args.qualification_root), reserved, RealFs(), manifest=plan
        )
        isolation_codes = {f.code for f in sections["isolation"] if f.severity == "refuse"}
        incomplete = any(
            f.code == "ISOLATION_RESERVED_SET_INCOMPLETE" for f in sections["isolation"]
        )
        evidence_valid = False if isolation_codes else (None if incomplete else True)
        ledger_path = args.qualification_root / "evidence" / "dispatch-ledger.jsonl"
        ledger_state = DispatchLedger(FileLedgerStore(ledger_path)).preflight_state(plan.digest())
        from .probes import probe_evidence_volume

        observations["evidence_volume_free_bytes"] = probe_evidence_volume(
            clocks, args.qualification_root
        )
    if args.vram_baseline_mib is not None:
        observations["vram_quiescent_baseline_bytes"] = Observation(
            "vram_quiescent_baseline_bytes",
            float(args.vram_baseline_mib) * MIB,
            "bytes",
            "operator-supplied prior measurement",
            clocks.mono(),
            clocks.utc(),
        )
    coverage = (
        {
            name: (
                state.coverage
                if (state := probe.fault_snapshot.sources.get(name))
                else NOT_COLLECTED
            )
            for name in ("system_log", "application_log", "wer_reports", "live_kernel", "whea")
        }
        if probe.fault_snapshot is not None
        else None
    )
    return PreflightInputs(
        manifest_digest=plan.digest(),
        sections=sections,
        observations=observations,
        telemetry_coverage=probe.telemetry_coverage,
        fault_baseline_coverage=coverage,
        residual_gpu_risk_accepted=None,
        evidence_dir_valid=evidence_valid,
        ledger_state=ledger_state,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    plan = build_manifest()
    if args.command == "manifest":
        print(json.dumps(plan.as_dict(), indent=2, sort_keys=True))
        return 0
    clocks = Clocks()
    if args.command == "dry-run":
        packet = build_packet(manifest=plan, mode="offline_dry_run")
    else:
        probe = collect_live_observations(clocks)
        inputs = _read_only_inputs(args, plan, probe, clocks)
        result = evaluate_preflight(
            inputs,
            now_mono_s=clocks.mono(),
            now_utc=clocks.utc(),
            policy=PreflightPolicy(),
            manifest=plan,
        )
        packet = build_packet(manifest=plan, preflight=result, probe=probe, mode="live_read_only")
    sys.stdout.write(render_text(packet))
    if args.out is not None:
        if args.out.exists():
            try:
                previous = json.loads(args.out.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = None
            if not isinstance(previous, dict) or previous.get("schema") != PACKET_SCHEMA:
                sys.stderr.write(
                    "refusing to overwrite a file that is not a previous operator packet\n"
                )
                return 2
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
