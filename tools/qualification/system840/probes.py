"""Injectable host probes for the campaign: the golden-path probes plus working-tree identity and process ownership."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tools.operator_journey.golden.host import HostProbes
from tools.operator_journey.workspace import REPO_ROOT


def tree_identity() -> dict[str, Any]:
    """The exact checkout state a plan freezes: HEAD, the modified tracked files and a digest of the whole diff."""

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=REPO_ROOT, text=True, encoding="utf-8", timeout=60
        )

    try:
        sha = git("rev-parse", "HEAD").strip()
        dirty = sorted(
            line[3:].strip()
            for line in git("status", "--porcelain", "--untracked-files=no").splitlines()
            if line.strip()
        )
        diff = git("diff", "HEAD") if dirty else ""
    except (OSError, subprocess.SubprocessError):
        return {"sha": "unknown", "dirty_files": ["git unavailable"], "diff_sha256": ""}
    return {
        "sha": sha,
        "dirty_files": dirty,
        "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest() if dirty else "",
    }


@dataclass
class QualProbes(HostProbes):
    """``HostProbes`` plus what an arm needs before dispatch.  Every probe is replaceable, so tests need no host."""

    tree: Callable[[], dict[str, Any]] = tree_identity
    #: Active generations on the target runtime (an incompatible one blocks a new arm); each item is a dict.
    active_generations: Callable[[str], list[dict[str, Any]]] = lambda base_url: []
    #: Unresolved safety stops from prior attempts, read from the evidence root (device loss, unsafe teardown, ...).
    unresolved_stops: Callable[[], list[dict[str, Any]]] = lambda: []
    #: Whether the telemetry sampler can produce a sample right now.
    telemetry_available: Callable[[], bool] = lambda: True
    #: GPU generations active anywhere on the host (any endpoint); CPU inference must yield to them and never mixes with them.
    gpu_activity: Callable[[], list[dict[str, Any]]] = lambda: []
    #: AI lane only: ``{"active": bool, "canary_pass_age_hours": float | None, "protected_interpreter": bool,
    #: "child_memory_limit_verified": bool}``; an absent or unreadable capture state is a HOLD, never a bypass.
    ai_capture_state: Callable[[], dict[str, Any]] = lambda: {}
    #: Launch flags of the runtime this plan targets (``None`` when they cannot be read); compared with the frozen flags.
    launch_flags: Callable[[dict[str, Any]], list[str] | None] = lambda runtime: None
    #: Whether fault collection (device-loss/hang recorder or the process-ownership log) is writable.
    fault_collection_available: Callable[[], bool] = lambda: True
