"""Mode C: gated physical execution.  Disabled by default; fails closed.

Order of gates (each failure returns before anything starts): mode/CI/pytest refusal (``modes``), plan shape, current
owner authorization of *this* digest, live environment equal to the frozen one, read-only readiness PASS, and a
deliberate launch action: the digest-naming phrase typed at a live console, or, only when the owner's authorization delegates
the launch, the same phrase passed by the named delegate (once per digest; recorded as such in the evidence).  Only then are journeys driven through the visible
Windows desktop, under a telemetry monitor that trips on the plan's own limits.

The harness never starts, stops, adopts or restarts a runtime: a Forge endpoint is external (API only); managed Comfy is
launched, owned and released by the production backend and its process manager.  An ambiguous or failed dispatch is
reported and never retried.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from tools.operator_journey.evidence import FAIL, HOLD, NO_GO, PASS, JourneyEvidence
from tools.operator_journey.golden.definitions import JourneyDef
from tools.operator_journey.golden.host import HostProbes
from tools.operator_journey.golden.modes import PHYSICAL
from tools.operator_journey.golden.plan import (
    authorization_problems,
    environment_diffs,
    load_plan,
    shape_problems,
)
from tools.operator_journey.golden.readiness import ReadinessContext, evaluate_readiness

QUALITY_PENDING = "PENDING_OPERATOR_REVIEW"
_FAILURE_CLASSES = (
    (
        "device_loss",
        re.compile(r"device[ -]?lost|cuda error|illegal memory access|gpu has fallen|nvml", re.I),
    ),
    ("oom", re.compile(r"out of memory|\boom\b|cuda out of memory|allocation", re.I)),
    ("timeout", re.compile(r"timed? ?out|timeout", re.I)),
    ("ambiguous_dispatch", re.compile(r"dispatchoutcomeunknown|ambiguous|outcome unknown", re.I)),
)


def confirmation_phrase(plan: dict[str, Any]) -> str:
    return f"RUN {str(plan.get('digest'))[:12]}"


def delegated_launch_problems(plan: dict[str, Any], phrase: str) -> list[str]:
    """A launch without a person at the console is allowed only when the owner's authorization delegates it.

    The authorization block (excluded from the digest, like the approval itself) must carry
    ``launch = {"mode": "delegated", "delegate": ..., "owner_instruction": ...}``: who may launch and the owner's own words
    granting it.  The delegate must still pass the exact digest-naming phrase, so a launch is never an accident of a flag.
    """

    launch = (plan.get("authorization") or {}).get("launch") or {}
    problems: list[str] = []
    if launch.get("mode") != "delegated":
        problems.append(
            "the authorization does not delegate the launch (authorization.launch.mode != 'delegated')"
        )
    if not str(launch.get("delegate") or "").strip():
        problems.append("the authorization names no delegate")
    if not str(launch.get("owner_instruction") or "").strip():
        problems.append("the authorization quotes no owner instruction for the delegation")
    if str(phrase).strip() != confirmation_phrase(plan):
        problems.append("the launch phrase does not name this plan digest")
    return problems


def delegated_launch_marker(plan: dict[str, Any], plan_path: Path) -> Path:
    return plan_path.parent / f"{str(plan.get('digest'))[:12]}.delegated-launch.json"


def consume_delegated_launch(plan: dict[str, Any], plan_path: Path) -> Path:
    """Record the single delegated launch of this digest.  Raises ``FileExistsError`` if it was already used."""

    marker = delegated_launch_marker(plan, plan_path)
    launch = plan["authorization"]["launch"]
    with marker.open(
        "x", encoding="utf-8"
    ) as handle:  # exclusive create: a second launch can never pass
        json.dump(
            {
                "digest": plan["digest"],
                "delegate": launch["delegate"],
                "owner_instruction": launch["owner_instruction"],
                "approved_by": plan["authorization"].get("approved_by"),
                "consumed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            handle,
            indent=2,
        )
    return marker


def classify_job_failure(row: dict[str, Any]) -> str | None:
    """Name the stop condition a job row shows, or ``None``.  Every class is a NO-GO and is never retried."""

    text = f"{row.get('error_message') or ''}"
    for name, pattern in _FAILURE_CLASSES:
        if pattern.search(text):
            return name
    if int(row.get("retry_attempts") or 0) or int(row.get("return_to_queue_count") or 0):
        return "ambiguous_dispatch"  # a retry or requeue means a dispatch was uncertain; never auto-replayed
    return None


class ResourceMonitor:
    """Samples GPU and host telemetry against the plan's limits; the first violation trips it (never recovers)."""

    def __init__(
        self,
        limits: dict[str, Any],
        probes: HostProbes,
        telemetry_path: Path,
        *,
        interval: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits, self.probes, self.path, self.interval, self._clock = (
            limits,
            probes,
            telemetry_path,
            interval,
            clock,
        )
        self.tripped: str | None = None
        self.peaks = {"vram_used_mib": 0.0, "commit_gb": 0.0, "min_available_ram_gb": float("inf")}
        self.samples = 0
        self._t0 = clock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="golden-telemetry", daemon=True)

    def sample_once(self) -> dict[str, Any]:
        gpu, memory = self.probes.gpu(), self.probes.memory()
        elapsed = self._clock() - self._t0
        record: dict[str, Any] = {"t": round(elapsed, 2), "gpu": gpu, "memory": memory}
        reason = None
        if gpu is None:
            reason = "GPU telemetry became unavailable"
        elif memory is None:
            reason = "host memory telemetry became unavailable"
        else:
            self.peaks["vram_used_mib"] = max(self.peaks["vram_used_mib"], gpu["used_mib"])
            self.peaks["commit_gb"] = max(self.peaks["commit_gb"], memory["commit_used_gb"])
            self.peaks["min_available_ram_gb"] = min(
                self.peaks["min_available_ram_gb"], memory["available_gb"]
            )
            if gpu["used_mib"] > self.limits["max_vram_used_mib"]:
                reason = f"VRAM {gpu['used_mib']:.0f} MiB exceeds the plan limit {self.limits['max_vram_used_mib']}"
            elif memory["available_gb"] < self.limits["min_available_ram_gb"]:
                reason = f"available RAM {memory['available_gb']:.1f} GB is below the plan floor"
            elif memory["commit_used_gb"] > self.limits["max_commit_gb"]:
                reason = f"system commit {memory['commit_used_gb']:.1f} GB exceeds the plan ceiling"
        if reason is None and elapsed > self.limits["timeout_seconds"]:
            reason = f"execution exceeded the plan timeout of {self.limits['timeout_seconds']} s"
        if reason and self.tripped is None:
            self.tripped = reason
            record["tripped"] = reason
        self.samples += 1
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        return record

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(self.interval)

    def __enter__(self) -> ResourceMonitor:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sample_once()
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.sample_once()


def default_confirm(prompt: str) -> str:
    if not sys.stdin or not sys.stdin.isatty():
        return ""  # a non-interactive session can never be a deliberate launch action
    return input(prompt)


def real_executor(
    journey: JourneyDef, target: dict[str, Any], monitor: ResourceMonitor, run_dir: Path
) -> JourneyEvidence:
    """Drive one journey through the visible Windows desktop against the real backend named by the plan."""

    from tools.operator_journey.golden.session import RunConfig, run_journey_body

    config = RunConfig(
        driver="windows",
        evidence_dir=run_dir / "journeys",
        run_timeout=float(target.get("timeout", 900)),
        startup_wait=120.0,
    )
    config.extras.update(
        physical=True,
        abort_check=lambda: monitor.tripped,
        target=target,
        journey_key=journey.key,
    )
    base_url = target["runtime"]["base_url"]
    settings = _engine_settings(target)
    if journey.key == "image":
        from tools.operator_journey.golden.img01 import run_img01

        body = lambda run: run_img01(run, simulated=False, physical=target)  # noqa: E731
    elif journey.key == "video":
        from tools.operator_journey.golden.vid01 import run_vid01

        body = lambda run: run_vid01(run, simulated=False, physical=target)  # noqa: E731
    else:
        from tools.operator_journey.golden.lrn01 import run_lrn01

        body = lambda run: run_lrn01(run, simulated=False, physical=target)  # noqa: E731
    return run_journey_body(
        journey.id,
        body,
        config,
        mode_label="physical",
        base_url=base_url,
        settings_extra=settings,
        execution_mode="physical",
    )


def _engine_settings(target: dict[str, Any]) -> dict[str, Any]:
    """Read-only copy of the operator's engine settings into the disposable workspace (never written back)."""

    from tools.operator_journey.workspace import REPO_ROOT

    try:
        real = json.loads((REPO_ROOT / "presets" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        real = {}
    kind = target["runtime"]["kind"]
    keep = {k: v for k, v in real.items() if k.startswith("comfy_")}
    keep.update(
        webui_runtime_identity="forge_webui"
        if kind == "forge"
        else real.get("webui_runtime_identity", "forge_webui"),
        webui_base_url=target["runtime"]["base_url"]
        if kind == "forge"
        else real.get("webui_base_url"),
        webui_autostart_enabled=False,  # the harness never launches Forge; ownership is external
        comfy_autostart_enabled=target["runtime"]["ownership"] == "managed",
    )
    return keep


def run_physical(
    plan_path: Path,
    *,
    journeys: list[JourneyDef],
    evidence_root: Path,
    confirm: Callable[[str], str] | None = None,
    ctx: ReadinessContext | None = None,
    executor: Callable[..., JourneyEvidence] | None = None,
    probes: HostProbes | None = None,
    launch_phrase: str | None = None,
) -> tuple[str, Path]:
    from tools.operator_journey.golden.suite import new_run_dir, redact, write_run_evidence

    ctx = ctx or ReadinessContext(probes=probes or HostProbes())
    probes = ctx.probes
    run_dir = new_run_dir(evidence_root, PHYSICAL)
    outcome: dict[str, Any] = {
        "physical_execution": "NOT RUN",
        "functional": None,
        "safety": None,
        "visual_quality": QUALITY_PENDING,
    }

    def finish(
        verdict: str,
        reason: str,
        plan: dict[str, Any] | None = None,
        results: list[JourneyEvidence] | None = None,
    ) -> tuple[str, Path]:
        outcome.update(verdict=verdict, reason=reason)
        write_run_evidence(
            run_dir,
            plan=plan or {},
            results=results or [],
            mode=PHYSICAL,
            driver="windows",
            extra={"outcomes": outcome},
            verdict=verdict,
        )
        (run_dir / "summary.md").write_text(
            redact(
                f"# Physical golden paths: {verdict}\n\n{reason}\n\n- Physical execution: {outcome['physical_execution']}\n"
                f"- Operator workflow correctness: {outcome['functional']}\n- Resource/runtime safety: {outcome['safety']}\n"
                f"- Visual output quality: {outcome['visual_quality']} (a run that completes but is unreviewed is not a "
                "complete quality-acceptance PASS)\n"
            ),
            "utf-8",
        )
        return verdict, run_dir

    try:
        plan = load_plan(plan_path)
    except (OSError, ValueError) as exc:
        return finish(HOLD, f"the plan cannot be read: {exc}")
    problems = shape_problems(plan)
    if problems:
        return finish(HOLD, "frozen plan invalid: " + "; ".join(problems), plan)
    wanted = [j.key for j in journeys]
    missing = [k for k in wanted if k not in plan["targets"]]
    if missing:
        return finish(HOLD, f"the plan does not contain journeys: {', '.join(missing)}", plan)
    auth = authorization_problems(plan, wanted)
    if auth:
        return finish(HOLD, "not authorized: " + "; ".join(auth), plan)
    diffs = environment_diffs(plan, probes)
    if diffs:
        return finish(
            HOLD,
            "the environment changed since the plan was frozen (renew authorization): "
            + "; ".join(diffs),
            plan,
        )
    report = evaluate_readiness(plan, ctx)
    if report["verdict"] != PASS:
        bad = [f"{g['id']}: {g['detail']}" for g in report["gates"] if g["state"] != PASS]
        return finish(
            report["verdict"],
            "physical readiness is " + report["verdict"] + ": " + "; ".join(bad),
            plan,
        )
    phrase = confirmation_phrase(plan)
    if launch_phrase is not None:
        delegated = delegated_launch_problems(plan, launch_phrase)
        if delegated:
            return finish(HOLD, "delegated launch refused: " + "; ".join(delegated), plan)
        try:
            consume_delegated_launch(plan, plan_path)
        except FileExistsError:
            return finish(
                HOLD,
                "delegated launch refused: this plan digest was already launched by delegation (one launch per authorization; "
                "renew the authorization and freeze a new plan)",
                plan,
            )
        outcome["launch"] = {
            "method": "delegated",
            "delegate": plan["authorization"]["launch"]["delegate"],
            "owner_instruction": plan["authorization"]["launch"]["owner_instruction"],
        }
    else:
        answer = (confirm or default_confirm)(
            f"Physical GPU execution of {', '.join(wanted)} under plan {plan['digest'][:12]}.\nType '{phrase}' to launch: "
        )
        if str(answer).strip() != phrase:
            return finish(
                HOLD,
                "no deliberate operator launch action (the confirmation phrase was not typed)",
                plan,
            )
        outcome["launch"] = {"method": "typed"}

    results: list[JourneyEvidence] = []
    run_executor = executor or real_executor
    outcome["physical_execution"] = "RAN"
    with ResourceMonitor(plan["limits"], probes, run_dir / "resource_telemetry.jsonl") as monitor:
        for journey in journeys:
            if monitor.tripped:
                break
            if environment_diffs(plan, probes):  # immediately before each journey
                return finish(
                    HOLD, "the environment changed during the run; stopped", plan, results
                )
            try:
                ev = run_executor(journey, plan["targets"][journey.key], monitor, run_dir)
            except (
                Exception
            ) as exc:  # an executor crash is a NO-GO with evidence, never a lost run directory
                outcome["functional"] = FAIL
                outcome["safety"] = NO_GO
                return finish(
                    NO_GO,
                    f"the executor raised during {journey.key}: {type(exc).__name__}: {exc} (never retried)",
                    plan,
                    results,
                )
            results.append(ev)
            stop = next((c for c in (classify_job_failure(r) for r in _job_rows(ev)) if c), None)
            if stop:
                monitor.tripped = monitor.tripped or f"stop condition: {stop} (never retried)"
    outcome["peaks"] = monitor.peaks
    outcome["functional"] = PASS if results and all(r.verdict == PASS for r in results) else FAIL
    outcome["safety"] = NO_GO if monitor.tripped else PASS
    if monitor.tripped:
        return finish(NO_GO, monitor.tripped, plan, results)
    verdict = PASS if outcome["functional"] == PASS else FAIL
    return finish(
        verdict,
        "functional and safety checks complete; visual quality still needs operator review",
        plan,
        results,
    )


def _job_rows(ev: JourneyEvidence) -> list[dict[str, Any]]:
    return [
        o["value"]
        for o in ev.observations
        if o["name"] == "job_row" and isinstance(o["value"], dict)
    ]


__all__ = [
    "classify_job_failure",
    "confirmation_phrase",
    "run_physical",
    "ResourceMonitor",
    "nullcontext",
]
