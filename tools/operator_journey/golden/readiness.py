"""Mode B: read-only physical readiness.  Reports PASS, HOLD or NO-GO and never starts a model runtime.

HOLD means a prerequisite is unfulfilled or the frozen plan no longer describes the world (renew and re-freeze).
NO-GO means a safety or resource condition forbids execution.  Every threshold comes from the plan's own limits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tools.operator_journey.golden.host import HostProbes
from tools.operator_journey.golden.plan import (
    authorization_problems,
    environment_diffs,
    shape_problems,
)

PASS = "PASS"
HOLD = "HOLD"
NO_GO = "NO-GO"
_RANK = {PASS: 0, HOLD: 1, NO_GO: 2}
SUPPORTED_PYTHON_PREFIX = "3.14."


@dataclass(frozen=True)
class Gate:
    id: str
    state: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "state": self.state, "detail": self.detail}


@dataclass
class ReadinessContext:
    """Collaborators beyond raw host probes; each is read-only and replaceable in tests."""

    probes: HostProbes = field(default_factory=HostProbes)
    #: workflow_id, version -> (governance_state, required launch flags)
    workflow_info: Callable[[str, str], tuple[str, tuple[str, ...]]] | None = None
    #: () -> {"command": [...], "environment_command": [...], "contract_problems": [...], "required_flags": [...]}
    comfy_launch: Callable[[], dict[str, Any]] | None = None
    #: () -> pinned managed-Forge identity string from config
    forge_identity: Callable[[], str] | None = None
    #: video preflight gates for (workflow_id, version): list of (gate id, state, detail), states ok/blocked/unknown
    video_gates: Callable[[str, str], list[tuple[str, str, str]]] | None = None


def default_workflow_info(workflow_id: str, version: str) -> tuple[str, tuple[str, ...]]:
    from src.video.workflow_readiness import required_launch_flags
    from src.video.workflow_registry import build_default_workflow_registry

    spec = build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)
    return str(spec.governance_state), tuple(required_launch_flags(spec))


def default_comfy_launch() -> dict[str, Any]:
    from src.video.comfy_process_manager import read_comfy_launch_facts
    from src.video.managed_comfy_runtime import detect_managed_comfy, load_managed_comfy_contract

    facts = read_comfy_launch_facts()
    contract = load_managed_comfy_contract()
    detection = detect_managed_comfy(contract)
    return {
        "command": list(facts.effective_command),
        "environment_command": list(facts.environment_command),
        "saved_command": list(facts.saved_command),
        "contract_problems": list(detection.problems),
        "identity": f"comfyui {contract.release} {contract.version}",
        "required_flags": list(contract.required_flags),
    }


def default_forge_identity() -> str:
    import json

    from tools.operator_journey.workspace import REPO_ROOT

    data = json.loads(
        (REPO_ROOT / "config" / "managed_forge_runtime.json").read_text(encoding="utf-8")
    )
    upstream = data.get("upstream") or {}
    return f"{data.get('runtime_identity')}@{str(upstream.get('revision'))[:12]}"


def _resource_gates(plan: dict[str, Any], probes: HostProbes) -> list[Gate]:
    limits = plan.get("limits") or {}
    gates: list[Gate] = []
    gpu = probes.gpu()
    if gpu is None:
        gates.append(
            Gate(
                "gpu_telemetry",
                NO_GO,
                "GPU telemetry is unavailable (nvidia-smi); safety cannot be established",
            )
        )
    else:
        used, cap = gpu["used_mib"], limits.get("max_vram_used_mib", 0)
        gates.append(
            Gate(
                "gpu_idle_vram",
                PASS if used <= cap else NO_GO,
                f"{gpu['name']}: {used:.0f} MiB in use before the run (plan allows {cap} MiB)",
            )
        )
    memory = probes.memory()
    if memory is None:
        gates.append(
            Gate("host_memory_telemetry", NO_GO, "host memory/commit telemetry is unavailable")
        )
    else:
        available, floor = memory["available_gb"], limits.get("min_available_ram_gb", 0)
        gates.append(
            Gate(
                "host_available_ram",
                PASS if available >= floor else NO_GO,
                f"{available:.1f} GB available (plan requires {floor} GB)",
            )
        )
        commit, ceiling = memory["commit_used_gb"], limits.get("max_commit_gb", 0)
        gates.append(
            Gate(
                "system_commit",
                PASS if commit <= ceiling else NO_GO,
                f"{commit:.1f} GB committed of {memory['commit_limit_gb']:.1f} GB (plan ceiling {ceiling} GB)",
            )
        )
    from pathlib import Path

    free = probes.disk_free_gb(Path(plan.get("evidence_dir") or "."))
    need = limits.get("min_free_disk_gb", 0)
    gates.append(
        Gate(
            "storage",
            PASS if free is not None and free >= need else NO_GO,
            f"{free if free is None else round(free, 1)} GB free for evidence/output (plan requires {need} GB)",
        )
    )
    return gates


def _target_gates(journey: str, target: dict[str, Any], ctx: ReadinessContext) -> list[Gate]:
    runtime = target["runtime"]
    kind, ownership, base = runtime["kind"], runtime["ownership"], runtime["base_url"]
    gates: list[Gate] = []
    endpoint = ctx.probes.endpoint(base, kind)
    state, busy = endpoint.get("state"), int(endpoint.get("busy_jobs") or 0)
    if ownership == "managed":
        if state != "free":
            gates.append(
                Gate(
                    f"{journey}:ownership",
                    NO_GO,
                    f"{base} is already served ({state}) by a process StableNew did not start; the plan needs a "
                    "StableNew-managed runtime and external processes are never adopted, stopped or restarted",
                )
            )
        else:
            gates.append(
                Gate(
                    f"{journey}:ownership",
                    PASS,
                    f"{base} is free; the production process manager will own the runtime",
                )
            )
    else:
        gates.append(
            Gate(
                f"{journey}:endpoint",
                PASS if state == "healthy" else HOLD,
                f"external {kind} endpoint {base} is {state}",
            )
        )
    gates.append(
        Gate(
            f"{journey}:no_competing_generation",
            NO_GO if busy else PASS,
            f"{busy} job(s) active on {base}" if busy else "no active generation observed",
        )
    )
    if kind == "forge":
        identity = (ctx.forge_identity or default_forge_identity)()
        gates.append(
            Gate(
                f"{journey}:runtime_identity",
                PASS if identity == runtime["identity"] else HOLD,
                f"managed Forge pin {identity!r}; plan {runtime['identity']!r}",
            )
        )
    else:
        launch = (ctx.comfy_launch or default_comfy_launch)()
        identity = launch.get("identity")
        gates.append(
            Gate(
                f"{journey}:runtime_identity",
                PASS if identity == runtime["identity"] else HOLD,
                f"managed Comfy pin {identity!r}; plan {runtime['identity']!r}",
            )
        )
        problems = launch.get("contract_problems") or []
        gates.append(
            Gate(
                f"{journey}:managed_install",
                HOLD if problems else PASS,
                "; ".join(problems) if problems else "managed ComfyUI installation found",
            )
        )
        env_cmd, saved = launch.get("environment_command") or [], launch.get("saved_command") or []
        override = bool(env_cmd) and env_cmd != saved
        gates.append(
            Gate(
                f"{journey}:environment_override",
                HOLD if override else PASS,
                "STABLENEW_COMFY_COMMAND overrides the saved launch command"
                if override
                else "no launch-command environment override",
            )
        )
        workflow = target.get("workflow") or {}
        governance, required = (ctx.workflow_info or default_workflow_info)(
            workflow["id"], workflow["version"]
        )
        gates.append(
            Gate(
                f"{journey}:workflow_governance",
                PASS if governance == "approved" else NO_GO,
                f"{workflow['id']} {workflow['version']} is {governance}",
            )
        )
        missing = [flag for flag in required if flag not in (launch.get("command") or [])]
        gates.append(
            Gate(
                f"{journey}:launch_flags",
                NO_GO if missing else PASS,
                f"the configured ComfyUI command lacks {' '.join(missing)}"
                if missing
                else f"required flags present: {' '.join(required) or 'none required'}",
            )
        )
        if ctx.video_gates is not None:
            for gate_id, gate_state, detail in ctx.video_gates(workflow["id"], workflow["version"]):
                gates.append(
                    Gate(
                        f"{journey}:{gate_id}",
                        {"ok": PASS, "blocked": HOLD}.get(gate_state, PASS),
                        detail,
                    )
                )
    return gates


def evaluate_readiness(plan: dict[str, Any], ctx: ReadinessContext | None = None) -> dict[str, Any]:
    """Run every read-only gate; the overall verdict is the worst gate."""

    ctx = ctx or ReadinessContext()
    probes = ctx.probes
    gates: list[Gate] = []
    problems = shape_problems(plan)
    gates.append(
        Gate(
            "frozen_plan",
            HOLD if problems else PASS,
            "; ".join(problems) or f"digest {plan.get('digest')}",
        )
    )
    python = probes.python()
    gates.append(
        Gate(
            "python",
            PASS if python.startswith(SUPPORTED_PYTHON_PREFIX) else HOLD,
            f"Python {python} (supported {SUPPORTED_PYTHON_PREFIX}x)",
        )
    )
    if not problems:
        diffs = environment_diffs(plan, probes)
        gates.append(
            Gate(
                "environment_matches_plan",
                HOLD if diffs else PASS,
                "; ".join(diffs)
                or "checkout, host, GPU, model and source identities match the frozen plan",
            )
        )
        for journey, target in sorted(plan["targets"].items()):
            gates.extend(_target_gates(journey, target, ctx))
        gates.extend(_resource_gates(plan, probes))
        extra = probes.processes()
        owned_managed = any(
            t["runtime"]["ownership"] == "managed" for t in plan["targets"].values()
        )
        gates.append(
            Gate(
                "existing_runtime_processes",
                NO_GO if (extra and owned_managed) else PASS,
                f"{len(extra)} runtime-like process(es) present; none will be adopted or stopped: "
                + "; ".join(f"pid {p['pid']}" for p in extra)
                if extra
                else "no competing runtime process observed",
            )
        )
    auth = authorization_problems(plan, list(plan.get("journeys") or []))
    verdict = max((g.state for g in gates), key=_RANK.__getitem__, default=PASS)
    return {
        "verdict": verdict,
        "gates": [g.as_dict() for g in gates],
        "plan_digest": plan.get("digest"),
        "physical_run_authorized": not auth,
        "authorization_problems": auth,
        "started_runtime": False,
    }
