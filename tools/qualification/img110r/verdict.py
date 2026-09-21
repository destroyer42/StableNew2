"""Deterministic verdict rules for PR-IMG-110R (torch-free, unit-tested).

Two questions are answered separately because the brief distinguishes them:

* ``model_on_hardware`` - can Ideogram 4 NF4 run on this GPU at all, and how usefully?
* ``diffusers_path``    - is the current Diffusers implementation a viable way to run it?
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.qualification.img110r.common import RunRecord

PASS_PRACTICAL = "PASS - PRACTICAL"
PASS_CONSTRAINED = "PASS - CONSTRAINED"
SOFTWARE_NO_GO = "SOFTWARE/RUNTIME NO-GO"
DRIVER_NO_GO = "CURRENT DRIVER/STACK NO-GO"
HARDWARE_NO_GO = "HARDWARE-CAPACITY NO-GO"
INCONCLUSIVE = "INCONCLUSIVE"

PRACTICAL_MIN_PIXELS = 768 * 1024  # a StableNew-class portrait/landscape workload
PRACTICAL_MAX_GENERATE_SECONDS = 300.0  # per image once the model is resident
# Runtimes that only succeed because the harness adds an explicit residency policy (text encoder
# staged first, one transformer resident at a time).  The brief counts that as CONSTRAINED, not
# PRACTICAL: PRACTICAL needs an unmodified documented path to work at a StableNew-class size.
EXPLICIT_POLICY_MARKER = "staged"
SOFTWARE_CLASSES = {"runtime_api_offload", "dtype_kernel_driver", "harness", "acquisition_schema"}
EXECUTED_STAGES = {"denoising", "decoding", "complete_failed_after_step"}


@dataclass(frozen=True)
class Verdict:
    model_on_hardware: str
    diffusers_path: str
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_on_hardware": self.model_on_hardware,
            "diffusers_path": self.diffusers_path,
            "reasons": self.reasons,
        }


def explicit_policy(record: RunRecord) -> bool:
    return EXPLICIT_POLICY_MARKER in record.runtime


def _ok(record: RunRecord) -> bool:
    return record.success and bool(record.output.get("valid"))


def _generate_seconds(record: RunRecord) -> float:
    return float(record.timing.get("generate_total_s", float("inf")))


def _reproduced(records: list[RunRecord], record: RunRecord) -> bool:
    return (
        sum(1 for r in records if _ok(r) and (r.runtime, r.level) == (record.runtime, record.level))
        >= 2
    )


def _diffusers_path(records: list[RunRecord]) -> tuple[str, str]:
    diffusers = [r for r in records if r.family == "diffusers"]
    if not diffusers:
        return INCONCLUSIVE, "no Diffusers runs recorded"
    if any(_ok(r) for r in diffusers):
        best = max((r for r in diffusers if _ok(r)), key=lambda r: r.width * r.height)
        return "VIABLE", f"Diffusers completed {best.runtime} at level {best.level}"
    classes = {r.classification for r in diffusers}
    if classes and classes <= SOFTWARE_CLASSES | {"no_progress_timeout"}:
        return SOFTWARE_NO_GO, f"every Diffusers run failed in software classes {sorted(classes)}"
    return INCONCLUSIVE, f"Diffusers failure classes {sorted(classes)} do not isolate a cause"


def decide(records: list[RunRecord]) -> Verdict:
    reasons: list[str] = []
    diffusers_status, diffusers_reason = _diffusers_path(records)
    reasons.append(diffusers_reason)
    successes = [r for r in records if _ok(r)]

    practical = [
        r
        for r in successes
        if r.width * r.height >= PRACTICAL_MIN_PIXELS
        and not explicit_policy(r)
        and _generate_seconds(r) <= PRACTICAL_MAX_GENERATE_SECONDS
        and _reproduced(records, r)
    ]
    if practical:
        best = max(practical, key=lambda r: (r.width * r.height, -_generate_seconds(r)))
        reasons.append(
            f"{best.runtime} completed {best.width}x{best.height} {best.preset} in "
            f"{_generate_seconds(best):.0f}s and reproduced"
        )
        return Verdict(PASS_PRACTICAL, diffusers_status, reasons)

    if successes:
        best = max(successes, key=lambda r: (r.width * r.height, r.steps))
        repeat = "reproduced" if _reproduced(records, best) else "not yet reproduced"
        policy = "an explicit residency policy" if explicit_policy(best) else "a documented path"
        reasons.append(
            f"largest valid run: {best.runtime} {best.width}x{best.height} {best.preset} "
            f"({repeat}) using {policy}; PRACTICAL needs a documented path (no added residency "
            f"policy) at >={PRACTICAL_MIN_PIXELS} px in <={PRACTICAL_MAX_GENERATE_SECONDS:.0f}s, "
            "reproduced"
        )
        return Verdict(PASS_CONSTRAINED, diffusers_status, reasons)

    faults = [
        r
        for r in records
        if r.family == "official" and r.classification in {"dtype_kernel_driver", "machine_fault"}
    ]
    if len(faults) >= 2:
        reasons.append(f"{len(faults)} official-path runs faulted outside VRAM exhaustion")
        return Verdict(DRIVER_NO_GO, diffusers_status, reasons)

    lowest = min((r.level for r in records), default=None)
    exhausted = {
        family: [
            r
            for r in records
            if r.family == family
            and r.level == lowest
            and r.classification == "resource_exhaustion"
            and r.stage in EXECUTED_STAGES | {"loading_transformers", "loading"}
        ]
        for family in ("official", "diffusers")
    }
    if all(len(runs) >= 2 for runs in exhausted.values()):
        reasons.append("both families reproducibly exhausted resources at the lowest level")
        return Verdict(HARDWARE_NO_GO, diffusers_status, reasons)

    reasons.append("no valid image and no reproduced, isolated failure cause")
    return Verdict(INCONCLUSIVE, diffusers_status, reasons)
