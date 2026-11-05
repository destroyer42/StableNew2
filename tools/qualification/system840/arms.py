"""The qualification arms (IMG-Q0..Q4, VID-Q0..Q5, AI-Q0..Q3): lane, evidence class, dependencies and standing holds.

An arm is a unit of owner authorization.  Lanes never mix inside one session: GPU arms run one at a time and never beside
CPU inference (AI Assist and Smart Review are CPU lanes that obey the generation conflict/yield policy), so no combined
stress test is manufactured.  Standing holds are owner decisions recorded in ``STATUS.md``.  The per-target holds below are structural (Z-Image, A14B,
Comfy still images); holds that depend on the host (the AI protected-capture hold) live in the ledger as capability status
HOLD, so clearing one is an owner-accepted ledger edit, never a code change.  An arm that stays held is a truthful campaign
outcome, not an orchestrator failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.qualification.system840.statuses import EvidenceKind

LANE_FORGE = "gpu_forge"  # external or managed Forge/A1111 over its API
LANE_COMFY = "gpu_comfy"  # managed Comfy, owned and released by the production process manager
LANE_NATIVE = "gpu_native_svd"  # native SVD XT inside the application process
LANE_AI_CPU = "cpu_ai_assist"  # Offline AI Assist: CPU-only, per-model security contract
LANE_VISION_CPU = (
    "cpu_smart_review"  # SAM 2.1 / Florence-2 CPU child under the verified memory limit
)
LANE_OFFLINE = "offline_cpu"  # no inference at all (import, conversion inventory, readiness)

GPU_LANES = frozenset({LANE_FORGE, LANE_COMFY, LANE_NATIVE})
CPU_INFERENCE_LANES = frozenset({LANE_AI_CPU, LANE_VISION_CPU})

STAGE_CANARY = "canary"
STAGE_COVERAGE = "coverage"
STAGES = (STAGE_CANARY, STAGE_COVERAGE)

PRODUCTION = EvidenceKind.PRODUCTION_WORKFLOW
STANDALONE = EvidenceKind.STANDALONE_FEASIBILITY


@dataclass(frozen=True)
class Hold:
    """A standing reason an arm (or one of its targets) cannot be planned as executable."""

    hold_id: str
    reason: str
    source: str  # repository path that records the hold
    clears_when: str
    targets: tuple[str, ...] = ()  # capability ids the hold applies to; empty means the whole arm


@dataclass(frozen=True)
class ArmDef:
    arm_id: str
    title: str
    domain: str  # image | video | ai
    lane: str
    physical: bool
    evidence_class: EvidenceKind
    summary: str
    depends_on: tuple[str, ...] = ()
    #: One authorization never covers two groups; the AI arms use one group per candidate model.
    authorization_group: str = ""
    holds: tuple[Hold, ...] = field(default_factory=tuple)

    @property
    def gpu(self) -> bool:
        return self.lane in GPU_LANES

    @property
    def needs_vram_limit(self) -> bool:
        return self.gpu


_Z_IMAGE_HOLD = Hold(
    "HOLD-ZIMAGE-STABILITY",
    "Z-Image-Turbo clean shutdown and repeated-run stability are unresolved; no repeat physical attempt is authorized.",
    "STATUS.md",
    "a new exact owner decision",
    ("IMG-Q1.zimage-turbo-fp8",),
)
_COMFY_IMAGE_HOLD = Hold(
    "HOLD-COMFY-STILL-IMAGE",
    "Forge-vs-Comfy still-image qualification is offline only (CONDITIONAL / INCONCLUSIVE); a Comfy image slice needs "
    "resource and fault clearance and is not implemented here.",
    "STATUS.md",
    "an owner decision to build a Comfy image slice, with its own package",
    ("IMG-Q4.forge-vs-comfy-still",),
)
_A14B_HOLD = Hold(
    "HOLD-A14B-NEW-BUDGET",
    "Wan A14B stays INCONCLUSIVE: teardown and worker-process memory evidence defects are unresolved and the "
    "three-attempt authorization is exhausted.",
    "tools/qualification/README.md",
    "the harness proves teardown and process-tree memory, and the owner grants a new exact budget",
    ("VID-Q4.wan-a14b-480p",),
)
ARMS: tuple[ArmDef, ...] = (
    ArmDef(
        "IMG-Q0",
        "Baseline SDXL / Forge",
        "image",
        LANE_FORGE,
        True,
        PRODUCTION,
        "Normal PromptPack -> model/profile -> Preview -> Queue -> History round trip; the base for matched comparisons.",
        authorization_group="forge-sdxl",
    ),
    ArmDef(
        "IMG-Q1",
        "Installed model families",
        "image",
        LANE_FORGE,
        True,
        PRODUCTION,
        "Each installed, registered, eligible family individually (SDXL, Klein 4B FP8; Z-Image only after its hold).",
        depends_on=("IMG-Q0",),
        authorization_group="forge-families",
        holds=(_Z_IMAGE_HOLD,),
    ),
    ArmDef(
        "IMG-Q2",
        "Refinement and conditioning",
        "image",
        LANE_FORGE,
        True,
        PRODUCTION,
        "Matched source/seed studies: ADetailer face and hands, upscaling, ControlNet OpenPose/Canny/Depth.",
        depends_on=("IMG-Q0",),
        authorization_group="forge-refine",
    ),
    ArmDef(
        "IMG-Q3",
        "Image editing",
        "image",
        LANE_FORGE,
        True,
        PRODUCTION,
        "Masked inpaint, outpaint, Regenerate with Changes, Compare with Parent, original-pixel preservation, replay.",
        depends_on=("IMG-Q0",),
        authorization_group="forge-edit",
    ),
    ArmDef(
        "IMG-Q4",
        "Conditional backends and held models",
        "image",
        LANE_OFFLINE,
        False,
        EvidenceKind.OFFLINE_CONTRACT,
        "Read-only feasibility assessments and explicit NO-GO classifications; nothing is executed.",
        holds=(_COMFY_IMAGE_HOLD, _Z_IMAGE_HOLD),
    ),
    ArmDef(
        "VID-Q0",
        "Approved Wan TI2V",
        "video",
        LANE_COMFY,
        True,
        PRODUCTION,
        "Reuse accepted production evidence; a limited regression canary only where the exact conditions differ.",
        authorization_group="comfy-wan-ti2v",
    ),
    ArmDef(
        "VID-Q1",
        "Native SVD XT",
        "video",
        LANE_NATIVE,
        True,
        PRODUCTION,
        "Minimal native SVD clip, then optional smoothing/export variation separately; never downloads a model.",
        authorization_group="native-svd",
    ),
    ArmDef(
        "VID-Q2",
        "Motion Library and Fun Control",
        "video",
        LANE_COMFY,
        True,
        STANDALONE,
        "Offline import/conversion/preview/source identity, then corrected-source-prep and visual transfer by driver type.",
        authorization_group="comfy-fun-control",
    ),
    ArmDef(
        "VID-Q3",
        "Wan-Animate-2",
        "video",
        LANE_COMFY,
        True,
        STANDALONE,
        "Accepted historical evidence is reused; only the missing representative-state resource/usability gap is planned.",
        authorization_group="comfy-wan-animate",
    ),
    ArmDef(
        "VID-Q4",
        "Wan A14B",
        "video",
        LANE_COMFY,
        True,
        STANDALONE,
        "Prior INCONCLUSIVE verdict preserved; no GPU time until teardown and worker-memory evidence defects are fixed.",
        authorization_group="comfy-wan-a14b",
        holds=(_A14B_HOLD,),
    ),
    ArmDef(
        "VID-Q5",
        "Video integration",
        "video",
        LANE_COMFY,
        True,
        PRODUCTION,
        "Make Video, admission, playback/History, Movie Clips, Storyboard, two-shot sequence, eval kit and ratings.",
        depends_on=("VID-Q0",),
        authorization_group="comfy-integration",
    ),
    ArmDef(
        "AI-Q0",
        "AI security and compatibility readiness",
        "ai",
        LANE_OFFLINE,
        False,
        EvidenceKind.OFFLINE_CONTRACT,
        "Read-only readiness: model/runtime SHA-256, licence, protected interpreter, offline command, ETW canary, budgets.",
    ),
    ArmDef(
        "AI-Q1",
        "AI Assist real inference",
        "ai",
        LANE_AI_CPU,
        True,
        STANDALONE,
        "The frozen corpus and bounded candidate arms on CPU; one separate authorization per candidate model.",
        depends_on=("AI-Q0",),
        authorization_group="ai-per-model",
    ),
    ArmDef(
        "AI-Q2",
        "AI Assist product integration",
        "ai",
        LANE_AI_CPU,
        True,
        PRODUCTION,
        "Prompt-tab Suggest -> Review -> explicit Accept, only after a qualified runtime and a separate enablement decision.",
        depends_on=("AI-Q1",),
        authorization_group="ai-integration",
    ),
    ArmDef(
        "AI-Q3",
        "Smart Review (SAM 2.1, Florence-2)",
        "ai",
        LANE_VISION_CPU,
        True,
        STANDALONE,
        "Point/box selection and caption suggestions on a fixed reference set; distinct from Offline AI Assist.",
        authorization_group="smart-review",
    ),
)

ARM_BY_ID = {arm.arm_id: arm for arm in ARMS}


def get_arm(arm_id: str) -> ArmDef:
    try:
        return ARM_BY_ID[arm_id]
    except KeyError:
        raise KeyError(f"unknown arm {arm_id!r}; known: {', '.join(ARM_BY_ID)}") from None


def execution_order(arm_ids: list[str] | tuple[str, ...]) -> list[str]:
    """Dependencies first, then registry order.  A dependency outside the selection is allowed (it needs accepted evidence)."""

    selected = set(arm_ids)
    ordered: list[str] = []

    def visit(arm_id: str) -> None:
        if arm_id in ordered:
            return
        for dependency in get_arm(arm_id).depends_on:
            if dependency in selected:
                visit(dependency)
        ordered.append(arm_id)

    for arm in ARMS:
        if arm.arm_id in selected:
            visit(arm.arm_id)
    unknown = selected - set(ARM_BY_ID)
    if unknown:
        raise KeyError(f"unknown arm(s): {', '.join(sorted(unknown))}")
    return ordered


def lane_class(lane: str) -> str:
    """``gpu``, ``cpu_inference`` or ``offline``: the classes a session may not mix."""

    if lane in GPU_LANES:
        return "gpu"
    if lane in CPU_INFERENCE_LANES:
        return "cpu_inference"
    return "offline"
