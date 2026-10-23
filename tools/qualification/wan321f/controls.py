"""Deterministic qualification controls, with no live-runtime entry point.

The future physical adapter must use the existing ComfyProcessManager and typed
ComfyApiClient. These small controls can be tested without either service.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.qualification.wan321f.plan import build_graph, digest, frozen_plan


@dataclass(frozen=True)
class Sample:
    elapsed: float
    commit_percent: float
    commit_headroom_gib: float
    physical_available_gib: float
    owned_working_set_gib: float
    owned_private_gib: float
    vram_used_mib: float
    vram_total_mib: float
    gpu_ok: bool = True
    device_loss: bool = False


class SafetyGuard:
    """Fail closed on telemetry loss; limits are proposals until accepted by Rob."""

    def __init__(self, policy: Mapping[str, Any]) -> None:
        self.policy = dict(policy)
        for key in (
            "sample_seconds",
            "commit_percent_abort",
            "commit_headroom_gib_abort",
            "physical_available_gib_abort",
            "attempt_seconds",
            "session_seconds",
            "telemetry_gap_seconds",
            "consecutive",
        ):
            value = self.policy.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"Invalid safety limit: {key}")
        if type(self.policy["consecutive"]) is not int or self.policy["commit_percent_abort"] > 100:
            raise ValueError("Invalid safety count or percentage")
        self.consecutive = [0, 0, 0]
        self.last_elapsed: float | None = None
        self.reason = ""

    def observe(self, sample: Sample | None) -> str:
        if self.reason:
            return self.reason
        if sample is None:
            self.reason = "missing telemetry"
            return self.reason
        if type(sample.gpu_ok) is not bool or type(sample.device_loss) is not bool:
            self.reason = "invalid GPU status telemetry"
            return self.reason
        values = [v for k, v in vars(sample).items() if k not in ("gpu_ok", "device_loss")]
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
            for v in values
        ):
            self.reason = "invalid telemetry"
        elif (
            sample.commit_percent > 100
            or sample.vram_total_mib <= 0
            or sample.vram_used_mib > sample.vram_total_mib
        ):
            self.reason = "inconsistent telemetry"
        elif sample.device_loss or not sample.gpu_ok:
            self.reason = "GPU unavailable or device loss"
        elif self.last_elapsed is not None and (
            sample.elapsed <= self.last_elapsed
            or sample.elapsed - self.last_elapsed > self.policy["telemetry_gap_seconds"]
        ):
            self.reason = "telemetry stalled or time reversed"
        elif sample.elapsed >= self.policy["attempt_seconds"]:
            self.reason = "attempt time limit"
        else:
            conditions = (
                sample.commit_percent >= self.policy["commit_percent_abort"],
                sample.commit_headroom_gib < self.policy["commit_headroom_gib_abort"],
                sample.physical_available_gib < self.policy["physical_available_gib_abort"],
            )
            self.consecutive = [
                n + 1 if bad else 0 for n, bad in zip(self.consecutive, conditions, strict=True)
            ]
            for name, count in zip(
                ("system commit", "commit headroom", "physical RAM"), self.consecutive, strict=True
            ):
                if count >= self.policy["consecutive"]:
                    self.reason = f"safety stop: {name}"
                    break
        self.last_elapsed = sample.elapsed
        return self.reason


def write_new_json(path: Path, value: Any) -> None:
    """Evidence is append-only by identity: refuse replacement, flush before returning."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


class AttemptLedger:
    """Reserve before dispatch. A used/ambiguous attempt identity can never dispatch again.

    A physical adapter must additionally hold the one exclusive session claim for
    its entire budget. Qualification evidence is not a production queue or history.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def dispatch_once(self, attempt: int, submit: Callable[[dict[str, Any]], Any]) -> Any:
        graph = build_graph(attempt)
        directory = self.root / f"attempt-{attempt}"
        directory.mkdir()  # No exist_ok: even a crash before /prompt consumes this identity.
        write_new_json(directory / "graph.json", graph)
        write_new_json(
            directory / "dispatch-intent.json", {"attempt": attempt, "graph_sha256": digest(graph)}
        )
        try:
            reply = submit({"prompt": graph})  # Exactly one non-idempotent call; no retries here.
        except BaseException as exc:
            write_new_json(directory / "dispatch-unresolved.json", {"type": type(exc).__name__})
            raise
        if (
            not isinstance(reply, dict)
            or not isinstance(reply.get("prompt_id"), str)
            or not reply["prompt_id"].strip()
        ):
            write_new_json(directory / "dispatch-unresolved.json", {"type": "invalid prompt reply"})
            raise ValueError("Dispatch outcome unresolved; end session, never replay")
        write_new_json(directory / "dispatch-ack.json", reply)
        return reply


@contextmanager
def owned_session(manager: Any):
    """Use the existing manager's ownership; never adopt or stop an external process.

    Startup, endpoint refusal and process-tree containment remain the manager's
    responsibility. A failed startup is cleaned only if that manager owns a child.
    """
    if manager.owns_process:
        raise RuntimeError("Qualification requires a new manager with no prior child")
    try:
        manager.start()
        if not manager.owns_process or not manager.contained:
            raise RuntimeError("Owned process containment was not established")
        yield manager
    finally:
        if manager.owns_process:
            manager.stop()
        if manager.owns_process or manager.is_running():
            raise RuntimeError("Owned-process teardown unverified; verdict INCONCLUSIVE")


def physical_refusals() -> list[str]:
    """No executable physical adapter is shipped in Stage 1."""
    plan = frozen_plan()
    reasons = [
        "Stage 1 only: separate authorization for assets, generation and runtime operations is required"
    ]
    if not plan["safety_proposal"]["owner_accepted"]:
        reasons.append("Owner acceptance of abort thresholds and time limits is missing")
    if plan["budget"]["automatic_retries"] is None:
        reasons.append("Total attempt/retry budget clarification is missing")
    return reasons
