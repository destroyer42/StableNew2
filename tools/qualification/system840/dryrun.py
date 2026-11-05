"""A representative simulated campaign: synthetic assets, fake host probes, a simulated adapter and test-only approvals.

This validates the whole coordinator (plans, digests, authorization, readiness, typed launch, archival, verdicts, stop
propagation, comparison) without a GPU, runtime, model, network or owner.  The approvals it creates are valid only for its
own synthetic temporary plans, and the simulated adapter refuses to be mistaken for a physical one: nothing here can
authorize or dispatch real work.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.qualification.system840 import coordinator
from tools.qualification.system840 import plan as plan_mod
from tools.qualification.system840.arms import (
    ARM_BY_ID,
    LANE_AI_CPU,
    STAGE_CANARY,
    STAGE_COVERAGE,
    get_arm,
    lane_class,
)
from tools.qualification.system840.ledger import Ledger, load_ledger
from tools.qualification.system840.probes import QualProbes

LIMITS_GPU = {
    "min_available_ram_gb": 8,
    "max_commit_gb": 60,
    "max_run_seconds": 900,
    "max_session_seconds": 3600,
    "min_free_disk_gb": 5,
    "max_vram_used_mib": 11000,
}
LIMITS_CPU = {k: v for k, v in LIMITS_GPU.items() if k != "max_vram_used_mib"}
EPOCH = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def fake_probes(**overrides: Any) -> QualProbes:
    """Healthy synthetic host.  Override any probe (``gpu=lambda: None`` etc.) to simulate a fault."""

    base: dict[str, Any] = {
        "repo_sha": lambda: "d76d1acde91a64f7f513ac42cffa5baa67f519bf",
        "tree": lambda: {
            "sha": "d76d1acde91a64f7f513ac42cffa5baa67f519bf",
            "dirty_files": [],
            "diff_sha256": "",
        },
        "gpu": lambda: {
            "name": "RTX 4070 Ti",
            "driver": "1",
            "total_mib": 12282.0,
            "used_mib": 600.0,
            "free_mib": 11600.0,
            "uuid": "GPU-sim",
        },
        "memory": lambda: {
            "available_gb": 24.0,
            "total_gb": 32.0,
            "commit_used_gb": 20.0,
            "commit_limit_gb": 80.0,
        },
        "disk_free_gb": lambda path: 500.0,
        "endpoint": lambda url, kind: {"state": "healthy", "busy_jobs": 0},
        "processes": lambda: [],
        "python": lambda: "3.14.0",
        "hostname": lambda: "sim-host",
        "os_name": lambda: "Windows sim",
        "ai_capture_state": lambda: {
            "active": True,
            "canary_pass_age_hours": 1.0,
            "protected_interpreter": True,
            "child_memory_limit_verified": True,
        },
    }
    base.update(overrides)
    return QualProbes(**base)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_case(
    arm_id: str, capability_id: str, root: Path, *, index: int = 0
) -> dict[str, Any]:
    """A complete, valid case for the arm's domain over tiny real files so identity checks hash something."""

    arm = get_arm(arm_id)
    root.mkdir(parents=True, exist_ok=True)
    model = root / f"model-{capability_id}.bin"
    model.write_bytes(f"model weights for {capability_id}".encode())
    source = root / f"source-{index}.png"
    from PIL import Image

    Image.new("RGB", (32, 32), (10 + index, 90, 200)).save(source)
    case: dict[str, Any] = {
        "case_id": f"{capability_id}#{index}",
        "capability_id": capability_id,
        "model": {"path": str(model), "size": model.stat().st_size, "sha256": _sha(model)},
        "sources": [
            {
                "role": "reference_image",
                "path": str(source),
                "sha256": _sha(source),
                "size": source.stat().st_size,
            }
        ],
        "prompts": {
            "positive": "A full-body portrait of a hiker on a ridge at golden hour",
            "negative": "blurry, extra fingers",
        },
        "seeds": [424242 + index],
        "geometry": {"width": 832, "height": 480},
        "jobs": 1,
        "expected_artifacts": 1,
        "expected_outputs": ["artifacts/artifact-0.png"],
    }
    if arm.domain == "image":
        case["settings"] = {"sampler": "Euler", "scheduler": "Beta", "steps": 4, "cfg": 1.0}
        case["geometry"] = {"width": 768, "height": 1024}
    if arm.domain == "video":
        case["workflow"] = {"id": "wan22_ti2v_5b_i2v_v1", "version": "1.3.0"}
        case["geometry"] = {"width": 480, "height": 832, "frames": 17, "fps": 24}
    if lane_class(arm.lane) == "cpu_inference":
        case["cpu_inference"] = {
            "cpu_only": True,
            "network": "denied",
            "command": ["llama-completion.exe", "--offline", "-ngl", "0"],
            "model_id": capability_id.split(".", 1)[1],
            "runtime_sha256": "f" * 64,
            "protected_interpreter": arm.lane == LANE_AI_CPU,
        }
    return case


def runtime_for(arm_id: str) -> dict[str, Any]:
    arm = get_arm(arm_id)
    if arm.gpu:
        kind = "comfy" if arm.lane == "gpu_comfy" else "forge"
        return {
            "kind": kind,
            "ownership": "managed" if kind == "comfy" else "external",
            "base_url": "http://127.0.0.1:8188" if kind == "comfy" else "http://127.0.0.1:7860",
            "identity": "sim-runtime-1",
        }
    return {"kind": "cpu", "ownership": "managed", "identity": "sim-cpu-runtime-1"}


def build_synthetic_plan(
    arm_id: str,
    stage: str,
    root: Path,
    probes: QualProbes,
    ledger: Ledger | None,
    capability_ids: list[str] | None = None,
) -> dict[str, Any]:
    ids = (
        capability_ids
        or [
            e.id
            for e in (ledger.for_arm(arm_id) if ledger else [])
            if e.status.value not in ("HOLD", "NO-GO", "UNSUPPORTED")
            and e.data["next_test"].get("admissible")
        ][:1]
    )
    cases = [synthetic_case(arm_id, cid, root / arm_id, index=i) for i, cid in enumerate(ids)]
    limits = LIMITS_GPU if get_arm(arm_id).gpu else LIMITS_CPU
    return plan_mod.build_plan(
        arm_id,
        stage=stage,
        cases=cases,
        runtime=runtime_for(arm_id),
        limits=dict(limits),
        evidence_dir=str(root / "evidence"),
        probes=probes,
        ledger=ledger,
        now=EPOCH,
    )


def synthetic_authorization(plan: dict[str, Any]) -> dict[str, Any]:
    """Valid only for a synthetic plan: built directly, bypassing the interactive-only issuance a real approval needs."""

    return plan_mod.build_authorization(
        plan, approved_by="dry-run", ttl_hours=12, now=EPOCH + timedelta(minutes=5)
    )


def run_dry_campaign(
    root: Path, *, scenario: str = "success", arms: tuple[str, ...] = ("IMG-Q0", "IMG-Q1", "VID-Q0")
) -> dict[str, Any]:
    """Run canary then coverage for the chosen GPU arms through the real coordinator with the simulated adapter."""

    ledger = load_ledger()
    probes = fake_probes()
    plans: list[dict[str, Any]] = []
    auths: dict[str, dict[str, Any]] = {}
    for arm_id in arms:
        for stage in (STAGE_CANARY, STAGE_COVERAGE):
            plan = build_synthetic_plan(arm_id, stage, root / "assets", probes, ledger)
            plans.append(plan)
            auths[f"{arm_id}/{stage}"] = synthetic_authorization(plan)
    adapters = {arm_id: coordinator.SimulatedAdapter(scenario) for arm_id in ARM_BY_ID}
    # IMG-Q1/VID-Q0 may depend on accepted baseline evidence from earlier sessions.
    accepted = {("IMG-Q0", STAGE_CANARY)} if "IMG-Q0" not in arms else set()
    return coordinator.run_campaign(
        plans,
        auths,
        adapters,
        probes=probes,
        evidence_root=root / "evidence-root",
        confirm=lambda phrase: phrase,
        ledger=ledger,
        accepted=accepted,
        now=lambda: EPOCH + timedelta(minutes=10),
    )
