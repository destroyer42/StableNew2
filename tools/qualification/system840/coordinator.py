"""The campaign coordinator: gates, dispatch through an adapter, archival, verdicts and stop propagation.

Order of gates for one arm stage (each failure returns before anything is dispatched): physical-mode refusal (CI/pytest),
standing and per-target holds, dependency and canary ordering, lane separation, plan validity, readiness, current owner
authorization, then the typed launch.  Only then is the frozen plan saved into a fresh attempt directory and the adapter
called, exactly once.  An ambiguous or failed dispatch is recorded and never retried; a safety stop halts the arm, its
dependents and any later GPU arm of the session, while unrelated accepted evidence is untouched.

The coordinator owns no runtime, queue or runner.  Physical dispatch is the adapter's job; this repository ships a
deterministic ``SimulatedAdapter`` for the dry run and tests, and ``UnwiredAdapter`` which refuses to dispatch anything
(each retained harness keeps its own gates and is run by the operator, see ``next_test.harness`` in the ledger).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from src.utils.atomic_io import atomic_write_json
from tools.operator_journey.golden.modes import running_in_ci, running_under_pytest
from tools.qualification.system840 import evidence, safety, verdict
from tools.qualification.system840 import plan as plan_mod
from tools.qualification.system840.arms import (
    ARM_BY_ID,
    STAGE_CANARY,
    execution_order,
    get_arm,
    lane_class,
)
from tools.qualification.system840.probes import QualProbes
from tools.qualification.system840.statuses import NON_EXECUTABLE, Verdict

RAN, NOT_RUN, HOLD, NO_GO = "RAN", "NOT RUN", "HOLD", "NO-GO"
#: Stops after which no later GPU arm of the session may run (the workstation itself is in doubt).
SAFETY_STOPS = frozenset(
    {
        "device_loss",
        "allocation_failure",
        "host_commit_pressure",
        "low_available_ram",
        "unsafe_teardown",
        "ambiguous_dispatch",
    }
)


class PhysicalRefused(RuntimeError):
    pass


@dataclass
class AdapterOutcome:
    """What a dispatch produced.  ``stop`` names a stop condition when the adapter observed one."""

    observations: dict[str, Any] = field(default_factory=dict)
    files: list[tuple[Path, str, str]] = field(
        default_factory=list
    )  # (source, relative name, role)
    samples: list[dict[str, Any]] = field(default_factory=list)  # telemetry
    metrics: dict[str, Any] = field(default_factory=dict)
    stop: str | None = None


class ArmAdapter(Protocol):
    simulated: bool

    def execute(self, plan: Mapping[str, Any], workdir: Path) -> AdapterOutcome: ...


class UnwiredAdapter:
    """Refuses every dispatch: no physical adapter is wired for the arm (an unbuilt adapter is never assumed runnable)."""

    simulated = False

    def execute(self, plan: Mapping[str, Any], workdir: Path) -> AdapterOutcome:
        raise PhysicalRefused(
            f"no physical adapter is wired for {plan.get('arm_id')}; run the retained harness named in the ledger's next_test"
        )


SCENARIOS = (
    "success",
    "device_loss",
    "oom",
    "timeout",
    "ambiguous_dispatch",
    "telemetry_gap",
    "teardown_unverified",
    "corrupt_media",
    "partial_artifacts",
)


class SimulatedAdapter:
    """Deterministic, CPU-only stand-in used by the dry run and tests.  It never touches a GPU, runtime or network."""

    simulated = True

    def __init__(self, scenario: str = "success", *, wall_seconds: float = 60.0) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        self.scenario, self.wall_seconds = scenario, wall_seconds
        self.calls = 0

    def execute(self, plan: Mapping[str, Any], workdir: Path) -> AdapterOutcome:
        from PIL import Image

        self.calls += 1
        jobs, artifacts = int(plan["jobs"]), int(plan["artifacts"])
        stop = {
            "device_loss": "device_loss",
            "oom": "allocation_failure",
            "timeout": "timeout",
            "ambiguous_dispatch": "ambiguous_dispatch",
        }.get(self.scenario)
        if stop:
            artifacts = 0
        elif self.scenario == "partial_artifacts":
            artifacts = max(0, artifacts - 1)
        samples = [
            {
                "t": float(t),
                "commit_fraction": 0.5,
                "available_ram_mib": 16000,
                "vram_used_mib": 9000,
            }
            for t in range(0, 61, 2)
        ]
        if self.scenario == "telemetry_gap":
            samples = [s for s in samples if not 20 < s["t"] < 40]
        files: list[tuple[Path, str, str]] = []
        for index in range(artifacts):
            path = workdir / f"artifact-{index}.png"
            if self.scenario == "corrupt_media" and index == 0:
                path.write_bytes(b"\x89PNG\r\n\x1a\n not a real image")
            else:
                Image.new("RGB", (16, 16), (index * 40 % 255, 80, 160)).save(path)
            files.append((path, f"artifacts/artifact-{index}.png", "artifact"))
        return AdapterOutcome(
            observations={
                "jobs_admitted": jobs,
                "artifacts": artifacts,
                "identity_verified": True,
                "provenance_complete": True,
                "teardown_clean": self.scenario != "teardown_unverified",
            },
            files=files,
            samples=samples,
            metrics={
                "wall_seconds": self.wall_seconds,
                "artifacts_per_admitted": (artifacts / jobs) if jobs else None,
                "host_commit_fraction_peak": 0.5,
                "gpu_vram_peak_mib": 9000,
                "host_available_ram_min_mib": 16000,
                "operator_interventions": 0,
                "queue_history_consistent": True,
                "error_count": 1 if stop else 0,
                "crash_count": 1 if stop == "device_loss" else 0,
                "timeout_count": 1 if stop == "timeout" else 0,
            },
            stop=stop,
        )


@dataclass
class Session:
    """State shared by the arms of one session: accepted stages, stops and the lane class in use."""

    accepted: set[tuple[str, str]] = field(
        default_factory=set
    )  # (arm_id, stage) passed or previously accepted
    stopped_arms: set[str] = field(default_factory=set)
    gpu_blocked: bool = False
    lane_class: str | None = None
    reports: list[dict[str, Any]] = field(default_factory=list)


def _report(arm_id: str, stage: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"arm_id": arm_id, "stage": stage, "status": status, "reason": reason, **extra}


def _dependents(arm_id: str) -> set[str]:
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for arm in ARM_BY_ID.values():
            if arm.arm_id not in found and (
                arm_id in arm.depends_on or found & set(arm.depends_on)
            ):
                found.add(arm.arm_id)
                changed = True
    return found


def run_stage(
    plan: Mapping[str, Any],
    auth: Mapping[str, Any] | None,
    *,
    adapter: ArmAdapter,
    probes: QualProbes,
    evidence_root: Path | str,
    confirm: Callable[[str], str],
    session: Session,
    ledger: Any | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    verify_hashes: bool = True,
) -> dict[str, Any]:
    """Run one frozen arm stage through every gate.  Returns an arm report; never raises for a refused gate."""

    arm_id, stage = str(plan.get("arm_id")), str(plan.get("stage"))
    if arm_id not in ARM_BY_ID:
        return _report(arm_id, stage, HOLD, f"unknown arm {arm_id!r}")
    arm = get_arm(arm_id)

    if not adapter.simulated and (running_in_ci() or running_under_pytest()):
        return _report(
            arm_id, stage, HOLD, "physical dispatch is refused in CI and under pytest", gates=[]
        )
    refusals = plan_mod.admission_problems(arm, list(plan.get("cases") or []), ledger)
    if refusals:
        return _report(arm_id, stage, HOLD, "; ".join(refusals))
    for dependency in arm.depends_on:
        if dependency in session.stopped_arms:
            return _report(arm_id, stage, HOLD, f"dependency {dependency} stopped in this session")
        if not any(done_arm == dependency for done_arm, _ in session.accepted):
            return _report(arm_id, stage, HOLD, f"dependency {dependency} has no accepted evidence")
    if arm_id in session.stopped_arms:
        return _report(arm_id, stage, HOLD, "this arm already stopped in the session; no retry")
    if stage != STAGE_CANARY and (arm_id, STAGE_CANARY) not in session.accepted:
        return _report(
            arm_id, stage, HOLD, plan_mod.stage_order_problem(stage, False) or "canary required"
        )
    klass = lane_class(arm.lane)
    if session.gpu_blocked and klass == "gpu":
        return _report(
            arm_id, stage, HOLD, "an earlier safety stop blocks every later GPU arm of this session"
        )
    if session.lane_class and klass != "offline" and session.lane_class != klass:
        return _report(
            arm_id, stage, HOLD, f"a session never mixes {session.lane_class} and {klass} work"
        )

    problems = plan_mod.shape_problems(plan)
    if problems:
        return _report(arm_id, stage, HOLD, "plan is not valid: " + "; ".join(problems[:3]))
    ready = safety.readiness(plan, probes, auth=auth, verify_hashes=verify_hashes, now=now())
    if not ready["ready"]:
        failing = [g for g in ready["gates"] if g["status"] != safety.PASS]
        return _report(
            arm_id,
            stage,
            HOLD,
            "; ".join(f"{g['gate']}: {g['detail']}" for g in failing[:4]),
            gates=ready["gates"],
        )
    assert auth is not None  # readiness passes only with an approved authorization
    typed = confirm(plan_mod.launch_phrase(plan))
    launch = plan_mod.launch_problems(plan, auth, typed, now())
    if launch:
        return _report(arm_id, stage, NOT_RUN, "; ".join(launch), gates=ready["gates"])

    session.lane_class = session.lane_class or (klass if klass != "offline" else None)
    attempt = evidence.Attempt.open(evidence_root, dict(plan), now=now())
    workdir = Path(tempfile.mkdtemp(prefix="qual840-"))
    try:
        try:
            outcome = adapter.execute(plan, workdir)
        except PhysicalRefused as exc:
            attempt.write_json(
                "dispatch.json", {"dispatched": False, "refused": str(exc)}, role="dispatch"
            )
            attempt.seal({"dispatched": False, "refused": str(exc), "stop": None}, now=now())
            return _report(arm_id, stage, NOT_RUN, str(exc), attempt=attempt.name)
        except Exception as exc:  # noqa: BLE001 - any adapter failure is a recorded stop, never retried
            stop = (
                safety.classify_stop({"error_message": f"{type(exc).__name__}: {exc}"})
                or "operator_cancel"
            )
            outcome = AdapterOutcome(
                observations={
                    "jobs_admitted": None,
                    "artifacts": None,
                    "teardown_clean": None,
                    "identity_verified": None,
                },
                stop=stop,
            )
            attempt.write_json(
                "dispatch.json",
                {"dispatched": True, "error": f"{type(exc).__name__}: {exc}"},
                role="dispatch",
            )
        return _finish(plan, attempt, outcome, session, auth, now)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _finish(
    plan: Mapping[str, Any],
    attempt: evidence.Attempt,
    outcome: AdapterOutcome,
    session: Session,
    auth: Mapping[str, Any],
    now: Callable[[], datetime],
) -> dict[str, Any]:
    arm_id, stage = str(plan["arm_id"]), str(plan["stage"])
    for source, rel, role in outcome.files:
        attempt.add_file(source, rel, role=role)
    telemetry = safety.evaluate_telemetry(
        outcome.samples, plan.get("limits") or {}, plan.get("telemetry") or {}
    )
    attempt.write_json(
        "telemetry.json", {"samples": outcome.samples, "evaluation": telemetry}, role="telemetry"
    )
    attempt.write_json("authorization.json", dict(auth), role="authorization")
    stop = outcome.stop or telemetry.get("stop")
    media = evidence.validate_media_files(attempt.partial, {"files": attempt.files})
    attempt.write_json("media_validation.json", media, role="media_validation")
    observations = {**outcome.observations, "stop": stop, "telemetry": telemetry}
    attempt.write_json("observations.json", observations, role="observations")
    result = {
        "observations": observations,
        "metrics": outcome.metrics,
        "media_valid": [m["valid"] for m in media],
        "stop": stop,
        "dispatched": True,
    }
    sealed = attempt.seal(result, now=now())
    verification = evidence.verify_attempt(sealed)
    verdicts = verdict.classify_attempt(
        plan, observations, verification=verification, media_reports=media
    )
    path = evidence.write_verdict(sealed, verdicts)
    if stop in SAFETY_STOPS and lane_class(get_arm(arm_id).lane) == "gpu":
        session.gpu_blocked = True
    if stop and stop != "operator_cancel":
        session.stopped_arms.add(arm_id)
        session.stopped_arms |= _dependents(arm_id)
    automated_ok = all(
        verdicts["dimensions"][d]["verdict"] == Verdict.PASS.value
        for d in (
            "functional_correctness",
            "resource_runtime_safety",
            "artifact_media_integrity",
            "reproducibility_provenance",
        )
    )
    if automated_ok:
        session.accepted.add((arm_id, stage))
    status = RAN
    reason = f"dispatched once; overall {verdicts['overall']}"
    if verdicts["dimensions"]["resource_runtime_safety"]["verdict"] == Verdict.NO_GO.value:
        status, reason = NO_GO, "definitive resource refusal of the tested envelope"
    return _report(
        arm_id,
        stage,
        status,
        reason,
        attempt=sealed.name,
        verdict=verdicts,
        verdict_file=str(path),
        stop=stop,
        verification=verification["status"],
    )


def run_campaign(
    plans: list[Mapping[str, Any]],
    auths: Mapping[str, Mapping[str, Any]],
    adapters: Mapping[str, ArmAdapter],
    *,
    probes: QualProbes,
    evidence_root: Path | str,
    confirm: Callable[[str], str],
    ledger: Any | None = None,
    accepted: set[tuple[str, str]] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    verify_hashes: bool = True,
) -> dict[str, Any]:
    """Run frozen plans in dependency order (canary before coverage).  Arms without a plan are reported NOT RUN."""

    session = Session(accepted=set(accepted or ()))
    by_arm: dict[str, list[Mapping[str, Any]]] = {}
    for plan in plans:
        by_arm.setdefault(str(plan["arm_id"]), []).append(plan)
    order = execution_order(list(by_arm))
    for arm_id in order:
        for stage_plan in sorted(
            by_arm[arm_id], key=lambda p: 0 if p.get("stage") == STAGE_CANARY else 1
        ):
            auth = auths.get(f"{arm_id}/{stage_plan.get('stage')}")
            adapter = adapters.get(arm_id) or UnwiredAdapter()
            session.reports.append(
                run_stage(
                    stage_plan,
                    auth,
                    adapter=adapter,
                    probes=probes,
                    evidence_root=evidence_root,
                    confirm=confirm,
                    session=session,
                    ledger=ledger,
                    now=now,
                    verify_hashes=verify_hashes,
                )
            )
    for arm_id in ARM_BY_ID:
        if arm_id in by_arm:
            continue
        arm = get_arm(arm_id)
        whole_arm_holds = [h.hold_id for h in arm.holds if not h.targets]
        if (
            ledger is not None
            and ledger.for_arm(arm_id)
            and all(e.status in NON_EXECUTABLE for e in ledger.for_arm(arm_id))
        ):
            ids = sorted({h for e in ledger.for_arm(arm_id) for h in e.data.get("holds", [])})
            session.reports.append(
                _report(
                    arm_id,
                    "-",
                    HOLD,
                    "every capability is held in the ledger: " + (", ".join(ids) or "see ledger"),
                )
            )
        elif whole_arm_holds:
            session.reports.append(
                _report(arm_id, "-", HOLD, "standing hold: " + "; ".join(whole_arm_holds))
            )
        elif not arm.physical:
            session.reports.append(
                _report(
                    arm_id, "-", NOT_RUN, "offline arm: assessed from the ledger, nothing executes"
                )
            )
        else:
            session.reports.append(_report(arm_id, "-", NOT_RUN, "no frozen plan was supplied"))
    counts: dict[str, int] = {}
    for report in session.reports:
        counts[report["status"]] = counts.get(report["status"], 0) + 1
    return {
        "reports": session.reports,
        "counts": counts,
        "promotion": "NOT AUTHORIZED",
        "ledger_changed": False,
        "stopped_arms": sorted(session.stopped_arms),
    }


def write_campaign_report(report: Mapping[str, Any], out: Path | str) -> Path:
    out = Path(out)
    if out.exists():
        raise evidence.ArchiveRefused(f"{out} already exists; reports are not overwritten")
    out.parent.mkdir(parents=True, exist_ok=True)
    return atomic_write_json(
        out, json.loads(json.dumps(report, default=str)), indent=2, sort_keys=True
    )
