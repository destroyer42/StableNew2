"""VID-CAND-382 frozen evaluation design: suite builders, written thresholds and the plan digest.

Pure data and functions; nothing here reads a private file, touches a runtime, queues a job or writes outside the
path the caller passes.  ``python -m tools.qualification.vid_cand382 build`` feeds the owner's private cases through
these builders.  The design follows VID-CLIP-371 (``docs/Subsystems/Video/PR-VID-CLIP-371_Three_Engine_Eval.md``) with the
three changes the A14B result called for: equal clip duration at native frame rates, a Hunyuan step-count arm pair, and a
blind pairwise preference in stage 2 because the A14B ratings saturated at 5/5.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

PLAN_SCHEMA = "stablenew.vid-cand-382-plan.v1"
SUITE_SCHEMA = "stablenew.video-eval-suite.v1"
TASK = "VID-CAND-382"

A14B_ID = "wan22_i2v_a14b_4step_v1"
A14B_VERSION = "1.0.0"
HUNYUAN_8_ID = "hunyuan_video15_i2v_480p_8step_v1"
HUNYUAN_12_ID = "hunyuan_video15_i2v_480p_12step_v1"
HUNYUAN_VERSION = "1.0.0"

A14B_FRAMES = 81  # 81 frames at 16 fps = 5.06 s
HUNYUAN_FRAMES = 121  # 121 frames at 24 fps = 5.04 s
SEEDS = {"stage0": 382, "stage1": 371, "stage2": 372}
A14B_ARM = "a14b_base"
HUNYUAN_8_ARM = "hy15_8step"
HUNYUAN_12_ARM = "hy15_12step"
#: Hard ceiling of one eval run (``src/video/video_eval_suite.py::MAX_EVAL_JOBS``).
MAX_EVAL_JOBS = 64
#: ``suite_id`` and ``case_id`` share the loader's identifier pattern; the suite file names are the plan's keys.
SUITE_FILES = {
    "stage0": "20261125_vidcand382_stage0_smoke_v001.suite.json",
    "stage1": "20261125_vidcand382_stage1_head_to_head_v001.suite.json",
    "stage2_hy8": "20261125_vidcand382_stage2_hard_cases_hy8_v001.suite.json",
    "stage2_hy12": "20261125_vidcand382_stage2_hard_cases_hy12_v001.suite.json",
}

#: The structured prompt frame of VID-CLIP-371 stage 2, so a new hard case reads like the cases A14B was rated on.
FRAME_SUFFIX = (
    "Static locked-off camera with no camera shake, no zoom, no pan. Same woman, same face, same clothing and "
    "same background throughout, sharp consistent detail."
)
#: The three new stage-2 actions the hand-off asks for; each is applied to one full-body source of the owner's choice.
NEW_HARD_ACTIONS = (
    (
        "hands",
        "hands_interact",
        "clasps her hands together at her waist, then raises both hands to adjust her hair",
    ),
    (
        "twostep",
        "two_step",
        "takes two steps forward, stops, then turns her head to look over her shoulder",
    ),
    (
        "fastturn",
        "fast_turn",
        "turns quickly all the way around in place, then faces the camera again",
    ),
)

FAIRNESS_RULES = (
    "Equal clip duration at native frame rates: A14B 81 frames at 16 fps (5.06 s) against Hunyuan 121 frames at 24 fps "
    "(5.04 s). RIFE smoothing is OFF for every arm; nothing else resamples a clip.",
    "Identical source images (SHA-256 pinned), identical prompts and negative prompts, one seed per stage, one "
    "prompt-directed input contract (source image, prompt, negative prompt, seed, frozen geometry, frozen length).",
    "Matched resolution class: A14B runs 480x832 portrait, Hunyuan its native 480x848 (multiples of 16); Hunyuan "
    "carries 1.9 % more pixels per frame and the report states it.",
    "Hunyuan sampler: 8 steps in every stage; 12 steps in stage 1 as a second arm; stage 2 runs only the arm the owner "
    "names after stage 1 (two pre-frozen suites, one digest each).",
    "Arms run arm-major (the eval kit builds every case of one arm, then the next). The warm hold keys on workflow id "
    "and version, so the first job of each arm is a cold start and later jobs are warm; speed is compared warm to warm "
    "and cold to cold from the job repository, never across an arm change.",
    "Ratings are the owner's, blind to nothing in stage 1 and blind pairwise in stage 2 (arm order shuffled with a "
    "recorded seed). An agent never fills ratings.csv or pairwise.csv.",
    "No settings change after a resource failure within a frozen plan; a change is a new plan and digest.",
)

THRESHOLDS: dict[str, Any] = {
    "no_go": {
        "any_allocation_failure_or_oom_at_the_frozen_envelope": True,
        "host_commit_fraction_at_or_above": 0.95,
        "stage1_action_achieved_cases_below": 6,
        "action_achieved_definition": "requested_action in (achieved, partially_achieved), as in VID-CLIP-371",
        "critical_identity_breaks_above": 1,
        "mean_source_fidelity_below": 4.0,
        "mean_subject_stability_below": 4.0,
        "material_regression": {
            "dimensions": ["source_fidelity_1_to_5", "subject_stability_1_to_5"],
            "points_at_least": 2,
            "or": "a critical identity break the A14B clip of the same case does not have",
            "cases_at_least": 2,
        },
    },
    "as_good_or_better": {
        "requires": "no NO-GO condition",
        "stage1_mean_gap_at_most": 0.25,
        "stage1_dimensions": ["source_fidelity_1_to_5", "subject_stability_1_to_5", "action_score"],
        "action_score": "achieved 1.0, partially_achieved 0.5, not_achieved 0.0 (case mean)",
        "stage2_blind_pairwise_preference_at_least": 0.5,
        "pairwise_ties": "split evenly",
    },
    "faster": {
        "warm_wall_time_median_ratio_at_most": 0.8,
        "ratio": "Hunyuan warm job wall-time median / A14B warm job wall-time median, same host session",
        "wall_time_source": "job repository started_at to completed_at",
    },
    "recommendation_values": [
        "keep A14B",
        "add Hunyuan as approved alternate (owner decision)",
        "candidate for default (owner decision)",
    ],
    "recommendation_note": (
        "The last two are owner decisions (VIDEO_PIPELINE section 13 and 1.1); the analysis reports a verdict, "
        "never a promotion."
    ),
}

STOP_RULES = (
    "device loss, allocation failure or any automatic retry ends the run; keep evidence, do not retry",
    "host commit fraction >= 0.97, available RAM < 0.25 GiB or commit headroom < 1 GiB ends the run "
    "(WAN-BENCH-373 telemetry rules)",
    "an arm that cannot be admitted: stop and report, do not change a spec or the suite arms",
)

BUDGET = {
    "stage0_jobs": 2,
    "stage1_jobs": 24,
    "stage2_jobs_per_candidate_suite": 16,
    "stage2_runs": 1,
    "max_generations": 42,
    "overall_cap": 60,
    "auto_retry": False,
}


def _arm(
    arm_id: str, label: str, workflow_id: str, version: str, frames: int, *, opt_in: bool
) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": workflow_id,
        "workflow_version": version,
        "frame_count": frames,
    }
    if opt_in:
        form["experimental_opt_in"] = True
    return {"arm_id": arm_id, "label": label, "backend": "video_workflow", "form": form}


def a14b_arm() -> dict[str, Any]:
    return _arm(
        A14B_ARM,
        "I2V-A14B 4-step 1.0.0 (approved baseline)",
        A14B_ID,
        A14B_VERSION,
        A14B_FRAMES,
        opt_in=False,
    )


def hunyuan_arm(steps: int) -> dict[str, Any]:
    arm_id, workflow_id = (
        (HUNYUAN_8_ARM, HUNYUAN_8_ID) if steps == 8 else (HUNYUAN_12_ARM, HUNYUAN_12_ID)
    )
    return _arm(
        arm_id,
        f"HunyuanVideo 1.5 480p I2V {steps}-step (experimental)",
        workflow_id,
        HUNYUAN_VERSION,
        HUNYUAN_FRAMES,
        opt_in=True,
    )


def _suite(
    suite_id: str,
    description: str,
    seed: int,
    baseline_arm: str,
    cases: Sequence[Mapping[str, Any]],
    arms: list[dict[str, Any]],
) -> dict[str, Any]:
    document = {
        "schema": SUITE_SCHEMA,
        "suite_id": suite_id,
        "description": description,
        "seed": seed,
        "baseline_arm": baseline_arm,
        "cases": [dict(case) for case in cases],
        "arms": arms,
    }
    if len(cases) * len(arms) > MAX_EVAL_JOBS:
        raise ValueError(
            f"{suite_id}: {len(cases) * len(arms)} jobs exceed the eval kit's {MAX_EVAL_JOBS}"
        )
    return document


def build_stage0(case: Mapping[str, Any]) -> dict[str, Any]:
    """Two jobs of one case under Hunyuan 8-step: the first is the cold start, the second the warm run."""

    cold = {**case, "case_id": "s0_cold", "tags": ["smoke", "cold"]}
    warm = {**case, "case_id": "s0_warm", "tags": ["smoke", "warm"]}
    return _suite(
        "vidcand382-stage0",
        "VID-CAND-382 stage 0: Hunyuan 8-step smoke, one case run twice (cold then warm) to prove it loads, "
        "completes and stays inside the VRAM and commit envelope, and to set the readiness floor.",
        SEEDS["stage0"],
        HUNYUAN_8_ARM,
        [cold, warm],
        [hunyuan_arm(8)],
    )


def build_stage1(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The eight CLIP-371 structured cases under A14B 1.0.0, Hunyuan 8-step and Hunyuan 12-step: 24 jobs."""

    return _suite(
        "vidcand382-stage1",
        "VID-CAND-382 stage 1: the eight VID-CLIP-371 cases (same images, same structured prompts, seed 371) under "
        "A14B 1.0.0, Hunyuan 8-step and Hunyuan 12-step.",
        SEEDS["stage1"],
        A14B_ARM,
        cases,
        [a14b_arm(), hunyuan_arm(8), hunyuan_arm(12)],
    )


def build_stage2(cases: Sequence[Mapping[str, Any]], hunyuan_steps: int) -> dict[str, Any]:
    """Eight harder cases under A14B 1.0.0 and the one Hunyuan arm the owner names after stage 1: 16 jobs."""

    return _suite(
        f"vidcand382-stage2-hy{hunyuan_steps}",
        f"VID-CAND-382 stage 2: eight harder full-body cases (seed 372) under A14B 1.0.0 and Hunyuan {hunyuan_steps}-step, "
        "for the blind pairwise preference.",
        SEEDS["stage2"],
        A14B_ARM,
        cases,
        [a14b_arm(), hunyuan_arm(hunyuan_steps)],
    )


def hard_case_prompt(action: str) -> str:
    return f"The woman in the image {action}, smooth continuous motion at a steady natural pace. {FRAME_SUFFIX}"


#: The negative prompt VID-CLIP-371 used for every structured case (no effect at CFG 1; kept so the inputs are identical).
STRUCTURED_NEGATIVE = (
    "camera shake, handheld, jitter, flicker, shaky footage, blurry, low quality, distorted face, "
    "deformed hands, extra limbs, morphing, changing clothes, watermark, text"
)
EXAMPLE_FILES = {
    "stage0": "video_eval_hunyuan15_stage0_smoke.suite.json",
    "stage1": "video_eval_hunyuan15_stage1_head_to_head.suite.json",
    "stage2": "video_eval_hunyuan15_stage2_hard_cases.suite.json",
}


def _neutral(action: str) -> str:
    return re.sub(r"\bher\b", "their", action)


#: (case id, synthetic image, action) for the eight VID-CLIP-371 motion classes, written for a neutral subject.
_EXAMPLE_STAGE1 = (
    ("head_turn_smile", "closeup_portrait", "turns their head toward the camera and smiles"),
    ("walk_toward", "fullbody_portrait", "walks slowly toward the camera"),
    ("wave", "halfbody_portrait", "raises their right hand and waves"),
    ("sway", "halfbody_portrait", "sways gently from side to side"),
    ("laugh_hair_toss", "closeup_portrait", "laughs and tosses their hair back"),
    ("turn_in_place", "fullbody_portrait", "turns around slowly in place"),
    ("single_step", "fullbody_portrait", "takes one small step forward"),
    ("gaze_shift", "closeup_portrait", "looks down, then slowly lifts their gaze to the camera"),
)
_EXAMPLE_STAGE2 = (
    ("walk_toward", "fullbody_portrait", "walks slowly toward the camera"),
    ("turn_in_place", "fullbody_portrait", "turns around slowly in place"),
    ("hands_interact", "fullbody_portrait", _neutral(NEW_HARD_ACTIONS[0][2])),
    ("two_step", "fullbody_portrait", _neutral(NEW_HARD_ACTIONS[1][2])),
    ("wave", "fullbody_portrait", "raises their right hand and waves"),
    ("fast_turn", "fullbody_landscape", NEW_HARD_ACTIONS[2][2]),
    ("weight_shift", "fullbody_portrait", "shifts their weight from one foot to the other"),
    (
        "walk_aside_glance",
        "fullbody_landscape",
        "walks slowly to the side, then glances back at the camera",
    ),
)


def _example_cases(
    table: Sequence[tuple[str, str, str]], tags: Sequence[str]
) -> list[dict[str, Any]]:
    suffix = FRAME_SUFFIX.replace("the woman", "the person").replace(
        "Same woman, same face", "Same person, same face"
    )
    return [
        {
            "case_id": case_id,
            "image": f"images/synthetic_{image}.png",
            "prompt": f"The person in the image {action}, smooth continuous motion at a steady natural pace. {suffix}",
            "negative_prompt": STRUCTURED_NEGATIVE,
            "tags": [*tags, case_id],
        }
        for case_id, image, action in table
    ]


def example_suites() -> dict[str, dict[str, Any]]:
    """Shareable suites with synthetic image names and no private path; the owner binds real sources in the editor."""

    stage1 = _example_cases(_EXAMPLE_STAGE1, ["structured"])
    stage2 = _example_cases(_EXAMPLE_STAGE2, ["structured", "hard"])
    return {
        "stage0": build_stage0(stage1[0]),
        "stage1": build_stage1(stage1),
        "stage2": build_stage2(stage2, 8),
    }


def canonical_json(document: Mapping[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def plan_digest(plan: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON, as ``freeze_v6.py`` of VID-CLIP-371 computed it."""

    return hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def freeze_plan(
    suites: Mapping[str, Mapping[str, Any]],
    suite_bytes: Mapping[str, bytes],
    *,
    base_commit: str,
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The frozen plan: suite digests, cases by image hash, fairness rules, thresholds, stop rules, budget.

    ``cases`` carry only ``case_id``, ``motion_class`` and ``image_sha256`` (no path, no prompt), so a plan can be
    quoted without a private file.  Any change to a suite, seed, arm or threshold is a new plan and digest.
    """

    entries: dict[str, Any] = {}
    for key, suite in suites.items():
        entries[key] = {
            "file": SUITE_FILES[key],
            "sha256": file_sha256(suite_bytes[key]),
            "seed": suite["seed"],
            "baseline_arm": suite["baseline_arm"],
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
    return {
        "schema": PLAN_SCHEMA,
        "task": TASK,
        "base_commit": base_commit,
        "suites": entries,
        "cases": [dict(case) for case in cases],
        "fairness_rules": list(FAIRNESS_RULES),
        "thresholds": THRESHOLDS,
        "stop_rules": list(STOP_RULES),
        "budget": BUDGET,
        "required_runtime": {
            "comfyui": "managed 0.38.0 (v0.38.0-py313)",
            "launch_flag": "--disable-pinned-memory",
        },
        "authorization": (
            "none issued: each physical stage needs the owner's typed RUN <digest12> against this plan's digest "
            "(docs/runbooks/qual_system_840.md section 2 or the eval-kit equivalent the owner names); an agent never "
            "issues it"
        ),
        "evidence_freeze": (
            "suites, image hashes, seeds, arms, thresholds and stop rules are fixed once authorized; any change is a "
            "new plan and digest"
        ),
    }


__all__ = [
    "A14B_ARM",
    "BUDGET",
    "EXAMPLE_FILES",
    "FAIRNESS_RULES",
    "HUNYUAN_8_ARM",
    "HUNYUAN_12_ARM",
    "MAX_EVAL_JOBS",
    "NEW_HARD_ACTIONS",
    "PLAN_SCHEMA",
    "SEEDS",
    "STOP_RULES",
    "STRUCTURED_NEGATIVE",
    "SUITE_FILES",
    "THRESHOLDS",
    "a14b_arm",
    "build_stage0",
    "build_stage1",
    "build_stage2",
    "canonical_json",
    "example_suites",
    "freeze_plan",
    "hard_case_prompt",
    "hunyuan_arm",
    "plan_digest",
]
