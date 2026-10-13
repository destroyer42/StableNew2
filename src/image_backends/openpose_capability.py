"""Target eligibility for OpenPose ControlNet conditioning (PR-IMG-CNET-210).

One pure answer to "may *this* selected checkpoint on *this* backend run an OpenPose conditioned base generation?",
derived entirely from the canonical ``ModelPolicy`` (the one capability authority: its family, evidence and exact-profile
reference) and the configured backend identity. The editor shows it, the compiler enforces it and the backend re-checks
it; none of them keeps its own rule.

It is deliberately a *projection over* ``ModelPolicy``, not a new ``ModelPolicy`` feature: the generic ``controlnet``
feature stays unsupported everywhere (Model Comparison and the exact profiles key off it), and the persisted policy
contract that frozen Learning studies compare against is unchanged.

It never claims more than the contract: only an SDXL-family checkpoint on the Forge backend at the base txt2img stage is
``supported``. Exact qualified profiles (Klein, Z-Image), A1111, identified non-SDXL families and every other stage are
``unsupported``; a checkpoint StableNew has not identified is only ``unverified`` and is never executable. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.image_backends.image_backend_types import FORGE_IMAGE_BACKEND_ID
from src.image_backends.model_policy import (
    EVIDENCE_CONFLICTING,
    FAMILY_SDXL,
    FAMILY_UNKNOWN,
    STAGE_TXT2IMG,
    ModelPolicy,
)

#: Name of this contract (a capability *projection*; not a ``ModelPolicy`` feature - see the module docstring).
FEATURE = "controlnet_openpose"

STATUS_SUPPORTED = "supported"
STATUS_UNVERIFIED = "unverified"
STATUS_UNSUPPORTED = "unsupported"

REASON_SUPPORTED = "supported"
REASON_STAGE = "stage"
REASON_EXACT_PROFILE = "exact_profile"
REASON_BACKEND = "backend"
REASON_FAMILY = "family"
REASON_UNVERIFIED = "unverified_family"
REASON_CONFLICT = "conflicting_evidence"


@dataclass(frozen=True, slots=True)
class OpenPoseTarget:
    status: str
    reason: str
    #: Operator-facing, content-free sentence (names the target and what to do, never a path or image content).
    message: str
    family: str = ""
    evidence: str = ""

    @property
    def executable(self) -> bool:
        return self.status == STATUS_SUPPORTED

    @property
    def blocked(self) -> bool:
        return self.status == STATUS_UNSUPPORTED


def assess_openpose_target(
    policy: ModelPolicy, backend_id: str | None, *, stage: str = STAGE_TXT2IMG
) -> OpenPoseTarget:
    """Classify one resolved model policy + configured backend for OpenPose conditioning (pure)."""

    family, evidence = policy.family, policy.evidence

    def result(status: str, reason: str, message: str) -> OpenPoseTarget:
        return OpenPoseTarget(status, reason, message, family, evidence)

    if stage != STAGE_TXT2IMG:
        return result(
            STATUS_UNSUPPORTED,
            REASON_STAGE,
            "OpenPose conditioning applies to the base txt2img stage only.",
        )
    if policy.profile_ref is not None:
        return result(
            STATUS_UNSUPPORTED,
            REASON_EXACT_PROFILE,
            f"{policy.display_name} does not support ControlNet conditioning; select an SDXL checkpoint.",
        )
    if str(backend_id or "") != FORGE_IMAGE_BACKEND_ID:
        shown = str(backend_id or "unknown")
        return result(
            STATUS_UNSUPPORTED,
            REASON_BACKEND,
            f"OpenPose conditioning runs only on the Forge WebUI backend (the configured backend is '{shown}'). "
            "StableNew will not switch backends for you.",
        )
    if evidence == EVIDENCE_CONFLICTING:
        return result(
            STATUS_UNSUPPORTED,
            REASON_CONFLICT,
            "StableNew's records for this checkpoint name conflict, so it cannot be verified as SDXL; "
            "remove the duplicate checkpoint file or select an unambiguous SDXL checkpoint.",
        )
    if family == FAMILY_UNKNOWN:
        return result(
            STATUS_UNVERIFIED,
            REASON_UNVERIFIED,
            "StableNew has not identified this checkpoint as SDXL. Preview checks the checkpoint header; "
            "submission is refused unless it is confirmed as an SDXL base checkpoint.",
        )
    if family != FAMILY_SDXL:
        return result(
            STATUS_UNSUPPORTED,
            REASON_FAMILY,
            f"OpenPose conditioning is SDXL-only and this target is {policy.display_name}; select an SDXL checkpoint.",
        )
    return result(STATUS_SUPPORTED, REASON_SUPPORTED, "SDXL checkpoint on the Forge backend: supported.")


__all__ = [
    "FEATURE",
    "OpenPoseTarget",
    "REASON_BACKEND",
    "REASON_CONFLICT",
    "REASON_EXACT_PROFILE",
    "REASON_FAMILY",
    "REASON_STAGE",
    "REASON_SUPPORTED",
    "REASON_UNVERIFIED",
    "STATUS_SUPPORTED",
    "STATUS_UNSUPPORTED",
    "STATUS_UNVERIFIED",
    "assess_openpose_target",
]
