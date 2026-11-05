"""Read-only before/after comparator over two sealed attempt archives.

Alignment first: the two attempts must share the arm, stage, benchmark version, and the same per-case model/workflow
identity, prompts, source hashes, seeds, parameters and geometry.  Any difference there makes the pair *not comparable* and
is listed.  Hardware, driver and runtime differences do not block the comparison but make timing and resource metrics
inconclusive.  A stochastic quality metric needs at least ``MIN_QUALITY_SAMPLES`` ratings on each side; a single sample is
never reported as an improvement.  Raw evidence is never modified: the computed comparison is written to a separate file
that must live outside both archives and must not already exist.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_json
from tools.qualification.system840 import evidence

IMPROVED, UNCHANGED, DEGRADED, INCONCLUSIVE = "improved", "unchanged", "degraded", "inconclusive"
EXIT_OK, EXIT_DEGRADED, EXIT_INCOMPARABLE = 0, 1, 5
MIN_QUALITY_SAMPLES = 2
TIMING_TOLERANCE = 0.15
_CONTEXT_KEYS = ("gpu", "python", "os", "hostname")


class Incomparable(Exception):
    """The two attempts cannot be compared (missing, unsealed, tampered, or not aligned)."""


@dataclass(frozen=True)
class Metric:
    name: str
    key: str  # dotted path inside manifest["result"]["metrics"]
    better: str  # "lower" | "higher" | "true"
    tolerance: float = 0.0  # relative; zero means any difference counts
    hardware_bound: bool = False  # inconclusive when the hardware/runtime context differs
    stochastic: bool = False  # needs MIN_QUALITY_SAMPLES on both sides


METRICS: tuple[Metric, ...] = (
    Metric("qualification_pass_coverage", "pass_coverage", "higher"),
    Metric("artifacts_per_admitted_attempt", "artifacts_per_admitted", "higher"),
    Metric(
        "execution_duration_seconds", "wall_seconds", "lower", TIMING_TOLERANCE, hardware_bound=True
    ),
    Metric("operator_interventions", "operator_interventions", "lower"),
    Metric(
        "host_commit_fraction_peak", "host_commit_fraction_peak", "lower", 0.05, hardware_bound=True
    ),
    Metric("gpu_vram_peak_mib", "gpu_vram_peak_mib", "lower", 0.05, hardware_bound=True),
    Metric(
        "host_available_ram_min_mib",
        "host_available_ram_min_mib",
        "higher",
        0.05,
        hardware_bound=True,
    ),
    Metric("queue_history_integrity", "queue_history_consistent", "true"),
    Metric("error_count", "error_count", "lower"),
    Metric("crash_count", "crash_count", "lower"),
    Metric("timeout_count", "timeout_count", "lower"),
    Metric("image_quality_rating", "image_quality_mean", "higher", 0.0, stochastic=True),
    Metric("video_quality_rating", "video_quality_mean", "higher", 0.0, stochastic=True),
    Metric("ai_response_quality", "ai_quality_mean", "higher", 0.0, stochastic=True),
    Metric("ai_safety_violations", "ai_safety_violations", "lower"),
    Metric(
        "ai_latency_median_seconds",
        "ai_latency_median_seconds",
        "lower",
        TIMING_TOLERANCE,
        hardware_bound=True,
    ),
)


def _get(path: str, data: Mapping[str, Any]) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def load_attempt(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    report = evidence.verify_attempt(path)
    if report["status"] != evidence.OK:
        raise Incomparable(f"{path} is {report['status']}: {'; '.join(report['problems'][:3])}")
    manifest = evidence.load_manifest(path)
    plan = json.loads((path / evidence.PLAN_FILE).read_text(encoding="utf-8"))
    return {"path": str(path), "manifest": manifest, "plan": plan}


def alignment_key(plan: Mapping[str, Any]) -> dict[str, Any]:
    cases = {}
    for case in plan.get("cases") or []:
        cases[str(case.get("case_id"))] = {
            "capability_id": case.get("capability_id"),
            "model": {k: (case.get("model") or {}).get(k) for k in ("sha256", "size")},
            "workflow": case.get("workflow"),
            "sources": sorted((s.get("role"), s.get("sha256")) for s in case.get("sources") or []),
            "prompts": case.get("prompts"),
            "seeds": case.get("seeds"),
            "settings": case.get("settings"),
            "geometry": case.get("geometry"),
            "cpu_inference": {
                k: (case.get("cpu_inference") or {}).get(k)
                for k in ("model_id", "runtime_sha256", "command")
            },
        }
    return {
        "arm_id": plan.get("arm_id"),
        "stage": plan.get("stage"),
        "benchmark_version": plan.get("benchmark_version"),
        "cases": cases,
    }


def context(plan: Mapping[str, Any]) -> dict[str, Any]:
    env = plan.get("environment") or {}
    return {
        **{k: env.get(k) for k in _CONTEXT_KEYS},
        "runtime_identity": (plan.get("runtime") or {}).get("identity"),
        "runtime_ownership": (plan.get("runtime") or {}).get("ownership"),
        "repo_sha": (env.get("repo") or {}).get("sha"),
    }


def alignment_problems(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    a, b = alignment_key(before), alignment_key(after)
    problems: list[str] = []
    for key in ("arm_id", "stage", "benchmark_version"):
        if a[key] != b[key]:
            problems.append(f"{key}: {a[key]!r} vs {b[key]!r}")
    for case_id in sorted(set(a["cases"]) | set(b["cases"])):
        left, right = a["cases"].get(case_id), b["cases"].get(case_id)
        if left is None or right is None:
            problems.append(f"case {case_id} exists on one side only")
            continue
        for field in sorted(left):
            if left[field] != right[field]:
                problems.append(f"case {case_id}: {field} differs")
    return problems


def context_differences(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    a, b = context(before), context(after)
    return [f"{k}: {a[k]!r} vs {b[k]!r}" for k in a if k != "repo_sha" and a[k] != b[k]]


def _judge(
    metric: Metric, old: Any, new: Any, *, same_hardware: bool, old_n: int, new_n: int
) -> dict[str, Any]:
    entry: dict[str, Any] = {"metric": metric.name, "before": old, "after": new}
    if old is None or new is None:
        return {**entry, "verdict": INCONCLUSIVE, "reason": "the value is absent on one side"}
    if metric.hardware_bound and not same_hardware:
        return {**entry, "verdict": INCONCLUSIVE, "reason": "hardware or runtime context differs"}
    if metric.stochastic and min(old_n, new_n) < MIN_QUALITY_SAMPLES:
        return {
            **entry,
            "verdict": INCONCLUSIVE,
            "reason": f"a single stochastic sample is not evidence (need {MIN_QUALITY_SAMPLES} per side)",
        }
    if metric.better == "true":
        if bool(old) == bool(new):
            return {**entry, "verdict": UNCHANGED}
        return {**entry, "verdict": IMPROVED if new else DEGRADED}
    old_f, new_f = float(old), float(new)
    if old_f == new_f:
        return {**entry, "verdict": UNCHANGED}
    scale = abs(old_f) or 1.0
    if abs(new_f - old_f) / scale <= metric.tolerance:
        return {
            **entry,
            "verdict": UNCHANGED,
            "reason": f"within the {metric.tolerance:.0%} tolerance",
        }
    better = new_f > old_f if metric.better == "higher" else new_f < old_f
    return {**entry, "verdict": IMPROVED if better else DEGRADED}


def compare(before_path: Path | str, after_path: Path | str) -> dict[str, Any]:
    """Compare two sealed attempts.  Raises ``Incomparable`` when they cannot be aligned."""

    before, after = load_attempt(before_path), load_attempt(after_path)
    mismatches = alignment_problems(before["plan"], after["plan"])
    if mismatches:
        raise Incomparable("not aligned: " + "; ".join(mismatches[:6]))
    diffs = context_differences(before["plan"], after["plan"])
    same_hardware = not diffs
    old_metrics = (before["manifest"].get("result") or {}).get("metrics") or {}
    new_metrics = (after["manifest"].get("result") or {}).get("metrics") or {}
    results = []
    for metric in METRICS:
        results.append(
            _judge(
                metric,
                _get(metric.key, old_metrics),
                _get(metric.key, new_metrics),
                same_hardware=same_hardware,
                old_n=int(_get(f"{metric.key}_n", old_metrics) or 0),
                new_n=int(_get(f"{metric.key}_n", new_metrics) or 0),
            )
        )
    counts = {
        v: sum(1 for r in results if r["verdict"] == v)
        for v in (IMPROVED, UNCHANGED, DEGRADED, INCONCLUSIVE)
    }
    return {
        "before": before["path"],
        "after": after["path"],
        "arm_id": after["plan"].get("arm_id"),
        "benchmark_version": after["plan"].get("benchmark_version"),
        "context_differences": diffs,
        "repo_shas": {
            "before": context(before["plan"])["repo_sha"],
            "after": context(after["plan"])["repo_sha"],
        },
        "metrics": results,
        "summary": counts,
        "claims_significance": False,
        "note": "raw evidence is unchanged; this file is a computed comparison and is never evidence itself",
    }


def exit_code(report: Mapping[str, Any]) -> int:
    return EXIT_DEGRADED if report["summary"].get(DEGRADED) else EXIT_OK


def write_comparison(report: Mapping[str, Any], out: Path | str) -> Path:
    """Write the computed comparison apart from the raw evidence: never inside either archive, never over a file."""

    out = Path(out).resolve()
    for key in ("before", "after"):
        root = Path(report[key]).resolve()
        if out == root or root in out.parents:
            raise evidence.ArchiveRefused(
                "a comparison is never written inside the evidence it compares"
            )
    if out.exists():
        raise evidence.ArchiveRefused(f"{out} already exists; comparisons are not overwritten")
    out.parent.mkdir(parents=True, exist_ok=True)
    return atomic_write_json(out, dict(report), indent=2, sort_keys=True)
