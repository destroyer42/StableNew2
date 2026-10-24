"""Built-in Research profiles: sourced starting values for the models StableNew can actually support (PR-IMG-PROFILE-630).

Read-only reference data. Every value names where it came from and in which of the four source classes:
official model recommendation, StableNew-tested configuration, inferred/community suggestion, or unverified. A value
with no source is not listed; it is declared unavailable. Exact-model values are *derived from* the immutable
executable profiles (``forge_klein_profile`` / ``forge_zimage_profile``) so the recommendation cannot drift from what the
compiler and backend will enforce; a test pins the agreement. The executable policy stays final.

Only SDXL (registry-verified family), FLUX.2 Klein 4B FP8 and Z-Image-Turbo FP8 have entries. A checkpoint of any other
family, or one the registry cannot classify, gets no Research profile: a file appearing in a models folder is not
evidence of capability.

Sources were read on 2026-10-24: the Hugging Face model cards of black-forest-labs/FLUX.2-klein-4B (page updated
2026-02-24), Tongyi-MAI/Z-Image-Turbo (updated 2026-01-30) and stabilityai/stable-diffusion-xl-base-1.0, and section 2.3
of the SDXL report (arXiv 2307.01952). No model was downloaded and no generation was run.
"""

from __future__ import annotations

from src.generation_profiles.contract import (
    IDENTITY_EXACT,
    IDENTITY_FAMILY,
    KIND_RESEARCH,
    SOURCE_OFFICIAL,
    SOURCE_STABLENEW_TESTED,
    EvidenceNote,
    GenerationProfile,
    ModelIdentity,
)
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_ID, latest_klein_profile
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1
from src.image_backends.model_policy import FAMILY_FLUX2_KLEIN, FAMILY_SDXL

REVIEWED_ON = "2026-10-24"
RESEARCH_REVISION = 1

KLEIN_RESEARCH_ID = "research-flux2_klein_4b_fp8"
ZIMAGE_RESEARCH_ID = "research-z_image_turbo_fp8_scaled"
SDXL_RESEARCH_ID = "research-sdxl-family"

_UNAVAILABLE_SDXL = (
    "The SDXL base-1.0 model card and report give no standalone-base value for this, and StableNew has not frozen "
    "or run a qualification for one."
)


def _klein() -> GenerationProfile:
    profile = latest_klein_profile()
    return GenerationProfile(
        profile_id=KLEIN_RESEARCH_ID,
        revision=RESEARCH_REVISION,
        kind=KIND_RESEARCH,
        name="FLUX.2 Klein 4B FP8 - research",
        model=ModelIdentity(
            kind=IDENTITY_EXACT,
            key=f"exact:{KLEIN_PROFILE_ID}",
            family=FAMILY_FLUX2_KLEIN,
            display_name=profile.display_name,
            exact_profile={"id": profile.profile_id},
        ),
        settings={
            "sampler_name": profile.sampler,
            "scheduler": profile.scheduler,
            "steps": profile.steps,
            "cfg_scale": profile.cfg_scale,
            "width": 1024,
            "height": 1024,
            "vae": "",
        },
        evidence=(
            EvidenceNote(
                fields=("steps", "cfg_scale", "width", "height"),
                source_class=SOURCE_OFFICIAL,
                citation="FLUX.2 [klein] 4B model card, Diffusers example (1024x1024, guidance_scale 1.0, 4 steps)",
                reference="https://huggingface.co/black-forest-labs/FLUX.2-klein-4B",
                reviewed_on=REVIEWED_ON,
                rationale="The publisher's own example for the distilled model; StableNew's exact profile fixes the same steps and CFG.",
            ),
            EvidenceNote(
                fields=("sampler_name", "scheduler", "vae"),
                source_class=SOURCE_STABLENEW_TESTED,
                citation="StableNew exact profile flux2_klein_4b_fp8 (physical qualification PR-IMG-115)",
                reference="docs/Subsystems/Image/PR-IMG-115_FLUX2_Klein_4B_FP8_Target_Hardware_Qualification.md",
                reviewed_on=REVIEWED_ON,
                rationale="The model card does not name a Forge sampler or scheduler; Euler/Beta and the profile-owned VAE are the qualified, fixed values.",
            ),
        ),
        executable_profile=dict(profile.reference()),
        provenance={"owner": "stablenew"},
        created_at=REVIEWED_ON,
    )


def _zimage() -> GenerationProfile:
    profile = ZIMAGE_PROFILE_V1
    return GenerationProfile(
        profile_id=ZIMAGE_RESEARCH_ID,
        revision=RESEARCH_REVISION,
        kind=KIND_RESEARCH,
        name="Z-Image-Turbo FP8 - research",
        model=ModelIdentity(
            kind=IDENTITY_EXACT,
            key=f"exact:{profile.profile_id}",
            family="z_image",
            display_name=profile.display_name,
            exact_profile={"id": profile.profile_id},
        ),
        settings={
            "sampler_name": profile.sampler,
            "scheduler": profile.scheduler,
            "steps": profile.steps,
            "cfg_scale": profile.cfg_scale,
            "width": 1024,
            "height": 1024,
            "vae": "",
        },
        evidence=(
            EvidenceNote(
                fields=("steps", "width", "height"),
                source_class=SOURCE_OFFICIAL,
                citation="Z-Image-Turbo model card, Diffusers example (1024x1024, num_inference_steps 9 = 8 forward passes)",
                reference="https://huggingface.co/Tongyi-MAI/Z-Image-Turbo",
                reviewed_on=REVIEWED_ON,
                rationale="The publisher's example; StableNew's exact profile fixes the same 9 steps and 1024x1024.",
            ),
            EvidenceNote(
                fields=("sampler_name", "scheduler", "cfg_scale", "vae"),
                source_class=SOURCE_STABLENEW_TESTED,
                citation="StableNew exact profile z_image_turbo_fp8_scaled v1 (limited support)",
                reference="docs/Subsystems/Image/PR-IMG-MODELS-155_ZImage_Turbo_FP8_Forge_Enablement.md",
                reviewed_on=REVIEWED_ON,
                rationale=(
                    "The card says guidance 0 for Diffusers; the managed Forge runtime takes CFG 1.0 with a distilled "
                    "scale. Euler/Beta come from the profile. One generation was observed and physical qualification is "
                    "inconclusive, so this is a configured value, not a qualified one."
                ),
            ),
        ),
        executable_profile=dict(profile.reference()),
        provenance={"owner": "stablenew"},
        created_at=REVIEWED_ON,
    )


def _sdxl() -> GenerationProfile:
    return GenerationProfile(
        profile_id=SDXL_RESEARCH_ID,
        revision=RESEARCH_REVISION,
        kind=KIND_RESEARCH,
        name="SDXL (registry-verified) - research",
        model=ModelIdentity(
            kind=IDENTITY_FAMILY,
            key=f"family:{FAMILY_SDXL}",
            family=FAMILY_SDXL,
            display_name="SDXL",
        ),
        settings={"width": 1024, "height": 1024},
        unavailable={
            "sampler_name": _UNAVAILABLE_SDXL,
            "scheduler": _UNAVAILABLE_SDXL,
            "steps": _UNAVAILABLE_SDXL,
            "cfg_scale": _UNAVAILABLE_SDXL,
            "vae": "Fine-tuned SDXL checkpoints differ on whether they need a separate VAE; keep the checkpoint's own.",
        },
        evidence=(
            EvidenceNote(
                fields=("width", "height"),
                source_class=SOURCE_OFFICIAL,
                citation="SDXL report section 2.3 (pixel count kept near 1024x1024); SDXL base-1.0 model card",
                reference="https://arxiv.org/abs/2307.01952",
                reviewed_on=REVIEWED_ON,
                rationale="The base model was fine-tuned on aspect-ratio buckets of about one megapixel; 1024x1024 is the square starting size.",
            ),
        ),
        provenance={"owner": "stablenew"},
        created_at=REVIEWED_ON,
    )


def research_profiles() -> tuple[GenerationProfile, ...]:
    """Every built-in Research profile (rebuilt from the executable profiles on each call; nothing is cached or written)."""

    return (_sdxl(), _klein(), _zimage())


__all__ = [
    "KLEIN_RESEARCH_ID",
    "RESEARCH_REVISION",
    "SDXL_RESEARCH_ID",
    "ZIMAGE_RESEARCH_ID",
    "research_profiles",
]
