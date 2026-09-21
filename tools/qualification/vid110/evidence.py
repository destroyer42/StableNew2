"""Evidence records, manual scorecards and the deterministic verdict rule."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PASS = "PASS"
CONDITIONAL = "CONDITIONAL"
NO_GO = "NO-GO"
HOLD = "HOLD"

# Manual visual criteria, each scored 0 (unusable) .. 5 (excellent) by a human/agent reviewer.
SCORE_CRITERIA = (
    "identity_preservation",
    "face_stability",
    "limb_anatomy_integrity",
    "temporal_coherence",
    "prompt_action_adherence",
    "driving_motion_fidelity",  # motion-transfer lanes only
)

# The bar for "materially better directed motion than SVD" and "operationally reasonable".
MOTION_RATIO_VS_SVD = 1.5
MIN_SCORE = 3
MAX_WALL_SECONDS = 20 * 60
VRAM_HEADROOM_MIB = 300


@dataclass
class RunEvidence:
    candidate: str
    lane: str
    evidence_class: str  # "stock-comfy" | "community-quantized" | "custom-node" | "reference"
    completed: bool = False
    failure: str = ""
    shared_gpu: bool = False  # another process held the GPU during the run
    model_files: dict[str, dict[str, str]] = field(
        default_factory=dict
    )  # name -> {revision, sha256}
    dependencies: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    wall_seconds: float = 0.0
    peaks: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, int] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    gpu_total_mib: int = 12282

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True, ensure_ascii=False)

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.candidate}_{self.lane}.json".replace(" ", "_")
        path.write_text(self.to_json(), encoding="utf-8")
        return path


def scoring_inputs_valid(scores: dict[str, int]) -> list[str]:
    """Problems with a scorecard (unknown criterion or out-of-range value)."""

    problems = [f"unknown criterion {k}" for k in scores if k not in SCORE_CRITERIA]
    problems += [f"{k}={v} outside 0..5" for k, v in scores.items() if not 0 <= int(v) <= 5]
    return problems


def decide(
    evidence: RunEvidence, baseline_local_motion_px: float, *, motion_transfer: bool
) -> tuple[str, list[str]]:
    """Deterministic verdict and its reasons.

    Executing is not enough: a candidate needs materially more real body motion than
    the SVD baseline, acceptable visual scores, and a reasonable footprint.
    """

    reasons: list[str] = []
    if not evidence.completed:
        return NO_GO, [f"did not complete: {evidence.failure or 'unknown failure'}"]
    problems = scoring_inputs_valid(evidence.scores)
    if problems:
        return HOLD, problems
    needed = [c for c in SCORE_CRITERIA if motion_transfer or c != "driving_motion_fidelity"]
    missing = [c for c in needed if c not in evidence.scores]
    if missing:
        return HOLD, [f"unscored criteria: {', '.join(missing)}"]

    motion = float(evidence.metrics.get("local_motion_px", 0.0))
    ratio = motion / baseline_local_motion_px if baseline_local_motion_px else float("inf")
    low = [c for c in needed if evidence.scores[c] < MIN_SCORE]
    if ratio < MOTION_RATIO_VS_SVD:
        reasons.append(f"body motion only {ratio:.2f}x the SVD baseline (< {MOTION_RATIO_VS_SVD}x)")
    reasons += [f"{c} scored {evidence.scores[c]} (< {MIN_SCORE})" for c in low]
    if reasons:
        return NO_GO, reasons

    caveats: list[str] = []
    if evidence.wall_seconds > MAX_WALL_SECONDS:
        caveats.append(f"wall time {evidence.wall_seconds:.0f}s exceeds {MAX_WALL_SECONDS}s")
    peak = float(evidence.peaks.get("vram_peak_mib", 0))
    if peak > evidence.gpu_total_mib - VRAM_HEADROOM_MIB:
        caveats.append(f"VRAM peak {peak:.0f} MiB leaves < {VRAM_HEADROOM_MIB} MiB headroom")
    if evidence.shared_gpu:
        caveats.append("measured on a shared GPU; capability on a dedicated card is unproven")
    if evidence.evidence_class != "stock-comfy":
        caveats.append(f"evidence class {evidence.evidence_class} is not stock-Comfy proof")
    if caveats:
        return CONDITIONAL, caveats
    return PASS, [f"body motion {ratio:.2f}x SVD with acceptable visual scores"]
