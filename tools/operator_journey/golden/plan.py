"""The frozen physical execution plan: build, digest, authorization and environment comparison.

The digest covers every field except ``digest`` and ``authorization``.  An authorization names the digest it approves, so
editing the plan after approval (or a changed environment) can never run: the runner returns HOLD and a fresh
authorization is required.  Neither a CLI flag nor an environment variable is an authorization.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.operator_journey.golden import SUITE_ID, SUITE_VERSION
from tools.operator_journey.golden.host import HostProbes

PLAN_SCHEMA = 1
APPROVED = "approved"
# The approved plan states its own budget; there is deliberately no built-in universal VRAM or RAM threshold.
REQUIRED_LIMITS = (
    "max_jobs",
    "max_artifacts",
    "max_width",
    "max_height",
    "max_steps",
    "max_frames",
    "timeout_seconds",
    "min_available_ram_gb",
    "max_commit_gb",
    "max_vram_used_mib",
    "min_free_disk_gb",
)
RUNTIME_KINDS = ("forge", "comfy")
OWNERSHIP = ("managed", "external")
_EXCLUDED_FROM_DIGEST = ("digest", "authorization", "generated_at")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def plan_digest(plan: dict[str, Any]) -> str:
    body = {k: v for k, v in plan.items() if k not in _EXCLUDED_FROM_DIGEST}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def snapshot_environment(plan: dict[str, Any], probes: HostProbes) -> dict[str, Any]:
    """The live facts the plan froze; compared immediately before execution."""

    gpu = probes.gpu()
    env: dict[str, Any] = {
        "repo_sha": probes.repo_sha(),
        "python": probes.python(),
        "hostname": probes.hostname(),
        "os": probes.os_name(),
        "gpu": {k: gpu[k] for k in ("name", "driver", "total_mib", "uuid")} if gpu else None,
        "targets": {},
    }
    for journey, target in sorted((plan.get("targets") or {}).items()):
        model = target.get("model") or {}
        entry: dict[str, Any] = {"runtime_identity": (target.get("runtime") or {}).get("identity")}
        if model.get("path"):
            path = Path(model["path"])
            entry["model_sha256"] = probes.file_sha256(path) if path.is_file() else None
        entry["sources"] = {
            str(asset["path"]): (
                probes.file_sha256(Path(asset["path"])) if Path(asset["path"]).is_file() else None
            )
            for asset in target.get("source_assets") or []
        }
        env["targets"][journey] = entry
    return env


def build_plan(
    *,
    targets: dict[str, dict[str, Any]],
    limits: dict[str, Any],
    evidence_dir: str,
    probes: HostProbes | None = None,
) -> dict[str, Any]:
    probes = probes or HostProbes()
    from tools.operator_journey.golden.frozen import journey_inputs

    # Every operator-controlled input the journey will type is frozen into the target (the plan, not the code, is the
    # authority the physical run reads them from).
    targets = {
        key: {**target, "inputs": {**journey_inputs(key), **(target.get("inputs") or {})}}
        for key, target in targets.items()
    }
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "suite": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "journeys": sorted(targets),
        "targets": targets,
        "limits": limits,
        "job_count": sum(int(t.get("job_count", 0)) for t in targets.values()),
        "expected_artifacts": sum(int(t.get("expected_artifacts", 0)) for t in targets.values()),
        "expected_endpoints": sorted({t["runtime"]["base_url"] for t in targets.values()}),
        "evidence_dir": evidence_dir,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "authorization": {"state": "unauthorized"},
    }
    plan["environment"] = snapshot_environment(plan, probes)
    plan["digest"] = plan_digest(plan)
    return plan


def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("plan must be a JSON object")
    return plan


def shape_problems(plan: dict[str, Any]) -> list[str]:
    """Structural validity and internal consistency (no live observation)."""

    problems: list[str] = []
    if plan.get("schema") != PLAN_SCHEMA or plan.get("suite") != SUITE_ID:
        problems.append("plan schema or suite does not match this runner")
    if plan.get("suite_version") != SUITE_VERSION:
        problems.append(
            f"plan suite_version {plan.get('suite_version')!r} != runner {SUITE_VERSION!r}"
        )
    limits = plan.get("limits") or {}
    missing = [
        k
        for k in REQUIRED_LIMITS
        if not isinstance(limits.get(k), (int, float)) or limits.get(k) <= 0
    ]
    if missing:
        problems.append(f"plan limits missing or not positive: {', '.join(missing)}")
    targets = plan.get("targets") or {}
    if not targets:
        problems.append("plan has no journey targets")
    if plan.get("digest") != plan_digest(plan):
        problems.append("plan digest does not match its content (edited after freezing)")
    jobs = 0
    for journey, target in sorted(targets.items()):
        runtime = target.get("runtime") or {}
        if runtime.get("kind") not in RUNTIME_KINDS or runtime.get("ownership") not in OWNERSHIP:
            problems.append(f"{journey}: runtime kind/ownership is not declared")
        if not runtime.get("base_url") or not runtime.get("identity"):
            problems.append(f"{journey}: runtime base_url and pinned identity are required")
        model = target.get("model") or {}
        if journey != "video" and not (
            model.get("name") and model.get("sha256") and model.get("path")
        ):
            problems.append(f"{journey}: an installed model with a SHA-256 identity is required")
        if journey == "video":
            workflow = target.get("workflow") or {}
            if not (workflow.get("id") and workflow.get("version")):
                problems.append("video: workflow id and version are required")
            if not target.get("source_assets"):
                problems.append("video: a source reference image identity is required")
        from tools.operator_journey.golden.frozen import input_problems

        problems += input_problems(journey, target)
        settings = target.get("settings") or {}
        for key, limit in (
            ("width", "max_width"),
            ("height", "max_height"),
            ("steps", "max_steps"),
            ("frames", "max_frames"),
        ):
            if key in settings and limits.get(limit) and settings[key] > limits[limit]:
                problems.append(f"{journey}: {key} {settings[key]} exceeds {limit} {limits[limit]}")
        jobs += int(target.get("job_count", 0))
    if limits.get("max_jobs") and jobs > limits["max_jobs"]:
        problems.append(f"planned jobs {jobs} exceed max_jobs {limits['max_jobs']}")
    if (
        limits.get("max_artifacts")
        and int(plan.get("expected_artifacts", 0)) > limits["max_artifacts"]
    ):
        problems.append("expected artifacts exceed max_artifacts")
    return problems


def authorization_problems(
    plan: dict[str, Any], journeys: list[str], now: datetime | None = None
) -> list[str]:
    """The current owner approval must name this digest, these journeys and a future expiry."""

    auth = plan.get("authorization") or {}
    now = now or datetime.now(UTC)
    if auth.get("state") != APPROVED:
        return ["the plan is not authorized (authorization.state != 'approved')"]
    problems: list[str] = []
    if not str(auth.get("approved_by") or "").strip():
        problems.append("authorization names no approving owner")
    if auth.get("plan_digest") != plan.get("digest") or plan.get("digest") != plan_digest(plan):
        problems.append("authorization does not match the current plan digest")
    unapproved = sorted(set(journeys) - set(auth.get("journeys") or []))
    if unapproved:
        problems.append(f"journeys not covered by the authorization: {', '.join(unapproved)}")
    try:
        expires = datetime.fromisoformat(str(auth.get("expires_at")))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= now:
            problems.append("authorization has expired")
    except ValueError:
        problems.append("authorization has no valid expires_at")
    return problems


def environment_diffs(plan: dict[str, Any], probes: HostProbes) -> list[str]:
    """Differences between the frozen environment and the live one (any difference is a HOLD)."""

    frozen = plan.get("environment") or {}
    live = snapshot_environment(plan, probes)
    diffs: list[str] = []
    for key in ("repo_sha", "python", "hostname", "gpu"):
        if frozen.get(key) != live.get(key):
            diffs.append(f"{key}: planned {frozen.get(key)!r}, live {live.get(key)!r}")
    for journey, target in sorted((live.get("targets") or {}).items()):
        planned = (frozen.get("targets") or {}).get(journey) or {}
        for key, value in target.items():
            if planned.get(key) != value:
                diffs.append(f"{journey}.{key}: planned {planned.get(key)!r}, live {value!r}")
    return diffs
