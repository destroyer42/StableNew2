"""Forward artifact-to-observed-seed association at the existing image-save boundary."""

from __future__ import annotations

import math
from typing import Any


def managed_runtime_observation(manager: Any) -> dict[str, Any] | None:
    """Read the existing manager's launch identity; never adopt or probe a process.

    Unowned/external runtimes remain viewable but cannot substantiate this
    same-launch controlled comparison. No new lifecycle authority is introduced.
    """
    if manager is None or getattr(manager, "owns_process", False) is not True:
        return None
    process = getattr(manager, "_process", None)
    pid, started = getattr(process, "pid", None), getattr(manager, "_start_time", None)
    epoch = getattr(manager, "ready_epoch", None)
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(started, (int, float))
        or isinstance(started, bool)
        or started <= 0
        or type(epoch) is not int
        or epoch <= 0
    ):
        return None
    result = {
        "pid": pid,
        "started": started,
        "ready_epoch": epoch,
        "endpoint": str(getattr(manager, "endpoint", "") or ""),
        "backend": str(getattr(manager, "runtime_identity", "") or ""),
    }
    return result if valid_runtime_observation(result) else None


def valid_runtime_observation(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and type(value.get("pid")) is int
        and value["pid"] > 0
        and type(value.get("started")) in (int, float)
        and math.isfinite(value["started"])
        and value["started"] > 0
        and type(value.get("ready_epoch")) is int
        and value["ready_epoch"] > 0
        and isinstance(value.get("endpoint"), str)
        and bool(value["endpoint"])
        and isinstance(value.get("backend"), str)
        and bool(value["backend"])
    )


def observed_sample(
    path: str, index: int, info: dict[str, Any], returned: int, job_id: str
) -> dict[str, Any] | None:
    """The response index is known here, before failed saves or reordering can lose it.

    No fallback to requested seeds, filenames or the response's first-seed field.
    """
    seeds = info.get("all_seeds")
    if (
        not job_id
        or not isinstance(seeds, list)
        or len(seeds) != returned
        or not 0 <= index < len(seeds)
        or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)
    ):
        return None
    return {"path": path, "seed": seeds[index], "sample_index": index, "job_id": job_id}
