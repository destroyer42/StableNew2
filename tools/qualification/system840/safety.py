"""Pre-arm safety preflight and stop-condition classification (pure logic over injected probes).

The eight gates mirror the campaign contract: fresh readiness and endpoint ownership, no incompatible active generation,
source/runtime identity, host and GPU and disk budgets, telemetry and fault collection, no unresolved prior safety stop, the
exact authorization with a typed launch, and the frozen plan saved before dispatch.  A gate is PASS, FAIL (a violated
condition) or HOLD (something that cannot be established); any non-PASS gate keeps the arm from dispatching.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.qualification.system840 import plan as plan_mod
from tools.qualification.system840.arms import get_arm, lane_class
from tools.qualification.system840.probes import QualProbes

PASS, FAIL, HOLD = "PASS", "FAIL", "HOLD"
GIB = 1024**3

#: Ordered, matched against job rows, log lines and runtime errors.  Each class stops the arm; none is retried.
_STOP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "device_loss",
        re.compile(
            r"device[ -]?lost|cuda error|illegal memory access|gpu has fallen|nvml|device-side assert",
            re.I,
        ),
    ),
    (
        "allocation_failure",
        re.compile(
            r"out of memory|\boom\b|cuda out of memory|allocation fail|commit (limit|charge)", re.I
        ),
    ),
    ("timeout", re.compile(r"timed? ?out|timeout|wall.?clock limit", re.I)),
    ("ambiguous_dispatch", re.compile(r"dispatchoutcomeunknown|ambiguous|outcome unknown", re.I)),
)
#: Stops that, with intact telemetry and verified identity, are a definitive refusal of the tested envelope.
RESOURCE_STOPS = frozenset(
    {"device_loss", "allocation_failure", "host_commit_pressure", "low_available_ram"}
)


@dataclass(frozen=True)
class Gate:
    gate_id: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"gate": self.gate_id, "status": self.status, "detail": self.detail}


def classify_stop(row: Mapping[str, Any]) -> str | None:
    """Name the stop condition a job/runtime record shows, or ``None``.  A retry or requeue means an uncertain dispatch."""

    text = f"{row.get('error_message') or ''} {row.get('error') or ''}"
    for name, pattern in _STOP_PATTERNS:
        if pattern.search(text):
            return name
    if int(row.get("retry_attempts") or 0) or int(row.get("return_to_queue_count") or 0):
        return "ambiguous_dispatch"
    return None


def _worst(gates: Sequence[Gate]) -> str:
    statuses = {g.status for g in gates}
    return FAIL if FAIL in statuses else HOLD if HOLD in statuses else PASS


def evaluate_telemetry(
    samples: Sequence[Mapping[str, Any]], limits: Mapping[str, Any], telemetry: Mapping[str, Any]
) -> dict[str, Any]:
    """Judge recorded samples against the frozen limits.  Returns the first violated stop condition or ``None``.

    Each sample carries ``t`` (seconds), optional ``commit_fraction``, ``available_ram_mib``, ``vram_used_mib`` and
    ``device_loss``.  A gap longer than ``max_gap_seconds`` or availability below the frozen fraction is a telemetry gap.
    """

    ordered = sorted(samples, key=lambda s: float(s.get("t", 0)))
    result: dict[str, Any] = {"stop": None, "detail": "", "samples": len(ordered)}
    if not ordered:
        return {**result, "stop": "telemetry_gap", "detail": "no telemetry samples were recorded"}
    max_gap = float(telemetry.get("max_gap_seconds") or 5.0)
    cadence = float(telemetry.get("cadence_seconds") or 2.0)
    previous = float(ordered[0].get("t", 0))
    for sample in ordered[1:]:
        now = float(sample.get("t", 0))
        if now - previous > max_gap:
            return {
                **result,
                "stop": "telemetry_gap",
                "detail": f"telemetry silent for {now - previous:.1f}s",
            }
        previous = now
    span = float(ordered[-1].get("t", 0)) - float(ordered[0].get("t", 0))
    expected = span / cadence + 1 if cadence else len(ordered)
    availability = min(1.0, len(ordered) / expected) if expected else 1.0
    if availability < float(telemetry.get("required_availability") or 0):
        return {
            **result,
            "stop": "telemetry_gap",
            "detail": f"availability {availability:.2f} below the frozen minimum",
        }
    min_ram = float(limits.get("min_available_ram_gb") or 0) * 1024
    for sample in ordered:
        if sample.get("device_loss"):
            return {
                **result,
                "stop": "device_loss",
                "detail": f"device loss at t={sample.get('t')}",
            }
        if (
            limits.get("max_commit_gb")
            and sample.get("commit_fraction") is not None
            and sample["commit_fraction"] >= 0.95
        ):
            return {
                **result,
                "stop": "host_commit_pressure",
                "detail": f"commit fraction {sample['commit_fraction']}",
            }
        if (
            min_ram
            and sample.get("available_ram_mib") is not None
            and sample["available_ram_mib"] < min_ram
        ):
            return {
                **result,
                "stop": "low_available_ram",
                "detail": f"available RAM {sample['available_ram_mib']} MiB",
            }
        if (
            limits.get("max_vram_used_mib")
            and (sample.get("vram_used_mib") or 0) > limits["max_vram_used_mib"]
        ):
            return {
                **result,
                "stop": "allocation_failure",
                "detail": f"VRAM {sample['vram_used_mib']} MiB over the limit",
            }
    return result


def ai_gates(plan: Mapping[str, Any], probes: QualProbes) -> list[Gate]:
    """CPU inference lanes: yield to GPU generation, and never run without a protected, active, canary-proven capture.

    A missing protected capture or an incompatible runtime is a HOLD, not an invitation to disable the guard.  Smart Review
    (``cpu_smart_review``) needs only its verified per-child memory limit; Offline AI Assist needs the full capture.
    """

    arm = get_arm(str(plan["arm_id"]))
    if lane_class(arm.lane) != "cpu_inference":
        return []
    gates: list[Gate] = []
    active = probes.gpu_activity()
    gates.append(
        Gate(
            "ai_yields_to_generation",
            FAIL,
            f"{len(active)} GPU generation(s) active; CPU inference never mixes with GPU work",
        )
        if active
        else Gate("ai_yields_to_generation", PASS, "no GPU generation active")
    )
    state = probes.ai_capture_state() or {}
    if arm.lane == "cpu_smart_review":
        verified = state.get("child_memory_limit_verified") is True
        gates.append(
            Gate("child_memory_limit", PASS, "the per-child memory limit is verified")
            if verified
            else Gate(
                "child_memory_limit",
                HOLD,
                "the per-child memory limit is not verified on this host",
            )
        )
        return gates
    if not state:
        gates.append(
            Gate(
                "ai_capture",
                HOLD,
                "no capture state is readable: a missing protected capture is a HOLD",
            )
        )
        return gates
    gates.append(
        Gate("protected_interpreter", PASS, "protected interpreter attested")
        if state.get("protected_interpreter") is True
        else Gate(
            "protected_interpreter",
            HOLD,
            "the capture was not started from a protected interpreter",
        )
    )
    gates.append(
        Gate("capture_active", PASS, "a capture session is ACTIVE")
        if state.get("active") is True
        else Gate("capture_active", HOLD, "no ACTIVE capture session")
    )
    age = state.get("canary_pass_age_hours")
    gates.append(
        Gate("canary_proof", PASS, f"canary passed {age:.1f} h ago")
        if isinstance(age, (int, float)) and 0 <= age < 24
        else Gate("canary_proof", HOLD, "no passing canary capture under 24 h old")
    )
    return gates


def readiness(
    plan: Mapping[str, Any],
    probes: QualProbes,
    *,
    auth: Mapping[str, Any] | None,
    verify_hashes: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the pre-dispatch gates.  ``ready`` is true only when every gate passes."""

    arm = get_arm(str(plan["arm_id"]))
    gates: list[Gate] = []
    runtime = plan.get("runtime") or {}
    limits = plan.get("limits") or {}

    # 1. Fresh readiness and current endpoint ownership.
    base_url = runtime.get("base_url") or ""
    info: dict[str, Any] = {}
    if arm.gpu and base_url:
        info = probes.endpoint(base_url, str(runtime.get("kind")))
        state = info.get("state")
        if runtime.get("ownership") == "external":
            if state == "healthy":
                gates.append(
                    Gate(
                        "endpoint_ready",
                        PASS,
                        f"external {base_url} answers; observed through its API only",
                    )
                )
            elif state == "occupied":
                gates.append(
                    Gate(
                        "endpoint_ownership",
                        FAIL,
                        f"{base_url} is occupied by something that is not the expected API",
                    )
                )
            else:
                gates.append(
                    Gate(
                        "endpoint_ready",
                        HOLD,
                        f"external {base_url} is not running; StableNew never starts it",
                    )
                )
        else:  # managed: the production process manager launches and owns it; the port must not be held by a stranger
            if state == "occupied":
                gates.append(
                    Gate(
                        "endpoint_ownership",
                        FAIL,
                        f"{base_url} is held by a process StableNew does not own",
                    )
                )
            else:
                gates.append(
                    Gate("endpoint_ready", PASS, f"managed {base_url} is free or already healthy")
                )
        expected = runtime.get("version")
        if expected and info.get("version") not in (None, expected):
            gates.append(
                Gate(
                    "runtime_identity",
                    FAIL,
                    f"live {info.get('version')!r} != planned {expected!r}",
                )
            )
    elif arm.gpu:
        gates.append(Gate("endpoint_ready", HOLD, "the plan names no runtime base_url"))
    else:
        gates.append(Gate("endpoint_ready", PASS, "CPU lane: no GPU runtime endpoint"))

    frozen_flags = runtime.get("launch_flags")
    if frozen_flags:
        live_flags = probes.launch_flags(dict(runtime))
        if live_flags is None:
            gates.append(Gate("launch_flags", HOLD, "the runtime's launch flags cannot be read"))
        elif sorted(live_flags) != sorted(frozen_flags):
            gates.append(
                Gate(
                    "launch_flags",
                    FAIL,
                    f"live flags {sorted(live_flags)} != frozen {sorted(frozen_flags)}",
                )
            )
        else:
            gates.append(Gate("launch_flags", PASS, "launch flags match the frozen plan"))

    # 2. No incompatible active generation (never mix GPU with CPU inference, never two GPU generations).
    if arm.gpu and base_url:
        active = probes.active_generations(base_url)
        busy_jobs = int(info.get("busy_jobs") or 0) + len(active)
        gates.append(
            Gate("no_active_generation", FAIL, f"{busy_jobs} active generation(s) on {base_url}")
            if busy_jobs
            else Gate("no_active_generation", PASS, "no active generation")
        )
    else:
        busy = [
            p.get("name")
            for p in probes.processes()
            if str(p.get("name", "")).lower().startswith(("python", "llama"))
        ]
        gates.append(
            Gate(
                "quiet_host",
                PASS,
                "no competing inference process observed" if not busy else "host is shared",
            )
        )

    # 3. Source, runtime and plan identities.
    diffs = plan_mod.environment_diffs(plan, probes) if verify_hashes else []
    gates.append(
        Gate("identity_frozen", FAIL, "; ".join(diffs[:4]))
        if diffs
        else Gate(
            "identity_frozen",
            PASS,
            "repository, model, source and runtime identities match the frozen plan",
        )
    )

    # 4. Host memory, system commit, GPU memory and disk budgets.
    memory = probes.memory()
    if memory is None:
        gates.append(Gate("host_memory", HOLD, "host memory is unreadable"))
    else:
        avail = float(memory.get("available_gb", 0) or 0)
        commit_used = memory.get("commit_used_gb")
        need_ram = float(limits.get("min_available_ram_gb") or 0)
        if avail < need_ram:
            gates.append(
                Gate(
                    "host_memory", FAIL, f"{avail:.1f} GiB available < required {need_ram:.1f} GiB"
                )
            )
        elif commit_used is not None and float(commit_used) >= float(
            limits.get("max_commit_gb") or 0
        ):
            gates.append(
                Gate(
                    "host_commit",
                    FAIL,
                    f"commit {float(commit_used):.1f} GB is already at the {limits.get('max_commit_gb')} GB ceiling",
                )
            )
        else:
            gates.append(Gate("host_memory", PASS, f"{avail:.1f} GiB available"))
    if arm.gpu:
        gpu = probes.gpu()
        if gpu is None:
            gates.append(Gate("gpu_memory", HOLD, "GPU telemetry is unavailable"))
        elif float(gpu.get("used_mib", 0)) > float(limits.get("max_vram_used_mib") or 0):
            gates.append(
                Gate(
                    "gpu_memory", FAIL, f"{gpu.get('used_mib')} MiB already in use before dispatch"
                )
            )
        else:
            gates.append(Gate("gpu_memory", PASS, f"{gpu.get('used_mib', 0)} MiB in use"))
    free = probes.disk_free_gb(Path(str(plan.get("evidence_dir") or ".")))
    if free is None:
        gates.append(Gate("disk_space", HOLD, "free disk space is unreadable"))
    elif free < float(limits.get("min_free_disk_gb") or 0):
        gates.append(
            Gate("disk_space", FAIL, f"{free:.1f} GiB free < {limits.get('min_free_disk_gb')} GiB")
        )
    else:
        gates.append(Gate("disk_space", PASS, f"{free:.1f} GiB free"))

    # 5. Telemetry and fault collection.
    gates.append(
        Gate("telemetry", PASS, "sampler available")
        if probes.telemetry_available()
        else Gate("telemetry", HOLD, "the telemetry sampler cannot produce a sample")
    )
    gates.append(
        Gate("fault_collection", PASS, "fault collection writable")
        if probes.fault_collection_available()
        else Gate("fault_collection", HOLD, "fault collection is unavailable")
    )

    # 6. Unresolved prior safety stops.
    stops = probes.unresolved_stops()
    relevant = [s for s in stops if s.get("lane") in (None, plan.get("lane"))]
    gates.append(
        Gate(
            "prior_safety_stops",
            HOLD,
            f"{len(relevant)} unresolved prior stop(s): {relevant[0].get('stop')}",
        )
        if relevant
        else Gate("prior_safety_stops", PASS, "no unresolved prior safety stop")
    )

    gates += ai_gates(plan, probes)

    # 7. Exact authorization (the typed launch is a separate act performed by the coordinator).
    auth_problems = plan_mod.authorization_problems(plan, auth, now)
    gates.append(
        Gate("authorization", HOLD, "; ".join(auth_problems[:3]))
        if auth_problems
        else Gate(
            "authorization", PASS, "an approved authorization names this digest, arm and model"
        )
    )

    # 8. Plan shape (the frozen plan is saved by the coordinator immediately before dispatch).
    shape = plan_mod.shape_problems(plan)
    gates.append(
        Gate("plan_valid", FAIL, "; ".join(shape[:4]))
        if shape
        else Gate("plan_valid", PASS, "plan is complete and unmodified")
    )

    overall = _worst(gates)
    return {"ready": overall == PASS, "status": overall, "gates": [g.as_dict() for g in gates]}
