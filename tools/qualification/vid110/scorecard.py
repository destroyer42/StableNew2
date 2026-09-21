"""Recorded reviewer scorecard and verdicts for the PR-VID-110 physical runs.

Visual criteria were scored 0-5 by reviewing contact sheets of each clip (see
``reports/vid110/runs`` locally; media is not committed).  Objective metrics come from
``metrics.py``.  Verdicts are computed, not asserted, by ``evidence.decide``.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

from tools.qualification.vid110 import evidence as ev

# (candidate, lane) -> (scores, observations)
SCORECARD: dict[tuple[str, str], tuple[dict[str, int], list[str]]] = {
    ("wan2.2-ti2v-5b", "i2v_walk_wave"): (
        {
            "identity_preservation": 4,
            "face_stability": 4,
            "limb_anatomy_integrity": 2,
            "temporal_coherence": 3,
            "prompt_action_adherence": 2,
        },
        [
            "Right-hand wave occurs in the second half; the requested walk toward the camera does not.",
            "Raised hand renders with a strong red colour cast; arm otherwise plausible.",
            "Face, clothing and framing match the source; camera static; oversaturated look.",
        ],
    ),
    ("wan2.2-ti2v-5b", "i2v_turn_raise_arms"): (
        {
            "identity_preservation": 4,
            "face_stability": 4,
            "limb_anatomy_integrity": 3,
            "temporal_coherence": 3,
            "prompt_action_adherence": 3,
        },
        [
            "Both arms rise overhead and lower part-way with plausible anatomy; the requested turn does not happen.",
            "Same person, clothing and framing as the source; slight skin-tone shift; camera static.",
        ],
    ),
    ("wan2.2-ti2v-5b", "user_i2v_prompt"): (
        {
            "identity_preservation": 4,
            "face_stability": 3,
            "limb_anatomy_integrity": 3,
            "temporal_coherence": 3,
            "prompt_action_adherence": 4,
        },
        [
            "Operator-supplied still: the person bends, grips a barbell and stands up lifting it, as prompted.",
            "Same person, clothing and hair throughout; saturation rises and a pink cast appears late.",
            "Face is soft and blotchy in mid-clip; hands and legs stay plausible.",
            "Camera tilts up late in the clip (background changes); the barbell has a plate on one end only.",
            "The driving clip is not an input to this lane; its motion curve is uncorrelated (r=-0.20).",
        ],
    ),
    ("wan2.1-vace-1.3b", "ref2v_walk_wave"): (
        {
            "identity_preservation": 1,
            "face_stability": 4,
            "limb_anatomy_integrity": 4,
            "temporal_coherence": 4,
            "prompt_action_adherence": 5,
        },
        [
            "Walks toward the camera with a clear gait and then waves the right hand: the prompt is followed.",
            "The person is NOT the source person (different face, skin, hair, shoes); reference weakly bound.",
            "Clean anatomy and background; static camera.",
        ],
    ),
    ("wan2.1-vace-1.3b", "ref2v_turn_raise_arms"): (
        {
            "identity_preservation": 1,
            "face_stability": 3,
            "limb_anatomy_integrity": 3,
            "temporal_coherence": 3,
            "prompt_action_adherence": 4,
        },
        [
            "Turns from profile to face the camera and raises an arm overhead (one arm, not both).",
            "Garment changes to long mesh sleeves mid-clip; person differs from the source.",
        ],
    ),
}


def svd_baseline_local_motion(root: Path = Path("output/SVD"), *, count: int = 6) -> float:
    """Mean local-motion metric of the most recent accepted native-SVD clips (metrics only)."""

    from tools.qualification.vid110.metrics import clip_metrics

    clips = sorted(glob.glob(str(root / "2026091[89]*" / "*.mp4")), key=os.path.getmtime)[-count:]
    values = [clip_metrics(Path(c)).local_motion_px for c in clips]
    return sum(values) / len(values)


def verdicts(runs_dir: Path, baseline: float) -> dict[str, tuple[str, list[str]]]:
    import json

    results: dict[str, tuple[str, list[str]]] = {}
    for (candidate, lane), (scores, notes) in SCORECARD.items():
        data = json.loads((runs_dir / f"{candidate}_{lane}.json").read_text(encoding="utf-8"))
        record = ev.RunEvidence(**{**data, "scores": scores, "observations": notes})
        results[f"{candidate}:{lane}"] = ev.decide(record, baseline, motion_transfer=False)
    return results
