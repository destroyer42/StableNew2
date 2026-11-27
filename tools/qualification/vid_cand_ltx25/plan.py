"""VID-CAND-LTX25 frozen evaluation design: LTX-2.5 suites derived from the frozen VID-CAND-382 suites.

Pure data and functions.  The comparison is three-way (A14B, HunyuanVideo 1.5, LTX-2.5) and the A14B and Hunyuan arms
are VID-CAND-382's own runs: LTX copies their cases, images, prompts and seeds unchanged and runs only its own arms, so
nothing here re-runs or alters that package's frozen suites.  Clips are joined by ``case_id`` afterwards (``threeway``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tools.qualification.vid_cand382 import plan as base

PLAN_SCHEMA = "stablenew.vid-cand-ltx25-plan.v1"
TASK = "VID-CAND-LTX25"

LTX25_ID = "ltx25_distilled_i2v_v1"
LTX25_AUDIO_ID = "ltx25_distilled_i2v_audio_v1"
LTX25_VERSION = "1.0.0"
LTX25_ARM = "ltx25_distilled"
LTX25_AUDIO_ARM = "ltx25_distilled_audio"
LTX25_FRAMES = 121  # 121 frames at 24 fps = 5.04 s, as the Hunyuan arms; A14B 81 at 16 fps = 5.06 s
AUDIO_PROMPT_SUFFIX = " Soft natural room sound that matches the movement; no music, no speech."
AUDIO_CASES = 4
STAGE0_SEED = base.SEEDS["stage0"]

SUITE_FILES = {
    "stage0": "20261127_vidcandltx25_stage0_smoke_v001.suite.json",
    "stage1": "20261127_vidcandltx25_stage1_head_to_head_v001.suite.json",
    "stage2": "20261127_vidcandltx25_stage2_hard_cases_v001.suite.json",
    "audio": "20261127_vidcandltx25_audio_v001.suite.json",
}
PLAN_FILE = "vid_cand_ltx25_plan.v1.json"

FAIRNESS_RULES = (
    "Sources, prompts, negative prompts and seeds are VID-CAND-382's frozen stage 1 and stage 2 cases, unchanged.",
    "Equal clip duration at native frame rates: A14B 81 frames at 16 fps (5.06 s), Hunyuan and LTX-2.5 121 frames at "
    "24 fps (5.04 s). RIFE smoothing is OFF for every arm.",
    "Each engine runs at its own practical size and the report states it: A14B 480x832, Hunyuan 480x848, LTX-2.5 "
    "768x1344 portrait (2.6 times A14B's pixels, same aspect to within 1 %). Resolution and frame rate can reveal the "
    "engine, so the blind sheet hides names only.",
    "The visual comparison uses the silent LTX-2.5 workflow (StableNew-encoded frames, like every other arm). The audio "
    "workflow's picture is encoded by ComfyUI and is never compared with other engines' clips.",
    "LTX-2.5 runs in a different host session than A14B and Hunyuan: its timings are labelled cross-session and no "
    "speed ratio is applied unless the owner authorizes an A14B re-run in the same session.",
    "Ratings are the owner's. The three-way sheet is blind (names hidden, order shuffled with a recorded seed); it is "
    "only fully blind for cases the owner has not already rated with names visible. An agent never fills a sheet.",
    "No settings change after a resource failure within a frozen plan; a change is a new plan and digest.",
)

THRESHOLDS: dict[str, Any] = {
    "no_go": {
        **base.THRESHOLDS["no_go"],
        "material_regression_baseline": "the A14B clip and rating of the same case in the VID-CAND-382 run",
    },
    "as_good_or_better": {
        **base.THRESHOLDS["as_good_or_better"],
        "stage1_baseline": "A14B means of the VID-CAND-382 stage 1 ratings",
        "blind_preference": "three-way sheet: LTX-2.5 ranked above A14B in at least half of the answered rankings "
        "(ties split)",
    },
    "speed": {
        "verdict": "none: VID-CAND-382's warm-time ratio is not applied across sessions",
        "reported": "LTX-2.5 cold and warm wall times, labelled cross-session beside VID-CAND-382's",
        "wall_time_source": "job repository started_at to completed_at",
        "for_a_verdict": "an owner-authorized A14B re-run in the same host session, as a new plan",
    },
    "audio": "reported, not gated: whether the audio is present, usable and in step with the motion, and its extra time "
    "and memory",
    "recommendation_values": [
        "do not adopt",
        "add LTX-2.5 as approved alternate (owner decision)",
        "candidate for default (owner decision)",
    ],
}

STOP_RULES = base.STOP_RULES

BUDGET = {
    "stage0_jobs": 2,
    "stage1_jobs": 8,
    "stage2_jobs": 8,
    "audio_jobs": AUDIO_CASES,
    "max_generations": 22,
    "overall_cap": 30,
    "job_budget_seconds": 1500,
    "auto_retry": False,
}


def _arm(audio: bool) -> dict[str, Any]:
    arm_id, workflow_id, label = (
        (LTX25_AUDIO_ARM, LTX25_AUDIO_ID, "LTX-2.5 distilled I2V with audio (experimental)")
        if audio
        else (LTX25_ARM, LTX25_ID, "LTX-2.5 distilled I2V (experimental)")
    )
    return {
        "arm_id": arm_id,
        "label": label,
        "backend": "video_workflow",
        "form": {
            "workflow_id": workflow_id,
            "workflow_version": LTX25_VERSION,
            "frame_count": LTX25_FRAMES,
            "experimental_opt_in": True,
        },
    }


def _suite(
    suite_id: str,
    description: str,
    seed: int,
    cases: Sequence[Mapping[str, Any]],
    *,
    audio: bool = False,
) -> dict[str, Any]:
    arm = _arm(audio)
    return {
        "schema": base.SUITE_SCHEMA,
        "suite_id": suite_id,
        "description": description,
        "seed": seed,
        "baseline_arm": arm["arm_id"],
        "cases": [dict(case) for case in cases],
        "arms": [arm],
    }


def build_suites(
    stage1_source: Mapping[str, Any], stage2_source: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """The four LTX-2.5 suites from the frozen VID-CAND-382 stage 1 suite and either stage 2 suite.

    Cases are copied unchanged.  The smoke suite uses two *different* cases, because two identical jobs let ComfyUI
    return a cached result and the second then measures nothing.
    """

    stage1 = list(stage1_source["cases"])
    stage2 = list(stage2_source["cases"])
    if len(stage1) < AUDIO_CASES:
        raise ValueError(f"the stage 1 source has fewer than {AUDIO_CASES} cases")
    smoke = [
        {**stage1[0], "case_id": "s0_cold", "tags": ["smoke", "cold"]},
        {**stage1[1], "case_id": "s0_warm", "tags": ["smoke", "warm"]},
    ]
    audio = [
        {**case, "prompt": f"{case['prompt']}{AUDIO_PROMPT_SUFFIX}"}
        for case in stage1[:AUDIO_CASES]
    ]
    return {
        "stage0": _suite(
            "vidcandltx25-stage0",
            "VID-CAND-LTX25 stage 0: silent smoke, one cold and one warm job on two different cases.",
            STAGE0_SEED,
            smoke,
        ),
        "stage1": _suite(
            "vidcandltx25-stage1",
            "VID-CAND-LTX25 stage 1: the VID-CAND-382 stage 1 cases under LTX-2.5 silent.",
            stage1_source["seed"],
            stage1,
        ),
        "stage2": _suite(
            "vidcandltx25-stage2",
            "VID-CAND-LTX25 stage 2: the VID-CAND-382 stage 2 hard cases under LTX-2.5 silent.",
            stage2_source["seed"],
            stage2,
        ),
        "audio": _suite(
            "vidcandltx25-audio",
            "VID-CAND-LTX25 audio: the first stage 1 cases with a fixed sound sentence, audio workflow.",
            stage1_source["seed"],
            audio,
            audio=True,
        ),
    }


def freeze_plan(
    suites: Mapping[str, Mapping[str, Any]],
    suite_bytes: Mapping[str, bytes],
    *,
    base_commit: str,
    source_digests: Mapping[str, str],
) -> dict[str, Any]:
    """Suite digests, the VID-CAND-382 sources they came from, rules, thresholds, stop rules and budget."""

    entries = {
        key: {
            "file": SUITE_FILES[key],
            "sha256": base.file_sha256(suite_bytes[key]),
            "seed": suite["seed"],
            "arms": [
                [
                    arm["arm_id"],
                    arm["form"]["workflow_id"],
                    arm["form"]["workflow_version"],
                    arm["form"]["frame_count"],
                ]
                for arm in suite["arms"]
            ],
            "jobs": len(suite["cases"]) * len(suite["arms"]),
        }
        for key, suite in suites.items()
    }
    return {
        "schema": PLAN_SCHEMA,
        "task": TASK,
        "base_commit": base_commit,
        "source_suites_sha256": dict(source_digests),
        "suites": entries,
        "fairness_rules": list(FAIRNESS_RULES),
        "thresholds": THRESHOLDS,
        "stop_rules": list(STOP_RULES),
        "budget": BUDGET,
        "required_runtime": {
            "comfyui": "managed 0.38.0 (v0.38.0-py313)",
            "launch_flag": "--disable-pinned-memory",
        },
        "authorization": "none issued: the owner approves the physical run plan and this digest before any GPU job",
        "evidence_freeze": "suites, seeds, arms, thresholds and stop rules are fixed once authorized; any change is a "
        "new plan and digest",
    }


__all__ = [
    "AUDIO_PROMPT_SUFFIX",
    "BUDGET",
    "FAIRNESS_RULES",
    "LTX25_ARM",
    "LTX25_AUDIO_ARM",
    "PLAN_FILE",
    "SUITE_FILES",
    "THRESHOLDS",
    "build_suites",
    "freeze_plan",
]
