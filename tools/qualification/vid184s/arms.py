"""PR-VID-184S B1 / A / B2 arm manifests, frozen matched-state bands and pre-registered
classification rules. Pure functions only; nothing here touches a GPU or the machine.

Frozen BEFORE Arm B1 is run (values must not change after any result is seen).
"""

from __future__ import annotations

import re
from typing import Any

from tools.qualification.vid184r import arm_manifest as base

ARMS = ("B1", "A", "B2")
EVIDENCE_ROOT = r"C:\Users\rob\qual\vid184\env\evidence_184s"
PINNED_FLAG = base.PINNED_FLAG

# ---- frozen matched-state bands (reference = Arm B1 immediately-pre-dispatch snapshot) ----------
BAND_COMMIT_PERCENT_POINTS = 3.0
BAND_PHYSICAL_AVAILABLE_GB = 1.5
BAND_FREE_VRAM_MIB = 512.0
MAX_MINUTES_SINCE_BOOT = 60.0  # "fresh normal Windows boot" gate
# Frozen definition of "substantially worse resource pressure" (Arm A vs Arm B1 commit peak).
PRESSURE_COMMIT_PEAK_DELTA_POINTS = 10.0

# Manifest keys allowed to differ between any two arms.
ALLOWED_DIFF_KEYS = frozenset({"arm", "launch_args", "evidence_dir", "pinned_memory_expected"})


def launch_args(arm: str) -> list[str]:
    if arm in ("B1", "B2"):
        return base.launch_args("B")
    if arm == "A":
        return base.launch_args("A")
    raise ValueError(f"unknown arm {arm!r}")


def arm_manifest(arm: str) -> dict[str, Any]:
    pinned_off = arm in ("B1", "B2")
    return {
        **base.FROZEN_WORKLOAD,
        "arm": arm,
        "launch_args": launch_args(arm),
        "pinned_memory_expected": (
            "disabled (no 'Enabled pinned memory' log line)"
            if pinned_off
            else "enabled (log: 'Enabled pinned memory')"
        ),
        "evidence_dir": rf"{EVIDENCE_ROOT}\{arm}",
    }


def execution_equivalent(x: dict[str, Any], y: dict[str, Any]) -> bool:
    """True when two manifests differ only in arm identity/evidence location."""
    return set(base.diff_manifests(x, y)) <= {"arm", "evidence_dir"}


def hidden_flag_check(arm: str) -> list[str]:
    joined = " ".join(launch_args(arm))
    return [f for f in base.FORBIDDEN_FLAGS if f in joined]


# ---- matched-state gate --------------------------------------------------------------------------
def state_vector(commit: dict[str, float], gpu: dict[str, Any] | None) -> dict[str, float | None]:
    return {
        "commit_percent": commit["commit_percent"],
        "physical_available_gb": commit["physical_available_gb"],
        "free_vram_mib": None if gpu is None else gpu["vram_free_mib"],
    }


def matched_state_check(
    ref: dict[str, float | None], cur: dict[str, float | None]
) -> dict[str, Any]:
    """Compare a pre-dispatch state vector to the B1 reference; record absolute values and deltas."""
    bands = {
        "commit_percent": BAND_COMMIT_PERCENT_POINTS,
        "physical_available_gb": BAND_PHYSICAL_AVAILABLE_GB,
        "free_vram_mib": BAND_FREE_VRAM_MIB,
    }
    rows: dict[str, Any] = {}
    ok = True
    for key, band in bands.items():
        r, c = ref[key], cur[key]
        if r is None or c is None:
            rows[key] = {"reference": r, "current": c, "delta": None, "band": band, "within": False}
            ok = False
            continue
        delta = round(c - r, 3)
        within = abs(delta) <= band
        ok = ok and within
        rows[key] = {"reference": r, "current": c, "delta": delta, "band": band, "within": within}
    return {"matched": ok, "rows": rows}


# ---- log analysis --------------------------------------------------------------------------------
_ERROR_PATTERNS = {
    "hostbuffer_error": r"HostBuffer",
    "cuda_error": r"CUDA error|cudaError|CUDA_ERROR",
    "sticky_error": r"sticky",
    "oom": r"(?i:OutOfMemory|out of memory)",
    "traceback": r"Traceback \(most recent call last\)",
    "gpu_lost": r"device-side assert|unspecified launch failure|illegal memory access|GPU is lost",
}


def analyze_log(text: str) -> dict[str, Any]:
    m = re.search(r"Enabled pinned memory\s+([0-9.]+)", text)
    steps = re.findall(r"(\d+)/10 \[[0-9:]+<[0-9:?]+, *([0-9.]+)s/it", text)
    done = re.search(r"Prompt executed in ([0-9.]+) seconds", text)
    return {
        "enabled_pinned_memory_line": m.group(0) if m else None,
        "enabled_pinned_memory_value": m.group(1) if m else None,
        "last_step_seen": int(steps[-1][0]) if steps else None,
        "prompt_executed_seconds": float(done.group(1)) if done else None,
        **{k: len(re.findall(p, text)) for k, p in _ERROR_PATTERNS.items()},
    }


# ---- pre-registered outcome classification -------------------------------------------------------
def arm_status(a: dict[str, Any] | None) -> str:
    """Normalise one arm record to COMPLETED / GPU_LOSS / SEVERE / CLEAN_FAIL / NOT_RUN /
    MATCHED_STATE_GATE_NOT_MET."""
    if a is None:
        return "NOT_RUN"
    if a.get("matched_state_gate_not_met"):
        return "MATCHED_STATE_GATE_NOT_MET"
    if a.get("severe_system_fault"):
        return "SEVERE"
    if a.get("outcome") == "COMPLETED":
        return "COMPLETED"
    if a.get("gpu_lost"):
        return "GPU_LOSS"
    return "CLEAN_FAIL"


def resource_pressure_worse(b1: dict[str, Any], a: dict[str, Any]) -> bool:
    delta = a["peaks"]["commit_peak_percent"] - b1["peaks"]["commit_peak_percent"]
    return delta >= PRESSURE_COMMIT_PEAK_DELTA_POINTS


def _early(status: dict[str, str], labels: list[str], notes: list[str]) -> dict[str, Any]:
    return {"status": status, "labels": labels, "notes": notes, "stopped_early": True}


def classify(results: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    """Apply the PR-VID-184S pre-registered rules. ``results`` maps B1/A/B2 to arm records.

    Resolution of an ambiguity in the brief: "all three complete" always yields
    ORIGINAL_PINNED_MEMORY_FAILURE_NOT_REPRODUCED_UNDER_MATCHED_STATE; a materially higher
    commit peak in A is then recorded as a separate secondary label, never as the strong label.
    """
    s = {k: arm_status(results.get(k)) for k in ARMS}
    fail_b1 = "DISABLE_PINNED_MEMORY_REPRODUCIBILITY_NOT_CONFIRMED"

    if s["B1"] in ("GPU_LOSS", "SEVERE"):
        return _early(
            s, [fail_b1], ["B1 lost the GPU or hit a hard fault: package stopped, A not run"]
        )
    if s["B1"] == "CLEAN_FAIL":
        return _early(s, [fail_b1], ["B1 cleanly failed: causal comparison invalidated, A not run"])
    if s["B1"] in ("MATCHED_STATE_GATE_NOT_MET", "NOT_RUN"):
        return _early(s, [], ["B1 not executed"])
    if s["A"] == "SEVERE":
        return _early(
            s,
            ["PINNED_MEMORY_SEVERE_SYSTEM_FAULT_DIAG_GPU_BOUNDARY"],
            ["A produced a system-level fault: B2 not run automatically"],
        )
    for arm in ("A", "B2"):
        if s[arm] == "MATCHED_STATE_GATE_NOT_MET":
            return _early(
                s,
                ["MATCHED_STATE_GATE_NOT_MET"],
                [f"{arm}: fresh-boot idle state did not enter the frozen bands"],
            )
    if s["A"] == "NOT_RUN" or s["B2"] == "NOT_RUN":
        return {
            "status": s,
            "labels": [],
            "notes": ["incomplete: arms remain"],
            "stopped_early": False,
        }

    if s["B2"] != "COMPLETED":
        return {
            "status": s,
            "labels": ["RUN_TO_RUN_REPRODUCIBILITY_UNRESOLVED"],
            "notes": ["B2 did not complete: no A/B causal result is claimed"],
            "stopped_early": False,
        }

    labels = ["WAN_ANIMATE_2_LOCAL_EXECUTION_REPRODUCIBLE_WITH_PINNED_MEMORY_DISABLED"]
    notes: list[str] = []
    if s["A"] == "COMPLETED":
        labels.append("ORIGINAL_PINNED_MEMORY_FAILURE_NOT_REPRODUCED_UNDER_MATCHED_STATE")
        if resource_pressure_worse(results["B1"], results["A"]):  # type: ignore[arg-type]
            labels.append("PINNED_MEMORY_RESOURCE_PRESSURE_EFFECT_REPRODUCED")
            notes.append("A completed with materially higher commit pressure (recorded separately)")
    elif s["A"] == "GPU_LOSS":
        labels.append("PINNED_MEMORY_EFFECT_REPRODUCED_UNDER_MATCHED_STATE")
    else:
        labels.append("PINNED_MEMORY_STATE_ASSOCIATED_WITH_MATERIAL_RUNTIME_DIFFERENCE")
    return {"status": s, "labels": labels, "notes": notes, "stopped_early": False}


__all__ = [
    "ARMS", "ALLOWED_DIFF_KEYS", "arm_manifest", "analyze_log", "arm_status", "classify",
    "execution_equivalent", "hidden_flag_check", "launch_args", "matched_state_check",
    "resource_pressure_worse", "state_vector",
]  # fmt: skip
