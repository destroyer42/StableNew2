"""Q0: offline readiness for the Fun Control 5B qualification.  Reads files and host counters only.

Nothing here starts Comfy, imports torch, queries a GPU, downloads a file or writes anywhere.  The pinned weights are verified
with the same read-only size/SHA-256 check the product uses; a missing file is a BLOCKER, never something to fetch.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.video.motion_source_preparation import sha256_file
from src.video.workflow_asset_integrity import verify_assets
from tools.qualification.fun354.plan import (
    OUTPUT_RESERVE_BYTES,
    PlanError,
    QualificationPlan,
    build_plan,
    fun_control_spec,
)

PASS, BLOCKED, UNKNOWN, INFO = "PASS", "BLOCKED", "UNKNOWN", "INFO"
READY, NOT_READY, INCOMPLETE = "READY", "BLOCKED", "INCOMPLETE"
GPU_NOT_READ = "not read: GPU telemetry belongs to the separately authorized run"


@dataclass(frozen=True)
class HostFacts:
    total_ram_mib: int
    available_ram_mib: int
    commit_limit_mib: int  # RAM + page file; an approximation labelled as such
    free_disk_bytes: int
    gpu: str = GPU_NOT_READ


@dataclass(frozen=True)
class Check:
    check_id: str
    status: str
    detail: str


@dataclass(frozen=True)
class Q0Report:
    plan_digest: str
    checks: tuple[Check, ...]
    host: HostFacts | None

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.checks}
        if BLOCKED in statuses:
            return NOT_READY
        return INCOMPLETE if UNKNOWN in statuses else READY

    @property
    def ready(self) -> bool:
        return self.status == READY

    @property
    def blockers(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.status == BLOCKED)

    def to_record(self) -> dict[str, Any]:
        return {
            "plan_digest": self.plan_digest,
            "status": self.status,
            "checks": [asdict(c) for c in self.checks],
            "host": asdict(self.host) if self.host else None,
            "physical_execution": "NOT AUTHORIZED",
        }


def read_host_facts(output_dir: str | Path) -> HostFacts:
    """RAM, page file and free disk beside the output folder; no GPU access."""

    import psutil

    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    mib = 1024 * 1024
    return HostFacts(
        total_ram_mib=int(memory.total // mib),
        available_ram_mib=int(memory.available // mib),
        commit_limit_mib=int((memory.total + swap.total) // mib),
        free_disk_bytes=int(shutil.disk_usage(Path(output_dir)).free),
    )


def _catalog_check(plan: QualificationPlan) -> Check:
    try:
        current = build_plan()
        spec = fun_control_spec()
    except PlanError as exc:
        return Check("catalog_identity", BLOCKED, str(exc))
    same = (
        current.graph_sha256 == plan.graph_sha256
        and current.assets == plan.assets
        and current.workflow_version == plan.workflow_version
        and spec.governance_state == "experimental"
    )
    if not same:
        return Check(
            "catalog_identity",
            BLOCKED,
            "The catalog entry differs from the plan; mint a new plan, never edit the entry.",
        )
    return Check(
        "catalog_identity",
        PASS,
        f"{plan.workflow_id}@{plan.workflow_version} graph {plan.graph_sha256[:12]} unchanged; still not_qualified.",
    )


def _weights_check(
    folders: Mapping[str, Sequence[Path]] | None,
    verifier: Callable[[Any, Mapping[str, Sequence[Path]]], tuple[str, ...]],
) -> Check:
    if folders is None:
        return Check(
            "pinned_weights",
            UNKNOWN,
            "No Comfy model folders were given, so the weights could not be looked for.",
        )
    issues = verifier(fun_control_spec(), folders)
    if issues:
        return Check("pinned_weights", BLOCKED, "; ".join(issues))
    return Check(
        "pinned_weights",
        PASS,
        "All three pinned files are present with the exact size and SHA-256.",
    )


def _input_checks(plan: QualificationPlan, inputs: Mapping[str, Path | None]) -> list[Check]:
    checks: list[Check] = []
    for pin in plan.inputs:
        path = inputs.get(pin.role)
        check_id = f"input_{pin.role}"
        if not pin.sha256:
            checks.append(
                Check(
                    check_id,
                    BLOCKED,
                    f"The {pin.role.replace('_', ' ')} is not pinned in the plan (no SHA-256 chosen).",
                )
            )
        elif path is None or not Path(path).is_file():
            checks.append(
                Check(
                    check_id,
                    BLOCKED,
                    f"The pinned {pin.role.replace('_', ' ')} file is not available.",
                )
            )
        elif sha256_file(Path(path)) != pin.sha256:
            checks.append(
                Check(
                    check_id,
                    BLOCKED,
                    f"The {pin.role.replace('_', ' ')} bytes differ from the pinned SHA-256.",
                )
            )
        else:
            checks.append(Check(check_id, PASS, f"{pin.role} matches its pinned SHA-256."))
    return checks


def _runtime_check(plan: QualificationPlan, observed_commit: str | None) -> Check:
    if not observed_commit:
        return Check(
            "runtime_identity",
            UNKNOWN,
            f"The installed ComfyUI commit was not read; the plan requires {plan.runtime_commit}.",
        )
    if observed_commit != plan.runtime_commit:
        return Check(
            "runtime_identity",
            BLOCKED,
            f"Installed ComfyUI {observed_commit[:12]} differs from the plan's {plan.runtime_commit[:12]}.",
        )
    return Check("runtime_identity", PASS, "Installed ComfyUI commit matches the plan.")


def _host_check(host: HostFacts | None) -> Check:
    if host is None:
        return Check("host_facts", UNKNOWN, "Host facts were not read.")
    if host.free_disk_bytes < OUTPUT_RESERVE_BYTES:
        return Check(
            "host_facts",
            BLOCKED,
            f"Only {host.free_disk_bytes // 1024**2} MiB free beside the output folder; {OUTPUT_RESERVE_BYTES // 1024**2} MiB are reserved for frames.",
        )
    return Check(
        "host_facts",
        PASS,
        f"RAM {host.total_ram_mib} MiB total / {host.available_ram_mib} MiB available, commit limit about {host.commit_limit_mib} MiB. "
        "Recorded only: no Fun Control memory threshold exists and none is borrowed from TI2V.",
    )


def run_q0(
    plan: QualificationPlan,
    *,
    folders: Mapping[str, Sequence[Path]] | None = None,
    host: HostFacts | None = None,
    inputs: Mapping[str, Path | None] | None = None,
    runtime_commit: str | None = None,
    verifier: Callable[[Any, Mapping[str, Sequence[Path]]], tuple[str, ...]] = verify_assets,
) -> Q0Report:
    checks = [_catalog_check(plan), _weights_check(folders, verifier)]
    checks.extend(_input_checks(plan, inputs or {}))
    checks.append(_runtime_check(plan, runtime_commit))
    checks.append(_host_check(host))
    checks.append(
        Check(
            "authorization",
            INFO,
            "Physical execution is NOT AUTHORIZED; Q1 and Q2 need a separate owner authorization bound to the plan digest.",
        )
    )
    return Q0Report(plan.digest, tuple(checks), host)
