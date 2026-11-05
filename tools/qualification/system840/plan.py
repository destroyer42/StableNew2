"""Frozen per-arm physical plans, owner authorization and the typed launch confirmation.

A plan freezes everything an arm will do.  The digest covers every field except ``digest``, ``generated_at`` and
``authorization``; an authorization names the digest, the arm, the stage and the exact candidate model, so editing the plan
afterward (a different model, source, prompt, setting, threshold, environment or budget) can never run: it needs a new
digest and a new approval.

Three separate acts are required before any physical dispatch, and none implies another:

1. creating the plan (this module's ``build_plan``; an agent may do this),
2. the owner's approval of that exact digest (``issue_authorization``; interactive only, refused in CI, pytest and any
   non-terminal session, stored in a file separate from the plan),
3. the typed launch confirmation ``RUN <digest12>`` at launch time (``launch_problems``).

An authorization file is a record, not proof: this tooling cannot establish *who* typed the approval, so its controls are
procedural (interactive-only issuance, distinct phrases, expiry, one arm per approval, audit trail) and the operating rule
that an agent never issues an authorization stays in force (``AGENTS.md`` section 5).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.operator_journey.golden.modes import running_in_ci, running_under_pytest
from tools.qualification.system840 import BENCHMARK_VERSION, SUITE_ID, SUITE_VERSION
from tools.qualification.system840.arms import (
    STAGE_CANARY,
    STAGES,
    ArmDef,
    get_arm,
    lane_class,
)
from tools.qualification.system840.probes import QualProbes
from tools.qualification.system840.statuses import NON_EXECUTABLE

PLAN_SCHEMA = 1
AUTH_SCHEMA = 1
APPROVED = "approved"
ISSUER = "interactive_owner_cli"
MAX_AUTH_HOURS = 24 * 14
RUNTIME_OWNERSHIP = ("managed", "external")
_EXCLUDED_FROM_DIGEST = ("digest", "authorization", "generated_at")

COMMON_LIMITS = (
    "min_available_ram_gb",
    "max_commit_gb",
    "max_run_seconds",
    "max_session_seconds",
    "min_free_disk_gb",
)
GPU_LIMITS = ("max_vram_used_mib",)
IMAGE_SETTINGS = ("sampler", "scheduler", "steps", "cfg")
VIDEO_SETTINGS = ("frames", "fps")
#: Every stop condition a plan must declare; each one stops the arm and none is retried or silently downgraded.
STOP_CONDITIONS = (
    "device_loss",
    "allocation_failure",
    "host_commit_pressure",
    "low_available_ram",
    "identity_mismatch",
    "timeout",
    "unsafe_teardown",
    "telemetry_gap",
    "operator_cancel",
    "ambiguous_dispatch",
)


class PlanRefused(ValueError):
    """The requested plan is not admissible (held arm/target, unknown capability); the message names why."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest_of(body: Mapping[str, Any]) -> str:
    cleaned = {k: v for k, v in body.items() if k not in _EXCLUDED_FROM_DIGEST}
    return hashlib.sha256(canonical_json(cleaned).encode("utf-8")).hexdigest()


def default_stop_policy() -> dict[str, Any]:
    return {
        "conditions": list(STOP_CONDITIONS),
        "on_stop": "stop the arm and every dependent GPU arm; inspect evidence before anything else",
        "retry": "never",  # an ambiguous dispatched generation POST is never replayed
        "downgrade_after_resource_failure": "never",  # no silent lowering of settings and no model substitution
        "cancel_behavior": "cancel through the existing production owner path; never kill an unowned process",
        "external_runtime_policy": "observe through the supported API only; never adopt, stop, restart or reconfigure",
    }


def default_telemetry() -> dict[str, Any]:
    return {
        "cadence_seconds": 2.0,
        "max_gap_seconds": 5.0,
        "required_availability": 0.99,
        "channels": [
            "host_commit_fraction",
            "host_available_ram_mib",
            "gpu_vram_used_mib",
            "device_loss_events",
        ],
    }


# --------------------------------------------------------------------------------------------------------------------
# Environment snapshot
# --------------------------------------------------------------------------------------------------------------------


def snapshot_environment(arm_plan: Mapping[str, Any], probes: QualProbes) -> dict[str, Any]:
    """The live facts a plan froze; compared immediately before execution (any difference is a HOLD)."""

    arm = get_arm(str(arm_plan["arm_id"]))
    tree = probes.tree()
    env: dict[str, Any] = {
        "repo": {k: tree.get(k) for k in ("sha", "dirty_files", "diff_sha256")},
        "python": probes.python(),
        "hostname": probes.hostname(),
        "os": probes.os_name(),
        "cases": {},
    }
    if arm.gpu:
        gpu = probes.gpu()
        env["gpu"] = {k: gpu[k] for k in ("name", "driver", "total_mib", "uuid")} if gpu else None
    for case in arm_plan.get("cases") or []:
        entry: dict[str, Any] = {
            "runtime_identity": (arm_plan.get("runtime") or {}).get("identity")
        }
        model = case.get("model") or {}
        if model.get("path"):
            path = Path(model["path"])
            entry["model"] = (
                {"size": path.stat().st_size, "sha256": probes.file_sha256(path)}
                if path.is_file()
                else None
            )
        entry["sources"] = {
            str(src["path"]): (
                probes.file_sha256(Path(src["path"])) if Path(src["path"]).is_file() else None
            )
            for src in case.get("sources") or []
        }
        env["cases"][case["case_id"]] = entry
    return env


def environment_diffs(arm_plan: Mapping[str, Any], probes: QualProbes) -> list[str]:
    frozen = arm_plan.get("environment") or {}
    live = snapshot_environment(arm_plan, probes)
    diffs: list[str] = []
    for key in ("repo", "python", "hostname", "gpu"):
        if frozen.get(key) != live.get(key):
            diffs.append(f"{key}: planned {frozen.get(key)!r}, live {live.get(key)!r}")
    for case_id, entry in sorted((live.get("cases") or {}).items()):
        planned = (frozen.get("cases") or {}).get(case_id) or {}
        for key, value in entry.items():
            if planned.get(key) != value:
                diffs.append(f"{case_id}.{key}: planned {planned.get(key)!r}, live {value!r}")
    return diffs


# --------------------------------------------------------------------------------------------------------------------
# Building a plan
# --------------------------------------------------------------------------------------------------------------------


def _capability_problem(capability_id: str, ledger: Any | None, arm: ArmDef) -> str | None:
    for hold in arm.holds:
        if capability_id in hold.targets:
            return f"{capability_id} is held by {hold.hold_id}: {hold.reason}"
    if ledger is None:
        return None
    entry = ledger.get(capability_id)
    if entry is None:
        return f"{capability_id} is not in the qualification ledger"
    if entry.arm != arm.arm_id:
        return f"{capability_id} belongs to {entry.arm}, not {arm.arm_id}"
    if entry.status in NON_EXECUTABLE:
        return f"{capability_id} is {entry.status.value} in the ledger; no executable plan is admissible"
    return None


def admission_problems(
    arm: ArmDef, cases: list[Mapping[str, Any]], ledger: Any | None = None
) -> list[str]:
    problems: list[str] = []
    whole_arm = [h for h in arm.holds if not h.targets]
    for hold in whole_arm:
        problems.append(f"{arm.arm_id} is held by {hold.hold_id}: {hold.reason}")
    if not arm.physical:
        problems.append(f"{arm.arm_id} is an offline arm; it has no physical plan")
    for case in cases:
        issue = _capability_problem(str(case.get("capability_id")), ledger, arm)
        if issue:
            problems.append(issue)
    return problems


def build_plan(
    arm_id: str,
    *,
    stage: str,
    cases: list[dict[str, Any]],
    runtime: dict[str, Any],
    limits: dict[str, Any],
    evidence_dir: str,
    probes: QualProbes | None = None,
    ledger: Any | None = None,
    telemetry: dict[str, Any] | None = None,
    stop: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Freeze one arm's stage.  Raises ``PlanRefused`` for a held, offline or ledger-refused arm or target."""

    arm = get_arm(arm_id)
    if stage not in STAGES:
        raise PlanRefused(f"unknown stage {stage!r}; choose one of {STAGES}")
    refusals = admission_problems(arm, cases, ledger)
    if refusals:
        raise PlanRefused("; ".join(refusals))
    probes = probes or QualProbes()
    created = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "suite": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "arm_id": arm_id,
        "stage": stage,
        "test_id": f"{arm_id}/{stage}",
        "authorization_group": arm.authorization_group,
        "lane": arm.lane,
        "evidence_class": arm.evidence_class.value,
        "backend": runtime.get("kind"),
        "runtime": runtime,
        "cases": cases,
        "jobs": sum(int(c.get("jobs", 1)) for c in cases),
        "artifacts": sum(int(c.get("expected_artifacts", 1)) for c in cases),
        "limits": limits,
        "telemetry": telemetry or default_telemetry(),
        "stop": stop or default_stop_policy(),
        "expected_outputs": sorted({o for c in cases for o in c.get("expected_outputs", [])}),
        "evidence_dir": evidence_dir,
        "generated_at": created,
        "authorization": {"state": "unauthorized"},
    }
    plan["environment"] = snapshot_environment(plan, probes)
    plan["digest"] = digest_of(plan)
    return plan


def campaign_digest(arm_plans: Mapping[str, Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        canonical_json({k: v.get("digest") for k, v in sorted(arm_plans.items())}).encode()
    ).hexdigest()


# --------------------------------------------------------------------------------------------------------------------
# Plan validation
# --------------------------------------------------------------------------------------------------------------------


def _case_problems(arm: ArmDef, case: Mapping[str, Any]) -> list[str]:
    cid = str(case.get("case_id") or "?")
    problems: list[str] = []
    for key in ("case_id", "capability_id", "seeds", "prompts", "expected_outputs"):
        if not case.get(key):
            problems.append(f"{cid}: {key} is required")
    prompts = case.get("prompts") or {}
    if "positive" not in prompts or "negative" not in prompts:
        problems.append(
            f"{cid}: positive and negative prompts must both be frozen (empty negative allowed)"
        )
    model = case.get("model") or {}
    if not (model.get("path") and model.get("sha256") and int(model.get("size") or 0) > 0):
        problems.append(f"{cid}: model path, size and SHA-256 are required")
    for src in case.get("sources") or []:
        if not (src.get("path") and src.get("sha256") and src.get("role")):
            problems.append(f"{cid}: every source asset needs role, path and SHA-256")
    geometry = case.get("geometry") or {}
    if not (geometry.get("width") and geometry.get("height")):
        problems.append(f"{cid}: width and height are required")
    if arm.domain == "image":
        sampler = case.get("settings") or {}
        missing = [k for k in IMAGE_SETTINGS if sampler.get(k) in (None, "")]
        if missing:
            problems.append(f"{cid}: image settings missing {', '.join(missing)}")
    if arm.domain == "video":
        if not (case.get("workflow") or {}).get("id") or not (case.get("workflow") or {}).get(
            "version"
        ):
            problems.append(f"{cid}: workflow id and version are required")
        missing = [k for k in VIDEO_SETTINGS if not geometry.get(k)]
        if missing:
            problems.append(f"{cid}: video geometry missing {', '.join(missing)}")
        if not case.get("sources"):
            problems.append(f"{cid}: a source image identity is required")
    if lane_class(arm.lane) == "cpu_inference":
        ai = case.get("cpu_inference") or {}
        if ai.get("cpu_only") is not True:
            problems.append(f"{cid}: CPU inference must be frozen as cpu_only")
        if ai.get("network") != "denied":
            problems.append(f"{cid}: CPU inference must freeze network as 'denied'")
        if not ai.get("command"):
            problems.append(f"{cid}: the exact offline inference command is required")
        if not (ai.get("runtime_sha256") and ai.get("model_id")):
            problems.append(f"{cid}: model id and runtime SHA-256 are required")
        if arm.lane == "cpu_ai_assist":
            if not ai.get("protected_interpreter"):
                problems.append(f"{cid}: a protected interpreter attestation is required")
            problems += _ai_command_problems(cid, [str(t) for t in ai.get("command") or []])
    return problems


def _ai_command_problems(cid: str, command: list[str]) -> list[str]:
    """The frozen offline command must be CPU-only, offline and inside the production closed flag vocabulary."""

    from src.ai_assist.argv import assert_argv_allowed

    problems: list[str] = []
    args = command[1:]
    if "--offline" not in args:
        problems.append(f"{cid}: the offline command must pass --offline")
    if "-ngl" not in args or args[args.index("-ngl") + 1 : args.index("-ngl") + 2] != ["0"]:
        problems.append(f"{cid}: the offline command must pass -ngl 0 (CPU only)")
    try:
        assert_argv_allowed(args)
    except ValueError as exc:
        problems.append(f"{cid}: {exc}")
    return problems


def shape_problems(plan: Mapping[str, Any]) -> list[str]:
    """Structural validity and internal consistency of a frozen arm plan (no live observation)."""

    problems: list[str] = []
    if plan.get("schema") != PLAN_SCHEMA or plan.get("suite") != SUITE_ID:
        problems.append("plan schema or suite does not match this runner")
    if plan.get("suite_version") != SUITE_VERSION:
        problems.append(
            f"plan suite_version {plan.get('suite_version')!r} != runner {SUITE_VERSION!r}"
        )
    if plan.get("benchmark_version") != BENCHMARK_VERSION:
        problems.append(
            f"plan benchmark_version {plan.get('benchmark_version')!r} != {BENCHMARK_VERSION!r}"
        )
    try:
        arm = get_arm(str(plan.get("arm_id")))
    except KeyError as exc:
        return [*problems, str(exc)]
    if plan.get("stage") not in STAGES:
        problems.append("plan stage is not canary or coverage")
    if plan.get("digest") != digest_of(plan):
        problems.append("plan digest does not match its content (edited after freezing)")
    repo = (plan.get("environment") or {}).get("repo") or {}
    if not repo.get("sha") or repo.get("sha") == "unknown":
        problems.append("the exact Git SHA is not frozen")
    runtime = plan.get("runtime") or {}
    if runtime.get("ownership") not in RUNTIME_OWNERSHIP:
        problems.append("runtime process ownership (managed or external) is not declared")
    if not runtime.get("identity"):
        problems.append("the pinned runtime identity is not frozen")
    limits = plan.get("limits") or {}
    required = COMMON_LIMITS + (GPU_LIMITS if arm.gpu else ())
    bad = [k for k in required if not isinstance(limits.get(k), (int, float)) or limits[k] <= 0]
    if bad:
        problems.append(f"plan limits missing or not positive: {', '.join(bad)}")
    if limits.get("max_run_seconds") and limits.get("max_session_seconds"):
        if limits["max_run_seconds"] > limits["max_session_seconds"]:
            problems.append("max_run_seconds exceeds max_session_seconds")
    telemetry = plan.get("telemetry") or {}
    if not (telemetry.get("cadence_seconds") and telemetry.get("required_availability")):
        problems.append("telemetry cadence and required availability are not frozen")
    stop = plan.get("stop") or {}
    absent = [c for c in STOP_CONDITIONS if c not in (stop.get("conditions") or [])]
    if absent:
        problems.append(f"stop conditions not declared: {', '.join(absent)}")
    if stop.get("retry") != "never" or stop.get("downgrade_after_resource_failure") != "never":
        problems.append("a plan may not allow retry or silent downgrade after a failure")
    cases = plan.get("cases") or []
    if not cases:
        problems.append("plan has no cases")
    ids = [c.get("case_id") for c in cases]
    if len(ids) != len(set(ids)):
        problems.append("case ids are not unique")
    for case in cases:
        problems += _case_problems(arm, case)
    if int(plan.get("jobs", 0)) <= 0:
        problems.append("the number of jobs is not frozen")
    if not plan.get("expected_outputs") or not plan.get("evidence_dir"):
        problems.append("expected outputs and the evidence directory are required")
    return problems


# --------------------------------------------------------------------------------------------------------------------
# Authorization and launch
# --------------------------------------------------------------------------------------------------------------------


def approval_phrase(plan: Mapping[str, Any]) -> str:
    return f"APPROVE {plan['arm_id']} {str(plan['digest'])[:12]}"


def launch_phrase(plan: Mapping[str, Any]) -> str:
    return f"RUN {str(plan['digest'])[:12]}"


def plan_model_ids(plan: Mapping[str, Any]) -> list[str]:
    ids: set[str] = set()
    for case in plan.get("cases") or []:
        if (case.get("cpu_inference") or {}).get("model_id"):
            ids.add(str(case["cpu_inference"]["model_id"]))
        elif (case.get("model") or {}).get("sha256"):
            ids.add(str(case["model"]["sha256"]))
    return sorted(ids)


def authorization_problems(
    plan: Mapping[str, Any], auth: Mapping[str, Any] | None, now: datetime | None = None
) -> list[str]:
    """The owner approval must name this digest, arm, stage and exact model(s), and be current."""

    if not auth or auth.get("state") != APPROVED:
        return ["the arm is not authorized (no approved authorization record)"]
    now = now or datetime.now(UTC)
    problems: list[str] = []
    if auth.get("schema") != AUTH_SCHEMA:
        problems.append("authorization schema is not recognized")
    if auth.get("issuer") != ISSUER:
        problems.append("authorization was not issued by the interactive owner command")
    if not str(auth.get("approved_by") or "").strip():
        problems.append("authorization names no approving owner")
    if auth.get("plan_digest") != plan.get("digest") or plan.get("digest") != digest_of(plan):
        problems.append("authorization does not match the current plan digest")
    if auth.get("arm_id") != plan.get("arm_id") or auth.get("stage") != plan.get("stage"):
        problems.append("authorization names a different arm or stage")
    if auth.get("authorization_group") != plan.get("authorization_group"):
        problems.append("authorization names a different authorization group")
    if sorted(auth.get("model_ids") or []) != plan_model_ids(plan):
        problems.append(
            "authorization does not cover exactly this model (a grant is never reused for another model)"
        )
    if auth.get("approval_phrase") != approval_phrase(plan):
        problems.append("the approval phrase does not name this arm and digest")
    try:
        approved_at = datetime.fromisoformat(str(auth.get("approved_at")))
        expires = datetime.fromisoformat(str(auth.get("expires_at")))
        if approved_at.tzinfo is None:
            approved_at = approved_at.replace(tzinfo=UTC)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        created = datetime.fromisoformat(str(plan.get("generated_at")))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if approved_at < created:
            problems.append("authorization predates the plan it approves")
        if expires <= now:
            problems.append("authorization has expired")
        if expires - approved_at > timedelta(hours=MAX_AUTH_HOURS):
            problems.append(f"authorization lifetime exceeds {MAX_AUTH_HOURS} hours")
    except ValueError:
        problems.append("authorization has no valid approved_at / expires_at")
    return problems


def launch_problems(
    plan: Mapping[str, Any], auth: Mapping[str, Any], typed: str, now: datetime | None = None
) -> list[str]:
    """The typed launch confirmation is a separate act from the approval and must come after it."""

    problems: list[str] = []
    if typed.strip() == approval_phrase(plan):
        problems.append("the approval phrase is not a launch confirmation; type the RUN phrase")
    elif typed.strip() != launch_phrase(plan):
        problems.append(f"launch confirmation must be exactly {launch_phrase(plan)!r}")
    try:
        approved_at = datetime.fromisoformat(str(auth.get("approved_at")))
        if approved_at.tzinfo is None:
            approved_at = approved_at.replace(tzinfo=UTC)
        if (now or datetime.now(UTC)) < approved_at:
            problems.append("launch confirmation predates the approval")
    except ValueError:
        problems.append("authorization has no valid approved_at")
    return problems


def build_authorization(
    plan: Mapping[str, Any],
    *,
    approved_by: str,
    ttl_hours: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The record an approval produces (pure; ``issue_authorization`` adds the interactive-only refusals)."""

    now = now or datetime.now(UTC)
    record: dict[str, Any] = {
        "schema": AUTH_SCHEMA,
        "state": APPROVED,
        "issuer": ISSUER,
        "approved_by": approved_by,
        "approved_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(timespec="seconds"),
        "arm_id": plan["arm_id"],
        "stage": plan["stage"],
        "authorization_group": plan.get("authorization_group"),
        "plan_digest": plan["digest"],
        "model_ids": plan_model_ids(plan),
        "approval_phrase": approval_phrase(plan),
        "nonce": secrets.token_hex(8),
    }
    return record


class AuthorizationRefused(RuntimeError):
    pass


def issue_authorization(
    plan: Mapping[str, Any],
    *,
    approved_by: str,
    typed_phrase: str,
    ttl_hours: float = 24,
    interactive: bool | None = None,
    ci: bool | None = None,
    pytest_active: bool | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Issue an approval only from an interactive terminal where the owner typed this arm's exact approval phrase."""

    if ttl_hours <= 0 or ttl_hours > MAX_AUTH_HOURS:
        raise AuthorizationRefused(f"approval lifetime must be within 0 and {MAX_AUTH_HOURS} hours")
    interactive = sys.stdin.isatty() if interactive is None else interactive
    ci = running_in_ci() if ci is None else ci
    pytest_active = running_under_pytest() if pytest_active is None else pytest_active
    if ci or pytest_active:
        raise AuthorizationRefused("an owner approval is never issued from CI or pytest")
    if not interactive:
        raise AuthorizationRefused("an owner approval is issued only from an interactive terminal")
    if shape := shape_problems(plan):
        raise AuthorizationRefused("the plan is not valid: " + "; ".join(shape[:3]))
    if typed_phrase.strip() != approval_phrase(plan):
        raise AuthorizationRefused(f"approval requires typing exactly {approval_phrase(plan)!r}")
    if not approved_by.strip():
        raise AuthorizationRefused("an approving owner name is required")
    return build_authorization(plan, approved_by=approved_by.strip(), ttl_hours=ttl_hours, now=now)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def stage_order_problem(stage: str, canary_passed: bool) -> str | None:
    if stage != STAGE_CANARY and not canary_passed:
        return "coverage requires a passed canary of the same arm"
    return None
