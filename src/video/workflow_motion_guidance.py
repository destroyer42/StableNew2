"""Display-only, evidence-grounded motion guidance for a Video Workflow (PR-VID-196).

A pure projection of a registered ``WorkflowSpec``: it is neither a catalog field nor part of any
versioned workflow specification, it receives no prompt text, and it returns nothing the compiler,
builder or backend reads.  The operator's prompts are therefore structurally unreachable from here
(they are never edited, appended to, normalised or replaced).

Which guidance applies is decided from what the spec declares -- its workflow family, whether it
binds a driving video, and the operator controls it actually exposes -- never from a display name:

1. ``wan22_prompt_directed`` -- Wan2.2 TI2V-5B, motion described only by the prompt;
2. ``wan_animate2_prompt`` -- Wan-Animate-2 without a driving video;
3. ``wan_animate2_driving_video`` -- Wan-Animate-2 transferring a driving clip's motion.

Anything else yields an explicit unsupported state.  Every statement carries a basis so a verified
runtime fact, a declared behaviour, a single-sample test result and an untested area are never
mistaken for one another.  Test results come from accepted PR-VID-150 (Wan2.2 prompt motion) and
PR-VID-192 (Animate-2 control truth) evidence and are quoted with their sample limits.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from src.video.motion_source_readiness import driving_frame_consumption
from src.video.workflow_controls import operator_controls

MODE_WAN22_PROMPT = "wan22_prompt_directed"
MODE_ANIMATE2_PROMPT = "wan_animate2_prompt"
MODE_ANIMATE2_DRIVING = "wan_animate2_driving_video"
MODE_UNSUPPORTED = "unsupported"

BASIS_RUNTIME = "runtime"  # read from the pinned runtime's source
BASIS_DECLARED = "declared"  # what this workflow's catalog entry declares
BASIS_TESTED = "tested"  # observed in an accepted qualification run (a single sample)
BASIS_UNRESOLVED = "unresolved"  # tested, and the requested behaviour was not delivered
BASIS_UNTESTED = "untested"  # no accepted evidence characterises it

TOPIC_SUBJECT = "subject_motion"
TOPIC_CAMERA = "camera_motion"
TOPIC_IDENTITY = "identity_background"

_EV_150 = "docs/Subsystems/Video/PR-VID-150_Wan22_Motion_Characterization.md"
_EV_192 = "docs/Subsystems/Video/PR-VID-192_Animate2_Control_Truth.md"

PROMPT_POLICY = (
    "This guidance is display-only. StableNew never edits, appends to or replaces your prompt."
)


@dataclass(frozen=True, slots=True)
class GuidancePoint:
    text: str
    basis: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidanceTopic:
    key: str
    title: str
    points: tuple[GuidancePoint, ...]


@dataclass(frozen=True, slots=True)
class TestedWording:
    """A prompt that was actually run, shown verbatim for reference (never inserted anywhere)."""

    label: str
    text: str
    outcome: str
    evidence: str


@dataclass(frozen=True, slots=True)
class MotionGuidance:
    mode: str
    supported: bool
    title: str
    summary: str
    topics: tuple[GuidanceTopic, ...]
    tested_wording: tuple[TestedWording, ...]
    limitations: tuple[str, ...]
    prompt_policy: str = PROMPT_POLICY


def _declared_names(spec: Any) -> set[str]:
    return set(getattr(spec, "declared_input_names", ()) or ())


def _control_names(spec: Any) -> set[str]:
    return {str(control["name"]) for control in operator_controls(spec)}


def guidance_mode(spec: Any) -> str:
    """Classify a spec from what it declares; unknown shapes are unsupported."""

    defaults = getattr(spec, "backend_defaults", None) or {}
    family = str(defaults.get("workflow_family") or "")
    has_driving = "pose_video" in _declared_names(spec)
    if family == "wan22" and not has_driving:
        return MODE_WAN22_PROMPT
    if family == "wan_animate2":
        return MODE_ANIMATE2_DRIVING if has_driving else MODE_ANIMATE2_PROMPT
    return MODE_UNSUPPORTED


def _unsupported() -> MotionGuidance:
    return MotionGuidance(
        mode=MODE_UNSUPPORTED,
        supported=False,
        title="No motion guidance for this workflow",
        summary=(
            "StableNew has no accepted evidence about how this workflow responds to motion "
            "wording, so no guidance is shown. Generation is not affected."
        ),
        topics=(),
        tested_wording=(),
        limitations=(),
    )


def _wan22_guidance(spec: Any) -> MotionGuidance:
    camera_declared = "camera_preset" in _declared_names(spec)
    camera_control = (
        GuidancePoint("A camera preset control is declared for this workflow.", BASIS_DECLARED)
        if camera_declared
        else GuidancePoint(
            "No camera control is declared; camera behaviour is influenced by the prompt only.",
            BASIS_DECLARED,
        )
    )
    return MotionGuidance(
        mode=MODE_WAN22_PROMPT,
        supported=True,
        title="Wan2.2 TI2V-5B: prompt-directed motion",
        summary=(
            "Motion is described only by the prompt. The source image fixes the starting frame; "
            "there is no driving video and no pose control."
        ),
        topics=(
            GuidanceTopic(
                TOPIC_SUBJECT,
                "Subject motion",
                (
                    GuidancePoint(
                        "A single local gesture is the tested strength: a structured, sequential "
                        "prompt (camera locked, stay in place, raise the arm, wave, lower it) gave "
                        "clearly more arm motion and smoother output than a one-line request, on "
                        "one source and one seed.",
                        BASIS_TESTED,
                        (f"{_EV_150} (Run B vs Run A)",),
                    ),
                    GuidancePoint(
                        "Walking or stepping was not delivered: a prompt asking for two forward "
                        "steps left the feet planted while the arms and torso moved. This is one "
                        "source, seed and wording, so it is unresolved rather than ruled out.",
                        BASIS_UNRESOLVED,
                        (f"{_EV_150} (Run C)",),
                    ),
                    GuidancePoint(
                        "Vigorous limb motion showed blur or deformation on the moving limb "
                        "(the hand during the wave, the forearm during the arm swing).",
                        BASIS_TESTED,
                        (f"{_EV_150} (Runs B and C)",),
                    ),
                ),
            ),
            GuidanceTopic(
                TOPIC_CAMERA,
                "Camera motion",
                (
                    camera_control,
                    GuidancePoint(
                        "The camera stayed static in all three tested runs, including the "
                        "one-line prompt that said nothing about the camera, so the effect of "
                        "'camera locked' wording was not isolated. Requesting camera movement was "
                        "not tested.",
                        BASIS_TESTED,
                        (f"{_EV_150} (Runs A to C)",),
                    ),
                ),
            ),
            GuidanceTopic(
                TOPIC_IDENTITY,
                "Identity and background",
                (
                    GuidancePoint(
                        "Face and clothing stayed recognisable in the tested clips.",
                        BASIS_TESTED,
                        (f"{_EV_150} (rubric, Runs A to C)",),
                    ),
                    GuidancePoint(
                        "An unrequested colour and lighting cast appeared in the second half of "
                        "all three clips regardless of prompt structure; it was recorded, not "
                        "diagnosed.",
                        BASIS_TESTED,
                        (f"{_EV_150} (Limitations)",),
                    ),
                ),
            ),
        ),
        tested_wording=(
            TestedWording(
                "One-line gesture",
                "The person raises their right hand and waves.",
                "Plain raise and wave; smaller motion.",
                f"{_EV_150} (Run A)",
            ),
            TestedWording(
                "Structured gesture",
                "Camera locked. The person stays in place, raises their right arm from their "
                "side to shoulder height, waves twice, then lowers the arm. The head follows the "
                "hand slightly. Natural shoulder, arm, clothing and hair movement. No zoom, pan, "
                "orbit or scene change.",
                "More arm motion and smoother output than the one-line wording; minor hand blur.",
                f"{_EV_150} (Run B)",
            ),
            TestedWording(
                "Structured locomotion",
                "Camera locked. The person takes two deliberate steps forward with natural "
                "weight transfer and opposing arm swing, then stops. Keep the same person, face, "
                "clothing and scene. No zoom, pan, orbit or scene change.",
                "No stepping occurred; feet stayed planted while the arms swung.",
                f"{_EV_150} (Run C)",
            ),
        ),
        limitations=(
            "Evidence is one source image, one seed and one run per wording; results are "
            "relative comparisons, not a statistical study.",
            "Other sources, seeds and wording have not been characterised.",
        ),
    )


def _animate2_prompt_guidance(spec: Any) -> MotionGuidance:
    controls = _control_names(spec)
    identity: list[GuidancePoint] = []
    if "reference_image_strength" in controls:
        identity.append(
            GuidancePoint(
                "Reference Image Strength is a real model input (1.0 is the trained behaviour): "
                "below 1.0 loosens appearance adherence, above 1.0 tightens it. Its effect in "
                "this mode has not been tested.",
                BASIS_DECLARED,
                (f"{_EV_192} (section 2)",),
            )
        )
    else:
        identity.append(
            GuidancePoint(
                "This workflow version exposes no reference-strength control.", BASIS_DECLARED
            )
        )
    identity.append(
        GuidancePoint(
            "The negative prompt has no effect in this graph (CFG 1.0), so it cannot be used to "
            "suppress unwanted content.",
            BASIS_RUNTIME,
            (f"{_EV_192} (section 5)",),
        )
    )
    return MotionGuidance(
        mode=MODE_ANIMATE2_PROMPT,
        supported=True,
        title="Wan-Animate-2: reference image and prompt (no driving video)",
        summary=(
            "Without a driving video the model's pose branch is skipped, so motion comes only "
            "from the text prompt and is typically subtle. This mode is exploratory; the model is "
            "built around a driving video."
        ),
        topics=(
            GuidanceTopic(
                TOPIC_SUBJECT,
                "Subject motion",
                (
                    GuidancePoint(
                        "With no driving video the pose branch is skipped, so a motion prompt, "
                        "pose strength and pose window have nothing to act on.",
                        BASIS_RUNTIME,
                        (f"{_EV_192} (section 2)",),
                    ),
                    GuidancePoint(
                        "No accepted evidence characterises how much, or what kind of, motion a "
                        "prompt produces in this mode; gestures and walking are both unverified.",
                        BASIS_UNTESTED,
                    ),
                ),
            ),
            GuidanceTopic(
                TOPIC_CAMERA,
                "Camera motion",
                (
                    GuidancePoint(
                        "No camera control is declared, and camera behaviour in this mode has not "
                        "been characterised.",
                        BASIS_UNTESTED,
                    ),
                ),
            ),
            GuidanceTopic(TOPIC_IDENTITY, "Identity and background", tuple(identity)),
        ),
        tested_wording=(),
        limitations=(
            "This mode was not part of the Animate-2 qualification; it is exposed so it can be "
            "evaluated.",
        ),
    )


def _animate2_driving_guidance(spec: Any) -> MotionGuidance:
    controls = _control_names(spec)
    consumption = driving_frame_consumption(spec)
    subject: list[GuidancePoint] = [
        GuidancePoint(
            consumption.rule
            if consumption.verified
            else "Which driving frames are used, and any frame-rate conversion, are not verified "
            "for this workflow's runtime revision, so no timing relationship is claimed.",
            BASIS_RUNTIME if consumption.verified else BASIS_UNTESTED,
            (f"{_EV_192} (section 2)",) if consumption.verified else (),
        )
    ]
    if "pose_prompt" in controls:
        subject.append(
            GuidancePoint(
                "The Motion Prompt feeds the pose branch and should describe only the motion; "
                "leaving it empty reuses the appearance and background prompt.",
                BASIS_DECLARED,
                (f"{_EV_192} (sections 2 and 4)",),
            )
        )
    else:
        subject.append(
            GuidancePoint(
                "This workflow version has no separate Motion Prompt: the pose branch reuses the "
                "main prompt.",
                BASIS_DECLARED,
                (f"{_EV_192} (section 1)",),
            )
        )
    subject.extend(
        (
            GuidancePoint(
                "On one source, one clip and one seed, the baseline without a separate motion "
                "prompt showed a duplicate subject in 28 of 39 frames; adding the Motion Prompt "
                "removed it. With it, a single forearm raise appeared (marginally larger at pose "
                "strength 1.5), as a qualitative reading, not an owner verdict.",
                BASIS_TESTED,
                (f"{_EV_192} (section 8)",),
            ),
            GuidancePoint(
                "The clip's high-knee run with lateral travel was not delivered on a single "
                "subject in any tested arm, and raising pose strength did not restore it. Walking, "
                "running and travel are unresolved.",
                BASIS_UNRESOLVED,
                (f"{_EV_192} (section 8)",),
            ),
        )
    )
    identity: list[GuidancePoint] = [
        GuidancePoint(
            "Separating the motion prompt did not degrade the histogram identity proxy "
            "(0.967 to 0.979), a weak signal rather than identity proof.",
            BASIS_TESTED,
            (f"{_EV_192} (section 8)",),
        )
    ]
    if "reference_image_strength" in controls:
        identity.append(
            GuidancePoint(
                "Reference Image Strength 1.3 (one arm) reduced motion (motion area 0.068 to "
                "0.036) without improving the identity proxy (0.979 to 0.905).",
                BASIS_TESTED,
                (f"{_EV_192} (section 8)",),
            )
        )
    identity.append(
        GuidancePoint(
            "The negative prompt has no effect in this graph (CFG 1.0), so unwanted background "
            "content cannot be suppressed with it.",
            BASIS_RUNTIME,
            (f"{_EV_192} (section 5)",),
        )
    )
    return MotionGuidance(
        mode=MODE_ANIMATE2_DRIVING,
        supported=True,
        title="Wan-Animate-2: driving-video motion",
        summary=(
            "Body motion is transferred from the driving video; the prompt describes appearance "
            "and background. The clip, not the prompt, decides what moves."
        ),
        topics=(
            GuidanceTopic(TOPIC_SUBJECT, "Subject motion", tuple(subject)),
            GuidanceTopic(
                TOPIC_CAMERA,
                "Camera motion",
                (
                    GuidancePoint(
                        "No camera control is declared. The graph centre-crops the clip to the "
                        "prepared frame size before conditioning, so the clip's framing decides "
                        "what is visible.",
                        BASIS_DECLARED,
                    ),
                    GuidancePoint(
                        "Whether camera movement in the driving clip is reproduced has not been "
                        "characterised.",
                        BASIS_UNTESTED,
                    ),
                ),
            ),
            GuidanceTopic(TOPIC_IDENTITY, "Identity and background", tuple(identity)),
        ),
        tested_wording=(),
        limitations=(
            "Evidence is one reference image, one driving clip, one seed, 41 frames at 480x832; "
            "the clips were read qualitatively and the owner's verdict on those arms is not "
            "recorded in the evidence.",
            "The local motion corpus has no legitimate source for a side step, an in-place turn, "
            "a squat or a moderate-speed walk, so those motions are uncharacterised.",
        ),
    )


def motion_guidance(spec: Any) -> MotionGuidance:
    """The guidance for ``spec`` (an explicit unsupported state when none applies)."""

    mode = guidance_mode(spec)
    if mode == MODE_WAN22_PROMPT:
        return _wan22_guidance(spec)
    if mode == MODE_ANIMATE2_PROMPT:
        return _animate2_prompt_guidance(spec)
    if mode == MODE_ANIMATE2_DRIVING:
        return _animate2_driving_guidance(spec)
    return _unsupported()


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def motion_readiness_projection(spec: Any) -> dict[str, Any]:
    """Everything the readiness panel needs from a spec, as plain data (no prompt, no payload)."""

    defaults = getattr(spec, "backend_defaults", None) or {}
    policy = defaults.get("source_preparation")
    consumption = driving_frame_consumption(spec)
    return {
        "source_preparation": dict(policy) if isinstance(policy, Mapping) else None,
        "accepts_driving_video": "pose_video" in _declared_names(spec),
        "driving_frame_consumption": {
            "verified": consumption.verified,
            "reason": consumption.reason,
            "rule": consumption.rule,
            "runtime_revision": consumption.runtime_revision,
        },
        "guidance": _plain(asdict(motion_guidance(spec))),
    }


__all__ = [
    "BASIS_DECLARED",
    "BASIS_RUNTIME",
    "BASIS_TESTED",
    "BASIS_UNRESOLVED",
    "BASIS_UNTESTED",
    "MODE_ANIMATE2_DRIVING",
    "MODE_ANIMATE2_PROMPT",
    "MODE_UNSUPPORTED",
    "MODE_WAN22_PROMPT",
    "PROMPT_POLICY",
    "TOPIC_CAMERA",
    "TOPIC_IDENTITY",
    "TOPIC_SUBJECT",
    "GuidancePoint",
    "GuidanceTopic",
    "MotionGuidance",
    "TestedWording",
    "guidance_mode",
    "motion_guidance",
    "motion_readiness_projection",
]
